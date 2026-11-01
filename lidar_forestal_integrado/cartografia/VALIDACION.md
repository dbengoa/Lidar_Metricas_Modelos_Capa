# Validación 0.1.1 — 1 de noviembre de 2026

32 pruebas aprobadas con QGIS 3.40.6; portable: 18 aprobadas y 14 omitidas (QGIS).
Registros tests-qgis.txt y tests-portable.txt. No se ejecuta FUSION real en Linux.

Se mantienen las pruebas de geometría, FCC, P95 y modelos. Nuevas comprobaciones:
- rechazo de UNC, unidades remotas asignadas y unidades desconocidas mediante la
  función Windows de selección de disco, contrastada con tipos de unidad simulados;
- copia de entradas con SHA-256, cancelación sin archivo final incompleto y
  conservación de destinos preexistentes diferentes;
- entrega final completa, repetible, detección de corrupción y recuperación tras
  desconexión simulada, conservando la ejecución local completada;
- checkpoint que evita los procesos FUSION al repetir una celda válida;
- invalidación por caché dañada y cambios de configuración de MDT;
- cambio de ecuaciones que aplica nuevas predicciones a métricas reutilizadas;
- importación de ejecución 0.1.0 y contraste independiente de sus recuentos contra
  los LAS locales; un LAS antiguo de tamaño/cabecera coherentes pero con un punto
  perdido se rechaza y recalcula;
- tarea de copia final que no llama a FUSION ni necesita volver a generar métricas.

Los ensayos FUSION usan fixtures de LAS y MDT. El comprobador de recuperación sí lee
los puntos reales de los LAS sintéticos con NumPy. Las pruebas de disco remoto y
fallos de red son simuladas, no equivalen a un ensayo Windows/SMB real. Las antiguas
ejecuciones 0.1.0 no incluían hash de herramientas; esa limitación queda registrada.

Pendiente: probar en Windows el rechazo de Q:, importación y recuperación del trabajo
del usuario, entrega al servidor real y desconexión/reintento. La evidencia aportada
por el usuario confirmó un recorte local completo de 9.366 puntos frente a un archivo
truncado de red que anunciaba 6.895; esos datos no se incorporan al repositorio.

---

# Validación 0.1.0 — 1 de noviembre de 2026

18 pruebas aprobadas con QGIS 3.40.6. Python portable: 11 aprobadas, 7 omitidas
(integración QGIS). No se ejecutó FUSION real, Chrome/CNIG real ni modelos de campo
del usuario. No presentar el flujo simulado como validación Windows.

Comprobaciones: cuadrícula UTM, unión sin duplicados, huecos y bordes, geometrías
400 m², columnas SHP de <=10 caracteres, NULL/SIN_MODELO, FCC ratio, P95 obligatorio,
modelos.json real, asignaciones de respuestas, familias media/lineal/potencial,
Duan sin duplicar, medianas, extrapolación, negativas y dominio inválido.

La función de referencia predict_model se copió sin cambiar del complemento
modelizacion_forestal_lidar (commit 09263b4a711fa0b724ee1cd16a622dc496871118)
para contrastar los resultados. No requiere pandas: el contraste usa una interfaz
mínima de tabla y NumPy; la aplicación nueva de modelos no requiere ninguno de ellos.

Dos pruebas completas recorren una nube sintética con suelo y vegetación hasta SHP,
GeoPackage y predicciones: métricas sin corte y modelos que requieren corte >2 m.
Los comandos FUSION se sustituyen por fixtures que escriben LAS/DTM/CSV sintéticos.
Se comprueba que FCC/P95 de salida no cambian al variar el protocolo de los modelos,
y que el recorte no es circular. Se revisó visualmente el diálogo con Qt offscreen.

Pendiente Windows: FUSION 4.61 real y bibliotecas LAZ, descarga con cesta CNIG y
Chrome, puntos exactamente sobre límites de cuadrícula, unidades de red,
rendimiento con muchos cuadrados y comparación con un lector LiDAR independiente.
Pendiente científico: aplicación de ecuaciones ajustadas en parcelas circulares a
cuadrados de 400 m², con el mismo vuelo, definición de retornos y normalización.
