"""Consulta de puntos de venta, exclusivamente en homologación."""

import argparse

from facturador.arca.wsfe import autenticar, crear_cliente_wsfe

def consultar_puntos_venta():
    auth = autenticar("testing")
    client = crear_cliente_wsfe("testing")

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


def main(argv=None):
    parser = argparse.ArgumentParser(description="Consulta de puntos de venta en homologación")
    parser.parse_args(argv)
    consultar_puntos_venta()


if __name__ == "__main__":
    main()
