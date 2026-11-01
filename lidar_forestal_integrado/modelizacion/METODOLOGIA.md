# Actualización QGIS 0.3.1: respuestas adicionales

La interfaz admite además FCC_pct (%) y D_medio_cm (cm), después de Hdom.
Las seis respuestas son opcionales individualmente; se exige al menos una y
columnas distintas del ID. La plantilla incluye ambas nuevas columnas. El motor
ajusta cada respuesta con la misma selección y validación; no cambian las ecuaciones
estadísticas ni se impone un indicador de cobertura como predictor obligatorio.
La FCC de campo no se confunde con cobertura de primeros retornos LiDAR. No hay
conversión de unidades ni limitación automática de predicciones a [0,100].
El CLI conserva sus cuatro objetivos predeterminados por compatibilidad; los nuevos
se solicitan mediante --objetivos. El resto del texto documenta la metodología
original para cuatro respuestas, aplicable también por separado a las nuevas.

# Nota para QGIS 0.3.0

El complemento exige inicialmente dos métricas. README.md describe las reglas
actuales que sustituyen las opciones de muestra pequeña y permiten dos métricas
con ocho parcelas: validación anidada, entrenamientos internos de seis, tres
coeficientes y dos observaciones por coeficiente. Es una relajación exploratoria;
la media es referencia, no candidato elegible con mínimo 2. Lo que sigue documenta
el motor independiente original y sus opciones predeterminadas.

# Ecuaciones de inventario forestal con LiDAR — 0.1.0 experimental

Script independiente del plugin QGIS. Une datos de campo con métricas LiDAR por ID y
ajusta **una ecuación por variable**: volumen, área basal, pies por hectárea y altura
dominante. Compara ecuaciones lineales y potenciales, con controles de complejidad,
validación cruzada anidada y aplicación posterior a nuevas métricas.
No requiere FUSION ni QGIS para el ajuste; usa sus CSV ya generados.

## Instalación en Windows

Python **3.10 o posterior**, de 64 bits. Abra PowerShell en esta carpeta:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

En los siguientes comandos se abrevia el ejecutable como `python`. Puede reemplazarlo
por `.\.venv\Scripts\python.exe` sin activar el entorno. No hace falta modificar el
Python de QGIS. Se necesitan NumPy, pandas y matplotlib; no hay servicios de pago,
paquetes propietarios, macros ni descargas automáticas de datos.

## Entradas

**campo.csv**: una fila por parcela. Las cabeceras predeterminadas son:

```csv
parcela_id,V_ha,G_ha,N_ha,Hdom
```

| Columna | Unidad / significado |
|---|---|
| `parcela_id` | Mismo ID que en el CSV LiDAR; texto, único, no vacío |
| `V_ha` | Volumen en m³/ha |
| `G_ha` | Área basal en m²/ha |
| `N_ha` | Pies/ha |
| `Hdom` | Altura dominante medida en campo, en m |

Las cuatro respuestas deben estar **ya calculadas en esas unidades**. No introduzca
volumen o número de árboles de la parcela sin convertirlos a hectárea. Hdom sigue
su definición de inventario; no se sustituye por P95. Fechas y superficie de campo
han de ser compatibles con el vuelo y el radio con que obtuvo las métricas.

**metricas.csv**: salida del plugin, con `parcela_id`, métricas `cm_Elev ...`, etc.
No se usan como predictores los nombres de archivos, IDs, coordenadas o respuestas.
Por defecto se consideran métricas de altura, `Canopy relief ratio`, `Profile area`
y densidad de **retornos** (`n_puntos / (pi * radio_m²)`, no densidad de pulsos).
La intensidad se excluye por defecto; sólo inclúyala expresamente si es comparable
entre vuelos/equipos. No se inventa una cobertura por encima de 2 m a partir del CSV.

Cree una plantilla con los IDs exactos de su archivo:

```powershell
python modelizacion_lidar.py plantilla --lidar metricas.csv --salida campo.csv
```

