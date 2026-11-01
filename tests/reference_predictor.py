"""Reference from dbengoa/modelizacion-qgis, GPL-3.0.
engine.py predict_model at 09263b4a711fa0b724ee1cd16a622dc496871118.
Kept for numerical parity testing, not used by the plugin at runtime.
"""
import numpy as np
CHECK_CANCEL=lambda:None

def predict_model(model, X):
    CHECK_CANCEL()
    columns = model['predictores']
    if not columns:
        return np.full(len(X), model['intercepto'])
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
    return pred
