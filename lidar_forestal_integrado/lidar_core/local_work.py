"""Local processing, verified staging and separate, recoverable result delivery."""
from pathlib import Path
import ctypes
import hashlib
import json
import os
import uuid
import ntpath

from .core import Cancelled, digest, atomic_json


def windows_local_path(path,drive_type=None):
    """Reject UNC and mapped remote drives; factored for testing outside Windows."""
    text=str(path)
    drive=ntpath.splitdrive(text)[0]
    kind=drive_type or (lambda root:ctypes.windll.kernel32.GetDriveTypeW(ctypes.c_wchar_p(root)))
    if text.startswith(('\\\\','//')) or not drive or kind(drive+'\\') not in (2,3,6):
        raise ValueError('Seleccione un disco local para procesar, no Q: ni una unidad de red. La red sólo puede ser origen de importación o destino final')


def local_workspace(path):
    path=Path(path).expanduser()
    if not path.is_absolute():
        raise ValueError('La carpeta de procesamiento debe ser absoluta')
    resolved=path.resolve()
    if os.name=='nt':
        windows_local_path(resolved)
    return resolved


def verified_copy(source,destination,check=lambda:None):
    source,destination=Path(source),Path(destination)
    check()
    if source.is_symlink() or not source.is_file():
        raise ValueError('Se requiere un archivo regular: '+str(source))
    if destination.is_symlink():
        raise ValueError('No se escribe sobre enlaces: '+str(destination))
    if destination.exists():
        expected=digest(source,check)
        if digest(destination,check)!=expected:
            raise ValueError('El destino ya contiene un archivo diferente; se conserva: '+str(destination))
        return expected
    destination.parent.mkdir(parents=True,exist_ok=True)
    partial=destination.with_name(destination.name+'.part_'+uuid.uuid4().hex)
    before=source.stat()
    checksum=hashlib.sha256()
    try:
        with source.open('rb') as incoming,partial.open('xb') as outgoing:
            while True:
                check()
                block=incoming.read(1024*1024)
                if not block:
                    break
                checksum.update(block)
                outgoing.write(block)
            outgoing.flush()
            os.fsync(outgoing.fileno())
        after=source.stat()
        if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):
            raise ValueError('El origen cambió mientras se copiaba: '+str(source))
        expected=checksum.hexdigest()
        if digest(partial,check)!=expected or partial.stat().st_size!=before.st_size:
            raise ValueError('La copia no coincide con el origen: '+str(destination))
        check()
        if destination.exists():
            raise ValueError('El destino apareció durante la copia; se conserva: '+str(destination))
        partial.replace(destination)
        return expected
    finally:
        partial.unlink(missing_ok=True)


def import_workspace(source,destination,check=lambda:None,progress=lambda text:None):
    source,destination=Path(source),local_workspace(destination)
    if source.resolve()==destination:
        return
    # Never traverse symlinks/junctions or arbitrary project files.
    for name in ('originales','LAS'):
        start=source/name
        if not start.exists():
            continue
        if start.is_symlink():
            raise ValueError('No se importan directorios enlazados: '+str(start))
        for directory,subdirs,files in os.walk(start,followlinks=False):
            check()
            for subdir in subdirs:
                candidate=Path(directory)/subdir
                if candidate.is_symlink() or (hasattr(candidate,'is_junction') and candidate.is_junction()):
                    raise ValueError('No se importan directorios enlazados: '+str(candidate))
            for filename in files:
                path=Path(directory)/filename
                if path.suffix.lower() not in ('.laz','.las','.json'):
                    continue
                target=destination/name/path.relative_to(start)
                progress('Importando a disco local: '+str(path))
                verified_copy(path,target,check)


FINAL_FILES=('cartografia_20m.shp','cartografia_20m.shx','cartografia_20m.dbf',
             'cartografia_20m.prj','cartografia_20m.cpg','cartografia_20m.gpkg',
             'cartografia_20m.csv','protocolo_cartografia.json','cuadricula.json',
             'estado.json','metricas.csv','metricas_modelos.csv','proceso.log','fusion.log','area_trabajo.wkb')
REQUIRED_FINAL=('cartografia_20m.shp','cartografia_20m.shx','cartografia_20m.dbf',
                'cartografia_20m.prj','cartografia_20m.gpkg','cartografia_20m.csv',
                'protocolo_cartografia.json','estado.json')


def deliver_results(run,destination,check=lambda:None,progress=lambda n,text:None):
    run=local_workspace(run)
    state=json.loads((run/'estado.json').read_text(encoding='utf-8'))
    cartographic=bool(state.get('cartography_outputs'))
    if state.get('status')!='completed' or not (cartographic or state.get('outputs')):
        raise ValueError('Sólo se copian ejecuciones completadas')
    required=REQUIRED_FINAL if cartographic else ('metricas.csv','metricas.gpkg','estado.json','protocolo_inventario.json')
    final_files=FINAL_FILES if cartographic else (*required,'proceso.log','fusion.log')
    for name in required:
        if not (run/name).is_file():
            raise ValueError('Falta un componente de la cartografía final: '+name)
    destination=Path(destination).expanduser()
    if not destination.is_absolute():
        raise ValueError('El destino final debe ser absoluto')
    final=destination/run.name
    if final.resolve()==run.resolve():
        raise ValueError('El destino final no debe ser la propia ejecución local')
    check()
    if final.exists():
        # A repeated delivery must verify every current component, not just existence.
        manifest=json.loads((final/'entrega.json').read_text(encoding='utf-8'))
        expected={name:digest(run/name,check) for name in final_files if (run/name).is_file()}
        if manifest.get('files')!=expected or any(digest(final/name,check)!=value for name,value in expected.items()):
            raise ValueError('El destino final ya existe con contenido distinto; no se sobrescribe')
        return final
    destination.mkdir(parents=True,exist_ok=True)
    stage=destination/('.'+run.name+'.partial_'+uuid.uuid4().hex)
    stage.mkdir()
    files={}
    try:
        selected=[name for name in final_files if (run/name).is_file()]
        for i,name in enumerate(selected):
            check()
            progress(99,'Copiando resultado final '+str(i+1)+'/'+str(len(selected))+': '+name)
            files[name]=verified_copy(run/name,stage/name,check)
        atomic_json(stage/'entrega.json',{'schema':1,'local_run':str(run),'files':files})
        check()
        if final.exists():
            raise ValueError('El destino apareció durante la entrega; no se sobrescribe')
        stage.rename(final)
        # This receipt is local and is not part of the completed-run state.
        atomic_json(run/'entrega_final.json',{'destination':str(final),'files':files})
        return final
    except Exception:
        # Keep the local run intact. A partial delivery is explicitly not a final result.
        raise


def processing_root(path):
    root=local_workspace(path)
    for name in ('originales','LAS','resultados','celdas','recuperacion','entradas'):
        local_workspace(root/name)
    return str(root)


def local_arguments(args):
    for argument in args:
        text=str(argument)
        candidate=text.split(':',1)[1] if text.lower().startswith(('/dtm:','/log:')) else text
        if Path(candidate).is_absolute():local_workspace(candidate)
    return args
