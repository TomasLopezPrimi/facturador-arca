"""Lectura y escritura de la configuración y la libreta locales."""

import json
import os

from facturador.rutas import CONFIG_PATH, RECEPTORES_PATH
from facturador.validaciones import validar_cuit


def guardar_json_atomico(ruta, datos):
    ruta.parent.mkdir(parents=True, exist_ok=True)
    temporal = ruta.with_name(ruta.name + ".tmp")
    with open(temporal, "w", encoding="utf-8") as archivo:
        json.dump(datos, archivo, ensure_ascii=False, indent=2, default=str)
        archivo.flush()
        os.fsync(archivo.fileno())
    os.replace(temporal, ruta)


def cargar_config():
    if not CONFIG_PATH.exists():
        return {}
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def cargar_cuit_emisor():
    config = cargar_config()
    if not config.get("cuit_emisor"):
        raise ValueError("Configurá y guardá tu CUIT emisor en Configuración antes de continuar.")
    return validar_cuit(config["cuit_emisor"])


def cargar_receptores():
    if not RECEPTORES_PATH.exists():
        return []
    receptores = json.loads(RECEPTORES_PATH.read_text(encoding="utf-8"))
    if not isinstance(receptores, list):
        raise ValueError("El archivo de receptores guardados no tiene un formato válido.")
    campos = ("id", "documento_tipo", "documento", "nombre", "domicilio", "iva")
    identificadores = set()
    for receptor in receptores:
        if not isinstance(receptor, dict) or any(campo not in receptor for campo in campos):
            raise ValueError("El archivo de receptores guardados no tiene un formato válido.")
        receptor["id"] = str(receptor["id"]).strip()
        if not receptor["id"] or receptor["id"] in identificadores:
            raise ValueError("El archivo de receptores guardados contiene identificadores inválidos.")
        identificadores.add(receptor["id"])
        for campo in campos[1:]:
            receptor[campo] = str(receptor[campo])
    return receptores


def guardar_receptores(receptores):
    guardar_json_atomico(RECEPTORES_PATH, receptores)
