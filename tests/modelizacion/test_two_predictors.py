import sys,unittest
from pathlib import Path
from dataclasses import replace
from unittest.mock import patch
import numpy as np
import pandas as pd
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from lidar_forestal_integrado.modelizacion import engine as m

class TwoPredictorTests(unittest.TestCase):
    def sample(self):
        X=pd.DataFrame({'cm_Elev P95':np.arange(2,10,dtype=float),'cm_Elev stddev':[.5,2.2,1.1,3.4,.9,2.7,4.8,1.7]})
        return X, 5+3*X.iloc[:,0].to_numpy()+4*X.iloc[:,1].to_numpy()
    def test_eight_plots_two_predictors_in_all_outer_models(self):
        X,y=self.sample();o=replace(m.Options(),min_plots=8,min_predictors=2)
        fits=[];real=m.fit_model
        def fit(x,y,cols,family,options):
            fits.append((len(y),len(cols),family))
            return real(x,y,cols,family,options)
        with patch.object(m,'fit_model',side_effect=fit):
            model,frame,ranking,_=m.calibrate_target(X,y,np.arange(8),'V_ha',o)
        self.assertEqual(len(model['predictores']),2)
        self.assertEqual(model['familia'],'lineal')
        self.assertTrue(all(len(names)==2 for names in frame.predictores))
        self.assertEqual(len(frame),8);self.assertEqual(frame.particion.nunique(),8)
        self.assertLess(model['validacion_externa_procedimiento']['rmse'],1e-10)
        reference=next(row for row in ranking if row['familia']=='media')
        self.assertFalse(reference['elegible']);self.assertFalse(reference['seleccionado'])
        self.assertTrue(any(n==6 and k==2 for n,k,_ in fits))
        self.assertEqual(model['opciones_efectivas']['min_per_coefficient'],2)
    def test_no_silent_fallback_to_mean_or_single_variable(self):
        X,y=self.sample();X=X.iloc[:,:1]
        with self.assertRaisesRegex(ValueError,'al menos 2 predictores'):
            m.select_model(X,y,m.effective_options(replace(m.Options(),min_predictors=2),8))
    def test_collinear_pair_rejected(self):
        X,y=self.sample();X.iloc[:,1]=2*X.iloc[:,0]
        with self.assertRaisesRegex(ValueError,'al menos 2 predictores'):
            m.select_model(X,y,m.effective_options(replace(m.Options(),min_predictors=2),8))
    def test_inconsistent_min_and_max_rejected(self):
        with self.assertRaises(ValueError):replace(m.Options(),min_predictors=2,max_predictors=1).validate()
    def test_training_size_adjusted_with_twenty_plots(self):
        o=m.effective_options(replace(m.Options(),min_predictors=2),20)
        self.assertEqual(o.min_per_coefficient,5)
        outer=m.folds(20,o.outer,o.seed)
        self.assertGreaterEqual(min(len(inner_train) for tr,_ in outer for inner_train,_ in m.folds(len(tr),o.inner,o.seed)),15)
    def test_forcing_is_recorded_and_reference_comparison_preserved(self):
        X,y=self.sample()
        model,frame,_,_=m.calibrate_target(X,y,np.arange(8),'V_ha',replace(m.Options(),min_plots=8,min_predictors=2))
        self.assertTrue(any('Selección restringida' in text for text in model['advertencias']))
        self.assertIn('referencia_rmse',model['validacion_externa_procedimiento'])

if __name__=='__main__':unittest.main(verbosity=2)
