"""Synthetic GTFS archives exercise topology fidelity without redistributing feeds."""
import copy
import csv
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import import_gtfs as gtfs


def base_feed():
    return {
        "routes.txt": [
            {"route_id": "R", "route_short_name": "Blue", "route_long_name": "Blue branch line", "route_type": "1", "route_color": "0088aa"},
            {"route_id": "B", "route_short_name": "Bus", "route_long_name": "Bus service", "route_type": "3", "route_color": ""},
        ],
        "trips.txt": [
            {"route_id": "R", "service_id": "weekday", "trip_id": "out", "direction_id": "0"},
            {"route_id": "B", "service_id": "weekday", "trip_id": "bus", "direction_id": "0"},
        ],
        "stops.txt": [
            {"stop_id": "A", "stop_name": "Central", "stop_lat": "24.4", "stop_lon": "118.1", "location_type": "1", "parent_station": ""},
            {"stop_id": "A1", "stop_name": "Central platform 1", "stop_lat": "24.4001", "stop_lon": "118.1001", "location_type": "0", "parent_station": "A"},
            {"stop_id": "A2", "stop_name": "Central platform 2", "stop_lat": "24.4002", "stop_lon": "118.1002", "location_type": "0", "parent_station": "A"},
            {"stop_id": "C", "stop_name": "Central", "stop_lat": "24.4", "stop_lon": "118.1", "location_type": "0", "parent_station": ""},
            {"stop_id": "D", "stop_name": "Delta", "stop_lat": "24.5", "stop_lon": "118.2", "location_type": "0", "parent_station": ""},
            {"stop_id": "E", "stop_name": "Echo", "stop_lat": "24.6", "stop_lon": "118.3", "location_type": "0", "parent_station": ""},
        ],
        # Intentionally unsorted and nonconsecutive. Lexical order differs.
        "stop_times.txt": [
            {"trip_id": "out", "stop_id": "D", "stop_sequence": "100"},
            {"trip_id": "out", "stop_id": "A1", "stop_sequence": "2"},
            {"trip_id": "out", "stop_id": "C", "stop_sequence": "20"},
            {"trip_id": "bus", "stop_id": "E", "stop_sequence": "0"},
            {"trip_id": "bus", "stop_id": "D", "stop_sequence": "1"},
        ],
        "calendar.txt": [
            {"service_id": "weekday", "monday": "1", "tuesday": "1", "wednesday": "1", "thursday": "1", "friday": "1", "saturday": "0", "sunday": "0", "start_date": "20260101", "end_date": "20261231"},
        ],
    }


def add_trip(feed, identifier, stops, direction="0", route="R", service="weekday"):
    feed["trips.txt"].append({"route_id": route, "service_id": service, "trip_id": identifier, "direction_id": direction})
    feed["stop_times.txt"].extend({"trip_id": identifier, "stop_id": stop, "stop_sequence": str(index * 10)} for index, stop in enumerate(stops))


class GTFSImportTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "feed.zip"

    def archive(self, feed=None, bom=False, prefix="", extra=None):
        feed = base_feed() if feed is None else feed
        with zipfile.ZipFile(self.path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, rows in feed.items():
                if isinstance(rows, str):
                    body = rows
                else:
                    buffer = io.StringIO(newline="")
                    fields = list(dict.fromkeys(key for row in rows for key in row))
                    writer = csv.DictWriter(buffer, fieldnames=fields, lineterminator="\n")
                    writer.writeheader()
                    writer.writerows(rows)
                    body = buffer.getvalue()
                archive.writestr(prefix + name, ("\ufeff" if bom else "") + body)
            for name, body in (extra or {}).items():
                archive.writestr(name, body)
        return self.path

    def import_feed(self, feed=None, **kwargs):
        return gtfs.import_gtfs(self.archive(feed), "Example network", **kwargs)

    def test_lists_routes_and_accepts_bom_and_nested_members(self):
        path = self.archive(bom=True, prefix="export/")
        self.assertEqual(gtfs.list_routes(path), [
            {"id": "B", "name": "Bus", "type": "3"},
            {"id": "R", "name": "Blue", "type": "1"},
        ])
        self.assertEqual(gtfs.import_gtfs(path, "Network", route_ids=["R"])["routes"][0]["color"], "#0088AA")
        self.assertEqual(list(Path(self.temporary.name).iterdir()), [path])

    def test_keeps_numeric_order_parent_identity_and_same_name_distinct(self):
        result = self.import_feed(route_types=[1])
        self.assertEqual(result["schema_version"], 1)
        self.assertEqual(result["routes"][0]["patterns"][0]["station_ids"], ["A", "C", "D"])
        self.assertEqual([station["id"] for station in result["stations"]], ["A", "C", "D"])
        station = result["stations"][0]
        self.assertEqual(station["name"], "Central")
        self.assertEqual(station["coordinates"], [118.1, 24.4])
        self.assertEqual(station["source_stop_ids"], ["A", "A1"])
        self.assertTrue(any("Same-name" in warning for warning in result["warnings"]))
        self.assertTrue(any("not today's" in warning for warning in result["warnings"]))
        self.assertEqual(result["sources"][0]["license"], "unknown")

    def test_non_passenger_timing_point_is_not_a_station_call(self):
        feed = base_feed()
        for row in feed["stop_times.txt"]:
            if row["trip_id"] == "out" and row["stop_id"] == "C":
                row.update(pickup_type="1", drop_off_type="1")
        result = self.import_feed(feed, route_ids=["R"])
        self.assertEqual(result["routes"][0]["patterns"][0]["station_ids"], ["A", "D"])
        self.assertTrue(any("neither pickup" in item for item in result["warnings"]))

    def test_preserves_reverse_branch_express_loop_and_direction(self):
        feed = base_feed()
        add_trip(feed, "reverse", ["D", "C", "A2"], "1")
        add_trip(feed, "branch", ["A1", "C", "E"])
        add_trip(feed, "express", ["A1", "D"])
        add_trip(feed, "loop", ["A1", "C", "D", "A2"])
        add_trip(feed, "same-path-other-direction", ["A1", "C", "D"], "1")
        add_trip(feed, "platform-duplicate", ["A1", "A2", "C", "D"])
        result = self.import_feed(feed, route_ids="R")
        patterns = result["routes"][0]["patterns"]
        self.assertEqual(len(patterns), 6)
        by_key = {(pattern["direction"], tuple(pattern["station_ids"])): pattern for pattern in patterns}
        self.assertEqual(by_key[("0", ("A", "C", "D"))]["trip_count"], 2)
        self.assertEqual(by_key[("0", ("A", "C", "D"))]["source_trip_ids"], ["out", "platform-duplicate"])
        self.assertIn(("0", ("A", "C", "D", "A")), by_key)
        self.assertIn(("1", ("D", "C", "A")), by_key)
        self.assertIn(("0", ("A", "D")), by_key)
        self.assertIn(("0", ("A", "C", "E")), by_key)
        self.assertIn(("1", ("A", "C", "D")), by_key)
        self.assertEqual(result["stations"][0]["source_stop_ids"], ["A", "A1", "A2"])

    def test_trip_samples_are_bounded_but_count_is_complete_and_deterministic(self):
        feed = base_feed()
        for index in range(30):
            add_trip(feed, f"same-{index:02}", ["A1", "C", "D"])
        path = self.archive(feed)
        first = gtfs.import_gtfs(path, "Network", route_ids=["R"])
        self.assertEqual(first, gtfs.import_gtfs(path, "Network", route_ids=["R"]))
        pattern = first["routes"][0]["patterns"][0]
        self.assertEqual(pattern["trip_count"], 31)
        self.assertEqual(len(pattern["source_trip_ids"]), gtfs.TRIP_SAMPLE_LIMIT)
        feed["stop_times.txt"].reverse()
        self.archive(feed)
        self.assertEqual(first, gtfs.import_gtfs(path, "Network", route_ids=["R"]))

    def test_date_additions_removals_and_calendar_dates_only(self):
        feed = base_feed()
        add_trip(feed, "special", ["A1", "E"], service="special")
        feed["calendar_dates.txt"] = [
            {"service_id": "weekday", "date": "20261029", "exception_type": "2"},
            {"service_id": "special", "date": "20261029", "exception_type": "1"},
        ]
        result = self.import_feed(feed, route_ids=["R"], service_date="2026-10-29")
        self.assertEqual(result["routes"][0]["patterns"][0]["station_ids"], ["A", "E"])
        self.assertEqual(result["sources"][0]["service_date"], "2026-10-29")
        self.assertFalse(any("No service_date" in warning for warning in result["warnings"]))
        del feed["calendar.txt"]
        self.assertEqual(self.import_feed(feed, route_ids=["R"], service_date="2026-10-29")["routes"], result["routes"])

    def test_date_with_no_service_rejects_empty_result(self):
        with self.assertRaisesRegex(ValueError, "No active trips.*2026-11-01"):
            self.import_feed(route_ids=["R"], service_date="2026-11-01")

    def test_date_requires_calendar_but_no_date_can_import_with_warning(self):
        feed = base_feed()
        del feed["calendar.txt"]
        result = self.import_feed(feed, route_ids=["R"])
        self.assertTrue(any("validity cannot be checked" in warning for warning in result["warnings"]))
        with self.assertRaisesRegex(ValueError, "requires calendar"):
            self.import_feed(feed, service_date="2026-10-29")

    def test_missing_color_and_coordinates_stay_missing(self):
        feed = base_feed()
        feed["routes.txt"][0]["route_color"] = ""
        feed["stops.txt"][0]["stop_lat"] = ""
        feed["stops.txt"][0]["stop_lon"] = ""
        result = self.import_feed(feed, route_ids=["R"])
        self.assertNotIn("color", result["routes"][0])
        self.assertNotIn("coordinates", result["stations"][0])
        self.assertTrue(any("no source color" in warning for warning in result["warnings"]))
        self.assertTrue(any("no source coordinates" in warning for warning in result["warnings"]))

    def test_transfers_preserve_prohibition_conditions_and_separate_stations(self):
        feed = base_feed()
        feed["transfers.txt"] = [
            {"from_stop_id": "A2", "to_stop_id": "C", "transfer_type": "3", "from_route_id": "", "to_trip_id": "", "min_transfer_time": ""},
            {"from_stop_id": "A1", "to_stop_id": "D", "transfer_type": "2", "from_route_id": "R", "to_trip_id": "out", "min_transfer_time": "180"},
            {"from_stop_id": "D", "to_stop_id": "E", "transfer_type": "0", "from_route_id": "", "to_trip_id": "", "min_transfer_time": ""},
        ]
        result = self.import_feed(feed, route_ids=["R"])
        self.assertEqual(len(result["stations"]), 3)
        self.assertEqual(result["transfers"], [
            {"from": "A", "to": "C", "type": "3", "source_from_stop_id": "A2", "source_to_stop_id": "C"},
            {"from": "A", "to": "D", "type": "2", "source_from_stop_id": "A1", "source_to_stop_id": "D", "from_route_id": "R", "to_trip_id": "out", "min_transfer_time": 180},
        ])

    def test_linked_trip_rules_derive_only_actual_trip_endpoints(self):
        feed = base_feed()
        add_trip(feed, "return", ["D", "A2"], direction="1")
        feed["transfers.txt"] = [{"transfer_type": "4", "from_trip_id": "out", "to_trip_id": "return"}]
        result = self.import_feed(feed, route_ids=["R"])
        self.assertEqual(result["transfers"][0], {"from": "D", "to": "D", "type": "4", "source_from_stop_id": "D", "source_to_stop_id": "D", "from_trip_id": "out", "to_trip_id": "return", "endpoints_from_trips": True})

    def test_route_and_type_filters_intersect_and_reject_bad_selections(self):
        for kwargs in ({"route_ids": ["missing"]}, {"route_types": [9]}, {"route_ids": []}, {"route_types": []}, {"route_ids": ["R"], "route_types": [3]}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.import_feed(**kwargs)
        self.assertEqual([route["id"] for route in self.import_feed(route_ids=["R", "B"], route_types="1")["routes"]], ["R"])

    def test_unselected_stop_times_are_not_validated_or_imported(self):
        feed = base_feed()
        feed["stop_times.txt"][-1]["stop_sequence"] = "not an integer"
        feed["stop_times.txt"][-1]["stop_id"] = "missing"
        feed["stops.txt"][-1]["stop_lon"] = "invalid"
        self.assertEqual(len(self.import_feed(feed, route_ids=["R"])["stations"]), 3)

    def test_invalid_ids_references_coordinates_sequences_and_hierarchy(self):
        cases = [
            ("duplicate stop_id", lambda feed: feed["stops.txt"].append(copy.deepcopy(feed["stops.txt"][0]))),
            ("duplicate route_id", lambda feed: feed["routes.txt"].append(copy.deepcopy(feed["routes.txt"][0]))),
            ("duplicate trip_id", lambda feed: feed["trips.txt"].append(copy.deepcopy(feed["trips.txt"][0]))),
            ("unknown stop_id", lambda feed: feed["stop_times.txt"][0].update(stop_id="missing")),
            ("unknown trip_id", lambda feed: feed["stop_times.txt"][0].update(trip_id="missing")),
            ("unknown route_id", lambda feed: feed["trips.txt"][0].update(route_id="missing")),
            ("unknown service_id", lambda feed: feed["trips.txt"][0].update(service_id="missing")),
            ("unknown stop_id/parent_station", lambda feed: feed["stops.txt"][1].update(parent_station="missing")),
            ("parent_station cycle", lambda feed: feed["stops.txt"][0].update(parent_station="A1")),
            ("parent_station hierarchy", lambda feed: feed["stops.txt"][1].update(parent_station="C")),
            ("longitude/latitude", lambda feed: feed["stops.txt"][0].update(stop_lon="NaN")),
            ("longitude/latitude", lambda feed: feed["stops.txt"][1].update(stop_lat="91")),
            ("both be supplied", lambda feed: feed["stops.txt"][0].update(stop_lon="")),
            ("stop_sequence", lambda feed: feed["stop_times.txt"][0].update(stop_sequence="1.5")),
            ("stop_sequence", lambda feed: feed["stop_times.txt"][0].update(stop_sequence="-1")),
            ("duplicate stop_sequence", lambda feed: feed["stop_times.txt"][0].update(stop_sequence="2")),
            ("direction_id", lambda feed: feed["trips.txt"][0].update(direction_id="2")),
            ("route_color", lambda feed: feed["routes.txt"][0].update(route_color="red")),
        ]
        for message, change in cases:
            feed = base_feed()
            change(feed)
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                self.import_feed(feed, route_ids=["R"])

    def test_coordinate_boundaries_are_valid(self):
        feed = base_feed()
        feed["stops.txt"][0].update(stop_lon="-180", stop_lat="-90")
        feed["stops.txt"][3].update(stop_lon="180", stop_lat="90")
        result = self.import_feed(feed, route_ids=["R"])
        self.assertEqual(result["stations"][0]["coordinates"], [-180.0, -90.0])
        self.assertEqual(result["stations"][1]["coordinates"], [180.0, 90.0])

    def test_invalid_service_dates_and_calendar_data(self):
        for value in ("20261029", "2026-02-30", "2026-1-1", ""):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "service_date"):
                self.import_feed(service_date=value)
        for updates in ({"thursday": "2"}, {"start_date": "20260230"}, {"start_date": "20270101"}):
            feed = base_feed()
            feed["calendar.txt"][0].update(updates)
            with self.subTest(updates=updates), self.assertRaises(ValueError):
                self.import_feed(feed)
        feed = base_feed()
        feed["calendar_dates.txt"] = [{"service_id": "weekday", "date": "20261029", "exception_type": "1"}] * 2
        with self.assertRaisesRegex(ValueError, "duplicate service/date"):
            self.import_feed(feed)

    def test_missing_tables_and_required_columns(self):
        for table in ("routes.txt", "trips.txt", "stops.txt", "stop_times.txt"):
            feed = base_feed()
            del feed[table]
            with self.subTest(table=table), self.assertRaisesRegex(ValueError, "missing required table"):
                self.import_feed(feed)
        feed = base_feed()
        feed["stop_times.txt"] = "trip_id,stop_id\nout,A1\n"
        with self.assertRaisesRegex(ValueError, "missing required columns: stop_sequence"):
            self.import_feed(feed)

    def test_missing_stop_times_and_single_station_patterns_reject_empty_map(self):
        feed = base_feed()
        feed["stop_times.txt"] = [row for row in feed["stop_times.txt"] if row["trip_id"] == "bus"]
        with self.assertRaisesRegex(ValueError, "missing stop_times"):
            self.import_feed(feed, route_ids=["R"])
        feed["stop_times.txt"].extend([
            {"trip_id": "out", "stop_id": "A1", "stop_sequence": "1"},
            {"trip_id": "out", "stop_id": "A2", "stop_sequence": "2"},
        ])
        with self.assertRaisesRegex(ValueError, "No drawable route patterns"):
            self.import_feed(feed, route_ids=["R"])

    def test_empty_routes_or_trips_reject_empty_map(self):
        feed = base_feed()
        feed["routes.txt"] = "route_id,route_short_name,route_type\n"
        with self.assertRaisesRegex(ValueError, "selection is empty"):
            self.import_feed(feed)
        feed = base_feed()
        feed["trips.txt"] = "route_id,trip_id,service_id\n"
        with self.assertRaisesRegex(ValueError, "No trips"):
            self.import_feed(feed)

    def test_duplicate_basename_archive_member_and_total_size_limits(self):
        path = self.archive(extra={"duplicate/routes.txt": "route_id,route_type\n"})
        with self.assertRaisesRegex(ValueError, "duplicate basename"):
            gtfs.list_routes(path)
        path = self.archive()
        with patch.object(gtfs, "MAX_MEMBERS", 2), self.assertRaisesRegex(ValueError, "file members"):
            gtfs.list_routes(path)
        with patch.object(gtfs, "MAX_UNCOMPRESSED_BYTES", 2), self.assertRaisesRegex(ValueError, "size limit"):
            gtfs.list_routes(path)

    def test_invalid_zip_utf8_and_csv_raise_actionable_value_error(self):
        self.path.write_text("not a ZIP", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Cannot read GTFS ZIP"):
            gtfs.list_routes(self.path)
        with zipfile.ZipFile(self.path, "w") as archive:
            archive.writestr("routes.txt", b"route_id,route_short_name,route_type\n\xff,Name,1\n")
        with self.assertRaisesRegex(ValueError, "Cannot read routes.txt"):
            gtfs.list_routes(self.path)
        for content in ("route_id,route_id,route_type\nA,A,1\n", "route_id,route_short_name,route_type\nA,Name,1,extra\n"):
            feed = base_feed()
            feed["routes.txt"] = content
            with self.subTest(content=content), self.assertRaises(ValueError):
                self.import_feed(feed)

    def test_transfer_unknown_references_rejected_with_selected_endpoints(self):
        for changes in ({"to_stop_id": "missing"}, {"to_trip_id": "missing"}, {"from_route_id": "missing"}, {"transfer_type": "2"}, {"transfer_type": "9"}):
            feed = base_feed()
            feed["transfers.txt"] = [{"from_stop_id": "A1", "to_stop_id": "D", "transfer_type": "0", **changes}]
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.import_feed(feed, route_ids=["R"])


if __name__ == "__main__":
    unittest.main()
