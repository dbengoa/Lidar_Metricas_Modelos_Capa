import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from dataclasses import replace
import numpy as np
import pandas as pd
from lidar_forestal_integrado.modelizacion import engine as m
from generar_ejemplo import generate


class ModelsTests(unittest.TestCase):
    def test_linear_coefficients_and_predictions_original_units(self):
        X=pd.DataFrame({'altura':np.linspace(1,30,40),'cobertura':np.sin(np.arange(40))+.1})
        y=5+2*X.altura.to_numpy()+3*X.cobertura.to_numpy()
        model=m.fit_model(X,y,list(X),'lineal',m.Options())
        np.testing.assert_allclose(model['coeficientes'],[2,3],rtol=1e-12)
        np.testing.assert_allclose(m.predict_model(model,X),y,atol=1e-12)
    def test_power_equation_and_retransformation(self):
        X=pd.DataFrame({'altura':np.linspace(2,30,50)})
        y=2.5*X.altura.to_numpy()**1.4
        model=m.fit_model(X,y,list(X),'potencial',m.Options())
        self.assertAlmostEqual(model['intercepto'],2.5)
        self.assertAlmostEqual(model['coeficientes'][0],1.4)
        np.testing.assert_allclose(m.predict_model(model,X),y,rtol=1e-12)
        noisy=y*np.exp(np.random.default_rng(1).normal(0,.2,len(y)))
        model=m.fit_model(X,noisy,list(X),'potencial',m.Options())
        self.assertGreaterEqual(model['factor_duan'],1-1e-12)
    def test_power_does_not_silently_shift_zeros_or_negative_values(self):
        X=pd.DataFrame({'x':np.arange(1,41,dtype=float)});y=np.arange(1,41,dtype=float)
        for bad in (0,-1):
            copy=X.copy();copy.loc[0,'x']=bad
            with self.assertRaises(ValueError):m.fit_model(copy,y,['x'],'potencial',m.Options())
        y[0]=0
        with self.assertRaises(ValueError):m.fit_model(X,y,['x'],'potencial',m.Options())
    def test_imputation_uses_training_median_only(self):
        train=pd.DataFrame({'x':[1,2,3,np.nan,5,6,7,8,9,10,11,12,13,14,15]})
        y=1+2*train.x.fillna(train.x.median()).to_numpy()
        model=m.fit_model(train,y,['x'],'lineal',m.Options())
        test=pd.DataFrame({'x':[np.nan,1000000]})
        predicted=m.predict_model(model,test)
        self.assertAlmostEqual(predicted[0],1+2*train.x.median())
    def test_vif_rejects_collinear_covariates(self):
        X=pd.DataFrame({'a':np.arange(1,41),'b':2*np.arange(1,41)})
        with self.assertRaisesRegex(ValueError,'Colinealidad'):m.fit_model(X,np.arange(40),list(X),'lineal',m.Options())
    def test_bias_sign_and_rmse(self):
        stats=m.scores([1,2,3],[2,3,4])
        self.assertEqual(stats['sesgo'],1);self.assertEqual(stats['rmse'],1)
        self.assertEqual(stats['sesgo_pct'],50)
    def test_group_folds_do_not_mix_group_or_repeat_observations(self):
        groups=np.repeat(np.arange(10),4);seen=[]
        for train,test in m.folds(40,5,42,groups):
            self.assertFalse(set(groups[train]) & set(groups[test]));seen.extend(test)
        self.assertEqual(sorted(seen),list(range(40)))
    def test_ranking_is_refit_within_every_internal_training(self):
        rng=np.random.default_rng(19);X=pd.DataFrame(rng.uniform(1,10,(40,3)),columns=['a','b','c'])
        y=3+2*X.a.to_numpy()+rng.normal(0,.1,40);options=m.Options(pool=3,max_predictors=2)
        real=m.shortlist
        with patch.object(m,'shortlist',wraps=real) as rank:
            model,ranking,_=m.select_model(X,y,options)
        used=[set(call.args[0].index) for call in rank.call_args_list]
        expected=[set(X.iloc[train].index) for train,_ in m.folds(40,4,options.seed)]
        self.assertEqual(used[1:],expected)
        self.assertTrue(any(row['seleccionado'] for row in ranking))
        self.assertIn('a',model['predictores'])
    def test_nested_predictions_never_use_external_target(self):
        rng=np.random.default_rng(2);X=pd.DataFrame({'a':rng.uniform(1,10,40)})
        y=4+2*X.a.to_numpy();identifiers=np.array([str(i) for i in range(40)])
        options=m.Options(pool=1,max_predictors=1,outer=4,inner=3,repeats=2)
        original=m.select_model
        with patch.object(m,'select_model',wraps=original) as selector:
            model,external,_,_=m.calibrate_target(X,y,identifiers,'V_ha',options)
        for rep in (1,2):
            rows=external[external.repeticion==rep]
            self.assertEqual(len(rows),40);self.assertEqual(rows.parcela_id.nunique(),40)
        calls=selector.call_args_list
        expected=[set(X.iloc[train].index) for rep in range(2) for train,_ in m.folds(40,4,options.seed+rep)]
        self.assertEqual([set(call.args[0].index) for call in calls[:-1]],expected)
        self.assertEqual(set(calls[-1].args[0].index),set(X.index))
        self.assertLess(model['validacion_externa_procedimiento']['rmse'],1e-10)
    def test_ids_preserve_zeros_and_normalization_detects_collisions(self):
        frame=pd.DataFrame({'id':['001','1','226.0']})
        self.assertEqual(m.ids(frame,'id').tolist(),['001','1','226.0'])
        self.assertEqual(m.ids(frame,'id',True).tolist(),['001','1','226'])
        with self.assertRaises(ValueError):m.ids(pd.DataFrame({'id':['226','226.0']}),'id',True)
    def test_decimal_comma_and_duplicate_headers(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'a.csv';path.write_text('parcela_id;V_ha\n001;12,5\n002;13,1\n',encoding='utf-8')
            frame=m.read_table(path)
            self.assertEqual(frame.parcela_id.tolist(),['001','002'])
            np.testing.assert_allclose(m.numeric(frame.V_ha,','),[12.5,13.1])
            path.write_text('id,id\na,b\n',encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'duplicadas'):m.read_table(path)
    def test_constant_target_selects_baseline_and_no_two_plot_calibration(self):
        X=pd.DataFrame({'a':np.arange(30)})
        selected,_,_=m.select_model(X,np.ones(30),m.Options(pool=1))
        self.assertEqual(selected['familia'],'media')
        with self.assertRaisesRegex(ValueError,'sólo 2'):
            m.calibrate_target(X.iloc[:2],np.ones(2),np.array(['1','2']),'V_ha',m.Options())
    def test_full_csv_fit_predict_and_preserve_inputs(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);field,lidar=generate(40)
            for name,frame in [('campo',field),('lidar',lidar)]:frame.to_csv(root/(name+'.csv'),index=False)
            original=(root/'campo.csv').read_bytes();lidar_original=(root/'lidar.csv').read_bytes()
            result=m.main(['ajustar','--campo',str(root/'campo.csv'),'--lidar',str(root/'lidar.csv'),
                '--salida',str(root/'out'),'--objetivos','V_ha','Hdom','--preseleccion','3','--max-predictores','2','--sin-graficos'])
            self.assertEqual(result,0)
            models=json.loads((root/'out/modelos.json').read_text())
            self.assertEqual(set(models['modelos']),{'V_ha','Hdom'})
            self.assertEqual(json.loads((root/'out/estado.json').read_text())['estado'],'completado')
            result=m.main(['predecir','--modelos',str(root/'out/modelos.json'),'--lidar',str(root/'lidar.csv'),'--salida',str(root/'pred.csv')])
            self.assertEqual(result,0);pred=pd.read_csv(root/'pred.csv',dtype=str)
            self.assertEqual(len(pred),40);self.assertEqual(pred.parcela_id.iloc[0],'001')
            self.assertTrue(pred.V_ha_estado.eq('ok').all())
            self.assertEqual((root/'campo.csv').read_bytes(),original)
            self.assertEqual((root/'lidar.csv').read_bytes(),lidar_original)
            self.assertEqual(m.main(['ajustar','--campo',str(root/'campo.csv'),'--lidar',str(root/'lidar.csv'),'--salida',str(root/'out')]),2)
    def test_prediction_flags_nonpositive_extrapolation_imputation_and_negative(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);X=pd.DataFrame({'cm_Elev P95':np.arange(1,31,dtype=float)})
            power=m.fit_model(X,2*X.iloc[:,0].to_numpy()**1.3,list(X),'potencial',m.Options())
            linear=m.fit_model(X,X.iloc[:,0].to_numpy()-100,list(X),'lineal',m.Options())
            m.write_json(root/'models.json',{'version':m.VERSION,'modelos':{'V_ha':power,'G_ha':linear}})
            pd.DataFrame({'parcela_id':['a','b','c'],'cm_Elev P95':[-1,40,np.nan]}).to_csv(root/'new.csv',index=False)
            self.assertEqual(m.main(['predecir','--modelos',str(root/'models.json'),'--lidar',str(root/'new.csv'),'--salida',str(root/'pred.csv')]),0)
            result=pd.read_csv(root/'pred.csv')
            self.assertTrue(pd.isna(result.V_ha.iloc[0]))
            self.assertIn('dominio_invalido',result.V_ha_estado.iloc[0])
            self.assertIn('fuera_rango',result.V_ha_estado.iloc[1])
            self.assertIn('imputado',result.V_ha_estado.iloc[2])
            self.assertIn('prediccion_negativa',result.G_ha_estado.iloc[0])
            self.assertLess(result.G_ha.iloc[0],0)
    def test_invalid_numeric_data_and_options_fail(self):
        for text in ('infinito','inf','1,25'):
            with self.assertRaises(ValueError):m.numeric(pd.Series([text],name='V_ha'))
        for options in (m.Options(bias_weight=float('nan')),m.Options(seed=-1),m.Options(min_plots=2)):
            with self.assertRaises(ValueError):options.validate()
    def test_corrupt_models_are_not_silently_used(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            model={'familia':'potencial','intercepto':1,'predictores':['x'],'coeficientes':[], 'medianas':[1],'rangos':{'x':[1,2]}}
            m.write_json(root/'model.json',{'version':m.VERSION,'modelos':{'V_ha':model}})
            self.assertEqual(m.main(['predecir','--modelos',str(root/'model.json'),'--lidar','nonexistent.csv','--salida',str(root/'out.csv')]),2)
            self.assertFalse((root/'out.csv').exists())
    def test_unmatched_ids_fail_with_audit(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);field,lidar=generate(30);lidar=lidar.iloc[1:]
            field.to_csv(root/'field.csv',index=False);lidar.to_csv(root/'lidar.csv',index=False)
            code=m.main(['ajustar','--campo',str(root/'field.csv'),'--lidar',str(root/'lidar.csv'),'--salida',str(root/'out')])
            self.assertEqual(code,2)
            self.assertEqual(json.loads((root/'out/auditoria_union.json').read_text())['campo_sin_lidar'],['001'])
            self.assertEqual(json.loads((root/'out/estado.json').read_text())['estado'],'fallido')


if __name__=='__main__':unittest.main()
