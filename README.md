# Facturador ARCA

Aplicación local de escritorio en Python para emitir **Facturas C** y **Notas de crédito C** mediante los Web Services de ARCA, con comprobantes en PDF y código QR.

Es un **proyecto personal, pensado para mi propio día a día**. Lo comparto como referencia y para quien quiera adaptarlo a sus necesidades: no es un producto oficial de ARCA, un servicio de facturación ni una solución contable de propósito general.

**Quien quiera usarlo tiene que configurar sus propias credenciales, certificados y datos fiscales**, además de los datos de sus receptores. El repositorio no incluye los míos ni comprobantes emitidos.

## Qué permite hacer

- Emitir Factura C y Nota de crédito C, con revisión y confirmación antes de solicitar el CAE.
- Trabajar en homologación (`testing`) o producción, con certificados separados.
- Cargar productos o servicios con varios renglones, cantidades, unidades y precios; calcular importes con `Decimal`.
- Indicar período de servicios, vencimiento para el pago y condición de venta.
- Consultar datos del padrón de ARCA y confirmar su uso en el formulario.
- Guardar una libreta local de receptores.
- Obtener y renovar tickets de autenticación WSAA.
- Guardar los comprobantes en JSON y PDF con QR, CAE y paginación.
- Recuperar una solicitud de resultado incierto sin reenviarla automáticamente.

No tiene servidor, cuentas de usuario ni almacenamiento en la nube. **Sí requiere conexión a Internet** para autenticarse y operar con ARCA.

## Requisitos

- **Windows** y **Python 3.11 o posterior**, con Tkinter. La versión actual utiliza `msvcrt`, `os.startfile` y las fuentes Arial de `C:/Windows/Fonts`; no está preparada para ejecutarse sin cambios en Linux o macOS.
- **OpenSSL** instalado como ejecutable del sistema, disponible en el `PATH` o indicado mediante la variable `OPENSSL_EXECUTABLE`.
- Paquetes Python: `zeep`, `requests` y `reportlab`. Para las pruebas de lectura de PDF, también `pypdf`.
- CUIT propio o autorizado, certificados digitales y servicios de ARCA habilitados para el ambiente correspondiente.
- Punto de venta habilitado para **Web Services / WSFE**.

## Instalación

Desde la carpeta del proyecto, en PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install zeep requests reportlab
```

No es necesario activar el entorno si usás su ejecutable directamente. Actualmente no hay un archivo de dependencias con versiones fijadas.

Si OpenSSL no está en el `PATH`, podés indicar su ubicación para la sesión actual; adaptá esta ruta a tu instalación:

```powershell
$env:OPENSSL_EXECUTABLE = "C:\Program Files\OpenSSL-Win64\bin\openssl.exe"
```

## Configuración propia y primer uso

1. Generá tu clave privada y obtené tu certificado en ARCA. Habilitá los servicios `wsfe` y `ws_sr_constancia_inscripcion` para el CUIT que vas a representar. Homologación y producción requieren su configuración y certificados correspondientes.
2. Colocá **tus propios archivos**, con estos nombres:

   ```text
   certificados/
   ├── certificado.pem          # Homologación
   ├── privada.key              # Homologación
   └── produccion/
       ├── certificado.pem      # Producción
       └── privada.key          # Producción
   ```

   Estas carpetas y archivos son privados y están excluidos de Git.

3. Iniciá la aplicación:

   ```powershell
   .\.venv\Scripts\python.exe -m facturador
   ```

   El archivo `facturador_app.py` también sigue funcionando como lanzador para accesos directos existentes.

4. Abrí la pestaña **Configuración** y completá tu CUIT, punto de venta, nombre o razón social, domicilio comercial, condición frente al IVA, Ingresos Brutos e inicio de actividades. Guardá los cambios: se crea `config_facturador.json` únicamente en tu copia local. No hay un CUIT personal predeterminado en el código.
5. En **Certificados y tickets**, revisá el estado y obtené los tickets del ambiente que necesites. `credenciales.json` se genera automáticamente; no se debe completar con tokens de otra persona.
6. Empezá con **Homologación**. Cargá tus receptores y una operación de prueba, revisá el resumen y confirmá solo cuando los datos sean correctos. Los comprobantes de este ambiente se marcan **SIN VALIDEZ FISCAL**.

**Atención:** el botón **Ver fiscal en ARCA** prioriza el padrón de producción incluso durante homologación, por lo que puede consultar datos reales si tenés acceso habilitado. Esto no cambia el ambiente de emisión. Si no puede acceder a producción, intenta homologación e identifica los datos como de prueba.

### Producción

**Solicitar un CAE en producción puede generar un comprobante fiscal real.** Verificá previamente certificados, autorizaciones, punto de venta, datos de las partes y normativa vigente. Las credenciales de homologación no sirven para producción.

Si hay un corte de conexión o no se confirma la respuesta de ARCA, utilizá **Recuperar solicitud pendiente** antes de volver a emitir. No borres el pendiente ni reenvíes una operación sin verificar su estado.

### Uso por consola

La interfaz gráfica es el punto de entrada principal. Los comandos de consola se ejecutan desde la raíz del proyecto; todos admiten `--help`:

```powershell
# Autenticación WSAA en homologación
.\.venv\Scripts\python.exe -m facturador.cli.autenticar --ambiente testing

