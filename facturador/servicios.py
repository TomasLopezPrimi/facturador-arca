"""Emisión individual de comprobantes C por WSFEv1."""

import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from zeep.exceptions import Fault

from facturador.almacenamiento import cargar_cuit_emisor, guardar_json_atomico
from facturador.arca.padron import consultar_datos_padron, ErrorConstanciaPadron
from facturador.arca.wsaa import obtener_credenciales_vigentes
from facturador.arca.wsfe import auth_wsfe, crear_cliente_wsfe, comprobar_errores
from facturador.constantes import CONDICIONES_IVA, TIPO_FACTURA, TIPO_NOTA_CREDITO
from facturador.detalle import items_del_comprobante
from facturador.documentos.pdf import generar_pdf
from facturador.rutas import BASE, CREDENTIALS_FILE, carpeta_datos
from facturador.validaciones import validar_cuit, validar_formulario


def estado_servicios(ambiente):
    nombre_ambiente = "homologacion" if ambiente == "testing" else "produccion"
    ruta_cert = BASE / "certificados" / ("certificado.pem" if ambiente == "testing" else "produccion/certificado.pem")
    ruta_clave = BASE / "certificados" / ("privada.key" if ambiente == "testing" else "produccion/privada.key")
    credenciales = {}
    if CREDENTIALS_FILE.exists():
        credenciales = json.loads(CREDENTIALS_FILE.read_text(encoding="utf-8"))
    lineas = [f"Certificado: {'presente' if ruta_cert.is_file() else 'FALTA'}", f"Clave privada: {'presente' if ruta_clave.is_file() else 'FALTA'}"]
    for servicio in ("wsfe", "ws_sr_constancia_inscripcion"):
        ticket = credenciales.get("services_by_environment", {}).get(nombre_ambiente, {}).get(servicio)
        if not ticket:
            ticket = credenciales.get("services", {}).get(servicio)
        if not ticket and credenciales.get("service") == servicio:
            ticket = credenciales
        if not ticket or ticket.get("environment") != nombre_ambiente:
            lineas.append(f"{servicio}: sin ticket guardado")
            continue
        try:
            vence = datetime.fromisoformat(ticket["expiration_time"].replace("Z", "+00:00"))
            vigente = vence.tzinfo is not None and vence > datetime.now(timezone.utc)
            fecha = vence.astimezone().strftime("%d/%m/%Y %H:%M") if vence.tzinfo else str(vence)
            lineas.append(f"{servicio}: {'vigente' if vigente else 'vencido'} · vence {fecha}")
        except (KeyError, ValueError):
            lineas.append(f"{servicio}: ticket inválido")
    return "\n".join(lineas)


def obtener_tickets(ambiente):
    for servicio in ("wsfe", "ws_sr_constancia_inscripcion"):
        obtener_credenciales_vigentes(servicio, ambiente)
    return estado_servicios(ambiente)


def consultar_padron_para_interfaz(cuit, ambiente, cuit_emisor=None):
    """Prioriza datos reales del padrón de producción aunque se emita en testing."""
    cuit_emisor = validar_cuit(cuit_emisor) if cuit_emisor else cargar_cuit_emisor()
    if ambiente == "produccion":
        return consultar_datos_padron(cuit, ambiente, cuit_representada=cuit_emisor)
    try:
        perfil = consultar_datos_padron(cuit, "produccion", cuit_representada=cuit_emisor)
        perfil["fuente"] = "ARCA padrón producción (datos reales, consulta durante homologación)"
        return perfil
    except ErrorConstanciaPadron:
        raise
    except Exception as error:
        problema_produccion = error
    try:
        perfil = consultar_datos_padron(cuit, "testing", cuit_representada=cuit_emisor)
    except Fault as error:
        if "No existe persona con ese Id" not in str(error):
            raise
        raise RuntimeError(
            "Ese CUIT no figura en el padrón de homologación. La consulta de datos reales "
            "requiere el certificado y el servicio de padrón habilitado en producción. "
            "Revisá la pestaña Certificados y tickets; mientras tanto podés cargar el domicilio manualmente."
        ) from problema_produccion
    perfil["fuente"] = "ARCA padrón homologación (datos de prueba)"
    return perfil


