#!/usr/bin/env python3
"""Ecuaciones forestales lineales/potenciales con selección y CV externa anidada.

Python >=3.10. Entradas CSV de campo y CloudMetrics; consulte README.md.
No ejecuta FUSION ni modifica los datos de entrada. Sin eval ni pickle.
"""
from __future__ import annotations
import argparse
import csv
import io
from dataclasses import dataclass, asdict, replace
from itertools import combinations
import json
import logging
import math
from pathlib import Path
import re
import sys
from datetime import datetime, timezone
import numpy as np
import pandas as pd

VERSION = '0.4.2-experimental'
LOGGER = logging.getLogger('lidar_forestal_integrado.modelizacion.engine')
LOGGER.setLevel(logging.INFO)
LOGGER.propagate = False
CHECK_CANCEL = lambda: None
TARGETS = ['V_ha', 'G_ha', 'N_ha', 'Hdom']
TEMPLATE_TARGETS = [*TARGETS, 'FCC_pct', 'D_medio_cm']
DEFAULT_PATTERN = r'^(cm_Elev |cm_Canopy relief ratio$|cm_Profile area$|FCC_lidar_primeros_gt2_pct$)'
MISSING = {'', 'nan', 'na', 'n/a', 'null', 'none', 'undefined'}


@dataclass(frozen=True)
class Options:
    outer: int = 5
    inner: int = 4
    repeats: int = 1
    pool: int = 10
    max_predictors: int = 3
    min_per_coefficient: int = 5
    min_plots: int = 20
    max_missing: float = 0.1
    max_vif: float = 10.0
    max_correlation: float = 0.98
    bias_weight: float = 0.5
    seed: int = 2026
    score_tolerance: float = 0.02
    min_predictors: int = 0
    required_predictors: tuple = ()

    def validate(self):
        if len(set(self.required_predictors)) != len(self.required_predictors) or len(self.required_predictors) > self.max_predictors:
            raise ValueError('Métricas obligatorias duplicadas o superiores al máximo')
        if not 2 <= self.outer <= 20 or not 2 <= self.inner <= 20:
            raise ValueError('Use entre 2 y 20 particiones internas/externas')
        if not 1 <= self.repeats <= 20 or not 1 <= self.pool <= 15:
            raise ValueError('Repeticiones: 1–20; preselección: 1–15')
        if not 1 <= self.max_predictors <= 4 or not 3 <= self.min_per_coefficient:
            raise ValueError('Predictores: 1–4; observaciones por coeficiente: al menos 3')
        if not 0 <= self.min_predictors <= self.max_predictors:
            raise ValueError('El mínimo de predictores debe estar entre 0 y el máximo')
        if self.min_plots < 8 or not 0 <= self.max_missing < 1:
            raise ValueError('Mínimo operativo: al menos 8 parcelas; faltantes: [0,1)')
        if not all(math.isfinite(v) for v in (self.max_missing,self.max_vif,self.max_correlation,self.bias_weight,self.score_tolerance)):
            raise ValueError('Las opciones numéricas deben ser finitas')
        if self.max_vif <= 1 or not 0 < self.max_correlation <= 1 or self.bias_weight < 0:
            raise ValueError('VIF >1, correlación (0,1], peso de sesgo >=0')
        if self.seed < 0:
            raise ValueError('La semilla debe ser no negativa')
        if not 0 <= self.score_tolerance <= .2:
            raise ValueError('Tolerancia del score: entre 0 y 0.2')


def read_table(path, separator=None):
    CHECK_CANCEL()
    if separator is not None and len(separator) != 1:
        raise ValueError('El separador CSV debe ser un solo carácter')
    with Path(path).open(encoding='utf-8-sig', newline='') as source:
        sample = source.read(65536)
    if separator is None:
        try:
            separator = csv.Sniffer().sniff(sample, delimiters=',;\t|').delimiter
        except csv.Error:
            separator = ','
    header = next(csv.reader(io.StringIO(sample), delimiter=separator), [])
    if len(set(name.strip() for name in header)) != len(header):
        raise ValueError(f'Columnas duplicadas en {path}')
    frame = pd.read_csv(path, sep=separator, engine='python', dtype=str,
                        encoding='utf-8-sig', keep_default_na=False)
    frame.columns = frame.columns.str.strip()
    if frame.columns.duplicated().any():
        raise ValueError(f'Columnas duplicadas en {path}')
    return frame


def ids(frame, column, normalize=False):
    CHECK_CANCEL()
    if column not in frame:
        raise ValueError(f'Falta la columna ID {column}')
    values = frame[column].astype(str).str.strip()
    if normalize:
        # Retains leading zeros: "001.0" -> "001"; does not turn "001" into "1".
        values = values.str.replace(r'^([+-]?\d+)\.0+$', r'\1', regex=True)
    if (values == '').any() or values.duplicated().any():
        raise ValueError('IDs vacíos o duplicados (incluida la normalización opcional)')
    return values


def numeric(series, decimal='.'):
    CHECK_CANCEL()
    text = series.astype(str).str.strip()
    missing = text.str.lower().isin(MISSING)
    if decimal == ',':
        text = text.str.replace(',', '.', regex=False)
    result = pd.to_numeric(text.mask(missing), errors='coerce').astype(float)
    bad = (~missing & result.isna()) | np.isinf(result)
    if bad.any():
        raise ValueError(f'Valor no numérico/no finito en {series.name}; índices/ID: '+
                         ', '.join(str(i) for i in series.index[bad][:5]))
    return result


