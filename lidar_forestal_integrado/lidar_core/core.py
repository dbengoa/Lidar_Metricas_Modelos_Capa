"""Portable validation, coverage and FUSION commands. No QGIS imports."""
from dataclasses import dataclass
from pathlib import Path
import csv
import hashlib
import json
import math
import re
import struct

CATALOG = 'https://centrodedescargas.cnig.es/CentroDescargas/catalogo.do?Serie=LIDA3'
DETAIL = 'https://centrodedescargas.cnig.es/CentroDescargas/detalleArchivo?sec='
VERSION = '0.4.7-experimental'

class Cancelled(Exception):
    pass

class AuthorizationRequired(Exception):
    pass

@dataclass(frozen=True)
class Plot:
    id: str
    x: float
    y: float

@dataclass(frozen=True)
class Tile:
    sec: str
    name: str
    bbox: tuple
    epsg: int
    url: str = ''
    sha256: str = ''
    source: str = ''

    @property
    def key(self):
        return self.sec


def token(value):
    return hashlib.sha256(str(value).encode('utf-8')).hexdigest()[:24]


def validate(plots, radius, directory):
    if not math.isfinite(radius) or radius <= 0:
        raise ValueError('Radio inválido')
    if any(c.isspace() for c in str(directory)):
        raise ValueError('La carpeta no puede contener espacios ni otros blancos')
    seen = set()
    if not plots:
        raise ValueError('La capa no contiene parcelas')
    for p in plots:
        if not p.id.strip() or p.id in seen or not all(map(math.isfinite, (p.x, p.y))):
            raise ValueError('ID vacío/duplicado o coordenadas no finitas: ' + p.id)
        seen.add(p.id)


def read_index(path, epsg):
    """Explicit official tile bounds; never infer a footprint from its filename."""
    tiles = {}
    with open(path, encoding='utf-8-sig', newline='') as f:
        for row in csv.DictReader(f):
            if row['series'] != 'LIDA3':
                raise ValueError('El índice debe contener exclusivamente LIDA3')
            sec, name = row['sec'], row['name']
            if not sec.isdigit() or not re.fullmatch(r'[A-Za-z0-9_.+-]+\.(?:laz|las)', name, re.I):
                raise ValueError('Identificador CNIG o nombre no válido')
            b = tuple(float(row[k]) for k in ('xmin','ymin','xmax','ymax'))
            if not all(map(math.isfinite, b)) or b[0] >= b[2] or b[1] >= b[3]:
                raise ValueError('Extensión inválida: ' + name)
            t = Tile(sec, name, b, int(row['epsg']), row.get('url', ''), row.get('sha256', ''))
            if t.epsg != epsg:
                raise ValueError('El índice y las parcelas deben usar el mismo CRS UTM')
            if sec in tiles and tiles[sec] != t:
                raise ValueError('Tesela duplicada con metadatos contradictorios: ' + sec)
            tiles[sec] = t
    if not tiles:
        raise ValueError('Índice vacío')
    return list(tiles.values())


def intersects(p, radius, b):
    dx = max(b[0]-p.x, 0, p.x-b[2])
    dy = max(b[1]-p.y, 0, p.y-b[3])
    return dx*dx + dy*dy < radius*radius


def covers(p, radius, tiles):
    """Exact disk-versus-union of axis-aligned footprints by vertical slab sweep.

    Inside each slab, coverage intervals are constant; test each uncovered rectangle
    for positive-area intersection with the disk. Tile boundaries have zero area.
    """
    x0, x1, y0, y1 = p.x-radius, p.x+radius, p.y-radius, p.y+radius
    xs = sorted({x0, x1} | {max(x0, min(x1, x)) for t in tiles for x in (t.bbox[0], t.bbox[2])})
    for a, b in zip(xs, xs[1:]):
        mid = (a+b)/2
        intervals = sorted((max(y0,t.bbox[1]),min(y1,t.bbox[3])) for t in tiles if t.bbox[0] <= mid <= t.bbox[2] and t.bbox[3] > y0 and t.bbox[1] < y1)
        cursor = y0
        gaps = []
        for lo, hi in intervals:
            if lo > cursor:
                gaps.append((cursor,lo))
            cursor = max(cursor,hi)
        if cursor < y1:
            gaps.append((cursor,y1))
        if any(intersects(p, radius, (a,lo,b,hi)) for lo,hi in gaps):
            return False
    return True


def select_tiles(plots, radius, tiles):
    selected = {}
    per_plot = {}
    for p in plots:
        hits = [t for t in tiles if intersects(p, radius, t.bbox)]
        if not covers(p, radius, hits):
            raise ValueError('Cobertura CNIG incompleta para ID ' + p.id)
        # Different products covering the same ground cannot be combined silently.
        for i, t in enumerate(hits):
            for u in hits[i+1:]:
                a = (max(t.bbox[0],u.bbox[0]),max(t.bbox[1],u.bbox[1]),min(t.bbox[2],u.bbox[2]),min(t.bbox[3],u.bbox[3]))
                if a[0] < a[2] and a[1] < a[3] and intersects(p, radius, a):
                    raise ValueError('Vuelos o niveles solapados: elija una versión de cada tesela')
        per_plot[p.id] = hits
        selected.update({t.key:t for t in hits})
    return list(selected.values()), per_plot