def ruta_pendiente(ambiente):
    return carpeta_datos(ambiente) / "solicitud_pendiente.json"


def consulta_autorizada(cliente, auth, tipo, punto, numero):
    respuesta = cliente.service.FECompConsultar(
        Auth=auth, FeCompConsReq={"CbteTipo": tipo, "PtoVta": punto, "CbteNro": numero}
    )
    resultado = getattr(respuesta, "ResultGet", None)
    if resultado and getattr(resultado, "CodAutorizacion", None):
        return resultado
    return None


def verificar_consulta(original, datos):
    if (Decimal(str(original.ImpTotal)) != Decimal(str(datos["importe"]))
            or str(original.DocNro) != str(datos["receptor"])
            or int(original.DocTipo) != int(datos["tipo_doc_receptor"])):
        raise RuntimeError("ARCA devuelve un comprobante distinto para ese número. Revisá la solicitud pendiente.")


def persistir_autorizado(datos, pendiente=None):
    carpeta = Path(datos["carpeta_salida"]) if datos.get("carpeta_salida") else carpeta_datos(datos["ambiente"])
    nombre = f"{datos['prefijo_archivo']}_C_{datos['punto']:05d}_{datos['numero']:08d}"
    ruta = carpeta / f"{nombre}.json"
    guardar_json_atomico(ruta, datos)
    pdf = generar_pdf(datos)
    if pendiente and pendiente.exists():
        pendiente.unlink()
    return pdf, ruta


def recuperar_pendiente(ambiente):
    pendiente = ruta_pendiente(ambiente)
    if not pendiente.exists():
        return "No hay solicitudes pendientes en este ambiente."
    datos = json.loads(pendiente.read_text(encoding="utf-8"))
    cliente = crear_cliente_wsfe(ambiente)
    original = consulta_autorizada(cliente, auth_wsfe(ambiente, datos["emisor"]), datos["tipo_comprobante"], datos["punto"], datos["numero"])
    if not original:
        return "ARCA todavía no informa un CAE. La solicitud queda pendiente; revisala antes de volver a emitir."
    verificar_consulta(original, datos)
    datos["cae"] = str(original.CodAutorizacion)
    datos["vencimiento"] = str(original.FchVto)
    pdf, _ = persistir_autorizado(datos, pendiente)
    return f"Comprobante recuperado. CAE {datos['cae']}\nPDF: {pdf}"


