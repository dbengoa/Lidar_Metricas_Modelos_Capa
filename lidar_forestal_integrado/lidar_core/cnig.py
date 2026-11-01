"""PNOA3 discovery using the actual CNIG portal protocol, verified 2026-10-18.

Only catalog/footprint requests use urllib. Binary downloads ALWAYS go through
normal Chrome with a human click; OfficialBrowser watches completed files.
"""
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request,build_opener,HTTPRedirectHandler,HTTPCookieProcessor
from urllib.error import HTTPError,URLError
from http.cookiejar import CookieJar
import html
import json
import math
import re
import threading
import time
from .core import atomic_json,las_header,digest
from .browser import OfficialBrowser

BASE='https://centrodedescargas.cnig.es/CentroDescargas/'


class CatalogError(RuntimeError):pass


class Redirect(HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        if not newurl.startswith(BASE):raise CatalogError('Redirección fuera del catálogo CNIG')
        return super().redirect_request(req,fp,code,msg,headers,newurl)


class Inputs(HTMLParser):
    def __init__(self,text):
        super().__init__(convert_charrefs=True);self.values={};self.feed(text)
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=='input' and a.get('id'):self.values[a['id']]=a.get('value','')


def parse_page(text):
    values=Inputs(text).values
    if values.get('codSerie')!='LIDA3' or not values.get('totalArchivos','').isdigit():
        raise CatalogError('Respuesta CNIG no reconocida como catálogo LIDA3; no se interpreta como ausencia de cobertura')
    records=[]
    # Pair within one desktop row, never by parallel filename/id arrays.
    for row in re.findall(r'<tr\b[^>]*>(.*?)</tr>',text,re.I|re.S):
        ids=re.findall(r'id\s*=\s*[\"\']linkDescDir_(\d+)[\"\']',row,re.I)
        if not ids:continue
        names=set(re.findall(r'PNOA[-_][A-Za-z0-9_.+\-]+\.LAZ',html.unescape(row),re.I))
        if len(set(ids))!=1 or len(names)!=1:
            raise CatalogError('CNIG cambió el formato de las filas de descarga')
        name=names.pop()
        records.append({'sec':ids[0],'name':name,'series':'LIDA3'})
    total=int(values['totalArchivos'])
    if total and not records:raise CatalogError('El catálogo informa archivos pero no ofrece filas LAZ reconocibles')
    return records,total


def rank_name(name):
    # Used to compare editions of a returned tile, never to invent its footprint.
    m=re.fullmatch(r'PNOA[-_](\d{4})[-_].+?[-_](\d{3})[-_](\d{4})(?:[-_]H(\d{2}))?[-_]NPC(\d{2})(\+?)\.LAZ',name,re.I)
    if not m:raise CatalogError('Nomenclatura PNOA3 no reconocida: '+name)
    year,x,y,zone,npc,plus=m.groups()
    return (int(x),int(y),int(zone) if zone else None),(int(year),int(npc),bool(plus))


def prefer_versions(records,epsg):
    zone=28 if epsg==4083 else epsg-25800
    groups={};excluded=[]
    for r in records:
        key,rank=rank_name(r['name'])
        if key[2] is not None and key[2]!=zone:
            excluded.append({**r,'reason':'different_utm_zone'});continue
        # Missing Hxx is not a CRS declaration. Group editions in this query;
        # official geometry and downloaded CRS remain mandatory checks.
        group_key=(key[0],key[1],zone)
        groups.setdefault(group_key,[]).append((rank,r))
    chosen=[]
    for group in groups.values():
        best=max(rank for rank,r in group)
        leaders=[r for rank,r in group if rank==best]
        if len(leaders)>1:
            raise CatalogError('CNIG ofrece dos archivos del mismo año/nivel para la misma tesela; no se mezclan automáticamente: '+', '.join(r['name'] for r in leaders))
        chosen.append(leaders[0])
        excluded.extend({**r,'reason':'older_flight_or_lower_npc'} for rank,r in group if rank!=best)
    return chosen,excluded


class Client:
    def __init__(self,check=lambda:None,opener=None):
        self.check=check
        self.opener=opener or build_opener(Redirect(),HTTPCookieProcessor(CookieJar()))

    def request(self,endpoint,data):
        if endpoint not in ('archivosSerie','localizarCoordsSec'):
            raise CatalogError('Endpoint de consulta no permitido')
        body=urlencode(data).encode('utf-8')
        for attempt in range(3):
            self.check()
            try:
                req=Request(BASE+endpoint,data=body,headers={'User-Agent':'InventarioForestalLiDAR/0.3','X-Requested-With':'XMLHttpRequest'})
                with self.opener.open(req,timeout=30) as r:
                    if not r.url.startswith(BASE):raise CatalogError('Respuesta fuera del catálogo CNIG')
                    blocks=[];size=0
                    while True:
                        self.check();block=r.read(65536)
                        if not block:break
                        size+=len(block)
                        if size>16*1024*1024:raise CatalogError('Respuesta de catálogo CNIG demasiado grande')
                        blocks.append(block)
                    return b''.join(blocks).decode('utf-8')
            except HTTPError as e:
                if e.code not in (429,500,502,503,504) or attempt==2:
                    raise CatalogError('CNIG '+endpoint+' HTTP '+str(e.code)+'. Reintente más tarde; no se ha sustituido por entrada manual.') from None
            except (URLError,TimeoutError):
                if attempt==2:raise CatalogError('No se pudo conectar con '+endpoint+' de CNIG; reintente cuando el servicio esté disponible') from None
            deadline=time.monotonic()+2**attempt
            while time.monotonic()<deadline:self.check();time.sleep(.1)

    def search(self,geojson):
        found={};page=1;total=None;last=None
        while page<=1000:
            self.check()
            params={'numPagina':str(page),'codAgr':'MOMDT','codSerie':'LIDA3',
                    'coordenadas':json.dumps(geojson,separators=(',',':')),'todaEspania':'N','todoMundo':'N'}
            rows,count=parse_page(self.request('archivosSerie',params))
            if total is not None and count!=total:raise CatalogError('El catálogo cambió durante la paginación; vuelva a consultar')
            total=count
            sig=tuple(r['sec'] for r in rows)
            if rows and sig==last:raise CatalogError('CNIG repitió la misma página; se detiene para evitar descargas incompletas')
            last=sig
            for r in rows:
                if r['sec'] in found and found[r['sec']]['name']!=r['name']:
                    raise CatalogError('Metadatos contradictorios para sec='+r['sec'])
                found[r['sec']]=r
            if len(found)>=total:return list(found.values())
            if not rows:raise CatalogError('Paginación CNIG incompleta')
            page+=1
        raise CatalogError('Demasiadas páginas CNIG para una parcela; reduzca el radio')

    def footprint(self,sec):
        payload=json.loads(self.request('localizarCoordsSec',{'secuencial':sec}))
        if str(payload.get('secuencial'))!=str(sec):raise CatalogError('CNIG devolvió una huella de otra tesela')
        data=payload.get('coordsJson')
        if isinstance(data,str):data=json.loads(data)
        if not isinstance(data,dict) or data.get('type')!='FeatureCollection' or not data.get('features'):
            raise CatalogError('Huella oficial CNIG no reconocida')
        for f in data['features']:
            if f.get('geometry',{}).get('type') not in ('Polygon','MultiPolygon'):
                raise CatalogError('La huella CNIG no es poligonal')
        return data


def transforms(epsg):
    from osgeo import osr
    projected=osr.SpatialReference();projected.ImportFromEPSG(epsg)
    geographic=osr.SpatialReference();geographic.ImportFromEPSG(4326)
    for crs in (projected,geographic):crs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    return osr.CoordinateTransformation(projected,geographic),osr.CoordinateTransformation(geographic,projected)


def query_polygon(plot,radius,to_geo):
    # Bounding square, densified before reprojection; conservative over-selection
    # is removed with the official footprint and later actual cloud checks.
    x0,y0,x1,y1=plot.x-radius,plot.y-radius,plot.x+radius,plot.y+radius
    ring=[]
    corners=[(x0,y0),(x1,y0),(x1,y1),(x0,y1),(x0,y0)]
    for (a,b),(c,d) in zip(corners,corners[1:]):
        for step in range(8):
            lon,lat,*_=to_geo.TransformPoint(a+(c-a)*step/8,b+(d-b)*step/8)
            if not all(map(math.isfinite,(lon,lat))) or not -180<=lon<=180 or not -90<=lat<=90:
                raise CatalogError('No se pudieron transformar las parcelas a coordenadas de consulta CNIG')
            ring.append([lon,lat])
    ring.append(ring[0])
    return {'type':'FeatureCollection','features':[{'type':'Feature','properties':{},'geometry':{'type':'Polygon','coordinates':[ring]}}]}


def projected_footprint(data,to_projected):
    from osgeo import ogr
    merged=None
    for feature in data['features']:
        geometry=ogr.CreateGeometryFromJson(json.dumps(feature['geometry']))
        if geometry is None or geometry.IsEmpty() or not geometry.IsValid():raise CatalogError('Geometría CNIG vacía o inválida')
        if geometry.Transform(to_projected)!=0 or not geometry.IsValid() or not all(map(math.isfinite,geometry.GetEnvelope())):
            raise CatalogError('No se pudo reproyectar la huella CNIG')
        merged=geometry if merged is None else merged.Union(geometry)
    return merged


def disk(plot,radius):
    from osgeo import ogr
    ring=ogr.Geometry(ogr.wkbLinearRing)
    r=radius/math.cos(math.pi/256)
    for i in range(257):
        angle=2*math.pi*i/256
        ring.AddPoint_2D(plot.x+r*math.cos(angle),plot.y+r*math.sin(angle))
    geometry=ogr.Geometry(ogr.wkbPolygon);geometry.AddGeometry(ring)
    return geometry


class AutomaticSource:
    def __init__(self,root,work,check=lambda:None,progress=lambda n,s:None,retry=None,client=None,browser_factory=OfficialBrowser,download_directory=None,batch_download=False,batch_limit=20):
        self.root=Path(root);self.work=Path(work)
        self.check=check;self.progress=progress;self.retry=retry or threading.Event()
        self.client=client or Client(check)
        self.browser_factory=browser_factory
        self.download_directory=download_directory
        from .batches import batch_size
        self.batch_download = batch_download
        self.batch_limit = batch_size(batch_limit)

    def plan(self,plots,epsg,radius,cell,support=5.):
        to_geo,to_projected=transforms(epsg)
        records={};queries=[]
        for i,p in enumerate(plots):
            self.check();self.progress(1+8*i/len(plots),'CNIG buscando PNOA3 para parcela '+p.id)
            rows=self.client.search(query_polygon(p,radius+2*cell+support,to_geo))
            if not rows:raise CatalogError('CNIG no publica teselas LIDA3 para parcela '+p.id)
            queries.append({'id':p.id,'candidate_secs':[r['sec'] for r in rows]})
            for row in rows:
                if row['sec'] in records and records[row['sec']]['name']!=row['name']:
                    raise CatalogError('Nombre contradictorio para tesela CNIG '+row['sec'])
                records[row['sec']]=row
        selected,excluded=prefer_versions(list(records.values()),epsg)
        shapes={}
        for i,row in enumerate(selected):
            self.check();self.progress(9+5*i/max(1,len(selected)),'CNIG comprobando huella '+row['name'])
            footprint=self.client.footprint(row['sec'])
            row['official_footprint_wgs84']=footprint
            shapes[row['sec']]=projected_footprint(footprint,to_projected)
        atomic_json(self.work/'catalogo_cnig.json',{'series':'LIDA3','queries':queries,'candidates':selected,'excluded':excluded})
        used={};coverage=[]
        for p in plots:
            self.check();circle=disk(p,radius+2*cell)
            union=None;hits=[]
            for row in selected:
                shape=shapes[row['sec']]
                if circle.Intersects(shape):
                    hits.append(row['sec']);used[row['sec']]=row
                    union=shape.Clone() if union is None else union.Union(shape)
            gap=circle.GetArea() if union is None else circle.Difference(union.Buffer(.02)).GetArea()
            report={'id':p.id,'secs':hits,'uncovered_area_m2':gap,'tolerance_m':.02,'method':'official_cnig_footprint_union'}
            coverage.append(report)
            if gap>.01:
                atomic_json(self.work/'cobertura_cnig.json',coverage)
                raise CatalogError('Cobertura oficial PNOA3 incompleta para ID '+p.id+' ('+format(gap,'.3f')+' m² sin cobertura). No se calcularán métricas parciales.')
        plan={'series':'LIDA3','edition_policy':'newest_flight_year_then_highest_npc','queries':queries,
              'selected':list(used.values()),'excluded':excluded}
        atomic_json(self.work/'plan_cnig.json',plan)
        atomic_json(self.work/'cobertura_cnig.json',coverage)
        if not used:raise CatalogError('No hay teselas PNOA3 seleccionadas')
        return list(used.values())

    def acquire(self,plots,epsg,radius,cell,support=5.):
        selected=self.plan(plots,epsg,radius,cell,support)
        files=[];missing=[]
        for row in selected:
            dest=self.root/'originales'/row['sec']/row['name']
            if not dest.exists():
                normalize=lambda name:name.replace('_','-').upper()
                matches=[]
                for folder in (self.root/'originales',dest.parent):
                    if folder.is_dir():
                        matches.extend(p for p in folder.iterdir() if p.is_file() and normalize(p.name)==normalize(row['name']))
                if matches:
                    fingerprints={digest(p,self.check) for p in matches}
                    if len(fingerprints)>1:raise CatalogError('Originales existentes contradictorios para '+row['name'])
                    dest=sorted(matches)[0]
            if dest.exists():
                las_header(dest,True)
                receipt=dest.with_suffix(dest.suffix+'.json')
                current=digest(dest,self.check)
                if receipt.exists() and json.loads(receipt.read_text(encoding='utf-8')).get('sha256')!=current:
                    raise CatalogError('El original existente cambió: '+str(dest)+'. Se conserva y no se sobrescribe.')
                if not receipt.exists():
                    atomic_json(receipt,{'series':'LIDA3','sec':row['sec'],'name':row['name'],
                        'sha256':current,'download_flow':'existing_original_header_validation'})
                files.append(str(dest));self.progress(15,'CNIG reutiliza '+row['name'])
            else:missing.append((row,dest))
        if missing:
            self.progress(15,'CNIG abre Google Chrome para descarga y autorización oficial')
            options={'download_directory':self.download_directory} if self.download_directory else {}
            with self.browser_factory(self.work,self.check,lambda text:self.progress(15,text),self.retry,**options) as browser:
                incorporated = 0
                def received(row, dest):
                    nonlocal incorporated
                    las_header(dest,True)
                    atomic_json(dest.with_suffix(dest.suffix+'.json'),{'series':'LIDA3','sec':row['sec'],
                        'name':row['name'],'sha256':digest(dest,self.check),
                        'download_flow':'normal_chrome_human_batch_filesystem' if self.batch_download else 'normal_chrome_human_download_filesystem'})
                    files.append(str(dest))
                    incorporated += 1
                    self.progress(15+15*incorporated/len(missing),'CNIG descarga completada '+row['name'])
                if self.batch_download:
                    for start in range(0,len(missing),self.batch_limit):
                        self.check()
                        browser.download_batch(missing[start:start+self.batch_limit],start//self.batch_limit+1,received)
                else:
                    for row,dest in missing:
                        self.check()
                        browser.download(row,dest)
                        received(row,dest)
        return files
