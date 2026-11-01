# Cartografía forestal LiDAR 20 m — 0.1.1 experimental

## Novedades 0.1.1: disco local, recuperación y entrega separada

**Todo el procesamiento debe ejecutarse en disco local.** El diálogo rechaza rutas
UNC y unidades de red asignadas, como Q:, para procesamiento en Windows. Se comprueban
también los directorios y rutas usados por FUSION. La unidad de red sólo interviene
al importar datos antiguos y al entregar los resultados terminados.

Campos nuevos:

- **Procesamiento local (sin espacios):** por ejemplo `C:\LIDAR_Cartografia\trabajo`.
  Guarda LAZ, LAS, MDT, registros y una caché verificable de celdas.
- **Destino final (opcional, admite red):** por ejemplo `Q:\LIDAR\cartografia_final`.
  Recibe una subcarpeta por ejecución con SHP completo, GPKG, CSV y auditoría.
- **Ejecución anterior para recuperar:** seleccione la carpeta con fecha/código que
  contiene `estado.json` y `cuadricula.json`, no la carpeta general `resultados`.
  Puede estar en la red. Se importan sus originales, LAS y celdas completadas a local,
  sin modificar los archivos antiguos. Conviene usar una carpeta local inicialmente
  vacía; si hay archivos distintos con el mismo nombre, no se sobrescriben.

### Recuperar un trabajo 0.1.0 que falló

Seleccione el mismo polígono, modelos, CRS, resolución de MDT y distancia de apoyo.
Indique la carpeta local nueva y la ejecución anterior. El programa copia y verifica
los datos con SHA-256 antes del cálculo. Para cada celda antigua completada verifica
LAS completos, métricas, FCC y MDT. Además cuenta independientemente en los LAS
locales de entrada los puntos del entorno, del cuadrado y sus primeros retornos.
Una celda que no coincide se recalcula: no basta el código 0 de ClipData ni un archivo
con tamaño aparentemente correcto. Esta comprobación inicial puede tardar y necesita
espacio para los originales y conversiones. No se garantiza recuperar todas las
celdas antiguas: sólo las que superen las comprobaciones.

Las ejecuciones 0.1.0 no registraban hashes de sus ejecutables FUSION; la adopción
queda marcada con esa limitación de procedencia. Los nuevos checkpoints incluyen
hashes de herramientas, LAS de entrada, configuración geométrica/MDT y todos sus
archivos. Cambios en esos datos invalidan la celda. Las ecuaciones se aplican de
nuevo aunque se reutilicen métricas: cambiar modelos no conserva predicciones viejas.

En ejecuciones posteriores basta usar el mismo procesamiento local: la caché se
consulta automáticamente. El diálogo sustituye la ruta antigua por su copia de recuperación local tras importarla; tampoco es necesario indicarla si todas las celdas ya están en caché.
Se reutilizan también métricas >2 m verificadas cuando ya están disponibles.

### Copia final y recuperación de una desconexión

La entrega empieza sólo después de completar la cartografía local. Copia todos los
componentes SHP y los resultados en una carpeta temporal del destino; verifica cada
archivo con SHA-256 y sólo después la renombra como entrega completa. Una copia
interrumpida queda identificada como `.partial_...`, nunca como resultado final.
No se borran los resultados locales ni se sobrescriben entregas distintas.

Si falla la red, restaure el acceso y pulse **Copiar resultados locales terminados
(sin recalcular)**. Seleccione la ejecución local completada y su destino. Este botón
no consulta CNIG ni ejecuta FUSION. Una repetición de una entrega correcta verifica
su contenido y no lo duplica. `entrega.json` y `entrega_final.json` documentan copias.

La evidencia del usuario mostró un recorte truncado en red y un recorte completo
más rápido en local; no se atribuye el fallo a un componente concreto del servidor.
Las pruebas de código simulan desconexiones y FUSION; queda pendiente validar este
nuevo flujo 0.1.1 en Windows, unidad asignada y datos reales.


