"""Read modelos.json from modelizacion-qgis; no eval, pickle, refit or new user format.

Prediction matches modelizacion_forestal_lidar 0.4.2, engine.py predict_model,
commit 09263b4a711fa0b724ee1cd16a622dc496871118 (GPL-3.0).
"""
import json
import math
import hashlib
from pathlib import Path

PROTOCOL = {'cell_m':20,'fcc_threshold_m':2,'fcc_returns':'first','fcc_unit':'ratio',
            'hdom_percentile':95,'hdom_returns':'all','hdom_height_filter_m':None}
TARGETS = {'N_HA':'N_ha','VOL_HA':'V_ha','AB_HA':'G_ha'}
VERSIONS = {'0.4.2-experimental','0.4.1-experimental','0.4.0-experimental',
            '0.3.1-experimental','0.2.0-experimental','0.1.0-experimental'}
MISSING = {'','nan','na','n/a','null','none','undefined'}


def finite(value):
    if isinstance(value,bool):
        raise ValueError('Se esperaba un número, no un booleano')
    result=float(value)
    if not math.isfinite(result):
        raise ValueError('Número no finito')
    return result


def read_package(path):
    path=Path(path)
    if path.stat().st_size>4*1024*1024:
        raise ValueError('Archivo de modelos demasiado grande')
    package=json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(package,dict) or package.get('version') not in VERSIONS or not isinstance(package.get('modelos'),dict) or not package['modelos']:
        raise ValueError('Seleccione el modelos.json exportado por Modelización forestal LiDAR')
    if len(package['modelos'])>64:
        raise ValueError('Demasiados modelos')
    if not isinstance(package.get('protocolo_fcc',{}),dict):
        raise ValueError('Metadatos de FCC no válidos')
    for target,model in package['modelos'].items():
        if not target or not isinstance(model,dict) or model.get('familia') not in ('media','lineal','potencial'):
            raise ValueError('Variable o familia de modelo no válida')
        cols=model.get('predictores',[])
        if not isinstance(cols,list) or len(cols)>256 or any(not isinstance(c,str) or not c or len(c)>256 for c in cols) or len(set(cols))!=len(cols):
            raise ValueError('Predictores de modelo no válidos')
        for field in ('coeficientes','medianas'):
            if not isinstance(model.get(field),list) or len(model[field])!=len(cols):
                raise ValueError('Dimensiones inconsistentes en modelos.json')
        for value in [model.get('intercepto'),*model['coeficientes'],*model['medianas']]:
            finite(value)
        model['intercepto']=finite(model['intercepto'])
        model['coeficientes']=[finite(v) for v in model['coeficientes']]
        model['medianas']=[finite(v) for v in model['medianas']]
        if model['familia']=='potencial' and finite(model['intercepto'])<=0:
            raise ValueError('Coeficiente potencial no positivo')
        ranges=model.get('rangos')
        if not isinstance(ranges,dict):
            raise ValueError('Faltan rangos de calibración')
        for col in cols:
            limits=ranges.get(col)
            if not isinstance(limits,list) or len(limits)!=2 or finite(limits[0])>finite(limits[1]):
                raise ValueError('Rango de calibración inválido: '+col)
            ranges[col]=[finite(v) for v in limits]
    return package


def load_models(path=None,mapping=None,standard_cutoff='unspecified'):
    if not path:
        return {'package':{'modelos':{}},'mapping':{key:None for key in TARGETS},
                'standard_height_filter_m':None,'source':None}
    package=read_package(path)
    if mapping is None:
        mapping={output:target if target in package['modelos'] else None for output,target in TARGETS.items()}
    if set(mapping)!=set(TARGETS) or any(target is not None and target not in package['modelos'] for target in mapping.values()):
        raise ValueError('Asigne una respuesta del archivo a N/ha, volumen/ha y área basal/ha')
    selected=[target for target in mapping.values() if target is not None]
    if any(target in ('Hdom','FCC_pct','D_medio_cm') for target in selected):
        raise ValueError('No asigne modelos de altura, FCC o diámetro a N/ha, volumen o área basal')
    if len(selected)!=len(set(selected)):
        raise ValueError('No asigne la misma ecuación a dos variables dasométricas')
    saved=package.get('protocolo_metricas',{})
    if saved.get('known'):
        recorded=saved['cm_standard_height_filter_m']
        if standard_cutoff!='unspecified' and standard_cutoff!=recorded:
            raise ValueError('El corte elegido no coincide con el guardado en modelos.json')
        standard_cutoff=recorded
    required={col for target in selected for col in package['modelos'][target]['predictores']}
    if 'radio_m' in required:
        raise ValueError('El modelo utiliza radio_m de parcelas circulares. No puede trasladarse automáticamente a celdas cuadradas')
    standard=any(col.startswith('cm_') and not col.startswith('cm_gt2_') for col in required)
    if standard and standard_cutoff=='unspecified':
        raise ValueError('Indique si las métricas cm_ del ajuste se calcularon sin corte o sólo con alturas >2 m; modelos.json no guarda ese dato')
    if standard_cutoff!='unspecified' and standard_cutoff is not None and standard_cutoff!=2:
        raise ValueError('Protocolo de métricas estándar no compatible')
    return {'package':package,'mapping':dict(mapping),
            'standard_height_filter_m':None if standard_cutoff=='unspecified' else standard_cutoff,
            'source':str(Path(path).resolve()),'source_sha256':hashlib.sha256(Path(path).read_bytes()).hexdigest()}


def needs_gt2(data):
    selected=[name for name in data['mapping'].values() if name is not None]
    return any(col.startswith('cm_gt2_') or (data['standard_height_filter_m']==2 and col.startswith('cm_'))
               for target in selected for col in data['package']['modelos'][target]['predictores'])


def predictions(metrics,data):
    result,states={},{}
    for output,target in data['mapping'].items():
        result[output]=None
        if target is None:
            states[output]='SIN_MODELO'
            continue
        model=data['package']['modelos'][target]
        flags=[]
        values=[]
        for col,median in zip(model['predictores'],model['medianas']):
            if col not in metrics:
                raise ValueError('Falta predictor requerido por el modelo '+target+': '+col)
            raw=metrics[col]
            missing=raw is None or str(raw).strip().lower() in MISSING
            if missing:
                values.append(finite(median))
                flags.append('IMPUTADO')
            else:
                value=finite(raw)
                values.append(value)
                lower,upper=model['rangos'][col]
                if not lower<=value<=upper:
                    flags.append('FUERA_RANGO')
        try:
            intercept=finite(model['intercepto'])
            if not values:
                value=intercept
            elif model['familia']=='potencial':
                if any(v<=0 for v in values):
                    raise ValueError('Predictor no positivo')
                # Exported intercept ALREADY contains Duan correction.
                value=intercept*math.exp(sum(math.log(v)*b for v,b in zip(values,model['coeficientes'])))
            else:
                value=intercept+sum(v*b for v,b in zip(values,model['coeficientes']))
            value=finite(value)
            if value<0:
                flags.append('NEGATIVA')
            result[output]=value
        except (ValueError,ArithmeticError):
            flags.append('DOMINIO_INVALIDO')
        states[output]=';'.join(dict.fromkeys(flags)) or 'OK'
    return result,states
