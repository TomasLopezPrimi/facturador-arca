
import json
import argparse
import base64
import ssl
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlencode

from zeep import Client
from zeep.exceptions import Fault
from zeep.transports import Transport
from requests.adapters import HTTPAdapter

from main import obtener_credenciales_vigentes

BASE = Path(__file__).resolve().parent

WSFE_WSDL = {"testing": "https://wswhomo.afip.gov.ar/wsfev1/service.asmx?WSDL", "produccion": "https://servicios1.afip.gov.ar/wsfev1/service.asmx?WSDL"}
PADRON_WSDL = {"testing": "https://awshomo.afip.gov.ar/sr-padron/webservices/personaServiceA5?WSDL", "produccion": "https://aws.arca.gob.ar/sr-padron/webservices/personaServiceA5?WSDL"}


class _CompatibilidadTlsArcaAdapter(HTTPAdapter):
    """Admite el DH débil del WSFE de producción sin desactivar TLS/verificación."""

    def __init__(self, ca_bundle):
        self.ca_bundle = ca_bundle
        super().__init__()

    def init_poolmanager(self, connections, maxsize, block=False, **pool_kwargs):
        context = ssl.create_default_context()
        context.load_verify_locations(cafile=self.ca_bundle)
        context.set_ciphers("DEFAULT:@SECLEVEL=1")
        pool_kwargs["ssl_context"] = context
        super().init_poolmanager(connections, maxsize, block=block, **pool_kwargs)


def crear_cliente_wsfe(ambiente):
    """Crea WSFE; limita el ajuste de TLS al host de producción de ARCA."""
    if ambiente not in WSFE_WSDL:
        raise ValueError(f"Ambiente WSFE desconocido: {ambiente}")

    if ambiente == "produccion":
        import requests

        session = requests.Session()
        session.mount(
            "https://servicios1.afip.gov.ar/",
            _CompatibilidadTlsArcaAdapter(requests.certs.where()),
        )
        return Client(WSFE_WSDL[ambiente], transport=Transport(session=session))

    return Client(WSFE_WSDL[ambiente])

TIPO_FACTURA = 11  # Factura C
TIPO_NOTA_CREDITO = 13  # Nota de Crédito C
URL_QR_ARCA = "https://www.arca.gob.ar/fe/qr/"
SERVICIO_PADRON = "ws_sr_constancia_inscripcion"


class ErrorConstanciaPadron(RuntimeError):
    """ARCA respondió que no puede emitir la constancia de esta CUIT."""

    def __init__(self, cuit, mensaje):
        self.cuit = str(cuit)
        self.mensaje_arca = str(mensaje)
        texto = self.mensaje_arca.casefold()
        self.permite_carga_manual = (
            "pendiente" in texto
            and ("requerimiento" in texto or "fiscalizacion" in texto or "fiscalización" in texto)
        )
        super().__init__(f"Error de padrón para CUIT {self.cuit}: {self.mensaje_arca}")


def consultar_datos_padron(cuit, ambiente, cuit_representada=None):
    """Consulta nombre y domicilio fiscal en el padrón del ambiente elegido."""
    if not cuit_representada:
        from facturador_core import cargar_cuit_emisor

        cuit_representada = cargar_cuit_emisor()
    cred = obtener_credenciales_vigentes(SERVICIO_PADRON, ambiente)
    cliente = Client(PADRON_WSDL[ambiente])
    respuesta = cliente.service.getPersona_v2(
        token=cred["token"],
        sign=cred["sign"],
        cuitRepresentada=int(cuit_representada),
        idPersona=int(cuit),
    )

    # Zeep puede desempaquetar el único elemento de respuesta directamente.
    persona = getattr(respuesta, "personaReturn", respuesta)

    error = getattr(persona, "errorConstancia", None)
    if error:
        mensaje = getattr(error, "error", None) or str(error)
        raise ErrorConstanciaPadron(cuit, mensaje)

    generales = getattr(persona, "datosGenerales", None)
    if generales is None:
        raise RuntimeError(f"El padrón no devolvió datos generales para CUIT {cuit}.")

    nombre = getattr(generales, "razonSocial", None)
    if not nombre:
        nombre = " ".join(
            parte for parte in (
                getattr(generales, "apellido", None),
                getattr(generales, "nombre", None),
            ) if parte
        )

    domicilio = getattr(generales, "domicilioFiscal", None)
    if domicilio is None:
        raise RuntimeError(f"El padrón no informó domicilio fiscal para CUIT {cuit}.")

    partes_domicilio = [
        getattr(domicilio, "direccion", None),
        getattr(domicilio, "datoAdicional", None),
        getattr(domicilio, "localidad", None),
        getattr(domicilio, "descripcionProvincia", None),
        getattr(domicilio, "codPostal", None),
    ]
    return {
        "cuit": str(cuit),
        "nombre": nombre or "Nombre no informado",
        "domicilio_fiscal": ", ".join(str(parte) for parte in partes_domicilio if parte),
        "estado": getattr(generales, "estadoClave", None),
        "tipo_persona": getattr(generales, "tipoPersona", None),
        "fuente": f"ARCA padrón {'homologación' if ambiente == 'testing' else 'producción'}",
    }


