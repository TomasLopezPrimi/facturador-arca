
import json
from pathlib import Path
from datetime import datetime, timezone
from zeep import Client
from facturador_core import cargar_cuit_emisor

BASE = Path(__file__).resolve().parent

# Exclusivamente homologación
WSFE_WSDL = (
    "https://wswhomo.afip.gov.ar/wsfev1/service.asmx?WSDL"
)

def consultar_tipos_comprobante():
    # 1. Leer credenciales guardadas
    archivo = BASE / "credenciales.json"

    with archivo.open("r", encoding="utf-8") as f:
        credenciales = json.load(f)

    if credenciales.get("environment") != "homologacion":
        raise ValueError("Se requieren credenciales de homologación")

    if credenciales.get("service") != "wsfe":
        raise ValueError("Las credenciales no corresponden a wsfe")

    # 2. Verificar vencimiento
    vencimiento = datetime.fromisoformat(
        credenciales["expiration_time"].replace("Z", "+00:00")
    )

    if vencimiento.tzinfo is None:
        raise ValueError("El vencimiento no contiene zona horaria")

    if datetime.now(timezone.utc) >= vencimiento:
        raise ValueError(
            "Credenciales vencidas. Ejecutá python main.py"
        )

    # 3. Conectar al Web Service SOAP
    client = Client(WSFE_WSDL)

    # 4. Autenticación
    auth = {
        "Token": credenciales["token"],
        "Sign": credenciales["sign"],
        "Cuit": int(cargar_cuit_emisor()),
    }

    # 5. Consultar tipos de comprobantes
    respuesta = client.service.FEParamGetTiposCbte(
        Auth=auth
    )

    # 6. Comprobar errores
    if respuesta.Errors and respuesta.Errors.Err:
        for error in respuesta.Errors.Err:
            print(f"Error {error.Code}: {error.Msg}")
        return

    # 7. Mostrar resultados
    if respuesta.ResultGet and respuesta.ResultGet.CbteTipo:
        for comprobante in respuesta.ResultGet.CbteTipo:
            print(
                f"{comprobante.Id} - {comprobante.Desc}"
            )
    else:
        print("No se recibieron tipos de comprobantes")


if __name__ == "__main__":
    consultar_tipos_comprobante()
