import csv
import json
import os
import shutil
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
try:
    from qgis.core import QgsApplication,QgsGeometry,QgsRectangle,QgsVectorLayer,QgsFeature
    AVAILABLE=True
except ImportError:
    AVAILABLE=False

from lidar_forestal_integrado.cartografia.models import load_models


@unittest.skipUnless(AVAILABLE,'Requiere QGIS/GDAL')
class GridTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QgsApplication.instance() or QgsApplication([],False)
        cls.app.initQgis()

    def test_grid_is_aligned_full_square_and_marks_edges(self):
        from lidar_forestal_integrado.cartografia.grid import cells
        geometry=QgsGeometry.fromRect(QgsRectangle(400001,4600000,400039,4600020))
        result=cells(bytes(geometry.asWkb()))
        self.assertEqual(len(result),2)
        self.assertEqual(len({c['id'] for c in result}),2)
        self.assertEqual([c['xmin'] for c in result],[400000,400020])
        self.assertTrue(all(abs(c['aoi_fraction']-.95)<1e-8 for c in result))

    def test_input_polygons_are_unioned_and_crs_checked(self):
        from lidar_forestal_integrado.cartografia.grid import cells,snapshot
        layer=QgsVectorLayer('Polygon?crs=EPSG:25830','AOI','memory')
        feature=QgsFeature()
        feature.setGeometry(QgsGeometry.fromRect(QgsRectangle(400000,4600000,400020,4600020)))
        layer.dataProvider().addFeatures([feature,feature])
        wkb,epsg=snapshot(layer)
        self.assertEqual(epsg,25830)
        self.assertEqual(len(cells(wkb)),1)
        wrong=QgsVectorLayer('Polygon?crs=EPSG:4326','wrong','memory')
        with self.assertRaisesRegex(ValueError,'UTM'):
            snapshot(wrong)

    def test_holes_are_not_filled(self):
        from lidar_forestal_integrado.cartografia.grid import cells
        outer=QgsGeometry.fromRect(QgsRectangle(400000,4600000,400060,4600060))
        hole=QgsGeometry.fromRect(QgsRectangle(400020,4600020,400040,4600040))
        result=cells(bytes(outer.difference(hole).asWkb()))
        self.assertEqual(len(result),8)

    def test_export_squares_fcc_p95_and_null_predictions(self):
        from lidar_forestal_integrado.cartografia.grid import cells
        from lidar_forestal_integrado.cartografia.workflow import export_grid
        geometry=QgsGeometry.fromRect(QgsRectangle(400000,4600000,400020,4600020))
        grid=cells(bytes(geometry.asWkb()))
        rows=[{'parcela_id':grid[0]['id'],'cm_Elev P95':'23.5',
               'n_primeros_retornos':10,'n_primeros_retornos_sobre_corte':6,'n_puntos':20}]
        with tempfile.TemporaryDirectory() as directory:
            export_grid(directory,grid,rows,25830,load_models(),lambda:None)
            for extension in ('shp','gpkg'):
                layer=QgsVectorLayer(str(Path(directory)/('cartografia_20m.'+extension)),'result','ogr')
                self.assertTrue(layer.isValid())
                self.assertEqual(layer.featureCount(),1)
                feature=next(layer.getFeatures())
                self.assertEqual(feature.geometry().area(),400)
                self.assertEqual(feature['FCC'],.6)
                self.assertEqual(feature['HDOM_M'],23.5)
                self.assertEqual(feature['EST_N'],'SIN_MODELO')
                from qgis.core import NULL
                self.assertEqual(feature['N_HA'],NULL)
                self.assertLessEqual(max(len(f.name()) for f in layer.fields()),10)
            self.assertTrue((Path(directory)/'cartografia_20m.prj').is_file())
            self.assertTrue((Path(directory)/'cartografia_20m.dbf').is_file())

    def test_complete_engine_with_simulated_fusion(self):
        self.complete_engine()

    def test_filtered_models_with_unfiltered_hdom(self):
        self.complete_engine(standard_cutoff=2)

    def test_cell_checkpoint_skips_recalculation(self):
        self.complete_engine(resume='cache')

    def test_new_equations_reuse_metrics_but_update_predictions(self):
        self.complete_engine(resume='models')

    def test_corrupt_cell_cache_is_recomputed(self):
        self.complete_engine(resume='corrupt')

    def test_previous_010_run_is_verified_against_local_sources(self):
        self.complete_engine(resume='legacy')

    def test_legacy_incomplete_but_consistent_las_is_recomputed(self):
        self.complete_engine(resume='legacy_incomplete')

    def test_changed_mdt_settings_invalidate_cell_cache(self):
        self.complete_engine(resume='config')

    def test_copy_only_task_uses_completed_local_results(self):
        self.complete_engine(resume='delivery')

    def complete_engine(self, standard_cutoff=None, resume=None):
        from fixtures import write_cloud
        from lidar_forestal_integrado.cartografia.grid import cells
        from lidar_forestal_integrado.cartografia.workflow import GridEngine
        from lidar_forestal_integrado.lidar_core.engine import Engine
        points=[(399960+x+.5,4599960+y+.5,z,c) for x in range(100) for y in range(100) for z,c in ((100,2),(110,5))]
        geometry=QgsGeometry.fromRect(QgsRectangle(400000,4600000,400020,4600020))
        grid=cells(bytes(geometry.asWkb()))
        calls=[]
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            source=root/'source.las'
            write_cloud(source,points)
            fusion=root/'fusion';fusion.mkdir()
            for name in ('LDA2LAS','GridSurfaceCreate','DTM2ASCII','ClipData','CloudMetrics'):
                (fusion/(name+'.exe')).touch()
            def run(args):
                calls.append(args)
                name=Path(args[0]).stem
                if name=='LDA2LAS':
                    shutil.copyfile(args[1],args[2])
                elif name=='ClipData':
                    self.assertIn('/shape:0',args)
                    left,bottom,right,top=map(float,args[-4:])
                    selected=[(x,y,z-100 if '/height' in args else z,c) for x,y,z,c in points if left<=x<=right and bottom<=y<=top]
                    write_cloud(args[-5],selected)
                elif name=='GridSurfaceCreate':
                    Path(args[2]).write_bytes(b'simulated terrain')
                elif name=='DTM2ASCII':
                    Path(args[-1]).write_text('ncols 100\nnrows 100\nxllcorner 399960\nyllcorner 4599960\ncellsize 1\nNODATA_value -9999\n'+(' '.join(['100']*100)+'\n')*100)
                elif name=='CloudMetrics':
                    filtered=any(str(a).startswith('/minht') for a in args)
                    Path(args[-1]).write_text('Elev P95,Elev mean\n10,'+('10' if filtered else '5')+'\n')
                else:
                    raise AssertionError(args)
            models=load_models()
            models['package']['modelos']={'N_ha':{'familia':'lineal','intercepto':5,'predictores':['cm_Elev mean'],'coeficientes':[2],'medianas':[10],'rangos':{'cm_Elev mean':[0,30]}}}
            models['mapping']['N_HA']='N_ha'
            models['standard_height_filter_m']=standard_cutoff
            config={'output':str(root/'work'),'files':[str(source)],'fusion':str(fusion),'epsg':25830,'cell':1,'support_distance':5}
            with patch.object(Engine,'run_command',side_effect=run):
                engine=GridEngine(config,grid,models)
                directory=Path(engine.execute())
            state=json.loads((directory/'estado.json').read_text())
            self.assertEqual(state['status'],'completed')
            self.assertIn('shp',state['cartography_outputs'])
            layer=QgsVectorLayer(str(directory/'cartografia_20m.shp'),'result','ogr')
            feature=next(layer.getFeatures())
            self.assertEqual(feature.geometry().area(),400)
            self.assertEqual(feature['FCC'],.5)
            self.assertEqual(feature['HDOM_M'],10)
            self.assertEqual(feature['N_PUNTOS'],800)
            self.assertEqual(feature['N_PRIM'],800)
            self.assertEqual(feature['N_PRIM_2'],400)
            self.assertEqual(feature['N_HA'],25 if standard_cutoff==2 else 15)
            self.assertEqual(feature['EST_N'],'OK')
            if resume:
                import copy
                import struct
                config2=dict(config)
                models2=copy.deepcopy(models)
                if resume=='models':
                    models2['package']['modelos']['N_ha']['coeficientes']=[4]
                if resume=='corrupt':
                    pointer=next((root/'work'/'celdas').glob('*/latest.json'))
                    generation=json.loads(pointer.read_text())['generation']
                    corrupt=pointer.parent/generation/'normalizada.las'
                    corrupt.write_bytes(corrupt.read_bytes()[:-1])
                if resume=='config':
                    config2['cell']=2
                if resume.startswith('legacy'):
                    old_state=json.loads((directory/'estado.json').read_text())
                    old_state['cartography_version']='0.1.0'
                    old_state['version']='0.1.0'
                    old_state.pop('tools_sha256',None)
                    old_state['status']='failed'
                    (directory/'estado.json').write_text(json.dumps(old_state))
                    config2.update(output=str(root/'new_local'),previous_run=str(directory))
                    if resume=='legacy_incomplete':
                        from lidar_forestal_integrado.lidar_core.core import token
                        path=directory/token(grid[0]['id'])/'entorno_mdt.las'
                        data=bytearray(path.read_bytes())
                        size=struct.unpack_from('<H',data,105)[0]
                        count=struct.unpack_from('<Q',data,247)[0]
                        struct.pack_into('<Q',data,247,count-1)
                        struct.pack_into('<I',data,107,count-1)
                        path.write_bytes(data[:-size])
                if resume=='delivery':
                    from lidar_forestal_integrado.cartografia.plugin import Job
                    task=Job({'copy_run':str(directory),'final_destination':str(root/'final')},None)
                    with patch.object(Engine,'run_command',side_effect=AssertionError('must not run FUSION')):
                        self.assertTrue(task.run(),task.message)
                    self.assertTrue((root/'final'/directory.name/'cartografia_20m.shp').is_file())
                    return
                calls.clear()
                with patch.object(Engine,'run_command',side_effect=run):
                    again=GridEngine(config2,grid,models2)
                    second=Path(again.execute())
                reuses=resume in ('cache','models','legacy')
                self.assertEqual(bool(calls),not reuses)
                state2=json.loads((second/'estado.json').read_text())
                self.assertEqual(state2['status'],'completed')
                self.assertEqual(bool(state2['plots'][0].get('reused')),reuses)
                if resume=='models':
                    changed=QgsVectorLayer(str(second/'cartografia_20m.gpkg'),'changed','ogr')
                    self.assertEqual(next(changed.getFeatures())['N_HA'],25)
                if resume=='legacy':
                    self.assertEqual(state2['legacy_recovery'][0]['square_points_verified'],800)
                    self.assertTrue((again.previous.staged/'estado.json').is_file())
            if standard_cutoff==2:
                self.assertTrue(any('/minht:2' in a for a in calls))
                self.assertTrue((directory/'metricas_modelos.csv').is_file())

    def test_dialog_and_help(self):
        from lidar_forestal_integrado.cartografia.plugin import Dialog
        class Iface:
            def mainWindow(self):return None
        dialog=Dialog(Iface())
        self.assertIn('20 m',dialog.windowTitle())
        self.assertIn('modelos.json',dialog.model_notice.text())
        self.assertFalse(dialog.pause.isEnabled())
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'modelos.json'
            models={name:{'familia':'media','intercepto':10,'predictores':[],
                          'coeficientes':[],'medianas':[],'rangos':{}} for name in ('N_ha','V_ha','G_ha','Hdom','FCC_pct')}
            path.write_text(json.dumps({'version':'0.4.2-experimental','modelos':models}))
            dialog.model_path.setText(str(path))
            dialog.load_model_choices()
            self.assertEqual(dialog.model_targets['N_HA'].currentData(),'N_ha')
            self.assertEqual(dialog.model_targets['VOL_HA'].currentData(),'V_ha')
            self.assertEqual(dialog.model_targets['AB_HA'].currentData(),'G_ha')
            self.assertEqual(dialog.model_targets['N_HA'].findData('Hdom'),-1)
        dialog.show_help()
        self.assertTrue(dialog.help_dialog.isVisible())
        dialog.help_dialog.close()
        dialog.close()
