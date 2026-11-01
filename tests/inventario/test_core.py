import csv
import json
import math
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
from lidar_forestal_integrado.lidar_core.core import *
from lidar_forestal_integrado.lidar_core.engine import Engine, official_url


def cloud(path,count=2,compressed=False):
    h = bytearray(375)
    h[:4] = b'LASF'
    h[24:26] = bytes((1,4))
    h[104] = 128 if compressed else 6
    struct.pack_into('<I',h,96,375)
    struct.pack_into('<H',h,105,30)
    struct.pack_into('<Q',h,247,count)
    Path(path).write_bytes(h+bytes(1 if compressed else count*30))


class CoreTests(unittest.TestCase):
    def test_ids_and_radius(self):
        for plots,r,path in [([Plot('a',1,2),Plot('a',3,4)],15,'/tmp/a'),([Plot('',1,2)],15,'/tmp/a'),([Plot('a',math.nan,2)],15,'/tmp/a'),([Plot('a',1,2)],0,'/tmp/a'),([Plot('a',1,2)],15,'C:/con espacio'),([],15,'/tmp/a')]:
            with self.assertRaises(ValueError): validate(plots,r,path)
        validate([Plot('01',1,2),Plot('1',1,2)],15,'C:/datos')
        self.assertNotEqual(token('01'),token('1'))
        self.assertNotEqual(token('a/b'),token('a?b'))

    def test_four_tile_corner_and_dedup(self):
        tiles = [Tile(str(i),'a.laz',b,25830) for i,b in enumerate([(-100,-100,0,0),(0,-100,100,0),(-100,0,0,100),(0,0,100,100)])]
        selected,mapping = select_tiles([Plot('a',0,0),Plot('b',1,1)],15,tiles)
        self.assertEqual(len(selected),4)
        self.assertEqual(len(mapping['a']),4)
        with self.assertRaisesRegex(ValueError,'incompleta'):
            select_tiles([Plot('a',0,0)],15,tiles[:-1])

    def test_hole_not_just_center_or_perimeter(self):
        p=Plot('a',0,0)
        boxes=[(-20,-20,-2,20),(2,-20,20,20),(-2,-20,2,2),(-2,4,2,20)]
        tiles=[Tile(str(i),'a.laz',b,25830) for i,b in enumerate(boxes)]
        self.assertFalse(covers(p,15,tiles))
        self.assertTrue(covers(p,15,[Tile('a','a.laz',(-15,-15,15,15),25830)]))

    def test_overlapping_versions_rejected(self):
        t=Tile('1','a.laz',(-20,-20,20,20),25830)
        with self.assertRaisesRegex(ValueError,'solapados'):
            select_tiles([Plot('a',0,0)],15,[t,Tile('2','b.laz',t.bbox,25830)])

    def test_circle_can_exclude_uncovered_bbox_corners(self):
        t=[Tile('1','a.laz',(-15,-15,10,15),25830),Tile('2','b.laz',(10,-12,15,12),25830)]
        self.assertTrue(covers(Plot('a',0,0),15,t))

    def test_index_duplicate_and_wrong_crs(self):
        with tempfile.TemporaryDirectory() as d:
            f=Path(d)/'index.csv'
            header='series,sec,name,epsg,xmin,ymin,xmax,ymax\n'
            row='LIDA3,1,a.laz,25830,0,0,1000,1000\n'
            f.write_text(header+row+row)
            self.assertEqual(len(read_index(f,25830)),1)
            with self.assertRaises(ValueError): read_index(f,25829)
            f.write_text(header+row.replace('LIDA3','LIDA2'))
            with self.assertRaises(ValueError): read_index(f,25830)
            f.write_text(header+row+row.replace(',1000,1000',',2000,1000'))
            with self.assertRaises(ValueError): read_index(f,25830)

    def test_parameters(self):
        c=commands('C:/FUSION','a.laz','LAS/a.las','files.txt','ground.dtm','raw.las','norm.las','m.csv',Plot('x',100,200),15,30)
        self.assertEqual(c['convert'][1:],['a.laz','LAS/a.las'])
        self.assertEqual(c['terrain'][1:],['/class:2','ground.dtm','1','M','M','1','30','0','0','files.txt'])
        self.assertEqual(c['normalize'][1:],['/shape:1','/dtm:ground.dtm','/height','files.txt','norm.las','85','185','115','215'])
        self.assertEqual(c['metrics'][1:],['/new','norm.las','m.csv'])

    def test_las_truncated_empty_html_and_compressed(self):
        with tempfile.TemporaryDirectory() as d:
            f=Path(d)/'a.las'
            cloud(f)
            self.assertEqual(las_header(f),2)
            f.write_bytes(f.read_bytes()[:-1])
            with self.assertRaises(ValueError): las_header(f)
            cloud(f,0)
            with self.assertRaises(ValueError): las_header(f)
            f.write_text('<html>login</html>')
            with self.assertRaises(ValueError): las_header(f,True)
            cloud(f,2,True)
            self.assertEqual(las_header(f,True),2)
            with self.assertRaises(ValueError): las_header(f)

    def test_url_policy(self):
        self.assertTrue(official_url(DETAIL+'123'))
        for url in ('http://centrodedescargas.cnig.es/a','https://evil.example/a','https://centrodedescargas.cnig.es.evil.example/a','https://user:pass@centrodedescargas.cnig.es/a'):
            with self.assertRaises(ValueError): official_url(url)

    def test_existing_original_reused_and_not_changed(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'a.laz';cloud(p,2,True)
            before=p.read_bytes()
            e=Engine({},[])
            e.logfile=Path(d)/'log'
            with patch('urllib.request.OpenerDirector.open',side_effect=AssertionError('network called')):
                e.download(Tile('1','a.laz',(0,0,1,1),25830),p)
            self.assertEqual(p.read_bytes(),before)

    def test_cancel_before_download(self):
        e=Engine({},[],lambda:True)
        with self.assertRaises(Cancelled):
            e.download(Tile('1','a.laz',(0,0,1,1),25830),Path('unused'))

    def test_missing_authorization(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(AuthorizationRequired):
                Engine({},[]).download(Tile('1','a.laz',(0,0,1,1),25830),Path(d)/'a.laz')

    def test_failure_and_cancel_write_state(self):
        for exception,expected in ((Cancelled('stop'),'cancelled'),(RuntimeError('failure'),'failed'),(AuthorizationRequired('official'),'authorization_required')):
            with tempfile.TemporaryDirectory() as d:
                e=Engine({'output':d,'radius':15},[Plot('a',0,0)])
                with patch.object(e,'_execute',side_effect=exception):
                    with self.assertRaises(Exception):e.execute()
                state=json.loads((e.run/'estado.json').read_text())
                self.assertEqual(state['status'],expected)
                self.assertTrue((e.run/'proceso.log').is_file())

    def test_process_cancellation(self):
        import sys
        import time
        with tempfile.TemporaryDirectory() as d:
            started=time.monotonic()
            e=Engine({},[],lambda:time.monotonic()-started>.2)
            e.logfile=Path(d)/'log'
            with self.assertRaises(Cancelled):e.run_command([sys.executable,'-c','import time; time.sleep(10)'])
            self.assertLess(time.monotonic()-started,3)

    def test_process_nonzero(self):
        import sys
        with tempfile.TemporaryDirectory() as d:
            e=Engine({},[]);e.logfile=Path(d)/'log'
            with self.assertRaisesRegex(RuntimeError,'devolvió 7'):
                e.run_command([sys.executable,'-c','raise SystemExit(7)'])

if __name__ == '__main__': unittest.main()
