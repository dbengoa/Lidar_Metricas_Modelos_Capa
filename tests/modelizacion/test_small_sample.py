import sys
import unittest
from pathlib import Path
from dataclasses import replace
from unittest.mock import patch
import numpy as np
import pandas as pd
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from lidar_forestal_integrado.modelizacion import engine as m

class SmallSampleTests(unittest.TestCase):
    def sample(self):
        x=np.arange(1,9,dtype=float)
        return pd.DataFrame({'cm_Elev P95':x,'cm_Elev stddev':np.array([3,2,5,7,1,4,6,8.])}), 7+3*x
    def test_eight_nested_predictions_and_linear_candidate(self):
        X,y=self.sample();options=replace(m.Options(),min_plots=8)
        seen=[];original=m.fit_model
        def capture(features,response,columns,family,opts):
            seen.append((len(response),len(columns),family))
            self.assertLessEqual(len(columns),1)
            if columns:self.assertGreaterEqual(len(response),6)
            return original(features,response,columns,family,opts)
        with patch.object(m,'fit_model',side_effect=capture):
            model,predictions,ranking,_=m.calibrate_target(X,y,np.array([str(i) for i in range(8)]),'V_ha',options)
        self.assertEqual(len(predictions),8)
        self.assertEqual(predictions.parcela_id.nunique(),8)
        self.assertEqual(predictions.particion.nunique(),8)
        self.assertEqual(model['modo'],'exploratorio_muestra_pequena')
        self.assertEqual(model['familia'],'lineal')
        self.assertLess(model['validacion_externa_procedimiento']['rmse'],1e-10)
        self.assertTrue(any(n==6 and p==1 for n,p,_ in seen))
        self.assertIn('EXPLORATORIO',model['advertencias'][0])
        self.assertTrue(any(row['familia']=='potencial' for row in ranking))
    def test_predict_accepts_previous_model_version(self):
        import tempfile,json
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            model=m.fit_model(pd.DataFrame({'cm_Elev P95':np.arange(1,21,dtype=float)}),np.arange(1,21,dtype=float),['cm_Elev P95'],'lineal',m.Options())
            m.write_json(root/'modelos.json',{'version':'0.1.0-experimental','modelos':{'V_ha':model}})
            (root/'lidar.csv').write_text('parcela_id,cm_Elev P95\n001,10\n')
            self.assertEqual(m.main(['predecir','--modelos',str(root/'modelos.json'),'--lidar',str(root/'lidar.csv'),'--salida',str(root/'pred.csv')]),0)
            self.assertAlmostEqual(float(m.read_table(root/'pred.csv').iloc[0].V_ha),10)

    def test_seven_plots_rejected(self):
        X,y=self.sample()
        with self.assertRaisesRegex(ValueError,'mínimo operativo configurado 8'):
            m.calibrate_target(X.iloc[:7],y[:7],np.arange(7),'V_ha',replace(m.Options(),min_plots=8))
    def test_twenty_preserves_standard_limits(self):
        o=m.Options();self.assertIs(m.effective_options(o,20),o)
        small=m.effective_options(o,8)
        self.assertEqual(small.max_predictors,1);self.assertEqual(small.pool,3)
        self.assertEqual(small.min_per_coefficient,3)
    def test_selection_training_does_not_include_held_out_parcel(self):
        X,y=self.sample();seen=[];real=m.select_model
        def capture(features,response,*args,**kwargs):
            seen.append(set(features.index));return real(features,response,*args,**kwargs)
        with patch.object(m,'select_model',side_effect=capture):
            m.calibrate_target(X,y,np.arange(8),'V_ha',replace(m.Options(),min_plots=8))
        self.assertEqual(len(seen),9)
        self.assertTrue(all(len(indices)==7 for indices in seen[:-1]))
        self.assertEqual(seen[-1],set(range(8)))
    def test_groups_remain_separate(self):
        X,y=self.sample();groups=np.array(['a','a','b','b','c','c','d','d'])
        model,frame,_,_=m.calibrate_target(X,y,np.arange(8),'V_ha',replace(m.Options(),min_plots=8),groups)
        self.assertEqual(len(frame),8)
        for _,rows in frame.groupby('particion'):
            self.assertEqual(len(set(groups[rows.parcela_id.astype(int)])),1)
    def test_insufficient_groups_do_not_fall_back_to_random_cv(self):
        X,y=self.sample()
        with self.assertRaisesRegex(ValueError,'grupos'):
            m.calibrate_target(X,y,np.arange(8),'V_ha',replace(m.Options(),min_plots=8),np.array(['a']*4+['b']*4))

if __name__=='__main__':unittest.main(verbosity=2)