Complemento independiente para QGIS: polígono → adquisición PNOA3/CNIG → LAS
normalizado → métricas en cuadrados de 20 × 20 m → SHP y GeoPackage dasométricos.
No altera los complementos de inventario o modelización.

## Entradas lógicas

1. **Capa poligonal**: SHP u otra capa QGIS válida, en el UTM de las teselas
   (EPSG:25828–25831 o 4083). Se usan todas sus entidades, no sólo la selección.
2. **modelos.json del complemento de modelización**: se lee directamente, sin copiar
   ecuaciones ni convertir a otro formato. Es opcional si sólo se desea FCC/P95.
3. **Asignación de respuestas**: N/ha, volumen/ha y área basal/ha. Se proponen los
   nombres originales `N_ha`, `V_ha`, `G_ha`. Para columnas con nombres personalizados,
   el usuario selecciona la ecuación y comprueba que sus unidades son las correctas.
4. **Protocolo de las métricas estándar cm_ del ajuste**: sin corte o sólo >2 m.
   El modelos.json actual no registra ese dato, por lo que no se adivina. Si lo exige
   una ecuación, es obligatorio seleccionarlo antes de ejecutar. Las columnas
   `cm_gt2_...` siempre usan métricas >2 m, con independencia de esta selección.
5. **Carpetas local de procesamiento, destino final y descargas de Chrome**, instalación FUSION, resolución de
   MDT (1 m por defecto) y distancia de apoyo (5 m por defecto).

La celda, FCC y percentil de altura son fijos, no parámetros de ajuste.

## Variables de salida

| Campo SHP | Definición | Unidad |
|---|---|---|
| FCC | Primeros retornos estrictamente >2 m / todos los primeros retornos | ratio 0–1 |
| HDOM_M | Elev P95 de todos los retornos normalizados, sin corte | m |
| N_HA | Ecuación guardada asignada a número de pies | pies/ha |
| VOL_HA | Ecuación guardada asignada a volumen | m³/ha |
| AB_HA | Ecuación guardada asignada a área basal | m²/ha |

FCC incluye suelo y alturas negativas/cero en el denominador. Sin primeros retornos,
FCC queda NULL, no 0. El P95 no se sustituye por una regresión de altura, máximo ni
media. Los modelos de FCC/Hdom del archivo no se utilizan para esas dos salidas.

`N_PRIM`, `N_PRIM_2`, `N_PUNTOS`, `EST_LIDAR`, `EST_N`, `EST_VOL` y `EST_AB` permiten
revisar recuentos y estados. Una variable sin ecuación queda NULL/SIN_MODELO. Las
predicciones negativas y fuera de rango se conservan con aviso, como en el motor
original; no se recortan silenciosamente. Una ecuación fuera de dominio queda NULL.

## Compatibilidad real con modelización

