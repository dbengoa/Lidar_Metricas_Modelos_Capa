# LiDAR forestal integrado 0.1.1 experimental

Las predicciones negativas se convierten a cero en la selección, validación y aplicación de modelos, incluyendo la cartografía. La ecuación exportada muestra max(0, ecuación) y modelos.json registra la regla.

Los modelos anteriores deben ajustarse de nuevo para obtener errores de validación con esta regla. Los valores ausentes y errores de dominio permanecen inválidos.

Verificación: 172 pruebas superadas; ZIP comprobado y acompañado de SHA-256.

# LiDAR forestal integrado 0.1.0 experimental

Un único instalador QGIS con tres módulos:

1. Inventario de parcelas: CNIG/LAZ, LAS, normalización, métricas y FCC.
2. Modelización: datos LiDAR/campo, ajuste, validación anidada y modelos.json.
3. Cartografía DasoLiDAR: polígonos a cuadrados completos de 20 × 20 m con variables
   dasométricas en SHP, GeoPackage y CSV.

Motor LiDAR y configuración compartidos; tareas de la suite serializadas. Botones
Métricas → Modelización y Modelos → Cartografía, con conservación del protocolo del
CSV. Cada módulo puede utilizar resultados anteriores sin ejecutar los otros dos.

FCC fija: primeros retornos >2 m / primeros retornos totales. HDOM cartográfica: P95
de todos los retornos normalizados. N/ha, volumen/ha y área basal/ha: modelos guardados.
Conserva corrección Duan, medianas, rangos, avisos, procesamiento local, caché de
celdas, lotes asistidos de 20 y entrega final separada.

Instalar el ZIP sin descomprimir desde QGIS y reiniciar. Puede mantener los tres
complementos anteriores instalados; la suite tiene su propio namespace y menú.
QGIS >=3.34; Windows/FUSION 4.61/Chrome para los procesos LiDAR; NumPy, pandas y
matplotlib en el Python de QGIS para modelización. No instala dependencias a escondidas.

171 pruebas aprobadas con QGIS 3.40.6. Ajuste real con datos sintéticos y contraste de
modelos. FUSION y descargas simulados en pruebas. Pendiente validar el flujo completo
Windows/CNIG/FUSION real y los modelos del usuario. Consulte VALIDACION.md.
