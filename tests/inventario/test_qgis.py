import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import tempfile
from pathlib import Path
import unittest
try:
    from qgis.core import QgsApplication,QgsVectorLayer,Qgis
    from osgeo import gdal
    AVAILABLE=True
except ImportError:
    AVAILABLE=False

@unittest.skipUnless(AVAILABLE,'QGIS/GDAL no disponibles en este intérprete')
class QgisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QgsApplication.instance() or QgsApplication([],False)
        cls.app.initQgis()
        print('QGIS probado:',Qgis.QGIS_VERSION)

    def terrain(self,path,nodata=False):
        import numpy as np
        ds=gdal.GetDriverByName('GTiff').Create(str(path),100,100,1,gdal.GDT_Float32)
        ds.SetGeoTransform((-50,1,0,50,0,-1))
        values=np.ones((100,100),dtype=np.float32)*100
        if nodata: values[50,50]=-9999
        ds.GetRasterBand(1).SetNoDataValue(-9999)
        ds.GetRasterBand(1).WriteArray(values)
        ds=None

    def test_terrain_hole_and_complete(self):
        from lidar_forestal_integrado.lidar_core.core import Plot
        from lidar_forestal_integrado.lidar_core.qgis_io import verify_terrain
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'terrain.tif'
            self.terrain(p)
            verify_terrain(p,Plot('a',0,0),15,lambda:None)
            self.terrain(p,True)
            with self.assertRaisesRegex(ValueError,'Huecos'):
                verify_terrain(p,Plot('a',0,0),15,lambda:None)

    def test_gpkg_csv_ids_and_geometry(self):
        from lidar_forestal_integrado.lidar_core.core import token
        from lidar_forestal_integrado.lidar_core.qgis_io import export_results
        with tempfile.TemporaryDirectory() as d:
            rows=[dict(parcela_id=id,x=400000+i,y=4600000,radio_m=15,n_puntos=100,cm_mean='12.3') for i,id in enumerate(('001','A/ñ'))]
            for row in rows:(Path(d)/token(row['parcela_id'])).mkdir()
            export_results(d,rows,25830,lambda:None)
            layer=QgsVectorLayer(str(Path(d)/'metricas.gpkg'),'test','ogr')
            self.assertTrue(layer.isValid())
            self.assertEqual(layer.featureCount(),2)
            self.assertEqual(layer.crs().authid(),'EPSG:25830')
            self.assertEqual({f['parcela_id'] for f in layer.getFeatures()},{'001','A/ñ'})
            for row in rows:
                single=QgsVectorLayer(str(Path(d)/token(row['parcela_id'])/'metricas.gpkg'),'test','ogr')
                self.assertEqual(single.featureCount(),1)
                f=next(single.getFeatures())
                self.assertEqual(f['parcela_id'],row['parcela_id'])
                self.assertEqual(f.geometry().asPoint().x(),row['x'])
                single=None
            layer=None

    def test_dialog_default_radius_and_fusion(self):
        from lidar_forestal_integrado.inventario.plugin import Dialog
        from qgis.PyQt.QtWidgets import QMainWindow
        window=QMainWindow()
        class Iface:
            def mainWindow(self):return window
        dialog=Dialog(Iface())
        self.assertEqual(dialog.radius.value(),15)
        self.assertEqual(dialog.fusion.text(),'C:\\FUSION')
        self.assertFalse(dialog.cancel_button.isEnabled())
        self.assertFalse(hasattr(dialog,'index'))
        self.assertFalse(dialog.assume_crs.isChecked())
        self.assertFalse(hasattr(dialog,'files'))
        self.assertFalse(dialog.auth_button.isEnabled())
        self.assertEqual(dialog.auth_button.text(),'Volver a abrir ficha')
        self.assertTrue(Path(dialog.download_directory.text()).is_absolute())
        self.assertIn('Inventario de parcelas',dialog.windowTitle())
        dialog.close()

    def test_offline_help_and_pause_controls(self):
        import threading
        from lidar_forestal_integrado.inventario.plugin import Dialog
        class Iface:
            def mainWindow(self): return None
        class Job:
            pause_requested = threading.Event()
            cancelled = False
            def isCanceled(self): return self.cancelled
            def cancel(self): self.cancelled = True
        dialog = Dialog(Iface())
        self.assertFalse(dialog.pause_button.isEnabled())
        self.assertTrue(dialog.batch_download.isChecked())
        self.assertEqual(dialog.batch_limit.maximum(),20)
        self.assertEqual(dialog.batch_limit.value(),20)
        dialog.batch_download.setChecked(False)
        self.assertFalse(dialog.batch_limit.isEnabled())
        dialog.batch_download.setChecked(True)
        self.assertTrue(dialog.batch_limit.isEnabled())
        dialog.show_help()
        text = dialog.help_browser.toPlainText()
        self.assertIn('FPC =', text)
        self.assertIn('Pausa, reanudación y cancelación', text)
        first_help = dialog._help_dialog
        dialog.show_help()
        self.assertIs(dialog._help_dialog, first_help)
        dialog.job = Job()
        dialog.pause_button.setEnabled(True)
        dialog.toggle_pause()
        self.assertTrue(dialog.job.pause_requested.is_set())
        self.assertEqual(dialog.pause_button.text(), 'Retirar pausa')
        dialog.status(10, 'En pausa. Pulse «Reanudar» para continuar.')
        self.assertEqual(dialog.pause_button.text(), 'Reanudar')
        dialog.toggle_pause()
        self.assertFalse(dialog.job.pause_requested.is_set())
        dialog.toggle_pause()
        dialog.cancel()
        self.assertFalse(dialog.pause_button.isEnabled())
        dialog.finished('', 'Cancelado')
        self.assertIsNone(dialog.job)
        self.assertEqual(dialog.pause_button.text(), 'Pausar')
        dialog._help_dialog.close()
        dialog.close()

    def test_wkt_crs_and_compound(self):
        from osgeo import osr
        from fixtures import write_cloud
        from lidar_forestal_integrado.lidar_core.local import metadata,resolve_epsg
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'wkt.las'
            crs=osr.SpatialReference();crs.ImportFromEPSG(25830)
            write_cloud(p,epsg=None,wkt=crs.ExportToWkt(),evlr=True)
            self.assertEqual(resolve_epsg(metadata(p),25830),(25830,False))
            vertical=osr.SpatialReference();vertical.ImportFromEPSG(5703)
            compound=osr.SpatialReference();compound.SetCompoundCS('test',crs,vertical)
            write_cloud(p,epsg=None,wkt=compound.ExportToWkt())
            self.assertEqual(resolve_epsg(metadata(p),25830),(25830,False))
            write_cloud(p,epsg=25829,wkt=crs.ExportToWkt())
            with self.assertRaisesRegex(ValueError,'distintos'):resolve_epsg(metadata(p),25830)

    def test_local_point_support_missing_neighbor_and_ground(self):
        from fixtures import four_tiles,write_cloud
        from lidar_forestal_integrado.lidar_core.local import verify_point_support
        from lidar_forestal_integrado.lidar_core.core import Plot
        with tempfile.TemporaryDirectory() as d:
            paths=four_tiles(d)
            p=Plot('001',400000,4600000)
            report=verify_point_support(paths,p,10,2)
            self.assertFalse(report['official_footprint_verified'])
            self.assertGreater(report['sample_count'],100)
            with self.assertRaisesRegex(ValueError,'insuficiente'):
                verify_point_support(paths[:-1],p,10,2)
            canopy=Path(d)/'canopy.las'
            write_cloud(canopy,[(400000+x+.5,4600000+y+.5,110,5) for x in range(-20,20) for y in range(-20,20)])
            with self.assertRaisesRegex(ValueError,'suelo clase 2'):
                verify_point_support([str(canopy)],p,10,2)

    def test_local_engine_without_index_and_conversion_cache(self):
        import shutil
        import json
        from unittest.mock import patch
        from fixtures import four_tiles
        from lidar_forestal_integrado.lidar_core.engine import Engine
        from lidar_forestal_integrado.lidar_core.core import Plot,digest
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            sources=root/'source with spaces';sources.mkdir()
            paths=four_tiles(sources)
            before={p:digest(p) for p in paths}
            fusion=root/'fusion';fusion.mkdir()
            for n in ('LDA2LAS','GridSurfaceCreate','ClipData','CloudMetrics','DTM2ASCII'):(fusion/(n+'.exe')).touch()
            calls=[]
            def fake_fusion(args):
                calls.append(args)
                name=Path(args[0]).stem
                if name=='LDA2LAS':shutil.copyfile(args[1],args[2])
                elif name=='GridSurfaceCreate':Path(args[2]).write_bytes(b'mocked DTM')
                elif name=='DTM2ASCII':
                    Path(args[-1]).write_text('ncols 100\nnrows 100\nxllcorner 399950\nyllcorner 4599950\ncellsize 1\nNODATA_value -9999\n'+(' '.join(['100']*100)+'\n')*100)
                elif name=='ClipData':
                    output=args[-5]
                    shutil.copyfile(paths[0],output)
                elif name=='CloudMetrics':Path(args[-1]).write_text('Mean\n10\n')
                else:raise AssertionError(args)
            config=dict(output=str(root/'output'),files=paths,fusion=str(fusion),epsg=25830,radius=5,cell=1,support_distance=2)
            statuses=[]
            with patch.object(Engine,'run_command',side_effect=fake_fusion):
                first=Path(Engine(config,[Plot('001',400000,4600000)],progress=lambda n,text:statuses.append(text)).execute())
                conversions=len([a for a in calls if Path(a[0]).stem=='LDA2LAS'])
                second=Path(Engine(config,[Plot('001',400000,4600000)]).execute())
            first_state=json.loads((first/'estado.json').read_text())
            self.assertEqual(len(first_state['tiles']),4)
            self.assertTrue(all(t['status']=='verified' and Path(t['las']).is_file() for t in first_state['tiles']))
            self.assertEqual(first_state['outputs']['gpkg'],str(first/'metricas.gpkg'))
            self.assertTrue(any('LAS convertido y verificado:' in text for text in statuses))
            self.assertTrue(any(text.startswith('CloudMetrics') for text in statuses))
            self.assertEqual(conversions,4)
            self.assertEqual(len([a for a in calls if Path(a[0]).stem=='LDA2LAS']),4)
            self.assertNotEqual(first,second)
            self.assertTrue((first/'metricas.gpkg').is_file())
            inventory=json.loads((first/'archivos_locales.json').read_text())
            self.assertEqual(len(inventory),4)
            self.assertEqual(json.loads((first/'estado.json').read_text())['input_mode'],'local_files')
            # Reproduce the reported ClipData crash after all conversions verified.
            from lidar_forestal_integrado.lidar_core.fusion import failure_message
            failed=Engine(config,[Plot('001',400000,4600000)])
            def fail_clip(args):
                if Path(args[0]).stem=='ClipData' and '/shape:1' in args:raise RuntimeError(failure_message(args[0],3221225477))
                return fake_fusion(args)
            with patch.object(Engine,'run_command',side_effect=fail_clip):
                with self.assertRaisesRegex(RuntimeError,'ClipData: recorte circular.*0xC0000005'):failed.execute()
            state=json.loads((failed.run/'estado.json').read_text())
            self.assertEqual(state['status'],'failed')
            self.assertEqual(state['phase'],'ClipData: recorte circular')
            self.assertEqual(len(state['tiles']),4)
            self.assertTrue(all(t['status']=='verified' and t['reused'] for t in state['tiles']))
            self.assertFalse((failed.run/'metricas.csv').exists())
            self.assertEqual(before,{p:digest(p) for p in paths})

if __name__=='__main__':unittest.main()
