"""Cálculo del detalle compartido por el formulario y el PDF."""

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


UNIDADES_MEDIDA = ("unidad", "servicio", "mes", "hora", "día", "kg", "litro", "metro")
CENTAVO = Decimal("0.01")


def decimal_positivo(valor, decimales, etiqueta):
    texto = str(valor).strip().replace(" ", "")
    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")
    try:
        numero = Decimal(texto)
        precision = Decimal(1).scaleb(-decimales)
        valido = numero.is_finite() and numero > 0 and numero == numero.quantize(precision)
    except InvalidOperation:
        valido = False
    if not valido:
        raise ValueError(f"{etiqueta}: ingresá un valor positivo con hasta {decimales} decimales.")
    return numero


def normalizar_items(items):
    if not isinstance(items, list) or not items:
        raise ValueError("Agregá al menos un producto o servicio al detalle.")
    resultado = []
    for indice, item in enumerate(items, 1):
        if not isinstance(item, dict):
            raise ValueError(f"Renglón {indice}: detalle inválido.")
        descripcion = str(item.get("descripcion", "")).strip()
        if not descripcion:
            raise ValueError(f"Renglón {indice}: completá la descripción.")
        unidad = str(item.get("unidad", "")).strip()
        if unidad not in UNIDADES_MEDIDA:
            raise ValueError(f"Renglón {indice}: seleccioná una unidad de medida válida.")
        cantidad = decimal_positivo(item.get("cantidad", ""), 6, f"Renglón {indice}, cantidad")
        precio = decimal_positivo(item.get("precio_unitario", ""), 2, f"Renglón {indice}, precio unitario")
        try:
            importe = (cantidad * precio).quantize(CENTAVO, rounding=ROUND_HALF_UP)
        except InvalidOperation as error:
            raise ValueError(f"Renglón {indice}: el importe es demasiado grande.") from error
        if importe <= 0 or importe >= Decimal("10000000000000"):
            raise ValueError(f"Renglón {indice}: el importe debe estar entre $0,01 y $9.999.999.999.999,99.")
        resultado.append({
            "codigo": str(item.get("codigo", "")).strip(),
            "descripcion": descripcion,
            "cantidad": format(cantidad, "f"), "unidad": unidad,
            "precio_unitario": f"{precio:.2f}", "importe": f"{importe:.2f}",
        })
    if total_items(resultado) >= Decimal("10000000000000"):
        raise ValueError("El total del comprobante supera el máximo admitido.")
    return resultado


def total_items(items):
    return sum((Decimal(item["importe"]) for item in items), Decimal("0.00"))


def items_del_comprobante(datos):
    """Admite registros anteriores, cuyo detalle era una descripción y un total."""
    if "items" in datos:
        items = normalizar_items(datos["items"])
    else:
        items = normalizar_items([{
            "descripcion": datos.get("descripcion") or "Producto o servicio",
            "cantidad": "1", "unidad": "unidad" if datos.get("concepto") == "Productos" else "servicio",
            "precio_unitario": datos["importe"],
        }])
    if total_items(items) != Decimal(str(datos["importe"])):
        raise ValueError("El detalle no coincide con el importe del comprobante.")
    return items
