"""Portable checks for new field responses, template and old CLI compatibility."""
import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from lidar_forestal_integrado.modelizacion import engine


class NewTargetsTests(unittest.TestCase):
    def test_template_has_six_targets_and_cli_fit_keeps_old_defaults(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);lidar=root/'lidar.csv';output=root/'template.csv'
            lidar.write_text('parcela_id,cm_Elev P95\n001,12\n002,14\n')
            self.assertEqual(engine.main(['plantilla','--lidar',str(lidar),'--salida',str(output)]),0)
            with output.open(encoding='utf-8-sig') as f:
                reader=csv.DictReader(f);rows=list(reader)
            self.assertEqual(reader.fieldnames,['parcela_id','V_ha','G_ha','N_ha','Hdom','FCC_pct','D_medio_cm'])
            self.assertEqual([r['parcela_id'] for r in rows],['001','002'])
            parsed=engine.parser().parse_args(['ajustar','--lidar',str(lidar),'--campo','campo.csv','--salida','out'])
            self.assertEqual(parsed.objetivos,['V_ha','G_ha','N_ha','Hdom'])

    def test_fcc_diameter_calibrate_save_and_predict(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);lidar=root/'lidar.csv';field=root/'campo.csv'
            z=[.5,2.2,1.1,3.4,.9,2.7,4.8,1.7]
            lidar.write_text('parcela_id,cm_Elev P95,cm_Elev stddev\n'+''.join(f'{i:03},{i+2},{v}\n' for i,v in enumerate(z)))
            field.write_text('parcela_id,FCC_pct,D_medio_cm\n'+''.join(f'{i:03},{15+2*(i+2)+.5*v},{8+.6*(i+2)+v}\n' for i,v in enumerate(z)))
            args=engine.parser().parse_args(['ajustar','--lidar',str(lidar),'--campo',str(field),'--salida',str(root/'out'),'--objetivos','FCC_pct','D_medio_cm','--min-parcelas','8','--min-predictores','2','--max-predictores','2','--sin-graficos'])
            engine.fit_command(args)
            package=json.loads((root/'out/modelos.json').read_text())
            self.assertEqual(set(package['modelos']),{'FCC_pct','D_medio_cm'})
            self.assertEqual(len(engine.read_table(root/'out/predicciones_validacion.csv')),16)
            pred=engine.parser().parse_args(['predecir','--lidar',str(lidar),'--modelos',str(root/'out/modelos.json'),'--salida',str(root/'pred.csv')])
            engine.predict_command(pred)
            out=engine.read_table(root/'pred.csv')
            self.assertTrue({'FCC_pct','D_medio_cm'}<=set(out.columns))
            self.assertEqual(out['parcela_id'].tolist(),[f'{i:03}' for i in range(8)])
