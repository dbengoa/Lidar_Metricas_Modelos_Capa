"""Square-cell orchestration reusing the bundled inventory acquisition/FUSION engine."""
from pathlib import Path
import csv
import json
import math

from ..lidar_core.engine import Engine
from ..lidar_core.core import Plot, atomic_json
from .grid import CELL
from .models import PROTOCOL, predictions, finite, needs_gt2
from ..lidar_core.fusion import program
from ..lidar_core.core import token
from .local_work import local_workspace,processing_root,local_arguments


def rectangular_command(args):
    args = list(args)
    if '/shape:1' not in args:
        return args
    args[args.index('/shape:1')] = '/shape:0'
    left, bottom, right, top = map(float, args[-4:])
    x, y = (left+right)/2, (bottom+top)/2
    # Request half-open upper boundaries; cells still have exact 20 m geometry.
    bounds = (x-CELL/2, y-CELL/2, math.nextafter(x+CELL/2, -math.inf), math.nextafter(y+CELL/2, -math.inf))
    args[-4:] = [format(value, '.17g') for value in bounds]
    return args


def outputs(row, models):
    lowered = {key.strip().casefold(): value for key, value in row.items()}
    if 'cm_elev p95' not in lowered:
        raise ValueError('CloudMetrics no entregó Elev P95; no puede calcularse altura dominante')
    p95 = finite(lowered['cm_elev p95'])
    first = int(row['n_primeros_retornos'])
    above = int(row['n_primeros_retornos_sobre_corte'])
    if first < 0 or above < 0 or above > first:
        raise ValueError('Recuentos de primeros retornos incoherentes')
    fcc = above/first if first else None
    context = dict(row)
    if models['standard_height_filter_m']==2:
        for key,value in row.items():
            if key.startswith('cm_gt2_'):
                context['cm_'+key[len('cm_gt2_'):]]=value
    context.update(FCC=fcc,HDOM_M=p95,FCC_lidar_primeros_gt2_pct=100*fcc if fcc is not None else None,
                   densidad_retornos_m2=int(row['n_puntos'])/(CELL*CELL))
    protocol=models['package'].get('protocolo_fcc',{})
    for key,value in ((protocol.get('superiores'),above),(protocol.get('total'),first)):
        if key:
            context[key]=value
    predicted, states = predictions(context, models)
    return {'FCC': fcc, 'HDOM_M': p95, 'N_PRIM': first, 'N_PRIM_2': above,
            'N_PUNTOS': int(row['n_puntos']), **predicted,
            'EST_LIDAR': 'OK' if first else 'SIN_PRIMEROS',
            'EST_N': states['N_HA'], 'EST_VOL': states['VOL_HA'], 'EST_AB': states['AB_HA']}


def export_grid(directory, grid, rows, epsg, models, check):
    from qgis.core import (QgsVectorLayer, QgsField, QgsFeature, QgsGeometry, QgsRectangle,
                           QgsVectorFileWriter, QgsCoordinateTransformContext)
    from qgis.PyQt.QtCore import QVariant
    records = {row['parcela_id']: row for row in rows}
    if set(records) != {cell['id'] for cell in grid}:
        raise ValueError('Las métricas no corresponden a todas las celdas de la cuadrícula')
    fields = [('ID_CELDA', QVariant.String, 40, 0), ('AREA_M2', QVariant.Double, 20, 3),
              ('FRAC_AOI', QVariant.Double, 20, 8), ('BORDE', QVariant.Int, 5, 0)]
    fields += [(name, QVariant.Double, 24, 8) for name in ('FCC','HDOM_M','N_HA','VOL_HA','AB_HA')]
    fields += [(name, QVariant.LongLong, 20, 0) for name in ('N_PRIM','N_PRIM_2','N_PUNTOS')]
    fields += [(name, QVariant.String, 80, 0) for name in ('EST_LIDAR','EST_N','EST_VOL','EST_AB')]
    layer = QgsVectorLayer('Polygon?crs=EPSG:'+str(epsg), 'cartografia_20m', 'memory')
    provider = layer.dataProvider()
    if not provider.addAttributes([QgsField(name, kind, len=length, prec=precision) for name, kind, length, precision in fields]):
        raise ValueError('No se pudieron crear los campos de salida')
    layer.updateFields()
    csv_rows = []
    for cell in grid:
        check()
        result = {'ID_CELDA': cell['id'], 'AREA_M2': CELL*CELL,
                  'FRAC_AOI': cell['aoi_fraction'], 'BORDE': int(cell['aoi_fraction'] < 1-1e-8),
                  **outputs(records[cell['id']], models)}
        feature = QgsFeature(layer.fields())
        feature.setGeometry(QgsGeometry.fromRect(QgsRectangle(cell['xmin'],cell['ymin'],cell['xmin']+CELL,cell['ymin']+CELL)))
        feature.setAttributes([result[name] for name, *_ in fields])
        if not provider.addFeatures([feature])[0]:
            raise ValueError('No se pudo añadir la celda '+cell['id'])
        csv_rows.append(result)
    layer.updateExtents()
    for driver, suffix in [('GPKG','.gpkg'), ('ESRI Shapefile','.shp')]:
        check()
        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName = driver
        options.fileEncoding = 'UTF-8'
        options.layerName = 'cartografia_20m'
        path = Path(directory)/('cartografia_20m'+suffix)
        result = QgsVectorFileWriter.writeAsVectorFormatV3(layer,str(path),QgsCoordinateTransformContext(),options)
        if result[0] != QgsVectorFileWriter.NoError:
            raise ValueError('Error al exportar '+str(path)+': '+str(result[1]))
    with (Path(directory)/'cartografia_20m.csv').open('w',encoding='utf-8-sig',newline='') as handle:
        writer = csv.DictWriter(handle,fieldnames=[field[0] for field in fields])
        writer.writeheader()
        writer.writerows(csv_rows)
    atomic_json(Path(directory)/'protocolo_cartografia.json', {
        'plugin_version':'0.1.1','protocol':PROTOCOL,'epsg':epsg,
        'fcc_unit':'ratio 0..1','hdom_definition':'Elev P95 de todos los retornos normalizados',
        'cell_geometry':'cuadrados completos; bordes sin recortar',
        'coverage':'círculo circunscrito más margen; comprobación conservadora',
        'models':models,'model_plugin_integration':{
            'repository':'https://github.com/dbengoa/modelizacion-qgis',
            'commit':'09263b4a711fa0b724ee1cd16a622dc496871118',
            'format':'modelos.json; media, lineal y potencial; Duan ya incluido en intercepto'},
        'cells':len(grid)})


