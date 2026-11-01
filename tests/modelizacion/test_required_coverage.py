import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import json
import tempfile
import unittest
from pathlib import Path
import numpy as np
import pandas as pd
from lidar_forestal_integrado.modelizacion.plugin import Dialog, SKIP_TARGET, ModelTask

from qgis.core import QgsApplication
app = QgsApplication.instance() or QgsApplication([], False)

class CoverageDialog(unittest.TestCase):
    def test_automatic_coverage_and_validation_summary(self):
        from lidar_forestal_integrado.modelizacion import engine
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            x=np.arange(40)+1
            pd.DataFrame({'parcela_id':range(40),'cm_Return 1 count above 2.00':x,'cm_Return 1 count':[100]*40}).to_csv(root/'lidar.csv',index=False)
            pd.DataFrame({'parcela_id':range(40),'Hdom':2*x+3,'V_ha':range(40)}).to_csv(root/'field.csv',index=False)
            dialog=Dialog();self.addCleanup(dialog.close)
            self.assertFalse(hasattr(dialog,'fcc_above'))
            self.assertFalse(any(default=='FCC_pct' for _,default in dialog.targets))
            self.assertIn('SÍ',dialog.validation_status.text())
            dialog.lidar.setText(str(root/'lidar.csv'));dialog.load_columns('lidar')
            dialog.field.setText(str(root/'field.csv'));dialog.load_columns('field')
            dialog.output.setText(str(root/'out'));dialog.graphs.setChecked(False)
            with self.assertRaisesRegex(ValueError,'dos métricas'):dialog.arguments()
            for box,_ in dialog.targets[:3]:box.setCurrentText(SKIP_TARGET)
            dialog.max_predictors.setValue(1)
            task=ModelTask(dialog.arguments());self.assertTrue(task.run(),task.error)
            package=json.loads((root/'out/modelos.json').read_text())
            self.assertEqual(package['modelos']['Hdom']['predictores'],['FCC_lidar_primeros_gt2_pct'])
            self.assertTrue(np.allclose(pd.read_csv(root/'out/fcc_directa.csv').FCC_pct,x))
            summary=pd.read_csv(root/'out/resumen_validacion.csv')
            self.assertTrue(summary.validacion_realizada.all())
            self.assertFalse(summary.validacion_independiente.any())
            self.assertTrue(np.allclose(summary.rmse_pct,0,atol=1e-9))
            self.assertTrue(np.allclose(summary.sesgo_pct,0,atol=1e-9))
            self.assertIn('VALIDACIÓN INDEPENDIENTE: NO',(root/'out/validacion.txt').read_text())
            dialog.result_path=root/'out';dialog.done_task(True,'')
            self.assertIn('sesgo relativo',dialog.info.toPlainText())
            dialog.mode.setCurrentIndex(2)
            self.assertIn('NO',dialog.validation_status.text())
            dialog.models.setText(str(root/'out/modelos.json'));dialog.output.setText(str(root/'pred.csv'))
            task=ModelTask(dialog.arguments());self.assertTrue(task.run(),task.error)
            result=pd.read_csv(root/'pred.csv');self.assertTrue(np.allclose(result.Hdom,2*x+3))
            self.assertTrue(np.allclose(result.FCC_pct,x))

    def test_direct_fcc_no_field_or_model_and_missing_total(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            pd.DataFrame({'parcela_id':['001','002'], 'cm_Return 1 count above 2.00':[30,0], 'cm_Return 1 count':[120,50]}).to_csv(root/'lidar.csv',index=False)
            dialog=Dialog();self.addCleanup(dialog.close)
            dialog.mode.setCurrentIndex(3)
            dialog.lidar.setText(str(root/'lidar.csv'));dialog.load_columns('lidar')
            dialog.output.setText(str(root/'fcc.csv'))
            task=ModelTask(dialog.arguments());self.assertTrue(task.run(),task.error)
            result=pd.read_csv(root/'fcc.csv',dtype={'parcela_id':str})
            self.assertEqual(result.FCC_pct.tolist(),[25,0])
            self.assertEqual(result.parcela_id.tolist(),['001','002'])
            with self.assertRaisesRegex(ValueError,'total de primeros'):
                from lidar_forestal_integrado.modelizacion import engine
                engine.detect_coverage_counts(pd.DataFrame({'cm_Return 1 count above 2.00':[30], 'cm_Total all returns':[100]}))
