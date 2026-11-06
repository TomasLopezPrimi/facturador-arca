"""Representación gráfica de comprobantes C, con contenido paginado."""

import os
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.graphics import renderPDF
from reportlab.graphics.barcode import qr
from reportlab.graphics.shapes import Drawing
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import BaseDocTemplate, Frame, KeepTogether, LongTable, PageTemplate, Paragraph, Spacer, Table, TableStyle

from facturador_detalle import items_del_comprobante


GRIS = colors.Color(0.25, 0.28, 0.31)
LINEA = colors.Color(0.35, 0.37, 0.39)
MARGEN = 14 * mm
ANCHO = A4[0] - 2 * MARGEN


def fecha_local(valor):
    try:
        return datetime.strptime(str(valor), "%Y%m%d").strftime("%d/%m/%Y")
    except ValueError:
        return str(valor or "-")


def numero_local(valor, decimales=2):
    return f"{Decimal(str(valor)):,.{decimales}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def condicion_fiscal(valor):
    condiciones = {
        "monotributista": "RESPONSABLE MONOTRIBUTO",
        "monotributo": "RESPONSABLE MONOTRIBUTO",
        "responsable monotributo": "RESPONSABLE MONOTRIBUTO",
        "exento en iva": "IVA EXENTO", "exento": "IVA EXENTO", "iva exento": "IVA EXENTO",
    }
    return condiciones.get(str(valor).strip().casefold(), str(valor or "No informado"))


def parrafo(valor, tamano=8, negrita=False, alineacion=0):
    estilo = ParagraphStyle(
        "comprobante", fontName="ArialPDF-Bold" if negrita else "ArialPDF",
        fontSize=tamano, leading=max(10, tamano * 1.2), textColor=GRIS,
        alignment=alineacion, splitLongWords=True,
    )
    texto = escape(str(valor or "-")).replace("\r\n", "\n").replace("\r", "\n").replace("\n", "<br/>")
    return Paragraph(texto, estilo)


def campo(etiqueta, valor, tamano=8, negrita=False):
    return [parrafo(etiqueta.upper(), 7, True), Spacer(1, 3), parrafo(valor, tamano, negrita)]


def tabla(filas, anchos, borde=True):
    resultado = Table(filas, colWidths=anchos, hAlign="LEFT", splitByRow=1, splitInRow=1)
    estilos = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3 * mm),
        ("TOPPADDING", (0, 0), (-1, -1), 2 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2 * mm),
    ]
    if borde:
        estilos.append(("BOX", (0, 0), (-1, -1), 0.7, LINEA))
    resultado.setStyle(TableStyle(estilos))
    return resultado


def cabecera(datos):
    emisor = datos.get("datos_emisor", {})
    titulo = datos.get("nombre_comprobante", "Factura C")
    izquierda = [
        parrafo(emisor.get("nombre", "Emisor"), 12, True), Spacer(1, 5),
        parrafo(emisor.get("domicilio_comercial") or emisor.get("domicilio_fiscal", "")),
        Spacer(1, 5), parrafo(condicion_fiscal(emisor.get("condicion_iva")), 7.5),
    ]
    centro = [parrafo("C", 17, True, TA_CENTER), Spacer(1, 5),
              parrafo(f"COD. {int(datos.get('tipo_comprobante', 11)):03d}", 6.5, alineacion=TA_CENTER)]
    derecha = [parrafo(titulo.upper(), 18, True, TA_RIGHT), Spacer(1, 5),
               parrafo("ORIGINAL", 8, True, TA_RIGHT)]
    if datos.get("ambiente") == "testing":
        derecha.extend([Spacer(1, 5), parrafo("HOMOLOGACIÓN - SIN VALIDEZ FISCAL", 7, alineacion=TA_RIGHT)])
    bloque = tabla([[izquierda, centro, derecha]], [81 * mm, 20 * mm, 81 * mm], False)
    bloque.setStyle(TableStyle([("BOX", (1, 0), (1, 0), 0.7, LINEA)]))
    return bloque


