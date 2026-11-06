"""Datos sintéticos y servicios simulados compartidos por las pruebas."""

from types import SimpleNamespace


# Identificador sintético con documento base cero, solo para servicios simulados.
CUIT_PRUEBA = "20000000001"


def comprobante_de_prueba(carpeta):
    return {
        "carpeta_salida": str(carpeta), "ambiente": "testing", "emisor": int(CUIT_PRUEBA),
        "receptor": CUIT_PRUEBA, "tipo_doc_receptor": 80, "punto": 3, "numero": 1,
        "tipo_comprobante": 11, "nombre_comprobante": "Factura C", "prefijo_archivo": "factura",
        "fecha": "20261001", "vencimiento": "20261011", "vencimiento_pago": "20261115",
        "concepto": "Servicios", "servicio_desde": "20260901", "servicio_hasta": "20260930",
        "cae": "12345678901234", "condicion_iva_receptor_nombre": "Responsable inscripto",
        "datos_emisor": {
            "nombre": "Emisor de prueba", "condicion_iva": "Monotributista",
            "domicilio_comercial": "Calle 1, Ciudad", "ingresos_brutos": "Exento",
            "inicio_actividades": "01/01/2020",
        },
        "datos_receptor": {"nombre": "Receptor de prueba", "domicilio_comercial": "Calle 2, Ciudad"},
        "descripcion": "Servicio de prueba", "importe": "100.00",
    }


class ServicioSinRespuesta:
    def FECAESolicitar(self, **_kwargs):
        raise TimeoutError("Se perdió la respuesta")


class ServicioAutorizado:
    def FECAESolicitar(self, **kwargs):
        self.solicitud = kwargs["FeCAEReq"]
        detalle = SimpleNamespace(Resultado="A", CAE="12345678901234", CAEFchVto="20261026")
        return SimpleNamespace(FeCabResp=SimpleNamespace(Resultado="A"), FeDetResp=SimpleNamespace(FECAEDetResponse=[detalle]))
