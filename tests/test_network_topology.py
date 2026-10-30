import copy
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from network_topology import import_csv, validate_topology

class TopologyTests(unittest.TestCase):
    def fixture(self, directory, body):
        path=Path(directory)/'stations.csv'
        path.write_text('route_id,route_name,pattern_id,sequence,station_id,station_name,lon,lat\n'+body,encoding='utf-8-sig')
        return path

    def test_csv_preserves_order_shared_identity_and_same_name_different_stations(self):
        with tempfile.TemporaryDirectory() as d:
            path=self.fixture(d, 'r,线路,p,30,b,中央,,\nr,线路,p,10,a,中央,,\ns,Second,p,1,b,中央,,\ns,Second,p,2,c,Centre,,\n')
            data=import_csv(path,'Sample')
        self.assertEqual(data['routes'][0]['patterns'][0]['station_ids'],['a','b'])
        self.assertEqual(len(data['stations']),3)
        self.assertEqual(data['routes'][1]['patterns'][0]['station_ids'],['b','c'])
        before=copy.deepcopy(data)
        validate_topology(data)
        self.assertEqual(data,before)

    def test_csv_rejects_conflicting_sequences_names_and_partial_coordinates(self):
        for body in ['r,R,p,1,a,A,,\nr,R,p,1,b,B,,\n',
                     'r,R,p,1,a,A,,\nr,R,p,2,a,B,,\n',
                     'r,R,p,1,a,A,10,\nr,R,p,2,b,B,,\n']:
            with self.subTest(body=body), tempfile.TemporaryDirectory() as d:
                with self.assertRaises(ValueError): import_csv(self.fixture(d,body),'Sample')

    def test_unknown_references_and_unserved_station_fail(self):
        with tempfile.TemporaryDirectory() as d:
            data=import_csv(self.fixture(d,'r,R,p,1,a,A,,\nr,R,p,2,b,B,,\n'),'Sample')
        for change in [lambda t:t['routes'][0]['patterns'][0]['station_ids'].append('unknown'),
                       lambda t:t['stations'].append({'id':'c','name':'Unserved'}),
                       lambda t:t['stations'][0].update(coordinates=[float('nan'),10])]:
            broken=copy.deepcopy(data);change(broken)
            with self.assertRaises(ValueError): validate_topology(broken)

if __name__=='__main__': unittest.main()
