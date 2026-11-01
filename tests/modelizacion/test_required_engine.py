import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
import numpy as np
import pandas as pd
from lidar_forestal_integrado.modelizacion import engine as m

class RequiredCoverage(unittest.TestCase):
    def test_coverage_denominator_and_bounds(self):
        frame=pd.DataFrame({'above':['0','30','100'],'total':['100','120','100']})
        result=m.coverage_features(frame,above='above',total='total')
        self.assertEqual(result.FCC_lidar_primeros_gt2_pct.astype(float).tolist(),[0,25,100])
        self.assertNotIn('FCC_lidar_primeros_gt2_pct',frame)
        for a,t in [('1','0'),('101','100'),('-1','100'),('0.5','100'),('','100')]:
            with self.subTest(a=a,t=t),self.assertRaises(ValueError):
                m.coverage_features(pd.DataFrame({'a':[a],'t':[t]}),above='a',total='t')

    def test_required_identity_survives_nested_selection(self):
        rng=np.random.default_rng(12)
        X=pd.DataFrame(rng.uniform(1,10,(40,4)),columns=['a','b','c','d'])
        y=10+3*X.a.to_numpy()+2*X.b.to_numpy()+rng.normal(0,.2,40)
        options=replace(m.Options(),required_predictors=('a','b'),min_predictors=2,pool=1)
        model,external,_,_=m.calibrate_target(X,y,np.arange(40),'N_ha',options)
        self.assertTrue({'a','b'}<=set(model['predictores']))
        self.assertTrue(all({'a','b'}<=set(p) for p in external.predictores))
        X['b']=X.a*2
        with self.assertRaises(ValueError):m.select_model(X,y,options)

    def test_missing_required_never_falls_back(self):
        X=pd.DataFrame({'a':range(20)})
        with self.assertRaises(ValueError):m.select_model(X,np.arange(20),replace(m.Options(),required_predictors=('absent',)))


    def test_relative_rmse_signed_bias_and_zero_mean(self):
        metrics=m.scores([10,20],[12,22])
        self.assertAlmostEqual(metrics['rmse_pct'],100*2/15)
        self.assertAlmostEqual(metrics['sesgo_pct'],100*2/15)
        self.assertLess(m.scores([10,20],[8,18])['sesgo_pct'],0)
        self.assertIsNone(m.scores([0,0],[1,1])['rmse_pct'])
        self.assertIsNone(m.scores([0,0],[1,1])['sesgo_pct'])