Adaptador para el formato de `qgis/modelizacion_forestal_lidar` de
[dbengoa/modelizacion-qgis](https://github.com/dbengoa/modelizacion-qgis), commit
`09263b4a711fa0b724ee1cd16a622dc496871118`, versión 0.4.2 experimental y las versiones
anteriores aceptadas por su propio predictor. No usa el repositorio vacío indicado
inicialmente, ni exige exportar a un nuevo esquema.

Se leen familias `media`, `lineal` y `potencial`, predictores, coeficientes, medianas
y rangos. El intercepto potencial YA incluye la corrección de Duan: no se aplica
otra vez. No se interpreta como código el texto `ecuacion`. La evaluación es numérica,
sin eval, pickle ni refit. El complemento nuevo no requiere pandas para predecir.

Las métricas con corte se calculan adicionalmente si las necesita un modelo. FCC y
HDOM_M siempre se obtienen de la nube completa antes de cualquier corte. El predictor
`FCC_lidar_primeros_gt2_pct` se entrega en porcentaje al modelo, como espera el segundo
complemento; el campo final FCC sigue siendo ratio. La densidad de retornos, si se
solicita, usa 400 m². Se rechazan modelos que exijan `radio_m`: no existe un radio
circular equivalente que conserve simultáneamente área, forma y soporte del ajuste.
Un predictor inexistente detiene la exportación; no se sustituye toda una columna
por la mediana. Un valor ausente en una columna disponible usa la mediana de
calibración y queda marcado, igual que el predictor original.

Aplicar modelos ajustados en parcelas circulares a cuadrados de 400 m² necesita
validación científica: compatibilidad de vuelo, normalización, retornos y escala.
La compatibilidad informática no certifica la validez de las predicciones.

## Cuadrícula y cobertura

Cuadrados completos de 400 m² alineados con múltiplos de 20 en UTM. Se unen entidades,
respetan huecos y evitan duplicados. Se incluyen celdas con intersección de área
positiva con el polígono; **no se recortan los bordes**. Sus métricas incluyen la
porción del cuadrado exterior al polígono. `AREA_M2=400`, `BORDE` y `FRAC_AOI` lo indican.

La adquisición y los controles usan el círculo circunscrito más margen para asegurar
los vértices. Las métricas se recortan aparte al cuadrado de 20 m. La comprobación es
conservadora y puede rechazar celdas próximas al límite de cobertura de un vuelo.
Se solicitan límites superiores exclusivos al recortar; debe validarse el tratamiento
numérico de puntos exactamente en bordes con FUSION real.

Límites iniciales: 10.000 celdas por ejecución y envolvente de 100.000. El motor por
celda necesita varios procesos FUSION: prioriza trazabilidad, no rendimiento regional.

## Instalar y ejecutar

1. Windows, QGIS >=3.34, FUSION 4.61 con bibliotecas LAZ oficiales y Chrome.
2. Instalar el ZIP sin descomprimir desde el administrador de complementos y reiniciar.
3. Cargar polígono y seleccionar carpeta de trabajo absoluta sin espacios, descargas
   reales de Chrome y FUSION. Para las primeras pruebas, utilizar disco local.
4. Seleccionar el modelos.json exportado por el segundo complemento, asignar respuestas
   y confirmar el protocolo de las métricas del ajuste. Sin archivo, sólo FCC/P95.
5. Ejecutar. En cada lote asistido de hasta 20 hojas, añadir las de la guía a la cesta
   oficial e iniciar la descarga en Chrome, completando sus trámites. La selección es
   manual: no se leen cookies ni se rellena automáticamente la cesta. No se extraen ZIP.
6. El receptor reconoce LAZ individuales en cualquier orden y continúa. Pausa, cancelación
   y reutilización de originales/conversiones funcionan como en inventario. La pausa no
   detiene Chrome y espera al comando FUSION activo.

El complemento incluye una copia interna GPL-3.0 del motor de inventario 0.4.7. No
necesita tener instalado el complemento anterior y no modifica sus archivos.

## Resultados y trazabilidad

En `resultados/<ejecución>/`: `cartografia_20m.shp` con todos sus componentes,
GeoPackage, CSV, `protocolo_cartografia.json`, `cuadricula.json`, polígono WKB, métricas
completas/modelos y registros. El protocolo conserva el archivo de modelos, su SHA-256,
la asignación de respuestas y el corte elegido. Los puntos intermedios no son el
resultado cartográfico. Una celda que falla detiene el trabajo; no se presenta una
capa final incompleta como válida. Conserve todos los componentes del SHP al copiarlo.

## Desarrollo

Desde esta carpeta:

```sh
python -m unittest discover -s tests -v
QT_QPA_PLATFORM=offscreen /usr/bin/python3 -m unittest discover -s tests -v
python tools/build.py
```

Las pruebas incluyen geometrías, FCC, P95, SHP/GPKG, modelos originales, Duan,
imputación, extrapolación, protocolos, y flujo de nubes sintéticas hasta polígonos con
predicciones. La función de referencia de modelización se conserva en tests para
contrastar numéricamente los resultados. FUSION es sustituido en pruebas de flujo.
Pendiente: validación Windows/FUSION real, descarga CNIG real y un modelos.json de
calibración del usuario. La publicación experimental no sustituye la validación en Windows.

Licencia GPL-3.0. QGIS, FUSION, Chrome y datos CNIG no se redistribuyen.
