# Facturador ARCA (uso personal)

Iniciá **Facturador ARCA** con `python facturador_app.py` desde tu entorno virtual, o desde un acceso directo que hayas creado. Es una aplicación local con Tkinter para **Factura C** y **Nota de crédito C**. No tiene usuarios, servidor ni acceso compartido. Usa tu sesión de Windows. La instalación y configuración con credenciales propias se explican en [README.md](README.md).

## Primer uso

1. En **Configuración**, cargá el CUIT emisor y el punto de venta habilitado para **Web Services / WSFE**, nombre o razón social y domicilio comercial. Elegí la condición frente al IVA y el régimen de Ingresos Brutos en las listas. Si corresponde, ingresá el número de inscripción IIBB. Seleccioná el inicio de actividades en el calendario. Al cambiar de CUIT, revisá también todos estos datos del emisor antes de guardar.
   - Junto al domicilio del emisor, **Ver fiscal en ARCA** consulta el padrón del ambiente elegido. ARCA devuelve el domicilio fiscal; confirmá si coincide con el comercial antes de copiarlo. Después guardá la configuración.
2. Guardá la configuración. Se crea `config_facturador.json` en esta carpeta.
3. En **Emitir comprobante**, empezá por **testing**. Elegí CUIT, DNI o Sin documento y cargá los datos del receptor. En **Productos / servicios**, usá **Agregar renglón** para ingresar descripción, código opcional, cantidad, unidad de medida y precio unitario. Podés editar o quitar renglones; el importe total se calcula automáticamente. Si elegís consumidor final sin documento, el importe debe ser inferior a $10.000.000.
   - Las cantidades admiten hasta seis decimales y los precios hasta dos. Cada renglón se redondea a centavos y el total es la suma de esos importes.
   - Para servicios, indicá el período y el **Vencimiento para el pago**. Esta fecha puede ser futura, no puede ser anterior a la emisión y se utiliza tanto en WSFE como en el PDF. Es independiente del vencimiento del CAE que otorga ARCA.
   - Para receptores con CUIT, **Ver fiscal en ARCA** puede completar nombre y domicilio tras tu confirmación. Para DNI o sin documento no hay consulta de padrón por CUIT.
   - Aunque estés emitiendo en homologación, el botón prioriza el padrón de **producción** para traer datos reales. Esto no cambia el ambiente de emisión. La consulta requiere certificado y servicio de padrón de producción habilitados. Si todavía faltan, intenta el padrón de prueba y lo identifica claramente; si tu CUIT no figura allí, podés completar los datos manualmente.
4. Para una nota de crédito, indicá el punto de venta y número de la Factura C original. El programa comprueba que exista en ARCA y que corresponda al receptor.
5. Revisá el resumen con el próximo número asignado por ARCA. El botón de confirmación es el que solicita el CAE.
6. Los PDF y JSON quedan en `facturas_test/<CUIT>` o `facturas_produccion/<CUIT>`, según el ambiente y CUIT emisor. Los comprobantes creados antes de esta versión permanecen en la carpeta principal de cada ambiente. Los PDF de homologación dicen **SIN VALIDEZ FISCAL**.
   - Se genera una única copia **ORIGINAL**. Cuando el contenido ocupa más de una página, continúa con identificación del comprobante, encabezado del detalle y CAE. Los nombres, domicilios y descripciones se ajustan al espacio sin recortarse.
   - Los registros anteriores siguen siendo compatibles: se representan con un renglón de cantidad 1 y, para servicios, el vencimiento de pago coincide con la fecha de emisión que enviaba la versión anterior. Los comprobantes existentes no se modifican automáticamente.
7. En **Certificados y tickets** podés revisar la presencia de certificados y la vigencia de los tickets WSFE y padrón en cada ambiente. **Obtener o renovar tickets** consulta WSAA y guarda los que falten o hayan vencido. La pantalla nunca muestra el contenido de los tokens.
   - Mientras no tengas acceso automático al padrón de producción, **Abrir constancia pública de ARCA** permite verificar manualmente un CUIT en el sitio oficial. La página solicita un código de seguridad y los datos deben copiarse luego al facturador.

## Producción

Los certificados de homologación sirven únicamente para pruebas. El repositorio no incluye certificados ni claves: cada usuario debe obtener los propios. Para emitir comprobantes fiscales reales necesitás:

- un certificado digital de **producción** y su clave en `certificados/produccion/certificado.pem` y `certificados/produccion/privada.key`;
- el servicio **wsfe** y **ws_sr_constancia_inscripcion** habilitados para el CUIT emisor seleccionado en producción; si usás otro CUIT, el certificado debe estar autorizado para representarlo;
- un punto de venta de Web Services habilitado en ARCA.

El programa obtiene y renueva los tickets WSAA automáticamente. No copies certificados ni claves a otra computadora sin protegerlos. La clave privada y los tickets ya existentes son archivos locales, por lo que conviene restringir esta carpeta a tu usuario de Windows y hacer copias de seguridad cifradas.

## Respuestas inciertas

Si se interrumpe la conexión al pedir CAE, la solicitud queda registrada en `solicitud_pendiente.json`. Usá **Recuperar solicitud pendiente** antes de intentar otra emisión. El programa consulta el mismo tipo, punto de venta y número en ARCA. Si todavía no figura autorizado, mantiene el pendiente para revisión; no lo reenvía automáticamente.

## Alcance actual

- Moneda: pesos argentinos.
- Receptores: CUIT, DNI o consumidor final sin documento. Desde $10.000.000, el consumidor final debe identificarse. Otros documentos, moneda extranjera, descuentos, impuestos adicionales o comprobantes A/B requieren ampliar el programa.
- El detalle admite varios productos o servicios y unidades (unidad, servicio, mes, hora, día, kg, litro y metro). La operación sigue siendo de Productos o de Servicios, sin mezclar ambos conceptos en un comprobante.
- No hay libro contable ni liquidación de impuestos.

## Archivos principales

- `facturador_app.py`: interfaz Tkinter.
- `facturador_core.py`: validación, consulta y solicitud de CAE.
- `main.py`: autenticación WSAA.
- `emitir_factura.py`: integración previa y generación de PDF/QR.
- `facturador_pdf.py`: representación gráfica y paginación del PDF.
- `facturador_detalle.py`: validación y cálculo de los renglones.

## Verificación local

`python -m unittest -v` ejecuta las pruebas sin emitir comprobantes. Las pruebas de lectura del PDF requieren `pypdf` como dependencia de desarrollo; sin ella se omiten esas pruebas. La aplicación utiliza ReportLab para generar los PDF.

Documentación oficial: [solicitud de autorización](https://arca.gob.ar/fe/emision-autorizacion/solicitud-autorizacion.asp), [datos del comprobante](https://www.arca.gob.ar/fe/emision-autorizacion/datos-comprobantes.asp), [certificados digitales](https://www.arca.gob.ar/ws/programadores/certificados-digitales.asp), [manual WSFEv1](https://www.arca.gob.ar/fe/ayuda/documentos/wsfev1-RG-4291.pdf).
