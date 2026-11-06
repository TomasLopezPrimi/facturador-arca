import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from zeep.exceptions import Fault

import facturador_core as core


# Identificador sintético con documento base cero, solo para servicios simulados.
CUIT_PRUEBA = "20000000001"


class ServicioSinRespuesta:
    def FECAESolicitar(self, **_kwargs):
        raise TimeoutError("Se perdió la respuesta")


class ServicioAutorizado:
    def FECAESolicitar(self, **kwargs):
        self.solicitud = kwargs["FeCAEReq"]
        detalle = SimpleNamespace(Resultado="A", CAE="12345678901234", CAEFchVto="20261026")
        return SimpleNamespace(FeCabResp=SimpleNamespace(Resultado="A"), FeDetResp=SimpleNamespace(FECAEDetResponse=[detalle]))


class FacturadorCoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.carpeta = Path(self.temp.name)
        self.datos = {
            "ambiente": "testing", "emisor": int(CUIT_PRUEBA),
            "receptor": CUIT_PRUEBA, "punto": 3, "numero": 4,
            "fecha": "20261016", "importe": "100.00", "concepto": "Servicios",
            "tipo_comprobante": core.TIPO_FACTURA,
            "condicion_iva_receptor": 1, "comprobante_asociado": None,
            "tipo_doc_receptor": 80,
            "prefijo_archivo": "factura",
        }

    def test_timeout_deja_pendiente_y_bloquea_reenvio(self):
        cliente = SimpleNamespace(service=ServicioSinRespuesta())
        with patch.object(core, "carpeta_datos", return_value=self.carpeta), patch.object(core, "consulta_autorizada", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "quedó pendiente"):
                core.solicitar(cliente, {}, self.datos)
            pendiente = self.carpeta / "solicitud_pendiente.json"
            self.assertTrue(pendiente.exists())
            self.assertEqual(json.loads(pendiente.read_text(encoding="utf-8"))["numero"], 4)
            with self.assertRaisesRegex(RuntimeError, "Existe una solicitud pendiente"):
                core.solicitar(cliente, {}, self.datos)

    def test_consulta_distinta_no_se_guarda_como_autorizada(self):
        original = SimpleNamespace(ImpTotal="999.00", DocNro=CUIT_PRUEBA, DocTipo=80)
        with self.assertRaisesRegex(RuntimeError, "comprobante distinto"):
            core.verificar_consulta(original, self.datos)

    def test_consumidor_final_sin_documento_exige_identificacion_desde_umbral(self):
        formulario = {
            "ambiente": "testing", "tipo": "Factura C", "concepto": "Servicios",
            "documento_tipo": "Sin documento", "receptor": "",
            "nombre_receptor": "", "domicilio_receptor": "",
            "iva": "Consumidor final", "descripcion": "Servicio",
            "importe": "9999999.99", "original_punto": "", "original_numero": "",
        }
        config = {
            "cuit_emisor": CUIT_PRUEBA,
            "punto_venta": "3", "nombre_emisor": "Emisor", "domicilio_emisor": "Calle 1",
            "condicion_iva_emisor": "Monotributo", "ingresos_brutos": "Exento",
            "inicio_actividades": "01/01/2020",
        }
        datos = core.validar_formulario(formulario, config)
        self.assertEqual((datos["tipo_doc"], datos["receptor"]), (99, "0"))
        config["cuit_emisor"] = "20-00000000-1"
        self.assertEqual(core.validar_formulario(formulario, config)["cuit_emisor"], CUIT_PRUEBA)
        formulario["importe"] = "10000000"
        with self.assertRaisesRegex(ValueError, "debe identificarse"):
            core.validar_formulario(formulario, config)

    def test_autorizacion_consumidor_final_guarda_cae_y_documento(self):
        datos = {**self.datos, "receptor": "0", "tipo_doc_receptor": 99, "condicion_iva_receptor": 5}
        servicio = ServicioAutorizado()
        cliente = SimpleNamespace(service=servicio)
        with patch.object(core, "carpeta_datos", return_value=self.carpeta), patch.object(core, "generar_pdf", return_value=self.carpeta / "factura.pdf"):
            _, registro = core.solicitar(cliente, {}, datos)
        detalle = servicio.solicitud["FeDetReq"]["FECAEDetRequest"][0]
        self.assertEqual((detalle["DocTipo"], detalle["DocNro"]), (99, 0))
        self.assertFalse((self.carpeta / "solicitud_pendiente.json").exists())
        self.assertEqual(json.loads(registro.read_text(encoding="utf-8"))["cae"], "12345678901234")

    def test_nota_credito_asocia_factura_con_cuit_del_emisor(self):
        datos = {
            **self.datos,
            "emisor": int(CUIT_PRUEBA),
            "tipo_comprobante": core.TIPO_NOTA_CREDITO,
            "prefijo_archivo": "nota_credito",
            "comprobante_asociado": {"punto": 3, "numero": 2, "fecha": "20261015"},
        }
        servicio = ServicioAutorizado()
        with patch.object(core, "carpeta_datos", return_value=self.carpeta), \
                patch.object(core, "generar_pdf", return_value=self.carpeta / "nota.pdf"):
            core.solicitar(SimpleNamespace(service=servicio), {}, datos)
        asociado = servicio.solicitud["FeDetReq"]["FECAEDetRequest"][0]["CbtesAsoc"]["CbteAsoc"][0]
        self.assertEqual(asociado["Cuit"], int(CUIT_PRUEBA))

    def test_padron_testing_prefiere_datos_reales_de_produccion(self):
        perfil = {"nombre": "Emisor", "domicilio_fiscal": "Calle fiscal"}
        with patch.object(core, "consultar_datos_padron", return_value=perfil) as consulta:
            resultado = core.consultar_padron_para_interfaz(CUIT_PRUEBA, "testing", CUIT_PRUEBA)
        self.assertEqual(consulta.call_args_list[0].args[1], "produccion")
        self.assertIn("producción", resultado["fuente"])

    def test_preparar_usa_cuit_configurado_en_arca_y_registro(self):
        formulario = {
            "ambiente": "testing", "tipo": "Factura C", "concepto": "Servicios",
            "documento_tipo": "Sin documento", "receptor": "",
            "nombre_receptor": "", "domicilio_receptor": "",
            "iva": "Consumidor final", "descripcion": "Servicio",
            "importe": "100.00", "original_punto": "", "original_numero": "",
        }
        config = {
            "cuit_emisor": CUIT_PRUEBA, "punto_venta": "3", "nombre_emisor": "Otro emisor",
            "domicilio_emisor": "Calle 1", "condicion_iva_emisor": "Monotributista",
            "ingresos_brutos": "Exento", "inicio_actividades": "01/01/2020",
        }
        servicio = SimpleNamespace(FECompUltimoAutorizado=lambda **_kwargs: SimpleNamespace(CbteNro=4))
        cliente = SimpleNamespace(service=servicio)
        perfil = {"cuit": CUIT_PRUEBA, "nombre": "Otro emisor", "estado": "ACTIVO"}
        with patch.object(core, "carpeta_datos", return_value=self.carpeta), \
                patch.object(core, "crear_cliente_wsfe", return_value=cliente), \
                patch.object(core, "auth_wsfe", return_value={"Cuit": int(CUIT_PRUEBA)}) as auth, \
                patch.object(core, "consultar_datos_padron", return_value=perfil) as padron:
            _, autenticacion, registro = core.preparar(formulario, config)
        auth.assert_called_once_with("testing", CUIT_PRUEBA)
        padron.assert_called_once_with(CUIT_PRUEBA, "testing", cuit_representada=CUIT_PRUEBA)
        self.assertEqual(autenticacion["Cuit"], int(CUIT_PRUEBA))
        self.assertEqual(registro["emisor"], int(CUIT_PRUEBA))
        self.assertEqual(registro["carpeta_salida"], str(self.carpeta / CUIT_PRUEBA))

    def test_recuperar_pendiente_usa_cuit_original_aun_si_cambia_configuracion(self):
        pendiente = self.carpeta / "solicitud_pendiente.json"
        datos = {**self.datos, "emisor": int(CUIT_PRUEBA), "carpeta_salida": str(self.carpeta / CUIT_PRUEBA)}
        core.guardar_json_atomico(pendiente, datos)
        original = SimpleNamespace(ImpTotal="100.00", DocNro=CUIT_PRUEBA, DocTipo=80,
                                   CodAutorizacion="12345678901234", FchVto="20261026")
        with patch.object(core, "carpeta_datos", return_value=self.carpeta), \
                patch.object(core, "crear_cliente_wsfe"), \
                patch.object(core, "auth_wsfe", return_value={"Cuit": int(CUIT_PRUEBA)}) as auth, \
                patch.object(core, "consulta_autorizada", return_value=original), \
                patch.object(core, "generar_pdf", return_value=self.carpeta / CUIT_PRUEBA / "factura.pdf"):
            resultado = core.recuperar_pendiente("testing")
        auth.assert_called_once_with("testing", int(CUIT_PRUEBA))
        self.assertIn("Comprobante recuperado", resultado)
        self.assertFalse(pendiente.exists())
        self.assertTrue((self.carpeta / CUIT_PRUEBA / "factura_C_00003_00000004.json").exists())

    def test_padron_sin_credenciales_produccion_explica_alternativa(self):
        with patch.object(core, "consultar_datos_padron", side_effect=[FileNotFoundError("certificado"), Fault("No existe persona con ese Id")]):
            with self.assertRaisesRegex(RuntimeError, "cargar el domicilio manualmente"):
                core.consultar_padron_para_interfaz(CUIT_PRUEBA, "testing", CUIT_PRUEBA)

    def test_padron_sin_produccion_indica_que_testing_es_de_prueba(self):
        perfil = {"nombre": "Receptor", "domicilio_fiscal": "Calle de prueba"}
        with patch.object(core, "consultar_datos_padron", side_effect=[FileNotFoundError("certificado"), perfil]):
            resultado = core.consultar_padron_para_interfaz(CUIT_PRUEBA, "testing", CUIT_PRUEBA)
        self.assertIn("datos de prueba", resultado["fuente"])


class ConfiguracionPrivadaTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config_path = Path(self.temp.name) / "config_facturador.json"
        parche = patch.object(core, "CONFIG_PATH", self.config_path)
        parche.start()
        self.addCleanup(parche.stop)

    def test_sin_configuracion_no_hay_cuit_predeterminado(self):
        with self.assertRaisesRegex(ValueError, "Configurá y guardá tu CUIT"):
            core.cargar_cuit_emisor()

    def test_cuit_se_lee_de_configuracion_local_y_se_normaliza(self):
        core.guardar_json_atomico(self.config_path, {"cuit_emisor": "20-00000000-1"})
        self.assertEqual(core.cargar_cuit_emisor(), CUIT_PRUEBA)

    def test_configuracion_incompleta_o_cuit_invalido_se_rechaza(self):
        for config in ({}, {"cuit_emisor": ""}, {"cuit_emisor": "20000000002"}):
            with self.subTest(config=config):
                core.guardar_json_atomico(self.config_path, config)
                with self.assertRaises(ValueError):
                    core.cargar_cuit_emisor()

    def test_auth_usa_cuit_local_sin_consultar_arca(self):
        core.guardar_json_atomico(self.config_path, {"cuit_emisor": CUIT_PRUEBA})
        ticket = {"token": "token-simulado", "sign": "firma-simulada"}
        with patch.object(core, "obtener_credenciales_vigentes", return_value=ticket):
            auth = core.auth_wsfe("testing")
        self.assertEqual(auth["Cuit"], int(CUIT_PRUEBA))

    def test_auth_sin_cuit_no_solicita_credenciales(self):
        with patch.object(core, "obtener_credenciales_vigentes") as obtener:
            with self.assertRaises(ValueError):
                core.auth_wsfe("testing")
        obtener.assert_not_called()


if __name__ == "__main__":
    unittest.main()