def datos_generales(datos):
    emisor = datos.get("datos_emisor", {})
    receptor = datos.get("datos_receptor", {})
    ancho = ANCHO / 3
    yield tabla([
        [campo("Punto de venta", f"{datos['punto']:05d}", 9, True),
         campo("Comp. Nro.", f"{datos['numero']:08d}", 9, True),
         campo("Fecha de emisión", fecha_local(datos.get("fecha")), 9, True)],
        [campo("CUIT", datos["emisor"]), campo("Ingresos Brutos", emisor.get("ingresos_brutos", "No informado")),
         campo("Inicio de actividades", emisor.get("inicio_actividades", "No informado"))],
    ], [ancho] * 3)
    yield Spacer(1, 5 * mm)
    tipo_doc = datos.get("tipo_doc_receptor", 80)
    documento = {80: "CUIT", 96: "DNI", 99: "Consumidor final"}.get(tipo_doc, "Documento")
    yield tabla([
        [campo("Señor(es) / Razón social", receptor.get("nombre", "A CONSUMIDOR FINAL"), 9, True),
         campo(documento, "-" if tipo_doc == 99 else datos.get("receptor"), 8, True)],
        [campo("Domicilio", receptor.get("domicilio_comercial") or receptor.get("domicilio_fiscal", "NR"), 7.5),
         campo("Condición frente al IVA", datos.get("condicion_iva_receptor_nombre", "Consumidor final"))],
    ], [109 * mm, 73 * mm])
    yield Spacer(1, 5 * mm)
    if datos.get("concepto") == "Servicios":
        periodo = f"{fecha_local(datos.get('servicio_desde'))} al {fecha_local(datos.get('servicio_hasta'))}"
        # Los registros previos enviaban a WSFE el vencimiento igual a la emisión.
        vencimiento = datos.get("vencimiento_pago") or datos.get("fecha")
        yield tabla([[campo("Condición de venta", datos.get("condicion_venta", "Transferencia Bancaria")),
                      campo("Período facturado", periodo), campo("Vencimiento para el pago", fecha_local(vencimiento))]],
                    [58 * mm, 64 * mm, 60 * mm])
    else:
        yield tabla([[campo("Condición de venta", datos.get("condicion_venta", "Transferencia Bancaria"))]], [ANCHO])
    asociado = datos.get("comprobante_asociado")
    if asociado:
        yield Spacer(1, 3 * mm)
        yield tabla([[campo("Comprobante asociado", f"Factura C {asociado['punto']:05d}-{asociado['numero']:08d}")]], [ANCHO])


def tabla_detalle(datos, items):
    titulos = ("CÓDIGO / PRODUCTO O SERVICIO", "Cantidad", "U. medida", "Precio unit.", "Importe")
    filas = [[parrafo(titulo, 6.5, True, TA_RIGHT if indice in (1, 3, 4) else 0)
              for indice, titulo in enumerate(titulos)]]
    for indice, item in enumerate(items):
        descripcion = item["descripcion"]
        if item["codigo"]:
            descripcion = f"{item['codigo']} - {descripcion}"
        if indice == 0 and datos.get("tipo_servicio"):
            descripcion = f"{datos['tipo_servicio']}\n{descripcion}"
        cantidad = Decimal(item["cantidad"])
        decimales = max(2, -cantidad.normalize().as_tuple().exponent)
        filas.append([
            parrafo(descripcion, 8.5), parrafo(numero_local(cantidad, decimales), 8.5, alineacion=TA_RIGHT),
            parrafo(item["unidad"], 8.5), parrafo(numero_local(item["precio_unitario"]), 8.5, alineacion=TA_RIGHT),
            parrafo(numero_local(item["importe"]), 8.5, True, TA_RIGHT),
        ])
    detalle = LongTable(filas, colWidths=[82 * mm, 19 * mm, 21 * mm, 30 * mm, 30 * mm],
                        repeatRows=1, splitByRow=1, splitInRow=1, hAlign="LEFT")
    detalle.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3 * mm), ("RIGHTPADDING", (0, 0), (-1, -1), 3 * mm),
        ("TOPPADDING", (0, 0), (-1, -1), 3 * mm), ("BOTTOMPADDING", (0, 0), (-1, -1), 3 * mm),
        ("BACKGROUND", (0, 0), (-1, 0), colors.Color(0.91, 0.92, 0.93)),
        ("BOX", (0, 0), (-1, 0), 0.7, LINEA),
        ("LINEBELOW", (0, 1), (-1, -1), 0.7, LINEA),
    ]))
    return detalle