def preparar(formulario, config):
    datos = validar_formulario(formulario, config)
    ambiente = datos["ambiente"]
    cuit_emisor = datos["cuit_emisor"]
    if ruta_pendiente(ambiente).exists():
        raise RuntimeError("Hay una solicitud pendiente. Usá Recuperar antes de emitir otra.")
    cliente = crear_cliente_wsfe(ambiente)
    auth = auth_wsfe(ambiente, cuit_emisor)
    tipo_codigo = TIPO_FACTURA if datos["tipo"] == "Factura C" else TIPO_NOTA_CREDITO
    asociado = None
    if tipo_codigo == TIPO_NOTA_CREDITO:
        factura = consulta_autorizada(cliente, auth, TIPO_FACTURA, datos["original_punto"], datos["original_numero"])
        if not factura:
            raise ValueError("ARCA no encontró la Factura C original autorizada.")
        if int(factura.DocTipo) != datos["tipo_doc"] or str(factura.DocNro) != datos["receptor"]:
            raise ValueError("La factura original pertenece a otro receptor o documento.")
        if datos["importe"] > Decimal(str(factura.ImpTotal)):
            raise ValueError("La nota supera el importe de la factura original.")
        asociado = {
            "tipo": TIPO_FACTURA, "punto": datos["original_punto"],
            "numero": datos["original_numero"], "fecha": str(factura.CbteFch),
            "cuit": cuit_emisor, "importe_original": str(factura.ImpTotal),
        }
    try:
        emisor = consultar_datos_padron(cuit_emisor, ambiente, cuit_representada=cuit_emisor)
    except Fault as error:
        if ambiente != "testing" or "No existe persona con ese Id" not in str(error):
            raise
        emisor = {"cuit": cuit_emisor, "estado": "No disponible en padrón de homologación", "fuente": "Configuración local"}
    if datos["tipo_doc"] != 80:
        receptor = {
            "cuit": datos["receptor"], "nombre": datos["nombre_receptor"],
            "domicilio_comercial": datos["domicilio_receptor"],
            "tipo_documento": datos["documento_tipo"], "fuente": "Carga manual consumidor final",
        }
    else:
        try:
            receptor = consultar_datos_padron(datos["receptor"], ambiente, cuit_representada=cuit_emisor)
        except ErrorConstanciaPadron as error:
            if not error.permite_carga_manual:
                raise
            receptor = {
                "cuit": datos["receptor"],
                "nombre": datos["nombre_receptor"],
                "domicilio_comercial": datos["domicilio_receptor"],
                "tipo_documento": datos["documento_tipo"],
                "fuente": "Carga manual (ARCA no emitió la constancia)",
                "padron_verificado": False,
                "error_padron": str(error),
            }
        except Fault as error:
            if ambiente != "testing" or "No existe persona con ese Id" not in str(error):
                raise
            receptor = {
                "cuit": datos["receptor"], "nombre": datos["nombre_receptor"],
                "domicilio_comercial": datos["domicilio_receptor"],
                "tipo_documento": datos["documento_tipo"],
                "estado": "No disponible en padrón de homologación",
                "fuente": "Carga manual de prueba",
                "padron_verificado": False,
            }
    if ambiente == "produccion":
        perfiles = [("emisor", emisor)]
        if datos["tipo_doc"] == 80 and receptor.get("padron_verificado", True):
            perfiles.append(("receptor", receptor))
        for etiqueta, perfil in perfiles:
            if str(perfil.get("estado", "")).upper() not in ("ACTIVO", "ACTIVA"):
                raise RuntimeError(f"El {etiqueta} no figura activo en el padrón de producción.")
    ultimo = cliente.service.FECompUltimoAutorizado(Auth=auth, PtoVta=datos["punto"], CbteTipo=tipo_codigo)
    comprobar_errores(ultimo)
    numero = int(ultimo.CbteNro) + 1
    fecha = datos["fecha"]
    perfil_emisor = {
        **emisor, "nombre": config["nombre_emisor"],
        "domicilio_comercial": config["domicilio_emisor"],
        "condicion_iva": config["condicion_iva_emisor"],
        "ingresos_brutos": config["ingresos_brutos"],
        "inicio_actividades": config["inicio_actividades"],
    }
    receptor["domicilio_comercial"] = datos["domicilio_receptor"]
    registro = {
        "ambiente": ambiente,
        "etiqueta_ambiente": "PRODUCCIÓN" if ambiente == "produccion" else "HOMOLOGACIÓN",
        "emisor": int(cuit_emisor), "receptor": datos["receptor"],
        "carpeta_salida": str(carpeta_datos(ambiente) / cuit_emisor),
        "datos_emisor": perfil_emisor, "datos_receptor": receptor,
        "punto": datos["punto"], "numero": numero, "fecha": fecha,
        "importe": str(datos["importe"]), "descripcion": datos["descripcion"],
        "items": datos["items"],
        "concepto": datos["concepto"], "tipo_servicio": datos["tipo_servicio"],
        "condicion_venta": datos["condicion_venta"],
        "tipo_comprobante": tipo_codigo,
        "servicio_desde": datos["servicio_desde"],
        "servicio_hasta": datos["servicio_hasta"],
        "vencimiento_pago": datos["vencimiento_pago"],
        "nombre_comprobante": datos["tipo"],
        "prefijo_archivo": "factura" if tipo_codigo == TIPO_FACTURA else "nota_credito",
        "moneda": "PES", "cotizacion": 1, "tipo_doc_receptor": datos["tipo_doc"],
        "condicion_iva_receptor": CONDICIONES_IVA[datos["iva"]],
        "condicion_iva_receptor_nombre": datos["iva"],
        "comprobante_asociado": asociado,
    }
    return cliente, auth, registro


