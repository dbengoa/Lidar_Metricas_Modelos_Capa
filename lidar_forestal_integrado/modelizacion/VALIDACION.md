# Validación QGIS 0.3.1 experimental — 21-10-2026

## Ejecutado en Linux

44 pruebas aprobadas: 17 de motor, 7 de muestra pequeña, 6 de mínimo dos predictores,
2 portables nuevas de FCC/diámetro y 12 de integración QGIS 3.40.6 (3 nuevas).
Las portables se ejecutaron con Python 3.12; la GUI, con Python 3.13 y los paquetes
NumPy/pandas/matplotlib disponibles en el entorno de pruebas, sin añadirlos al ZIP.
Los registros están en validacion/. No se han utilizado datos privados en estas pruebas.

Pruebas nuevas:
- Orden exacto de los seis selectores: los dos nuevos siguen a Altura dominante.
- Selección inicial de FCC_pct y D_medio_cm cuando existen; si faltan, no modelizar.
- Conservación de exclusiones manuales al recargar; rechazo de ninguna respuesta,
  columnas repetidas y campo ID como respuesta; controles por modo de operación.
- Plantilla GUI y CLI con seis columnas de campo e IDs con ceros iniciales; CLI
  ajustar mantiene las cuatro respuestas por defecto para compatibilidad.
- Ajuste sintético de seis respuestas con ocho parcelas y mínimo dos métricas;
  48 predicciones externas, seis modelos y resumen, guardado y aplicación del JSON.
- Ajuste portable independiente de FCC/diámetro, 16 predicciones externas y aplicación
  a nuevas métricas. Selección exclusiva de las dos respuestas nuevas en la GUI.
- CSV anteriores de cuatro respuestas siguen funcionando; gráficos, cancelación,
  trabajo asíncrono y selección de métricas conservan las pruebas previas.

Los ajustes sintéticos demuestran funcionamiento, no precisión forestal. No se han
recalculado aquí los modelos de las 24 parcelas del usuario. La interfaz no obliga
al modelo de volumen o área basal a usar cobertura como predictor.

## Windows

Pendiente local: instalación y uso de QGIS Windows. La CI está configurada para
repetir las 32 pruebas portables en Windows y Linux antes de publicar la versión
experimental; consulte Actions para su resultado efectivo. No ejecuta QGIS Windows.

Protocolo pendiente:
1. Instalar ZIP 0.3.1 sin descomprimir, reiniciar QGIS y comprobar los dos nuevos
   campos debajo de Altura dominante, dentro del formulario con desplazamiento.
2. Abrir campo_24_parcelas.csv: comprobar FCC_pct y D_medio_cm; dejar Hdom sin
   modelizar si no existe (H_media_m no es altura dominante).
3. Ejecutar en carpeta nueva/vacía, comprobar ecuaciones, resumen, gráficos, modelos
   y predicciones de las respuestas seleccionadas, con unidades % y cm.
4. Abrir un CSV anterior de cuatro respuestas y otro solo con FCC/diámetro; verificar
   que no se asigna otra columna ni el ID a respuestas ausentes.
5. Aplicar modelos guardados a métricas del mismo protocolo; comprobar unidades y
   predicciones de FCC fuera de 0–100 (no se recortan automáticamente).

## Reproducción

```
python -m unittest discover -s tests -p test_engine.py -v
python -m unittest discover -s tests -p test_small_sample.py -v
python -m unittest discover -s tests -p test_two_predictors.py -v
python -m unittest discover -s tests -p test_new_targets.py -v
QT_QPA_PLATFORM=offscreen python tests/test_qgis.py
python build.py
```
