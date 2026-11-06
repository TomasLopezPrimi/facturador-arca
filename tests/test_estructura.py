import importlib
import io
import os
import runpy
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from facturador import rutas
from facturador.arca import wsaa
from facturador.documentos import pdf


class EstructuraTests(unittest.TestCase):
    def test_rutas_privadas_siguen_en_la_raiz_del_proyecto(self):
        raiz = Path(__file__).resolve().parent.parent
        self.assertEqual(rutas.BASE, raiz)
        self.assertEqual(rutas.CONFIG_PATH, raiz / "config_facturador.json")
        self.assertEqual(rutas.RECEPTORES_PATH, raiz / "receptores.json")
        self.assertEqual(wsaa.CREDENTIALS_FILE, raiz / "credenciales.json")
        self.assertEqual(wsaa.CERT, raiz / "certificados" / "certificado.pem")
        self.assertEqual(wsaa.KEY, raiz / "certificados" / "privada.key")
        self.assertEqual(pdf.carpeta_datos("testing"), raiz / "facturas_test")
        self.assertEqual(pdf.carpeta_datos("produccion"), raiz / "facturas_produccion")

    def test_rutas_no_dependen_del_directorio_actual(self):
        codigo = (
            "from pathlib import Path; "
            "from facturador.rutas import BASE, CONFIG_PATH; "
            "import sys; "
            "assert BASE == Path(sys.argv[1]); "
            "assert CONFIG_PATH == BASE / 'config_facturador.json'"
        )
        with tempfile.TemporaryDirectory() as temporal:
            entorno = {**os.environ, "PYTHONPATH": str(rutas.BASE)}
            resultado = subprocess.run(
                [sys.executable, "-c", codigo, str(rutas.BASE)],
                cwd=temporal, env=entorno, capture_output=True, text=True,
            )
        self.assertEqual(resultado.returncode, 0, resultado.stderr)

    def test_lanzadores_de_interfaz_delegan_al_mismo_main(self):
        with patch("facturador.ui.app.main") as iniciar:
            runpy.run_module("facturador", run_name="__main__")
            iniciar.assert_called_once_with()
            iniciar.reset_mock()
            runpy.run_path(str(rutas.BASE / "facturador_app.py"), run_name="__main__")
            iniciar.assert_called_once_with()

    def test_ayuda_de_consola_no_autentica_ni_emite(self):
        comandos = {
            "autenticar": "obtener_credenciales",
            "emitir": "emitir_factura",
            "consultar_wsfe": "consultar_tipos_comprobante",
            "consultar_puntos_venta": "consultar_puntos_venta",
        }
        for nombre, funcion in comandos.items():
            with self.subTest(comando=nombre):
                modulo = importlib.import_module(f"facturador.cli.{nombre}")
                with patch.object(modulo, funcion) as ejecutar, redirect_stdout(io.StringIO()):
                    with self.assertRaises(SystemExit) as salida:
                        modulo.main(["--help"])
                self.assertEqual(salida.exception.code, 0)
                ejecutar.assert_not_called()


if __name__ == "__main__":
    unittest.main()
