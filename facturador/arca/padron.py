"""Consulta de la constancia de inscripción en el padrón de ARCA."""

from zeep import Client
from zeep.exceptions import Fault

from facturador.almacenamiento import cargar_cuit_emisor
from facturador.arca.wsaa import obtener_credenciales_vigentes


PADRON_WSDL = {
    "testing": "https://awshomo.afip.gov.ar/sr-padron/webservices/personaServiceA5?WSDL",
    "produccion": "https://aws.arca.gob.ar/sr-padron/webservices/personaServiceA5?WSDL",
}
SERVICIO_PADRON = "ws_sr_constancia_inscripcion"


class ErrorConstanciaPadron(RuntimeError):
    """ARCA respondió que no puede emitir la constancia de esta CUIT."""

    def __init__(self, cuit, mensaje):
        self.cuit = str(cuit)
        self.mensaje_arca = str(mensaje)
        texto = self.mensaje_arca.casefold()
        self.permite_carga_manual = (
            "pendiente" in texto
            and ("requerimiento" in texto or "fiscalizacion" in texto or "fiscalización" in texto)
        )
        super().__init__(f"Error de padrón para CUIT {self.cuit}: {self.mensaje_arca}")


def consultar_datos_padron(cuit, ambiente, cuit_representada=None):
    """Consulta nombre y domicilio fiscal en el padrón del ambiente elegido."""
    if not cuit_representada:
        cuit_representada = cargar_cuit_emisor()
    cred = obtener_credenciales_vigentes(SERVICIO_PADRON, ambiente)
    cliente = Client(PADRON_WSDL[ambiente])
    respuesta = cliente.service.getPersona_v2(
        token=cred["token"],
        sign=cred["sign"],
        cuitRepresentada=int(cuit_representada),
        idPersona=int(cuit),
    )

    # Zeep puede desempaquetar el único elemento de respuesta directamente.
    persona = getattr(respuesta, "personaReturn", respuesta)
    error = getattr(persona, "errorConstancia", None)
    if error:
        mensaje = getattr(error, "error", None) or str(error)
        raise ErrorConstanciaPadron(cuit, mensaje)
    generales = getattr(persona, "datosGenerales", None)
    if generales is None:
        raise RuntimeError(f"El padrón no devolvió datos generales para CUIT {cuit}.")
    nombre = getattr(generales, "razonSocial", None)
    if not nombre:
        nombre = " ".join(
            parte for parte in (
                getattr(generales, "apellido", None),
                getattr(generales, "nombre", None),
            ) if parte
        )
    domicilio = getattr(generales, "domicilioFiscal", None)
    if domicilio is None:
        raise RuntimeError(f"El padrón no informó domicilio fiscal para CUIT {cuit}.")
    partes_domicilio = [
        getattr(domicilio, "direccion", None),
        getattr(domicilio, "datoAdicional", None),
        getattr(domicilio, "localidad", None),
        getattr(domicilio, "descripcionProvincia", None),
        getattr(domicilio, "codPostal", None),
    ]
    return {
        "cuit": str(cuit),
        "nombre": nombre or "Nombre no informado",
        "domicilio_fiscal": ", ".join(str(parte) for parte in partes_domicilio if parte),
        "estado": getattr(generales, "estadoClave", None),
        "tipo_persona": getattr(generales, "tipoPersona", None),
        "fuente": f"ARCA padrón {'homologación' if ambiente == 'testing' else 'producción'}",
    }
