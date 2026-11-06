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
   .\.venv\Scripts\python.exe facturador_app.py
   ```

4. Abrí la pestaña **Configuración** y completá tu CUIT, punto de venta, nombre o razón social, domicilio comercial, condición frente al IVA, Ingresos Brutos e inicio de actividades. Guardá los cambios: se crea `config_facturador.json` únicamente en tu copia local. No hay un CUIT personal predeterminado en el código.
5. En **Certificados y tickets**, revisá el estado y obtené los tickets del ambiente que necesites. `credenciales.json` se genera automáticamente; no se debe completar con tokens de otra persona.
6. Empezá con **Homologación**. Cargá tus receptores y una operación de prueba, revisá el resumen y confirmá solo cuando los datos sean correctos. Los comprobantes de este ambiente se marcan **SIN VALIDEZ FISCAL**.

**Atención:** el botón **Ver fiscal en ARCA** prioriza el padrón de producción incluso durante homologación, por lo que puede consultar datos reales si tenés acceso habilitado. Esto no cambia el ambiente de emisión. Si no puede acceder a producción, intenta homologación e identifica los datos como de prueba.

### Producción

**Solicitar un CAE en producción puede generar un comprobante fiscal real.** Verificá previamente certificados, autorizaciones, punto de venta, datos de las partes y normativa vigente. Las credenciales de homologación no sirven para producción.

Si hay un corte de conexión o no se confirma la respuesta de ARCA, utilizá **Recuperar solicitud pendiente** antes de volver a emitir. No borres el pendiente ni reenvíes una operación sin verificar su estado.

### Uso por consola

La interfaz gráfica es el punto de entrada principal. También se incluyen scripts de consola:

```powershell
# Autenticación WSAA en homologación
.\.venv\Scripts\python.exe main.py --ambiente testing

# Consultas de homologación; requieren configuración y tickets propios
.\.venv\Scripts\python.exe consultar_wsfe.py
.\.venv\Scripts\python.exe consultar_puntos_venta.py

# Emisión interactiva en homologación; usa la configuración local guardada
.\.venv\Scripts\python.exe emitir_factura.py --ambiente testing
```

## Datos locales y privacidad

Los archivos de ejecución se guardan junto al código:

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

El `.gitignore` excluye estos datos, certificados, claves, temporales, capturas, vistas previas, páginas de trámites guardadas y entornos virtuales. Por precaución también excluye archivos JSON, PDF, XML, imágenes, planillas y copias comprimidas en cualquier carpeta. Si incorporás recursos públicos de esos tipos en el futuro, revisalos antes de permitirlos explícitamente.

**El `.gitignore` no cifra archivos, no detecta secretos dentro del código y no elimina nada que ya esté versionado o publicado.** No uses `git add -f` para incluir datos locales. Protegé el acceso a la carpeta y conservá copias de seguridad cifradas fuera del repositorio.

Antes de tu primer commit, revisá qué va a publicarse:

```powershell
git status --short --untracked-files=all
git add .
git diff --cached --name-only
git diff --cached
```

Si un secreto llegó a publicarse, eliminarlo del último commit no alcanza: revocá o reemplazá la credencial afectada y revisá el historial del repositorio.

## Organización

| Archivo | Responsabilidad |
| --- | --- |
| `facturador_app.py` | Interfaz Tkinter y bloqueo de instancia en Windows. |
| `facturador_core.py` | Configuración local, validaciones, preparación, solicitud de CAE y recuperación. |
| `main.py` | Autenticación WSAA y persistencia de tickets por ambiente y servicio. |
| `emitir_factura.py` | Integración con WSFE y padrón, URL del QR y emisión por consola. |
| `facturador_detalle.py` | Validación de renglones y cálculo de importes. |
| `facturador_pdf.py` | Diseño y generación de PDF. |
| `consultar_wsfe.py` / `consultar_puntos_venta.py` | Consultas auxiliares de homologación. |
| `test_facturador_*.py` | Pruebas unitarias con servicios simulados y datos sintéticos. |

## Pruebas

```powershell
.\.venv\Scripts\python.exe -m pip install pypdf
.\.venv\Scripts\python.exe -m unittest -v
```

Las pruebas no emiten comprobantes ni necesitan credenciales reales. Utilizan servicios simulados y carpetas temporales. Si `pypdf` no está instalado, se omiten las pruebas de lectura de PDF.

## Alcance y limitaciones

- Solo comprobantes C y pesos argentinos; no contempla comprobantes A/B, moneda extranjera ni liquidación de impuestos.
- Cada comprobante es de productos o de servicios, sin mezclar ambos conceptos. El servicio previsto actualmente es **620900 - Servicios de informática N.C.P.**, acorde a mi uso personal.
- No reemplaza un sistema contable, asesoramiento profesional ni la verificación de la normativa vigente. Los parámetros fiscales implementados pueden requerir actualizaciones.
- Está pensado para uso individual en una computadora, no para múltiples usuarios o procesos concurrentes compartiendo un punto de venta.
- La persistencia es local y no incluye cifrado propio ni gestión de usuarios.

Para más información, consultá [USO_FACTURADOR.md](USO_FACTURADOR.md), [FACTURACION_PRODUCCION.md](FACTURACION_PRODUCCION.md) y la [documentación oficial de Web Services de ARCA](https://www.arca.gob.ar/ws/).
