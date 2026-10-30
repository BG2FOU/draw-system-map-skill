"""Read a local GTFS Schedule ZIP into the system-map topology contract.

Only the Python standard library is needed. ZIP members are streamed, never
extracted. Stop times for unselected trips are discarded as they are read.
This imports service patterns, not a timetable or a promise of current service.
"""
from __future__ import annotations

from collections import defaultdict
from contextlib import contextmanager
import csv
from datetime import date
import io
import math
from pathlib import Path, PurePosixPath
import re
import zipfile


MAX_MEMBERS = 128
MAX_UNCOMPRESSED_BYTES = 2 * 1024 * 1024 * 1024
TRIP_SAMPLE_LIMIT = 8
WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


def _integer(value, label):
    if not re.fullmatch(r"[0-9]+", str(value)):
        raise ValueError(f"{label}: expected a non-negative integer, got {value!r}")
    return int(value)


def _date(value, label, iso=False):
    pattern = r"\d{4}-\d{2}-\d{2}" if iso else r"\d{8}"
    if not isinstance(value, str) or not re.fullmatch(pattern, value):
        raise ValueError(f"{label}: expected {'YYYY-MM-DD' if iso else 'YYYYMMDD'}")
    try:
        return date.fromisoformat(value if iso else f"{value[:4]}-{value[4:6]}-{value[6:]}")
    except ValueError as exc:
        raise ValueError(f"{label}: invalid date {value!r}") from exc


class _Feed:
    def __init__(self, archive):
        self.archive = archive
        self.members = {}
        files = [item for item in archive.infolist() if not item.is_dir()]
        if len(files) > MAX_MEMBERS:
            raise ValueError(f"GTFS ZIP has more than {MAX_MEMBERS} file members")
        if sum(item.file_size for item in files) > MAX_UNCOMPRESSED_BYTES:
            raise ValueError("GTFS ZIP exceeds the 2 GiB uncompressed size limit")
        for item in files:
            basename = PurePosixPath(item.filename.replace("\\", "/")).name.lower()
            if basename in self.members:
                raise ValueError(f"GTFS ZIP contains duplicate basename {basename!r}")
            if item.flag_bits & 1:
                raise ValueError(f"GTFS ZIP contains an encrypted member: {item.filename}")
            self.members[basename] = item

    def rows(self, table, required, optional=False):
        member = self.members.get(table)
        if member is None:
            if optional:
                return
            raise ValueError(f"GTFS ZIP is missing required table {table}")
        try:
            with self.archive.open(member) as raw, io.TextIOWrapper(raw, encoding="utf-8-sig", newline="") as stream:
                reader = csv.DictReader(stream, strict=True)
                headers = reader.fieldnames
                if not headers:
                    raise ValueError(f"{table}: missing CSV header")
                headers = [field.strip() for field in headers]
                if len(headers) != len(set(headers)) or any(not field for field in headers):
                    raise ValueError(f"{table}: duplicate or empty column name")
                reader.fieldnames = headers
                missing = set(required) - set(headers)
                if missing:
                    raise ValueError(f"{table}: missing required columns: {', '.join(sorted(missing))}")
                if table == "routes.txt" and not {"route_short_name", "route_long_name"}.intersection(headers):
                    raise ValueError("routes.txt: requires route_short_name or route_long_name")
                for row in reader:
                    if None in row or any(value is None for value in row.values()):
                        raise ValueError(f"{table}:{reader.line_num}: inconsistent CSV column count")
                    yield {key: value.strip() for key, value in row.items()}
        except (UnicodeError, csv.Error, zipfile.BadZipFile, RuntimeError, NotImplementedError, OSError) as exc:
            raise ValueError(f"Cannot read {table}: {exc}") from exc


@contextmanager
def _open_feed(path):
    try:
        with zipfile.ZipFile(path) as archive:
            yield _Feed(archive)
    except (zipfile.BadZipFile, zipfile.LargeZipFile, OSError) as exc:
        raise ValueError(f"Cannot read GTFS ZIP {path}: {exc}") from exc


