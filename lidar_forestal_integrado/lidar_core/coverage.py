"""First-return cover from the full normalized parcel LAS, never from /minht output."""
import math
import struct
import time
from .core import validate_height_cutoff
from .local import metadata
from .storage import LASBlockReader


def first_return_cover(path, cutoff=2., check=lambda: None, progress=lambda text: None):
    """Read LAS point formats 0–10 without changing source bytes or classifications.

    Return order is independent of classification: ground (class 2) and every other
    class contribute to the denominator when return_number == 1. No class/flag
    filtering is applied. Heights must already be normalized to the parcel MDT.
    """
    cutoff = validate_height_cutoff(cutoff)
    if cutoff is None:
        raise ValueError('La cobertura requiere una altura de corte explícita')
    check()
    info = metadata(path, check, progress)
    if info.compressed:
        raise ValueError('La cobertura requiere el LAS normalizado sin comprimir')
    first = above = 0
    mask = 7 if info.point_format < 6 else 15
    zvalue = struct.Struct('<i').unpack_from
    cursor, remaining = info.offset, info.count
    last_report = time.monotonic()
    progress('Cobertura de primeros retornos: leyendo nube normalizada completa')
    with LASBlockReader(path, check, progress) as reader:
        while remaining:
            check()
            n = min(remaining, max(1, (1024*1024)//info.record_size))
            block = reader.read_exact(cursor, n*info.record_size)
            if len(block) != n*info.record_size:
                raise ValueError('LAS truncado durante el recuento de primeros retornos')
            for i, offset in enumerate(range(0, len(block), info.record_size)):
                if i % 4096 == 0:
                    check()
                if block[offset+14] & mask == 1:
                    first += 1
                    height = zvalue(block, offset+8)[0]*info.scales[2]+info.offsets[2]
                    if not math.isfinite(height):
                        raise ValueError('Altura no finita en la nube normalizada')
                    if height > cutoff:
                        above += 1
            cursor += len(block)
            remaining -= n
            if time.monotonic()-last_report >= 10:
                progress('Cobertura de primeros retornos: '+format(100*(info.count-remaining)/info.count,'.1f')+'% leído')
                last_report = time.monotonic()
    return {
        'n_primeros_retornos': first,
        'n_primeros_retornos_sobre_corte': above,
        'altura_cobertura_m': cutoff,
        'cobertura_primeros_retornos_pct': 100*above/first if first else '',
        'estado_cobertura': 'ok' if first else 'sin_primeros_retornos',
    }