# Consultas de homologación; requieren configuración y tickets propios
.\.venv\Scripts\python.exe -m facturador.cli.consultar_wsfe
.\.venv\Scripts\python.exe -m facturador.cli.consultar_puntos_venta

# Emisión interactiva en homologación; usa la configuración local guardada
.\.venv\Scripts\python.exe -m facturador.cli.emitir --ambiente testing
```

## Datos locales y privacidad

Los archivos de ejecución permanecen en la **raíz del proyecto**, fuera del paquete `facturador/`. La reorganización no requiere mover ni migrar los datos existentes. Las rutas se resuelven en `facturador/rutas.py`, no desde el directorio de trabajo actual:

| Archivo o carpeta | Contenido |
| --- | --- |
| `config_facturador.json` | Datos fiscales y configuración del emisor. |
| `credenciales.json` | Tickets WSAA: tokens, firmas y vencimientos. |
| `receptores.json` | Documentos, nombres, domicilios y condiciones fiscales de los receptores guardados. |
| `certificados/` | Certificados y claves privadas de cada ambiente. |
| `facturas_test/<CUIT>/` | Comprobantes de homologación en JSON y PDF. |
| `facturas_produccion/<CUIT>/` | Comprobantes reales en JSON y PDF. |
| `facturas_test/solicitud_pendiente.json` o `facturas_produccion/solicitud_pendiente.json` | Operación pendiente de confirmar en cada ambiente. |

Los comprobantes anteriores pueden estar directamente en la carpeta de su ambiente. Tanto los PDF como los JSON y los QR pueden contener información personal o fiscal, incluso en homologación.



## Organización

```text
facturador/
├── __main__.py           # Inicio con python -m facturador
├── rutas.py              # Rutas de datos locales y certificados
├── constantes.py         # Tipos y opciones fiscales
├── almacenamiento.py     # Configuración, receptores y escritura JSON
├── validaciones.py       # Validaciones sin archivos ni conexiones
├── detalle.py            # Renglones e importes con Decimal
├── servicios.py          # Preparación, emisión y recuperación
├── arca/
│   ├── wsaa.py           # Autenticación y tickets
│   ├── wsfe.py           # Cliente de facturación
│   └── padron.py         # Consulta de contribuyentes
├── documentos/
│   ├── pdf.py            # Diseño y paginación
│   └── qr.py             # Payload oficial del QR
├── ui/
│   ├── app.py            # Interfaz y bloqueo de instancia
│   └── calendario.py     # Selector de fechas
└── cli/                  # Comandos de consola
tests/                    # Pruebas y helpers sintéticos compartidos
docs/                     # Guías de uso y facturación
facturador_app.py          # Lanzador compatible con accesos directos
```

La interfaz y la consola usan los mismos servicios. Las validaciones y los cálculos no dependen de Tkinter, los clientes SOAP ni el almacenamiento. Los clientes de ARCA no importan la interfaz ni los comandos de consola.

## Pruebas

```powershell
.\.venv\Scripts\python.exe -m pip install pypdf
.\.venv\Scripts\python.exe -m unittest discover -s tests -t . -v
```

Las pruebas no emiten comprobantes ni necesitan credenciales reales. Utilizan servicios simulados y carpetas temporales; los datos compartidos están en `tests/helpers.py`. También funciona el descubrimiento automático con `python -m unittest -v`. Si `pypdf` no está instalado, se omiten las pruebas de lectura de PDF.

## Alcance y limitaciones

- Solo comprobantes C y pesos argentinos; no contempla comprobantes A/B, moneda extranjera ni liquidación de impuestos.
- Cada comprobante es de productos o de servicios, sin mezclar ambos conceptos. El servicio previsto actualmente es **620900 - Servicios de informática N.C.P.**, acorde a mi uso personal.
- No reemplaza un sistema contable, asesoramiento profesional ni la verificación de la normativa vigente. Los parámetros fiscales implementados pueden requerir actualizaciones.
- Está pensado para uso individual en una computadora, no para múltiples usuarios o procesos concurrentes compartiendo un punto de venta.
- La persistencia es local y no incluye cifrado propio ni gestión de usuarios.

Para más información, consultá [USO_FACTURADOR.md](docs/USO_FACTURADOR.md), [FACTURACION_PRODUCCION.md](docs/FACTURACION_PRODUCCION.md) y la [documentación oficial de Web Services de ARCA](https://www.arca.gob.ar/ws/).
