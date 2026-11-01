# Procedencia e integración

- Inventario: dbengoa/inventario-lidar, commit 881d2b95bc1dd5150ce2b7b663ac29754bd0b91d,
  complemento 0.4.7 experimental.
- Modelización: dbengoa/modelizacion-qgis, commit 09263b4a711fa0b724ee1cd16a622dc496871118,
  qgis/modelizacion_forestal_lidar, 0.4.2 experimental.
- Cartografía: dbengoa/generacion_capa_dasolidar, commit a037db45db562fda21d99d4fae9ab1db320c7830,
  complemento 0.1.1 experimental.

Todo es GPL-3.0. Las licencias se conservan en la distribución. La nueva suite tiene
un único paquete QGIS, namespaces propios y una sola copia de los módulos científicos
y de adquisición en lidar_core; cartografía ya no distribuye otro _inventory.

Los diálogos originales se integran como módulos de una ventana. Se añaden configuración
compartida, coordinación de tareas, paso explícito de archivos, FCC fija >2 m,
reconocimiento de recuentos modernos en modelización y persistencia del protocolo de
métricas en modelos.json. El motor de ajuste/predicción conserva su versión 0.4.2
para compatibilidad del formato; suite_version identifica la integración. El nombre
del logger se separa para no mezclar registros con el complemento anterior instalado.
Los módulos conservan sus ayudas históricas; AYUDA.html de la suite describe el contrato
actual y las diferencias de integración.

No se cambian los coeficientes, las ecuaciones, la corrección de Duan ni el protocolo
de validación cruzada del motor de modelización. La FCC de la suite siempre usa 2 m,
independiente del corte configurado para otras métricas de inventario.
