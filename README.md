# LiDAR forestal integrado — 0.1.1 experimental

**[⬇️ DESCARGAR INSTALADOR ZIP PARA QGIS](https://github.com/dbengoa/Lidar_Metricas_Modelos_Capa/raw/refs/heads/main/descargas/lidar_forestal_integrado-0.1.1-experimental.zip)**

También está en la carpeta [descargas](descargas): abra el ZIP y pulse **Download raw**.
No use Code → Download ZIP, que descarga el repositorio, no el instalador preparado.

Un único complemento con tres módulos independientes y un motor LiDAR compartido:

| Módulo | Entrada | Resultado |
|---|---|---|
| Inventario | Centros, ID y radio de parcelas | Métricas CSV/GPKG y FCC directa |
| Modelización | Métricas y datos de campo | Ecuaciones, modelos.json y validación anidada |
| Cartografía DasoLiDAR | Polígono y modelos guardados | Cuadrados de 20 × 20 m en SHP/GPKG/CSV |

Los complementos anteriores no se modifican ni se desinstalan. Los módulos pueden
trabajar con archivos previos; no es obligatorio ejecutar los tres en cada trabajo.
La suite añade un único menú/icono de QGIS y una ventana con tres pestañas.

## Instalación

1. Windows con QGIS >=3.34, FUSION 4.61 y sus bibliotecas oficiales LAZ y Chrome para
   los módulos LiDAR. La modelización también se puede ejecutar en Linux/QGIS.
2. NumPy, pandas y matplotlib disponibles en el **Python de QGIS**, como necesita el
   complemento de modelización original. El instalador no modifica Python ni instala
   paquetes automáticamente. Si faltan, inventario y cartografía siguen disponibles;
   la pestaña de modelización explica el requisito y permite recomprobarlo.
3. Instale el ZIP sin descomprimir en Complementos → Administrar e instalar
   complementos → Instalar a partir de ZIP. Active **LiDAR forestal integrado**.
4. Configure en la cabecera una carpeta local sin espacios, FUSION, descargas de
   Chrome y, si lo desea, destino final en red. No procese con FUSION en Q:.

Puede mantener instalados los complementos anteriores. Evite ejecutar otro proceso
externo sobre la misma carpeta mientras trabaja la suite. La suite bloquea dos
operaciones propias simultáneas y conserva cancelación/pausa segura por módulo.

## Flujo conectado

### Inventario → Modelización

Ejecute Inventario con los centros de parcelas. Al terminar, pulse **Métricas →
Modelización**: carga el CSV, sin iniciar el ajuste ni sobrescribir datos de campo.
También puede elegir un CSV anterior. Seleccione después campo, respuestas,
predictores y parámetros de validación como en el complemento original.

FCC siempre cuenta primeros retornos **>2 m** sobre todos los primeros retornos de
la nube normalizada completa. Cambiar el corte de las demás métricas no cambia FCC.
La modelización reconoce los recuentos n_primeros_retornos y
n_primeros_retornos_sobre_corte cuando altura_cobertura_m=2, además de nombres antiguos.

### Modelización → Cartografía

Después de ajustar, pulse **Modelos → Cartografía**: carga directamente modelos.json,
propone N_ha → N_HA, V_ha → VOL_HA y G_ha → AB_HA, sin copiar ni reajustar ecuaciones.
Las respuestas con nombres personalizados se asignan manualmente, comprobando unidades.

La suite guarda en modelos.json el corte real de las columnas cm_ cuando se declara
en el CSV. Cartografía lo carga automáticamente y rechaza una selección incompatible.
Un CSV con cortes mezclados no se admite. Los archivos antiguos siguen siendo válidos;
si no guardan el protocolo, se pide seleccionar explícitamente sin corte o >2 m.
Las columnas cm_gt2_ siempre usan >2 m. Duan ya está en el intercepto potencial y no
se aplica dos veces. Se mantienen medianas, rangos y estados de predicción.

## Definiciones fijas de cartografía

- **FCC:** primeros retornos estrictamente >2 m / primeros retornos totales. Ratio
  0–1; suelo y alturas negativas/cero entran en el denominador. Sin primeros: NULL.
- **HDOM_M:** P95 de todos los retornos normalizados, sin corte. No es una regresión.
- **N_HA**, **VOL_HA**, **AB_HA:** ecuaciones guardadas, en pies/ha, m³/ha y m²/ha.
  Sin ecuación: NULL/SIN_MODELO. Se conservan avisos de imputación, extrapolación,
  negativas y dominio inválido; no se inventan ceros ni se recortan predicciones.

Se usan cuadrados completos de 400 m², alineados en UTM, conservando huecos y sin
recortar celdas de borde. BORDE y FRAC_AOI lo documentan. La comprobación de cobertura
es conservadora, mediante círculo circunscrito y margen; las métricas se recortan
al cuadrado. Máximo inicial: 10.000 celdas. No está optimizado para trabajos regionales.

Pasar de parcelas circulares a cuadrados de 400 m² requiere validar científicamente
los modelos. Un formato compatible no acredita equivalencia de vuelo, retornos,
normalización o superficie de muestreo. Los modelos que exigen radio_m se rechazan
para la cuadrícula en lugar de inventar un radio.

## Datos locales, recuperación y entregas

El motor común descarga por lotes asistidos de hasta 20 hojas, conserva LAZ originales,
verifica conversiones y calcula con archivos locales. La selección y autorización
de la cesta se realizan en Chrome; no se leen cookies ni se automatiza su trámite.
El vigilante reconoce archivos individuales en cualquier orden y no extrae ZIP.

Cartografía conserva los checkpoints de celdas y la importación de ejecuciones
anteriores, con contraste de recuentos contra LAS locales. Se invalidan celdas si
cambian entradas, herramientas, geometría o parámetros de MDT; las ecuaciones se
aplican siempre de nuevo. Los archivos antiguos no se modifican.

La entrega en red sólo se hace después de completar el resultado local y verificar
sus componentes con SHA-256. En Cartografía, **Copiar resultados locales terminados**
permite reintentar la entrega de una ejecución de inventario o cartografía sin volver
a ejecutar FUSION. Los resultados locales se conservan si falla la red.

## Desarrollo y comprobación

```sh
QT_QPA_PLATFORM=offscreen python3 -m unittest discover -s tests -v
python3 tools/build.py
```

Las pruebas requieren el Python de QGIS con pandas/NumPy/matplotlib. Se incluyen las
regresiones de los tres módulos, contraste con el predictor original, pruebas del
motor compartido, enlaces entre pestañas y entrenamiento real con datos sintéticos
seguido de aplicación de sus modelos. FUSION y la entrega de LAZ se sustituyen en
pruebas de flujo; no se afirman ensayos Windows/CNIG/FUSION reales de esta suite.

La referencia de procedencia está en PROCEDENCIA.md y el detalle de validación en
VALIDACION.md. Licencia GPL-3.0. FUSION, QGIS, Chrome y datos CNIG no se redistribuyen.


### Predicciones no negativas (0.1.1)

La modelización aplica `max(0, ecuación)` antes de seleccionar modelos y calcular RMSE y sesgo en la validación interna y externa. Las predicciones CSV y la cartografía también convierten valores negativos en cero, manteniendo un aviso cuando se corrige una predicción. Los errores de archivos modelos.json anteriores no se recalculan al abrirlos: para evaluar esta nueva regla hay que repetir el ajuste. Los valores ausentes o errores de dominio continúan siendo inválidos, no se convierten en cero.
