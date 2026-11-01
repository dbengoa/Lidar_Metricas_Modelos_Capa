from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from lidar_forestal_integrado.lidar_core.browser import chrome_candidates,executable

class BrowserSelectionTests(unittest.TestCase):
    def test_chrome_all_windows_installations_and_path_without_edge(self):
        env={'PROGRAMFILES':'/programs','PROGRAMFILES(X86)':'/programs32','LOCALAPPDATA':'/local'}
        queried=[]
        def lookup(name):
            queried.append(name)
            return '/bin/'+name if name in ('chrome','google-chrome') else None
        paths=chrome_candidates(True,env,lookup)
        self.assertEqual(paths[:3],[Path('/programs/Google/Chrome/Application/chrome.exe'),Path('/programs32/Google/Chrome/Application/chrome.exe'),Path('/local/Google/Chrome/Application/chrome.exe')])
        self.assertNotIn('msedge',queried)
        self.assertNotIn('chromium',queried)
        self.assertTrue(all('Edge' not in str(p) for p in paths))

    def test_chrome_local_install_is_used_even_with_edge_elsewhere(self):
        with tempfile.TemporaryDirectory() as d:
            chrome=Path(d)/'local/Google/Chrome/Application/chrome.exe'
            edge=Path(d)/'programs32/Microsoft/Edge/Application/msedge.exe'
            for p in (chrome,edge):p.parent.mkdir(parents=True);p.touch()
            env={'PROGRAMFILES(X86)':str(Path(d)/'programs32'),'LOCALAPPDATA':str(Path(d)/'local')}
            paths=chrome_candidates(True,env,lambda name:None)
            with patch('lidar_forestal_integrado.lidar_core.browser.chrome_candidates',return_value=paths):
                self.assertEqual(executable(),str(chrome))
            chrome.unlink()
            with patch('lidar_forestal_integrado.lidar_core.browser.chrome_candidates',return_value=paths):
                with self.assertRaisesRegex(RuntimeError,'No se encontró Google Chrome'):executable()

if __name__=='__main__':unittest.main()
