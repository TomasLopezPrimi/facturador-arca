
import json
from pathlib import Path
from zeep import Client
from facturador_core import cargar_cuit_emisor

BASE = Path(__file__).resolve().parent

# Exclusivamente homologación
WSFE_WSDL = (
    "https://wswhomo.afip.gov.ar/wsfev1/service.asmx?WSDL"
)

def consultar_puntos_venta():
    # Leer credenciales existentes
    with open(BASE / "credenciales.json", encoding="utf-8") as f:
        credenciales = json.load(f)

    if credenciales.get("environment") != "homologacion":
        raise ValueError("Credenciales de entorno incorrecto")

    auth = {
        "Token": credenciales["token"],
        "Sign": credenciales["sign"],
        "Cuit": int(cargar_cuit_emisor()),
    }

    client = Client(WSFE_WSDL)

    # Consultar puntos de venta
    respuesta = client.service.FEParamGetPtosVenta(Auth=auth)

    # Mostrar errores de ARCA
    if respuesta.Errors and respuesta.Errors.Err:
        for error in respuesta.Errors.Err:
            print(f"Error {error.Code}: {error.Msg}")

    # Mostrar puntos de venta
    if respuesta.ResultGet and respuesta.ResultGet.PtoVenta:
        print("\nPuntos de venta encontrados:\n")

        for pv in respuesta.ResultGet.PtoVenta:
            print(f"Punto de venta: {pv.Nro}")
            print(f"Tipo emisión: {pv.EmisionTipo}")
            print(f"Bloqueado: {pv.Bloqueado}")
            print(f"Fecha de baja: {pv.FchBaja}")
            print("-" * 30)
    else:
        print("No se encontraron puntos de venta")


if __name__ == "__main__":
    consultar_puntos_venta()