Rellene las cuatro columnas de campo. **Dos parcelas no permiten esta calibración**.
El mínimo operativo predeterminado es 20 valores de campo válidos por respuesta;
no es una garantía de suficiencia estadística. También se limita el número de
coeficientes dentro de cada entrenamiento. Una muestra pequeña puede terminar en
un único predictor o en la media, aunque se permita un máximo de tres.

Guarde los CSV en UTF-8 (opción «CSV UTF-8» de Excel). El separador se detecta
automáticamente; indique la coma decimal con la opción mostrada más abajo.
En Excel, mantenga el ID como texto para conservar ceros iniciales.

Los IDs mantienen ceros iniciales. `226.0` y `226` son distintos salvo que se indique
`--normalizar-id-decimal`; esa opción sólo quita sufijos `.0` y detecta colisiones.
Por defecto se exige coincidencia de todos los IDs de ambos archivos. Si tiene más
parcelas en un archivo, revise `auditoria_union.json` y, para autorizar el cruce
parcial, añada `--permitir-no-coincidentes`. Nunca se hace un cruce por orden de filas.

## Ajustar las cuatro respuestas

```powershell
python modelizacion_lidar.py ajustar --campo campo.csv --lidar metricas.csv --salida resultados_modelos
```

Use una carpeta nueva o vacía. Los datos originales nunca se modifican.
Cada respuesta puede tener su propia ecuación, conjunto de parcelas válidas y métricas.
Las respuestas vacías se excluyen **sólo para esa variable** y se registran. Los valores
no numéricos o negativos en las respuestas provocan error, no se convierten a cero.

Si el CSV de campo tiene `;` y coma decimal:

```powershell
python modelizacion_lidar.py ajustar --campo campo.csv --lidar metricas.csv --salida resultados_modelos --sep-campo ";" --decimal-campo ","
```

Puede elegir nombres de columnas diferentes, por ejemplo:

```powershell
python modelizacion_lidar.py ajustar --campo campo.csv --lidar metricas.csv --id-campo id --objetivos volumen_ha area_basal_ha pies_ha altura_dominante --salida resultados_modelos
```

O restringir a métricas seleccionadas por criterio forestal:

```powershell
python modelizacion_lidar.py ajustar --campo campo.csv --lidar metricas.csv --salida resultados_modelos --predictores "cm_Elev P95" "cm_Elev P50" "cm_Elev stddev" "cm_Canopy relief ratio" "densidad_retornos_m2"
```

### Montes, bloques o parcelas relacionadas

Añada una columna de grupo, por ejemplo `monte`, a **campo.csv** y use:

```powershell
python modelizacion_lidar.py ajustar --campo campo.csv --lidar metricas.csv --salida resultados_agrupados --grupo monte
```

Todos los registros de un grupo quedan juntos tanto en las particiones externas
como internas. Se necesitan al menos dos grupos en cada entrenamiento interno;
con pocos grupos puede no ser viable la validación anidada. El número de folds se
reduce al número de grupos disponibles, sin mezclar grupos para alcanzar el solicitado.

Defina bloques acordes con el objetivo de aplicación y la dependencia espacial.
El programa no crea bloques geográficos ni impone distancias de separación. La
validación aleatoria predeterminada asume observaciones suficientemente independientes;
puede ser optimista con parcelas próximas. El grupo no es un predictor.

## Método y criterio de selección

- **Lineal:** `Y = b0 + b1 X1 + ... + bp Xp`, mínimos cuadrados con intercepto.
- **Potencial:** `Y = a * X1^b1 * ... * Xp^bp`, ajuste lineal de `ln(Y)` frente
  a `ln(X)`. Se multiplica `exp(intercepto)` por el promedio de `exp(residuo_log)`
  del entrenamiento (corrección de retransformation de Duan). **a ya incluye ese
  factor** en la ecuación exportada. No se trata de un ajuste no lineal directo por
  mínimos cuadrados en unidades originales. El error se evalúa en unidades originales.

Las potenciales exigen respuesta y predictores estrictamente positivos durante el
ajuste. No se añaden `+1` ni constantes a ceros/negativos. Si no son aplicables se
descartan esos candidatos; las lineales siguen disponibles. No se eliminan parcelas
externas para que una potencial pueda evaluarse: si la elegida no puede predecir una
parcela externa, la ejecución falla con un mensaje explícito.

