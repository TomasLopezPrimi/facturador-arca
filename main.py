
import base64
import subprocess
import tempfile
import time
import json
import os
import shutil
import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

from zeep import Client

BASE = Path(__file__).resolve().parent
CERT = BASE / "certificados" / "certificado.pem"
KEY = BASE / "certificados" / "privada.key"

CREDENTIALS_FILE = BASE / "credenciales.json"
ENVIRONMENTS = {
    "testing": {"name": "homologacion", "wsaa": "https://wsaahomo.afip.gov.ar/ws/services/LoginCms?WSDL"},
    "produccion": {"name": "produccion", "wsaa": "https://wsaa.afip.gov.ar/ws/services/LoginCms?WSDL"},
}
ENVIRONMENT = "testing"
SERVICE_WSFE = "wsfe"
SERVICE_PADRON = "ws_sr_constancia_inscripcion"


def buscar_openssl():
    configurado = os.environ.get("OPENSSL_EXECUTABLE")
    if configurado and Path(configurado).is_file():
        return configurado

    encontrado = shutil.which("openssl")
    if encontrado:
        return encontrado

    ubicaciones = [
        Path(os.environ.get("ProgramFiles", "C:/Program Files"))
        / "OpenSSL-Win64" / "bin" / "openssl.exe",
        Path(os.environ.get("ProgramFiles", "C:/Program Files"))
        / "Git" / "usr" / "bin" / "openssl.exe",
        Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)"))
        / "OpenSSL-Win32" / "bin" / "openssl.exe",
    ]
    for ubicacion in ubicaciones:
        if ubicacion.is_file():
            return str(ubicacion)

    raise FileNotFoundError(
        "No se encontrÃ³ OpenSSL. Instala OpenSSL para Windows y agrega "
        "openssl.exe al PATH, o define OPENSSL_EXECUTABLE con su ruta completa. "
        "OpenSSL es un ejecutable del sistema, no un paquete del venv."
    )

def guardar_credenciales(token, sign, vencimiento, service=SERVICE_WSFE, environment=ENVIRONMENT):
    credenciales = {}
    if CREDENTIALS_FILE.exists():
        credenciales = json.loads(CREDENTIALS_FILE.read_text(encoding="utf-8"))

    environment_name = ENVIRONMENTS[environment]["name"]
    credenciales["environment"] = environment_name
    por_ambiente = credenciales.setdefault("services_by_environment", {})
    por_ambiente.setdefault(environment_name, {})[service] = {
        "token": token,
        "sign": sign,
        "expiration_time": vencimiento,
        "service": service,
        "environment": environment_name,
    }
    servicios = credenciales.setdefault("services", {})
    servicios[service] = {
        "token": token,
        "sign": sign,
        "expiration_time": vencimiento,
        "service": service,
        "environment": environment_name,
    }

    # Mantener las claves antiguas para que los scripts WSFE existentes sigan funcionando.
    if service == SERVICE_WSFE:
        credenciales.update(servicios[service])

    temporal = CREDENTIALS_FILE.with_name(CREDENTIALS_FILE.name + ".tmp")
    with open(temporal, "w", encoding="utf-8") as archivo:
        json.dump(credenciales, archivo, indent=2, ensure_ascii=False)
        archivo.flush()
        os.fsync(archivo.fileno())
    os.replace(temporal, CREDENTIALS_FILE)


def obtener_credenciales(service=SERVICE_WSFE, environment=ENVIRONMENT):
    # 1. Preparar solicitud de acceso (TRA)
    ahora = datetime.now(timezone.utc)

    def fecha(dt):
        return dt.isoformat(timespec="seconds")

    tra = f"""<?xml version="1.0" encoding="UTF-8"?>
<loginTicketRequest version="1.0">
  <header>
    <uniqueId>{int(time.time())}</uniqueId>
    <generationTime>{fecha(ahora - timedelta(minutes=10))}</generationTime>
    <expirationTime>{fecha(ahora + timedelta(minutes=10))}</expirationTime>
  </header>
  <service>{service}</service>
</loginTicketRequest>"""

    # Homologación y producción usan certificados distintos.
    cert = CERT if environment == "testing" else BASE / "certificados" / "produccion" / "certificado.pem"
    key = KEY if environment == "testing" else BASE / "certificados" / "produccion" / "privada.key"
    if not cert.is_file() or not key.is_file():
        raise FileNotFoundError(
            f"Falta el certificado o la clave de {ENVIRONMENTS[environment]['name']}. "
            f"Ubicalos en {cert.parent}."
        )

    # 2. Firmar solicitud con OpenSSL
    openssl = buscar_openssl()
    with tempfile.TemporaryDirectory() as temp:
        xml_path = Path(temp) / "tra.xml"
        cms_path = Path(temp) / "tra.cms"

        xml_path.write_text(tra, encoding="utf-8")

        subprocess.run(
            [
                openssl, "cms", "-sign",
                "-in", str(xml_path),
                "-signer", str(cert),
                "-inkey", str(key),
                "-out", str(cms_path),
                "-outform", "DER",
                "-nodetach",
                "-binary",
            ],
            check=True,
            capture_output=True,
        )

        cms = base64.b64encode(
            cms_path.read_bytes()
        ).decode("ascii")

    # 3. Enviar solicitud SOAP a ARCA
    client = Client(ENVIRONMENTS[environment]["wsaa"])
    respuesta = client.service.loginCms(in0=cms)

    # 4. Leer respuesta XML
    root = ET.fromstring(respuesta)

    token = root.findtext(".//credentials/token")
    sign = root.findtext(".//credentials/sign")
    vencimiento = root.findtext(
        ".//header/expirationTime"
    )

    if not token or not sign:
        raise RuntimeError(
            "ARCA no devolviÃ³ credenciales vÃ¡lidas"
        )

    return token, sign, vencimiento


def obtener_credenciales_vigentes(service, environment=ENVIRONMENT):
    environment_name = ENVIRONMENTS[environment]["name"]
    if CREDENTIALS_FILE.exists():
        credenciales = json.loads(CREDENTIALS_FILE.read_text(encoding="utf-8"))
        guardadas = credenciales.get("services_by_environment", {}).get(environment_name, {}).get(service)
        if not guardadas:
            guardadas = credenciales.get("services", {}).get(service)

        # Compatibilidad con el formato previo, que solo guardaba el ticket WSFE.
        if not guardadas and credenciales.get("service") == service:
            guardadas = credenciales

        if guardadas and guardadas.get("environment") == environment_name:
            vencimiento = datetime.fromisoformat(
                guardadas["expiration_time"].replace("Z", "+00:00")
            )
            if vencimiento.tzinfo and datetime.now(timezone.utc) < vencimiento:
                return guardadas

    token, sign, vencimiento = obtener_credenciales(service, environment)
    guardar_credenciales(token, sign, vencimiento, service, environment)
    return {
        "token": token,
        "sign": sign,
        "expiration_time": vencimiento,
        "service": service,
        "environment": environment_name,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Autenticación ARCA WSAA")
    parser.add_argument("--ambiente", choices=ENVIRONMENTS, default=ENVIRONMENT)
    args = parser.parse_args()
    token, sign, vencimiento = obtener_credenciales(environment=args.ambiente)
    guardar_credenciales(token, sign, vencimiento, environment=args.ambiente)
    print("Autenticación exitosa")
    print("Token recibido:", bool(token))
    print("Sign recibido:", bool(sign))
    print("Vencimiento:", vencimiento)
