import copy
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from layout_network import layout
from network_topology import import_csv,group_routes
SKILL=Path(__file__).resolve().parents[1]

class LayoutTests(unittest.TestCase):
    def topology(self):return import_csv(SKILL/'assets/import-examples/station-sequences.csv','Sample')

    def test_no_coordinate_draft_is_deterministic_and_preserves_branch_loop_and_identity(self):
        data=self.topology();before=copy.deepcopy(data)
        network,report=layout(data)
        self.assertEqual((network,report),layout(data))
        self.assertEqual(data,before)
        self.assertEqual(report['method'],'topological')
        self.assertEqual({s['id'] for s in network['stations']},{s['id'] for s in data['stations']})
        routes={r['id']:r for r in network['routes']}
        self.assertEqual(len(routes['red']['segments']),2)
        self.assertTrue(routes['loop']['segments'][0]['closed'])
        self.assertTrue(all('structure' not in route for route in network['routes']))

    def test_geographic_direction_and_coincident_distinct_ids_remain_distinct(self):
        data=self.topology()
        for i,s in enumerate(data['stations']):s['coordinates']=[120+i*.1,30+i*.1]
        data['stations'][1]['coordinates']=data['stations'][0]['coordinates'][:]
        network,report=layout(data)
        self.assertEqual(report['method'],'geographic')
        coords={s['id']:s['point'] for s in network['stations']}
        first,last=data['stations'][0]['id'],data['stations'][-1]['id']
        self.assertGreater(coords[last][0],coords[first][0])
        self.assertLess(coords[last][1],coords[first][1])
        self.assertTrue(report['automatically_shifted_stations'])
        self.assertEqual(len(set(map(tuple,coords.values()))),len(coords))

    def test_overrides_apply_and_cannot_change_station_order(self):
        data=self.topology();initial,_=layout(data)
        red=next(r for r in initial['routes'] if r['id']=='red')
        segments=copy.deepcopy(red['segments']);segments[0]['points'].insert(1,[250,400])
        override={'stations':{'central':{'point':[420,420],'label':{'offset':[20,-30],'anchor':'start'}}},
                  'routes':{'red':{'color':'#123456','segments':segments}}}
        network,_=layout(data,override)
        self.assertEqual(next(s for s in network['stations'] if s['id']=='central')['point'],[420,420])
        self.assertEqual(next(r for r in network['routes'] if r['id']=='red')['color'],'#123456')
        segments[0]['points']=['east','central','west']
        with self.assertRaisesRegex(ValueError,'order'):layout(data,override)
        with self.assertRaisesRegex(ValueError,'unknown IDs'):layout(data,{'stations':{'missing':{}}})

    def test_shared_edges_get_separate_editable_lanes_without_changing_calls(self):
        data={'schema_version':1,'title':'Lanes','sources':[],
              'stations':[{'id':'a','name':'A','coordinates':[10,20]}, {'id':'b','name':'B','coordinates':[11,21]}],
              'routes':[{'id':'one','name':'One','patterns':[{'id':'p','station_ids':['a','b']}]},
                        {'id':'two','name':'Two','patterns':[{'id':'p','station_ids':['b','a']}]}]}
        network,report=layout(data)
        self.assertGreater(report['offset_shared_segments'],0)
        paths=[route['segments'][0]['points'] for route in network['routes']]
        self.assertEqual([x for x in paths[0] if isinstance(x,str)],['a','b'])
        self.assertEqual([x for x in paths[1] if isinstance(x,str)],['b','a'])
        self.assertNotEqual(paths[0],list(reversed(paths[1])))
        self.assertTrue(all(isinstance(x,list) for x in paths[0][1:-1]))

    def test_explicit_grouping_prevents_direction_ids_from_becoming_fake_lines(self):
        data=self.topology();red=next(r for r in data['routes'] if r['id']=='red')
        reverse=copy.deepcopy(red);reverse['id']='red-return';reverse['name']='Red return'
        for pattern in reverse['patterns']:pattern['station_ids'].reverse()
        data['routes'].append(reverse)
        grouped=group_routes(data,[{'id':'both-red','name':'Red','route_ids':['red','red-return']}])
        network,report=layout(grouped)
        self.assertEqual(len(network['routes']),3)
        self.assertEqual(len(next(r for r in network['routes'] if r['id']=='both-red')['segments']),2)
        self.assertEqual(sum(len(r['patterns']) for r in grouped['routes']),6)
        with self.assertRaisesRegex(ValueError,'Unknown source'):group_routes(data,[{'id':'new','name':'X','route_ids':['unknown']}])

if __name__=='__main__':unittest.main()
