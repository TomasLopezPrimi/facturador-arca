"""Cliente SOAP de facturación electrónica y autenticación WSFE."""

import json
import ssl
from datetime import datetime, timezone

from requests.adapters import HTTPAdapter
from zeep import Client
from zeep.transports import Transport

from facturador.almacenamiento import cargar_cuit_emisor
from facturador.arca.wsaa import obtener_credenciales_vigentes
from facturador.constantes import TIPO_FACTURA
from facturador.rutas import CREDENTIALS_FILE
from facturador.validaciones import validar_cuit


WSFE_WSDL = {
    "testing": "https://wswhomo.afip.gov.ar/wsfev1/service.asmx?WSDL",
    "produccion": "https://servicios1.afip.gov.ar/wsfev1/service.asmx?WSDL",
}


class _CompatibilidadTlsArcaAdapter(HTTPAdapter):
    """Admite el DH débil del WSFE de producción sin desactivar TLS/verificación."""

    def __init__(self, ca_bundle):
        self.ca_bundle = ca_bundle
        super().__init__()

    def init_poolmanager(self, connections, maxsize, block=False, **pool_kwargs):
        context = ssl.create_default_context()
        context.load_verify_locations(cafile=self.ca_bundle)
        context.set_ciphers("DEFAULT:@SECLEVEL=1")
        pool_kwargs["ssl_context"] = context
        super().init_poolmanager(connections, maxsize, block=block, **pool_kwargs)


def crear_cliente_wsfe(ambiente):
    """Crea WSFE; limita el ajuste de TLS al host de producción de ARCA."""
    if ambiente not in WSFE_WSDL:
        raise ValueError(f"Ambiente WSFE desconocido: {ambiente}")

    if ambiente == "produccion":
        import requests

        session = requests.Session()
        session.mount(
            "https://servicios1.afip.gov.ar/",
            _CompatibilidadTlsArcaAdapter(requests.certs.where()),
        )
        return Client(WSFE_WSDL[ambiente], transport=Transport(session=session))

    return Client(WSFE_WSDL[ambiente])


def auth_wsfe(ambiente, cuit_emisor=None):
    cuit_emisor = validar_cuit(cuit_emisor) if cuit_emisor else cargar_cuit_emisor()
    credenciales = obtener_credenciales_vigentes("wsfe", ambiente)
    return {"Token": credenciales["token"], "Sign": credenciales["sign"], "Cuit": int(cuit_emisor)}


def autenticar(ambiente):
    """Lee un ticket existente sin renovarlo (compatibilidad con consultas auxiliares)."""
    cuit_emisor = cargar_cuit_emisor()
    cred = json.loads(CREDENTIALS_FILE.read_text(encoding="utf-8"))
    cred = cred.get("services", {}).get("wsfe", cred)
    if cred.get("environment") != ("homologacion" if ambiente == "testing" else "produccion"):
        raise ValueError("Entorno incorrecto")
    if cred.get("service") != "wsfe":
        raise ValueError("Credenciales de otro servicio")
    vencimiento = datetime.fromisoformat(cred["expiration_time"].replace("Z", "+00:00"))
    if vencimiento.tzinfo is None:
        raise ValueError("Vencimiento sin zona horaria")
    if datetime.now(timezone.utc) >= vencimiento:
        raise ValueError("Credenciales vencidas. Ejecutá python -m facturador.cli.autenticar")
    return {"Token": cred["token"], "Sign": cred["sign"], "Cuit": int(cuit_emisor)}


def comprobar_errores(respuesta):
    errores = getattr(respuesta, "Errors", None)
    if errores and errores.Err:
        for error in errores.Err:
            print(f"ARCA error {error.Code}: {error.Msg}")
        raise RuntimeError("ARCA devolvió errores")


def consultar_factura_original(client, auth, punto, numero, receptor):
    """Verifica por WSFE que exista una Factura C autorizada para el receptor."""
    respuesta = client.service.FECompConsultar(
        Auth=auth,
        FeCompConsReq={"CbteTipo": TIPO_FACTURA, "PtoVta": punto, "CbteNro": numero},
    )
    comprobar_errores(respuesta)
    original = getattr(respuesta, "ResultGet", None)
    if not original or not getattr(original, "CodAutorizacion", None):
        raise ValueError("ARCA no encontró una Factura C autorizada con esos datos.")
    if int(original.DocTipo) != 80 or str(original.DocNro) != str(receptor):
        raise ValueError("La factura original no corresponde al CUIT receptor indicado.")
    return original
