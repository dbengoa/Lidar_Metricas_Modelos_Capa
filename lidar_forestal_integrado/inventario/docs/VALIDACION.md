# Validación 0.4.2 — 19 de octubre de 2026

Ejecutado: 83 pruebas aprobadas en Linux con QGIS 3.40.6; ninguna omitida.
Python sin QGIS: 73 aprobadas y 10 de integración omitidas. Registros en tests-linux.txt
 y tests-portable.txt. Los avisos de Qt/GDAL no afectan al resultado.

Once pruebas de vigilancia verifican nombres (guiones/bajos/sufijos), copia conservando
fuente, temporales .crdownload, HTML, tesela incorrecta, enlaces simbólicos, estabilidad,
cambio de fuente durante copia, reutilización, cancelación y reapertura de ficha.
El lanzamiento se comprueba con Popen sustituido: sólo Chrome normal, --new-tab y URL
oficial. No se utiliza CDP, navegador headless, perfil temporal ni clic programado.

La integración QGIS/GDAL recorre cuatro teselas vecinas con una descarga humana
simulada que entrega archivos sintéticos en Descargas. La vigilancia real los incorpora;
FUSION está sustituido por fixtures. Se verifica exportación CSV/GeoPackage y caché.
Se mantienen pruebas de CRS, cobertura/MDT, parámetros FUSION, nombres PNR sin Hxx,
deduplicación, errores y cancelación. No son cálculos FUSION reales.

Consultas CNIG reales de catálogo y geometrías: ejecutadas en versiones anteriores,
evidencias conservadas en FUENTES.md. No se repitió descarga binaria CNIG en 0.4.2.

## Regresión del fallo ClipData comunicado

Nueve pruebas portables adicionales verifican selección de variantes 64/32, pareja
LDA2LAS/LASzip, instalación sólo 64-bit, directorio de arranque, registro privado,
variables heredadas sin modificar el entorno QGIS y códigos de error firmados o no.
La prueba de arranque sustituye Popen; verifica el comando persistido cuando el
proceso termina con 3221225477. No ejecuta un binario FUSION real.

La integración QGIS reproduce el fallo de ClipData tras las conversiones (FUSION
sustituido): estado failed en recorte circular, todas las teselas verificadas y
reutilizadas, sin CSV final ni falsas métricas. Verifica también la ruta de cada
LAS, aviso CloudMetrics y salida GeoPackage en el caso satisfactorio.

El registro real del usuario prueba dos conversiones y un MDT satisfactorios con
FUSION 4.61 de 32 bits, no una prueba satisfactoria de ClipData/CloudMetrics. No se
ha reproducido aquí el fallo real. No se conserva su registro íntegro en el repositorio
por contener rutas personales de red; sólo el código de error en pruebas sintéticas.

## Regresiones de lectura y estado 0.4.2

18 pruebas adicionales reproducen I/O fallida: reintento de ENOENT, temporales únicos
con escritores concurrentes, conservación de JSON previo, cancelación, disco lleno,
carpeta desaparecida y diagnóstico alternativo. Verifican que un fallo de estado final
no sustituye el error original, la cancelación o la autorización, y que un fallo de
confirmación después del cálculo no se anuncia como éxito completo.

Para errno 22 se simulan lecturas de metadatos y puntos fallidas, reapertura con el
mismo offset, descarte de una lectura parcial y límites de 1 MiB. Se comprueba que los
archivos fuente permanecen intactos. El error persistente conserva errno, ruta y byte.
La prueba no reproduce la causa real de errno 22 en el servidor del usuario.

El workflow ejecuta estas 18 pruebas en Windows antes de permitir la publicación;
consulte Actions para confirmar el resultado del runner de la versión descargada.
En Linux se ejecutó además toda la suite QGIS/GDAL con 83 pruebas aprobadas. Las
pruebas portables son 73 aprobadas y 10 omitidas por requerir QGIS.

## Pendiente en Windows, con datos reales

1. Comprobar que ClipData64.exe y dependencias oficiales están en C:\FUSION si se desea 64 bits.
   Instalar ZIP y reiniciar QGIS; comprobar versión 0.4.2 y carpeta Descargas.
2. Centros con cobertura PNOA3; incluir parcela entre dos teselas y esquina de cuatro.
3. Ejecutar, comprobar Chrome habitual sin depuración. Pulsar Descargar, completar
   trámite oficial y guardar en carpeta indicada sin renombrar. No abrir descargaDir
   como enlace directo. Confirmar incorporación automática al terminar.