def solicitar(cliente, auth, datos):
    ambiente = datos["ambiente"]
    pendiente = ruta_pendiente(ambiente)
    if pendiente.exists():
        raise RuntimeError("Existe una solicitud pendiente. Recuperala primero.")
    if "items" in datos:
        items_del_comprobante(datos)
    importe = Decimal(datos["importe"])
    fecha = datos["fecha"]
    concepto = 1 if datos["concepto"] == "Productos" else 2
    detalle = {
        "Concepto": concepto, "DocTipo": datos["tipo_doc_receptor"], "DocNro": int(datos["receptor"]),
        "CbteDesde": datos["numero"], "CbteHasta": datos["numero"],
        "CbteFch": fecha, "ImpTotal": importe,
        "ImpTotConc": Decimal("0"), "ImpNeto": importe,
        "ImpOpEx": Decimal("0"), "ImpTrib": Decimal("0"), "ImpIVA": Decimal("0"),
        "MonId": "PES", "MonCotiz": 1,
        "CondicionIVAReceptorId": datos["condicion_iva_receptor"],
    }
    if concepto == 2:
        detalle.update({
            "FchServDesde": datos.get("servicio_desde", fecha),
            "FchServHasta": datos.get("servicio_hasta", fecha),
            "FchVtoPago": datos.get("vencimiento_pago") or fecha,
        })
    if datos["comprobante_asociado"]:
        asociado = datos["comprobante_asociado"]
        detalle["CbtesAsoc"] = {"CbteAsoc": [{
            "Tipo": TIPO_FACTURA, "PtoVta": asociado["punto"],
            "Nro": asociado["numero"], "Cuit": datos["emisor"],
            "CbteFch": asociado["fecha"],
        }]}
    solicitud = {
        "FeCabReq": {"CantReg": 1, "PtoVta": datos["punto"], "CbteTipo": datos["tipo_comprobante"]},
        "FeDetReq": {"FECAEDetRequest": [detalle]},
    }
    guardar_json_atomico(pendiente, datos)
    try:
        respuesta = cliente.service.FECAESolicitar(Auth=auth, FeCAEReq=solicitud)
    except Exception as error:
        # El servidor puede haber autorizado aunque la respuesta se haya perdido.
        try:
            resultado = consulta_autorizada(cliente, auth, datos["tipo_comprobante"], datos["punto"], datos["numero"])
        except Exception:
            resultado = None
        if not resultado:
            raise RuntimeError("No se pudo confirmar la respuesta de ARCA. La solicitud quedó pendiente; usá Recuperar.") from error
        verificar_consulta(resultado, datos)
        datos["cae"] = str(resultado.CodAutorizacion)
        datos["vencimiento"] = str(resultado.FchVto)
        return persistir_autorizado(datos, pendiente)
    try:
        comprobar_errores(respuesta)
        detalle_respuesta = respuesta.FeDetResp.FECAEDetResponse[0]
        if respuesta.FeCabResp.Resultado != "A" or detalle_respuesta.Resultado != "A" or not detalle_respuesta.CAE:
            observaciones = getattr(detalle_respuesta, "Observaciones", None)
            raise ValueError(f"ARCA rechazó el comprobante. {observaciones or ''}")
    except ValueError:
        pendiente.unlink(missing_ok=True)
        raise
    except Exception as error:
        raise RuntimeError("La respuesta de ARCA requiere revisión. La solicitud quedó pendiente.") from error
    datos["cae"] = str(detalle_respuesta.CAE)
    datos["vencimiento"] = str(detalle_respuesta.CAEFchVto)
    return persistir_autorizado(datos, pendiente)
