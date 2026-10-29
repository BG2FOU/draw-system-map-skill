"""Generic basemap behavior checks, with optional real SVG pixel assertions."""
import copy
from pathlib import Path
import sys
import unittest
import xml.etree.ElementTree as ET

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
from basemap import BasemapError, render_basemap

NS = {"s": "http://www.w3.org/2000/svg"}


def ring(left, top, right, bottom):
    return [["M", left, top], ["L", right, top], ["L", right, bottom],
            ["L", left, bottom], ["Z"]]


def area(outer, holes=()):
    return {"type": "area", "parts": [{"outer": outer, "holes": list(holes)}]}


def feature(identifier, kind, geometry, **properties):
    return {"id": identifier, "kind": kind, "geometry": geometry, **properties}


def basemap(features=(), **properties):
    return {"frame": [0, 0, 200, 160], "features": list(features), **properties}


def svg(data):
    fragment = render_basemap(data, 200, 160)
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="200" height="160" '
            'viewBox="0 0 200 160"><rect width="200" height="160" fill="white"/>'
            + fragment + "</svg>")


class BasemapContractTests(unittest.TestCase):
    def test_labels_are_editable_multiline_text_below_network(self):
        land = feature("mainland", "land", area(ring(10, 10, 190, 150)))
        data = basemap([land], labels=[{"id": "name", "feature": "mainland", "point": [80, 60],
                                       "text": "北岸 & 西岸\n<城区>", "secondary_text": "North & West", "line_height": 25}])
        root = ET.fromstring(svg(data))
        label = root.find('.//s:g[@id="basemap-labels"]/s:text', NS)
        lines = label.findall('s:tspan', NS)
        self.assertEqual([line.text for line in lines], ["北岸 & 西岸", "<城区>", "North & West"])
        self.assertEqual([line.attrib["y"] for line in lines], ["60", "85", "103"])
        self.assertEqual(label.attrib["data-feature"], "mainland")
        self.assertEqual(root.findall('.//s:image', NS), [])

    def test_hidden_feature_hides_label_but_does_not_skip_validation(self):
        land = feature("mainland", "land", area(ring(10, 10, 190, 150)), visible=False)
        label = {"id": "name", "feature": "mainland", "point": [80, 60], "text": "North"}
        data = basemap([land], labels=[label])
        self.assertEqual(ET.fromstring(svg(data)).findall('.//s:g[@id="basemap-labels"]/s:text', NS), [])
        label["size"] = -1
        with self.assertRaises(BasemapError):
            svg(data)

    def test_invalid_label_references_ids_and_layout_fail(self):
        land = feature("mainland", "land", area(ring(10, 10, 190, 150)))
        label = {"id": "name", "feature": "mainland", "point": [80, 60], "text": "North"}
        for override in [{"feature": "missing"}, {"point": [True, 2]}, {"point": [2]},
                         {"opacity": 2}, {"anchor": "left"}, {"text": ""}, {"line_height": 0}]:
            with self.subTest(override=override), self.assertRaises(BasemapError):
                svg(basemap([land], labels=[{**label, **override}]))
        with self.assertRaises(BasemapError):
            svg(basemap([land], labels=[label, label]))

    def test_order_is_stable_within_layers_and_cannot_cross_layer_boundaries(self):
        shape = area(ring(20, 20, 80, 80))
        data = basemap([
            feature("water-first-in-input", "water", shape, order=-100),
            feature("land-first", "land", shape),
            feature("land-last", "land", shape, order=10),
            feature("island-before-land", "island", shape, order=-2),
            feature("land-second", "land", shape),
            feature("district", "admin", shape, clip_to=None, order=100),
            feature("border", "boundary", {"type": "line", "paths": [
                [["M", 20, 20], ["L", 80, 80]]]}, order=-100),
        ])
        root = ET.fromstring(svg(data))
        layer_ids = [node.attrib["id"] for node in root.iter()
                     if node.attrib.get("id") in {
                         "basemap-land", "basemap-admin", "basemap-water", "basemap-boundary"}]
        self.assertEqual(layer_ids, ["basemap-land", "basemap-admin", "basemap-water", "basemap-boundary"])
        land = root.find('.//s:g[@id="basemap-land"]', NS)
        self.assertEqual([node.attrib["data-feature"] for node in land.iter()
                          if "data-feature" in node.attrib],
                         ["island-before-land", "land-first", "land-second", "land-last"])
        self.assertEqual(svg(data), svg(copy.deepcopy(data)))

    def test_curves_and_explicit_closed_boundaries_remain_vector_paths(self):
        lens = [["M", 20, 40], ["Q", 60, 0, 100, 40],
                ["C", 80, 80, 40, 80, 20, 40], ["Z"]]
        data = basemap([
            feature("curved-island", "island", area(lens)),
            feature("closed-border", "boundary", {"type": "line", "paths": [ring(30, 30, 80, 80)]}),
        ])
        root = ET.fromstring(svg(data))
        curved = root.find('.//s:g[@data-feature="curved-island"]', NS)
        paths = curved.findall('.//s:path', NS)
        self.assertTrue(paths)
        self.assertTrue(any("Q" in p.attrib["d"] and "C" in p.attrib["d"] for p in paths))
        boundary = root.find('.//s:g[@data-feature="closed-border"]', NS)
        self.assertTrue(all(p.attrib["d"].rstrip().endswith("Z") for p in boundary.findall('.//s:path', NS)))
        self.assertEqual(root.findall('.//s:image', NS), [])

    def test_shared_boundary_is_one_independent_feature(self):
        land = feature("land", "land", area(ring(20, 20, 100, 140)))
        north = feature("north", "admin", area(ring(20, 20, 180, 80)), clip_to=["land"])
        south = feature("south", "admin", area(ring(20, 80, 180, 140)), clip_to=["land"])
        border = feature("shared", "boundary", {"type": "line", "paths": [
            [["M", 20, 80], ["L", 180, 80]]]})
        root = ET.fromstring(svg(basemap([land, north, south, border])))
        boundaries = root.findall('.//s:g[@id="basemap-boundary"]//s:g[@data-feature="shared"]', NS)
        self.assertEqual(len(boundaries), 1)
        self.assertEqual(len(boundaries[0].findall('.//s:path', NS)), 1)
        admin_layer = root.find('.//s:g[@id="basemap-admin"]', NS)
        self.assertEqual(admin_layer.findall('.//s:g[@data-feature="shared"]', NS), [])

    def test_invalid_geometry_is_rejected_without_mutating_input(self):
        invalid = [
            area([["M", 10, 10], ["L", 50, 10], ["L", 50, 50]]),
            area([["M", 10, 10], ["L", 50, 10], ["Z"]]),
            area([["L", 10, 10], ["L", 50, 10], ["L", 50, 50], ["Z"]]),
            area([["M", 10, 10], ["M", 50, 10], ["L", 50, 50], ["Z"]]),
            area([["M", 10, 10], ["A", 10, 10, 0, 0, 1, 50, 50], ["Z"]]),
            area([["M", 10, 10], ["Q", 20, 20, 50], ["L", 50, 50], ["Z"]]),
            area([["M", 10, 10], ["L", float("inf"), 10], ["L", 50, 50], ["Z"]]),
            area([["M", True, 10], ["L", 50, 10], ["L", 50, 50], ["Z"]]),
            area(ring(10, 10, 80, 80), [[["M", 20, 20], ["L", 30, 20], ["L", 30, 30]]]),
            {"type": "area", "parts": []},
            {"type": "line", "paths": [[["M", 10, 10], ["L", 50, 50]]]},
        ]
        for geometry in invalid:
            with self.subTest(geometry=geometry):
                data = basemap([feature("invalid", "land", geometry)])
                original = copy.deepcopy(data)
                with self.assertRaises(BasemapError):
                    render_basemap(data, 200, 160)
                self.assertEqual(data, original)

    def test_invalid_lines_frames_and_styles_are_rejected(self):
        invalid_lines = [
            {"type": "line", "paths": []},
            {"type": "line", "paths": [[["M", 20, 20]]]},
            {"type": "line", "paths": [[["M", 20, 20], ["L", 20, 20]]]},
            {"type": "line", "paths": [[["M", 20, 20], ["L", 40, 40], ["Z"], ["L", 50, 50]]]},
        ]
        for geometry in invalid_lines:
            with self.subTest(geometry=geometry), self.assertRaises(BasemapError):
                render_basemap(basemap([feature("river", "river", geometry)]), 200, 160)
        for frame in ([0, 0, 0, 100], [-1, 0, 100, 100], [180, 0, 30, 100],
                      [0, 150, 100, 20], [0, 0, float("nan"), 10], [0, 0, 100]):
            with self.subTest(frame=frame), self.assertRaises(BasemapError):
                render_basemap(basemap(frame=frame), 200, 160)
        for properties in ({"order": float("inf")}, {"visible": "false"},
                           {"style": {"opacity": 1.1}}, {"style": {"stroke_width": -1}},
                           {"style": {"dash": [2, 0]}}):
            with self.subTest(properties=properties), self.assertRaises(BasemapError):
                render_basemap(basemap([feature("land", "land", area(ring(20, 20, 80, 80)), **properties)]), 200, 160)

    def test_administrative_clip_references_are_explicit_and_type_checked(self):
        land = feature("land", "land", area(ring(20, 20, 80, 80)))
        water = feature("lake", "water", area(ring(40, 40, 60, 60)))
        district = feature("district", "admin", area(ring(0, 0, 180, 140)))
        for clip in ([], ["unknown"], ["lake"], ["land", "land"], "land"):
            with self.subTest(clip=clip), self.assertRaises(BasemapError):
                render_basemap(basemap([land, water, {**district, "clip_to": clip}]), 200, 160)
        with self.assertRaises(BasemapError):
            render_basemap(basemap([land, district]), 200, 160)
        with self.assertRaises(BasemapError):
            render_basemap(basemap([{**land, "clip_to": None}]), 200, 160)
        with self.assertRaises(BasemapError):
            render_basemap(basemap([land, {**land, "visible": False}]), 200, 160)
        # Explicit null is the documented way to retain a water-crossing extent.
        ET.fromstring(svg(basemap([land, {**district, "clip_to": None}])))


class BasemapPixelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import gi
            gi.require_version("Rsvg", "2.0")
            from gi.repository import Rsvg
        except (ImportError, ValueError):
            raise unittest.SkipTest("Optional basemap pixel checks require PyGObject and librsvg")
        cls.Rsvg = Rsvg

    def render_pixels(self, data):
        pixbuf = self.Rsvg.Handle.new_from_data(svg(data).encode("utf-8")).get_pixbuf()
        self.pixels = bytes(pixbuf.get_pixels())
        self.stride = pixbuf.get_rowstride()
        self.channels = pixbuf.get_n_channels()

    def assert_color(self, x, y, expected, tolerance=0):
        offset = y * self.stride + x * self.channels
        actual = tuple(self.pixels[offset:offset + 3])
        self.assertTrue(all(abs(a - b) <= tolerance for a, b in zip(actual, expected)),
                        f"pixel {(x, y)}: {actual} != {expected} (tolerance {tolerance})")

    def test_multiple_parts_cover_overlap_without_xor_and_preserve_local_holes(self):
        geometry = area(ring(20, 20, 110, 120), [ring(40, 40, 60, 60), ring(90, 70, 100, 90)])
        geometry["parts"].append({"outer": ring(80, 20, 160, 120)})
        self.render_pixels(basemap([feature("land", "land", geometry, style={"fill": "#22aa44", "stroke": "none"})]))
        for point in ((30, 30), (95, 35), (95, 80), (150, 50)):
            self.assert_color(*point, (34, 170, 68))
        self.assert_color(50, 50, (255, 255, 255))
        self.assert_color(180, 50, (255, 255, 255))

    def test_clip_union_keeps_holes_and_can_use_hidden_land(self):
        first = feature("mainland", "land", area(ring(20, 20, 110, 120), [ring(40, 40, 60, 60)]),
                        style={"fill": "#aaaaaa", "stroke": "none"})
        hidden = feature("hidden-island", "island", area(ring(80, 20, 160, 120), [ring(125, 70, 145, 90)]),
                         visible=False)
        district = feature("district", "admin", area(ring(0, 0, 200, 160)),
                           clip_to=["mainland", "hidden-island"], style={"fill": "#ffcc00"})
        data = basemap([first, hidden, district], background="#3366cc")
        root = ET.fromstring(svg(data))
        visible_land = root.find('.//s:g[@id="basemap-land"]', NS)
        self.assertEqual(visible_land.findall('.//s:g[@data-feature="hidden-island"]', NS), [])
        self.render_pixels(data)
        for point in ((30, 30), (95, 35), (140, 40)):
            self.assert_color(*point, (255, 204, 0))
        for point in ((50, 50), (135, 80), (180, 80)):
            self.assert_color(*point, (51, 102, 204))

    def test_nested_lake_island_and_pond_reveal_administrative_color(self):
        land = feature("mainland", "land", area(ring(20, 20, 180, 140)), style={"fill": "#dddddd"})
        district = feature("district", "admin", area(ring(0, 0, 200, 160)), clip_to=["mainland"],
                           style={"fill": "#eebb99"})
        lake = feature("lake", "water", area(ring(50, 40, 150, 120), [ring(80, 60, 120, 100)]),
                       style={"fill": "#1666cc", "stroke": "none"})
        pond = feature("island-pond", "water", area(ring(90, 70, 110, 90)), order=10,
                       style={"fill": "#1666cc", "stroke": "none"})
        self.render_pixels(basemap([pond, lake, district, land], background="#1666cc"))
        for point in ((30, 30), (85, 65)):
            self.assert_color(*point, (238, 187, 153))
        for point in ((10, 10), (60, 50), (100, 80)):
            self.assert_color(*point, (22, 102, 204))

    def test_curved_clip_keeps_holes_with_either_input_winding(self):
        contours = [
            [["M", 20, 80], ["C", 20, 0, 180, 0, 180, 80], ["C", 180, 160, 20, 160, 20, 80], ["Z"]],
            [["M", 20, 80], ["C", 20, 160, 180, 160, 180, 80], ["C", 180, 0, 20, 0, 20, 80], ["Z"]],
        ]
        for outer in contours:
            with self.subTest(outer=outer):
                land = feature("curved", "land", area(outer, [ring(80, 60, 120, 100)]), visible=False)
                district = feature("district", "admin", area(ring(0, 0, 200, 160)),
                                   clip_to=["curved"], style={"fill": "#ffcc00"})
                self.render_pixels(basemap([land, district]))
                self.assert_color(40, 80, (255, 204, 0))
                self.assert_color(100, 80, (255, 255, 255))
                self.assert_color(10, 80, (255, 255, 255))

    def test_shared_boundary_crosses_water_once_without_admin_clip(self):
        land = feature("land", "land", area(ring(20, 20, 100, 140)))
        north = feature("north", "admin", area(ring(20, 20, 180, 80)), clip_to=["land"])
        south = feature("south", "admin", area(ring(20, 80, 180, 140)), clip_to=["land"])
        border = feature("shared", "boundary", {"type": "line", "paths": [
            [["M", 20, 80], ["L", 180, 80]]]},
            style={"stroke": "#ff0000", "stroke_width": 8, "dash": [], "opacity": 0.5})
        self.render_pixels(basemap([land, north, south, border], background="#0000ff"))
        self.assert_color(140, 80, (128, 0, 127), tolerance=1)
        self.assert_color(140, 100, (0, 0, 255))

    def test_frame_clips_background_fills_and_boundary_strokes(self):
        land = feature("land", "land", area(ring(0, 0, 100, 160)), style={"fill": "#ff0000", "stroke": "none"})
        border = feature("border", "boundary", {"type": "line", "paths": [
            [["M", 20, 60], ["L", 180, 60]]]}, style={"stroke": "#00ff00", "stroke_width": 10, "dash": []})
        self.render_pixels(basemap([land, border], frame=[40, 30, 120, 100], background="#0000ff"))
        self.assert_color(50, 60, (0, 255, 0))
        self.assert_color(50, 110, (255, 0, 0))
        self.assert_color(150, 110, (0, 0, 255))
        for point in ((20, 60), (175, 60), (170, 110), (80, 20)):
            self.assert_color(*point, (255, 255, 255))


if __name__ == "__main__":
    unittest.main()
