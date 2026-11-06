import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from facturador import almacenamiento
from facturador.arca import wsfe
from tests.helpers import CUIT_PRUEBA


class ConfiguracionPrivadaTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config_path = Path(self.temp.name) / "config_facturador.json"
        parche = patch.object(almacenamiento, "CONFIG_PATH", self.config_path)
        parche.start()
        self.addCleanup(parche.stop)

    def test_sin_configuracion_no_hay_cuit_predeterminado(self):
        with self.assertRaisesRegex(ValueError, "Configurá y guardá tu CUIT"):
            almacenamiento.cargar_cuit_emisor()

    def test_cuit_se_lee_de_configuracion_local_y_se_normaliza(self):
        almacenamiento.guardar_json_atomico(self.config_path, {"cuit_emisor": "20-00000000-1"})
        self.assertEqual(almacenamiento.cargar_cuit_emisor(), CUIT_PRUEBA)

    def test_configuracion_incompleta_o_cuit_invalido_se_rechaza(self):
        for config in ({}, {"cuit_emisor": ""}, {"cuit_emisor": "20000000002"}):
            with self.subTest(config=config):
                almacenamiento.guardar_json_atomico(self.config_path, config)
                with self.assertRaises(ValueError):
                    almacenamiento.cargar_cuit_emisor()

    def test_auth_usa_cuit_local_sin_consultar_arca(self):
        almacenamiento.guardar_json_atomico(self.config_path, {"cuit_emisor": CUIT_PRUEBA})
        ticket = {"token": "token-simulado", "sign": "firma-simulada"}
        with patch.object(wsfe, "obtener_credenciales_vigentes", return_value=ticket):
            auth = wsfe.auth_wsfe("testing")
        self.assertEqual(auth["Cuit"], int(CUIT_PRUEBA))

    def test_auth_sin_cuit_no_solicita_credenciales(self):
        with patch.object(wsfe, "obtener_credenciales_vigentes") as obtener:
            with self.assertRaises(ValueError):
                wsfe.auth_wsfe("testing")
        obtener.assert_not_called()

    def test_receptores_se_guardan_y_se_leen_en_ruta_local(self):
        receptores_path = Path(self.temp.name) / "receptores.json"
        receptor = {
            "id": "prueba", "documento_tipo": "CUIT", "documento": CUIT_PRUEBA,
            "nombre": "Receptor de prueba", "domicilio": "Calle de prueba",
            "iva": "Monotributista",
        }
        with patch.object(almacenamiento, "RECEPTORES_PATH", receptores_path):
            self.assertEqual(almacenamiento.cargar_receptores(), [])
            almacenamiento.guardar_receptores([receptor])
            self.assertEqual(almacenamiento.cargar_receptores(), [receptor])


if __name__ == "__main__":
    unittest.main()
