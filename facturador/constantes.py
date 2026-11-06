"""Tipos de comprobante y opciones fiscales compartidas."""

from decimal import Decimal


TIPO_FACTURA = 11  # Factura C
TIPO_NOTA_CREDITO = 13  # Nota de crédito C
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