El sesgo se define como **predicho − observado**: positivo significa sobreestimación.
RMSE y sesgo pueden tener óptimos diferentes. El criterio por defecto es:

```text
score = RMSE_interno + 0.5 * abs(sesgo_interno)
```

Ambos términos están en la unidad de la respuesta. `--peso-sesgo` cambia la importancia
del sesgo; `0` usa sólo RMSE. Se conservan RMSE, sesgo, porcentajes, MAE y R² por separado.
Los porcentajes son respecto a la media observada, no porcentajes individuales por
parcela. Si esa media es cero no se calculan porcentajes; R² queda vacío si la
respuesta es constante. Un R² externo negativo es posible y no se oculta.

Para favorecer ecuaciones parsimoniosas se elige el menor número de predictores
entre candidatos con score hasta un **2 % por encima del mínimo**; después el menor
score. `--tolerancia-score 0` elige el score mínimo estricto. Se incluye la **media de
entrenamiento** como referencia y como posible ganador: no se fuerza una relación
LiDAR cuando los datos no la apoyan. No existe garantía de óptimo global o de sesgo
cero en otras masas forestales.

### Cómo se evita usar las parcelas de evaluación para elegir variables

1. Se reservan particiones **externas**, por defecto 5. Ninguna respuesta externa
   participa en selección, imputación o ajuste del modelo que la predice.
2. Dentro de cada entrenamiento externo se realiza otra CV de 4 particiones.
   En cada entrenamiento **interno** se recalculan ranking por correlación absoluta
   de Spearman, filtros y ajuste. Se descartan métricas constantes, más de 10 %
   ausentes y pares con correlación absoluta de Spearman >=0,98.
3. Se prueban combinaciones de hasta tres **posiciones del ranking** entre las diez
   primeras métricas retenidas. Las posiciones, el tamaño y la familia definen la
   regla candidata; los nombres de métricas pueden variar entre folds. Esto mantiene
   la preselección dentro del entrenamiento. No se preselecciona por correlación en
   todas las parcelas y después se presenta esa selección como validación externa.
4. Se exige por defecto cinco observaciones por coeficiente, **incluido el intercepto**,
   en cada entrenamiento, y VIF <=10 en la matriz transformada. Una potencial tiene
   tantos parámetros como una lineal del mismo número de métricas. Los valores
   faltantes aceptables se imputan con la mediana de ese entrenamiento.
5. Se selecciona la regla por su CV interna, se reajusta en el entrenamiento externo
   y se predice el bloque externo reservado. Al final se repite la selección con
   todas las parcelas para obtener la ecuación que se exporta.

`candidatos_*.csv` presenta los nombres al reajustar con todos los datos y las posiciones
que definían cada regla. Sus errores internos evalúan esa regla de selección, **no
una ecuación con idénticas métricas en todos los folds**, y no son los errores externos.
Se marca también la frontera Pareto RMSE/|sesgo| y qué candidato se seleccionó.

La CV externa estima el rendimiento del **procedimiento de selección**. No es una
prueba independiente de la ecuación final reajustada en todas las parcelas. No use
los errores de ajuste sobre los mismos datos como sustituto de validación. Tampoco
reutilice el resultado externo repetidamente para retocar opciones y luego lo presente
como una prueba intacta. Conserve una muestra independiente para una validación final
si el uso requiere estimaciones de error del modelo definitivo.

Puede repetir la CV externa, manteniendo una semilla reproducible:

```powershell
python modelizacion_lidar.py ajustar --campo campo.csv --lidar metricas.csv --salida resultados_repetidos --repeticiones 5 --semilla 2026
```

Cada parcela se predice una vez por repetición. El resumen agrupa los errores de esas
predicciones, sin promediarlas previamente para aparentar menor error. Se informa
`n_parcelas` además de `n`, que cuenta predicciones repetidas. Las repeticiones no son
nuevas parcelas independientes; no se ofrecen intervalos de confianza basados en ello.

## Resultados

