"""QGIS/GDAL adapters. Called in the worker using only privately owned objects."""
from pathlib import Path
import csv
import math


def read_plot_centers(layer, field, split_multipoints=False):
    """Snapshot point features on the GUI thread; never edit the input layer.

    Singleton MultiPoint keeps its original ID. Real multipart features require an
    explicit opt-in and receive <ID>__p1, <ID>__p2, ... in source vertex order.
    """
    from qgis.core import QgsWkbTypes, NULL
    from .core import Plot
    if not layer or not layer.isValid() or field not in layer.fields().names():
        raise ValueError('Seleccione capa de puntos y campo ID')
    features, ids = [], set()
    for feature in layer.getFeatures():
        fid = feature.id()
        value = feature[field]
        if value is None or value == NULL or not str(value).strip():
            raise ValueError('ID nulo o vacío en entidad '+str(fid))
        base = str(value)
        if base in ids:
            raise ValueError('ID duplicado '+base+' en entidad '+str(fid)+'. Use un campo único por entidad.')
        ids.add(base)
        geometry = feature.geometry()
        if geometry.isNull() or geometry.isEmpty():
            raise ValueError('Geometría vacía en ID '+base+' (entidad '+str(fid)+')')
        if QgsWkbTypes.geometryType(geometry.wkbType()) != QgsWkbTypes.PointGeometry:
            raise ValueError('La entidad '+str(fid)+' (ID '+base+') no es Point/MultiPoint')
        points = geometry.asMultiPoint() if geometry.isMultipart() else [geometry.asPoint()]
        if not points:
            raise ValueError('Sin centros en ID '+base)
        if len(points) > 1 and not split_multipoints:
            raise ValueError('ID '+base+' (entidad '+str(fid)+') contiene '+str(len(points))+
                             ' puntos. Active «Separar multipuntos con varios centros» para crear una parcela por punto.')
        features.append((fid, base, points))
    plots, origins, used = [], [], set()
    for fid, base, points in features:
        for part, point in enumerate(points, 1):
            identifier = base if len(points) == 1 else base+'__p'+str(part)
            if identifier in used or (len(points) > 1 and identifier in ids):
                raise ValueError('Colisión de ID generado '+identifier+'. Cambie los ID de origen antes de separar.')
            if not all(map(math.isfinite, (point.x(), point.y()))):
                raise ValueError('Coordenadas no finitas en ID '+identifier+' (entidad '+str(fid)+')')
            used.add(identifier)
            plots.append(Plot(identifier, point.x(), point.y()))
            origins.append({'parcela_id':identifier, 'id_origen':base, 'entidad_id':fid,
                            'parte':part, 'partes_entidad':len(points)})
    if not plots:
        raise ValueError('La capa no contiene parcelas')
    return plots, origins


def verify_terrain(path, plot, radius, check):
    from osgeo import gdal
    # Every raster cell intersecting the circle must have valid terrain, including
    # a one-cell halo for interpolation. Catalog coverage alone is insufficient.
    ds = gdal.Open(str(path))
    if ds is None:
        raise ValueError('No se puede leer el MDT convertido')
    gt = ds.GetGeoTransform()
    if gt[2] or gt[4] or gt[1] <= 0 or gt[5] >= 0:
        raise ValueError('MDT con orientación inesperada')
    band = ds.GetRasterBand(1)
    nodata = band.GetNoDataValue()
    halo = max(abs(gt[1]),abs(gt[5]))
    r = radius+halo
    left = math.floor((plot.x-r-gt[0])/gt[1])
    right = math.ceil((plot.x+r-gt[0])/gt[1])
    top = math.floor((plot.y+r-gt[3])/gt[5])
    bottom = math.ceil((plot.y-r-gt[3])/gt[5])
    if left < 0 or top < 0 or right > ds.RasterXSize or bottom > ds.RasterYSize:
        raise ValueError('El MDT no cubre el círculo y su margen de interpolación')
    for row in range(top,bottom):
        check()
        values = band.ReadAsArray(left,row,right-left,1)[0]
        cy = gt[3]+(row+.5)*gt[5]
        for col,z in enumerate(values,left):
            cx = gt[0]+(col+.5)*gt[1]
            if math.hypot(max(abs(cx-plot.x)-abs(gt[1])/2,0),max(abs(cy-plot.y)-abs(gt[5])/2,0)) <= r:
                if not math.isfinite(float(z)) or (nodata is not None and z == nodata) or z == -1:
                    raise ValueError('Huecos MDT cerca de ID '+plot.id)
    ds = None


def export_results(directory, rows, epsg, check):
    from qgis.core import (QgsVectorLayer,QgsField,QgsFeature,QgsGeometry,QgsPointXY,
                           QgsVectorFileWriter,QgsCoordinateTransformContext)
    from qgis.PyQt.QtCore import QVariant
    from .core import token
    keys = list(rows[0])
    with (Path(directory)/'metricas.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer = csv.DictWriter(f,fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)
    layer = QgsVectorLayer('Point?crs=EPSG:'+str(epsg),'metricas','memory')
    provider = layer.dataProvider()
    numeric = {'x','y','radio_m','n_puntos','n_puntos_metricas','altura_corte_m',
               'n_primeros_retornos','n_primeros_retornos_sobre_corte',
               'altura_cobertura_m','cobertura_primeros_retornos_pct'}
    # FUSION field names and nonnumeric diagnostic values are retained verbatim.
    provider.addAttributes([QgsField(k,QVariant.Double if k in numeric else QVariant.String) for k in keys])
    layer.updateFields()
    for row in rows:
        check()
        feature = QgsFeature(layer.fields())
        feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(row['x'],row['y'])))
        feature.setAttributes([(None if row[k] == '' else row[k]) if k in numeric else str(row[k]) for k in keys])
        if not provider.addFeatures([feature])[0]:
            raise RuntimeError('No se pudo crear la geometría de resultados')
    layer.updateExtents()
    def save(target, selected=None):
        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName = 'GPKG'
        options.layerName = 'metricas'
        options.onlySelectedFeatures = selected is not None
        if selected is not None:
            layer.selectByIds(selected)
        error, message, *_ = QgsVectorFileWriter.writeAsVectorFormatV3(layer,str(target),QgsCoordinateTransformContext(),options)
        if error != QgsVectorFileWriter.NoError:
            raise RuntimeError('Error GeoPackage: '+message)
    save(Path(directory)/'metricas.gpkg')
    for feature in layer.getFeatures():
        check()
        save(Path(directory)/token(feature['parcela_id'])/'metricas.gpkg',[feature.id()])
