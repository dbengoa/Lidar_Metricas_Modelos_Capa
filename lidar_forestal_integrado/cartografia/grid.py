"""Fixed, global UTM grid: full 400 m² cells intersecting the input polygon."""
import math

CELL = 20.
MAX_CELLS = 10000


def snapshot(layer):
    from qgis.core import QgsGeometry, QgsWkbTypes
    if not layer or not layer.isValid() or layer.geometryType() != QgsWkbTypes.PolygonGeometry:
        raise ValueError('Seleccione una capa poligonal válida')
    epsg = layer.crs().postgisSrid()
    if layer.crs().authid() not in ('EPSG:25828','EPSG:25829','EPSG:25830','EPSG:25831','EPSG:4083'):
        raise ValueError('Reproyecte el polígono al CRS UTM de las teselas (EPSG:25828–25831 o 4083)')
    polygons = []
    for feature in layer.getFeatures():
        geometry = feature.geometry()
        if geometry.isNull() or geometry.isEmpty() or not geometry.isGeosValid():
            raise ValueError('Polígono vacío o inválido en entidad '+str(feature.id()))
        polygons.append(geometry)
    if not polygons:
        raise ValueError('La capa no contiene polígonos')
    geometry = QgsGeometry.unaryUnion(polygons)
    if geometry.isEmpty() or not geometry.isGeosValid() or geometry.area() <= 0:
        raise ValueError('No se pudo obtener una superficie poligonal válida')
    return bytes(geometry.asWkb()), epsg


def cells(wkb, check=lambda: None):
    from qgis.core import QgsGeometry, QgsRectangle
    geometry = QgsGeometry()
    geometry.fromWkb(wkb)
    if geometry.isEmpty() or not geometry.isGeosValid():
        raise ValueError('Geometría de trabajo no válida')
    bounds = geometry.boundingBox()
    if not all(map(math.isfinite, (bounds.xMinimum(),bounds.xMaximum(),bounds.yMinimum(),bounds.yMaximum()))):
        raise ValueError('Coordenadas no finitas')
    left, right = math.floor(bounds.xMinimum()/CELL), math.ceil(bounds.xMaximum()/CELL)
    bottom, top = math.floor(bounds.yMinimum()/CELL), math.ceil(bounds.yMaximum()/CELL)
    if (right-left)*(top-bottom) > MAX_CELLS*10:
        raise ValueError('Envolvente demasiado grande para esta versión; divida el trabajo en polígonos menores')
    result = []
    for col in range(left, right):
        check()
        for row in range(bottom, top):
            check()
            xmin, ymin = col*CELL, row*CELL
            square = QgsGeometry.fromRect(QgsRectangle(xmin,ymin,xmin+CELL,ymin+CELL))
            if not geometry.intersects(square):
                continue
            overlap = geometry.intersection(square)
            if overlap.isNull():
                raise ValueError('Falló la intersección de una celda con el polígono')
            area = overlap.area()
            if area <= 1e-8:
                continue
            result.append({'id': f'E{col}_N{row}', 'x': xmin+CELL/2, 'y': ymin+CELL/2,
                           'xmin': xmin, 'ymin': ymin, 'aoi_fraction': min(1.,area/(CELL*CELL))})
            if len(result) > MAX_CELLS:
                raise ValueError('Máximo inicial de 10.000 celdas por ejecución; divida el polígono')
    if not result:
        raise ValueError('No se generaron celdas en el polígono')
    return result
