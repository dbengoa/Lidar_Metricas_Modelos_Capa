"""Immutable cell checkpoints and explicit, independently checked 0.1.0 recovery."""
from pathlib import Path
import csv
import hashlib
import json
import uuid
import math

from ..lidar_core.core import atomic_json,digest,las_header,token,terrain_clip_command
from ..lidar_core.coverage import first_return_cover
from ..lidar_core.local import metadata
from ..lidar_core.qgis_io import verify_terrain
from ..lidar_core.storage import LASBlockReader
from .local_work import verified_copy,import_workspace

ARTIFACTS=('original.las','normalizada.las','entorno_mdt.las','mdt.dtm','mdt.asc',
           'cloudmetrics.csv','metricas.csv','entorno_mdt.json','cobertura.json','cobertura_retornos.json')
CONFIG_KEYS=('epsg','cell','support_distance','radius','height_cutoff')


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def signature(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


class PreviousRun:
    def __init__(self,engine,source):
        self.engine=engine
        self.source=Path(source)
        self.state=read_json(self.source/'estado.json')
        if self.state.get('status') in ('running','paused'):
            raise ValueError('Detenga la ejecución anterior antes de importar sus archivos')
        if self.state.get('cartography_version') not in ('0.1.0','0.1.1') or self.state.get('geometry')!='square_20m':
            raise ValueError('La ejecución anterior no es cartografía de cuadrados de 20 m compatible')
        if any(self.state['config'].get(key)!=engine.c.get(key) for key in CONFIG_KEYS):
            raise ValueError('CRS, MDT o configuración de la ejecución anterior no coinciden; no se recuperan sus celdas')
        self.grid={cell['id']:cell for cell in read_json(self.source/'cuadricula.json')}
        self.completed={row['id']:row for row in self.state.get('plots',[]) if row.get('status')=='completed'}
        self.tiles={row['sec']:row for row in self.state.get('tiles',[]) if row.get('status')=='verified'}
        self.by_path={row['las'].replace('\\','/').casefold():key for key,row in self.tiles.items()}
        self.staged=Path(engine.c['output'])/'recuperacion'/uuid.uuid4().hex

    def stage(self):
        engine=self.engine
        import_workspace(self.state['config']['output'],engine.c['output'],engine.check,
                         lambda text:engine.progress(0,text))
        for identifier,row in self.completed.items():
            engine.check()
            if row.get('directory')!=token(identifier):
                raise ValueError('Directorio de celda anterior no válido')
            source=self.source/row['directory']
            target=self.staged/row['directory']
            engine.progress(0,'Importando celda anterior a disco local: '+identifier)
            for name in ARTIFACTS:
                path=source/name
                if path.is_file():
                    verified_copy(path,target/name,engine.check)
        atomic_json(self.staged/'procedencia.json',{'source_run':str(self.source),'state':self.state})
        # Make the imported recovery set self-contained, so future retries need no
        # reads from the old share after the first successful import.
        local_state=dict(self.state,config=dict(self.state['config'],output=str(engine.c['output'])))
        atomic_json(self.staged/'estado.json',local_state)
        atomic_json(self.staged/'cuadricula.json',list(self.grid.values()))

    def candidate(self,cell,paths,source_keys):
        if self.state.get('tools_sha256') and self.state['tools_sha256']!=self.engine.cache.tools:
            return None
        identifier=cell['id']
        if identifier not in self.completed or identifier not in self.grid:
            return None
        old=self.grid[identifier]
        if any(old.get(k)!=cell[k] for k in ('x','y','xmin','ymin')):
            return None
        folder=self.staged/token(identifier)
        report=read_json(folder/'entorno_mdt.json')
        old_keys={self.by_path.get(str(p).replace('\\','/').casefold()) for p in report['source_tiles']}
        if old_keys!=set(source_keys):
            return None
        for key in source_keys:
            receipt=read_json(Path(paths[key]).with_suffix('.json'))
            if self.tiles[key]['source_sha256']!=receipt['source_sha256']:
                return None
        return folder


def inspect_cell(folder,cell,check):
    for name in ARTIFACTS:
        if not (folder/name).is_file():
            raise ValueError('Falta componente de celda: '+name)
    counts={name:las_header(folder/name) for name in ('original.las','normalizada.las','entorno_mdt.las')}
    if counts['original.las']!=counts['normalizada.las']:
        raise ValueError('La normalización no conserva el número de puntos')
    info=metadata(folder/'normalizada.las')
    xmin,ymin,xmax,ymax=info.bbox
    if xmin<cell['xmin']-1e-6 or ymin<cell['ymin']-1e-6 or xmax>cell['xmin']+20+1e-6 or ymax>cell['ymin']+20+1e-6:
        raise ValueError('El LAS normalizado no corresponde al cuadrado')
    with (folder/'metricas.csv').open(encoding='utf-8-sig',newline='') as stream:
        rows=list(csv.DictReader(stream))
    if len(rows)!=1 or rows[0]['parcela_id']!=cell['id'] or int(rows[0]['n_puntos'])!=counts['normalizada.las']:
        raise ValueError('Métricas de otra celda o recuento distinto')
    row=rows[0]
    with (folder/'cloudmetrics.csv').open(encoding='utf-8-sig',newline='') as stream:
        metrics=list(csv.DictReader(stream))
    if len(metrics)!=1 or any(row.get('cm_'+k)!=value for k,value in metrics[0].items()):
        raise ValueError('CloudMetrics y métricas de celda no coinciden')
    if not math.isfinite(float(row['cm_Elev P95'])):
        raise ValueError('P95 de celda no finito')
    coverage=first_return_cover(folder/'normalizada.las',2,check)
    if int(row['n_primeros_retornos'])!=coverage['n_primeros_retornos'] or int(row['n_primeros_retornos_sobre_corte'])!=coverage['n_primeros_retornos_sobre_corte']:
        raise ValueError('Recuentos de FCC no coinciden con el LAS')
    row.update(coverage)
    for name in ('x','y','radio_m'):
        row[name]=float(row[name])
    for name in ('n_puntos','n_puntos_metricas'):
        row[name]=int(row[name])
    return row,counts


def source_counts(paths,bounds,check):
    """Count independent source points in the square and terrain halo, in local LAS."""
    import numpy as np
    result=[0]*len(bounds)
    first=[0]*len(bounds)
    for path in paths:
        info=metadata(path)
        if info.compressed:
            raise ValueError('La comprobación de recuperación exige LAS sin comprimir')
        with LASBlockReader(path,check) as reader:
            cursor,remaining=info.offset,info.count
            while remaining:
                check()
                n=min(remaining,max(1,(4*1024*1024)//info.record_size))
                block=reader.read_exact(cursor,n*info.record_size)
                xyz=np.ndarray((n,2),dtype='<i4',buffer=block,strides=(info.record_size,4))
                x=xyz[:,0]*info.scales[0]+info.offsets[0]
                y=xyz[:,1]*info.scales[1]+info.offsets[1]
                returns=np.ndarray((n,),dtype='u1',buffer=block,offset=14,strides=(info.record_size,)) & (7 if info.point_format<6 else 15)
                for i,(left,bottom,right,top) in enumerate(bounds):
                    mask=(x>=left)&(x<=right)&(y>=bottom)&(y<=top)
                    result[i]+=int(np.count_nonzero(mask))
                    first[i]+=int(np.count_nonzero(mask & (returns==1)))
                cursor+=n*info.record_size
                remaining-=n
    return result,first


class CellCache:
    def __init__(self,engine,paths,mapping):
        self.engine,self.paths,self.mapping=engine,paths,mapping
        self.root=Path(engine.c['output'])/'celdas'
        self.cells={cell['id']:cell for cell in engine.grid}
        self.tile_hashes={key:read_json(Path(path).with_suffix('.json'))['las_sha256'] for key,path in paths.items()}
        from ..lidar_core.fusion import PROGRAMS,program
        self.tools={name:digest(program(engine.c['fusion'],name),engine.check) for name in PROGRAMS}

    def key(self,identifier):
        cell=self.cells[identifier]
        return signature({'protocol':'square20-allreturns-2m-v1',
                          'cell':{k:cell[k] for k in ('id','x','y','xmin','ymin')},
                          'config':{key:self.engine.c.get(key) for key in CONFIG_KEYS},
                          'sources':{t.sec:self.tile_hashes[t.sec] for t in self.mapping[identifier]},'tools':self.tools})

    def save(self,identifier,folder,row):
        key=self.key(identifier)
        base=self.root/key
        generation=uuid.uuid4().hex
        destination=base/generation
        files={}
        for name in (*ARTIFACTS,'cloudmetrics_gt2.csv'):
            path=folder/name
            if path.is_file():
                files[name]=verified_copy(path,destination/name,self.engine.check)
        atomic_json(destination/'cache.json',{'schema':1,'signature':key,'files':files})
        atomic_json(base/'latest.json',{'generation':generation})

    def restore(self,identifier,work):
        engine=self.engine
        cell=self.cells[identifier]
        key=self.key(identifier)
        base=self.root/key
        folder=None
        if (base/'latest.json').is_file():
            try:
                generation=read_json(base/'latest.json')['generation']
                if len(generation)!=32 or any(c not in '0123456789abcdef' for c in generation):
                    raise ValueError('Generación de caché inválida')
                candidate=base/generation
                receipt=read_json(candidate/'cache.json')
                if receipt.get('schema')!=1 or receipt.get('signature')!=key or not set(ARTIFACTS).issubset(receipt['files']):
                    raise ValueError('Recibo de caché no válido')
                for name,value in receipt['files'].items():
                    if name not in (*ARTIFACTS,'cloudmetrics_gt2.csv') or digest(candidate/name,engine.check)!=value:
                        raise ValueError('Caché modificada o incompleta')
                folder=candidate
            except (OSError,ValueError,KeyError) as error:
                engine.progress(engine._last_progress,'Caché descartada '+identifier+': '+str(error))
        legacy=False
        if folder is None and getattr(engine,'previous',None):
            try:
                folder=engine.previous.candidate(cell,self.paths,[t.sec for t in self.mapping[identifier]])
                legacy=folder is not None
            except (OSError,ValueError,KeyError) as error:
                engine.progress(engine._last_progress,'Celda anterior descartada '+identifier+': '+str(error))
        if folder is None:
            return None
        try:
            row,counts=inspect_cell(folder,cell,engine.check)
            if legacy:
                from .workflow import rectangular_command
                engine.progress(engine._last_progress,'Contrastando celda anterior con LAS locales: '+identifier)
                p=next(p for p in engine.plots if p.id==identifier)
                halo=list(map(float,terrain_clip_command(engine.c['fusion'],'input','output',p,engine.c['radius'],engine.c['cell'],engine.c['support_distance'])[-4:]))
                raw=list(map(float,rectangular_command(['ClipData','/shape:1',p.x-engine.c['radius'],p.y-engine.c['radius'],p.x+engine.c['radius'],p.y+engine.c['radius']])[-4:]))
                expected,first=source_counts([self.paths[t.sec] for t in self.mapping[identifier]],[halo,raw],engine.check)
                if expected!=[counts['entorno_mdt.las'],counts['original.las']] or first[1]!=int(row['n_primeros_retornos']):
                    raise ValueError('El recorte anterior no contiene todos los puntos de las entradas locales')
                verify_terrain(folder/'mdt.asc',p,engine.c['radius'],engine.check)
                engine.state.setdefault('legacy_recovery',[]).append({'cell':identifier,'source_run':str(engine.previous.source),
                    'terrain_points_verified':expected[0],'square_points_verified':expected[1],
                    'first_returns_verified':first[1],'original_tool_hashes':engine.previous.state.get('tools_sha256','not_recorded_in_0.1.0')})
            for name in (*ARTIFACTS,'cloudmetrics_gt2.csv'):
                if (folder/name).is_file():
                    verified_copy(folder/name,work/name,engine.check)
            if legacy:
                self.save(identifier,work,row)
            engine.progress(engine._last_progress,'Celda reutilizada y verificada: '+identifier)
            return row
        except (OSError,ValueError,KeyError) as error:
            # A rejected candidate must not leave partial artifacts in the fresh work dir.
            for name in (*ARTIFACTS,'cloudmetrics_gt2.csv'):
                (work/name).unlink(missing_ok=True)
            engine.progress(engine._last_progress,'Se recalcula '+identifier+': '+str(error))
            return None
