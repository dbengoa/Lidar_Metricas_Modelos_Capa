from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from fixtures import write_cloud
from lidar_forestal_integrado.lidar_core.browser import OfficialBrowser
from lidar_forestal_integrado.lidar_core.batches import prepare, batch_size
from lidar_forestal_integrado.lidar_core.cnig import AutomaticSource
from lidar_forestal_integrado.lidar_core.core import AuthorizationRequired, Cancelled


class BatchTests(unittest.TestCase):
    def items(self, root, count=2):
        return [({'sec': str(i+1), 'name': f'PNOA-test-{i+1}.laz'}, root/'originales'/str(i+1)/f'PNOA-test-{i+1}.laz') for i in range(count)]

    def test_reverse_order_receipts_and_one_guide(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            downloads = root/'downloads'
            downloads.mkdir()
            items = self.items(root)
            # Only the second file is ready when the watcher starts.
            write_cloud(downloads/items[1][0]['name'])
            received = []
            def receipt(record, path):
                received.append(record['sec'])
                if len(received) == 1:
                    write_cloud(downloads/items[0][0]['name'])
            browser = OfficialBrowser(root, download_directory=downloads, timeout=.4, poll=.001, stable_seconds=.002)
            with patch.object(browser, 'navigate') as launch:
                result = browser.download_batch(items, received=receipt)
            self.assertEqual(received, ['2', '1'])
            self.assertEqual(len(result), 2)
            launch.assert_called_once_with((root/'lote_cnig_1.html').as_uri())
            self.assertTrue(all(path.is_file() for record, path in items))
            self.assertEqual(len(list(downloads.iterdir())), 2)
            self.assertIn('no añade archivos automáticamente', (root/'lote_cnig_1.html').read_text())

    def test_partial_and_unrelated_files_not_adopted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            downloads = root/'downloads'
            downloads.mkdir()
            items = self.items(root)
            for record, path in items:
                write_cloud(downloads/record['name'])
            (downloads/(items[1][0]['name']+'.crdownload')).touch()
            write_cloud(downloads/'unrelated.laz')
            receipts = []
            browser = OfficialBrowser(root, download_directory=downloads, timeout=.04, poll=.001, stable_seconds=.001)
            with patch.object(browser, 'navigate'), self.assertRaisesRegex(AuthorizationRequired, 'PNOA-test-2'):
                browser.download_batch(items, received=lambda record, path: receipts.append(record['sec']))
            self.assertEqual(receipts, ['1'])
            self.assertTrue(items[0][1].exists())
            self.assertFalse(items[1][1].exists())

    def test_invalid_limits_and_ambiguous_names_rejected(self):
        for value in (0, 21, True, 2.5, '20'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                batch_size(value)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            browser = OfficialBrowser(root)
            with self.assertRaises(ValueError):
                prepare(browser, self.items(root, 21), 1)
            items = self.items(root)
            items[1][0]['name'] = items[0][0]['name'].replace('-', '_')
            with self.assertRaisesRegex(ValueError, 'ambiguo'):
                prepare(browser, items, 1)

    def test_guide_navigation_confined_to_work_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            browser = OfficialBrowser(root/'work')
            guide = prepare(browser, self.items(root), 1)
            with patch('lidar_forestal_integrado.lidar_core.browser.executable', return_value='chrome'), patch('lidar_forestal_integrado.lidar_core.browser.subprocess.Popen') as launch:
                browser.navigate(guide.as_uri())
                self.assertEqual(launch.call_args.args[0], ['chrome', '--new-tab', guide.as_uri()])
                outside = root/'lote_cnig_1.html'
                outside.write_text('outside')
                for url in (outside.as_uri(), 'https://example.org', guide.as_uri()+'?other=1'):
                    with self.assertRaises(ValueError):
                        browser.navigate(url)

    def test_cancel_keeps_received_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            downloads = root/'downloads'
            downloads.mkdir()
            items = self.items(root)
            write_cloud(downloads/items[0][0]['name'])
            cancelled = threading.Event()
            def check():
                if cancelled.is_set():
                    raise Cancelled('cancelado')
            browser = OfficialBrowser(root, check, download_directory=downloads, timeout=.3, poll=.001, stable_seconds=.001)
            with patch.object(browser, 'navigate'), self.assertRaises(Cancelled):
                browser.download_batch(items, received=lambda record, path: cancelled.set())
            self.assertTrue(items[0][1].is_file())
            self.assertFalse(items[1][1].exists())

    def test_split_twenty_and_resume_only_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            items = self.items(root, 23)
            calls = []
            class Browser:
                fail = True
                def __init__(self, *args, **kwargs): pass
                def __enter__(self): return self
                def __exit__(self, *args): pass
                def download_batch(self, batch, number, received):
                    calls.append(len(batch))
                    if number == 2 and self.fail:
                        raise AuthorizationRequired('second batch interrupted')
                    for record, destination in batch:
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        write_cloud(destination)
                        received(record, destination)
            def source():
                result = AutomaticSource(root, root/'run', browser_factory=Browser, batch_download=True)
                result.plan = lambda *args: [record for record, path in items]
                return result
            with self.assertRaises(AuthorizationRequired):
                source().acquire([], 25830, 15, 1)
            self.assertEqual(calls, [20, 3])
            self.assertTrue(all(path.with_suffix('.laz.json').is_file() for record, path in items[:20]))
            Browser.fail = False
            files = source().acquire([], 25830, 15, 1)
            self.assertEqual(calls, [20, 3, 3])
            self.assertEqual(len(files), 23)

    def test_pause_does_not_consume_batch_waiting_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            downloads = root/'downloads'
            downloads.mkdir()
            items = self.items(root,1)
            write_cloud(downloads/items[0][0]['name'])
            clock, calls = [0.], [0]
            def check():
                calls[0] += 1
                if calls[0] == 2:
                    clock[0] += 100
            browser = OfficialBrowser(root,check,download_directory=downloads,timeout=1,stable_seconds=0)
            with patch.object(browser,'navigate'), patch('lidar_forestal_integrado.lidar_core.batches.time.monotonic',side_effect=lambda:clock[0]), patch('lidar_forestal_integrado.lidar_core.batches.time.sleep',side_effect=lambda seconds:clock.__setitem__(0,clock[0]+.1)):
                browser.download_batch(items)
            self.assertTrue(items[0][1].is_file())


if __name__ == '__main__':
    unittest.main()
