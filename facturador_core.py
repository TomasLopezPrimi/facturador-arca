"""Emisión individual de comprobantes C por WSFEv1."""

import json
import os
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from zeep.exceptions import Fault

from emitir_factura import (
    BASE, TIPO_FACTURA, TIPO_NOTA_CREDITO, crear_cliente_wsfe,
    comprobar_errores, generar_pdf,
    consultar_datos_padron, ErrorConstanciaPadron,
)
from main import obtener_credenciales_vigentes, CREDENTIALS_FILE
from facturador_detalle import items_del_comprobante, normalizar_items, total_items


CONFIG_PATH = BASE / "config_facturador.json"
RECEPTORES_PATH = BASE / "receptores.json"
CONDICIONES_IVA = {
    "Responsable inscripto": 1,
    "Exento": 4,
    "Consumidor final": 5,
    "Monotributista": 6,
}
TIPO_SERVICIO = "620900 - SERVICIOS DE INFORMÁTICA N.C.P."
CONDICIONES_VENTA = (
    "Contado",
    "Tarjeta de Débito",
    "Tarjeta de Crédito",
    "Cuenta Corriente",
    "Cheque",
    "Transferencia Bancaria",
    "Otra",
    "Otros medios de pago electrónico",
)
LIMITE_CONSUMIDOR_SIN_DOCUMENTO = Decimal("10000000")


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


def guardar_json_atomico(ruta, datos):
    ruta.parent.mkdir(parents=True, exist_ok=True)
    temporal = ruta.with_name(ruta.name + ".tmp")
    with open(temporal, "w", encoding="utf-8") as archivo:
        json.dump(datos, archivo, ensure_ascii=False, indent=2, default=str)
        archivo.flush()
        os.fsync(archivo.fileno())
    os.replace(temporal, ruta)


def cargar_config():
    if not CONFIG_PATH.exists():
        return {}
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def cargar_cuit_emisor():
    config = cargar_config()
    if not config.get("cuit_emisor"):
        raise ValueError("Configurá y guardá tu CUIT emisor en Configuración antes de continuar.")
    return validar_cuit(config["cuit_emisor"])


def cargar_receptores():
    if not RECEPTORES_PATH.exists():
        return []
    receptores = json.loads(RECEPTORES_PATH.read_text(encoding="utf-8"))
    if not isinstance(receptores, list):
        raise ValueError("El archivo de receptores guardados no tiene un formato válido.")
    campos = ("id", "documento_tipo", "documento", "nombre", "domicilio", "iva")
    identificadores = set()
    for receptor in receptores:
        if not isinstance(receptor, dict) or any(campo not in receptor for campo in campos):
            raise ValueError("El archivo de receptores guardados no tiene un formato válido.")
        receptor["id"] = str(receptor["id"]).strip()
        if not receptor["id"] or receptor["id"] in identificadores:
            raise ValueError("El archivo de receptores guardados contiene identificadores inválidos.")
        identificadores.add(receptor["id"])
        for campo in campos[1:]:
            receptor[campo] = str(receptor[campo])
    return receptores


def guardar_receptores(receptores):
    guardar_json_atomico(RECEPTORES_PATH, receptores)


def validar_cuit(valor):
    cuit = "".join(caracter for caracter in str(valor) if caracter.isdigit())
    if len(cuit) != 11:
        raise ValueError("El CUIT debe tener 11 dígitos.")
    suma = sum(int(digito) * peso for digito, peso in zip(cuit[:10], (5, 4, 3, 2, 7, 6, 5, 4, 3, 2)))
    verificador = 11 - suma % 11
    if verificador == 11:
        verificador = 0
    elif verificador == 10:
        verificador = 9
    if verificador != int(cuit[-1]):
        raise ValueError("El CUIT tiene un dígito verificador incorrecto.")
    return cuit


