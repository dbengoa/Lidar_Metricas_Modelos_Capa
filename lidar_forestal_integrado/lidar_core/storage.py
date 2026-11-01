"""Bounded filesystem retries and private diagnostics; never recreate a lost share."""
from pathlib import Path
import errno
import json
import os
import tempfile
import time


class StateStorageError(RuntimeError):
    pass


def diagnostic_root():
    base=os.environ.get('LOCALAPPDATA') if os.name=='nt' else None
    return Path(base or tempfile.gettempdir())/'InventarioForestalLiDAR'/'diagnosticos'


def transient(error):
    codes={getattr(errno,name,None) for name in ('ENOENT','ESTALE','EIO','ETIMEDOUT','ENETDOWN',
        'ENETRESET','ENETUNREACH','ECONNRESET','ENOTCONN','EBUSY')}
    return error.errno in codes-{None} or getattr(error,'winerror',None) in (5,32,33,53,64,67,121)


def pause(seconds,check):
    while seconds>0:
        check();step=min(seconds,.1);time.sleep(step);seconds-=step


def atomic_json(path,data,check=lambda:None,*,retry_delays=(.2,.5,1.0)):
    """Unique temporary beside destination; retain old JSON until replace succeeds.

    Missing parents are NOT created: a disconnected share must not become an empty
    replacement directory. Retry only bounded transient I/O failures. Caller owns
    directory creation and any alternate diagnostic destination.
    """
    path=Path(path)
    payload=json.dumps(data,ensure_ascii=False,indent=2)
    for attempt in range(len(retry_delays)+1):
        check();temporary=None
        try:
            with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=str(path.parent),
                    prefix=path.name+'.',suffix='.tmp',delete=False) as handle:
                temporary=Path(handle.name);handle.write(payload)
            check()
            temporary.replace(path)
            return
        except OSError as error:
            if attempt==len(retry_delays) or not transient(error):raise
            pause(retry_delays[attempt],check)
        finally:
            if temporary is not None:
                try:temporary.unlink(missing_ok=True)
                except OSError:pass


class LASBlockReader:
    """Read-only, unbuffered LAS ranges; reopen and reread the same range on I/O errors.

    Only point reads treat EINVAL as retryable, not arbitrary JSON writes.
    This is a compatibility measure, not proof that a server or file is healthy.
    """
    def __init__(self,path,check=lambda:None,progress=lambda text:None,*,retry_delays=(.2,.5,1.0)):
        self.path=Path(path);self.check=check;self.progress=progress
        self.retry_delays=retry_delays;self.file=None

    def __enter__(self):return self

    def close(self):
        if self.file is not None:
            try:self.file.close()
            except OSError:pass
            self.file=None

    def __exit__(self,*args):self.close()

    def read_exact(self,offset,size):
        for attempt in range(len(self.retry_delays)+1):
            self.check()
            try:
                if self.file is None:self.file=open(self.path,'rb',buffering=0)
                self.file.seek(offset)
                remaining=size;blocks=[]
                while remaining:
                    self.check();block=self.file.read(min(remaining,1024*1024))
                    if not block:raise ValueError('LAS truncado: '+str(self.path)+'; byte '+str(offset+size-remaining))
                    blocks.append(block);remaining-=len(block)
                return b''.join(blocks)
            except OSError as error:
                self.close()
                detail='Lectura LAS '+str(self.path)+'; byte '+str(offset)+'; bytes solicitados '+str(size)
                if attempt<len(self.retry_delays) and (transient(error) or error.errno==errno.EINVAL):
                    self.progress(detail+'; reintento '+str(attempt+1)+' por '+str(error))
                    pause(self.retry_delays[attempt],self.check)
                    continue
                raise OSError(error.errno,detail+': '+str(error),str(self.path)) from error
