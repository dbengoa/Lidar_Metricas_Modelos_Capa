"""Normal Chrome, human official download, cancellable filesystem handoff.

No browser automation, private profile, cookie access or scripted portal clicks.
"""
from pathlib import Path
import os
import re
import shutil
import subprocess
import threading
import time
from .core import AuthorizationRequired, las_header
BASE='https://centrodedescargas.cnig.es/CentroDescargas/'


def default_download_directory():
    if os.name=='nt':
        # Windows known folder honors a relocated Downloads directory.
        import ctypes
        import uuid
        folder=(ctypes.c_ubyte*16).from_buffer_copy(uuid.UUID('374de290-123f-4565-9164-39c4925e467b').bytes_le)
        pointer=ctypes.c_wchar_p()
        try:
            if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(folder),0,None,ctypes.byref(pointer))==0:
                try:return Path(pointer.value)
                finally:ctypes.windll.ole32.CoTaskMemFree(pointer)
        except (OSError,AttributeError):pass
    return Path.home()/'Downloads'


def canonical_name(name):
    return re.sub(r' \(\d+\)(?=\.[^.]+$)','',name).replace('_','-').upper()


def chrome_candidates(windows=None,environ=None,which=None):
    windows=os.name=='nt' if windows is None else windows
    environ=os.environ if environ is None else environ
    which=shutil.which if which is None else which
    candidates=[]
    if windows:
        for name in ('PROGRAMFILES','PROGRAMFILES(X86)','LOCALAPPDATA'):
            root=environ.get(name)
            if root:candidates.append(Path(root)/'Google/Chrome/Application/chrome.exe')
    names=('chrome','google-chrome','google-chrome-stable')
    if not windows:names+=('chromium','chromium-browser')
    for name in names:
        found=which(name)
        if found:candidates.append(Path(found))
    return list(dict.fromkeys(candidates))


def executable():
    for path in chrome_candidates():
        if path.is_file():return str(path)
    raise RuntimeError('No se encontró Google Chrome. Instale Chrome y vuelva a ejecutar; esta versión no cambia automáticamente a Microsoft Edge.')


class OfficialBrowser:
    def __init__(self,work,check=lambda:None,progress=lambda s:None,retry=None,*,download_directory=None,
                 timeout=3600,poll=.5,stable_seconds=2):
        self.work=Path(work);self.check=check;self.progress=progress
        self.retry=retry or threading.Event()
        self.download_directory=Path(download_directory) if download_directory else default_download_directory()
        self.timeout=timeout;self.poll=poll;self.stable_seconds=stable_seconds

    def __enter__(self):return self

    def navigate(self,url):
        from urllib.parse import urlparse
        from urllib.request import url2pathname
        parsed = urlparse(url)
        local = False
        if parsed.scheme == 'file' and not parsed.query and not parsed.fragment:
            path = Path(url2pathname(('//'+parsed.netloc if parsed.netloc else '')+parsed.path)).resolve()
            local = path.parent == self.work.resolve() and re.fullmatch(r'lote_cnig_[1-9]\d*\.html',path.name) and path.is_file()
        if not local and not re.fullmatch(re.escape(BASE)+r'detalleArchivo\?sec=\d+',url):
            raise ValueError('La ficha debe ser oficial CNIG o una guía local de lote')
        # Use the user's ordinary Chrome session. Never own or close this process.
        subprocess.Popen([executable(),'--new-tab',url],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)

    def adopt(self,source,destination,expected,check=None):
        check = check or self.check
        las_header(source,True)
        if source.resolve()==destination.resolve():return destination
        staging=destination.with_suffix(destination.suffix+'.part')
        try:
            written=0
            with source.open('rb') as src,staging.open('wb') as dst:
                while True:
                    check();block=src.read(1024*1024)
                    if not block:break
                    dst.write(block);written+=len(block)
            stat=source.stat()
            if (stat.st_size,stat.st_mtime_ns)!=expected or written!=stat.st_size:
                raise OSError('La descarga cambió mientras se copiaba')
            las_header(staging,True)
            if destination.exists():raise ValueError('El original ya existe; no se sobrescribe')
            staging.replace(destination)
            return destination
        finally:
            if staging.exists():staging.unlink()

    def download(self,record,destination):
        sec=str(record['sec'])
        if not sec.isdigit():raise ValueError('Identificador CNIG inválido')
        destination=Path(destination);destination.parent.mkdir(parents=True,exist_ok=True)
        if destination.exists():las_header(destination,True);return destination
        directories=list(dict.fromkeys((self.download_directory,destination.parent,destination.parent.parent)))
        self.retry.clear();self.check()
        url=BASE+'detalleArchivo?sec='+sec
        self.navigate(url)
        self.progress('CNIG autorización: pulse «Descargar» en Chrome normal para '+record['name']+
                      '. Guarde en '+str(self.download_directory)+'. El plugin continuará automáticamente.')
        self.progress('CNIG vigilando: '+' | '.join(map(str,directories)))
        started=time.monotonic();last_report=started;seen={};reported=set()
        while time.monotonic()-started<self.timeout:
            before_check=time.monotonic()
            self.check()
            # A cooperative pause must not consume the download waiting limit.
            started+=time.monotonic()-before_check
            if self.retry.is_set():self.retry.clear();self.navigate(url)
            candidates=[]
            for directory in directories:
                try:candidates.extend(directory.iterdir())
                except FileNotFoundError:continue
            for candidate in sorted(set(candidates),key=str):
                if canonical_name(candidate.name)!=canonical_name(record['name']):continue
                if candidate.is_symlink() or not candidate.is_file():continue
                if any(candidate.with_name(candidate.name+suffix).exists() for suffix in ('.crdownload','.part','.tmp')):
                    seen.pop(candidate,None);continue
                try:
                    stat=candidate.stat();signature=(stat.st_size,stat.st_mtime_ns)
                    previous=seen.get(candidate)
                    if previous is None or previous[0]!=signature:
                        seen[candidate]=(signature,time.monotonic());continue
                    if time.monotonic()-previous[1]<self.stable_seconds:continue
                    result=self.adopt(candidate,destination,signature)
                except (OSError,ValueError) as error:
                    if candidate not in reported:
                        self.progress('CNIG esperando archivo completo '+candidate.name+': '+str(error));reported.add(candidate)
                    continue
                self.progress('CNIG archivo completo incorporado; original conservado: '+str(candidate))
                return result
            if time.monotonic()-last_report>=10:
                partial_bytes=0
                for candidate in candidates:
                    if candidate.name.lower().endswith('.crdownload') and canonical_name(candidate.name[:-11])==canonical_name(record['name']):
                        try:partial_bytes+=candidate.stat().st_size
                        except OSError:pass
                self.progress('CNIG vigilando: '+record['name']+'; '+
                              (format(partial_bytes/1048576,'.1f')+' MiB parciales' if partial_bytes else 'esperando el archivo completo en '+str(self.download_directory)))
                last_report=time.monotonic()
            time.sleep(self.poll)
        raise AuthorizationRequired('No apareció la descarga completa en una hora. Compruebe la carpeta de descargas de Chrome y reanude; se conservan los originales.')

    def download_batch(self, items, number=1, received=lambda record, path: None):
        from .batches import receive
        return receive(self, items, number, received)

    def __exit__(self,*args):
        # Cancellation stops only the watcher. Chrome and its downloads stay open.
        return False
