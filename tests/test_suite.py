import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from qgis.core import QgsApplication
from lidar_forestal_integrado.plugin import Dialog
from lidar_forestal_integrado.contracts import metric_protocol
from lidar_forestal_integrado.modelizacion import engine as m
from lidar_forestal_integrado.cartografia.models import load_models
from lidar_forestal_integrado.cartografia.workflow import outputs


class SuiteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QgsApplication.instance() or QgsApplication([],False)
        cls.app.initQgis()
    def dialog(self):
        class Iface:
            def mainWindow(self):return None
        dialog=Dialog(Iface())
        self.addCleanup(dialog.close)
        return dialog
    def test_three_modules_share_one_configuration(self):
        dialog=self.dialog()
        self.assertEqual(dialog.tabs.count(),3)
        dialog.work.setText('/tmp/suite_local')
        self.assertEqual(dialog.inventory.output.text(),'/tmp/suite_local')
        self.assertEqual(dialog.cartography.output.text(),'/tmp/suite_local')
        dialog.cartography.downloads.setText('/tmp/new_downloads')
        self.assertEqual(dialog.inventory.download_directory.text(),'/tmp/new_downloads')
        from lidar_forestal_integrado.inventario.engine import Engine as InventoryEngine
        from lidar_forestal_integrado.cartografia.workflow import GridEngine
        from lidar_forestal_integrado.lidar_core.engine import Engine as Shared
        self.assertTrue(issubclass(InventoryEngine,Shared))
        self.assertTrue(issubclass(GridEngine,Shared))
    def test_only_one_active_module_and_no_unexpected_close(self):
        dialog=self.dialog()
        class FakeJob:
            def __init__(self):self.cancelled=False
            def cancel(self):self.cancelled=True
        job=FakeJob();dialog.inventory.job=job
        dialog.refresh()
        try:
            self.assertFalse(dialog.cartography.start.isEnabled())
            self.assertFalse(dialog.model.start.isEnabled())
            with patch('lidar_forestal_integrado.plugin.QMessageBox.information'):
                self.assertFalse(dialog.can_start())
            dialog.cancel_all();self.assertTrue(job.cancelled)
        finally:
            dialog.inventory.job=None;dialog.refresh()
        self.assertTrue(dialog.cartography.start.isEnabled())
    def test_missing_model_dependencies_leave_other_modules_available(self):
        with patch('lidar_forestal_integrado.plugin.dependencies',return_value=['pandas ausente']):
            dialog=self.dialog()
            self.assertIsNone(dialog.model)
            self.assertEqual(dialog.tabs.count(),3)
            self.assertTrue(dialog.inventory.start.isEnabled())
            self.assertTrue(dialog.cartography.start.isEnabled())
    def test_new_inventory_counts_are_recognized_for_fcc(self):
        frame=m.pd.DataFrame({'n_primeros_retornos':['10','20'],
                              'n_primeros_retornos_sobre_corte':['4','15'],'altura_cobertura_m':['2','2.0']})
        above,total=m.detect_coverage_counts(frame)
        result=m.coverage_features(frame,'.',above,total)
        self.assertEqual(result['FCC_lidar_primeros_gt2_pct'].astype(float).tolist(),[40,75])
        frame.loc[0,'altura_cobertura_m']='3'
        with self.assertRaises(ValueError):m.detect_coverage_counts(frame)
    def test_mixed_metric_protocol_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'metricas.csv'
            path.write_text('parcela_id,altura_corte_m,filtro_altura\n1,2,mayor_que\n2,,sin_filtro\n')
            with self.assertRaisesRegex(ValueError,'mezcla'):metric_protocol(path)
    def test_inventory_fcc_stays_at_two_metres_with_another_metric_cut(self):
        import shutil,csv
        from fixtures import write_cloud
        from lidar_forestal_integrado.inventario.engine import Engine
        from lidar_forestal_integrado.lidar_core.engine import Engine as Shared
        from lidar_forestal_integrado.lidar_core.core import Plot
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'source.las'
            points=[(399960+x+.5,4599960+y+.5,z,c) for x in range(100) for y in range(100) for z,c in ((100,2),(110,5))]
            write_cloud(source,points)
            fusion=root/'fusion';fusion.mkdir()
            for name in ('LDA2LAS','ClipData','GridSurfaceCreate','DTM2ASCII','CloudMetrics'):(fusion/(name+'.exe')).touch()
            def command(args):
                name=Path(args[0]).stem
                if name=='LDA2LAS':shutil.copyfile(args[1],args[2])
                elif name=='ClipData':
                    normalized='/height' in args
                    write_cloud(args[-5],[(400000+i,4600000+i,z if normalized else z+100,c) for i,(z,c) in enumerate(((0,2),(2.5,5),(5,5)))])
                elif name=='GridSurfaceCreate':Path(args[2]).write_bytes(b'mocked DTM')
                elif name=='DTM2ASCII':Path(args[-1]).write_text('ncols 100\nnrows 100\nxllcorner 399950\nyllcorner 4599950\ncellsize 1\nNODATA_value -9999\n'+(' '.join(['100']*100)+'\n')*100)
                elif name=='CloudMetrics':Path(args[-1]).write_text('Total return count above 3.00,Elev minimum,Elev P95\n1,5,5\n')
            config={'output':str(root/'work'),'files':[str(source)],'fusion':str(fusion),'epsg':25830,
                    'cell':1,'support_distance':5,'radius':5,'height_cutoff':3}
            with patch.object(Shared,'run_command',side_effect=command):
                run=Path(Engine(config,[Plot('001',400000,4600000)]).execute())
            with (run/'metricas.csv').open(newline='',encoding='utf-8-sig') as stream:row=next(csv.DictReader(stream))
            self.assertEqual(float(row['altura_corte_m']),3)
            self.assertEqual(int(row['n_puntos_metricas']),1)
            self.assertEqual(float(row['altura_cobertura_m']),2)
            self.assertEqual(int(row['n_primeros_retornos']),3)
            self.assertEqual(int(row['n_primeros_retornos_sobre_corte']),2)
            self.assertAlmostEqual(float(row['cobertura_primeros_retornos_pct']),100*2/3)

    def test_metrics_to_fitted_models_to_cartography(self):
        dialog=self.dialog()
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);run=root/'inventario';run.mkdir()
            lidar=run/'metricas.csv';field=root/'campo.csv'
            lidar.write_text('parcela_id,altura_corte_m,filtro_altura,radio_m,cm_Elev mean,cm_Elev P95,n_primeros_retornos,n_primeros_retornos_sobre_corte,altura_cobertura_m\n'+
                ''.join(f'{i},2,mayor_que,15,{2+i/3},{30+(i*7)%9},100,50,2\n' for i in range(30)))
            field.write_text('parcela_id,N_ha\n'+''.join(f'{i},{12+3*(2+i/3)}\n' for i in range(30)))
            (run/'estado.json').write_text(json.dumps({'status':'completed'}))
            dialog.record_inventory(run);dialog.transfer_metrics()
            self.assertEqual(dialog.model.lidar.text(),str(lidar))
            self.assertEqual(dialog.tabs.currentIndex(),1)
            destination=root/'models'
            args=m.parser().parse_args(['ajustar','--campo',str(field),'--lidar',str(lidar),'--salida',str(destination),
                '--objetivos','N_ha','--folds','3','--inner-folds','2','--repeticiones','1','--preseleccion','2',
                '--max-predictores','1','--min-predictores','0'])
            m.fit_command(args)
            package=json.loads((destination/'modelos.json').read_text())
            self.assertEqual(package['protocolo_metricas']['cm_standard_height_filter_m'],2)
            self.assertTrue(package['protocolo_metricas']['known'])
            dialog.record_models(destination);dialog.transfer_models()
            self.assertEqual(dialog.tabs.currentIndex(),2)
            self.assertEqual(dialog.cartography.model_protocol.currentIndex(),2)
            self.assertEqual(dialog.cartography.model_targets['N_HA'].currentData(),'N_ha')
            model=load_models(destination/'modelos.json')
            result=outputs({'n_puntos':100,'n_primeros_retornos':80,'n_primeros_retornos_sobre_corte':40,
                'cm_Elev P95':35,'cm_Elev mean':2,'cm_gt2_Elev P95':45,'cm_gt2_Elev mean':10},model)
            self.assertEqual(result['HDOM_M'],35)
            self.assertEqual(result['FCC'],.5)
            self.assertAlmostEqual(result['N_HA'],42,places=6)
            with self.assertRaisesRegex(ValueError,'no coincide'):
                load_models(destination/'modelos.json',standard_cutoff=None)
