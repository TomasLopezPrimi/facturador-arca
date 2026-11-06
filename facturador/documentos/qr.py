"""Payload oficial del QR de factura electrónica (versión 1)."""

import base64
import json
from decimal import Decimal
from urllib.parse import urlencode

from facturador.constantes import TIPO_FACTURA


URL_QR_ARCA = "https://www.arca.gob.ar/fe/qr/"


def generar_url_qr(datos):
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