def _indexed(rows, key, table):
    result = {}
    for row in rows:
        identifier = row[key]
        if not identifier:
            raise ValueError(f"{table}: empty {key}")
        if identifier in result:
            raise ValueError(f"{table}: duplicate {key} {identifier!r}")
        result[identifier] = row
    return result


def _routes(feed):
    routes = _indexed(feed.rows("routes.txt", ("route_id", "route_type")), "route_id", "routes.txt")
    for route in routes.values():
        _integer(route["route_type"], f"route {route['route_id']} route_type")
    return routes


def _route_name(route):
    return route.get("route_short_name") or route.get("route_long_name") or route["route_id"]


def list_routes(path):
    """Return deterministic route choices; ``type`` is the GTFS type string."""
    with _open_feed(path) as feed:
        return [{"id": identifier, "name": _route_name(route), "type": route["route_type"]}
                for identifier, route in sorted(_routes(feed).items())]


def _selection(values, label):
    if values is None:
        return None
    if isinstance(values, (str, int)):
        values = [values]
    result = {str(value).strip() for value in values}
    if not result or "" in result:
        raise ValueError(f"{label}: selection must not be empty")
    return result


def _services(feed, needed, service_day, warnings):
    """Validate selected services and resolve additions/removals for one day."""
    if not {"calendar.txt", "calendar_dates.txt"}.intersection(feed.members):
        if service_day is not None:
            raise ValueError("service_date requires calendar.txt or calendar_dates.txt")
        warnings.append("No calendar.txt or calendar_dates.txt: service validity cannot be checked.")
        return None
    known, active, calendar_seen, exception_seen = set(), set(), set(), set()
    for row in feed.rows("calendar.txt", ("service_id", *WEEKDAYS, "start_date", "end_date"), optional=True):
        service = row["service_id"]
        if service not in needed:
            continue
        if service in calendar_seen:
            raise ValueError(f"calendar.txt: duplicate service_id {service!r}")
        calendar_seen.add(service)
        known.add(service)
        start = _date(row["start_date"], f"calendar {service} start_date")
        end = _date(row["end_date"], f"calendar {service} end_date")
        if start > end:
            raise ValueError(f"calendar {service}: start_date exceeds end_date")
        if any(row[day] not in {"0", "1"} for day in WEEKDAYS):
            raise ValueError(f"calendar {service}: weekday flags must be 0 or 1")
        if service_day is not None and start <= service_day <= end and row[WEEKDAYS[service_day.weekday()]] == "1":
            active.add(service)
    for row in feed.rows("calendar_dates.txt", ("service_id", "date", "exception_type"), optional=True):
        service = row["service_id"]
        if service not in needed:
            continue
        known.add(service)
        day = _date(row["date"], f"calendar_dates {service} date")
        key = (service, day)
        if key in exception_seen:
            raise ValueError(f"calendar_dates.txt: duplicate service/date {service!r} {day}")
        exception_seen.add(key)
        if row["exception_type"] not in {"1", "2"}:
            raise ValueError(f"calendar_dates {service}: exception_type must be 1 or 2")
        if day == service_day:
            if row["exception_type"] == "1":
                active.add(service)
            else:
                active.discard(service)
    unknown = needed - known
    if unknown:
        raise ValueError(f"trips.txt references unknown service_id: {', '.join(sorted(unknown))}")
    return active if service_day is not None else None


