from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch
from lidar_forestal_integrado.cartografia.local_work import (windows_local_path,verified_copy,import_workspace,
    deliver_results,REQUIRED_FINAL)
from lidar_forestal_integrado.lidar_core.core import Cancelled


class LocalWorkTests(unittest.TestCase):
    def test_windows_mapped_and_unc_drives_rejected(self):
        windows_local_path('C:\\trabajo',lambda root:3)
        windows_local_path('D:\\trabajo',lambda root:2)
        for path,kind in [('Q:\\trabajo',4),('\\\\server\\share\\trabajo',3),('Z:\\unknown',0)]:
            with self.subTest(path=path),self.assertRaises(ValueError):
                windows_local_path(path,lambda root:kind)

    def test_verified_copy_preserves_different_destination(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'source';target=root/'target'
            source.write_bytes(b'original')
            verified_copy(source,target)
            verified_copy(source,target)
            target.write_bytes(b'user contents')
            with self.assertRaises(ValueError):verified_copy(source,target)
            self.assertEqual(target.read_bytes(),b'user contents')
            self.assertEqual(source.read_bytes(),b'original')

    def test_cancelled_copy_has_no_final_or_partial_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'source';target=root/'target'
            source.write_bytes(b'x'*2000000)
            calls=[0]
            def check():
                calls[0]+=1
                if calls[0]>=3:raise Cancelled('cancel')
            with self.assertRaises(Cancelled):verified_copy(source,target,check)
            self.assertFalse(target.exists())
            self.assertEqual(list(root.glob('target.part_*')),[])

    def test_import_only_originals_and_las(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'old';target=root/'local'
            (source/'originales'/'1').mkdir(parents=True)
            (source/'LAS').mkdir()
            (source/'originales'/'1'/'tile.laz').write_bytes(b'cloud')
            (source/'LAS'/'tile.json').write_text('{}')
            (source/'LAS'/'incomplete.part').write_bytes(b'partial')
            (source/'private.txt').write_text('not an input')
            import_workspace(source,target)
            self.assertEqual((target/'originales'/'1'/'tile.laz').read_bytes(),b'cloud')
            self.assertFalse((target/'LAS'/'incomplete.part').exists())
            self.assertFalse((target/'private.txt').exists())

    def completed(self,root):
        run=root/'local'/'run_1';run.mkdir(parents=True)
        for name in REQUIRED_FINAL:
            (run/name).write_text('fixture '+name)
        (run/'estado.json').write_text(json.dumps({'status':'completed','cartography_outputs':{'shp':str(run/'cartografia_20m.shp')}}))
        return run

    def test_delivery_is_verified_and_repeatable(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);run=self.completed(root)
            target=deliver_results(run,root/'network')
            self.assertTrue((target/'entrega.json').is_file())
            self.assertTrue((run/'entrega_final.json').is_file())
            self.assertEqual(deliver_results(run,root/'network'),target)
            (target/'cartografia_20m.dbf').write_text('corrupted')
            with self.assertRaises(ValueError):deliver_results(run,root/'network')
            self.assertEqual((target/'cartografia_20m.dbf').read_text(),'corrupted')

    def test_failed_delivery_keeps_local_outputs_and_can_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);run=self.completed(root)
            with patch('lidar_forestal_integrado.lidar_core.local_work.verified_copy',side_effect=OSError('network down')):
                with self.assertRaises(OSError):deliver_results(run,root/'network')
            self.assertTrue((run/'cartografia_20m.shp').is_file())
            self.assertEqual(json.loads((run/'estado.json').read_text())['status'],'completed')
            self.assertFalse((root/'network'/run.name).exists())
            self.assertTrue(deliver_results(run,root/'network').is_dir())

    def test_incomplete_run_not_delivered(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);run=self.completed(root)
            (run/'estado.json').write_text(json.dumps({'status':'failed'}))
            with self.assertRaises(ValueError):deliver_results(run,root/'network')
