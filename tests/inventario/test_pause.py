from pathlib import Path
import json
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from lidar_forestal_integrado.lidar_core.core import Cancelled
from lidar_forestal_integrado.lidar_core.engine import Engine


class PauseTests(unittest.TestCase):
    def engine(self, directory, cancelled=lambda: False):
        reached = threading.Event()
        engine = Engine({}, [], cancelled, lambda n, text: reached.set() if text.startswith('En pausa.') else None)
        engine.run = Path(directory)
        engine.logfile = engine.run/'proceso.log'
        engine.logfile.touch()
        return engine, reached

    def worker(self, operation):
        errors = []
        def run():
            try:
                operation()
            except Exception as error:
                errors.append(error)
        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        return thread, errors

    def test_pause_persists_state_and_resumes_same_engine(self):
        with tempfile.TemporaryDirectory() as directory:
            engine, reached = self.engine(directory)
            engine.pause_requested.set()
            thread, errors = self.worker(engine.check)
            try:
                self.assertTrue(reached.wait(3))
                self.assertTrue(thread.is_alive())
                self.assertEqual(json.loads((engine.run/'estado.json').read_text())['status'], 'paused')
            finally:
                engine.pause_requested.clear()
                thread.join(3)
            self.assertFalse(thread.is_alive())
            self.assertEqual(errors, [])
            self.assertEqual(json.loads((engine.run/'estado.json').read_text())['status'], 'running')

    def test_cancel_during_pause_without_resuming(self):
        with tempfile.TemporaryDirectory() as directory:
            cancelled = threading.Event()
            engine, reached = self.engine(directory, cancelled.is_set)
            engine.pause_requested.set()
            thread, errors = self.worker(engine.check)
            try:
                self.assertTrue(reached.wait(3))
                cancelled.set()
                thread.join(3)
                self.assertFalse(thread.is_alive())
                self.assertEqual(len(errors), 1)
                self.assertIsInstance(errors[0], Cancelled)
            finally:
                cancelled.set()
                thread.join(3)

    def test_active_subprocess_finishes_before_pause(self):
        with tempfile.TemporaryDirectory() as directory:
            engine, reached = self.engine(directory)
            marker = engine.run/'finished.txt'
            real_popen = subprocess.Popen
            def start(*args, **kwargs):
                proc = real_popen(*args, **kwargs)
                engine.pause_requested.set()
                return proc
            command = [sys.executable, '-c', 'import time, pathlib, sys; time.sleep(.2); pathlib.Path(sys.argv[1]).write_text("done")', str(marker)]
            with patch('lidar_forestal_integrado.lidar_core.engine.subprocess.Popen', side_effect=start):
                thread, errors = self.worker(lambda: engine.run_command(command))
                try:
                    self.assertTrue(reached.wait(5))
                    self.assertEqual(marker.read_text(), 'done')
                    self.assertTrue(thread.is_alive())
                finally:
                    engine.pause_requested.clear()
                    thread.join(3)
            self.assertEqual(errors, [])
            self.assertFalse(thread.is_alive())

    def test_pause_does_not_consume_browser_timeout(self):
        from lidar_forestal_integrado.lidar_core.browser import OfficialBrowser
        from fixtures import write_cloud
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            downloads = root/'downloads'
            downloads.mkdir()
            write_cloud(downloads/'tile.laz')
            clock = [0.]
            checks = [0]
            def check():
                checks[0] += 1
                if checks[0] == 2:
                    clock[0] += 100  # Long cooperative pause in the first watcher iteration.
            browser = OfficialBrowser(root, check, download_directory=downloads, timeout=1, stable_seconds=0)
            def sleep(seconds):
                clock[0] += .1
            with patch.object(browser, 'navigate'), patch('lidar_forestal_integrado.lidar_core.browser.time.monotonic', side_effect=lambda: clock[0]), patch('lidar_forestal_integrado.lidar_core.browser.time.sleep', side_effect=sleep):
                destination = root/'originals'/'tile.laz'
                self.assertEqual(browser.download({'sec': '1', 'name': 'tile.laz'}, destination), destination)
                self.assertTrue(destination.is_file())
                self.assertGreater(clock[0], 100)


if __name__ == '__main__':
    unittest.main()