class _Stops:
    def __init__(self, rows, warnings):
        self.rows = _indexed(rows, "stop_id", "stops.txt")
        self.warnings = warnings
        self.cache = {}
        self.coordinate_cache = {}

    def coordinates(self, identifier):
        if identifier in self.coordinate_cache:
            return self.coordinate_cache[identifier]
        row = self.rows[identifier]
        lon, lat = row.get("stop_lon", ""), row.get("stop_lat", "")
        coordinate = None
        if bool(lon) != bool(lat):
            raise ValueError(f"stop {identifier}: longitude and latitude must both be supplied or both be absent")
        if lon:
            try:
                coordinate = [float(lon), float(lat)]
            except ValueError as exc:
                raise ValueError(f"stop {identifier}: invalid longitude/latitude") from exc
            if not all(math.isfinite(value) for value in coordinate) or not (-180 <= coordinate[0] <= 180 and -90 <= coordinate[1] <= 90):
                raise ValueError(f"stop {identifier}: longitude/latitude outside valid ranges")
        self.coordinate_cache[identifier] = coordinate
        return coordinate

    def canonical(self, identifier, coordinates=True):
        # Validate the entire referenced parent chain before accepting any merge.
        chain, seen, current = [], set(), identifier
        while current:
            if current in seen:
                raise ValueError(f"stop {identifier}: parent_station cycle involving {current!r}")
            if current not in self.rows:
                raise ValueError(f"stops.txt: unknown stop_id/parent_station {current!r}")
            seen.add(current)
            chain.append(current)
            current = self.rows[current].get("parent_station", "")
        for current in chain:
            row = self.rows[current]
            location = row.get("location_type") or "0"
            if location not in {"0", "1", "2", "3", "4"}:
                raise ValueError(f"stop {current}: invalid location_type {location!r}")
            parent = row.get("parent_station", "")
            if parent:
                parent_type = self.rows[parent].get("location_type") or "0"
                expected = "0" if location == "4" else "1"
                if location == "1" or parent_type != expected:
                    raise ValueError(f"stop {current}: invalid parent_station hierarchy")
            elif location in {"2", "3", "4"}:
                raise ValueError(f"stop {current}: location_type {location} requires parent_station")
            if coordinates:
                self.coordinates(current)
        canonical = next((item for item in chain if self.rows[item].get("location_type") == "1"), identifier)
        self.cache[identifier] = canonical
        return canonical


def _transfers(feed, stops, station_ids, routes, selected_routes, trips, selected_trips, sequences, warnings):
    transfers = []
    for row in feed.rows("transfers.txt", ("transfer_type",), optional=True):
        kind = row["transfer_type"]
        source_from, source_to = row.get("from_stop_id", ""), row.get("to_stop_id", "")
        derived = False
        if kind in {"4", "5"}:
            from_trip, to_trip = row.get("from_trip_id", ""), row.get("to_trip_id", "")
            if from_trip not in selected_trips or to_trip not in selected_trips:
                continue
            if not source_from or not source_to:
                source_from = source_from or sequences[from_trip][-1][1]
                source_to = source_to or sequences[to_trip][0][1]
                derived = True
        resolved = []
        errors = []
        for stop_id in (source_from, source_to):
            try:
                resolved.append(stops.canonical(stop_id, coordinates=False))
                errors.append(None)
            except ValueError as exc:
                resolved.append(None)
                errors.append(exc)
        relevant = any(identifier in station_ids for identifier in resolved)
        if relevant and any(errors):
            raise next(error for error in errors if error is not None)
        if not all(identifier in station_ids for identifier in resolved):
            continue
        if kind not in {"", "0", "1", "2", "3", "4", "5"}:
            raise ValueError(f"transfers.txt: invalid transfer_type {kind!r}")
        keep = True
        conditions = {}
        for side in ("from", "to"):
            route_id, trip_id = row.get(f"{side}_route_id", ""), row.get(f"{side}_trip_id", "")
            if route_id:
                if route_id not in routes:
                    raise ValueError(f"transfers.txt: unknown route_id {route_id!r}")
                keep = keep and route_id in selected_routes
                conditions[f"{side}_route_id"] = route_id
            if trip_id:
                if trip_id not in trips:
                    raise ValueError(f"transfers.txt: unknown trip_id {trip_id!r}")
                if route_id and trips[trip_id]["route_id"] != route_id:
                    raise ValueError(f"transfers.txt: {side}_trip_id does not belong to {side}_route_id")
                keep = keep and trip_id in selected_trips
                conditions[f"{side}_trip_id"] = trip_id
        if not keep:
            continue
        transfer = {"from": resolved[0], "to": resolved[1], "type": kind,
                    "source_from_stop_id": source_from, "source_to_stop_id": source_to, **conditions}
        if row.get("min_transfer_time"):
            transfer["min_transfer_time"] = _integer(row["min_transfer_time"], "transfers min_transfer_time")
        elif kind == "2":
            raise ValueError("transfers.txt: transfer_type 2 requires min_transfer_time")
        if derived:
            transfer["endpoints_from_trips"] = True
        transfers.append(transfer)
    if transfers:
        warnings.append("Transfer rules are retained for review, not station merges; type 3 prohibits transfers, and route/trip conditions must be respected.")
    return transfers


