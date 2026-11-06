"""Emisión interactiva de comprobantes desde la consola."""

import argparse
from datetime import date

from zeep.exceptions import Fault

from facturador.almacenamiento import cargar_config
from facturador.arca.padron import consultar_datos_padron
from facturador.constantes import CONDICIONES_IVA, CONDICIONES_VENTA
from facturador.detalle import UNIDADES_MEDIDA, normalizar_items
from facturador.documentos.pdf import numero_local
from facturador.servicios import preparar, solicitar


def obtener_datos_contribuyente(cuit, etiqueta, ambiente):
    """Permite la carga manual cuando un CUIT no está en el padrón de prueba."""
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
            "cuit": str(cuit), "nombre": nombre, "domicilio_fiscal": domicilio,
            "estado": "No consultado en padrón de homologación", "tipo_persona": None,
            "fuente": "Carga manual para homologación",
        }


def emitir_factura(ambiente):
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


def main(argv=None):
    parser = argparse.ArgumentParser(description="Emisión de Factura C o Nota de Crédito C")
    parser.add_argument("--ambiente", choices=("testing", "produccion"), default="testing")
    args = parser.parse_args(argv)
    emitir_factura(args.ambiente)


if __name__ == "__main__":
    main()
