"""Validaciones fiscales y del formulario, sin acceso a archivos ni a ARCA."""

from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from facturador.constantes import (
    CONDICIONES_IVA, CONDICIONES_VENTA, LIMITE_CONSUMIDOR_SIN_DOCUMENTO,
    TIPO_SERVICIO,
)
from facturador.detalle import normalizar_items, total_items


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