4. Verificar variantes Chrome «preguntar dónde guardar», Descargas reubicada y unidad
   de salida Q:/red. Si Chrome usa carpeta propia, configurarla en QGIS antes de ejecutar.
5. Cancelar durante espera/copia/FUSION: Chrome queda abierto, originales intactos;
   reanudar debe reutilizar las teselas completas sin nueva descarga.
6. Con FUSION 4.61 real y bibliotecas LAZ: comprobar descompresión, conteos, MDT clase 2,
   círculo y normalización ClipData, métricas y coincidencia de IDs en CSV/GPKG.
7. Reproducir la parcela 213.0 del incidente, confirmar lectura de LAS/cobertura y
   que un fallo primario aparece antes del aviso de guardado. Probar desconexión y
   reconexión de Q: sin datos originales únicos en riesgo; revisar el respaldo local.
8. Si ClipData falla, comprobar fase/ejecutable/código y /version en proceso.log;
   guardar estado.json y fusion.log. Distinguir fallo de arranque de fallo al recortar.
9. Inspeccionar proceso.log, estado.json, coberturas y recibos SHA-256; comparar cotas y
   métricas con una ejecución FUSION independiente antes de uso productivo.

La autorización CNIG depende del servidor. Esta versión permite el clic humano oficial;
no pretende eludir rechazos ni ser una descarga desatendida.

En la primera ejecución Windows, la prueba de escritores concurrentes reprodujo
WinError 5 al reemplazar el JSON. Se añadió reintento acotado también para ese código,
que puede corresponder a un bloqueo de reemplazo. Una denegación persistente se
sigue notificando sin cambiar permisos; se comprueba que mantiene el JSON anterior.


## Versión 0.4.3 — corte de altura (19-10-2026)

Ejecutadas 90 pruebas aprobadas en Linux con QGIS 3.40.6. Las nuevas comprobaciones
incluyen /minht sólo en CloudMetrics, umbral cero/fractional/desactivado, parámetros
inválidos, recuentos y metadatos, ausencia de retornos, controles de la interfaz y
flujo automático con FUSION simulado que exporta el corte a CSV y GeoPackage.
No se ejecutó FUSION real ni CloudMetrics.exe en Linux. Pendiente: instalación y
flujo real en Windows, y comprobar los estadísticos numéricos filtrados con FUSION
4.61 sobre datos reales. El manual oficial 4.61 respalda /minht; /above no sustituye
el filtrado de las estadísticas.


## 0.4.4 — entorno de MDT (19-10-2026)

94 pruebas aprobadas con QGIS 3.40.6 en Linux. Nuevas pruebas de geometría de
recorte con margen, entrada única para MDT, conservación de /class:2 y diagnóstico
0xC0000409. Flujos con FUSION simulado comprueban que el listado incluye cuatro
vecinas y que MDT/normalización consumen entorno_mdt.las. Estas pruebas verifican
orquestación y parámetros; no ejecutan los binarios FUSION ni demuestran su
comportamiento real con los datos que provocaron el cierre. Pendiente en Windows:
prueba real de ClipData con varias entradas, MDT, normalización y CloudMetrics.


## 0.4.5 — primeros retornos y Point/MultiPoint (21-10-2026)

Ejecutadas localmente 104 pruebas aprobadas en Linux con QGIS 3.40.6. Con Python
sin QGIS: 89 aprobadas y 15 omitidas. Registros tests-0.4.5-linux.txt y
 tests-0.4.5-portable.txt. Las seis pruebas nuevas portables cubren formatos LAS
0–10, máscaras de 3/4 bits (un noveno retorno no se cuenta como primero), clase 2
en el denominador, altura estrictamente > corte, umbral 0/fraccional, escalas/offsets,
alturas negativas, denominador vacío frente a cobertura cero, truncado, errores de
lectura, cancelación y conservación SHA-256 del LAS. Los 11 formatos se ejecutan
como subcasos. Cuatro pruebas QGIS nuevas cubren Point/PointZ/PointM y
MultiPoint/MultiPointZM, un punto o varios, opt-in, IDs con ceros iniciales,
colisiones, geometrías vacías, nulos y duplicados, sin editar la fuente.

