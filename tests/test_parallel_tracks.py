"""Geometry regressions for continuous shared lanes and short-corner clipping."""
import copy
import math
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from parallel_tracks import route_geometry


def route(name, ids, **segment):
    return {'id': name, 'segments': [{'points': list(ids), **segment}]}


def edges(positions, *sequences):
    result = {}
    for sequence in sequences:
        for a, b in zip(sequence, sequence[1:]):
            result[a, b] = [positions[a], positions[b]]
            result[b, a] = [positions[b], positions[a]]
    return result


def resolve(segment, positions):
    return [[positions[value][i] + segment.get('station_offsets', {}).get(value, [0, 0])[i]
             for i in (0, 1)] if isinstance(value, str) else value
            for value in segment['points']]


class ParallelTracksTests(unittest.TestCase):
    def test_scrambled_ids_do_not_flip_lanes_or_return_to_station_centers(self):
        ids = ['z', 'a', 'p', 'b', 'q', 'c', 'r', 'd', 's', 'e', 't', 'f']
        positions = {sid: [100 + index * 80, 200] for index, sid in enumerate(ids)}
        routes = [route(name, ids) for name in ('four', 'one', 'three', 'two')]
        report = route_geometry(routes, positions, edges(positions, ids))
        heights = []
        for item in routes:
            segment = item['segments'][0]
            self.assertEqual(segment['points'], ids)
            path = resolve(segment, positions)
            self.assertEqual(len({point[1] for point in path}), 1)
            heights.append(path[0][1])
            self.assertEqual([point[0] for point in path], [positions[sid][0] for sid in ids])
        self.assertEqual(sorted(heights), [186.5, 195.5, 204.5, 213.5])
        self.assertEqual(report['unique_offset_route_edges'], 44)
        self.assertEqual(report['unique_offset_route_stations'], 48)
        self.assertEqual(report['transition_count'], 0)

    def test_reverse_and_duplicate_patterns_share_physical_lane(self):
        ids = ['a', 'z', 'b', 'y']
        positions = {sid: [index * 80, 200] for index, sid in enumerate(ids)}
        routes = [route('one', ids), route('two', ids)]
        routes[0]['segments'].append({'points': list(reversed(ids))})
        report = route_geometry(routes, positions, edges(positions, ids))
        forward, reverse = routes[0]['segments']
        self.assertEqual(forward['station_offsets'], reverse['station_offsets'])
        self.assertEqual(resolve(forward, positions), list(reversed(resolve(reverse, positions))))
        self.assertEqual(report['unique_offset_route_stations'], 8)
        self.assertEqual(report['continuous_lane_station_count'], 12)

    def test_right_angle_and_diagonal_corners_have_continuous_parallel_supports(self):
        ids = ['a', 'b', 'c', 'd']
        positions = dict(zip(ids, ([0, 0], [100, 0], [100, 100], [200, 200])))
        routes = [route('one', ids), route('two', ids)]
        report = route_geometry(routes, positions, edges(positions, ids))
        for item in routes:
            path = resolve(item['segments'][0], positions)
            for index, (a, b) in enumerate(zip(path, path[1:])):
                before, after = positions[ids[index]], positions[ids[index + 1]]
                dx, dy = after[0] - before[0], after[1] - before[1]
                self.assertAlmostEqual((b[0] - a[0]) * dy - (b[1] - a[1]) * dx, 0, delta=.02)
                self.assertGreater((b[0] - a[0]) * dx + (b[1] - a[1]) * dy, 0)
        self.assertEqual(report['transition_count'], 0)

    def test_bend_between_stations_is_offset_without_dropping_references(self):
        positions = {'a': [0, 0], 'b': [100, 100]}
        centerlines = {('a', 'b'): [[0, 0], [100, 0], [100, 100]]}
        routes = [route('one', ['a', 'b']), route('two', ['b', 'a'])]
        route_geometry(routes, positions, centerlines)
        for item in routes:
            segment = item['segments'][0]
            self.assertEqual(len(segment['points']), 3)
            path = resolve(segment, positions)
            self.assertEqual(path[0][1], path[1][1]) if item['id'] == 'one' else self.assertEqual(path[0][0], path[1][0])
            self.assertEqual([x for x in segment['points'] if isinstance(x, str)],
                             ['a', 'b'] if item['id'] == 'one' else ['b', 'a'])

    def test_shared_to_private_transition_does_not_tilt_neighboring_legs(self):
        ids = ['a', 'b', 'c', 'd']
        positions = {sid: [index * 100, 200] for index, sid in enumerate(ids)}
        routes = [route('one', ids), route('two', ids[:3])]
        report = route_geometry(routes, positions, edges(positions, ids))
        segment = routes[0]['segments'][0]
        path = resolve(segment, positions)
        self.assertEqual([x for x in segment['points'] if isinstance(x, str)], ids)
        self.assertTrue(all(a[0] == b[0] or a[1] == b[1] for a, b in zip(path, path[1:])))
        self.assertEqual(path[0][1], path[1][1])
        self.assertEqual(path[-2][1], path[-1][1])
        self.assertGreater(report['transition_count'], 0)

    def test_closed_routes_keep_wrap_corner_and_reverse_identity(self):
        ids = ['a', 'b', 'c', 'd']
        positions = dict(zip(ids, ([0, 0], [100, 0], [100, 100], [0, 100])))
        routes = [route('one', ids, closed=True), route('two', list(reversed(ids)), closed=True)]
        route_geometry(routes, positions, edges(positions, ids + ids[:1]))
        for item in routes:
            segment = item['segments'][0]
            self.assertTrue(segment['closed'])
            self.assertEqual(len(segment['points']), 4)
            path = resolve(segment, positions)
            for first, second in zip(path, path[1:] + path[:1]):
                self.assertTrue(first[0] == second[0] or first[1] == second[1])
            self.assertEqual(len(segment['station_offsets']), 4)

    def test_explicit_repeated_closed_start_is_preserved(self):
        ids = ['a', 'b', 'c', 'a']
        positions = {'a': [0, 0], 'b': [100, 0], 'c': [100, 100]}
        routes = [route('one', ids), route('two', ids)]
        route_geometry(routes, positions, edges(positions, ids))
        for item in routes:
            self.assertEqual(item['segments'][0]['points'], ids)
            points = resolve(item['segments'][0], positions)
            self.assertEqual(points[0], points[-1])

    def test_manual_route_geometry_and_offsets_are_retained(self):
        positions = {'a': [0, 0], 'b': [100, 0]}
        manual = route('one', ['a', 'b'])
        manual['segments'][0] = {'points': ['a', [20, 35], 'b'], 'station_offsets': {'a': [1, 2]}}
        before = copy.deepcopy(manual)
        routes = [manual, route('two', ['a', 'b'])]
        report = route_geometry(routes, positions, edges(positions, ['a', 'b']), {'one': {'segments': manual['segments']}})
        self.assertEqual(manual, before)
        self.assertEqual(report['manual_shared_route_ids'], ['one'])
        self.assertTrue(report['warnings'])

    def test_missing_edge_does_not_partially_mutate_routes(self):
        positions = {'a': [0, 0], 'b': [100, 0], 'c': [200, 0]}
        routes = [route('one', ['a', 'b']), route('two', ['b', 'c'])]
        before = copy.deepcopy(routes)
        with self.assertRaisesRegex(ValueError, 'Missing centerline'):
            route_geometry(routes, positions, edges(positions, ['a', 'b']))
        self.assertEqual(routes, before)

    def test_inside_corner_shorter_than_lane_offset_is_clipped_without_spike(self):
        # The 12px southbound leg reverses after a -18px offset at its 135deg
        # turn. It must be trimmed to the intersection of surrounding supports.
        positions = {'a': [0, 0], 'b': [100, 12], 'c': [200, -88]}
        centerlines = {('a', 'b'): [[0, 0], [100, 0], [100, 12]],
                      ('b', 'c'): [[100, 12], [200, -88]]}
        routes = [route(str(index), ['a', 'b', 'c']) for index in range(5)]
        report = route_geometry(routes, positions, centerlines)
        self.assertGreater(report['clipped_short_legs'], 0)
        path = resolve(routes[0]['segments'][0], positions)
        self.assertEqual(routes[0]['segments'][0]['points'], ['a', 'b', 'c'])
        self.assertAlmostEqual(path[0][1], path[1][1], delta=.0001)
        self.assertAlmostEqual(path[1][0] + path[1][1], path[2][0] + path[2][1], delta=.0001)
        self.assertTrue(all(right[0] > left[0] for left, right in zip(path, path[1:])))

    def test_short_corner_fix_is_identical_for_reverse_pattern(self):
        positions = {'a': [0, 0], 'b': [100, 12], 'c': [200, -88]}
        centerlines = {('a', 'b'): [[0, 0], [100, 0], [100, 12]],
                      ('b', 'c'): [[100, 12], [200, -88]]}
        routes = [route(str(index), ['a', 'b', 'c']) for index in range(5)]
        routes[0]['segments'].append({'points': ['c', 'b', 'a']})
        route_geometry(routes, positions, centerlines)
        forward, reverse = routes[0]['segments']
        self.assertEqual(forward['station_offsets'], reverse['station_offsets'])
        self.assertEqual(resolve(forward, positions), list(reversed(resolve(reverse, positions))))


if __name__ == '__main__':
    unittest.main()