def dibujar_pie(pdf, documento, datos, url_qr):
    pdf.saveState()
    derecha = A4[0] - MARGEN
    pie_y = 49 * mm
    pdf.setFillColor(GRIS)
    pdf.setStrokeColor(LINEA)
    pdf.setLineWidth(0.7)
    pdf.line(MARGEN, pie_y + 25 * mm, derecha, pie_y + 25 * mm)
    for x, etiqueta, valor, tamano in (
        (MARGEN, "CAE", datos.get("cae", ""), 10),
        (MARGEN + 64 * mm, "VENCIMIENTO DEL CAE", fecha_local(datos.get("vencimiento")), 9),
    ):
        pdf.setFont("ArialPDF-Bold", 7)
        pdf.drawString(x, pie_y + 19 * mm, etiqueta)
        pdf.setFont("ArialPDF-Bold", tamano)
        pdf.drawString(x, pie_y + 12 * mm, str(valor))
    pdf.setFont("ArialPDF", 7)
    pdf.drawString(MARGEN, pie_y + 4 * mm, "Comprobante autorizado por ARCA")
    if datos.get("ambiente") == "testing":
        pdf.setFont("ArialPDF-Bold", 7)
        pdf.drawString(MARGEN, pie_y, "DOCUMENTO DE PRUEBA - SIN VALIDEZ FISCAL")
    tamano_qr = 29 * mm
    dibujo = Drawing(tamano_qr, tamano_qr)
    dibujo.add(qr.QrCodeWidget(url_qr, barWidth=tamano_qr, barHeight=tamano_qr))
    renderPDF.draw(dibujo, pdf, derecha - tamano_qr, 14 * mm)
    pdf.setFont("ArialPDF", 7)
    pdf.drawString(MARGEN, 15 * mm, f"Página {documento.page}")
    if documento.page > 1:
        pdf.setFont("ArialPDF-Bold", 9)
        identificacion = f"{datos.get('nombre_comprobante', 'Factura C')} {datos['punto']:05d}-{datos['numero']:08d}"
        pdf.drawString(MARGEN, A4[1] - 19 * mm, identificacion)
        pdf.drawRightString(derecha, A4[1] - 19 * mm, "ORIGINAL - CONTINUACIÓN")
        pdf.setFont("ArialPDF", 7)
        pdf.drawString(MARGEN, A4[1] - 24 * mm, f"Emisor CUIT {datos['emisor']} - Receptor {datos.get('receptor', '-')}")
    pdf.restoreState()


def generar_pdf(datos, url_qr):
    items = items_del_comprobante(datos)
    pdfmetrics.registerFont(TTFont("ArialPDF", "C:/Windows/Fonts/arial.ttf"))
    pdfmetrics.registerFont(TTFont("ArialPDF-Bold", "C:/Windows/Fonts/arialbd.ttf"))
    base = Path(__file__).resolve().parent
    carpeta = Path(datos["carpeta_salida"]) if datos.get("carpeta_salida") else base / (
        "facturas_test" if datos["ambiente"] == "testing" else "facturas_produccion")
    carpeta.mkdir(parents=True, exist_ok=True)
    nombre = f"{datos.get('prefijo_archivo', 'factura')}_C_{datos['punto']:05d}_{datos['numero']:08d}.pdf"
    ruta = carpeta / nombre
    temporal = ruta.with_name(ruta.name + ".tmp")
    documento = BaseDocTemplate(str(temporal), pagesize=A4, title=datos.get("nombre_comprobante", "Factura C"),
                               author=f"CUIT {datos['emisor']}")
    for nombre_pagina, superior in (("primera", 14 * mm), ("continuacion", 29 * mm)):
        marco = Frame(MARGEN, 79 * mm, ANCHO, A4[1] - superior - 79 * mm,
                      leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
        documento.addPageTemplates(PageTemplate(
            id=nombre_pagina, frames=[marco], autoNextPageTemplate="continuacion",
            onPage=lambda pdf, doc: dibujar_pie(pdf, doc, datos, url_qr)))
    contenido = [cabecera(datos), Spacer(1, 5 * mm), *datos_generales(datos), Spacer(1, 7 * mm)]
    contenido.append(tabla_detalle(datos, items))
    contenido.append(Spacer(1, 6 * mm))
    total = tabla([[parrafo("IMPORTE TOTAL", 10, True, TA_RIGHT),
                    parrafo(f"$ {numero_local(datos['importe'])}", 13, True, TA_RIGHT)]], [ANCHO - 65 * mm, 65 * mm], False)
    contenido.append(KeepTogether([total, parrafo("Moneda: PES - Cotización: 1", 7.5, alineacion=TA_RIGHT)]))
    try:
        documento.build(contenido)
        os.replace(temporal, ruta)
    finally:
        temporal.unlink(missing_ok=True)
    return ruta