def obtener_datos_contribuyente(cuit, etiqueta, ambiente):
    try:
        return consultar_datos_padron(cuit, ambiente)
    except Fault as error:
        if "No existe persona con ese Id" not in str(error) or ambiente == "produccion":
            raise

        print(
            f"El CUIT {cuit} ({etiqueta}) no está cargado en el padrón de "
            "homologación; completá estos datos manualmente para la prueba."
        )
        nombre = input(f"Nombre o razón social del {etiqueta}: ").strip()
        domicilio = input(f"Domicilio fiscal del {etiqueta}: ").strip()
        if not nombre or not domicilio:
            raise ValueError("Nombre y domicilio son obligatorios para continuar.")

        return {
            "cuit": str(cuit),
            "nombre": nombre,
            "domicilio_fiscal": domicilio,
            "estado": "No consultado en padrón de homologación",
            "tipo_persona": None,
            "fuente": "Carga manual para homologación",
        }


def generar_url_qr(datos):
    """Arma el payload oficial del QR de factura electrónica (versión 1)."""
    fecha = str(datos["fecha"])
    if len(fecha) == 8 and fecha.isdigit():
        fecha = f"{fecha[:4]}-{fecha[4:6]}-{fecha[6:8]}"

    payload = {
        "ver": 1,
        "fecha": fecha,
        "cuit": int(datos["emisor"]),
        "ptoVta": int(datos["punto"]),
        "tipoCmp": int(datos.get("tipo_comprobante", TIPO_FACTURA)),
        "nroCmp": int(datos["numero"]),
        "importe": float(Decimal(str(datos["importe"]))),
        "moneda": datos.get("moneda", "PES"),
        "ctz": float(Decimal(str(datos.get("cotizacion", 1)))),
        "tipoDocRec": int(datos.get("tipo_doc_receptor", 80)),
        "nroDocRec": int(datos["receptor"]),
        "tipoCodAut": "E",
        "codAut": int(datos["cae"]),
    }
    contenido = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    codificado = base64.b64encode(contenido.encode("utf-8")).decode("ascii")
    return f"{URL_QR_ARCA}?{urlencode({'p': codificado})}"


def autenticar(ambiente):
    from facturador_core import cargar_cuit_emisor

    cuit_emisor = cargar_cuit_emisor()
    path = BASE / "credenciales.json"
    cred = json.loads(path.read_text(encoding="utf-8"))

    cred = cred.get("services", {}).get("wsfe", cred)
    if cred.get("environment") != ("homologacion" if ambiente == "testing" else "produccion"):
        raise ValueError("Entorno incorrecto")

    if cred.get("service") != "wsfe":
        raise ValueError("Credenciales de otro servicio")

    vencimiento = datetime.fromisoformat(
        cred["expiration_time"].replace("Z", "+00:00")
    )

    if vencimiento.tzinfo is None:
        raise ValueError("Vencimiento sin zona horaria")

    if datetime.now(timezone.utc) >= vencimiento:
        raise ValueError(
            "Credenciales vencidas. Ejecutá python main.py"
        )

    return {
        "Token": cred["token"],
        "Sign": cred["sign"],
        "Cuit": int(cuit_emisor),
    }


def comprobar_errores(respuesta):
    errores = getattr(respuesta, "Errors", None)
    if errores and errores.Err:
        for error in errores.Err:
            print(f"ARCA error {error.Code}: {error.Msg}")
        raise RuntimeError("ARCA devolvió errores")


def consultar_factura_original(client, auth, punto, numero, receptor):
    """Verifica por WSFE que exista una Factura C autorizada para el receptor."""
    respuesta = client.service.FECompConsultar(
        Auth=auth,
        FeCompConsReq={"CbteTipo": TIPO_FACTURA, "PtoVta": punto, "CbteNro": numero},
    )
    comprobar_errores(respuesta)
    original = getattr(respuesta, "ResultGet", None)
    if not original or not getattr(original, "CodAutorizacion", None):
        raise ValueError("ARCA no encontró una Factura C autorizada con esos datos.")
    if int(original.DocTipo) != 80 or str(original.DocNro) != str(receptor):
        raise ValueError("La factura original no corresponde al CUIT receptor indicado.")
    return original


