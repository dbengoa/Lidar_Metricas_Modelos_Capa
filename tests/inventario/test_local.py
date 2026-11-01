from pathlib import Path
import shutil
import struct
import tempfile
import unittest
from lidar_forestal_integrado.lidar_core.core import Plot,Cancelled
from lidar_forestal_integrado.lidar_core.local import metadata,resolve_epsg,discover,select_local
from fixtures import write_cloud,four_tiles


class LocalTests(unittest.TestCase):
    def test_metadata_las12_geokey(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'source.las';write_cloud(p,version=2)
            m=metadata(p)
            self.assertEqual(m.epsg,25830)
            self.assertEqual(m.bbox,(400000.5,4600000.5,400001.5,4600001.5))
            self.assertEqual(m.count,2)
            self.assertFalse(m.compressed)
            self.assertEqual(resolve_epsg(m,25830),(25830,False))

    def test_metadata_laz_header_without_decompression(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'source.laz';write_cloud(p,compressed=True)
            self.assertTrue(metadata(p).compressed)
            self.assertEqual(metadata(p).epsg,25830)

    def test_metadata_evlr_and_truncation(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'source.las';write_cloud(p,evlr=True)
            self.assertEqual(metadata(p).epsg,25830)
            p.write_bytes(p.read_bytes()[:-1])
            with self.assertRaisesRegex(ValueError,'EVLR'):metadata(p)

    def test_missing_crs_requires_explicit_assumption(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'source.las';write_cloud(p,epsg=None)
            m=metadata(p)
            with self.assertRaisesRegex(ValueError,'CRS ausente'):resolve_epsg(m,25830)
            self.assertEqual(resolve_epsg(m,25830,True),(25830,True))

    def test_known_mismatch_never_overridden(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'source.las';write_cloud(p,epsg=25829)
            with self.assertRaisesRegex(ValueError,'incompatible'):resolve_epsg(metadata(p),25830,True)

    def test_invalid_envelope_scale_record(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'source.las'
            for offset,fmt,value in ((131,'<d',0),(179,'<d',float('nan')),(105,'<H',1)):
                write_cloud(p)
                data=bytearray(p.read_bytes());struct.pack_into(fmt,data,offset,value);p.write_bytes(data)
                with self.assertRaises(ValueError):metadata(p)

    def test_content_deduplication_and_provenance(self):
        with tempfile.TemporaryDirectory() as d:
            a=Path(d)/'same.las';b=Path(d)/'copy.las';write_cloud(a);shutil.copyfile(a,b)
            tiles,inventory=discover([str(a),str(b),str(a)],25830)
            self.assertEqual(len(tiles),1)
            self.assertEqual(len(inventory),2)
            self.assertTrue(inventory[1]['duplicate'])
            self.assertFalse(inventory[0]['crs_assumed'])
            self.assertEqual(inventory[0]['series'],'not_verified_from_header')
            self.assertEqual(tiles[0].source,str(a))

    def test_discovery_cancellation(self):
        def cancel():raise Cancelled()
        with self.assertRaises(Cancelled):discover(['anything.las'],25830,check=cancel)

    def test_local_four_neighbors_and_overlap(self):
        with tempfile.TemporaryDirectory() as d:
            paths=four_tiles(d)
            tiles,_=discover(paths,25830)
            selected,mapping=select_local([Plot('001',400000,4600000)],10,tiles)
            self.assertEqual(len(selected),4)
            self.assertEqual(len(mapping['001']),4)
            with self.assertRaisesRegex(ValueError,'No hay archivos'):
                select_local([Plot('other',0,0)],10,tiles)
            write_cloud(Path(d)/'different.las')
            more,_=discover(paths+[str(Path(d)/'different.las')],25830)
            with self.assertRaisesRegex(ValueError,'solapadas'):
                select_local([Plot('001',400000,4600000)],10,more)

if __name__=='__main__':unittest.main()