def las_header(path, allow_compressed=False):
    """Check LAS 1.0–1.4 structure and that all uncompressed point records exist."""
    with open(path, 'rb') as f:
        h = f.read(375)
    if len(h) < 227 or h[:4] != b'LASF' or h[24] != 1 or h[25] > 4:
        raise ValueError('Cabecera LAS/LAZ inválida: ' + str(path))
    offset = struct.unpack_from('<I', h, 96)[0]
    size = struct.unpack_from('<H', h, 105)[0]
    count = struct.unpack_from('<I', h, 107)[0]
    if h[25] >= 4:
        if len(h) < 375:
            raise ValueError('Cabecera LAS 1.4 truncada')
        count = struct.unpack_from('<Q', h, 247)[0] or count
    compressed = bool(h[104] & 128)
    if not count or not size or offset < 227:
        raise ValueError('Nube vacía o cabecera incoherente')
    if compressed and not allow_compressed:
        raise ValueError('Se esperaba LAS sin comprimir')
    if Path(path).stat().st_size < (offset + (1 if compressed else count*size)):
        raise ValueError('Archivo de puntos truncado')
    return count


def digest(path, check=lambda:None):
    h = hashlib.sha256()
    with open(path,'rb') as f:
        for block in iter(lambda:f.read(1024*1024), b''):
            check()
            h.update(block)
    return h.hexdigest()


def commands(fusion, source, las, listing, terrain, raw, normalized, metrics, p, radius, zone, cell=1, height_cutoff=None):
    height_cutoff = validate_height_cutoff(height_cutoff)
    from .fusion import program
    exe = lambda name: str(program(fusion,name))
    bounds = [format(n, '.12g') for n in (p.x-radius,p.y-radius,p.x+radius,p.y+radius)]
    return {
        'convert':[exe('LDA2LAS'),str(source),str(las)],
        'terrain':[exe('GridSurfaceCreate'),'/class:2',str(terrain),str(cell),'M','M','1',str(zone),'0','0',str(listing)],
        'raw':[exe('ClipData'),'/shape:1',str(listing),str(raw),*bounds],
        'normalize':[exe('ClipData'),'/shape:1','/dtm:'+str(terrain),'/height',str(listing),str(normalized),*bounds],
        'metrics':[exe('CloudMetrics'),'/new',*(['/minht:'+format(height_cutoff,'.12g')] if height_cutoff is not None else []),str(normalized),str(metrics)],
    }


# Public API retained for callers and existing receipts.
from .storage import atomic_json


def validate_height_cutoff(value):
    """None disables filtering; zero explicitly selects returns above ground."""
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError('Altura de corte inválida')
    value = float(value)
    if not math.isfinite(value) or value < 0:
        raise ValueError('La altura de corte debe ser finita y mayor o igual a 0 m')
    return value


def metrics_row(plot, radius, total_count, result, height_cutoff=None):
    cutoff = validate_height_cutoff(height_cutoff)
    selected = total_count
    if cutoff is not None:
        counts = [v for k,v in result.items() if k.strip().lower().startswith('total return count above ')]
        if len(counts) != 1:
            raise ValueError('CloudMetrics no informó el número de retornos sobre el corte para ID '+plot.id)
        selected = int(counts[0])
        if not 0 < selected <= total_count:
            raise ValueError('Sin retornos válidos sobre la altura de corte para ID '+plot.id)
        minimum = float(result['Elev minimum'])
        if not math.isfinite(minimum) or minimum < cutoff:
            raise ValueError('CloudMetrics no respetó la altura de corte para ID '+plot.id)
    return {'parcela_id':plot.id, 'x':plot.x, 'y':plot.y, 'radio_m':radius,
            'n_puntos':total_count, 'n_puntos_metricas':selected,
            'altura_corte_m':cutoff if cutoff is not None else '',
            'filtro_altura':'mayor_que' if cutoff is not None else 'sin_filtro',
            **{'cm_'+k:v for k,v in result.items()}}


def terrain_clip_command(fusion, listing, output, plot, radius, cell, support=5.):
    """Keep original XYZ/classes; include a square halo before constructing MDT.

    Selected neighboring tiles are all read into ONE LAS. Coverage and actual MDT
    checks remain mandatory; a buffered subset is not evidence of full coverage.
    """
    from .fusion import program
    if not all(math.isfinite(v) and v > 0 for v in (radius, cell, support)):
        raise ValueError('Radio, celda y apoyo deben ser positivos y finitos')
    extent = radius + 2*cell + support
    bounds = [format(v,'.12g') for v in (plot.x-extent,plot.y-extent,plot.x+extent,plot.y+extent)]
    return [str(program(fusion,'ClipData')), '/shape:0', str(listing), str(output), *bounds]
