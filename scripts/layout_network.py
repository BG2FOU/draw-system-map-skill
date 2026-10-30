#!/usr/bin/env python3
"""Create a deterministic, editable drawing draft from source topology.

This is an initial layout, not a metro-map optimization or a font-aware collision
checker. Geographic coordinates establish approximate direction only. Missing
coordinates select an explicitly nongeographic graph layout for the whole map.
"""
from __future__ import annotations

import copy
import math
import unicodedata
from collections import defaultdict, deque

from network_topology import validate_topology
from draw_map import color, point, render

PALETTE = ("#D8443C", "#247BA0", "#238B57", "#9A55A2", "#D17B14", "#6B6DB4", "#008A91", "#A65F49")


def _object(value, name):
    if not isinstance(value, dict):
        raise ValueError(f"{name}: expected an object")
    return value


def _keys(value, allowed, name):
    _object(value, name)
    unknown = set(value) - set(allowed)
    if unknown:
        raise ValueError(f"{name}: unknown fields {', '.join(sorted(unknown))}")


def _dimension(value, name, minimum):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < minimum:
        raise ValueError(f"{name}: expected a finite number >= {minimum}")
    return value


def _fit(raw, frame):
    left, top, right, bottom = frame
    xs, ys = zip(*raw.values())
    dx, dy = max(xs) - min(xs), max(ys) - min(ys)
    scale = min((right - left) / dx if dx else float("inf"),
                (bottom - top) / dy if dy else float("inf"))
    if not math.isfinite(scale):
        scale = 1
    # A schematic may stretch a narrow geographic extent to use the page better.
    sx = min((right - left) / dx, scale * 2.5) if dx else scale
    sy = min((bottom - top) / dy, scale * 2.5) if dy else scale
    cx, cy = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
    return {sid: [round((x - cx) * sx + (left + right) / 2, 4),
                  round((y - cy) * sy + (top + bottom) / 2, 4)]
            for sid, (x, y) in raw.items()}


def _geographic(stations):
    # Unwrap at the largest empty longitude interval, including the date line.
    longitudes = sorted({s["coordinates"][0] % 360 for s in stations})
    gaps = [(longitudes[(i + 1) % len(longitudes)] + (360 if i == len(longitudes) - 1 else 0)
             - longitude, i) for i, longitude in enumerate(longitudes)]
    _, gap_index = max(gaps)
    start = longitudes[(gap_index + 1) % len(longitudes)]
    mean_lat = sum(s["coordinates"][1] for s in stations) / len(stations)
    longitude_scale = max(abs(math.cos(math.radians(mean_lat))), 1e-6)
    return {s["id"]: (((s["coordinates"][0] % 360 - start) % 360) * longitude_scale,
                      -s["coordinates"][1]) for s in stations}