def importe_decimal(valor):
    texto = str(valor).strip().replace(" ", "")
    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")
    try:
        importe = Decimal(texto)
    except InvalidOperation as error:
        raise ValueError("Ingresá un importe válido.") from error
    if not importe.is_finite() or importe <= 0 or importe != importe.quantize(Decimal("0.01")):
        raise ValueError("El importe debe ser positivo y tener hasta dos decimales.")
    return importe


def validar_formulario(formulario, config):
    cuit_emisor = validar_cuit(config.get("cuit_emisor", ""))
    ambiente = formulario["ambiente"]
    if ambiente not in ("testing", "produccion"):
        raise ValueError("Ambiente inválido.")
    tipo = formulario["tipo"]
    if tipo not in ("Factura C", "Nota de crédito C"):
        raise ValueError("Tipo de comprobante inválido.")
    condicion_venta = formulario.get("condicion_venta", "Transferencia Bancaria")
    if condicion_venta not in CONDICIONES_VENTA:
        raise ValueError("Seleccioná una condición de venta válida.")
    documento_tipo = formulario["documento_tipo"]
    documento = formulario["receptor"].strip()
    if documento_tipo == "CUIT":
        receptor = validar_cuit(documento)
        tipo_doc = 80
    elif documento_tipo == "DNI":
        if not documento.isdigit() or not 7 <= len(documento) <= 8:
            raise ValueError("Ingresá un DNI de 7 u 8 dígitos.")
        receptor = documento
        tipo_doc = 96
    elif documento_tipo == "Sin documento":
        receptor = "0"
        tipo_doc = 99
    else:
        raise ValueError("Seleccioná el tipo de documento del receptor.")
    nombre_receptor = formulario["nombre_receptor"].strip()
    domicilio_receptor = formulario["domicilio_receptor"].strip()
    if tipo_doc == 80 and (not nombre_receptor or not domicilio_receptor):
        raise ValueError("Completá el nombre y domicilio del receptor.")
    if tipo_doc != 80:
        nombre_receptor = nombre_receptor or "A CONSUMIDOR FINAL"
        domicilio_receptor = domicilio_receptor or "NR"
    if "items" in formulario:
        items = normalizar_items(formulario["items"])
        importe = total_items(items)
        descripcion = "\n".join(item["descripcion"] for item in items)
    else:
        importe = importe_decimal(formulario["importe"])
        descripcion = formulario["descripcion"].strip()
        unidad = "unidad" if formulario["concepto"] == "Productos" else "servicio"
        items = normalizar_items([{
            "descripcion": descripcion, "cantidad": "1", "unidad": unidad,
            "precio_unitario": str(importe),
        }])
    if tipo_doc == 99 and importe >= LIMITE_CONSUMIDOR_SIN_DOCUMENTO:
        raise ValueError("Desde $10.000.000, el consumidor final debe identificarse con DNI o CUIT.")
    if formulario["iva"] not in CONDICIONES_IVA:
        raise ValueError("Seleccioná la condición IVA del receptor.")
    if tipo_doc != 80 and formulario["iva"] != "Consumidor final":
        raise ValueError("Para DNI o sin documento, seleccioná IVA 'Consumidor final'.")
    concepto = formulario["concepto"]
    if concepto not in ("Productos", "Servicios"):
        raise ValueError("Seleccioná Productos o Servicios.")
    tipo_servicio = ""
    if concepto == "Servicios":
        tipo_servicio = formulario.get("tipo_servicio", TIPO_SERVICIO)
        if tipo_servicio != TIPO_SERVICIO:
            raise ValueError("Seleccioná el tipo de servicio 620900 - SERVICIOS DE INFORMÁTICA N.C.P.")
    try:
        fecha_comprobante = datetime.strptime(
            formulario.get("fecha", date.today().strftime("%d/%m/%Y")), "%d/%m/%Y"
        ).date()
        fecha_desde = datetime.strptime(
            formulario.get("servicio_desde", formulario.get("fecha", date.today().strftime("%d/%m/%Y"))), "%d/%m/%Y"
        ).date()
        fecha_hasta = datetime.strptime(
            formulario.get("servicio_hasta", formulario.get("fecha", date.today().strftime("%d/%m/%Y"))), "%d/%m/%Y"
        ).date()
        vencimiento_pago = None
        if concepto == "Servicios":
            vencimiento_pago = datetime.strptime(
                formulario.get("vencimiento_pago", fecha_comprobante.strftime("%d/%m/%Y")), "%d/%m/%Y"
            ).date()
    except ValueError as error:
        raise ValueError("Ingresá fechas válidas con formato DD/MM/AAAA.") from error
    if fecha_comprobante > date.today():
        raise ValueError("La fecha del comprobante no puede ser futura.")
    if concepto == "Servicios" and fecha_hasta < fecha_desde:
        raise ValueError("La fecha hasta del servicio no puede ser anterior a la fecha desde.")
    if vencimiento_pago and vencimiento_pago < fecha_comprobante:
        raise ValueError("El vencimiento para el pago no puede ser anterior a la fecha del comprobante.")
    try:
        punto = int(config["punto_venta"])
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("Configurá el punto de venta de Web Services.") from error
    if not 1 <= punto <= 99998:
        raise ValueError("Punto de venta inválido.")
    for campo in ("nombre_emisor", "domicilio_emisor", "condicion_iva_emisor", "ingresos_brutos", "inicio_actividades"):
        if not str(config.get(campo, "")).strip():
            raise ValueError(f"Completá {campo.replace('_', ' ')} en Configuración.")
    try:
        inicio = datetime.strptime(config["inicio_actividades"], "%d/%m/%Y").date()
        if inicio > date.today():
            raise ValueError
    except ValueError as error:
        raise ValueError("Inicio de actividades: elegí una fecha válida que no sea futura.") from error
    if tipo == "Nota de crédito C":
        try:
            original_punto = int(formulario["original_punto"])
            original_numero = int(formulario["original_numero"])
        except ValueError as error:
            raise ValueError("Indicá punto de venta y número de la factura original.") from error
        if not (1 <= original_punto <= 99998 and 1 <= original_numero <= 99999999):
            raise ValueError("La factura original tiene un número inválido.")
    else:
        original_punto = original_numero = None
    return {
        "ambiente": ambiente, "tipo": tipo, "receptor": receptor,
        "nombre_receptor": nombre_receptor, "domicilio_receptor": domicilio_receptor,
        "tipo_doc": tipo_doc, "documento_tipo": documento_tipo,
        "importe": importe, "descripcion": descripcion, "items": items, "iva": formulario["iva"],
        "concepto": concepto, "tipo_servicio": tipo_servicio,
        "condicion_venta": condicion_venta,
        "fecha": fecha_comprobante.strftime("%Y%m%d"),
        "servicio_desde": fecha_desde.strftime("%Y%m%d"),
        "servicio_hasta": fecha_hasta.strftime("%Y%m%d"),
        "vencimiento_pago": vencimiento_pago.strftime("%Y%m%d") if vencimiento_pago else None,
        "punto": punto, "cuit_emisor": cuit_emisor,
        "original_punto": original_punto, "original_numero": original_numero,
    }


def carpeta_datos(ambiente):
    return BASE / ("facturas_test" if ambiente == "testing" else "facturas_produccion")


def ruta_pendiente(ambiente):
    return carpeta_datos(ambiente) / "solicitud_pendiente.json"


def auth_wsfe(ambiente, cuit_emisor=None):
    cuit_emisor = validar_cuit(cuit_emisor) if cuit_emisor else cargar_cuit_emisor()
    credenciales = obtener_credenciales_vigentes("wsfe", ambiente)
    return {"Token": credenciales["token"], "Sign": credenciales["sign"], "Cuit": int(cuit_emisor)}


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
