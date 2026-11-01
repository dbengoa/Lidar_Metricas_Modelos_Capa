"""Official FUSION executable selection and Windows failure diagnostics."""
from pathlib import Path
import os

PROGRAMS=('LDA2LAS','GridSurfaceCreate','ClipData','CloudMetrics','DTM2ASCII')


def installed(folder,name):
    folder=Path(folder)
    if not folder.is_dir():return None
    return next((path for path in folder.iterdir() if path.name.lower()==name.lower() and path.is_file()),None)


def program(folder,name):
    preferred=installed(folder,name+'64.exe')
    legacy=installed(folder,name+'.exe')
    # Conversion needs LASzip of matching architecture for the CNIG LAZ input.
    # Keep the working 32-bit converter if only its DLL is installed.
    if name=='LDA2LAS' and preferred and not installed(folder,'laszip64.dll') and legacy and installed(folder,'laszip.dll'):
        return legacy
    return preferred or legacy or Path(folder)/(name+'.exe')


def invocation(args,logfile):
    args=list(map(str,args));exe=Path(args[0])
    name=exe.stem.lower().removesuffix('64')
    if name not in tuple(p.lower() for p in PROGRAMS):return args,{}
    # Avoid the shared master log under C:\FUSION and relative DLL lookup from QGIS.
    args.insert(1,'/log:'+str(Path(logfile).parent/'fusion.log'))
    env=os.environ.copy()
    # Execute the selected binary directly; do not hand off via an inherited setting.
    env.pop('FUSION64',None)
    env.pop('NOLASZIPDLL',None)
    return args,{'cwd':str(exe.parent),'env':env}


def failure_message(executable,code):
    message=Path(executable).name+' devolvió '+str(code)
    status=code & 0xffffffff
    if status==0xc0000005:
        message+=' (0xC0000005: acceso no válido a memoria; fallo del ejecutable o de una DLL; no identifica por sí solo la causa)'
    elif status == 0xc0000409:
        message+=' (0xC0000409: terminación de seguridad/fail-fast del ejecutable; el código por sí solo no identifica la causa)'
    elif status in (0xc0000135,0xc000007b):
        message+=' ('+format(status,'#010x')+': dependencia DLL ausente o arquitectura incompatible)'
    return message