def _topological(adjacency):
    remaining, components = set(adjacency), []
    while remaining:
        first = min(remaining)
        connected, pending = {first}, [first]
        while pending:
            for neighbor in sorted(adjacency[pending.pop()]):
                if neighbor not in connected:
                    connected.add(neighbor)
                    pending.append(neighbor)
        remaining -= connected
        root = min(connected, key=lambda sid: (-len(adjacency[sid]), sid))
        depths, queue = {root: 0}, deque([root])
        while queue:
            sid = queue.popleft()
            for neighbor in sorted(adjacency[sid]):
                if neighbor not in depths:
                    depths[neighbor] = depths[sid] + 1
                    queue.append(neighbor)
        layers = defaultdict(list)
        for sid in sorted(connected):
            layers[depths[sid]].append(sid)
        raw, previous = {}, {}
        for depth in sorted(layers):
            def rank(sid):
                parent_rows = [previous[n] for n in adjacency[sid] if n in previous]
                return (sum(parent_rows) / len(parent_rows) if parent_rows else 0, sid)
            layer = sorted(layers[depth], key=rank)
            for row, sid in enumerate(layer):
                y = row - (len(layer) - 1) / 2
                raw[sid] = (depth * 120, y * 80)
                previous[sid] = y
        min_y = min(y for _, y in raw.values())
        components.append({sid: (x, y - min_y) for sid, (x, y) in raw.items()})
    # Independent components occupy separate cells; isolated stations remain visible.
    cols = math.ceil(math.sqrt(len(components)))
    cell_width = max(max(x for x, _ in part.values()) for part in components) + 160
    cell_height = max(max(y for _, y in part.values()) for part in components) + 160
    return {sid: (x + (index % cols) * cell_width, y + (index // cols) * cell_height)
            for index, part in enumerate(components) for sid, (x, y) in part.items()}


def _separate_equal_points(positions, frame):
    """Keep different station identities drawable when source coordinates coincide."""
    left, top, right, bottom = frame
    occupied, shifted = set(), []
    for sid in sorted(positions):
        original = tuple(positions[sid])
        candidate = original
        attempt = 0
        while candidate in occupied:
            angle = (attempt % 8) * math.pi / 4
            radius = (attempt // 8 + 1) * 18
            candidate = (round(min(right, max(left, original[0] + math.cos(angle) * radius)), 4),
                         round(min(bottom, max(top, original[1] + math.sin(angle) * radius)), 4))
            attempt += 1
            if attempt > 8 * (len(positions) + 1):
                raise ValueError("Unable to separate coincident stations in this canvas; enlarge canvas")
        occupied.add(candidate)
        positions[sid] = list(candidate)
        if candidate != original:
            shifted.append({"station_id": sid, "original_point": list(original), "point": list(candidate)})
    return shifted


def _spread_dense_points(positions, frame):
    """Separate dense schematic markers while keeping a weak geographic anchor."""
    original = copy.deepcopy(positions)
    ids = sorted(positions)
    for _ in range(100):
        movement = {sid: [0., 0.] for sid in ids}
        for i, sid in enumerate(ids):
            for other in ids[i + 1:]:
                dx, dy = positions[sid][0] - positions[other][0], positions[sid][1] - positions[other][1]
                distance = math.hypot(dx, dy)
                if distance < 64:
                    if distance < .001:
                        dx, dy, distance = 1., 0., 1.
                    force = (64 - distance) * .26
                    for axis, delta in enumerate((dx, dy)):
                        movement[sid][axis] += delta / distance * force
                        movement[other][axis] -= delta / distance * force
        for sid in ids:
            for axis in (0, 1):
                step = movement[sid][axis] + (original[sid][axis] - positions[sid][axis]) * .015
                positions[sid][axis] = max(frame[axis], min(frame[axis + 2], positions[sid][axis] + step))
    for sid in ids:
        positions[sid] = [round(value, 4) for value in positions[sid]]
    return [{"station_id": sid, "distance": round(math.dist(original[sid], positions[sid]), 2)}
            for sid in ids if math.dist(original[sid], positions[sid]) > 1]


def _offset_shared_tracks(drawing_routes, positions, edge_routes, route_overrides):
    count = 0
    for route in drawing_routes:
        if "segments" in route_overrides.get(route["id"], {}):
            continue  # User geometry always wins.
        for segment in route["segments"]:
            stations = segment["points"]
            points = []
            pairs = list(zip(stations, stations[1:]))
            if segment.get("closed"):
                pairs.append((stations[-1], stations[0]))
            for a, b in pairs:
                points.append(a)
                key = tuple(sorted((a, b)))
                members = sorted(edge_routes[key])
                if len(members) < 2:
                    continue
                start, end = positions[key[0]], positions[key[1]]
                dx, dy = end[0] - start[0], end[1] - start[1]
                distance = math.hypot(dx, dy)
                if not distance:
                    continue
                offset = (members.index(route["id"]) - (len(members) - 1) / 2) * 11
                if offset:
                    x, y = positions[a]; bx, by = positions[b]
                    for fraction in (.22, .78):
                        points.append([round(x + (bx-x)*fraction - dy/distance*offset, 4),
                                       round(y + (by-y)*fraction + dx/distance*offset, 4)])
                    count += 1
            if not segment.get("closed"):
                points.append(stations[-1])
            segment["points"] = points
    return count


def _text_width(value, size):
    return max(size * .6, sum(0 if unicodedata.combining(c) else
                             1 if unicodedata.east_asian_width(c) in "WF" else .58
                             for c in value) * size)


def _label_box(station, position, label):
    x, y = position[0] + label["offset"][0], position[1] + label["offset"][1]
    width = max(_text_width(station["name"], 17), _text_width(station.get("secondary_name", ""), 12))
    x -= width * {"start": 0, "middle": .5, "end": 1}[label.get("anchor", "start")]
    return (x, y - 15, x + width, y + (20 if station.get("secondary_name") else 4))


def _overlap(a, b):
    return max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))


def _line_box(a, b, box):
    """Segment/rectangle intersection used only as an approximate layout warning."""
    lo, hi = 0., 1.
    dx, dy = b[0] - a[0], b[1] - a[1]
    for p, q in ((-dx, a[0] - box[0]), (dx, box[2] - a[0]),
                 (-dy, a[1] - box[1]), (dy, box[3] - a[1])):
        if p == 0:
            if q < 0:
                return False
        else:
            t = q / p
            if p < 0:
                lo = max(lo, t)
            else:
                hi = min(hi, t)
            if lo > hi:
                return False
    return True


def _segments(route, override):
    segments, patterns, seen = [], [], {}
    for pattern in sorted(route["patterns"], key=lambda p: p["id"]):
        sequence = pattern["station_ids"]
        if any(a == b for a, b in zip(sequence, sequence[1:])):
            raise ValueError(f"Route {route['id']}, pattern {pattern['id']}: consecutive identical stations cannot be drawn")
        key = min(tuple(sequence), tuple(reversed(sequence)))
        if key not in seen:
            closed = sequence[0] == sequence[-1] and len(set(sequence)) >= 3
            seen[key] = len(segments)
            segments.append({"points": list(sequence[:-1] if closed else sequence), **({"closed": True} if closed else {})})
        patterns.append({"pattern_id": pattern["id"], "segment_index": seen[key]})
    if "segments" in override:
        supplied = override["segments"]
        if not isinstance(supplied, list) or len(supplied) != len(segments):
            raise ValueError(f"routes.{route['id']}.segments: retain exactly {len(segments)} displayed segments")
        for index, (original, replacement) in enumerate(zip(segments, supplied)):
            where = f"routes.{route['id']}.segments[{index}]"
            _keys(replacement, {"points", "closed"}, where)
            vertices = replacement.get("points")
            if not isinstance(vertices, list):
                raise ValueError(f"{where}.points: expected an array")
            if [v for v in vertices if isinstance(v, str)] != original["points"]:
                raise ValueError(f"{where}: station order must remain unchanged; only insert coordinate waypoints")
            closed = replacement.get("closed", False)
            if not isinstance(closed, bool) or closed != original.get("closed", False):
                raise ValueError(f"{where}.closed: retain the generated loop setting")
            for vertex in vertices:
                if not isinstance(vertex, str):
                    point(vertex, where)
        segments = copy.deepcopy(supplied)
    return segments, patterns


def layout(topology, overrides=None):
    """Return (draw_map v1 network, draft diagnostics), without changing inputs."""
    data = validate_topology(copy.deepcopy(topology))
    overrides = copy.deepcopy(overrides) if overrides is not None else {}
    _keys(overrides, {"canvas", "stations", "routes"}, "overrides")
    stations = sorted(data["stations"], key=lambda s: s["id"])
    routes = sorted(data["routes"], key=lambda r: r["id"])
    if not stations or not routes:
        raise ValueError("Layout requires at least one station and one route")
    by_id = {s["id"]: s for s in stations}
    station_overrides, route_overrides = overrides.get("stations", {}), overrides.get("routes", {})
    for value, ids, name in ((station_overrides, set(by_id), "stations"),
                             (route_overrides, {r["id"] for r in routes}, "routes")):
        _object(value, name)
        unknown = set(value) - ids
        if unknown:
            raise ValueError(f"{name}: unknown IDs {', '.join(sorted(unknown))}")
    canvas_overrides = overrides.get("canvas", {})
    _keys(canvas_overrides, {"width", "height", "background"}, "canvas")
    canvas = {"width": max(1400, math.ceil((math.sqrt(len(stations)) * 210 + 400) / 50) * 50),
              "height": max(950, math.ceil((math.sqrt(len(stations)) * 185 + 300) / 50) * 50, len(routes) * 40 + 230),
              "background": "#ffffff", **canvas_overrides}
    width, height = _dimension(canvas["width"], "canvas.width", 800), _dimension(canvas["height"], "canvas.height", max(600, len(routes) * 40 + 230))
    color(canvas["background"])
    frame = (90, 145, width - 370, height - 130)
    label_frame = (32, 100, width - 310, height - 80)
    adjacency, membership, edge_routes = {sid: set() for sid in by_id}, defaultdict(set), defaultdict(set)
    for route in routes:
        for pattern in route["patterns"]:
            for sid in pattern["station_ids"]:
                membership[sid].add(route["id"])
            for a, b in zip(pattern["station_ids"], pattern["station_ids"][1:]):
                adjacency[a].add(b)
                adjacency[b].add(a)
                edge_routes[tuple(sorted((a, b)))].add(route["id"])
    geographic = all(s.get("coordinates") is not None for s in stations)
    method = "geographic" if geographic else "topological"
    positions = _fit(_geographic(stations) if geographic else _topological(adjacency), frame)
    shifted = _separate_equal_points(positions, frame)
    spread = _spread_dense_points(positions, frame) if geographic else []
    warnings = list(data.get("warnings", []))
    if not geographic:
        warnings.append("Some stations lack coordinates: the entire map uses a nongeographic topological draft.")
    if spread:
        warnings.append("Dense station positions were spread for readability; this schematic is not to geographic scale.")
    if shifted:
        warnings.append("Coincident source positions were separated for drawing; station identities were kept distinct.")
    if data.get("transfers"):
        warnings.append("Separate-station transfer records remain in topology; this draft does not draw walking-transfer links or merge their identities.")
    labels = {}
    for sid, entry in station_overrides.items():
        _keys(entry, {"point", "label"}, f"stations.{sid}")
        if "point" in entry:
            positions[sid] = list(point(entry["point"], f"stations.{sid}.point"))
        if "label" in entry:
            label = entry["label"]
            _keys(label, {"offset", "anchor"}, f"stations.{sid}.label")
            offset = list(point(label.get("offset", [14, -12]), f"stations.{sid}.label.offset"))
            align = label.get("anchor", "start")
            if align not in ("start", "middle", "end"):
                raise ValueError(f"stations.{sid}.label.anchor: use start/middle/end")
            labels[sid] = {"offset": offset, "anchor": align}
    drawing_routes, pattern_map, fallback_colors = [], {}, []
    for index, route in enumerate(routes):
        entry = route_overrides.get(route["id"], {})
        _keys(entry, {"color", "segments"}, f"routes.{route['id']}")
        stroke = entry.get("color", route.get("color"))
        if not stroke:
            stroke = PALETTE[index % len(PALETTE)]
            fallback_colors.append({"route_id": route["id"], "color": stroke})
        color(stroke)
        segments, pattern_map[route["id"]] = _segments(route, entry)
        drawing_routes.append({"id": route["id"], "name": route["name"], "color": stroke,
                               "mode": route.get("mode", ""), "segments": segments})
    if fallback_colors:
        warnings.append("Some routes have no source color: fallback palette colors are drawing choices, not official colors.")
    offset_count = _offset_shared_tracks(drawing_routes, positions, edge_routes, route_overrides)
    lines = []
    for route in drawing_routes:
        for segment in route["segments"]:
            vertices = [positions[v] if isinstance(v, str) else v for v in segment["points"]]
            if segment.get("closed"):
                vertices = [*vertices, vertices[0]]
            if any(tuple(a) == tuple(b) for a, b in zip(vertices, vertices[1:])):
                raise ValueError(f"Route {route['id']}: consecutive drawing points coincide; adjust station or waypoint overrides")
            lines.extend((a, b, route["id"]) for a, b in zip(vertices, vertices[1:]))
    marker_boxes = {sid: (p[0] - (18 if len(membership[sid]) > 1 else 7), p[1] - (18 if len(membership[sid]) > 1 else 7),
                          p[0] + (18 if len(membership[sid]) > 1 else 7), p[1] + (18 if len(membership[sid]) > 1 else 7))
                    for sid, p in positions.items()}
    boxes = {sid: _label_box(by_id[sid], positions[sid], label) for sid, label in labels.items()}
    candidates = [([16, -12], "start"), ([18, 5], "start"), ([16, 27], "start"), ([0, 33], "middle"),
                  ([-16, 27], "end"), ([-18, 5], "end"), ([-16, -12], "end"), ([0, -24], "middle"),
                  ([16, -40], "start"), ([-16, -40], "end"), ([16, 50], "start"), ([-16, 50], "end")]
    for sid in sorted(by_id, key=lambda s: (-len(membership[s]), -len(adjacency[s]), s)):
        if sid in labels:
            continue
        options = []
        for index, (offset, align) in enumerate(candidates):
            label = {"offset": list(offset), "anchor": align}
            box = _label_box(by_id[sid], positions[sid], label)
            area = (box[2] - box[0]) * (box[3] - box[1])
            outside = area - _overlap(box, label_frame)
            score = outside * 20 + sum(_overlap(box, other) * 3 for other in boxes.values())
            score += sum(1000 + _overlap(box, other) * 5 for other in marker_boxes.values() if _overlap(box, other))
            score += sum(250 for a, b, _ in lines if _line_box(a, b, box))
            options.append((score, index, label, box))
        _, _, labels[sid], boxes[sid] = min(options, key=lambda option: option[:2])
    label_conflicts, near_stations, outside_labels = [], [], []
    station_ids = sorted(by_id)
    for i, sid in enumerate(station_ids):
        box = boxes[sid]
        if box[0] < label_frame[0] or box[1] < label_frame[1] or box[2] > label_frame[2] or box[3] > label_frame[3]:
            outside_labels.append(sid)
        for other in station_ids[i + 1:]:
            if _overlap(box, boxes[other]):
                label_conflicts.append({"station_ids": [sid, other]})
            distance = math.dist(positions[sid], positions[other])
            threshold = (18 if len(membership[sid]) > 1 else 7) + (18 if len(membership[other]) > 1 else 7) + 8
            if distance < threshold:
                near_stations.append({"station_ids": [sid, other], "distance": round(distance, 2)})
    station_label_conflicts = [{"label_station_id": sid, "marker_station_id": other}
                               for sid in station_ids for other in station_ids if _overlap(boxes[sid], marker_boxes[other])]
    route_label_conflicts = [{"station_id": sid, "route_ids": sorted({rid for a, b, rid in lines if _line_box(a, b, boxes[sid])})}
                             for sid in station_ids]
    route_label_conflicts = [row for row in route_label_conflicts if row["route_ids"]]
    shared_edges = [{"station_ids": list(edge), "route_ids": sorted(ids)} for edge, ids in sorted(edge_routes.items()) if len(ids) > 1]
    warnings.append("Automatic draft only. Label estimates do not measure installed fonts, curve shapes or all collisions; inspect the rendered map.")
    if shared_edges:
        warnings.append("Shared-edge lanes were separated where possible; inspect junctions, curves and any manually overridden tracks.")
    network = {"version": 1, "title": data["title"],
               "subtitle": f"Automatic {'geographic' if geographic else 'nongeographic topological'} draft · visual review required",
               "canvas": canvas, "style": {"label_size": 17, "secondary_size": 12},
               "stations": [{"id": s["id"], "name": s["name"], "point": positions[s["id"]], "label": labels[s["id"]],
                             **({"secondary_name": s["secondary_name"]} if s.get("secondary_name") else {})} for s in stations],
               "routes": drawing_routes, "legend": {"point": [width - 280, 110], "width": 250, "title": "Lines"},
               "annotations": [{"point": [32, height - 30], "text": "Automatic draft: review station identities, shared tracks and labels.", "size": 12}],
               "source_metadata": copy.deepcopy(data.get("sources", []))}
    attributions = list(dict.fromkeys(source["attribution"] for source in data.get("sources", [])
                                     if isinstance(source, dict) and isinstance(source.get("attribution"), str) and source["attribution"].strip()))
    if fallback_colors:
        network["annotations"].append({"point": [32, height - 72], "text": "Some route colors are draft choices; source colors were unavailable.", "size": 12})
    if attributions:
        attribution = " · ".join(attributions)
        network["annotations"].append({"point": [32, height - 52], "text": attribution, "size": 12})
        if _text_width(attribution, 12) > width - 64:
            warnings.append("Source attribution exceeds the estimated footer width; adjust its layout before publication.")
    # Use the actual renderer contract as the last gate, without emitting a file.
    render(network)
    report = {"status": "draft_needs_visual_review", "method": method, "geographic": geographic,
              "station_count": len(stations), "route_count": len(routes), "pattern_segments": pattern_map,
              "fallback_colors": fallback_colors, "automatically_shifted_stations": shifted,
              "density_adjustments": spread, "offset_shared_segments": offset_count,
              "near_stations": near_stations, "estimated_label_conflicts": label_conflicts,
              "estimated_label_station_conflicts": station_label_conflicts,
              "estimated_label_route_conflicts": route_label_conflicts, "labels_outside_plot": outside_labels,
              "stations_outside_canvas": [sid for sid, p in positions.items() if not (0 <= p[0] <= width and 0 <= p[1] <= height)],
              "shared_edges": shared_edges, "warnings": warnings}
    return network, report
