"""Autenticación WSAA desde la consola."""

import argparse

from facturador.arca.wsaa import (
    ENVIRONMENT, ENVIRONMENTS, guardar_credenciales, obtener_credenciales,
)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Autenticación ARCA WSAA")
    parser.add_argument("--ambiente", choices=ENVIRONMENTS, default=ENVIRONMENT)
    args = parser.parse_args(argv)
    token, sign, vencimiento = obtener_credenciales(environment=args.ambiente)
    guardar_credenciales(token, sign, vencimiento, environment=args.ambiente)
    print("Autenticación exitosa")
    print("Token recibido:", bool(token))
    print("Sign recibido:", bool(sign))
    print("Vencimiento:", vencimiento)


if __name__ == "__main__":
    main()
