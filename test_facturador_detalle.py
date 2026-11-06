import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import facturador_core as core
from facturador_detalle import items_del_comprobante, normalizar_items, total_items
from test_facturador_core import CUIT_PRUEBA, ServicioAutorizado


class DetalleTests(unittest.TestCase):
    def item(self, **cambios):
        return {"descripcion": "Soporte técnico", "cantidad": "2", "unidad": "hora", "precio_unitario": "1500,25", **cambios}

    def test_calculo_decimal_y_redondeo_por_renglon(self):
        items = normalizar_items([self.item(cantidad="1,005", precio_unitario="1,00"), self.item()])
        self.assertEqual(items[0]["importe"], "1.01")
        self.assertEqual(total_items(items), Decimal("3001.51"))

    def test_rechaza_cantidades_precios_y_unidades_invalidas(self):
        for cambios in ({"cantidad": "0"}, {"cantidad": "-2"}, {"cantidad": "NaN"},
                        {"cantidad": "1.0000001"}, {"precio_unitario": "1,005"},
                        {"precio_unitario": "Infinity"}, {"unidad": ""}, {"descripcion": " "}):
            with self.subTest(cambios=cambios), self.assertRaises(ValueError):
                normalizar_items([self.item(**cambios)])

    def test_rechaza_detalle_vacio_y_total_fuera_de_limite(self):
        for items in ([], [self.item(cantidad="10000000000000", precio_unitario="1")],
                      [self.item(cantidad="1", precio_unitario="9999999999999.99"), self.item()]):
            with self.subTest(items=items), self.assertRaises(ValueError):
                normalizar_items(items)

    def test_registro_legacy_conserva_total_y_descripcion(self):
        items = items_del_comprobante({"descripcion": "Servicio anterior", "importe": "150.00", "concepto": "Servicios"})
        self.assertEqual(items[0]["descripcion"], "Servicio anterior")
        self.assertEqual(total_items(items), Decimal("150.00"))

    def test_no_acepta_pdf_con_total_distinto_del_detalle(self):
        with self.assertRaisesRegex(ValueError, "no coincide"):
            items_del_comprobante({"items": [self.item()], "importe": "1"})


class FechasYEmisionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.carpeta = Path(self.temp.name)
        self.config = {
            "cuit_emisor": CUIT_PRUEBA, "punto_venta": "3", "nombre_emisor": "Emisor",
            "domicilio_emisor": "Calle 1, Ciudad", "condicion_iva_emisor": "Monotributista",
            "ingresos_brutos": "Exento", "inicio_actividades": "01/01/2020",
        }
        self.formulario = {
            "ambiente": "testing", "tipo": "Factura C", "concepto": "Servicios",
            "documento_tipo": "Sin documento", "receptor": "", "nombre_receptor": "", "domicilio_receptor": "",
            "iva": "Consumidor final", "fecha": "01/01/2020", "servicio_desde": "01/01/2020", "servicio_hasta": "31/01/2020",
            "vencimiento_pago": "15/02/2020",
            "items": [{"descripcion": "Descripción completa " * 40, "cantidad": "2.5", "unidad": "hora", "precio_unitario": "100"}],
        }

    def test_formulario_deriva_total_del_detalle_y_conserva_texto(self):
        datos = core.validar_formulario(self.formulario, self.config)
        self.assertEqual(datos["importe"], Decimal("250.00"))
        self.assertEqual(datos["items"][0]["descripcion"], self.formulario["items"][0]["descripcion"].strip())
        self.assertEqual(datos["vencimiento_pago"], "20200215")

    def test_pago_puede_ser_futuro(self):
        self.formulario["vencimiento_pago"] = f"01/01/{date.today().year + 1}"
        self.assertIsNotNone(core.validar_formulario(self.formulario, self.config)["vencimiento_pago"])

    def test_rechaza_vencimientos_invalidos_o_anteriores_a_emision(self):
        for valor in ("31/02/2020", "", "31/12/2019"):
            with self.subTest(valor=valor), self.assertRaises(ValueError):
                core.validar_formulario({**self.formulario, "vencimiento_pago": valor}, self.config)

    def test_productos_ignoran_fechas_de_pago_de_servicios(self):
        formulario = {**self.formulario, "concepto": "Productos", "vencimiento_pago": "fecha vieja inválida"}
        self.assertIsNone(core.validar_formulario(formulario, self.config)["vencimiento_pago"])

    def test_fecha_y_total_se_conservan_de_formulario_a_wsfe_y_json(self):
        servicio = ServicioAutorizado()
        servicio.FECompUltimoAutorizado = lambda **_kw: SimpleNamespace(CbteNro=0)
        cliente = SimpleNamespace(service=servicio)
        with patch.object(core, "carpeta_datos", return_value=self.carpeta), \
                patch.object(core, "crear_cliente_wsfe", return_value=cliente), \
                patch.object(core, "auth_wsfe", return_value={}), \
                patch.object(core, "consultar_datos_padron", return_value={"estado": "ACTIVO"}), \
                patch.object(core, "generar_pdf", return_value=self.carpeta / "factura.pdf") as generar:
            _, auth, registro = core.preparar(self.formulario, self.config)
            _, ruta = core.solicitar(cliente, auth, registro)
        import json
        guardado = json.loads(ruta.read_text(encoding="utf-8"))
        detalle = servicio.solicitud["FeDetReq"]["FECAEDetRequest"][0]
        self.assertEqual(detalle["FchVtoPago"], "20200215")
        self.assertEqual(detalle["ImpTotal"], Decimal("250.00"))
        self.assertEqual(guardado["vencimiento_pago"], "20200215")
        self.assertEqual(guardado["items"], registro["items"])
        self.assertEqual(generar.call_args.args[0]["vencimiento_pago"], "20200215")

    def test_detalle_inconsistente_se_rechaza_antes_de_solicitar_cae(self):
        servicio = ServicioAutorizado()
        registro = {"ambiente": "testing", "items": self.formulario["items"], "importe": "1.00"}
        with patch.object(core, "carpeta_datos", return_value=self.carpeta):
            with self.assertRaisesRegex(ValueError, "no coincide"):
                core.solicitar(SimpleNamespace(service=servicio), {}, registro)
        self.assertFalse(hasattr(servicio, "solicitud"))


if __name__ == "__main__":
    unittest.main()
