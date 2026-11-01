# Inventario forestal LiDAR 0.4.7 experimental

Añade descarga por lotes asistida, activada por defecto en el diálogo, con tamaño
configurable de 1 a 20 hojas. Conserva pausa, ayuda integrada y métricas FPC.

El complemento agrupa las hojas pendientes y abre en Chrome una guía con nombres
y enlaces oficiales. El usuario añade las hojas a la cesta del CNIG y pulsa
«Iniciar descarga». La selección en la cesta sigue siendo manual. Se conservan los
trámites oficiales; no se promete un único ZIP ni una única autorización.

El vigilante incorpora LAZ individuales en cualquier orden, registra cada hoja,
conserva fuentes, ignora parciales/ajenos y abre el siguiente lote al completar el
actual. Reanudar con la misma carpeta reutiliza los originales y solicita sólo los
pendientes. Una hora de espera sin incorporar otra hoja; la pausa no consume ese
plazo. No extrae ZIP. Desactivar lotes recupera el modo por ficha.

Comprobación oficial: cesta de dos hojas LIDA3 y límite de 20 sin iniciar sesión.
No se transfirieron LAZ reales ni se ejecutó FUSION real. Las pruebas de recepción
usan archivos sintéticos; el flujo final Windows/Chrome/CNIG sigue pendiente.

Instale el ZIP desde QGIS y reinicie QGIS. Consulte Ayuda, sección de lotes, y
DESCARGAS_CNIG.md para pasos y límites. Revise el contenido de la cesta antes de cada
lote: el complemento no elimina archivos de otras tareas.

Validación local: 82 aprobadas con QGIS; Python portable: 70 aprobadas y 12 omitidas.
