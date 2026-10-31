"""Continuous lane geometry keeps the original shared station identities."""
import copy
import json
from pathlib import Path
import sys
import unittest
import xml.etree.ElementTree as ET

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / "scripts"))
import draw_map

NS = {"s": "http://www.w3.org/2000/svg"}


def network():
    return {
        "version": 1,
        "title": "Parallel corridor",
        "stations": [{"id": sid, "name": sid.upper(), "point": [x, 100]}
                     for sid, x in (("a", 100), ("b", 200), ("c", 300))],
        "routes": [{"id": rid, "name": rid, "color": stroke,
                    "segments": [{"points": ["a", "b", "c"]}]}
                   for rid, stroke in (("red", "#D8443C"), ("blue", "#247BA0"))],
    }


class StationOffsetsTests(unittest.TestCase):
    def test_parallel_tracks_do_not_return_to_shared_station_centers(self):
        data = network()
        for route, dy in zip(data["routes"], (-6, 6)):
            route["segments"][0]["station_offsets"] = {sid: [0, dy] for sid in ("a", "b", "c")}
        before = copy.deepcopy(data)
        root = ET.fromstring(draw_map.render(data))
        for rid, y in (("red", 94), ("blue", 106)):
            path = root.find(f'.//s:g[@data-route="{rid}"]//s:path', NS)
            self.assertEqual(path.attrib["d"], f"M100 {y} L200 {y} L300 {y}")
        self.assertEqual(len(root.findall('.//s:g[@data-station]', NS)), 3)
        for sid, x in (("a", 100), ("b", 200), ("c", 300)):
            marker = root.find(f'.//s:g[@data-station="{sid}"]', NS)
            self.assertEqual(marker.attrib["transform"], f"translate({x} 100)")
            self.assertEqual(len(marker.findall('s:path[@class="transfer-arrow"]', NS)), 2)
            label = root.find(f'.//s:text[@data-label="{sid}"]', NS)
            self.assertEqual((label.attrib["x"], label.attrib["y"]), (str(x + 14), "88"))
        self.assertEqual(data, before)

    def test_no_offsets_and_empty_offsets_reproduce_existing_outputs(self):
        for name in ("minimal", "multimodal", "metro-style", "coastal-basemap", "inland-basemap"):
            with self.subTest(template=name):
                data = json.loads((SKILL / f"assets/{name}-network.json").read_text(encoding="utf-8"))
                original = (SKILL / f"assets/previews/{name}.svg").read_text(encoding="utf-8")
                self.assertEqual(draw_map.render(data), original)
                for route in data["routes"]:
                    for segment in route["segments"]:
                        segment["station_offsets"] = {}
                self.assertEqual(draw_map.render(data), original)

    def test_partial_offsets_leave_other_stations_and_waypoints_in_place(self):
        data = network()
        segment = data["routes"][0]["segments"][0]
        segment["points"] = ["a", [150, 100], "b", "c"]
        segment["station_offsets"] = {"b": [0, -6]}
        data["routes"][0]["corner_radius"] = 0
        root = ET.fromstring(draw_map.render(data))
        path = root.find('.//s:g[@data-route="red"]//s:path', NS)
        self.assertEqual(path.attrib["d"], "M100 100 L150 100 L200 94 L300 100")

    def test_invalid_offset_objects_and_coordinates_are_rejected(self):
        malformed = (None, [], "offsets", {"a": 6}, {"a": [0]}, {"a": [0, 1, 2]},
                     {"a": [True, 0]}, {"a": [float("inf"), 0]}, {"a": [0, float("nan")]},
                     {1: [0, 6]})
        for offsets in malformed:
            with self.subTest(offsets=offsets):
                data = network()
                data["routes"][0]["segments"][0]["station_offsets"] = offsets
                with self.assertRaises(draw_map.MapError):
                    draw_map.render(data)

    def test_unknown_or_nonmember_station_offsets_are_rejected(self):
        for sid in ("unknown", "outside"):
            with self.subTest(station=sid):
                data = network()
                data["stations"].append({"id": "outside", "name": "Outside", "point": [400, 100]})
                data["routes"][0]["segments"][0]["station_offsets"] = {sid: [0, 6]}
                with self.assertRaisesRegex(draw_map.MapError, "unknown station ID|not referenced by this segment"):
                    draw_map.render(data)

    def test_offsets_cannot_create_invalid_final_geometry(self):
        data = network()
        data["routes"][0]["segments"][0]["station_offsets"] = {"b": [-100, 0]}
        with self.assertRaisesRegex(draw_map.MapError, "consecutive identical points"):
            draw_map.render(data)
        data = network()
        data["stations"][0]["point"][0] = 1e308
        data["routes"][0]["segments"][0]["station_offsets"] = {"a": [1e308, 0]}
        with self.assertRaisesRegex(draw_map.MapError, "finite number"):
            draw_map.render(data)


if __name__ == "__main__":
    unittest.main()
