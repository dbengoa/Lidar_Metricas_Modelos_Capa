"""LAS/LAZ metadata and local point support, without laspy or network access.

Header envelopes describe point bounds, NOT official distribution footprints.
"""
from dataclasses import dataclass
from pathlib import Path
import math
import struct
import time
import errno
from .storage import LASBlockReader,transient,pause
from .core import Tile, digest, intersects, las_header

SUPPORTED_CRS = (25828,25829,25830,25831,4083)
MIN_RECORD = (20,28,26,34,57,63,30,36,38,59,67)


@dataclass(frozen=True)
class Metadata:
    path: str
    bbox: tuple
    count: int
    offset: int
    record_size: int
    point_format: int
    compressed: bool
    scales: tuple
    offsets: tuple
    epsg: object
    wkt: str
    crs_present: bool


def _metadata_once(path):
    path = Path(path).resolve()
    count = las_header(path, True)
    size = path.stat().st_size
    with path.open('rb') as f:
        h = f.read(375)
        header_size = struct.unpack_from('<H', h, 94)[0]
        offset = struct.unpack_from('<I', h, 96)[0]
        nvlr = struct.unpack_from('<I', h, 100)[0]
        record_size = struct.unpack_from('<H', h, 105)[0]
        fmt = h[104] & 63
        if fmt > 10 or h[104] & 64 or record_size < MIN_RECORD[fmt]:
            raise ValueError('Formato de puntos no compatible: '+path.name)
        if header_size < (375 if h[25] >= 4 else 235 if h[25] == 3 else 227) or header_size > offset or offset > size:
            raise ValueError('Cabecera LAS incoherente: '+path.name)
        scales = struct.unpack_from('<ddd', h, 131)
        offsets = struct.unpack_from('<ddd', h, 155)
        xmax,xmin,ymax,ymin,zmax,zmin = struct.unpack_from('<dddddd', h, 179)
        if not all(map(math.isfinite, (*scales,*offsets,xmin,ymin,xmax,ymax,zmin,zmax))) or min(scales) <= 0 or xmin >= xmax or ymin >= ymax or zmin > zmax:
            raise ValueError('Escalas o extensión inválidas: '+path.name)
        epsgs = set()
        wkts = set()
        crs_present = False

        def consume(user, record_id, payload):
            nonlocal crs_present
            if user.rstrip(b'\0 ') != b'LASF_Projection':
                return
            if record_id in (2112,34735):
                crs_present = True
            if record_id == 2112:
                wkts.add(payload.rstrip(b'\0').decode('utf-8', errors='strict'))
            elif record_id == 34735:
                if len(payload) < 8 or len(payload) % 2:
                    raise ValueError('GeoKeys truncadas: '+path.name)
                values = struct.unpack('<'+'H'*(len(payload)//2),payload)
                if len(values) < 4+4*values[3]:
                    raise ValueError('GeoKeys incompletas: '+path.name)
                for i in range(values[3]):
                    key,location,n,value = values[4+4*i:8+4*i]
                    if key == 3072 and location == 0 and n == 1 and value not in (0,32767):
                        epsgs.add(value)

        if nvlr > 100000:
            raise ValueError('Demasiados VLR: '+path.name)
        f.seek(header_size)
        for _ in range(nvlr):
            if f.tell()+54 > offset:
                raise ValueError('VLR fuera de la cabecera: '+path.name)
            vh = f.read(54)
            record_id,length = struct.unpack_from('<HH',vh,18)
            if f.tell()+length > offset:
                raise ValueError('VLR truncado: '+path.name)
            consume(vh[2:18], record_id, f.read(length))
        if h[25] >= 4:
            evlr_offset = struct.unpack_from('<Q',h,235)[0]
            nevlr = struct.unpack_from('<I',h,243)[0]
            if nevlr > 100000 or (nevlr and (evlr_offset < offset or evlr_offset > size)):
                raise ValueError('EVLR fuera del archivo: '+path.name)
            if nevlr:
                f.seek(evlr_offset)
            for _ in range(nevlr):
                if f.tell()+60 > size:
                    raise ValueError('EVLR truncado: '+path.name)
                vh = f.read(60)
                record_id = struct.unpack_from('<H',vh,18)[0]
                length = struct.unpack_from('<Q',vh,20)[0]
                if f.tell()+length > size:
                    raise ValueError('EVLR fuera del archivo: '+path.name)
                if vh[2:18].rstrip(b'\0 ') == b'LASF_Projection' and record_id in (2112,34735):
                    if length > 4*1024*1024:
                        raise ValueError('Registro CRS demasiado grande: '+path.name)
                    consume(vh[2:18],record_id,f.read(length))
                else:
                    f.seek(length,1)
        if len(epsgs)>1 or len(wkts)>1:
            raise ValueError('Definiciones CRS contradictorias: '+path.name)
    return Metadata(str(path),(xmin,ymin,xmax,ymax),count,offset,record_size,fmt,
                    bool(h[104]&128),scales,offsets,next(iter(epsgs),None),next(iter(wkts),''),crs_present)


def metadata(path,check=lambda:None,progress=lambda text:None):
    for attempt in range(4):
        check()
        try:return _metadata_once(path)
        except OSError as error:
            if attempt<3 and (transient(error) or error.errno==errno.EINVAL):
                progress('Lectura de cabecera LAS '+str(path)+'; reintento '+str(attempt+1)+': '+str(error))
                pause((.2,.5,1.0)[attempt],check)
                continue
            raise OSError(error.errno,'Lectura de metadatos LAS '+str(path)+': '+str(error),str(path)) from error


def resolve_epsg(info, expected, assume_missing=False):
    codes = set()
    if info.epsg:
        codes.add(info.epsg)
    if info.wkt:
        from osgeo import osr
        crs = osr.SpatialReference()
        if crs.ImportFromWkt(info.wkt) != 0:
            raise ValueError('WKT no válido: '+Path(info.path).name)
        if crs.IsCompound():
            crs.StripVertical()
        crs.AutoIdentifyEPSG()
        code = crs.GetAuthorityCode('PROJCS') or crs.GetAuthorityCode(None)
        if code is None:
            matches = crs.FindMatches()
            code = next((s.GetAuthorityCode(None) for s, confidence in matches if confidence >= 95 and s.GetAuthorityCode(None)),None)
        if code is None:
            raise ValueError('No se puede identificar el CRS WKT: '+Path(info.path).name)
        codes.add(int(code))
    if len(codes)>1:
        raise ValueError('WKT y GeoTIFF declaran CRS distintos: '+Path(info.path).name)
    if not codes:
        if info.crs_present or not assume_missing:
            raise ValueError('CRS ausente o no identificable en '+Path(info.path).name+'. Sólo si lo ha comprobado, active «Asumir CRS de parcelas si falta».')
        return expected,True
    actual = codes.pop()
    if actual != expected or actual not in SUPPORTED_CRS:
        raise ValueError('CRS incompatible en '+Path(info.path).name+': EPSG:'+str(actual)+'; parcelas EPSG:'+str(expected))
    return actual,False


def discover(files, expected, assume_missing=False, check=lambda:None, progress=lambda n,s:None):
    """Resolve files and deduplicate exact bytes. No filename-based CRS inference."""
    if not files:
        raise ValueError('Seleccione archivos LAZ/LAS descargados de CNIG')
    if expected not in SUPPORTED_CRS:
        raise ValueError('CRS de parcelas no compatible')
    result, inventory, seen, paths = [],[],set(),set()
    for i,source in enumerate(files):
        check()
        path = Path(source).resolve()
        if path in paths:
            continue
        paths.add(path)
        if path.suffix.lower() not in ('.las','.laz') or not path.is_file():
            raise ValueError('Archivo LAZ/LAS inexistente: '+str(path))
        progress(2+8*i/len(files),'Leyendo metadatos '+path.name)
        info = metadata(path)
        epsg,assumed = resolve_epsg(info,expected,assume_missing)
        sha = digest(path,check)
        inventory.append({'source':str(path),'bbox_points':info.bbox,'epsg':epsg,
                          'crs_assumed':assumed,'sha256':sha,'points':info.count,
                          'duplicate':sha in seen,'series':'not_verified_from_header'})
        if sha in seen:
            continue
        seen.add(sha)
        result.append(Tile(sha[:24],path.name,info.bbox,epsg,sha256=sha,source=str(path)))
    return result,inventory


def select_local(plots, radius, tiles):
    """Select by point envelopes. Never claim official footprint coverage from them."""
    selected, mapping = {},{}
    for p in plots:
        hits = [t for t in tiles if intersects(p,radius,t.bbox)]
        if not hits:
            raise ValueError('No hay archivos locales cerca de la parcela '+p.id+'. Añada las teselas vecinas.')
        for i,t in enumerate(hits):
            for u in hits[i+1:]:
                a = (max(t.bbox[0],u.bbox[0]),max(t.bbox[1],u.bbox[1]),min(t.bbox[2],u.bbox[2]),min(t.bbox[3],u.bbox[3]))
                if a[0]<a[2] and a[1]<a[3] and intersects(p,radius,a):
                    raise ValueError('Nubes locales solapadas cerca de ID '+p.id+'. Seleccione un solo vuelo/nivel por tesela: '+t.name+' / '+u.name)
        mapping[p.id] = hits
        selected.update({t.key:t for t in hits})
    return list(selected.values()),mapping


def verify_point_support(paths, plot, radius, distance=5., check=lambda:None,progress=lambda text:None):
    """Require real returns AND class-2 support near samples of the plot + halo.

    This is a sampled gap check, not a proof of acquisition completeness. Unfilled
    samples and their coordinates are returned in errors, never silently interpolated.
    Numpy is shipped with QGIS. Only uncompressed derived LAS is scanned.
    """
    import numpy as np
    if not math.isfinite(distance) or distance < .5 or distance > 20:
        raise ValueError('La distancia de apoyo debe estar entre 0,5 y 20 m')
    step = distance/2
    half = math.ceil(radius/step)
    if (2*half+1)**2 > 500000:
        raise ValueError('Demasiadas muestras para comprobar cobertura; reduzca el radio')
    offsets = np.arange(-half,half+1,dtype=float)*step
    xx,yy = np.meshgrid(offsets,offsets)
    mask = xx**2+yy**2 <= radius**2
    sx = xx[mask]+plot.x
    sy = yy[mask]+plot.y
    supported = np.zeros(len(sx),dtype=bool)
    ground = np.zeros(len(sx),dtype=bool)
    for path in paths:
        check()
        progress('Cobertura: leyendo '+str(path))
        info = metadata(path,check,progress)
        if info.compressed:
            raise ValueError('La comprobación de puntos requiere LAS convertido')
        dtype = np.dtype({'names':['x','y','c','flags'],
                          'formats':['<i4','<i4','u1','u1'],
                          'offsets':[0,4,15 if info.point_format<6 else 16,15],
                          'itemsize':info.record_size})
        with LASBlockReader(path,check,progress) as reader:
            remaining = info.count
            cursor=info.offset;last_report=time.monotonic()
            while remaining:
                check()
                n = min(remaining,max(1,(1024*1024)//info.record_size))
                block = reader.read_exact(cursor,n*info.record_size)
                cursor+=len(block)
                if time.monotonic()-last_report>=10:
                    progress('Cobertura: '+str(path)+' · '+format(100*(info.count-remaining+n)/info.count,'.1f')+'% leído')
                    last_report=time.monotonic()
                if len(block) != n*info.record_size:
                    raise ValueError('LAS truncado durante lectura: '+str(path))
                remaining -= n
                a = np.frombuffer(block,dtype=dtype,count=n)
                x = a['x']*info.scales[0]+info.offsets[0]
                y = a['y']*info.scales[1]+info.offsets[1]
                good = (abs(x-plot.x)<=radius+distance)&(abs(y-plot.y)<=radius+distance)
                if info.point_format<6:
                    good &= (a['c']&128)==0
                    classes = a['c']&31
                else:
                    good &= (a['flags']&4)==0
                    classes = a['c']
                x,y,classes = x[good],y[good],classes[good]
                if not len(x):
                    continue
                # Blocks of nearby points bound temporary memory independently of file size.
                for start in range(0,len(x),2048):
                    check()
                    xpart,ypart,cp = x[start:start+2048],y[start:start+2048],classes[start:start+2048]
                    # Batch samples too, so a large plot does not allocate an unbounded matrix.
                    for si in range(0,len(sx),256):
                        d2 = (sx[si:si+256,None]-xpart)**2+(sy[si:si+256,None]-ypart)**2
                        supported[si:si+256] |= np.any(d2 <= distance**2,axis=1)
                        if np.any(cp==2):
                            ground[si:si+256] |= np.any(d2[:,cp==2] <= distance**2,axis=1)
    for label,values in (('puntos',supported),('suelo clase 2',ground)):
        missing = np.flatnonzero(~values)
        if len(missing):
            i = missing[0]
            raise ValueError('Cobertura local insuficiente ('+label+') para ID '+plot.id+
                             ': '+str(len(missing))+' muestras sin apoyo a '+str(distance)+
                             ' m; primera en '+format(sx[i],'.3f')+', '+format(sy[i],'.3f')+
                             '. Añada las teselas vecinas o revise la densidad/clasificación.')
    return {'method':'sampled_point_and_class2_support','sample_count':len(sx),
            'spacing_m':step,'max_distance_m':distance,'radius_with_halo_m':radius,
            'official_footprint_verified':False}