class GridEngine(Engine):
    def __init__(self, config, grid, models, *args, **kwargs):
        self.grid = grid
        self.models = models
        config = dict(config, radius=CELL/math.sqrt(2), height_cutoff=None)
        super().__init__(config,[Plot(cell['id'],cell['x'],cell['y']) for cell in grid],*args,**kwargs)
        self.state['version'] = '0.1.1'
        self.state['inventory_engine_version'] = '0.4.7'
        self.state['cartography_version'] = '0.1.1'
        self.state['geometry'] = 'square_20m'
        self.state.update(suite_version='0.1.0',module='cartografia')
        self.previous=None

    def execute(self):
        self.c['output']=processing_root(self.c['output'])
        if self.c.get('previous_run'):
            from .cell_cache import PreviousRun
            self.previous=PreviousRun(self,self.c['previous_run'])
            self.previous.stage()
        # Runtime FUSION never reads from the user's optional external input paths.
        if self.c.get('files'):
            from .local_work import verified_copy
            staged=[]
            for i,path in enumerate(self.c['files']):
                source=Path(path)
                destination=Path(self.c['output'])/'entradas'/str(i)/source.name
                verified_copy(source,destination,self.check)
                staged.append(str(destination))
            self.c['files']=staged
        return super().execute()

    def prepare_cells(self,paths,mapping):
        from .cell_cache import CellCache
        self.cache=CellCache(self,paths,mapping)
        self.state['tools_sha256']=self.cache.tools
        self.save_state()

    def reuse_cell(self,plot,work):
        return self.cache.restore(plot.id,work)

    def checkpoint_cell(self,identifier,work,row):
        self.cache.save(identifier,work,row)

    def run_command(self, args):
        args=rectangular_command(args)
        return super().run_command(local_arguments(args))

    def phase(self, name, plot=None):
        if name == 'ClipData: recorte circular':
            name = 'ClipData: celda cuadrada 20 x 20 m'
        return super().phase(name,plot)

    def _execute(self, root):
        atomic_json(self.run/'cuadricula.json',self.grid)
        if hasattr(self,'aoi_wkb'):
            (self.run/'area_trabajo.wkb').write_bytes(self.aoi_wkb)
        # Radius covers square corners for acquisition, terrain and support checks.
        # Only the raw/normalized metrics clips are narrowed to the exact square.
        super()._execute(root)
        self.check()
        self.phase('Exportación de polígonos dasométricos 20 x 20 m')
        with (self.run/'metricas.csv').open(encoding='utf-8-sig',newline='') as handle:
            rows = list(csv.DictReader(handle))
        if needs_gt2(self.models):
            self.phase('Métricas >2 m requeridas por los modelos')
            for row in rows:
                self.check()
                work=self.run/token(row['parcela_id'])
                path=work/'cloudmetrics_gt2.csv'
                if not path.is_file():
                    self.run_command([str(program(self.c['fusion'],'CloudMetrics')),'/new','/minht:2',str(work/'normalizada.las'),str(path)])
                with path.open(encoding='utf-8-sig',newline='') as handle:
                    filtered=list(csv.DictReader(handle))
                if len(filtered)!=1:
                    raise ValueError('CloudMetrics >2 m no entregó una fila para '+row['parcela_id'])
                row.update({'cm_gt2_'+key:value for key,value in filtered[0].items()})
                self.checkpoint_cell(row['parcela_id'],work,row)
        with (self.run/'metricas_modelos.csv').open('w',encoding='utf-8-sig',newline='') as handle:
            writer=csv.DictWriter(handle,fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        export_grid(self.run,self.grid,rows,self.c['epsg'],self.models,self.check)
        self.state['cartography_outputs'] = {kind:str(self.run/('cartografia_20m.'+kind)) for kind in ('shp','gpkg','csv')}
        self.progress(99,'Cartografía generada: '+str(self.run/'cartografia_20m.shp'))