def detect_coverage_counts(frame):
    if {'n_primeros_retornos','n_primeros_retornos_sobre_corte','altura_cobertura_m'}.issubset(frame.columns):
        thresholds=numeric(frame['altura_cobertura_m'].astype(str).str.replace(',','.',regex=False))
        if thresholds.isna().any() or not thresholds.eq(2).all():
            raise ValueError('Los recuentos directos de FCC deben corresponder al umbral de 2 m')
        return 'n_primeros_retornos_sobre_corte','n_primeros_retornos'

    """Only unambiguous first-return counts with the explicit 2 m threshold."""
    def normalized(name):
        return re.sub(r'\s+', ' ', name.removeprefix('cm_').strip()).lower()
    above = [c for c in frame if re.fullmatch(r'return 1 count above 2(?:[.,]0+)?', normalized(c))]
    total = [c for c in frame if normalized(c) in ('return 1 count', 'total first returns', 'first return count')]
    if len(above) != 1 or len(total) != 1:
        raise ValueError('FCC: se necesita un recuento inequívoco de primeros retornos >2 m y otro del total de primeros retornos a todas las alturas. No use el numerador como total ni el total de todos los retornos.')
    return above[0], total[0]


def direct_coverage_command(args):
    frame = read_table(args.lidar, args.sep_lidar)
    identifiers = ids(frame, args.id_lidar, args.normalizar_id_decimal)
    above, total = detect_coverage_counts(frame)
    calculated = coverage_features(frame, args.decimal_lidar, above, total)
    result = pd.DataFrame({'parcela_id': identifiers.to_numpy(),
        'FCC_pct': calculated['FCC_lidar_primeros_gt2_pct'].to_numpy()})
    output = Path(args.salida)
    if output.exists():
        raise ValueError('La salida ya existe; no se sobrescribe')
    output.parent.mkdir(parents=True, exist_ok=True)
    write_csv(result, output)
    print('FCC directa (%): '+str(output.resolve()))


def coverage_features(frame, decimal='.', above=None, total=None):
    """Explicit counts: first returns strictly >2 m / ALL first returns."""
    if bool(above) != bool(total):
        raise ValueError('Seleccione ambos recuentos de primeros retornos para FCC')
    result = frame.copy()
    if not above and not total and 'FCC_lidar_primeros_gt2_pct' not in result:
        try:
            above, total = detect_coverage_counts(result)
        except ValueError:
            pass
    if above and total:
        if above == total or above not in frame or total not in frame:
            raise ValueError('Columnas de FCC ausentes o iguales')
        a, t = numeric(frame[above], decimal), numeric(frame[total], decimal)
        if a.isna().any() or t.isna().any() or ((a < 0) | (t <= 0) | (a > t) | (a % 1 != 0) | (t % 1 != 0)).any():
            raise ValueError('FCC requiere recuentos enteros: 0 <= primeros >2 m <= total, con total >0')
        result['FCC_lidar_primeros_gt2_pct'] = (100 * a / t).map(str)
    return result


def lidar_features(frame, decimal='.'):

    CHECK_CANCEL()
    numeric_columns = {}
    for name in frame:
        if name.startswith('cm_') and name not in ('cm_DataFile', 'cm_FileTitle'):
            numeric_columns[name] = numeric(frame[name], decimal)
    for name in ('n_puntos', 'radio_m', 'densidad_retornos_m2', 'FCC_lidar_primeros_gt2_pct'):
        if name in frame:
            numeric_columns[name] = numeric(frame[name], decimal)
    if 'densidad_retornos_m2' not in numeric_columns and all(n in numeric_columns for n in ('n_puntos', 'radio_m')):
        radius = numeric_columns['radio_m']
        if (radius.dropna() <= 0).any() or (numeric_columns['n_puntos'].dropna() < 0).any():
            raise ValueError('Radio debe ser positivo y n_puntos no negativo')
        numeric_columns['densidad_retornos_m2'] = numeric_columns['n_puntos']/(np.pi*radius**2)
    if 'FCC_lidar_primeros_gt2_pct' in numeric_columns:
        coverage = numeric_columns['FCC_lidar_primeros_gt2_pct']
        if coverage.isna().any() or ((coverage < 0) | (coverage > 100)).any():
            raise ValueError('FCC LiDAR debe estar entre 0 y 100 %')
    return numeric_columns


def scores(observed, predicted):
    CHECK_CANCEL()
    y = np.asarray(observed, float); pred = np.asarray(predicted, float)
    if y.shape != pred.shape or not len(y) or not np.isfinite(y).all() or not np.isfinite(pred).all():
        raise ValueError('Observados/predichos inválidos')
    error = pred-y  # Positive bias means overprediction.
    rmse = float(np.sqrt(np.mean(error**2))); bias = float(np.mean(error))
    mean = float(np.mean(y)); sst = float(np.sum((y-mean)**2))
    return {'n': len(y), 'rmse': rmse, 'sesgo': bias, 'mae': float(np.mean(np.abs(error))),
            'rmse_pct': 100*rmse/mean if mean else None,
            'sesgo_pct': 100*bias/mean if mean else None,
            'r2': 1-float(np.sum(error**2))/sst if sst else None,
            'predicciones_negativas': int(np.sum(pred < 0))}


def folds(n, k, seed, groups=None):
    CHECK_CANCEL()
    rng = np.random.default_rng(seed)
    if groups is None:
        k = min(k, n)
        batches = np.array_split(rng.permutation(n), k)
    else:
        groups = np.asarray(groups, str)
        names, counts = np.unique(groups, return_counts=True)
        k = min(k, len(names))
        if k < 2:
            raise ValueError('La validación agrupada necesita al menos dos grupos en cada entrenamiento')
        order = rng.permutation(len(names))
        order = order[np.argsort(-counts[order], kind='stable')]
        assigned = [[] for _ in range(k)]; sizes = np.zeros(k, int)
        for j in order:
            bucket = int(np.argmin(sizes)); assigned[bucket].append(names[j]); sizes[bucket] += counts[j]
        batches = [np.flatnonzero(np.isin(groups, names_)) for names_ in assigned]
    if k < 2:
        raise ValueError('No hay suficientes parcelas para validación')
    universe = np.arange(n)
    return [(np.setdiff1d(universe, test), np.asarray(test, int)) for test in batches]