La exportación QGIS comprueba tipo numérico y NULL (no 0) en cobertura sin primeros
retornos, tanto agregado como por parcela. El flujo automático con FUSION simulado
comprueba los nuevos campos en CSV/GPKG, cobertura_retornos.json y el mapa de origen.
En estas pruebas la nube copiada por el FUSION simulado NO es una normalización
real; los valores de cobertura se usan solo para comprobar la integración.

Pendiente en Windows/QGIS con FUSION 4.61 real:
1. Instalar ZIP 0.4.5, reiniciar QGIS y comprobar título y nueva casilla.
2. Procesar capa Point y copia MultiPoint de un punto: mismos IDs, centros y métricas.
3. Probar MultiPoint de varios puntos: rechazo explicativo sin opt-in; con casilla,
   IDs __p1/__p2 y parcelas_entrada.json correctos; cotejar con partes simples manuales.
4. Reutilizar carpeta anterior sin borrar LAZ/LAS; verificar nueva carpeta de resultados.
5. Contar manualmente retorno==1 en normalizada.las, incluido clase 2; contrastar
   numerador >2 y porcentaje con CSV, JSON y GPKG. Repetir corte 0, 3 y sin filtro
   (en ese último caso cobertura sigue usando 2 m). Verificar que ClipData conserva
   número de retorno y que CloudMetrics no altera el LAS normalizado.
6. Parcela entre teselas, nube sin primeros retornos, cancelación y unidad de red.
   Comparar porcentaje con un lector LAS independiente antes de uso productivo.

La consulta/descarga CNIG no se ha modificado ni repetido en esta versión.
No se ha ejecutado FUSION real aquí; no se valida cobertura como FCC de campo.


## 0.4.6 — pausa segura y ayuda integrada (31-10-2026)

74 pruebas aprobadas con QGIS 3.40.6. Con Python sin QGIS: 63 aprobadas y 11 omitidas.
Registros actuales en tests-0.4.6-linux.txt y tests-0.4.6-portable.txt.

Se comprueba persistencia del estado paused, continuación del mismo motor,
cancelación durante pausa y finalización de un subproceso Python real antes de
confirmar la pausa. El vigilante no consume su tiempo de espera durante la pausa.
La prueba QGIS comprueba solicitud/retirada/reanudación/cancelación en el diálogo,
reutilización de la ventana de ayuda y lectura local de su contenido. Se revisaron
visualmente el diálogo principal y la ayuda con Qt offscreen.

Pendiente Windows: solicitud de pausa durante ClipData/CloudMetrics reales,
reanudación con las mismas salidas que sin pausa, cancelación durante pausa y
recepción de un LAZ descargado en Chrome mientras el complemento está pausado.
Mantener QGIS abierto; no se implementa continuación de un proceso tras apagarlo.

La consulta actual al catálogo CNIG fue rechazada por el proxy (CONNECT 403).
No se atribuye el rechazo a CNIG ni se confirma descarga conjunta. Evidencia de cesta
y pasos pendientes en DESCARGAS_CNIG.md. La descarga actual sigue siendo por ficha.


## 0.4.7 — lotes asistidos de hasta 20 hojas (1-11-2026)

82 pruebas aprobadas con QGIS 3.40.6; sin QGIS, 70 aprobadas y 12 omitidas.
Registros tests-0.4.7-linux.txt y tests-0.4.7-portable.txt.

Se comprueban recepción en orden distinto al plan, una guía por lote, separación
20+3, recibos inmediatos y reanudación sólo de las tres pendientes tras un fallo.
También parciales/archivos ajenos, cancelación conservando hojas completas, límites,
nombres ambiguos, navegación local confinada y exclusión de la pausa del plazo.
El flujo QGIS recorre dos lotes de dos hojas con entrega humana y FUSION simulados,
verifica recibos, cobertura y exportación GeoPackage. El diálogo limita el tamaño a
20 y permite desactivar el modo lotes. El ZIP contiene la guía y la ayuda local.

En el portal real se comprobaron catálogo, cesta de dos hojas LIDA3 y control de 20
sin sesión. No se transfirieron LAZ reales. Pendiente en Windows: selección manual,
trámite oficial CNIG, formato de entrega, permisos de múltiples descargas de Chrome,
recepción de dos hojas reales y continuación FUSION. No se afirma que la cesta se
rellene automáticamente ni que el portal entregue un ZIP o una única autorización.