def import_gtfs(path, title, route_ids=None, route_types=None, service_date=None):
    """Import every unique ordered pattern in the selected local GTFS slice.

    Both filters, when supplied, must match (intersection). A service date uses
    the feed's service day, including its calendar exceptions. Without a date,
    the output intentionally combines patterns across the whole feed period.
    """
    if not isinstance(title, str) or not title.strip():
        raise ValueError("title must be a non-empty string")
    service_day = _date(service_date, "service_date", iso=True) if service_date is not None else None
    wanted_ids, wanted_types = _selection(route_ids, "route_ids"), _selection(route_types, "route_types")
    warnings = []
    if service_day is None:
        warnings.append("No service_date supplied: this is the feed's combined service-pattern set, not today's operating network.")
    with _open_feed(path) as feed:
        routes = _routes(feed)
        if wanted_ids is not None and wanted_ids - routes.keys():
            raise ValueError(f"Unknown route_id selection: {', '.join(sorted(wanted_ids - routes.keys()))}")
        available_types = {row["route_type"] for row in routes.values()}
        if wanted_types is not None and wanted_types - available_types:
            raise ValueError(f"Unknown route_type selection: {', '.join(sorted(wanted_types - available_types))}")
        selected_routes = {identifier for identifier, row in routes.items()
                           if (wanted_ids is None or identifier in wanted_ids)
                           and (wanted_types is None or row["route_type"] in wanted_types)}
        if not selected_routes:
            raise ValueError("Route selection is empty; route_id and route_type filters must both match")
        trips = _indexed(feed.rows("trips.txt", ("route_id", "service_id", "trip_id")), "trip_id", "trips.txt")
        for trip in trips.values():
            if trip["route_id"] not in routes:
                raise ValueError(f"trip {trip['trip_id']}: unknown route_id {trip['route_id']!r}")
        selected_trips = {identifier: trip for identifier, trip in trips.items() if trip["route_id"] in selected_routes}
        if not selected_trips:
            raise ValueError("No trips for the selected routes; no drawable data")
        for identifier, trip in selected_trips.items():
            if not trip["service_id"]:
                raise ValueError(f"trip {identifier}: empty service_id")
            if trip.get("direction_id", "") not in {"", "0", "1"}:
                raise ValueError(f"trip {identifier}: direction_id must be empty, 0, or 1")
        active = _services(feed, {trip["service_id"] for trip in selected_trips.values()}, service_day, warnings)
        if active is not None:
            selected_trips = {identifier: trip for identifier, trip in selected_trips.items() if trip["service_id"] in active}
        if not selected_trips:
            raise ValueError(f"No active trips on service_date {service_date} for the selected routes; no drawable data")
        stops = _Stops(feed.rows("stops.txt", ("stop_id", "stop_name")), warnings)
        sequences = defaultdict(list)
        non_passenger = set()
        for row in feed.rows("stop_times.txt", ("trip_id", "stop_id", "stop_sequence")):
            trip_id = row["trip_id"]
            if trip_id not in trips:
                raise ValueError(f"stop_times.txt: unknown trip_id {trip_id!r}")
            if trip_id not in selected_trips:
                continue
            sequence = _integer(row["stop_sequence"], f"trip {trip_id} stop_sequence")
            sequences[trip_id].append((sequence, row["stop_id"]))
            pickup, dropoff = row.get("pickup_type", "") or "0", row.get("drop_off_type", "") or "0"
            if pickup not in {"0", "1", "2", "3"} or dropoff not in {"0", "1", "2", "3"}:
                raise ValueError(f"trip {trip_id}: invalid pickup_type/drop_off_type")
            if pickup == dropoff == "1":
                non_passenger.add((trip_id, sequence))
        groups = defaultdict(lambda: defaultdict(list))
        source_ids = defaultdict(set)
        for trip_id, trip in sorted(selected_trips.items()):
            entries = sorted(sequences[trip_id])
            if not entries:
                raise ValueError(f"trip {trip_id}: missing stop_times; no drawable data")
            if len({entry[0] for entry in entries}) != len(entries):
                raise ValueError(f"trip {trip_id}: duplicate stop_sequence")
            sequences[trip_id] = entries
            station_sequence = []
            trip_sources = defaultdict(set)
            for sequence, stop_id in entries:
                canonical = stops.canonical(stop_id)
                if (trip_id, sequence) in non_passenger:
                    continue
                trip_sources[canonical].update((canonical, stop_id))
                if not station_sequence or station_sequence[-1] != canonical:
                    station_sequence.append(canonical)
            if len(set(station_sequence)) < 2:
                warnings.append(f"Trip {trip_id} has fewer than two distinct stations after parent grouping; omitted from the drawable network.")
                continue
            for canonical, originals in trip_sources.items():
                source_ids[canonical].update(originals)
            groups[trip["route_id"]][(trip.get("direction_id", ""), tuple(station_sequence))].append(trip_id)
        if non_passenger:
            warnings.append(f"Excluded {len(non_passenger)} stop-time records allowing neither pickup nor drop-off.")
        output_routes = []
        for identifier in sorted(selected_routes):
            if not groups[identifier]:
                warnings.append(f"Route {identifier} has no drawable patterns in the selected service scope; omitted.")
                continue
            raw = routes[identifier]
            route = {"id": identifier, "name": _route_name(raw), "mode": raw["route_type"], "patterns": []}
            color = raw.get("route_color", "")
            if color:
                if not re.fullmatch(r"[0-9a-fA-F]{6}", color):
                    raise ValueError(f"route {identifier}: route_color must contain six hexadecimal digits")
                route["color"] = "#" + color.upper()
            else:
                warnings.append(f"Route {identifier} has no source color; the layout may assign a display color.")
            for index, ((direction, stations), trip_ids) in enumerate(sorted(groups[identifier].items()), 1):
                route["patterns"].append({"id": f"{identifier}:pattern:{index}", "station_ids": list(stations),
                                          "direction": direction, "trip_count": len(trip_ids),
                                          "source_trip_ids": trip_ids[:TRIP_SAMPLE_LIMIT]})
            if len(route["patterns"]) > 1:
                warnings.append(f"Route {identifier}: preserved {len(route['patterns'])} distinct ordered/direction patterns.")
            output_routes.append(route)
        if not output_routes:
            raise ValueError("No drawable route patterns: at least two distinct stations are required")
        output_stations, names = [], defaultdict(list)
        for identifier, originals in sorted(source_ids.items()):
            raw = stops.rows[identifier]
            name = raw["stop_name"] or identifier
            station = {"id": identifier, "name": name, "source_stop_ids": sorted(originals)}
            coordinate = stops.coordinates(identifier)
            if coordinate is not None:
                station["coordinates"] = coordinate
            else:
                warnings.append(f"Station {identifier} has no source coordinates; a topology-only position is required.")
            if not raw["stop_name"]:
                warnings.append(f"Station {identifier} has no source name; its source ID is used as the label.")
            names[name].append(identifier)
            output_stations.append(station)
        for name, identifiers in sorted(names.items()):
            if len(identifiers) > 1:
                warnings.append(f"Same-name stations remain separate: {name!r} ({', '.join(identifiers)}).")
        transfers = _transfers(feed, stops, set(source_ids), routes, selected_routes, trips, selected_trips, sequences, warnings)
    source = {"kind": "gtfs", "file": Path(path).name, "license": "unknown"}
    if service_date is not None:
        source["service_date"] = service_date
    return {"schema_version": 1, "title": title.strip(), "sources": [source], "stations": output_stations,
            "routes": output_routes, "transfers": transfers, "warnings": warnings}
