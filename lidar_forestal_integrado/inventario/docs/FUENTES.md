# Fuentes y protocolo comprobado — 18 de octubre de 2026

## CNIG: verificación primaria directa

Se obtuvieron respuestas reales del dominio oficial con cabeceras `User-Agent` del
plugin y `X-Requested-With: XMLHttpRequest`, HTTPS verificado, sin desactivar TLS:

- [Catálogo LIDA3](https://centrodedescargas.cnig.es/CentroDescargas/catalogo.do?Serie=LIDA3):
  HTTP 200, HTML y JavaScript oficial inspeccionados.
- `POST https://centrodedescargas.cnig.es/CentroDescargas/archivosSerie` con
  `codAgr=MOMDT`, `codSerie=LIDA3`, `numPagina` y `coordenadas` GeoJSON lon/lat:
  HTTP 200. El fragmento incluye `codSerie`, `totalArchivos`, filas de nombres y
  `linkDescDir_<sec>`. Se cotejó la paginación del propio JavaScript.
- [Ficha de ejemplo](https://centrodedescargas.cnig.es/CentroDescargas/detalleArchivo?sec=12752563):
  HTTP 200. Identifica la serie LIDA3 y el control `bDescDir`. Su manejador ejecuta
  reCAPTCHA con acción `preautorizar_descarga`, solicita `preAutorizarDescarga` y sólo
  si `autorizado == 'S'` continúa a `initDescargaDir`/licencia/formulario de descarga.
- `POST https://centrodedescargas.cnig.es/CentroDescargas/localizarCoordsSec` con
  `secuencial=12752563`: HTTP 200, `coordsJson` FeatureCollection/MultiPolygon en lon/lat.
  La ficha lo lee con OpenLayers GeoJSON y proyección de visualización EPSG:3857.
- `POST initDescargaDir` de diagnóstico respondió HTTP 200 con `muestraLic=NO` y
  `autorizado=null`. **Esto no se interpreta como autorización de descarga**. La nueva
  implementación deja esa secuencia al botón oficial del navegador y no solicita el
  binario desde urllib.

Algunas peticiones GET anteriores sin cabecera AJAX respondieron 503. Ese resultado no
afectó a la búsqueda POST verificada, ni justifica sustituir la descarga por selección
manual. Los endpoints son internos del portal y pueden cambiar.

## Consulta real entre cuatro teselas

Se consultó la parcela de diagnóstico EPSG:25829 `(629000, 4780000)`, radio 15 m,
celda 1 m y margen, sobre una esquina entre cuatro teselas. El catálogo devolvió:

| sec | Nombre |
|---|---|
| 12752563 | PNOA-2024-GAL-628-4780-H29-NPC01.LAZ |
| 12726205 | PNOA-2024-GAL-628-4781-H29-NPC01.LAZ |
| 12744109 | PNOA-2024-GAL-629-4780-H29-NPC01.LAZ |
| 12739748 | PNOA-2024-GAL-629-4781-H29-NPC01.LAZ |

Se solicitaron las cuatro geometrías oficiales y se comprobó su unión. Los polígonos
publicados terminan a 0,01 m de la siguiente celda; con tolerancia de 0,02 m, el área
restante del círculo ampliado fue 0 m². No se inventaron huellas a partir de nombres.
La respuesta y el plan de prueba están en `live-cnig-plan.json` y `live-cnig-coverage.json`.
**No se descargaron esos LAZ ni se ejecutó FUSION en esta consulta.**

## FUSION

Fuente primaria: [manual FUSION 4.61, septiembre de 2024](https://forsys.sefs.washington.edu/software/fusion/FUSION_manual.pdf).
Se revisaron LDA2LAS (p. 111), GridSurfaceCreate (p. 92), ClipData (p. 43),
CloudMetrics (p. 49) y DTM2ASCII (p. 66), según numeración impresa.

```text
LDA2LAS.exe entrada.laz salida.las
GridSurfaceCreate.exe /class:2 mdt.dtm 1 M M 1 <huso> 0 0 teselas.txt
DTM2ASCII.exe /raster mdt.dtm mdt.asc
ClipData.exe /shape:1 teselas.txt original.las xmin ymin xmax ymax
ClipData.exe /shape:1 /dtm:mdt.dtm /height teselas.txt normalizada.las xmin ymin xmax ymax
CloudMetrics.exe /new normalizada.las cloudmetrics.csv
```

El círculo usa caja de diámetro `2 × radio`. Los códigos de datum `0 0` no atribuyen
códigos norteamericanos a los datos españoles; el CRS correcto se mantiene en el
manifiesto y GeoPackage. Los `.txt` de entrada permiten combinar teselas sin exceder
la longitud de la línea de comandos. El ejecutable real Windows sigue pendiente de prueba.

## Metadatos de las nubes

[Documentos ASPRS](https://community.asprs.org/leadership-restricted/leadership-content/public-documents/standards)
y [representación CRS WKT](https://asprslas.org/latest/03_crs.html). El lector admite
LAS 1.0–1.4 y VLR/EVLR de GeoTIFF/WKT; no anuncia LAS 1.5. Las cabeceras no sustituyen
la comprobación de huellas oficiales ni de apoyo de puntos reales.

## Verificación de la corrección 0.3.1 — 19 de octubre de 2026

Consulta real de sólo lectura en EPSG:25830 `(523500,4653500)`: CNIG devolvió
`PNOA-2024-PNR-523-4654-NPC01.laz`. El adaptador corregido lo aceptó, obtuvo la huella
oficial y confirmó cobertura del círculo. Evidencia: live-cnig-pnr-plan.json y
live-cnig-pnr-coverage.json. No se descargó LAZ ni se ejecutó FUSION en esta consulta.

## Corrección de autorización 0.4.0

La ficha oficial `https://centrodedescargas.cnig.es/CentroDescargas/detalleArchivo?sec=12183731`,
consultada el 19/10/2026, contiene comprobación de automatización (`navigator.webdriver`)
y marca `BOT_DETECTED` frente a `HUMAN_CONFIRMED` antes del formulario POST descargaDir.
La URL descargaDir comunicada por el usuario no es una descarga GET independiente.
Se retira el navegador CDP y se usa Chrome habitual con clic humano, sin modificar las
señales, formularios, CAPTCHA o firmas del portal. No se afirma una descarga real
satisfactoria desde este entorno. El resto del flujo usa vigilancia local cancelable.

## FUSION 0.4.1 — revisión del 19 de octubre de 2026

Se volvió a consultar el [manual oficial 4.61](https://forsys.sefs.uw.edu/software/fusion/FUSION_manual.pdf):
p. 19–21 (numeración impresa) documentan /version, /log:name, FUSION64 y ejecutables
con sufijo 64. LASzip requiere DLL acorde con la arquitectura (laszip.dll/laszip64.dll).
P. 43–47 confirman ClipData /shape:1 con lista de entrada y caja cuadrada; /dtm y
/height normalizan alturas. No se cambia la selección de retornos ni clasificación.
El manual contiene una advertencia histórica de ClipData 2.6 sobre escritura LAS 1.4;
no se extrapola a la versión 4.61 ni se usa para afirmar la causa de este incidente.
No se desactiva LASzip ni se rebaja el formato LAS como supuesto arreglo.

[Microsoft NTSTATUS](https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-erref/596a1078-e883-4972-9bbc-49e60bebca55)
define 0xC0000005 como STATUS_ACCESS_VIOLATION. El código decimal recibido,
3221225477, equivale a ese valor; no identifica la biblioteca o dato causante.
Las medidas de compatibilidad de 0.4.1 necesitan ensayo real Windows.

## Lectura y persistencia 0.4.2 — 19 de octubre de 2026

El registro del usuario identifica el error inicial errno 22 durante cobertura y el
fallo secundario al guardar estado. No ofrece un traceback de la operación fallida;
no se asigna una causa de red, formato o permisos sin esa evidencia. La lectura por
rangos y las escrituras transitorias se ensayan con fallos inyectados, sin atribuir al
servidor un comportamiento comprobado sólo en fixtures. No se publica el registro
íntegro del usuario ni sus rutas personales.


0.4.3: manual oficial 4.61 consultado para CloudMetrics /minht:# (retornos sobre el corte en datos normalizados); /above:# calcula ratios de cobertura. Se usa /minht y se mantiene /class:2 en GridSurfaceCreate.

0.4.4: verificado ClipData /shape:0 (rectángulo) y /shape:1 (círculo), manual oficial FUSION 4.61, páginas impresas 43–47. El entorno se recorta sin /height ni filtro de clase/altura y se entrega a GridSurfaceCreate con /class:2.
