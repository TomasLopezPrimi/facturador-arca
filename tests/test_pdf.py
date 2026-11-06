import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from facturador.detalle import normalizar_items, total_items
from facturador.documentos import pdf as documento_pdf
from facturador.documentos.pdf import generar_pdf
from tests.helpers import comprobante_de_prueba

try:
    from pypdf import PdfReader
except ImportError:
    PdfReader = None


@unittest.skipIf(PdfReader is None, "La revisión de PDFs requiere pypdf (dependencia de desarrollo).")
class PdfTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.datos = comprobante_de_prueba(self.temp.name)

    def leer(self):
        ruta = generar_pdf(self.datos, "https://www.arca.gob.ar/fe/qr/?p=prueba")
        pdf = PdfReader(str(ruta))
        return pdf, "\n".join(p.extract_text() for p in pdf.pages)

    def test_una_copia_con_datos_fiscales_y_dos_vencimientos(self):
        pdf, texto = self.leer()
        self.assertEqual(len(pdf.pages), 1)
        for esperado in ("RESPONSABLE MONOTRIBUTO", "15/11/2026", "11/10/2026", "12345678901234", "servicio"):
            self.assertIn(esperado, texto)
        self.assertNotIn("DUPLICADO", texto)
        self.assertNotIn("TRIPLICADO", texto)
        self.assertFalse(pdf.pages[0].get("/Annots"))

    def test_registro_anterior_usa_la_fecha_de_pago_que_enviaba_wsfe(self):
        del self.datos["vencimiento_pago"]
        _, texto = self.leer()
        self.assertIn("VENCIMIENTO PARA EL PAGO", texto)
        self.assertGreaterEqual(texto.count("01/10/2026"), 2)

    def test_descripcion_y_domicilios_largos_se_imprimen_completos(self):
        self.datos["datos_receptor"]["domicilio_comercial"] = "DomicilioExtenso " * 25 + "FINALDOMICILIO"
        self.datos["datos_emisor"]["nombre"] = "NombreEmisorExtenso " * 15 + "FINALNOMBRE"
        self.datos["descripcion"] = "DetalleExtenso " * 500 + "FINALDETALLE"
        pdf, texto = self.leer()
        self.assertGreater(len(pdf.pages), 1)
        for esperado in ("FINALDOMICILIO", "FINALNOMBRE", "FINALDETALLE", "CONTINUACIÓN"):
            self.assertIn(esperado, texto)
        self.assertEqual(texto.count("DetalleExtenso"), 500)
        self.assertEqual(texto.count("DomicilioExtenso"), 25)

    def test_varios_items_paginan_sin_perder_renglones_y_repiten_encabezados(self):
        self.datos["items"] = normalizar_items([
            {"descripcion": f"RenglonIdentificable{indice:03d}", "cantidad": "2.5", "unidad": "hora", "precio_unitario": "250.50"}
            for indice in range(60)])
        self.datos["importe"] = str(total_items(self.datos["items"]))
        pdf, texto = self.leer()
        self.assertGreater(len(pdf.pages), 1)
        for indice in range(60):
            self.assertEqual(texto.count(f"RenglonIdentificable{indice:03d}"), 1)
        for pagina in pdf.pages:
            self.assertIn("Precio unit.", pagina.extract_text())
            self.assertIn("12345678901234", pagina.extract_text())
        self.assertEqual(texto.count("IMPORTE TOTAL"), 1)
        self.assertIn("37.575,00", texto)

    def test_nota_credito_imprime_asociacion_y_codigo(self):
        self.datos.update(nombre_comprobante="Nota de crédito C", tipo_comprobante=13, prefijo_archivo="nota_credito",
                          comprobante_asociado={"punto": 3, "numero": 9})
        _, texto = self.leer()
        self.assertIn("COD. 013", texto)
        self.assertIn("00003-00000009", texto)

    def test_error_de_render_no_reemplaza_pdf_existente(self):
        ruta = Path(self.temp.name) / "factura_C_00003_00000001.pdf"
        ruta.write_bytes(b"PDF anterior")
        with patch("facturador.documentos.pdf.BaseDocTemplate.build", side_effect=RuntimeError("fallo")):
            with self.assertRaises(RuntimeError):
                self.leer()
        self.assertEqual(ruta.read_bytes(), b"PDF anterior")
        self.assertFalse(ruta.with_name(ruta.name + ".tmp").exists())


class GeneracionPdfTests(unittest.TestCase):
    """Verificaciones de escritura que no requieren el lector opcional pypdf."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.datos = comprobante_de_prueba(self.temp.name)

    def test_genera_pdf_y_qr_por_defecto_en_carpeta_indicada(self):
        with patch.object(documento_pdf, "generar_url_qr", wraps=documento_pdf.generar_url_qr) as generar_qr:
            ruta = generar_pdf(self.datos)
        generar_qr.assert_called_once_with(self.datos)
        self.assertEqual(ruta.parent, Path(self.temp.name))
        self.assertTrue(ruta.read_bytes().startswith(b"%PDF-"))
        self.assertFalse(ruta.with_name(ruta.name + ".tmp").exists())

    def test_sin_carpeta_explicita_usa_la_ruta_del_ambiente(self):
        del self.datos["carpeta_salida"]
        with patch.object(documento_pdf, "carpeta_datos", return_value=Path(self.temp.name)) as carpeta:
            ruta = generar_pdf(self.datos)
        carpeta.assert_called_once_with("testing")
        self.assertEqual(ruta.parent, Path(self.temp.name))

    def test_url_qr_explicita_no_se_recalcula(self):
        with patch.object(documento_pdf, "generar_url_qr") as generar_qr:
            generar_pdf(self.datos, "https://www.arca.gob.ar/fe/qr/?p=prueba")
        generar_qr.assert_not_called()


if __name__ == "__main__":
    unittest.main()
