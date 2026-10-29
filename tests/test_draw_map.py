"""Portable behavior checks; no city-specific counts, topology or dependencies."""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / "scripts"))
spec = importlib.util.spec_from_file_location("draw_map", SKILL / "scripts/draw_map.py")
draw_map = importlib.util.module_from_spec(spec)
spec.loader.exec_module(draw_map)
NS = {"s": "http://www.w3.org/2000/svg"}


class PortableMapTests(unittest.TestCase):
    def setUp(self):
        self.data = json.loads((SKILL / "assets/minimal-network.json").read_text(encoding="utf-8"))

    def test_existing_templates_reproduce_their_unchanged_svg(self):
        for name in ["minimal", "multimodal", "metro-style"]:
            with self.subTest(template=name):
                data = json.loads((SKILL / f"assets/{name}-network.json").read_text(encoding="utf-8"))
                self.assertEqual(draw_map.render(data), (SKILL / f"assets/previews/{name}.svg").read_text(encoding="utf-8"))

    def test_basemap_is_below_routes_and_above_legacy_regions(self):
        self.data["basemap"] = {"frame": [20, 100, 600, 400], "background": "#dceef6", "features": []}
        svg = draw_map.render(self.data)
        root = ET.fromstring(svg)
        self.assertIsNotNone(root.find('.//s:g[@id="basemap"]', NS))
        self.assertLess(svg.index('id="regions"'), svg.index('id="basemap"'))
        self.assertLess(svg.index('id="basemap"'), svg.index('id="routes"'))
        self.data["basemap"]["frame"] = [20, 100, -1, 400]
        with self.assertRaises(draw_map.MapError):
            draw_map.render(self.data)

    def test_unicode_and_special_characters_remain_editable_text(self):
        self.data["stations"][0]["name"] = '北 & Süd <Park> "A"'
        svg = draw_map.render(self.data)
        root = ET.fromstring(svg)
        label = root.find('.//s:text[@data-label="west"]/s:tspan', NS)
        self.assertEqual(label.text, self.data["stations"][0]["name"])
        self.assertEqual(root.findall('.//s:image', NS), [])
        self.assertEqual(svg, draw_map.render(copy.deepcopy(self.data)))

    def test_shared_identity_is_transfer_and_branch_does_not_duplicate_membership(self):
        self.data["routes"][0]["segments"].append({"points": ["central", "north"]})
        root = ET.fromstring(draw_map.render(self.data))
        central = root.find('.//s:g[@data-station="central"]', NS)
        self.assertEqual(len(central.findall('s:path[@class="transfer-arrow"]', NS)), 2)
        self.assertEqual(len(root.findall('.//s:g[@data-station="central"]', NS)), 1)

    def test_branches_loop_and_independent_route_styles(self):
        data = json.loads((SKILL / "assets/multimodal-network.json").read_text(encoding="utf-8"))
        root = ET.fromstring(draw_map.render(data))
        self.assertEqual(len(root.findall('.//s:g[@data-route="regional"]//s:path', NS)), 2)
        loop = root.findall('.//s:g[@data-route="shuttle"]//s:path', NS)
        self.assertEqual(len(loop), 2)
        self.assertTrue(all(p.attrib["d"].endswith("Z") for p in loop))
        ferry = root.find('.//s:g[@data-route="ferry"]//s:path', NS)
        self.assertIn("stroke-dasharray", ferry.attrib)

    def test_three_line_arrows_have_explicit_color_order_and_ring_option(self):
        self.data["routes"].append({"id": "green", "name": "Green", "color": "#238B57", "segments": [{"points": ["central", "harbor"]}]})
        self.data["stations"][1]["transfer_order"] = ["green", "blue", "red"]
        root = ET.fromstring(draw_map.render(self.data))
        group = root.find('.//s:g[@data-station="central"]', NS)
        arrows = group.findall('s:path[@class="transfer-arrow"]', NS)
        self.assertEqual([p.attrib["stroke"] for p in arrows], ["#238B57", "#247BA0", "#D8443C"])
        self.assertEqual(len(group.findall('s:path[@class="transfer-head"]', NS)), 3)
        self.data["style"]["interchange_style"] = "ring"
        ring = ET.fromstring(draw_map.render(self.data))
        self.assertEqual(len(ring.findall('.//s:g[@data-station="central"]/s:path[@class="transfer-ring"]', NS)), 3)
        self.data["stations"][1]["transfer_order"] = ["green", "red"]
        with self.assertRaises(draw_map.MapError):
            draw_map.render(self.data)

    def test_structure_transitions_share_endpoints_without_extra_station(self):
        route = self.data["routes"][0]
        route["segments"] = [
            {"points": ["west", [300, 310]], "structure": "underground"},
            {"points": [[300, 310], "central", [500, 310]], "structure": "surface"},
            {"points": [[500, 310], "east"], "structure": "elevated"},
        ]
        root = ET.fromstring(draw_map.render(self.data))
        group = root.find('.//s:g[@data-route="red"]', NS)
        segments = [group.findall(f'.//s:g[@data-segment="{i}"]/s:path', NS) for i in range(3)]
        self.assertEqual([len(paths) for paths in segments], [1, 2, 2])
        for outer, inner in segments[1:]:
            self.assertEqual(outer.attrib["d"], inner.attrib["d"])
            self.assertEqual(inner.attrib["stroke"], "#ffffff")
        self.assertEqual(len(root.findall('.//s:g[@data-station]', NS)), len(self.data["stations"]))
        route["structure_patterns"] = {"surface": "solid"}
        route["segments"][2]["pattern"] = "dashed"
        adjusted = ET.fromstring(draw_map.render(self.data))
        group = adjusted.find('.//s:g[@data-route="red"]', NS)
        segments = [group.findall(f'.//s:g[@data-segment="{i}"]/s:path', NS) for i in range(3)]
        self.assertEqual([len(paths) for paths in segments], [1, 1, 1])
        self.assertIn("stroke-dasharray", segments[2][0].attrib)

    def test_structure_transition_pixels_do_not_depend_on_segment_order_or_direction(self):
        try:
            import gi
            gi.require_version("Rsvg", "2.0")
            from gi.repository import Rsvg
        except (ImportError, ValueError):
            self.skipTest("Optional pixel regression requires PyGObject and librsvg")

        def pixels(data):
            svg = draw_map.render(data).encode("utf-8")
            return bytes(Rsvg.Handle.new_from_data(svg).get_pixbuf().get_pixels())

        def assert_same_render(actual, expected):
            self.assertEqual(len(actual), len(expected))
            # Same-color antialiased edges can round one channel level differently
            # when composited in reverse order; a hidden core differs by far more.
            self.assertLessEqual(max(abs(a - b) for a, b in zip(actual, expected)), 1)

        data = {"version": 1, "title": "Transition", "canvas": {"width": 400, "height": 300},
                "style": {"route_width": 9}, "stations": [], "routes": [
                    {"id": "r", "name": "R", "color": "#D8443C", "segments": []}]}
        for structures in [("underground", "surface", "underground"),
                           ("surface", "elevated", "surface")]:
            for points in [([80, 150], [160, 150], [240, 150], [320, 150]),
                           ([120, 100], [160, 140], [200, 180], [240, 220])]:
                with self.subTest(structures=structures, points=points):
                    segments = [{"points": [points[i], points[i + 1]], "structure": structure}
                                for i, structure in enumerate(structures)]
                    data["routes"][0]["segments"] = segments
                    expected = pixels(data)
                    data["routes"][0]["segments"] = list(reversed(segments))
                    assert_same_render(pixels(data), expected)
                    data["routes"][0]["segments"] = [
                        {**segment, "points": list(reversed(segment["points"]))}
                        for segment in reversed(segments)]
                    assert_same_render(pixels(data), expected)

    def test_reserved_station_is_gray_dashed_with_preserved_name(self):
        self.data["stations"][0]["status"] = "reserved"
        root = ET.fromstring(draw_map.render(self.data))
        circle = root.find('.//s:g[@data-station="west"]/s:circle', NS)
        self.assertEqual(circle.attrib["stroke"], "#858b91")
        self.assertIn("stroke-dasharray", circle.attrib)
        label = root.find('.//s:text[@data-label="west"]', NS)
        self.assertEqual(label.attrib["fill"], "#858b91")
        self.assertEqual(label.find('s:tspan', NS).text, self.data["stations"][0]["name"])

    def test_corner_arc_preserves_tangent_endpoints_and_station_position(self):
        points = [(0, 0), (100, 0), (100, 100)]
        self.assertEqual(draw_map.rounded_path(points, [True, False, True], 20),
                         "M0 0 L80 0 A20 20 0 0 1 100 20 L100 100")
        self.assertEqual(draw_map.rounded_path(points, [True, True, True], 20),
                         "M0 0 L100 0 L100 100")

    def test_invalid_references_ids_and_numbers_fail_before_export(self):
        missing = copy.deepcopy(self.data)
        missing["routes"][0]["segments"][0]["points"].append("missing")
        duplicate = copy.deepcopy(self.data)
        duplicate["stations"].append(duplicate["stations"][0])
        nonfinite = copy.deepcopy(self.data)
        nonfinite["stations"][0]["point"][0] = float("nan")
        for invalid in [missing, duplicate, nonfinite]:
            with self.subTest(invalid=invalid), self.assertRaises(draw_map.MapError):
                draw_map.render(invalid)

    def test_cli_runs_outside_repository_and_check_is_read_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, output = root / "network.json", root / "out.svg"
            source.write_text(json.dumps(self.data), encoding="utf-8")
            command = [sys.executable, str(SKILL / "scripts/draw_map.py"), str(source), "--output", str(output)]
            first = subprocess.run(command, cwd=root, capture_output=True, text=True)
            self.assertEqual(first.returncode, 0, first.stderr)
            before = output.stat().st_mtime_ns
            checked = subprocess.run([*command, "--check"], cwd=root, capture_output=True, text=True)
            self.assertEqual(checked.returncode, 0, checked.stderr)
            self.assertEqual(output.stat().st_mtime_ns, before)
            output.write_text("stale", encoding="utf-8")
            failed = subprocess.run([*command, "--check"], cwd=root, capture_output=True, text=True)
            self.assertEqual(failed.returncode, 1)
            self.assertEqual(output.read_text(encoding="utf-8"), "stale")
            self.assertEqual(json.loads(source.read_text(encoding="utf-8")), self.data)


if __name__ == "__main__":
    unittest.main()
