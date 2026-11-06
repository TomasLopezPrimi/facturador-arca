# Facturación electrónica: requisitos y controles esenciales

Instalación y estructura del código: [README.md](../README.md).

Resumen de referencia para preparar la emisión por WSFE. La clase del comprobante será un parámetro del sistema; los requisitos concretos varían según la clase, la condición fiscal del emisor y del receptor, y la operación. Verificar la normativa vigente antes de habilitar producción.

## 1. Datos obligatorios del comprobante

### Emisor y comprobante

1. Nombre y apellido o razón social del emisor.
2. Domicilio comercial del emisor.
3. CUIT del emisor.
4. Número de inscripción en Ingresos Brutos o indicación de que no es contribuyente.
5. Leyenda de condición frente al IVA que corresponda al emisor.
6. Punto de venta y número correlativo del comprobante.
7. Fecha de inicio de actividades correspondiente al local o punto de venta, con la leyenda **“INICIO DE ACTIVIDADES”**.
8. Clase y tipo de comprobante.
9. Fecha de emisión.
10. CAE otorgado por ARCA y fecha de vencimiento del CAE.
11. Código QR con los datos del comprobante, según la especificación de ARCA.
12. Para comprobantes electrónicos de la RG 4291, su artículo 14 exceptúa las leyendas **ORIGINAL** y **DUPLICADO** del régimen general. El facturador conserva **ORIGINAL** y genera una única copia, con páginas de continuación si el contenido lo requiere.
13. Número de remito, si existe uno vinculado con la operación.

### Receptor

Los datos identificatorios dependen de la condición del receptor:

- **Responsable inscripto:** nombre o razón social, domicilio comercial, CUIT y leyenda de condición IVA correspondiente.
- **Exento o no alcanzado:** nombre o razón social, domicilio comercial, CUIT y leyenda correspondiente.
- **Monotributista:** nombre o razón social, domicilio comercial, CUIT y leyenda de su categoría aplicable.
- **Consumidor final:** leyenda **“A CONSUMIDOR FINAL”**. Al 15/10/2026, si la operación es igual o superior a **$10.000.000**, debe informarse CUIT, CUIL, CDI o documento admitido. También debe identificarse si el consumidor lo solicita para computar una deducción admitida en Ganancias, sin importar ese umbral. Nombre y domicilio pueden informarse o completarse con “NR”/ceros cuando el sistema lo requiera.

### Operación e importes

1. Descripción suficiente para identificar el bien vendido, servicio prestado, obra, locación o trabajo realizado.
2. Cantidad de bienes y, cuando corresponda, unidad de medida.
3. Precio unitario y total de los bienes o servicios.
4. Descuentos, recargos, tributos y cualquier otro concepto que incida en el importe total.
5. Importe total de la operación.
6. Moneda y tipo de cambio usado cuando la operación esté expresada en moneda extranjera.
7. Tratamiento del IVA y demás datos impositivos que correspondan a la clase y condición de las partes. No discriminar ni calcular IVA como si el emisor fuera responsable inscripto cuando no corresponda.
8. Para servicios u operaciones con requisitos especiales, fechas o leyendas adicionales que establezca la normativa aplicable.

La representación gráfica debe ser legible e incluir los datos exigidos aunque WSFE no reciba el detalle de ítems para todos los tipos de comprobante. La RG 1415 establece los datos generales del emisor, receptor y operación; la RG 4892 establece el QR para los comprobantes electrónicos alcanzados.

## 2. Verificación de los datos del receptor

Antes de emitir:

1. Validar el formato y dígito verificador del CUIT/CUIL/CDI cuando corresponda.
2. Consultar `ws_sr_constancia_inscripcion` en el mismo ambiente que se utilizará para emitir.
3. Confirmar que el CUIT devuelto coincida con el consultado y que el estado de la clave sea activo.
4. Comparar nombre o razón social y domicilio fiscal con los datos informados por el cliente. El domicilio fiscal obtenido del padrón no necesariamente es el domicilio comercial o de entrega.
5. Revisar la información tributaria para cargar correctamente la condición del receptor en WSFE. No inferirla solo por el texto del nombre o por un CUIT válido.
6. Si el padrón no responde, devuelve un error o no encuentra el CUIT, no completar silenciosamente datos de producción: solicitar revisión o corrección antes de emitir.
7. Guardar junto con la operación los datos verificados, la fecha/hora de consulta y el origen de los datos para auditoría.

La consulta al padrón ayuda a validar identidad y situación registral; no reemplaza la confirmación del domicilio comercial o de entrega cuando sean distintos.

## 3. Recuperación de respuestas inciertas y prevención de duplicados

Un timeout al solicitar el CAE no demuestra que ARCA haya rechazado el comprobante: puede haberlo autorizado y haberse perdido la respuesta. **No reenviar automáticamente la solicitud.**

1. Antes de llamar a `FECAESolicitar`, guardar de forma durable el contenido de la solicitud, el CUIT emisor, punto de venta, tipo y número de comprobante, fecha e importe, con estado `pendiente`.
2. Si la llamada responde con timeout, desconexión o error de transporte, consultar `FECompConsultar` usando el mismo punto de venta, tipo y número.
3. Si ARCA informa que el comprobante existe y tiene CAE, guardar esa respuesta y finalizar la generación del JSON y PDF con los datos autorizados. No volver a solicitar otro CAE para esa operación.
4. Si todavía no aparece, volver a consultar tras una espera breve. Solo después de confirmar que no fue autorizado, revisar el último número autorizado y decidir si se reintenta la misma operación.
5. Antes de reintentar, verificar que no haya otro proceso emitiendo simultáneamente para el mismo punto de venta y tipo de comprobante. Proteger la asignación local del número contra concurrencia.
6. Guardar la solicitud y respuesta de ARCA, incluidos CAE, vencimiento, errores y observaciones. No marcar como emitido hasta persistir el resultado autorizado.

### Referencias oficiales

- [RG 1415/2003, texto vigente y Anexo II](https://biblioteca.arca.gob.ar/search/query/norma.aspx?p=t%3ARAG%7Cn%3A1415%7Co%3A3%7Ca%3A2003%7Cf%3A07%2F01%2F2003)
- [RG 4291/2018, artículos 14 y 15: datos y representación gráfica del comprobante electrónico](https://biblioteca.arca.gob.ar/search/query/norma.aspx?p=t%3ARAG%7Cn%3A4291%7Co%3A3%7Ca%3A2018%7Cf%3A02%2F08%2F2018)
- [ARCA: datos que deben contener los comprobantes](https://www.arca.gob.ar/fe/emision-autorizacion/datos-comprobantes.asp)
- [Especificación oficial del QR](https://www.arca.gob.ar/fe/qr/documentos/QRespecificaciones.pdf)
- [Manual de WSFE: autorización y consulta de comprobantes](https://www.arca.gob.ar/ws/documentacion/manuales/manual-desarrollador-ARCA-COMPG.pdf)
- [ARCA: constatación de comprobantes con CAE](https://servicioscf.arca.gob.ar/publico/comprobantes/cae.aspx)
