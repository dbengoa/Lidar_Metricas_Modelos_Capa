# Descargas por lotes CNIG: comprobación del 1 de noviembre de 2026

El catálogo oficial LIDA3 respondió HTTP 200. Sus controles incluyen «Añadir todos»
y «Añadir a la cesta». En una sesión anónima temporal se seleccionaron sólo dos hojas:
PNOA_2021_CAT_259-4513_H31_NPC02.LAZ (sec=13011582) y
PNOA_2021_CAT_259-4514_H31_NPC02.LAZ (sec=13010017).
El servidor confirmó totalFiles=1 y después 2. La cesta mostró ambas hojas LIDA3,
208,86 MB en total y un único botón «Iniciar descarga». Se inspeccionó la pantalla
previa con encuesta opcional; no se enviaron encuestas ni se transfirieron LAZ.

El controlador de la cesta impide iniciar sin sesión si totatlFilesDesc > 20 y
solicita identificación. Los mensajes anuncian un máximo de cesta de 40.000, mientras
un fichero JavaScript conserva otra constante: no se ensayó el máximo registrado.
La implementación inicial se limita siempre a 20, incluso si existe sesión.

Fuentes consultadas:
- https://centrodedescargas.cnig.es/CentroDescargas/catalogo.do?Serie=LIDA3
- https://centrodedescargas.cnig.es/CentroDescargas/listaFicheros
- https://centrodedescargas.cnig.es/CentroDescargas/js/msj.js

No se confirmó si el paso final entrega archivos independientes, un gestor o un
paquete. Tampoco se confirmó una API pública estable para preparar cestas desde
QGIS. La sesión de una consulta Python es distinta de la sesión habitual de Chrome.

## Implementación 0.4.7

Modo asistido: guía local por lote con lista exacta y enlaces oficiales. El usuario
añade las hojas a su cesta e inicia la descarga en Chrome. El complemento no lee
cookies ni transfiere sesiones ni modifica otras cestas. No hay selección automática.

El receptor acepta LAZ/LAS individuales completos de la lista, en cualquier orden,
con las comprobaciones existentes de nombre, estabilidad, cabecera y copia. Cada hoja
se registra inmediatamente con SHA-256. Los lotes siguientes sólo se abren tras
completar el anterior. Los originales permiten reanudar tras cancelación/error.
No se extraen ZIP ni se evita el trámite oficial de autorización. El flujo final
CNIG/Chrome debe verificarse en Windows con dos hojas antes de trabajos grandes.
