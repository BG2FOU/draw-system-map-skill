import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
SKILL=Path(__file__).resolve().parents[1]
class GeneratorTests(unittest.TestCase):
    def command(self,*args):return subprocess.run([sys.executable,str(SKILL/'scripts/create_map.py'),*map(str,args)],capture_output=True,text=True)
    def test_csv_to_svg_from_another_directory_without_manual_coordinates(self):
        with tempfile.TemporaryDirectory() as d:
            out=Path(d)/'new map'
            result=self.command('build',SKILL/'assets/import-examples/station-sequences.csv','--title','City network','--output-dir',out)
            self.assertEqual(result.returncode,0,result.stderr)
            topology=json.loads((out/'topology.json').read_text())
            network=json.loads((out/'network.json').read_text())
            self.assertEqual(len(topology['stations']),7)
            self.assertEqual(len(network['routes']),3)
            self.assertTrue(all('point' in station for station in network['stations']))
            self.assertIn('<text',(out/'network.svg').read_text())
            before=(out/'network.svg').read_bytes()
            repeated=self.command('build',SKILL/'assets/import-examples/station-sequences.csv','--output-dir',out)
            self.assertNotEqual(repeated.returncode,0)
            self.assertEqual((out/'network.svg').read_bytes(),before)
    def test_invalid_input_keeps_source_and_an_actionable_failure_report(self):
        with tempfile.TemporaryDirectory() as d:
            source=Path(d)/'bad.json';source.write_text('{}');out=Path(d)/'out'
            result=self.command('build',source,'--output-dir',out)
            self.assertNotEqual(result.returncode,0)
            report=json.loads((out/'report.json').read_text())
            self.assertEqual(report['status'],'failed')
            self.assertEqual((out/'source.json').read_text(),'{}')
            self.assertFalse((out/'network.svg').exists())
if __name__=='__main__':unittest.main()