def spearman(a, b):
    CHECK_CANCEL()
    aa = pd.Series(a).rank().to_numpy(); bb = pd.Series(b).rank().to_numpy()
    if np.std(aa) == 0 or np.std(bb) == 0:
        return 0.0
    return float(np.corrcoef(aa, bb)[0, 1])


def shortlist(X, y, options):
    CHECK_CANCEL()
    """Screen on the current outer training ONLY; never on external folds."""
    ranked = []
    for name in X:
        col = X[name].to_numpy(float)
        if np.isnan(col).mean() > options.max_missing or np.isnan(col).all():
            continue
        filled = np.where(np.isnan(col), np.nanmedian(col), col)
        if np.std(filled) <= 1e-12:
            continue
        ranked.append((abs(spearman(filled, y)), name, filled))
    ranked.sort(key=lambda row: (-row[0], row[1]))
    chosen = []
    for row in ranked:
        if all(abs(spearman(row[2], old[2])) < options.max_correlation for old in chosen):
            chosen.append(row)
        if len(chosen) >= options.pool:
            break
    return [row[1] for row in chosen]


def fit_model(X, y, columns, family, options):
    CHECK_CANCEL()
    y = np.asarray(y, float)
    if not columns:
        return {'familia': 'media', 'predictores': [], 'intercepto': float(np.mean(y)),
                'coeficientes': [], 'medianas': [], 'rangos': {}, 'factor_duan': 1.0}
    if len(y) < options.min_per_coefficient*(len(columns)+1):
        raise ValueError('Demasiados coeficientes para el entrenamiento disponible')
    raw = X.loc[:, list(columns)].to_numpy(float)
    if np.any(np.isnan(raw).mean(axis=0) > options.max_missing) or np.any(np.all(np.isnan(raw), axis=0)):
        raise ValueError('Demasiados valores ausentes en el entrenamiento')
    medians = np.nanmedian(raw, axis=0)
    raw = np.where(np.isnan(raw), medians, raw)
    ranges = {c: [float(np.min(raw[:, i])), float(np.max(raw[:, i]))] for i, c in enumerate(columns)}
    if family == 'potencial':
        if np.any(raw <= 0) or np.any(y <= 0):
            raise ValueError('La ecuación potencial exige respuesta y predictores estrictamente positivos')
        design = np.log(raw); target = np.log(y)
    else:
        design = raw; target = y
    centers = np.mean(design, axis=0); scales = np.std(design, axis=0)
    if np.any(scales <= 1e-12):
        raise ValueError('Predictor constante')
    standard = (design-centers)/scales
    if len(columns) > 1:
        corr = standard.T@standard/len(standard)
        if np.linalg.cond(corr) > 1e8 or np.max(np.diag(np.linalg.inv(corr))) > options.max_vif:
            raise ValueError('Colinealidad excesiva')
    full = np.column_stack([np.ones(len(y)), standard])
    coefficients, _, rank, _ = np.linalg.lstsq(full, target, rcond=None)
    if rank != full.shape[1]:
        raise ValueError('Matriz singular')
    slopes = coefficients[1:]/scales
    intercept = float(coefficients[0]-np.dot(slopes, centers))
    factor = 1.0
    with np.errstate(over='raise', invalid='raise'):
        if family == 'potencial':
            # Training residuals ONLY; correct log-to-original retransformation.
            factor = float(np.mean(np.exp(target-(intercept+design@slopes))))
            intercept = float(np.exp(intercept)*factor)
    if not np.isfinite(intercept) or not np.isfinite(slopes).all() or (family == 'potencial' and intercept <= 0):
        raise ValueError('Coeficientes no finitos')
    return {'familia': family, 'predictores': list(columns), 'intercepto': intercept,
            'coeficientes': slopes.tolist(), 'medianas': medians.tolist(), 'rangos': ranges,
            'factor_duan': factor}


def predict_model(model, X, *, raw_prediction=False):
    CHECK_CANCEL()
    columns = model['predictores']
    if not columns:
        return np.full(len(X), model['intercepto'] if raw_prediction else max(0.0, model['intercepto']))
    raw = X.loc[:, columns].to_numpy(float)
    raw = np.where(np.isnan(raw), np.asarray(model['medianas']), raw)
    with np.errstate(over='raise', invalid='raise', divide='raise'):
        if model['familia'] == 'potencial':
            if np.any(raw <= 0):
                raise ValueError('Predictor no positivo en la ecuación potencial')
            pred = model['intercepto']*np.exp(np.log(raw)@np.asarray(model['coeficientes']))
        else:
            pred = model['intercepto']+raw@np.asarray(model['coeficientes'])
    if not np.isfinite(pred).all():
        raise ValueError('Predicción no finita')
    return pred if raw_prediction else np.maximum(pred, 0.0)


