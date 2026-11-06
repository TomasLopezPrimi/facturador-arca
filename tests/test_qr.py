import base64
import json
import unittest
from urllib.parse import parse_qs, urlparse

from facturador.documentos.qr import generar_url_qr
from tests.helpers import CUIT_PRUEBA


class QrTests(unittest.TestCase):
    def test_qr_conserva_datos_del_comprobante_sin_consultar_arca(self):
        datos = {
            "fecha": "20261001", "emisor": CUIT_PRUEBA, "receptor": CUIT_PRUEBA,
            "punto": 3, "numero": 1, "importe": "1500.25", "cae": "12345678901234",
        }
        url = urlparse(generar_url_qr(datos))
        payload = json.loads(base64.b64decode(parse_qs(url.query)["p"][0]))
        self.assertEqual(url.netloc, "www.arca.gob.ar")
        self.assertEqual(payload["fecha"], "2026-10-01")
        self.assertEqual(payload["cuit"], int(CUIT_PRUEBA))
        self.assertEqual(payload["nroDocRec"], int(CUIT_PRUEBA))
        self.assertEqual(payload["importe"], 1500.25)
        self.assertEqual(payload["codAut"], 12345678901234)
        self.assertEqual(payload["tipoCmp"], 11)


if __name__ == "__main__":
    unittest.main()