def generar_pdf(datos):
    from facturador_pdf import generar_pdf as renderizar_pdf

    return renderizar_pdf(datos, generar_url_qr(datos))


def emitir_factura(ambiente):
    # La consola usa las mismas validaciones y persistencia que la aplicación.
    from facturador_core import (
        CONDICIONES_IVA, CONDICIONES_VENTA, cargar_config, preparar, solicitar,
    )
    from facturador_detalle import UNIDADES_MEDIDA, normalizar_items
    from facturador_pdf import numero_local

    if ambiente == "produccion":
        print("ATENCIÓN: vas a emitir comprobantes fiscales válidos en PRODUCCIÓN.")
        if input("Escribí EMITIR para continuar: ").strip() != "EMITIR":
            print("Operación cancelada")
            return
    opcion = input("Comprobante: 1. Factura C / 2. Nota de crédito C: ").strip()
    if opcion not in ("1", "2"):
        raise ValueError("Opción inválida")
    concepto = input("Operación: 1. Servicios / 2. Productos: ").strip()
    if concepto not in ("1", "2"):
        raise ValueError("Opción inválida")
    formulario = {
        "ambiente": ambiente,
        "tipo": "Factura C" if opcion == "1" else "Nota de crédito C",
        "concepto": "Servicios" if concepto == "1" else "Productos",
        "documento_tipo": "CUIT", "receptor": input("CUIT receptor: ").strip(),
        "nombre_receptor": input("Nombre o razón social del receptor: ").strip(),
        "domicilio_receptor": input("Domicilio comercial del receptor: ").strip(),
        "fecha": input("Fecha de emisión (DD/MM/AAAA, vacío = hoy): ").strip() or date.today().strftime("%d/%m/%Y"),
    }
    print("Condiciones IVA:", ", ".join(CONDICIONES_IVA))
    formulario["iva"] = input("Condición IVA del receptor: ").strip()
    print("Condiciones de venta:", ", ".join(CONDICIONES_VENTA))
    formulario["condicion_venta"] = input("Condición de venta (vacío = Transferencia Bancaria): ").strip() or "Transferencia Bancaria"
    if concepto == "1":
        formulario["servicio_desde"] = input("Servicio desde (DD/MM/AAAA): ").strip()
        formulario["servicio_hasta"] = input("Servicio hasta (DD/MM/AAAA): ").strip()
        formulario["vencimiento_pago"] = input("Vencimiento para el pago (DD/MM/AAAA): ").strip()
    if opcion == "2":
        formulario["original_punto"] = input("Punto de venta de la factura original: ").strip()
        formulario["original_numero"] = input("Número de la factura original: ").strip()
    items = []
    while True:
        descripcion = input("Descripción del producto o servicio: ").strip()
        print("Unidades:", ", ".join(UNIDADES_MEDIDA))
        unidad = "servicio" if concepto == "1" else "unidad"
        item = {
            "descripcion": descripcion, "codigo": input("Código (opcional): ").strip(),
            "cantidad": input("Cantidad (vacío = 1): ").strip() or "1",
            "unidad": input(f"Unidad (vacío = {unidad}): ").strip() or unidad,
            "precio_unitario": input("Precio unitario ($): ").strip(),
        }
        items.extend(normalizar_items([item]))
        if input("¿Agregar otro renglón? (s/N): ").strip().lower() != "s":
            break
    formulario["items"] = items
    cliente, auth, datos = preparar(formulario, cargar_config())
    print(f"{datos['nombre_comprobante']} {datos['punto']:05d}-{datos['numero']:08d}")
    print(f"Receptor: {datos['datos_receptor']['nombre']} - {datos['receptor']}")
    for item in datos["items"]:
        print(f"{item['descripcion']}: {item['cantidad']} {item['unidad']} x $ {numero_local(item['precio_unitario'])} = $ {numero_local(item['importe'])}")
    if concepto == "1":
        print("Vencimiento para el pago:", formulario["vencimiento_pago"])
    print("Importe total: $", numero_local(datos["importe"]))
    print("Ambiente:", ambiente.upper())
    if input("¿Solicitar CAE? (s/N): ").strip().lower() != "s":
        print("Operación cancelada")
        return
    pdf, registro = solicitar(cliente, auth, datos)
    print("CAE:", datos["cae"])
    print("PDF:", pdf)
    print("JSON:", registro)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Emisión de Factura C o Nota de Crédito C")
    parser.add_argument("--ambiente", choices=("testing", "produccion"), default="testing")
    args = parser.parse_args()
    emitir_factura(args.ambiente)