| Archivo | Contenido |
|---|---|
| `ecuaciones.txt` | Una ecuación explícita por respuesta |
| `modelos.json` | Coeficientes a precisión completa, medianas, rangos y método |
| `resumen_validacion.csv` | RMSE, sesgo, RMSE%, sesgo%, MAE, R² externos y referencia media |
| `predicciones_validacion.csv` | Observado, predicho, error, ID, fold y métricas elegidas, fuera de muestra |
| `candidatos_*.csv` | Comparación interna, Pareto y candidato seleccionado |
| `descartados_*.json` | Combinaciones/reglas descartadas y motivo |
| `estabilidad_metricas.csv` | Frecuencia de selección de cada métrica en ajustes externos |
| `diagnostico_*.png` | Observado/predicho y residuos de la CV externa |
| `auditoria_union.json`, `exclusiones.csv` | IDs sin pareja y respuestas de campo ausentes |
| `ajuste.log`, `estado.json` | Progreso y estado completado/fallido/cancelado |

Los gráficos son diagnósticos, no pruebas suficientes de validez. Revise la
plausibilidad forestal, errores por rangos de volumen/densidad, grupos y estabilidad
de las métricas. Una métrica seleccionada no implica causalidad. No se eliminan
atípicos automáticamente ni se fuerzan predicciones a cero para mejorar resultados.
Las cuatro ecuaciones se ajustan por separado: no se imponen restricciones de
compatibilidad entre volumen, área basal, densidad y altura.

## Aplicar a nuevas parcelas

```powershell
python modelizacion_lidar.py predecir --modelos resultados_modelos/modelos.json --lidar metricas_nuevas.csv --salida predicciones.csv
```

No reajusta coeficientes. Mantenga las mismas unidades, vuelo/procesamiento,
normalización de alturas, definiciones de métricas y soporte espacial de calibración.
Las predicciones incluyen un estado por respuesta: `ok`, imputado, fuera del rango
univariante de calibración, negativo o dominio inválido. Una potencial con predictor
no positivo produce una celda vacía y aviso. La ausencia de una columna necesaria
provoca error. **Un estado `ok` no certifica que una combinación de covariables sea
representativa**: el control de rangos no evalúa extrapolación multivariante ni cambios
de especie, gestión o región. No se ofrecen intervalos de predicción en esta versión.

## Prueba reproducible sin datos reales

```powershell
python generar_ejemplo.py --salida ejemplo --n 80
python modelizacion_lidar.py ajustar --campo ejemplo/campo.csv --lidar ejemplo/metricas.csv --salida resultado_ejemplo
python modelizacion_lidar.py predecir --modelos resultado_ejemplo/modelos.json --lidar ejemplo/metricas.csv --salida predicciones_ejemplo.csv
python -m unittest discover -s . -p "test_*.py" -v
```

El ejemplo es **artificial**. Sus buenos errores no describen su inventario ni validan
las ecuaciones con datos forestales reales. Consulte `VALIDACION.md` para pruebas
realmente ejecutadas y pendientes. La entrada de dos parcelas del plugin sólo se
utilizó localmente para probar la plantilla; no se incluye en esta distribución.

Opciones completas: `python modelizacion_lidar.py ajustar --help`.
Licencia GPL-3.0, igual que el repositorio. Este script no modifica el plugin QGIS.

## Referencias metodológicas

- [Documentación de CV anidada, scikit-learn](https://scikit-learn.org/stable/auto_examples/model_selection/plot_nested_cross_validation_iris.html).
- [Validación con grupos, scikit-learn](https://scikit-learn.org/stable/modules/cross_validation.html#cross-validation-iterators-for-grouped-data).
- [Cawley y Talbot (2010), selección y sesgo de evaluación](https://www.jmlr.org/papers/v11/cawley10a.html).
- Duan, N. (1983), *Smearing Estimate: A Nonparametric Retransformation Method*,
  JASA 78(383), 605–610, DOI 10.1080/01621459.1983.10478017. Se implementa explícitamente
  el factor medio de exponenciales de residuos de entrenamiento; no se presupone
  normalidad para la retransformation. El texto completo no se pudo consultar desde
  este entorno (HTTP 403); la fórmula está descrita y probada en el código.
