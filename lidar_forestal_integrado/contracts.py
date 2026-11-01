"""Small, explicit contracts between module outputs. No model refitting."""
from pathlib import Path
import csv
import hashlib
import math


def metric_protocol(path,decimal='.'):
    path=Path(path)
    with path.open(encoding='utf-8-sig',newline='') as stream:
        sample=stream.read(65536);stream.seek(0)
        try: delimiter=csv.Sniffer().sniff(sample,delimiters=',;\t').delimiter
        except csv.Error: delimiter=','
        reader=csv.DictReader(stream,delimiter=delimiter)
        known={'altura_corte_m','filtro_altura'}.issubset(reader.fieldnames or [])
        values=set();radii=set();count=0
        for row in reader:
            count+=1
            if known:
                mode=row['filtro_altura'].strip()
                cutoff=row['altura_corte_m'].strip().replace(decimal,'.')
                if mode=='sin_filtro' and cutoff=='': value=None
                elif mode=='mayor_que':
                    value=float(cutoff)
                    if not math.isfinite(value) or value<0:raise ValueError('Corte no válido')
                else: raise ValueError('Filtro de altura incoherente')
                values.add(value)
            if row.get('radio_m'):
                radii.add(float(row['radio_m'].replace(decimal,'.')))
    if not count:raise ValueError('El CSV de métricas no contiene filas')
    if known and len(values)!=1:raise ValueError('El CSV mezcla cortes de altura distintos')
    return {'known':known,'cm_standard_height_filter_m':next(iter(values)) if known else None,
            'returns':'all' if known else None,'normalized':True if known else None,'radius_m':sorted(radii),
            'source_csv_sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