def select_model(X, y, options, groups=None, seed=None):
    CHECK_CANCEL()
    seed = options.seed if seed is None else seed
    splits = folds(len(y), options.inner, seed, groups)
    # Candidate positions are fixed before seeing responses. Ranking, filtering,
    # medians and coefficients are refitted on EACH internal training split.
    # This evaluates a ranking/selection procedure; feature names may vary by fold.
    required = list(options.required_predictors)
    if any(c not in X for c in required):
        raise ValueError('Falta una métrica obligatoria')
    def pool_for(data, response):
        # Required identities never depend on ranking or held-out responses.
        optional = shortlist(data.drop(columns=required), response, options)
        return required + optional
    full_pool = pool_for(X, y)
    internal_pools = [pool_for(X.iloc[train], y[train]) for train, _ in splits]
    cap = min(options.max_predictors, min(len(train) for train, _ in splits)//options.min_per_coefficient-1)
    slots = min(len(required) + options.pool, len(X.columns))
    candidates = [('media', ())]
    for size in range(max(1, options.min_predictors, len(required)), max(0, cap)+1):
        candidates += [(family, tuple(range(len(required))) + subset) for subset in combinations(range(len(required), slots), size-len(required)) for family in ('lineal', 'potencial')]
    valid = []; invalid = []
    for family, positions in candidates:
        predicted = np.full(len(y), np.nan)
        try:
            if positions and max(positions) >= len(full_pool):
                raise ValueError('Posición no disponible en la preselección completa')
            full_subset = [full_pool[j] for j in positions]
            for (train, test), pool in zip(splits, internal_pools):
                if positions and max(positions) >= len(pool):
                    raise ValueError('Posición no disponible en un entrenamiento interno')
                columns = [pool[j] for j in positions]
                model = fit_model(X.iloc[train], y[train], columns, family, options)
                predicted[test] = predict_model(model, X.iloc[test])
            metrics = scores(y, predicted)
            model = fit_model(X, y, full_subset, family, options)
        except (ValueError, FloatingPointError, np.linalg.LinAlgError) as error:
            invalid.append({'familia': family, 'posiciones_ranking': [j+1 for j in positions], 'motivo': str(error)})
            continue
        row = {'familia': family, 'predictores': full_subset, 'posiciones_ranking': [j+1 for j in positions], **metrics,
               'score': metrics['rmse']+options.bias_weight*abs(metrics['sesgo']),
               'n_predictores': len(positions), 'elegible':len(positions)>=max(options.min_predictors, len(required)), 'particiones_internas': len(splits)}
        valid.append((row, model))
    if not valid:
        raise ValueError('No hay candidato válido, ni siquiera la media')
    valid.sort(key=lambda pair: (pair[0]['score'], pair[0]['n_predictores'], pair[0]['rmse']))
    eligible = [pair for pair in valid if pair[0]['elegible']]
    if not eligible:
        raise ValueError(f'No hay ecuación válida con al menos {options.min_predictors} predictores: revise tamaño de entrenamiento, métricas, colinealidad y grupos. La media sólo se conserva como referencia.')
    threshold = eligible[0][0]['score']*(1+options.score_tolerance)
    competitive = [pair for pair in eligible if pair[0]['score'] <= threshold]
    winner = min(competitive, key=lambda pair: (pair[0]['n_predictores'], pair[0]['score']))
    best = winner[1]
    for row, _ in valid:
        row['seleccionado'] = row is winner[0]
        row['pareto'] = not any(other['rmse'] <= row['rmse'] and abs(other['sesgo']) <= abs(row['sesgo']) and
                                (other['rmse'] < row['rmse'] or abs(other['sesgo']) < abs(row['sesgo']))
                                for other, _ in valid)
    best['cv_interna_seleccion'] = winner[0]
    return best, [row for row, _ in valid], invalid


def equation(target, model):
    CHECK_CANCEL()
    label = lambda name: '['+name+']'
    a = format(model['intercepto'], '.12g')
    if model['familia'] == 'potencial':
        terms = [a]+[f'{label(c)}^({b:.12g})' for c, b in zip(model['predictores'], model['coeficientes'])]
        return target+' = max(0, '+' * '.join(terms)+')'
    terms = [a]+[f'({b:.12g}) * {label(c)}' for c, b in zip(model['predictores'], model['coeficientes'])]
    return target+' = max(0, '+' + '.join(terms)+')'


def effective_options(options, n):
    """A small-sample procedure; retain fully nested selection and group splits."""
    if n < 20:
        # n=8: 7 outer training and 6 inner training; with TWO slopes and
        # intercept this leaves only 3 residual degrees of freedom internally.
        multi = options.min_predictors >= 2
        if options.min_predictors > 2:
            raise ValueError('Con 8–19 parcelas se permite como máximo 2 predictores')
        return replace(options, outer=20, inner=20, repeats=1,
                       pool=min(options.pool, 10 if multi else 3), max_predictors=2 if multi else 1,
                       min_per_coefficient=2 if multi else 3)
    if options.min_predictors >= 2 and n < 30:
        # Preserve five observations/coefficient while leaving enough training
        # plots for two predictors in the 20–29 range. Groups remain intact.
        return replace(options, outer=20, inner=20)
    return options


def calibrate_target(X, y, identifiers, target, options, groups=None):
    CHECK_CANCEL()
    if len(y) < options.min_plots:
        raise ValueError(f'{target}: sólo {len(y)} parcelas válidas; mínimo operativo configurado {options.min_plots}')
    options = effective_options(options, len(y))
    exploratory = len(y) < 20
    if exploratory:
        LOGGER.warning('%s: EXPLORATORIO con %d parcelas; CV anidada dejando una parcela/grupo fuera, predictores %d–%d, preselección <=%d, %d observaciones por coeficiente. Errores muy inciertos.', target, len(y), options.min_predictors, options.max_predictors, options.pool, options.min_per_coefficient)
    all_predictions = []
    for repetition in range(options.repeats):
        splits = folds(len(y), options.outer, options.seed+repetition, groups)
        for fold, (train, test) in enumerate(splits, 1):
            LOGGER.info('%s: repetición %d/%d, partición externa %d/%d', target, repetition+1, options.repeats, fold, len(splits))
            train_groups = groups[train] if groups is not None else None
            selected, _, _ = select_model(X.iloc[train], y[train], options, train_groups,
                                           options.seed+1000*(repetition+1)+fold)
            try:
                predicted = predict_model(selected, X.iloc[test])
            except (ValueError, FloatingPointError) as error:
                # Never discard an inconvenient held-out parcel or silently change model.
                raise ValueError(f'{target}: modelo seleccionado no aplicable en evaluación externa: {error}') from error
            baseline = float(np.mean(y[train]))
            for index, value in zip(test, predicted):
                all_predictions.append({'variable': target, 'parcela_id': str(identifiers[index]),
                                        'repeticion': repetition+1, 'particion': fold,
                                        'observado': float(y[index]), 'predicho': float(value),
                                        'error': float(value-y[index]), 'referencia_media': baseline,
                                        'familia': selected['familia'], 'predictores': selected['predictores']})
    frame = pd.DataFrame(all_predictions)
    outer_scores = scores(frame.observado, frame.predicho)
    outer_scores['n_parcelas'] = len(y); outer_scores['repeticiones'] = options.repeats
    outer_scores['referencia_rmse'] = scores(frame.observado, frame.referencia_media)['rmse']
    final, ranking, invalid = select_model(X, y, options, groups)
    final.update(variable=target, ecuacion=equation(target, final), n_calibracion=len(y),
                 validacion_externa_procedimiento=outer_scores)
    final['opciones_efectivas'] = asdict(options)
    final['validacion'] = {'realizada': True, 'metodo': 'validacion_cruzada_anidada',
        'independiente': False, 'agrupada': groups is not None,
        'particiones_externas_por_repeticion': [len(folds(len(y), options.outer, options.seed+r, groups)) for r in range(options.repeats)],
        'particiones_internas_solicitadas': options.inner,
        'repeticiones': options.repeats}
    final['modo'] = 'exploratorio_muestra_pequena' if exploratory else 'estandar'
    final['advertencias'] = ['Las predicciones negativas se convierten a cero en selección, validación y aplicación.']
    final['politica_prediccion'] = {'minimo': 0, 'aplicada_en_validacion': True}
    if exploratory:
        final['advertencias'].insert(0, 'EXPLORATORIO: menos de 20 parcelas; selección y errores de validación muy inestables. No es validación independiente ni garantía de aplicación a otras masas.')
    if options.min_predictors:
        final['advertencias'].append(f'Selección restringida a ecuaciones con al menos {options.min_predictors} métricas LiDAR. La media es sólo referencia; exigir predictores no garantiza mejorar su error.')
    if final['familia'] == 'media':
        final['advertencias'].append('La búsqueda no mejoró la media: no se ha seleccionado una relación LiDAR útil.')
    if outer_scores['rmse'] >= outer_scores['referencia_rmse']:
        final['advertencias'].append('La validación externa del procedimiento no mejora la media de entrenamiento.')
    if outer_scores['predicciones_negativas']:
        final['advertencias'].append('Se ha detectado una predicción negativa inesperada.')
    return final, frame, ranking, invalid


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def write_csv(frame, path):
    CHECK_CANCEL()
    copy = frame.copy()
    for col in copy:
        if any(isinstance(value, (list, dict)) for value in copy[col]):
            copy[col] = copy[col].map(lambda value: json.dumps(value, ensure_ascii=False))
    copy.to_csv(path, index=False, encoding='utf-8-sig', float_format='%.12g')


def diagnostics(frame, directory, target):
    CHECK_CANCEL()
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    fig = Figure(figsize=(10, 4))
    FigureCanvasAgg(fig)
    axes = fig.subplots(1, 2)
    axes[0].scatter(frame.observado, frame.predicho, alpha=.65, s=20)
    lower = float(min(frame.observado.min(), frame.predicho.min()))
    upper = float(max(frame.observado.max(), frame.predicho.max()))
    axes[0].plot([lower, upper], [lower, upper], 'k--', lw=1)
    axes[0].set(xlabel='Observado', ylabel='Predicho fuera de muestra', title=target)
    axes[1].scatter(frame.predicho, frame.error, alpha=.65, s=20)
    axes[1].axhline(0, color='black', linestyle='--', lw=1)
    axes[1].set(xlabel='Predicho fuera de muestra', ylabel='Predicho − observado')
    for ax in axes:
        ax.grid(alpha=.2)
    fig.tight_layout()
    fig.savefig(directory/('diagnostico_'+target+'.png'), dpi=160)


def fit_command(args):
    CHECK_CANCEL()
    options = Options(args.folds, args.inner_folds, args.repeticiones, args.preseleccion,
                      args.max_predictores, args.min_por_coeficiente, args.min_parcelas,
                      args.max_ausentes, args.max_vif, args.max_correlacion, args.peso_sesgo, args.semilla, args.tolerancia_score, args.min_predictores)
    options.validate()
    if len(set(args.objetivos)) != len(args.objetivos):
        raise ValueError('Respuestas duplicadas')
    destination = Path(args.salida)
    if destination.exists() and any(destination.iterdir()):
        raise ValueError('Use una carpeta de salida nueva o vacía; no se sobrescriben resultados')
    destination.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(destination/'ajuste.log', encoding='utf-8'); LOGGER.addHandler(handler)
    try:
        field = read_table(args.campo, args.sep_campo); lidar = read_table(args.lidar, args.sep_lidar)
        field_ids = ids(field, args.id_campo, args.normalizar_id_decimal)
        lidar_ids = ids(lidar, args.id_lidar, args.normalizar_id_decimal)
        field.index = field_ids; lidar.index = lidar_ids
        missing_lidar = field_ids[~field_ids.isin(lidar_ids)].tolist()
        missing_field = lidar_ids[~lidar_ids.isin(field_ids)].tolist()
        audit = {'campo_sin_lidar': missing_lidar, 'lidar_sin_campo': missing_field}
        write_json(destination/'auditoria_union.json', audit)
        if (missing_lidar or missing_field) and not args.permitir_no_coincidentes:
            raise ValueError('IDs no coincidentes; revise auditoria_union.json o autorice el cruce parcial con --permitir-no-coincidentes')
        common = field.index[field.index.isin(lidar.index)]
        if not len(common):
            raise ValueError('No hay IDs coincidentes')
        field = field.loc[common]; lidar = lidar.loc[common]
        lidar = coverage_features(lidar, args.decimal_lidar, args.fcc_superiores, args.fcc_total)
        parsed = lidar_features(lidar, args.decimal_lidar)
        if 'FCC_lidar_primeros_gt2_pct' in parsed:
            write_csv(pd.DataFrame({'parcela_id': common.to_numpy(), 'FCC_pct': parsed['FCC_lidar_primeros_gt2_pct'].to_numpy()}), destination/'fcc_directa.csv')
        required_by_target = json.loads(args.metricas_obligatorias)
        if not isinstance(required_by_target, dict) or any(k not in args.objetivos or not isinstance(v, list) or any(not isinstance(c, str) for c in v) for k,v in required_by_target.items()):
            raise ValueError('Configuración de métricas obligatorias inválida')
        columns = args.predictores or [c for c in parsed if re.search(args.regex, c)]
        columns = list(dict.fromkeys(columns + [c for v in required_by_target.values() for c in v]))
        if not columns or len(set(columns)) != len(columns):
            raise ValueError('No hay predictores candidatos o están duplicados')
        forbidden = set(args.objetivos+[args.id_lidar, args.id_campo, 'x', 'y', 'parcela_id'])
        if args.grupo:
            forbidden.add(args.grupo)
        if forbidden.intersection(columns):
            raise ValueError('ID, coordenadas, grupo y respuestas no pueden usarse como predictores')
        for c in columns:
            if c not in parsed:
                if c not in lidar:
                    raise ValueError('Falta la métrica '+c)
                parsed[c] = numeric(lidar[c], args.decimal_lidar)
        X = pd.DataFrame({c: parsed[c] for c in columns}, index=common)
        groups = None
        if args.grupo:
            if args.grupo not in field or field[args.grupo].str.strip().eq('').any():
                raise ValueError('Grupo ausente o vacío en el CSV de campo')
            groups = field[args.grupo].str.strip().to_numpy()
        models = {}; reports = []; predictions = []; exclusions = []
        for target in args.objetivos:
            if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*', target):
                raise ValueError('Use nombres de respuesta simples, sin espacios: '+target)
            if target not in field:
                raise ValueError('Falta la respuesta '+target)
            response = numeric(field[target], args.decimal_campo)
            if (response.dropna() < 0).any():
                raise ValueError('Respuesta forestal negativa: '+target)
            valid = response.notna().to_numpy()
            exclusions += [{'parcela_id': str(i), 'variable': target, 'motivo': 'respuesta ausente'} for i in common[~valid]]
            selected_groups = groups[valid] if groups is not None else None
            required = tuple(required_by_target.get(target, []))
            target_options = replace(options, required_predictors=required, min_predictors=max(options.min_predictors, len(required)))
            target_options.validate()
            model, external, ranking, invalid = calibrate_target(X.iloc[np.flatnonzero(valid)], response.to_numpy()[valid],
                    common.to_numpy()[valid], target, target_options, selected_groups)
            # Descriptive only: these full-sample correlations never select candidates.
            exploration = []
            for column in X:
                pair = pd.DataFrame({'x': X[column], 'y': response.to_numpy()}).dropna()
                exploration.append({'metrica': column, 'n': len(pair),
                    'pearson': pair.x.corr(pair.y) if len(pair)>2 else None,
                    'spearman': spearman(pair.x.to_numpy(), pair.y.to_numpy()) if len(pair)>2 else None})
            write_csv(pd.DataFrame(exploration), destination/('correlaciones_descriptivas_'+target+'.csv'))
            models[target] = model; predictions.append(external)
            reports.append({'variable': target, 'modo':model['modo'], 'min_predictores_exigidos':target_options.min_predictors, 'validacion_realizada': True, 'metodo_validacion': 'cruzada_anidada', 'validacion_independiente': False, 'particiones_externas': model['validacion']['particiones_externas_por_repeticion'][0], 'familia_final': model['familia'], 'ecuacion': model['ecuacion'],
                            **model['validacion_externa_procedimiento']})
            write_csv(pd.DataFrame(ranking), destination/('candidatos_'+target+'.csv'))
            write_json(destination/('descartados_'+target+'.json'), invalid)
            if not args.sin_graficos:
                diagnostics(external, destination, target)
            LOGGER.info('%s: %s', target, model['ecuacion'])
        write_csv(pd.DataFrame(reports), destination/'resumen_validacion.csv')
        lines = ['VALIDACIÓN REALIZADA: SÍ. Validación cruzada anidada.',
            'La selección de métricas, imputación y ajuste se repiten dentro de los entrenamientos.',
            'Las métricas proceden de predicciones de parcelas excluidas de cada entrenamiento externo.',
            'VALIDACIÓN INDEPENDIENTE: NO. El modelo final se reajusta con todas las parcelas.',
            'RMSE relativo (%) = 100 × sqrt(media((predicho-observado)^2)) / media(observado).',
            'Sesgo relativo (%) = 100 × media(predicho-observado) / media(observado).',
            'Media observada cero: porcentajes no definidos; no se sustituyen por cero.',
            'Sesgo positivo: sobreestimación. Sesgo negativo: subestimación.']
        for target, model in models.items():
            v = model['validacion']
            lines.append(f"{target}: {model['n_calibracion']} parcelas; particiones externas por repetición {v['particiones_externas_por_repeticion']}; internas solicitadas {v['particiones_internas_solicitadas']} (limitadas por parcelas/grupos disponibles); agrupada: {v['agrupada']}; repeticiones: {v['repeticiones']}.")
        (destination/'validacion.txt').write_text('\n'.join(lines)+'\n', encoding='utf-8')
        all_external = pd.concat(predictions, ignore_index=True)
        write_csv(all_external, destination/'predicciones_validacion.csv')
        stability = []
        for target in models:
            subset = all_external[all_external.variable == target].drop_duplicates(['repeticion','particion'])
            for name in columns:
                times = sum(name in names for names in subset.predictores)
                stability.append({'variable': target, 'metrica': name, 'veces_seleccionada': times,
                                  'ajustes_externos': len(subset), 'fraccion': times/len(subset)})
        write_csv(pd.DataFrame(stability), destination/'estabilidad_metricas.csv')
        write_csv(pd.DataFrame(exclusions, columns=['parcela_id', 'variable', 'motivo']), destination/'exclusiones.csv')
        package = {'version': VERSION, 'creado_utc': datetime.now(timezone.utc).isoformat(),
                   'opciones': asdict(options), 'candidatos_iniciales': columns, 'grupo': args.grupo,
                   'protocolo_fcc': {'superiores': args.fcc_superiores, 'total': args.fcc_total, 'umbral_m': 2, 'retornos': 'primeros', 'unidad': '%'},
                   'tipo_validacion': 'agrupada' if groups is not None else 'aleatoria',
                   'modelos': models, 'convencion_sesgo': 'predicho - observado',
                   'aviso': 'La CV externa evalúa el procedimiento de selección, no es una prueba independiente del modelo final reajustado.'}
        from ..contracts import metric_protocol
        package['protocolo_metricas']=metric_protocol(args.lidar,args.decimal_lidar)
        package['suite_version']='0.1.1'
        package['politica_prediccion']={'minimo': 0, 'aplicada_en_validacion': True}
        write_json(destination/'modelos.json', package)
        (destination/'ecuaciones.txt').write_text('\n\n'.join(m['ecuacion']+'\n'+'\n'.join(m['advertencias']) for m in models.values())+'\n', encoding='utf-8')
        write_json(destination/'estado.json', {'estado': 'completado', 'version': VERSION})
    except KeyboardInterrupt:
        write_json(destination/'estado.json', {'estado': 'cancelado'})
        raise
    except Exception as error:
        write_json(destination/'estado.json', {'estado': 'fallido', 'error': str(error)})
        raise
    finally:
        LOGGER.removeHandler(handler); handler.close()
    print('Resultados: '+str(destination.resolve()))


def predict_command(args):
    CHECK_CANCEL()
    package = json.loads(Path(args.modelos).read_text(encoding='utf-8'))
    if package.get('version') not in (VERSION, '0.4.1-experimental', '0.4.0-experimental', '0.1.0-experimental', '0.2.0-experimental', '0.3.1-experimental') or not isinstance(package.get('modelos'), dict):
        raise ValueError('Archivo de modelos incompatible')
    for target, model in package['modelos'].items():
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*', target) or model.get('familia') not in ('media', 'lineal', 'potencial'):
            raise ValueError('Variable o familia inválida en modelos.json')
        cols = model.get('predictores', [])
        if len(cols) != len(set(cols)) or len(cols) != len(model.get('coeficientes', [])) or len(cols) != len(model.get('medianas', [])):
            raise ValueError('Dimensiones inconsistentes en modelos.json')
        numbers = [model['intercepto'], *model['coeficientes'], *model['medianas']]
        if not all(isinstance(v, (int,float)) and math.isfinite(v) for v in numbers):
            raise ValueError('Modelo con números inválidos')
        if model['familia']=='potencial' and model['intercepto'] <= 0:
            raise ValueError('Coeficiente potencial no positivo')
        for c in cols:
            limits = model['rangos'].get(c, [])
            if len(limits) != 2 or not all(math.isfinite(v) for v in limits) or limits[0] > limits[1]:
                raise ValueError('Rangos inválidos en modelos.json')
    frame = read_table(args.lidar, args.sep_lidar)
    protocol = package.get('protocolo_fcc', {})
    frame = coverage_features(frame, args.decimal_lidar, protocol.get('superiores'), protocol.get('total'))
    identifiers = ids(frame, args.id_lidar, args.normalizar_id_decimal)
    parsed = lidar_features(frame, args.decimal_lidar)
    required = {c for m in package['modelos'].values() for c in m['predictores']}
    for c in required:
        if c not in parsed:
            if c not in frame:
                raise ValueError('Falta predictor requerido: '+c)
            parsed[c] = numeric(frame[c], args.decimal_lidar)
    X = pd.DataFrame({c: parsed[c] for c in required}, index=frame.index)
    output = pd.DataFrame({'parcela_id': identifiers.to_numpy()})
    if 'FCC_lidar_primeros_gt2_pct' in parsed and 'FCC_pct' not in package['modelos']:
        output['FCC_pct'] = parsed['FCC_lidar_primeros_gt2_pct'].to_numpy()
    for target, model in package['modelos'].items():
        cols = model['predictores']; values = []; flags = []
        for i in range(len(frame)):
            row = X.iloc[[i]]; alerts = []
            if cols and row.loc[:, cols].isna().any(axis=None):
                alerts.append('imputado_con_mediana_calibracion')
            for c in cols:
                value = row.iloc[0][c]; lower, upper = model['rangos'][c]
                if not pd.isna(value) and not lower <= value <= upper:
                    alerts.append('fuera_rango:'+c)
            try:
                value = float(predict_model(model, row, raw_prediction=True)[0])
                if value < 0:
                    alerts.append('prediccion_negativa_convertida_a_cero')
                    value = 0.0
                if target.startswith('FCC') and value > 100:
                    alerts.append('FCC_superior_100_pct')
            except (ValueError, FloatingPointError):
                value = np.nan; alerts.append('dominio_invalido_o_desbordamiento')
            values.append(value); flags.append('; '.join(alerts) or 'ok')
        output[target] = values; output[target+'_estado'] = flags
    path = Path(args.salida)
    if path.exists():
        raise ValueError('La salida ya existe; no se sobrescribe')
    path.parent.mkdir(parents=True, exist_ok=True); write_csv(output, path)
    print('Predicciones: '+str(path.resolve()))


def parser():
    CHECK_CANCEL()
    root = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    root.add_argument('--version', action='version', version=VERSION)
    commands = root.add_subparsers(dest='command', required=True)
    fit = commands.add_parser('ajustar', help='Calibrar y validar con dos CSV unidos por ID')
    fit.add_argument('--campo', required=True); fit.add_argument('--lidar', required=True)
    fit.add_argument('--salida', required=True); fit.add_argument('--id-campo', default='parcela_id')
    fit.add_argument('--id-lidar', default='parcela_id'); fit.add_argument('--objetivos', nargs='+', default=TARGETS)
    fit.add_argument('--metricas-obligatorias', default='{}', help='JSON respuesta: lista de métricas obligatorias')
    fit.add_argument('--fcc-superiores', help='Recuento de primeros retornos estrictamente >2 m')
    fit.add_argument('--fcc-total', help='Recuento total de primeros retornos, incluido <=2 m')
    fit.add_argument('--predictores', nargs='+'); fit.add_argument('--regex', default=DEFAULT_PATTERN)
    fit.add_argument('--grupo', help='Columna de monte/bloque en campo; no se mezcla entre folds')
    fit.add_argument('--normalizar-id-decimal', action='store_true')
    fit.add_argument('--permitir-no-coincidentes', action='store_true')
    fit.add_argument('--sep-campo'); fit.add_argument('--sep-lidar')
    fit.add_argument('--decimal-campo', choices=['.', ','], default='.')
    fit.add_argument('--decimal-lidar', choices=['.', ','], default='.')
    for name, default in [('folds', 5), ('inner-folds', 4), ('repeticiones', 1), ('preseleccion', 10),
                          ('max-predictores', 3), ('min-por-coeficiente', 5), ('min-parcelas', 20), ('semilla', 2026)]:
        fit.add_argument('--'+name, type=int, default=default)
    fit.add_argument('--min-predictores', type=int, default=0, help='0 permite la media; 2 exige dos métricas como mínimo')
    fit.add_argument('--max-ausentes', type=float, default=.1)
    fit.add_argument('--max-vif', type=float, default=10)
    fit.add_argument('--max-correlacion', type=float, default=.98)
    fit.add_argument('--peso-sesgo', type=float, default=.5)
    fit.add_argument('--tolerancia-score', type=float, default=.02)
    fit.add_argument('--sin-graficos', action='store_true')
    direct = commands.add_parser('fcc', help='FCC directa de primeros retornos, sin regresión ni datos de campo')
    direct.add_argument('--lidar', required=True); direct.add_argument('--salida', required=True)
    direct.add_argument('--id-lidar', default='parcela_id'); direct.add_argument('--sep-lidar')
    direct.add_argument('--decimal-lidar', choices=['.', ','], default='.')
    direct.add_argument('--normalizar-id-decimal', action='store_true')
    pred = commands.add_parser('predecir', help='Aplicar modelos.json a nuevas métricas sin reajustar')
    pred.add_argument('--modelos', required=True); pred.add_argument('--lidar', required=True)
    pred.add_argument('--salida', required=True); pred.add_argument('--id-lidar', default='parcela_id')
    pred.add_argument('--normalizar-id-decimal', action='store_true')
    pred.add_argument('--sep-lidar'); pred.add_argument('--decimal-lidar', choices=['.', ','], default='.')
    template = commands.add_parser('plantilla', help='Crear CSV de campo vacío con los IDs del CSV LiDAR')
    template.add_argument('--lidar', required=True); template.add_argument('--salida', required=True)
    template.add_argument('--id-lidar', default='parcela_id'); template.add_argument('--sep-lidar')
    return root


def main(argv=None):
    CHECK_CANCEL()
    args = parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    try:
        if args.command == 'ajustar':
            fit_command(args)
        elif args.command == 'fcc':
            direct_coverage_command(args)
        elif args.command == 'predecir':
            predict_command(args)
        else:
            frame = read_table(args.lidar, args.sep_lidar); identifiers = ids(frame, args.id_lidar)
            path = Path(args.salida)
            if path.exists():
                raise ValueError('La plantilla ya existe; no se sobrescribe')
            path.parent.mkdir(parents=True, exist_ok=True)
            result = pd.DataFrame({'parcela_id': identifiers})
            for target in TEMPLATE_TARGETS:
                result[target] = ''
            write_csv(result, path); print('Plantilla creada: '+str(path.resolve()))
    except (ValueError, OSError, KeyError, pd.errors.ParserError, ImportError) as error:
        LOGGER.error('%s', error); return 2
    except KeyboardInterrupt:
        LOGGER.error('Cancelado. No use una ejecución sin estado completado.'); return 130
    return 0


if __name__ == '__main__':
    sys.exit(main())
