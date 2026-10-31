"""Geometric regression tests for the corridor-based schematic layout.

These tests exercise the public layout result, including degenerate branch and
canvas cases. They deliberately do not depend on a city feed or other layouts.
"""
import copy
import json
import math
from pathlib import Path
import subprocess
import sys
import unittest


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
from schematic_layout import corridors, schematic_layout


def graph(*chains):
    adjacency = {sid: set() for chain in chains for sid in chain}
    for chain in chains:
        for first, second in zip(chain, chain[1:]):
            adjacency[first].add(second)
            adjacency[second].add(first)
    return adjacency


def edge_length(points):
    return sum(math.dist(first, second) for first, second in zip(points, points[1:]))


def proper_crossing(first, second, third, fourth):
    def area(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    return (area(first, second, third) * area(first, second, fourth) < -1e-5
            and area(third, fourth, first) * area(third, fourth, second) < -1e-5)


class SchematicLayoutTests(unittest.TestCase):
    def layout(self, adjacency, reference, geographic=True, canvas=None, overrides=None):
        canvas = {"width": 1400, "height": 1000} if canvas is None else copy.deepcopy(canvas)
        result = schematic_layout(adjacency, reference, geographic, canvas, overrides or {})
        return (*result, canvas)

    def straight(self, count=12):
        ids = [f"S{index:03}" for index in range(count)]
        return ids, graph(ids), {sid: [100 + 600 * index / (count - 1), 300]
                                for index, sid in enumerate(ids)}

    def ring(self):
        ids = [f"L{index:02}" for index in range(12)]
        reference = {sid: [500 + 300 * math.cos(index * math.pi / 6),
                           500 + 300 * math.sin(index * math.pi / 6)]
                     for index, sid in enumerate(ids)}
        return ids, graph(ids + ids[:1]), reference

    def assert_octilinear(self, edges):
        for edge, points in edges.items():
            for first, second in zip(points, points[1:]):
                dx, dy = abs(second[0] - first[0]), abs(second[1] - first[1])
                self.assertGreater(math.hypot(dx, dy), 1e-4, f"zero-length segment on {edge}")
                self.assertTrue(min(dx, dy, abs(dx - dy)) <= 2e-4,
                                f"non-octilinear segment on {edge}: {first} -> {second}")

    def assert_edge_endpoints(self, adjacency, stations, edges):
        expected = {(first, second) for first, neighbors in adjacency.items() for second in neighbors}
        self.assertEqual(set(edges), expected)
        for (first, second), points in edges.items():
            self.assertEqual(points[0], stations[first])
            self.assertEqual(points[-1], stations[second])
            self.assertEqual(points, list(reversed(edges[(second, first)])))

    def test_twelve_straight_stations_stay_collinear_in_source_order(self):
        ids, adjacency, reference = self.straight()
        stations, edges, report, _ = self.layout(adjacency, reference)
        self.assertEqual(len({stations[sid][1] for sid in ids}), 1)
        xs = [stations[sid][0] for sid in ids]
        self.assertTrue(all(left < right for left, right in zip(xs, xs[1:])))
        gaps = [right - left for left, right in zip(xs, xs[1:])]
        self.assertLess(max(gaps) - min(gaps), 2e-4)
        self.assertGreater(min(gaps), 70, "default canvas should retain readable corridor spacing")
        self.assertEqual(report["corridors"], 1)
        self.assertEqual(report["anchors"], 2)
        self.assert_octilinear(edges)
        self.assert_edge_endpoints(adjacency, stations, edges)

    def test_small_geographic_jitter_does_not_create_station_by_station_zigzags(self):
        ids, adjacency, reference = self.straight()
        for index, sid in enumerate(ids[1:-1]):
            reference[sid][1] += 7 if index % 2 else -7
        stations, edges, report, _ = self.layout(adjacency, reference)
        self.assertEqual(len({stations[sid][1] for sid in ids}), 1)
        self.assertEqual(report["corridors"], 1)
        self.assert_octilinear(edges)

    def test_topological_corridor_uses_regular_spacing_without_source_bends(self):
        ids, adjacency, reference = self.straight()
        for index, sid in enumerate(ids[1:-1]):
            reference[sid][1] += 100 if index % 2 else -100
        stations, edges, report, _ = self.layout(adjacency, reference, geographic=False)
        self.assertEqual(report["corridors"], 1)
        self.assertEqual(len({stations[sid][1] for sid in ids}), 1)
        self.assert_octilinear(edges)

    def test_corridor_decomposition_covers_each_graph_edge_exactly_once(self):
        adjacency = graph(["A", "B", "C", "D"], ["C", "E", "F", "G", "C"], ["C", "H"])
        chains = corridors(adjacency)
        actual = [frozenset((first, second)) for chain in chains for first, second in zip(chain, chain[1:])]
        expected = {frozenset((first, second)) for first, neighbors in adjacency.items() for second in neighbors}
        self.assertEqual(set(actual), expected)
        self.assertEqual(len(actual), len(expected))
        self.assertTrue(any(chain[0] == chain[-1] for chain in chains))

    def test_ring_stays_closed_with_distinct_stations_and_no_self_crossing(self):
        ids, adjacency, reference = self.ring()
        stations, edges, _, _ = self.layout(adjacency, reference)
        self.assertEqual(len(set(map(tuple, stations.values()))), len(ids))
        route = ids + ids[:1]
        path = []
        for first, second in zip(route, route[1:]):
            path.extend(edges[(first, second)][:-1])
        path.append(stations[ids[0]])
        self.assertEqual(path[0], path[-1])
        signed_area = sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(path, path[1:])) / 2
        self.assertGreater(abs(signed_area), 1000, "a ring must not collapse to a retraced line")
        segments = list(zip(path, path[1:]))
        for index, (a, b) in enumerate(segments):
            for c, d in segments[index + 1:]:
                self.assertFalse(proper_crossing(a, b, c, d), "ring crosses its own nonadjacent segment")
        self.assert_octilinear(edges)
        self.assert_edge_endpoints(adjacency, stations, edges)

    def test_stations_advance_in_equal_arc_length_steps_across_corridor_bends(self):
        ids, adjacency, _ = self.straight()
        reference = {sid: [600 * index / 11, 300 * index / 11]
                     for index, sid in enumerate(ids)}
        stations, edges, _, _ = self.layout(adjacency, reference, geographic=False)
        # Compare the full edge arc, including any intermediate octilinear
        # corner; Euclidean station distance would cut across such a corner.
        lengths = [edge_length(edges[(a, b)]) for a, b in zip(ids, ids[1:])]
        self.assertGreater(min(lengths), 0)
        self.assertLess(max(lengths) - min(lengths), 4e-4)
        walked = 0
        for first, second in zip(ids, ids[1:]):
            self.assertEqual(edges[(first, second)][0], stations[first])
            self.assertEqual(edges[(first, second)][-1], stations[second])
            next_distance = walked + edge_length(edges[(first, second)])
            self.assertGreater(next_distance, walked)
            walked = next_distance
        self.assertAlmostEqual(walked, sum(lengths), places=4)
        self.assert_octilinear(edges)

    def test_branched_graph_all_returned_segments_are_horizontal_vertical_or_diagonal(self):
        adjacency = graph(["W", "A", "J", "B", "E"], ["J", "C", "N"], ["J", "D", "S"])
        reference = {"W": [50, 400], "A": [200, 390], "J": [400, 400],
                     "B": [550, 430], "E": [800, 450], "C": [480, 200],
                     "N": [620, 50], "D": [260, 600], "S": [120, 850]}
        stations, edges, _, _ = self.layout(adjacency, reference)
        self.assert_octilinear(edges)
        self.assert_edge_endpoints(adjacency, stations, edges)

    def test_deterministic_under_reordered_inputs_and_does_not_mutate_topology(self):
        _, adjacency, reference = self.ring()
        original = copy.deepcopy((adjacency, reference))
        first = self.layout(adjacency, reference)
        reversed_adjacency = {sid: set(reversed(sorted(adjacency[sid]))) for sid in reversed(sorted(adjacency))}
        reversed_reference = {sid: reference[sid] for sid in reversed(sorted(reference))}
        self.assertEqual(first, self.layout(reversed_adjacency, reversed_reference))
        self.assertEqual(first, self.layout(adjacency, reference))
        self.assertEqual((adjacency, reference), original)

    def test_runs_with_only_standard_library_in_isolated_python(self):
        source = str(SCRIPTS / "schematic_layout.py")
        script = """
import importlib.util, json
spec = importlib.util.spec_from_file_location('schematic_under_test', SOURCE)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
adjacency = {'A': {'B'}, 'B': {'A', 'C'}, 'C': {'B'}}
reference = {'A': [0, 0], 'B': [100, 0], 'C': [200, 0]}
positions, edges, report = module.schematic_layout(adjacency, reference, True, {'width': 1400, 'height': 1000}, {})
print(json.dumps({'stations': sorted(positions), 'edges': len(edges), 'corridors': report['corridors']}))
""".replace("SOURCE", repr(source))
        completed = subprocess.run([sys.executable, "-I", "-S", "-c", script],
                                   text=True, capture_output=True, check=True)
        self.assertEqual(json.loads(completed.stdout), {"stations": ["A", "B", "C"], "edges": 4, "corridors": 1})

    def test_default_canvas_grows_to_keep_long_corridor_spacing(self):
        ids, adjacency, reference = self.straight(180)
        stations, edges, report, canvas = self.layout(adjacency, reference)
        self.assertGreater(canvas["width"], 1400)
        self.assertEqual(report["scale"], 1)
        self.assertGreater(min(edge_length(edges[(a, b)]) for a, b in zip(ids, ids[1:])), 70)
        self.assertTrue(all(0 <= x <= canvas["width"] and 0 <= y <= canvas["height"] for x, y in stations.values()))

    def test_explicit_canvas_limits_are_preserved_and_every_point_fits(self):
        _, adjacency, reference = self.straight(180)
        explicit = {"width": 800, "height": 600}
        # A clear refusal is acceptable when an explicit sheet cannot support
        # the intended spacing. A successful result must never silently clip.
        try:
            stations, edges, _, canvas = self.layout(adjacency, reference, canvas=explicit, overrides=explicit)
        except ValueError as error:
            self.assertRegex(str(error).lower(), "canvas|fit|spacing|enlarge")
            return
        self.assertEqual(canvas, explicit)
        points = list(stations.values()) + [point for path in edges.values() for point in path]
        outside = [point for point in points if not (0 <= point[0] <= 800 and 0 <= point[1] <= 600)]
        self.assertEqual(outside, [], f"explicit 800 x 600 canvas clips {len(outside)} points; examples: {outside[:3]}")

    def test_distinct_same_endpoint_branches_do_not_collapse_their_stations(self):
        adjacency = graph(["A", "X1", "X2", "B"], ["A", "Y1", "Y2", "B"], ["A", "Z1", "Z2", "B"])
        reference = {"A": [0, 100], "B": [600, 100], "X1": [200, 0], "X2": [400, 0],
                     "Y1": [200, 100], "Y2": [400, 100], "Z1": [200, 200], "Z2": [400, 200]}
        stations, edges, _, _ = self.layout(adjacency, reference)
        collisions = [(first, second) for first in stations for second in stations
                      if first < second and math.dist(stations[first], stations[second]) < 1e-3]
        self.assertEqual(collisions, [], f"different source stations collapsed: {collisions}")
        self.assert_octilinear(edges)
        self.assert_edge_endpoints(adjacency, stations, edges)


if __name__ == "__main__":
    unittest.main()
