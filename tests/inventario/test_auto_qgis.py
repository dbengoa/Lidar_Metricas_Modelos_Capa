import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
from fixtures import four_tiles
try:
    from osgeo import ogr,osr
    from qgis.core import QgsApplication
    AVAILABLE=True
except ImportError:
    AVAILABLE=False
from lidar_forestal_integrado.lidar_core.cnig import AutomaticSource,CatalogError,transforms,query_polygon,projected_footprint,disk
from lidar_forestal_integrado.lidar_core.core import Plot,digest


@unittest.skipUnless(AVAILABLE,'QGIS/GDAL no disponibles')
class AutomaticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QgsApplication.instance() or QgsApplication([],False)
        cls.app.initQgis()

    def synthetic_client(self,missing=False):
        forward,_=transforms(25830)
        rows=[{'sec':str(i+1),'name':f'PNOA-2024-TEST-{399 if i in (0,2) else 400}-{4600 if i<2 else 4601}-H30-NPC01.LAZ','series':'LIDA3'} for i in range(4)]
        boxes=[(399980,4599980,400000,4600000),(400000,4599980,400020,4600000),(399980,4600000,400000,4600020),(400000,4600000,400020,4600020)]
        if missing:rows=rows[:-1]
        class FakeClient:
            def search(self,geometry):return [dict(r) for r in rows]
            def footprint(self,sec):
                x0,y0,x1,y1=boxes[int(sec)-1]
                ring=[]
                for x,y in ((x0,y0),(x1,y0),(x1,y1),(x0,y1),(x0,y0)):
                    lon,lat,*_=forward.TransformPoint(x,y);ring.append([lon,lat])
                return {'type':'FeatureCollection','features':[{'type':'Feature','properties':{},'geometry':{'type':'Polygon','coordinates':[ring]}}]}
        return FakeClient(),rows

    def test_real_official_footprint_reprojection(self):
        payload=json.loads((Path(__file__).parent/'data/cnig-footprint-real.json').read_text())
        data=json.loads(payload['coordsJson'])
        _,reverse=transforms(25829)
        geometry=projected_footprint(data,reverse)
        self.assertAlmostEqual(geometry.GetArea(),999980,delta=1)
        circle=disk(Plot('a',628500,4779500),15)
        self.assertTrue(geometry.Contains(circle))

    def test_query_axis_order_and_official_coverage_at_four_tile_corner(self):
        client,rows=self.synthetic_client()
        p=Plot('001',400000,4600000)
        forward,_=transforms(25830)
        q=query_polygon(p,22,forward)
        lon,lat=q['features'][0]['geometry']['coordinates'][0][0]
        self.assertTrue(-5<lon<-3)
        self.assertTrue(40<lat<43)
        with tempfile.TemporaryDirectory() as d:
            source=AutomaticSource(d,d,client=client)
            selected=source.plan([p,p],25830,5,1,2)
            self.assertEqual(len(selected),4)
            self.assertLess(json.loads((Path(d)/'cobertura_cnig.json').read_text())[0]['uncovered_area_m2'],.01)
        with tempfile.TemporaryDirectory() as d:
            client,_=self.synthetic_client(True)
            with self.assertRaisesRegex(CatalogError,'incompleta'):
                AutomaticSource(d,d,client=client).plan([p],25830,5,1,2)

    def test_acquire_download_and_resume_without_browser(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);source_dir=root/'source';source_dir.mkdir()
            originals=four_tiles(source_dir)
            before={p:digest(p) for p in originals}
            client,rows=self.synthetic_client()
            calls=[]
            class FakeOfficialBrowser:
                def __init__(self,*args):pass
                def __enter__(self):return self
                def __exit__(self,*args):pass
                def download(self,row,dest):
                    calls.append(row['sec']);dest.parent.mkdir(parents=True,exist_ok=True)
                    shutil.copyfile(originals[int(row['sec'])-1],dest)
            source=AutomaticSource(root,root,client=client,browser_factory=FakeOfficialBrowser)
            files=source.acquire([Plot('001',400000,4600000)],25830,5,1,2)
            self.assertEqual(len(files),4);self.assertEqual(len(calls),4)
            # A flat original using underscores must also be reused, without moving it.
            moved=Path(files[0]);flat=root/'originales'/moved.name.replace('-','_')
            moved.rename(flat)
            moved.with_suffix(moved.suffix+'.json').rename(flat.with_suffix(flat.suffix+'.json'))
            files[0]=str(flat)
            with patch.object(source,'browser_factory',side_effect=AssertionError('browser not needed')):
                again=source.acquire([Plot('001',400000,4600000)],25830,5,1,2)
            self.assertEqual(set(files),set(again));self.assertEqual(len(calls),4)
            self.assertEqual(before,{p:digest(p) for p in originals})

    def test_auto_engine_needs_no_user_files_or_index(self):
        self.auto_engine()

    def test_batch_engine_receives_two_lots_and_exports(self):
        self.auto_engine(batch=True)

    def auto_engine(self, batch=False):
        from lidar_forestal_integrado.lidar_core.engine import Engine
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);source_dir=root/'source';source_dir.mkdir();originals=four_tiles(source_dir)
            client,rows=self.synthetic_client()
            from lidar_forestal_integrado.lidar_core.browser import OfficialBrowser
            downloads=root/'Chrome downloads';downloads.mkdir()
            class HumanDownload(OfficialBrowser):
                def __init__(self,*args,**kwargs):
                    super().__init__(*args,**kwargs,timeout=2,poll=.001,stable_seconds=.002)
                def navigate(self,url):
                    # Simulate the user's official click producing a completed file.
                    if url.startswith('file:'):
                        manifest=self.work/url.rsplit('/',1)[1].replace('.html','.json')
                        selected=json.loads(manifest.read_text())['files']
                    else:
                        selected=[{'sec':url.rsplit('=',1)[1]}]
                    for item in reversed(selected):
                        sec=int(item['sec'])
                        row=next(row for row in rows if int(row['sec'])==sec)
                        shutil.copyfile(originals[sec-1],downloads/row['name'])
            real_source=AutomaticSource
            def source_factory(*args,**kwargs):return real_source(*args,**kwargs,client=client,browser_factory=HumanDownload)
            fusion=root/'fusion';fusion.mkdir()
            for n in ('LDA2LAS','GridSurfaceCreate','ClipData','CloudMetrics','DTM2ASCII'):(fusion/(n+'.exe')).touch()
            def fake_fusion(args):
                name=Path(args[0]).stem
                if name=='LDA2LAS':shutil.copyfile(args[1],args[2])
                elif name=='GridSurfaceCreate':Path(args[2]).write_bytes(b'mocked DTM')
                elif name=='DTM2ASCII':Path(args[-1]).write_text('ncols 100\nnrows 100\nxllcorner 399950\nyllcorner 4599950\ncellsize 1\nNODATA_value -9999\n'+(' '.join(['100']*100)+'\n')*100)
                elif name=='ClipData':shutil.copyfile(originals[0],args[-5])
                elif name=='CloudMetrics':Path(args[-1]).write_text('Mean\n10\n')
                else:raise AssertionError(args)
            config=dict(output=str(root/'output'),fusion=str(fusion),epsg=25830,radius=5,cell=1,support_distance=2,download_directory=str(downloads))
            config.update(batch_download=batch,batch_limit=2)
            with patch('lidar_forestal_integrado.lidar_core.cnig.AutomaticSource',side_effect=source_factory),patch.object(Engine,'run_command',side_effect=fake_fusion):
                run=Path(Engine(config,[Plot('001',400000,4600000)]).execute())
            self.assertEqual(json.loads((run/'estado.json').read_text())['input_mode'],'automatic_cnig')
            self.assertTrue((run/'plan_cnig.json').is_file())
            self.assertTrue((run/'cobertura_cnig.json').is_file())
            self.assertTrue((run/'metricas.gpkg').is_file())
            if batch:
                self.assertEqual(len(list(run.glob('lote_cnig_*.html'))),2)
                receipts=list((root/'output'/'originales').rglob('*.json'))
                self.assertEqual(len(receipts),4)
                self.assertTrue(all(json.loads(p.read_text())['download_flow']=='normal_chrome_human_batch_filesystem' for p in receipts))

if __name__=='__main__':unittest.main()
