# Validación de LiDAR forestal integrado 0.1.0

1 de noviembre de 2026: **171 pruebas ejecutadas y aprobadas**, ninguna omitida, con
QGIS 3.40.6 / Python 3.13.5, NumPy 2.2.6, pandas 2.2.3 y matplotlib 3.10.7.
Se usó un entorno virtual con acceso a los paquetes de QGIS del sistema; no se
modificó el Python del sistema. Las dependencias del instalador no se incluyen como
binarios: deben estar en el QGIS del usuario, como en el complemento de modelización.

## Qué se comprobó

- Regresiones heredadas de inventario, modelización y cartografía: catálogos y huellas
  con fixtures, recepción y lotes de LAZ, caché/recuperación, LAS, comandos FUSION,
  CRS, círculo/cuadrado, SHP/GPKG, modelos y validación cruzada.
- Una sola copia del motor LiDAR, utilizada por ambos adaptadores; una configuración
  enlazada de carpetas, FUSION, descargas y destino final.
- Tres módulos en una ventana y disponibilidad de inventario/cartografía si faltan
  las dependencias de modelización. Coordinación de tareas y cancelación al cerrar.
- Inventario con corte de métricas a 3 m: las métricas respetan ese corte, mientras
  FCC sigue calculándose con primeros retornos >2 m sobre primeros retornos totales.
- Reconocimiento de los recuentos modernos de inventario en modelización y rechazo
  de recuentos asociados a un umbral distinto de 2 m.
- Paso de CSV de inventario al módulo de modelización; ajuste estadístico real con
  datos sintéticos, exportación de modelos.json y paso al módulo cartográfico.
- Persistencia del corte del CSV en el modelo, lectura automática por cartografía y
  rechazo de una selección incompatible. CSV con cortes mezclados rechazado.
- Aplicación de la ecuación ajustada a métricas de celda; FCC y P95 mantienen sus
  definiciones, aunque la ecuación use métricas >2 m. Sin duplicar Duan.

El ajuste y la validación estadística se ejecutan realmente, con datos sintéticos.
En cambio los procesos FUSION y las descargas se sustituyen por fixtures: no se
presentan como una ejecución Windows/FUSION/CNIG real de la suite.

## Comprobaciones de distribución

ZIP autónomo, determinista y con SHA-256. Una sola raíz QGIS y una sola copia de
lidar_core. Se incluye instalador en descargas/ para no depender de la visibilidad
de Releases. La comprobación del ZIP incluye CRC y su punto de entrada autónomo.

## Pendiente en el equipo del usuario

Instalación Windows/QGIS, dependencias de modelización en ese Python, Chrome y sus
trámites CNIG, FUSION real con las DLL oficiales, recepción de dos hojas reales,
pausa/cancelación y recuperación en datos del usuario, entrega real a Q: y puntos
exactamente en bordes de celdas. Empezar con pocas parcelas y un polígono pequeño.

La compatibilidad de formato no valida modelos calibrados en parcelas circulares
para cuadrados de 400 m². Deben comprobarse vuelo, retornos, normalización, umbral,
unidades y superficie, además de la validación científica de las ecuaciones.
