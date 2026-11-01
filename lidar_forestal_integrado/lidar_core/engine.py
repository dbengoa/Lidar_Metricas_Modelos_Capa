"""Cancellable workflow. Original data are never overwritten or deleted."""
from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import urlparse
from urllib.request import urlopen, Request
from urllib.error import HTTPError
import csv
import json
import os
import subprocess
import time
import threading
import uuid
import traceback
from .fusion import PROGRAMS, program, invocation, failure_message
from .storage import StateStorageError, diagnostic_root
from .coverage import first_return_cover
from .core import (Cancelled, AuthorizationRequired, DETAIL, VERSION, token,
                   validate, read_index, select_tiles, las_header, digest, commands, atomic_json, validate_height_cutoff, metrics_row, terrain_clip_command)


def official_url(url):
    p = urlparse(url)
    if p.scheme != 'https' or p.hostname != 'centrodedescargas.cnig.es' or p.username or p.password or p.port not in (None,443):
        raise ValueError('Se requiere un enlace HTTPS oficial de centrodedescargas.cnig.es')
    return url


class OfficialRedirect(__import__('urllib.request', fromlist=['HTTPRedirectHandler']).HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        official_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class Engine:
    def __init__(self, config, plots, cancelled=lambda:False, progress=lambda n,s:None,retry_authorization=None, pause_requested=None):
        self.c = config
        self.plots = plots
        self.cancelled = cancelled
        self._progress = progress
        self._last_progress = 0
        self.progress = self.report_progress
        self.retry_authorization = retry_authorization or threading.Event()
        self.pause_requested = pause_requested or threading.Event()
        self.paused_seconds = 0.
        self.state = {'version':VERSION, 'status':'running', 'plots':[], 'tiles':[]}

    def report_progress(self,n,text):
        n=max(self._last_progress,min(100,float(n)))
        self._last_progress=n
        self._progress(n,text)
        if hasattr(self,'logfile'):
            self.log('PROGRESO '+format(n,'.1f')+' '+text)

    def check_cancelled(self):
        if self.cancelled():
            raise Cancelled('Cancelado por el usuario')

    def check(self):
        self.check_cancelled()
        if not self.pause_requested.is_set():
            return
        started = time.monotonic()
        self.state['status'] = 'paused'
        try:
            if hasattr(self, 'run'):
                self.save_state(final=True)
            self.progress(self._last_progress, 'En pausa. Pulse «Reanudar» para continuar.')
            while self.pause_requested.is_set():
                self.check_cancelled()
                time.sleep(.1)
            self.check_cancelled()
        finally:
            self.paused_seconds += time.monotonic() - started
            self.state['status'] = 'running'
        if hasattr(self, 'run'):
            self.save_state(final=True)
        self.progress(self._last_progress, 'Proceso reanudado.')

    def diagnostics_directory(self):
        directory=diagnostic_root()/self.run.name
        directory.mkdir(parents=True,exist_ok=True)
        return directory

    def backup_state(self):
        target=self.diagnostics_directory()/'estado.json'
        self.state['diagnostic_state']=str(target)
        atomic_json(target,self.state)
        self.local_diagnostic_path=target
        return target

    def save_state(self,final=False):
        try:
            atomic_json(self.run/'estado.json',self.state,check=(lambda:None) if final else self.check)
        except OSError as error:
            self.state['state_storage_error']={'path':str(self.run/'estado.json'),'error':str(error)}
            try:
                backup=self.backup_state()
                detail='Diagnóstico alternativo: '+str(backup)
            except OSError as backup_error:
                detail='Tampoco se pudo guardar el diagnóstico alternativo: '+str(backup_error)
            raise StateStorageError('No se pudo guardar el estado en '+str(self.run)+
                ' tras los reintentos de escritura. Compruebe la disponibilidad de la carpeta/unidad. '+
                detail+'. Los LAZ y LAS completos se conservan.') from error

    def log(self,text):
        line=datetime.now(timezone.utc).isoformat()+' '+text+'\n'
        try:
            with self.logfile.open('a',encoding='utf-8') as handle:handle.write(line)
        except OSError as error:
            # Reporting a failure must never replace the original exception.
            self.state['logging_error']=str(error)
            try:
                target=self.diagnostics_directory()/'proceso.log'
                with target.open('a',encoding='utf-8') as handle:handle.write(line)
                self.local_log_path=target
            except OSError as backup_error:
                self.state['local_logging_error']=str(backup_error)

    def run_command(self, args):
        self.check()
        args,launch=invocation(args,self.logfile)
        self.state['active_command']=list(map(str,args))
        if hasattr(self,'run'):self.save_state()
        self.log('COMANDO '+subprocess.list2cmdline(args))
        started=time.monotonic();last_report=started
        with self.logfile.open('a', encoding='utf-8') as f:
            kwargs = {'creationflags':subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == 'nt' else {}
            proc = subprocess.Popen(list(map(str,args)), stdout=f, stderr=subprocess.STDOUT, shell=False, **launch, **kwargs)
            try:
                while proc.poll() is None:
                    # Let FUSION finish this command before acknowledging a pause.
                    self.check_cancelled()
                    if time.monotonic()-last_report>=10:
                        self.progress(self._last_progress,Path(args[0]).name+' sigue ejecutándose ('+str(int(time.monotonic()-started))+' s)')
                        last_report=time.monotonic()
                    time.sleep(.15)
            except BaseException:
                if os.name == 'nt':
                    subprocess.run(['taskkill','/PID',str(proc.pid),'/T','/F'], capture_output=True, check=False)
                else:
                    proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
                raise
            if proc.returncode != 0:
                raise RuntimeError(failure_message(args[0],proc.returncode))
        self.log('COMPLETADO '+Path(args[0]).name+' en '+format(time.monotonic()-started,'.1f')+' s')
        self.check()

    def phase(self,name,plot=None):
        self.state['phase']=name
        self.state['active_plot']=plot
        self.state.pop('active_command',None)
        self.save_state()
        self.progress(self._last_progress,name+(' · parcela '+plot if plot is not None else ''))

    def download(self, tile, destination):
        self.check()
        if destination.exists():
            las_header(destination, True)
            if tile.sha256 and digest(destination).lower() != tile.sha256.lower():
                raise ValueError('SHA256 incorrecto: '+tile.name)
            self.log('REUTILIZADO original '+tile.name)
            return
        if not tile.url:
            raise AuthorizationRequired('Descargue '+tile.name+' en '+str(destination.parent)+' desde '+DETAIL+tile.sec)
        from urllib.request import build_opener
        opener = build_opener(OfficialRedirect())
        self.log('DESCARGA sec='+tile.sec+' '+tile.name)
        partial = destination.with_suffix(destination.suffix+'.part')
        # A fresh partial is used. No unsafe appending without ETag/Content-Range.
        try:
            with opener.open(Request(official_url(tile.url), headers={'User-Agent':'InventarioForestalLiDAR/0.1'}), timeout=30) as response:
                official_url(response.url)
                if response.status != 200:
                    raise AuthorizationRequired('La descarga requiere intervención oficial: '+DETAIL+tile.sec)
                expected = response.headers.get('Content-Length')
                received = 0
                with partial.open('wb') as f:
                    while True:
                        self.check()
                        block = response.read(1024*1024)
                        if not block:
                            break
                        f.write(block)
                        received += len(block)
                if expected and received != int(expected):
                    raise ValueError('Descarga incompleta: '+tile.name)
            try:
                las_header(partial, True)
            except ValueError as e:
                raise AuthorizationRequired('Respuesta sin nube LAS/LAZ; complete la descarga oficial: '+DETAIL+tile.sec) from e
            if tile.sha256 and digest(partial).lower() != tile.sha256.lower():
                raise ValueError('SHA256 incorrecto: '+tile.name)
            partial.replace(destination)
            self.log('DESCARGADO sec='+tile.sec+' bytes='+str(received))
        except HTTPError as e:
            if e.code in (401,403,429):
                raise AuthorizationRequired('Autorización o límite CNIG; abra '+DETAIL+tile.sec) from None
            raise RuntimeError('CNIG HTTP '+str(e.code)+' para sec='+tile.sec) from None

    def execute(self):
        validate(self.plots,self.c['radius'],self.c['output'])
        self.c['height_cutoff'] = validate_height_cutoff(self.c.get('height_cutoff'))
        root = Path(self.c['output'])
        root.mkdir(parents=True,exist_ok=True)
        self.run = root/'resultados'/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')+'_'+uuid.uuid4().hex[:8])
        self.run.mkdir(parents=True)
        self.logfile = self.run/'proceso.log'
        self.logfile.touch()
        self.state['config'] = {k:v for k,v in self.c.items() if k not in ('index','files')}
        self.state['started_utc'] = datetime.now(timezone.utc).isoformat()
        cutoff = self.c['height_cutoff']
        self.log('MÉTRICAS: '+('todos los retornos' if cutoff is None else 'altura normalizada > '+format(cutoff,'.12g')+' m; CloudMetrics /minht'))
        try:
            if 'input_centers' in self.c:
                atomic_json(self.run/'parcelas_entrada.json', self.c['input_centers'], check=self.check)
            self._execute(root)
            self.state['status'] = 'completed'
            self.progress(100,'Finalizado')
        except Cancelled as e:
            self.state.update(status='cancelled', error=str(e))
            self.log('CANCELADO '+str(e))
            raise
        except AuthorizationRequired as e:
            self.state.update(status='authorization_required', error=str(e))
            self.log('INTERVENCIÓN OFICIAL '+str(e))
            raise
        except Exception as e:
            # Avoid persisting signed download URLs embedded in network exceptions.
            message = str(e) if not ('https://' in str(e) and 'sec=' not in str(e)) else type(e).__name__+'; consulte conexión CNIG'
            if self.state.get('phase'):
                message='Fallo en '+self.state['phase']+(' · parcela '+self.state['active_plot'] if self.state.get('active_plot') is not None else '')+': '+message
            self.state.update(status='failed', error=message)
            self.log('ERROR '+message)
            if self.state.get('phase')=='Comprobación de cobertura':
                self.log('DETALLE DE COBERTURA\n'+traceback.format_exc())
            raise RuntimeError(message) from None
        finally:
            self.state['finished_utc'] = datetime.now(timezone.utc).isoformat()
            try:
                self.save_state(final=True)
            except StateStorageError as storage_error:
                if self.state['status'] in ('failed','cancelled','authorization_required'):
                    # Preserve the first processing/cancellation/authorization failure.
                    self.log('AVISO AL GUARDAR ESTADO FINAL '+str(storage_error))
                else:
                    self.state.update(status='storage_error',calculation_status='completed',error=str(storage_error))
                    try:self.backup_state()
                    except OSError:pass
                    raise RuntimeError('El cálculo terminó, pero no se pudo confirmar el estado final. '+str(storage_error)) from None
        return str(self.run)

    def _execute(self, root):
        from .qgis_io import verify_terrain, export_results
        epsg = self.c['epsg']
        if epsg not in (25828,25829,25830,25831,4083):
            raise ValueError('Use ETRS89 UTM 28–31 o REGCAN95 UTM 28 (EPSG:4083)')
        fusion = Path(self.c['fusion'])
        self.phase('Comprobación de FUSION')
        for name in PROGRAMS:
            selected=program(fusion,name)
            if not selected.is_file():raise ValueError('Falta '+str(selected))
            self.progress(0,'FUSION '+name+': '+str(selected))
        if os.name=='nt':
            # Catch the reported startup crash before downloads or expensive conversion.
            self.run_command([str(program(fusion,'ClipData')),'/version'])
        automatic_mode = not self.c.get('files') and not self.c.get('index')
        source_files = self.c.get('files',[])
        if automatic_mode:
            from .cnig import AutomaticSource
            self.state['input_mode'] = 'automatic_cnig'
            self.phase('Consulta y descarga CNIG')
            source = AutomaticSource(root,self.run,self.check,self.progress,self.retry_authorization,
                download_directory=self.c.get('download_directory'),batch_download=self.c.get('batch_download',False),
                batch_limit=self.c.get('batch_limit',20))
            source_files = source.acquire(self.plots,epsg,self.c['radius'],self.c['cell'],self.c.get('support_distance',5.))
            self.state['input_mode'] = 'automatic_cnig'
        local_mode = bool(source_files)
        if local_mode:
            from .local import discover, select_local
            self.phase('Metadatos de las teselas')
            candidates, inventory = discover(source_files,epsg,self.c.get('assume_missing_crs',False),self.check,self.progress)
            atomic_json(self.run/'archivos_locales.json',inventory)
            tiles, mapping = select_local(self.plots,self.c['radius']+2*self.c['cell']+self.c.get('support_distance',5.),candidates)
            self.log('ARCHIVOS LOCALES: metadatos automáticos; procedencia LIDA3 y huellas oficiales no verificadas por cabecera')
            if not automatic_mode:
                self.state['input_mode'] = 'local_files'
        elif self.c.get('index'):
            tiles, mapping = select_tiles(self.plots,self.c['radius']+2*self.c['cell'],read_index(self.c['index'],epsg))
            self.state['input_mode'] = 'legacy_index'
        else:
            raise ValueError('CNIG no proporcionó archivos descargables para las parcelas')
        # Snapshot deliberately excludes temporary or signed download URLs.
        atomic_json(self.run/'teselas.json',[{'key':t.sec,'name':t.name,'bbox':t.bbox,'epsg':t.epsg,'bounds_kind':'point_envelope' if local_mode else 'declared_official_footprint'} for t in tiles])
        laz, las = root/'originales', root/'LAS'
        if not local_mode:
            laz.mkdir(exist_ok=True)
        las.mkdir(exist_ok=True)
        self.phase('Conversión LAZ a LAS')
        paths = {}
        pending = []
        for i,t in enumerate(tiles):
            self.check()
            self.progress(5+30*i/max(1,len(tiles)), 'Descarga/conversión '+t.name)
            if local_mode:
                src = Path(t.source)
                las_header(src,True)
                self.log('ORIGINAL LOCAL (sólo lectura) '+str(src))
            else:
                srcdir = laz/t.sec
                srcdir.mkdir(exist_ok=True)
                src = srcdir/t.name
                flat = laz/t.name
                if not src.exists() and flat.exists():
                    src = flat
                try:
                    self.download(t,src)
                except AuthorizationRequired:
                    pending.append({'sec':t.sec,'name':t.name,'official_page':DETAIL+t.sec,'destination':str(src)})
                    continue
            source_count = las_header(src, True)
            fingerprint = digest(src,self.check)
            if local_mode and fingerprint != t.sha256:
                raise ValueError('El original cambió durante la ejecución: '+t.name)
            out = las/(t.sec+'.las') if local_mode else las/(t.sec+'_'+Path(t.name).stem+'.las')
            receipt = out.with_suffix('.json')
            reusable = False
            if out.exists() and receipt.exists():
                previous = json.loads(receipt.read_text(encoding='utf-8'))
                reusable = previous.get('source_sha256') == fingerprint and previous.get('las_sha256') == digest(out,self.check)
                if reusable:
                    if las_header(out) != source_count:
                        reusable = False
            if not reusable:
                # Work in this run, then atomically replace our derived cache.
                temporary = self.run/(t.sec+'_conversion.las')
                self.run_command([str(program(fusion,'LDA2LAS')),str(src),str(temporary)])
                if las_header(temporary) != source_count:
                    raise ValueError('La conversión perdió puntos: '+t.name)
                temporary.replace(out)
                atomic_json(receipt,{'source_sha256':fingerprint,'las_sha256':digest(out,self.check),'version':VERSION})
            self.progress(5+30*(i+1)/max(1,len(tiles)),
                          ('LAS reutilizado y verificado: ' if reusable else 'LAS convertido y verificado: ')+str(out)+' · '+str(source_count)+' puntos')
            paths[t.sec] = out
            self.state['tiles'].append({'sec':t.sec,'source':str(src),'name':t.name,'source_sha256':fingerprint,'las':str(out),'points':source_count,'status':'verified','reused':reusable})
            self.save_state()
        if pending:
            atomic_json(self.run/'descargas_pendientes.json',pending)
            raise AuthorizationRequired('Faltan '+str(len(pending))+' descargas oficiales. Consulte descargas_pendientes.json y reanude con Ejecutar.')
        if hasattr(self,'prepare_cells'):
            self.prepare_cells(paths,mapping)
        rows = []
        zone = 28 if epsg == 4083 else epsg-25800
        for i,p in enumerate(self.plots):
            self.check()
            self.progress(35+60*i/len(self.plots),'Parcela '+p.id)
            work = self.run/token(p.id)
            work.mkdir()
            if hasattr(self,'reuse_cell'):
                cached=self.reuse_cell(p,work)
                if cached is not None:
                    rows.append(cached)
                    self.state['plots'].append({'id':p.id,'directory':work.name,'points':int(cached['n_puntos']),'status':'completed','reused':True})
                    self.save_state()
                    continue
            self.phase('Comprobación de cobertura',p.id)
            if local_mode:
                from .local import verify_point_support
                report = verify_point_support([paths[t.sec] for t in mapping[p.id]],p,
                    self.c['radius']+2*self.c['cell'],self.c.get('support_distance',5.),self.check,
                    lambda text:self.progress(self._last_progress,text))
                atomic_json(work/'cobertura.json',report)
                self.log('COBERTURA MUESTREADA ID='+p.id+' muestras='+str(report['sample_count']))
            listing = work/'teselas.txt'
            listing.write_text('\n'.join(str(paths[t.sec]) for t in mapping[p.id])+'\n',encoding='utf-8')
            terrain, raw, normalized, metrics = [work/n for n in ('mdt.dtm','original.las','normalizada.las','cloudmetrics.csv')]
            # GridSurfaceCreate previously read complete neighboring tiles directly.
            # Feed one bounded LAS, retaining classes and original Z for the MDT.
            terrain_input = work/'entorno_mdt.las'
            self.phase('ClipData: entorno conjunto para MDT',p.id)
            self.run_command(terrain_clip_command(fusion,listing,terrain_input,p,self.c['radius'],self.c['cell'],self.c.get('support_distance',5.)))
            terrain_input_count = las_header(terrain_input)
            atomic_json(work/'entorno_mdt.json',{'source_tiles':[str(paths[t.sec]) for t in mapping[p.id]],
                'points':terrain_input_count,'margin_m':2*self.c['cell']+self.c.get('support_distance',5.),
                'original_elevations':True,'height_filter_applied':False})
            self.log('MDT ENTRADA ÚNICA ID='+p.id+' teselas='+str(len(mapping[p.id]))+' puntos='+str(terrain_input_count))
            cmd = commands(fusion,'','',terrain_input,terrain,raw,normalized,metrics,p,self.c['radius'],zone,self.c['cell'],self.c.get('height_cutoff'))
            self.phase('MDT clase 2',p.id)
            self.run_command(cmd['terrain'])
            if not terrain.is_file() or not terrain.stat().st_size:
                raise ValueError('FUSION no generó MDT')
            ascii_file = work/'mdt.asc'
            self.phase('Validación del MDT',p.id)
            self.run_command([str(program(fusion,'DTM2ASCII')),'/raster',str(terrain),str(ascii_file)])
            verify_terrain(ascii_file,p,self.c['radius'],self.check)
            self.phase('ClipData: recorte circular',p.id)
            self.run_command(cmd['raw'])
            raw_count = las_header(raw)
            self.phase('ClipData: normalización de alturas',p.id)
            self.run_command(cmd['normalize'])
            count = las_header(normalized)
            if count != raw_count:
                raise ValueError('La normalización perdió puntos para ID '+p.id)
            self.phase('Cobertura de primeros retornos',p.id)
            coverage = first_return_cover(normalized,
                2.,
                self.check, lambda text:self.progress(self._last_progress,text))
            atomic_json(work/'cobertura_retornos.json', coverage, check=self.check)
            if coverage['estado_cobertura'] != 'ok':
                self.progress(self._last_progress,'AVISO ID '+p.id+': sin primeros retornos; cobertura vacía, no cero')
            self.log('COBERTURA PRIMEROS RETORNOS ID='+p.id+' '+json.dumps(coverage,ensure_ascii=False))
            self.phase('CloudMetrics',p.id)
            self.run_command(cmd['metrics'])
            with metrics.open(encoding='utf-8-sig',newline='') as f:
                result = list(csv.DictReader(f))
            if len(result) != 1:
                raise ValueError('CloudMetrics debe producir exactamente una fila por parcela')
            row = metrics_row(p,self.c['radius'],count,result[0],self.c.get('height_cutoff'))
            row.update(coverage)
            self.log('RETORNOS MÉTRICAS ID='+p.id+' total='+str(count)+' usados='+str(row['n_puntos_metricas']))
            rows.append(row)
            with (work/'metricas.csv').open('w',encoding='utf-8-sig',newline='') as f:
                writer = csv.DictWriter(f,fieldnames=list(row))
                writer.writeheader()
                writer.writerow(row)
            if hasattr(self,'checkpoint_cell'):
                self.checkpoint_cell(p.id,work,row)
            self.state['plots'].append({'id':p.id,'directory':work.name,'points':count,'status':'completed'})
            self.save_state()
        self.check()
        self.phase('Exportación CSV y GeoPackage')
        export_results(self.run,rows,epsg,self.check)
        self.state['outputs']={'csv':str(self.run/'metricas.csv'),'gpkg':str(self.run/'metricas.gpkg')}
        self.progress(99,'Métricas exportadas: '+str(self.run/'metricas.gpkg'))
