"""Consulta de tipos de comprobante, exclusivamente en homologación."""

import argparse

from facturador.arca.wsfe import autenticar, crear_cliente_wsfe

def consultar_tipos_comprobante():
    auth = autenticar("testing")
    client = crear_cliente_wsfe("testing")

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


def main(argv=None):
    parser = argparse.ArgumentParser(description="Consulta de tipos de comprobante en homologación")
    parser.parse_args(argv)
    consultar_tipos_comprobante()


if __name__ == "__main__":
    main()
