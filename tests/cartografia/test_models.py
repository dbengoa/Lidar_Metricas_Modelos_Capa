import json
import tempfile
import unittest
from pathlib import Path
from lidar_forestal_integrado.cartografia.models import load_models, predictions, read_package, needs_gt2
from lidar_forestal_integrado.cartografia.workflow import outputs, rectangular_command


def model(family='lineal',columns=None,intercept=2,coefficients=None):
    columns=['cm_Elev P95'] if columns is None else columns
    return {'familia':family,'predictores':columns,'intercepto':intercept,
            'coeficientes':[3]*len(columns) if coefficients is None else coefficients,
            'medianas':[5]*len(columns),'rangos':{c:[1,20] for c in columns},'factor_duan':1.5}


class ModelTests(unittest.TestCase):
    def data(self,value,cutoff=None):
        return {'package':{'modelos':{'N_ha':value}},
                'mapping':{'N_HA':'N_ha','VOL_HA':None,'AB_HA':None},
                'standard_height_filter_m':cutoff,'source':None}

    def test_fixed_fcc_and_p95_without_models(self):
        result=outputs({'n_primeros_retornos':'8','n_primeros_retornos_sobre_corte':'3',
                        'n_puntos':'20','cm_Elev P95':'18.2'},load_models())
        self.assertEqual(result['FCC'],3/8)
        self.assertEqual(result['HDOM_M'],18.2)
        self.assertIsNone(result['N_HA'])
        self.assertEqual(result['EST_N'],'SIN_MODELO')

    def test_zero_denominator_not_zero_cover(self):
        result=outputs({'n_primeros_retornos':0,'n_primeros_retornos_sobre_corte':0,
                        'n_puntos':5,'cm_Elev P95':3},load_models())
        self.assertIsNone(result['FCC'])
        self.assertEqual(result['EST_LIDAR'],'SIN_PRIMEROS')
        with self.assertRaises(ValueError):
            outputs({'n_primeros_retornos':1,'n_primeros_retornos_sobre_corte':2,
                     'n_puntos':5,'cm_Elev P95':3},load_models())

    def test_missing_p95_is_a_failure(self):
        with self.assertRaisesRegex(ValueError,'P95'):
            outputs({},load_models())

    def test_original_linear_mean_and_power_families(self):
        for value,expected in [(model(),32),(model('media',[],7,[]),7),
                               (model('potencial',intercept=2,coefficients=[2]),200)]:
            result,states=predictions({'cm_Elev P95':10},self.data(value))
            self.assertAlmostEqual(result['N_HA'],expected)
            self.assertEqual(states['N_HA'],'OK')
        self.assertNotEqual(result['N_HA'],300)  # Duan is already included in intercept.

    def test_imputation_extrapolation_negative_and_invalid_domain(self):
        result,states=predictions({'cm_Elev P95':''},self.data(model()))
        self.assertEqual(result['N_HA'],17)
        self.assertEqual(states['N_HA'],'IMPUTADO')
        result,states=predictions({'cm_Elev P95':30},self.data(model()))
        self.assertEqual(result['N_HA'],92)
        self.assertEqual(states['N_HA'],'FUERA_RANGO')
        result,states=predictions({'cm_Elev P95':2},self.data(model(intercept=-100)))
        self.assertEqual(result['N_HA'],0)
        self.assertIn('NEGATIVA',states['N_HA'])
        result,states=predictions({'cm_Elev P95':0},self.data(model('potencial')))
        self.assertIsNone(result['N_HA'])
        self.assertIn('DOMINIO_INVALIDO',states['N_HA'])
        with self.assertRaisesRegex(ValueError,'Falta predictor'):
            predictions({},self.data(model()))

    def test_original_json_and_explicit_metric_protocol(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'modelos.json'
            package={'version':'0.4.2-experimental','modelos':{'N_ha':model()}}
            path.write_text(json.dumps(package))
            with self.assertRaisesRegex(ValueError,'sin corte'):
                load_models(path)
            self.assertEqual(load_models(path,standard_cutoff=None)['mapping']['N_HA'],'N_ha')
            package['modelos']['N_ha']['coeficientes']=[]
            path.write_text(json.dumps(package))
            with self.assertRaisesRegex(ValueError,'Dimensiones'):
                read_package(path)

    def test_filtered_models_do_not_change_fcc_or_hdom(self):
        data=self.data(model(),cutoff=2)
        self.assertTrue(needs_gt2(data))
        result=outputs({'n_primeros_retornos':10,'n_primeros_retornos_sobre_corte':4,
                        'n_puntos':20,'cm_Elev P95':10,'cm_gt2_Elev P95':15},data)
        self.assertEqual(result['N_HA'],47)
        self.assertEqual(result['HDOM_M'],10)
        self.assertEqual(result['FCC'],.4)
        data=self.data(model(columns=['FCC_lidar_primeros_gt2_pct'],coefficients=[1],intercept=0))
        result=outputs({'n_primeros_retornos':10,'n_primeros_retornos_sobre_corte':4,
                        'n_puntos':20,'cm_Elev P95':10},data)
        self.assertEqual(result['N_HA'],40)

    def test_multiple_predictors_and_circle_radius_rejected(self):
        value=model(columns=['cm_Elev mean','cm_gt2_Elev P95'],intercept=4,coefficients=[2,3])
        result,states=predictions({'cm_Elev mean':5,'cm_gt2_Elev P95':10},self.data(value))
        self.assertEqual(result['N_HA'],44)
        self.assertEqual(states['N_HA'],'OK')
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'modelos.json'
            path.write_text(json.dumps({'version':'0.4.2-experimental','modelos':{'N_ha':model(columns=['radio_m'])}}))
            with self.assertRaisesRegex(ValueError,'circulares'):
                load_models(path,standard_cutoff=None)

    def test_equation_string_is_not_executed(self):
        value=model()
        value['ecuacion']='__import__("os").system("do not execute")'
        result,states=predictions({'cm_Elev P95':10},self.data(value))
        self.assertEqual(result['N_HA'],32)

    def test_matches_original_modelling_predictor(self):
        try:
            import numpy as np
            from reference_predictor import predict_model
        except ImportError:
            self.skipTest('NumPy para contraste con la función original')
        class Matrix:
            def __init__(self, values): self.values=values
            def to_numpy(self, kind): return np.array([self.values],dtype=kind)
        class Frame:
            def __init__(self, values): self.values=values; self.loc=self
            def __len__(self): return 1
            def __getitem__(self, key): return Matrix([self.values[c] for c in key[1]])
        for family in ('lineal','potencial','media'):
            value=model(family,columns=[] if family=='media' else ['cm_Elev P95'])
            for metric in (3.,10.,30.,float('nan')):
                expected=float(predict_model(value,Frame({'cm_Elev P95':metric}))[0])
                actual,_=predictions({'cm_Elev P95':metric},self.data(value))
                self.assertAlmostEqual(actual['N_HA'],expected,places=10)

    def test_square_clip_has_twenty_m_bounds_and_no_circle(self):
        result=rectangular_command(['ClipData.exe','/shape:1','input','output',0,0,28,28])
        self.assertIn('/shape:0',result)
        self.assertNotIn('/shape:1',result)
        bounds=list(map(float,result[-4:]))
        self.assertEqual(bounds[:2],[4,4])
        self.assertAlmostEqual(bounds[2],24)
        self.assertLess(bounds[2],24)
        self.assertAlmostEqual(bounds[2]-bounds[0],20)
        unchanged=['ClipData.exe','/shape:0','halo','output',1,2,30,40]
        self.assertEqual(rectangular_command(unchanged),unchanged)
