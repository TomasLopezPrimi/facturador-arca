"""Rutas locales, independientes del directorio desde el que se ejecute Python."""

from pathlib import Path


# Los datos privados permanecen en la raíz para conservar las instalaciones previas.
BASE = Path(__file__).resolve().parent.parent
CONFIG_PATH = BASE / "config_facturador.json"
RECEPTORES_PATH = BASE / "receptores.json"
CREDENTIALS_FILE = BASE / "credenciales.json"
CERT = BASE / "certificados" / "certificado.pem"
KEY = BASE / "certificados" / "privada.key"


def carpeta_datos(ambiente):
    return BASE / ("facturas_test" if ambiente == "testing" else "facturas_produccion")
