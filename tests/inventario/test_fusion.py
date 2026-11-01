"""Portable regressions for the Windows startup failure reported in 0.4.0."""
from pathlib import Path
import json
import os
import tempfile
import unittest
from unittest.mock import patch,Mock
from lidar_forestal_integrado.lidar_core.fusion import program,invocation,failure_message,PROGRAMS
from lidar_forestal_integrado.lidar_core.core import commands,Plot
from lidar_forestal_integrado.lidar_core.engine import Engine

class FusionTests(unittest.TestCase):
    def test_prefers_available_64_bit_programs(self):
        with tempfile.TemporaryDirectory() as d:
            for name in PROGRAMS:
                for suffix in ('64.exe','.exe'):(Path(d)/(name+suffix)).touch()
            (Path(d)/'laszip64.dll').touch()
            for name in PROGRAMS:self.assertEqual(program(d,name).name,name+'64.exe')
            cmd=commands(d,'a','b','list.txt','m.dtm','o.las','n.las','m.csv',Plot('1',0,0),15,30)
            self.assertEqual(Path(cmd['raw'][0]).name,'ClipData64.exe')
            self.assertEqual(Path(cmd['normalize'][0]).name,'ClipData64.exe')
            self.assertEqual(Path(cmd['metrics'][0]).name,'CloudMetrics64.exe')
    def test_32_only_supported(self):
        with tempfile.TemporaryDirectory() as d:
            for name in PROGRAMS:
                file=Path(d)/(name+'.exe');file.touch();self.assertEqual(program(d,name),file)
    def test_converter_preserves_working_32_bit_laszip_pair(self):
        with tempfile.TemporaryDirectory() as d:
            for name in ('LDA2LAS.exe','LDA2LAS64.exe','LASzip.dll','ClipData.exe','ClipData64.exe'):(Path(d)/name).touch()
            self.assertEqual(program(d,'LDA2LAS').name,'LDA2LAS.exe')
            self.assertEqual(program(d,'ClipData').name,'ClipData64.exe')
            (Path(d)/'LASzip64.DLL').touch()
            self.assertEqual(program(d,'LDA2LAS').name,'LDA2LAS64.exe')
    def test_only_64_installation_is_accepted(self):
        with tempfile.TemporaryDirectory() as d:
            for name in PROGRAMS:
                file=Path(d)/(name+'64.exe');file.touch();self.assertEqual(program(d,name),file)
    def test_controlled_working_directory_and_separate_log(self):
        with tempfile.TemporaryDirectory() as d:
            directory=Path(d);exe=directory/'fusion/ClipData64.exe';log=directory/'run/proceso.log'
            original=[str(exe),'/shape:1',str(directory/'files.txt'),'raw.las','0','0','1','1']
            with patch.dict(os.environ,{'FUSION64':'TRUE','NOLASZIPDLL':'TRUE'}):
                args,options=invocation(original,log)
                self.assertEqual(options['cwd'],str(exe.parent))
                self.assertNotIn('FUSION64',options['env'])
                self.assertNotIn('NOLASZIPDLL',options['env'])
                self.assertEqual(os.environ['FUSION64'],'TRUE')
                self.assertEqual(os.environ['NOLASZIPDLL'],'TRUE')
            self.assertEqual(args,[original[0],'/log:'+str(log.parent/'fusion.log'),*original[1:]])
            self.assertEqual(original[1],'/shape:1')
    def test_nonfusion_process_unchanged(self):
        self.assertEqual(invocation(['python','-V'],'run/log'),(['python','-V'],{}))
    def test_signed_and_unsigned_crash_status(self):
        for code in (3221225477,-1073741819):
            self.assertIn('0xC0000005',failure_message('ClipData.exe',code))
            self.assertIn('memoria',failure_message('ClipData.exe',code))
        self.assertIn('devolvió 7',failure_message('test',7))
    def test_dll_error_is_distinguished(self):
        for code in (0xc0000135,0xc000007b):self.assertIn('DLL',failure_message('ClipData64.exe',code))
    def test_startup_crash_preserves_exact_command(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);e=Engine({},[]);e.run=root;e.logfile=root/'proceso.log';e.logfile.touch()
            exe=root/'ClipData64.exe'
            proc=Mock();proc.poll.return_value=3221225477;proc.returncode=3221225477
            with patch('lidar_forestal_integrado.lidar_core.engine.subprocess.Popen',return_value=proc) as launch:
                with self.assertRaisesRegex(RuntimeError,'0xC0000005'):e.run_command([str(exe),'/version'])
            saved=json.loads((root/'estado.json').read_text())
            self.assertEqual(saved['active_command'],launch.call_args.args[0])
            self.assertEqual(launch.call_args.kwargs['cwd'],str(root))
            self.assertTrue(any(a.startswith('/log:') for a in saved['active_command']))
