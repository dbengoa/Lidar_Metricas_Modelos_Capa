"""Filesystem handoff; no interaction with CNIG or a real Chrome session."""
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from fixtures import write_cloud
from lidar_forestal_integrado.lidar_core.browser import OfficialBrowser,canonical_name,BASE
from lidar_forestal_integrado.lidar_core.core import Cancelled,AuthorizationRequired

class BrowserTests(unittest.TestCase):
    name='PNOA-2024-PNR-523-4654-NPC01.laz'
    def test_names(self):
        self.assertEqual(canonical_name(self.name),canonical_name('PNOA_2024_PNR_523_4654_NPC01 (1).LAZ'))
        self.assertNotEqual(canonical_name(self.name),canonical_name('other.laz'))
    def scenario(self,mode='complete'):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);downloads=root/'Chrome downloads';downloads.mkdir()
            source=downloads/self.name.replace('-','_');destination=root/'output/originales/1'/self.name
            write_cloud(source);original=source.read_bytes()
            if mode=='html':source.write_text('<html>Forbidden</html>')
            if mode=='partial':source.with_name(source.name+'.crdownload').touch()
            if mode=='wrong':source.rename(downloads/'other.laz')
            if mode=='symlink':
                real=downloads/'real.laz';source.rename(real);source.symlink_to(real)
            browser=OfficialBrowser(root,download_directory=downloads,timeout=.08,poll=.001,stable_seconds=.005)
            with patch('lidar_forestal_integrado.lidar_core.browser.executable',return_value='chrome'),patch('lidar_forestal_integrado.lidar_core.browser.subprocess.Popen') as launch:
                if mode in ('partial','html','wrong','symlink'):
                    with self.assertRaises(AuthorizationRequired):browser.download({'sec':'1','name':self.name},destination)
                    self.assertFalse(destination.exists())
                else:
                    with browser:result=browser.download({'sec':'1','name':self.name},destination)
                    self.assertEqual(result.read_bytes(),original);self.assertEqual(source.read_bytes(),original)
                    self.assertFalse(destination.with_suffix('.laz.part').exists())
                self.assertEqual(launch.call_args.args[0],['chrome','--new-tab',BASE+'detalleArchivo?sec=1'])
                launch.return_value.terminate.assert_not_called();launch.return_value.kill.assert_not_called()
    def test_normal_chrome_copy_preserves_original(self):self.scenario()
    def test_partial_ignored(self):self.scenario('partial')
    def test_html_ignored(self):self.scenario('html')
    def test_wrong_tile_ignored(self):self.scenario('wrong')
    def test_symlink_ignored(self):self.scenario('symlink')
    def test_cancel_does_not_close_chrome(self):
        with tempfile.TemporaryDirectory() as d:
            count=0
            def check():
                nonlocal count
                count+=1
                if count>1:raise Cancelled('cancelado')
            with patch.object(OfficialBrowser,'navigate') as navigate:
                with self.assertRaises(Cancelled):
                    with OfficialBrowser(d,check,download_directory=d) as browser:
                        browser.download({'sec':'1','name':self.name},Path(d)/'originales/1'/self.name)
                navigate.assert_called_once()
    def test_existing_original_reused_without_browser(self):
        with tempfile.TemporaryDirectory() as d:
            dest=Path(d)/self.name;write_cloud(dest);data=dest.read_bytes()
            with patch.object(OfficialBrowser,'navigate') as navigate:
                self.assertEqual(OfficialBrowser(d).download({'sec':'1','name':self.name},dest),dest)
                navigate.assert_not_called();self.assertEqual(dest.read_bytes(),data)
    def test_copy_detects_source_change_and_removes_partial(self):
        with tempfile.TemporaryDirectory() as d:
            source=Path(d)/'source.laz';write_cloud(source);dest=Path(d)/'out.laz'
            with self.assertRaises(OSError):OfficialBrowser(d).adopt(source,dest,(1,0))
            self.assertTrue(source.exists());self.assertFalse(dest.exists());self.assertFalse(Path(str(dest)+'.part').exists())
    def test_reopen_event_opens_only_official_detail(self):
        with tempfile.TemporaryDirectory() as d:
            retry=threading.Event();calls=[]
            def opened(url):
                calls.append(url)
                if len(calls)==1:retry.set()
                else:write_cloud(Path(d)/self.name)
            browser=OfficialBrowser(d,retry=retry,download_directory=d,timeout=.2,poll=.001,stable_seconds=.001)
            with patch.object(browser,'navigate',side_effect=opened):browser.download({'sec':'1','name':self.name},Path(d)/'out/1'/self.name)
            self.assertEqual(calls,[BASE+'detalleArchivo?sec=1']*2)
    def test_changing_file_not_adopted_until_stable(self):
        with tempfile.TemporaryDirectory() as d:
            source=Path(d)/self.name;write_cloud(source);calls=0
            def check():
                nonlocal calls
                calls+=1
                if calls<8:source.touch()
            browser=OfficialBrowser(d,check,download_directory=d,timeout=.2,poll=.002,stable_seconds=.01)
            with patch.object(browser,'navigate'):browser.download({'sec':'1','name':self.name},Path(d)/'out/1'/self.name)
            self.assertGreater(calls,8)
