#!/usr/bin/env python3
"""Generate editable schematic SVG from portable JSON; Python standard library only."""
from __future__ import annotations

import argparse
import html
import json
import math
import re
import sys
from pathlib import Path


class MapError(ValueError):
    pass


def number(value, where, minimum=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise MapError(f"{where}: expected a finite number")
    if minimum is not None and value < minimum:
        raise MapError(f"{where}: must be >= {minimum}")
    return value


def point(value, where):
    if not isinstance(value, list) or len(value) != 2:
        raise MapError(f"{where}: expected [x, y]")
    return tuple(number(v, where) for v in value)


def text(value, where, empty=False):
    if not isinstance(value, str) or (not empty and not value.strip()):
        raise MapError(f"{where}: expected {'a' if empty else 'a nonempty'} string")
    return value


def obj(value, where):
    if not isinstance(value, dict):
        raise MapError(f"{where}: expected an object")
    return value


def array(value, where):
    if not isinstance(value, list):
        raise MapError(f"{where}: expected an array")
    return value


def color(value):
    if not isinstance(value, str) or not re.fullmatch(r"(?:#[0-9a-fA-F]{3}|#[0-9a-fA-F]{6}|[a-zA-Z]+)", value):
        raise MapError(f"Invalid color {value!r}; use #RGB, #RRGGBB or a CSS color name")
    return value


def pattern(value):
    if value not in ("solid", "hollow", "dashed"):
        raise MapError(f"Unknown pattern {value!r}; use solid, hollow or dashed")
    return value


def anchor(value):
    if value not in ("start", "middle", "end"):
        raise MapError(f"Invalid text anchor {value!r}")
    return value


def fmt(value):
    return f"{value:.4f}".rstrip("0").rstrip(".") if value else "0"


def esc(value):
    return html.escape(str(value), quote=True)


def xy(p):
    return f"{fmt(p[0])} {fmt(p[1])}"


def rounded_path(points, station_flags, radius, closed=False):
    """Round waypoint corners with tangent circular arcs; station coordinates stay exact."""
    if closed and points[-1] != points[0]:
        points = [*points, points[0]]
        station_flags = [*station_flags, station_flags[0]]
    commands = [f"M{xy(points[0])}"]
    for i in range(1, len(points) - 1):
        a, p, b = points[i - 1:i + 2]
        u, v = (p[0] - a[0], p[1] - a[1]), (b[0] - p[0], b[1] - p[1])
        la, lb = math.hypot(*u), math.hypot(*v)
        if station_flags[i] or not radius or not la or not lb:
            commands.append(f"L{xy(p)}")
            continue
        u, v = (u[0] / la, u[1] / la), (v[0] / lb, v[1] / lb)
        turn = math.acos(max(-1, min(1, u[0] * v[0] + u[1] * v[1])))
        if turn < 1e-6 or math.pi - turn < 1e-6:
            commands.append(f"L{xy(p)}")
            continue
        trim = min(radius * math.tan(turn / 2), la * .45, lb * .45)
        r = trim / math.tan(turn / 2)
        entry = (p[0] - u[0] * trim, p[1] - u[1] * trim)
        end = (p[0] + v[0] * trim, p[1] + v[1] * trim)
        sweep = int(u[0] * v[1] - u[1] * v[0] > 0)
        commands.extend([f"L{xy(entry)}", f"A{fmt(r)} {fmt(r)} 0 0 {sweep} {xy(end)}"])
    commands.append(f"L{xy(points[-1])}")
    if closed:
        commands.append("Z")
    return " ".join(commands)


def track_layers(d, stroke, width, style, inner_color):
    dash = ' stroke-dasharray="12 8"' if style == "dashed" else ""
    outer = f'<path d="{d}" fill="none" stroke="{esc(stroke)}" stroke-width="{fmt(width)}" stroke-linecap="round" stroke-linejoin="round"{dash}/>'
    inner = ""
    if style == "hollow":
        inner = f'<path d="{d}" fill="none" stroke="{esc(inner_color)}" stroke-width="{fmt(width * .48)}" stroke-linecap="round" stroke-linejoin="round"/>'
    return outer, inner


def track(d, stroke, width, style, inner_color):
    return "".join(track_layers(d, stroke, width, style, inner_color))


def marker(colors, radius, reserved, interchange_style, background, reserved_color):
    colors = [reserved_color for _ in colors] if reserved else colors
    if len(colors) <= 1:
        dash = ' stroke-dasharray="3 2"' if reserved else ""
        return f'<circle r="{fmt(radius)}" fill="{background}" stroke="{colors[0] if colors else reserved_color}" stroke-width="2.5"{dash}/>'
    parts = [f'<circle r="{fmt(radius + 5)}" fill="{background}"/>']
    for i, stroke in enumerate(colors):
        if interchange_style == "ring":
            a, b = i * math.tau / len(colors) - math.pi / 2, (i + 1) * math.tau / len(colors) - math.pi / 2
            start, end = (radius * math.cos(a), radius * math.sin(a)), (radius * math.cos(b), radius * math.sin(b))
            parts.append(f'<path class="transfer-ring" d="M{xy(start)} A{fmt(radius)} {fmt(radius)} 0 0 1 {xy(end)}" fill="none" stroke="{stroke}" stroke-width="3.5"/>')
        else:
            center = -math.pi / 2 + i * math.tau / len(colors)
            sweep = math.radians(120) if len(colors) == 2 else math.tau / len(colors) * .7
            a, b = center + sweep / 2, center - sweep / 2
            start, end = (radius * math.cos(a), radius * math.sin(a)), (radius * math.cos(b), radius * math.sin(b))
            tangent = (math.sin(b), -math.cos(b))
            normal = (-tangent[1], tangent[0])
            tip = (end[0] + tangent[0] * 3.5, end[1] + tangent[1] * 3.5)
            base = (end[0] - tangent[0] * 3, end[1] - tangent[1] * 3)
            left = (base[0] + normal[0] * 3.5, base[1] + normal[1] * 3.5)
            right = (base[0] - normal[0] * 3.5, base[1] - normal[1] * 3.5)
            parts.append(f'<path class="transfer-arrow" d="M{xy(start)} A{fmt(radius)} {fmt(radius)} 0 0 0 {xy(end)}" fill="none" stroke="{stroke}" stroke-width="3.5" stroke-linecap="round"/>')
            parts.append(f'<path class="transfer-head" d="M{xy(tip)} L{xy(left)} L{xy(right)} Z" fill="{stroke}"/>')
    return "".join(parts)


def resolved_pattern(item, mappings, fallback):
    if "pattern" in item:
        return pattern(item["pattern"])
    if "structure" in item:
        structure = text(item["structure"], "structure")
        if structure not in mappings:
            raise MapError(f"No pattern for structure {structure!r}; configure structure_patterns or an explicit pattern")
        return mappings[structure]
    return fallback


def render(data):
    obj(data, "network")
    if data.get("version") != 1 or isinstance(data.get("version"), bool):
        raise MapError("version: expected 1")
    canvas = obj(data.get("canvas", {}), "canvas")
    width = number(canvas.get("width", 1200), "canvas.width", 1)
    height = number(canvas.get("height", 900), "canvas.height", 1)
    background = color(canvas.get("background", "#ffffff"))
    style = obj(data.get("style", {}), "style")
    font = text(style.get("font_family", "Noto Sans CJK SC, Microsoft YaHei, sans-serif"), "font_family")
    route_width = number(style.get("route_width", 8), "route_width", .1)
    radius = number(style.get("corner_radius", 24), "corner_radius", 0)
    label_size = number(style.get("label_size", 17), "label_size", 1)
    secondary_size = number(style.get("secondary_size", 12), "secondary_size", 1)
    text_color = color(style.get("text_color", "#243746"))
    inner_color = color(style.get("hollow_fill", "#ffffff"))
    interchange_style = style.get("interchange_style", "arrows")
    if interchange_style not in ("arrows", "ring"):
        raise MapError("interchange_style: use arrows or ring")
    interchange_radius = number(style.get("interchange_radius", 12.5), "interchange_radius", 1)
    reserved_color = color(style.get("reserved_color", "#858b91"))
    structure_patterns = {"underground": "solid", "surface": "hollow", "elevated": "hollow"}
    structure_patterns.update(obj(style.get("structure_patterns", {}), "structure_patterns"))
    structure_patterns = {k: pattern(v) for k, v in structure_patterns.items()}
    stations, members = {}, {}
    for row in array(data.get("stations"), "stations"):
        s = obj(row, "station")
        sid = text(s.get("id"), "station.id")
        if sid in stations:
            raise MapError(f"Duplicate station ID: {sid}")
        text(s.get("name"), f"{sid}.name")
        if "secondary_name" in s:
            text(s["secondary_name"], f"{sid}.secondary_name", empty=True)
        point(s.get("point"), f"{sid}.point")
        if s.get("status", "open") not in ("open", "reserved", "unopened"):
            raise MapError(f"{sid}.status: use open, reserved or unopened")
        stations[sid], members[sid] = s, []
    routes, seen = [], set()
    for row in array(data.get("routes"), "routes"):
        route = obj(row, "route")
        rid = text(route.get("id"), "route.id")
        if rid in seen:
            raise MapError(f"Duplicate route ID: {rid}")
        seen.add(rid)
        name = text(route.get("name"), f"{rid}.name")
        stroke = color(route.get("color", "#2563eb"))
        mappings = {**structure_patterns, **obj(route.get("structure_patterns", {}), f"{rid}.structure_patterns")}
        mappings = {k: pattern(v) for k, v in mappings.items()}
        default_pattern = resolved_pattern(route, mappings, "solid")
        size = number(route.get("width", route_width), f"{rid}.width", .1)
        route_radius = number(route.get("corner_radius", radius), f"{rid}.corner_radius", 0)
        segments = array(route.get("segments"), f"{rid}.segments")
        if not segments:
            raise MapError(f"{rid}: needs at least one segment")
        outlines, cores = [], []
        for index, segment in enumerate(segments):
            obj(segment, f"{rid}.segment")
            vertices = array(segment.get("points"), f"{rid}.points")
            if len(vertices) < 2:
                raise MapError(f"{rid}: a segment needs at least two points")
            points, flags = [], []
            for vertex in vertices:
                if isinstance(vertex, str):
                    if vertex not in stations:
                        raise MapError(f"{rid}: unknown station ID {vertex!r}")
                    points.append(point(stations[vertex]["point"], vertex))
                    flags.append(True)
                    if rid not in [r[0] for r in members[vertex]]:
                        members[vertex].append((rid, stroke))
                else:
                    points.append(point(vertex, rid))
                    flags.append(False)
            if any(a == b for a, b in zip(points, points[1:])):
                raise MapError(f"{rid}: consecutive identical points; remove the duplicate")
            closed = segment.get("closed", False)
            if not isinstance(closed, bool):
                raise MapError(f"{rid}.closed: expected true or false")
            if closed and len(set(points)) < 3:
                raise MapError(f"{rid}: a closed segment needs at least three distinct points")
            d = rounded_path(points, flags, route_radius, closed)
            structure = text(segment.get("structure", route.get("structure", "unspecified")), "structure")
            outer, inner = track_layers(d, stroke, size, resolved_pattern(segment, mappings, default_pattern), inner_color)
            group = f'<g data-segment="{index}" data-structure="{esc(structure)}">'
            outlines.append(f'{group}{outer}</g>')
            if inner:
                cores.append(f'{group}{inner}</g>')
        # Paint every outline before any core so shared round caps cannot occlude
        # another segment's hollow interior when the route direction is reversed.
        paths = f'<g data-track-layer="outline">{"".join(outlines)}</g><g data-track-layer="core">{"".join(cores)}</g>'
        routes.append((rid, name, stroke, size, default_pattern, paths, str(route.get("mode", ""))))

    title = text(data.get("title", "Network map"), "title")
    subtitle = text(data.get("subtitle", ""), "subtitle", empty=True)
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{fmt(width)}" height="{fmt(height)}" viewBox="0 0 {fmt(width)} {fmt(height)}" role="img" aria-labelledby="map-title">',
             f'<title id="map-title">{esc(title)}</title>',
             '<desc>Schematic network; positions do not imply geographic scale. Editable vector paths and text.</desc>',
             f'<rect width="{fmt(width)}" height="{fmt(height)}" fill="{background}"/>',
             f'<g font-family="{esc(font)}" fill="{text_color}">', '<g id="regions">']
    for region in array(data.get("regions", []), "regions"):
        obj(region, "region")
        points = [point(p, "region.points") for p in array(region.get("points"), "region.points")]
        if len(points) < 3:
            raise MapError("region.points: at least three points required")
        parts.append(f'<polygon points="{" ".join(xy(p) for p in points)}" fill="{color(region.get("fill", "#e8f1f5"))}"/>')
    parts.append('</g><g id="routes">')
    for rid, name, stroke, size, route_pattern, paths, mode in routes:
        parts.append(f'<g data-route="{esc(rid)}" data-mode="{esc(mode)}"><title>{esc(name)}</title>{paths}</g>')
    parts.append('</g><g id="stations">')
    for sid, s in stations.items():
        x, y = point(s["point"], sid)
        order = array(s.get("transfer_order", [item[0] for item in members[sid]]), f"{sid}.transfer_order")
        if not all(isinstance(item, str) for item in order) or len(order) != len(members[sid]) or set(order) != {item[0] for item in members[sid]}:
            raise MapError(f"{sid}.transfer_order must contain each serving route ID exactly once")
        palette = dict(members[sid])
        line_colors = [palette[rid] for rid in order]
        r = number(s.get("radius", interchange_radius if len(line_colors) > 1 else 5.5), f"{sid}.radius", .1)
        reserved = s.get("status", "open") != "open"
        parts.append(f'<g data-station="{esc(sid)}" data-status="{esc(s.get("status", "open"))}" transform="translate({fmt(x)} {fmt(y)})"><title>{esc(s["name"])}</title>')
        parts.append(marker(line_colors or [text_color], r, reserved, interchange_style, background, reserved_color))
        parts.append('</g>')
    parts.append('</g><g id="labels">')
    for sid, s in stations.items():
        layout = obj(s.get("label", {}), f"{sid}.label")
        dx, dy = point(layout.get("offset", [14, -12]), f"{sid}.label.offset")
        x, y = s["point"][0] + dx, s["point"][1] + dy
        align = anchor(layout.get("anchor", "start"))
        reserved_attrs = f' fill="{reserved_color}" opacity="0.65"' if s.get("status", "open") != "open" else ""
        parts.append(f'<text data-label="{esc(sid)}" x="{fmt(x)}" y="{fmt(y)}" text-anchor="{align}" font-size="{fmt(label_size)}"{reserved_attrs}><tspan x="{fmt(x)}">{esc(s["name"])}</tspan>')
        if s.get("secondary_name"):
            parts.append(f'<tspan x="{fmt(x)}" dy="{fmt(secondary_size + 4)}" font-size="{fmt(secondary_size)}">{esc(s["secondary_name"])}</tspan>')
        parts.append('</text>')
    parts.append('</g><g id="heading">')
    parts.append(f'<text x="32" y="48" font-size="30" font-weight="700">{esc(title)}</text>')
    if subtitle:
        parts.append(f'<text x="32" y="77" font-size="16">{esc(subtitle)}</text>')
    parts.append('</g>')
    if "legend" in data:
        legend = obj(data["legend"], "legend")
        lx, ly = point(legend.get("point", [width - 240, 110]), "legend.point")
        lw = number(legend.get("width", 210), "legend.width", 1)
        extra_items = array(legend.get("items", []), "legend.items")
        parts.append(f'<g id="legend" transform="translate({fmt(lx)} {fmt(ly)})"><rect width="{fmt(lw)}" height="{(len(routes) + len(extra_items)) * 40 + 52}" rx="8" fill="{background}" stroke="#cbd5e1"/>')
        parts.append(f'<text x="16" y="27" font-size="17">{esc(text(legend.get("title", "Legend"), "legend.title"))}</text>')
        for i, (_, name, stroke, size, route_pattern, _, _) in enumerate(routes):
            y = 50 + i * 40
            parts.append(track(f"M16 {y} H62", stroke, size, route_pattern, inner_color))
            parts.append(f'<text x="76" y="{y + 5}" font-size="14">{esc(name)}</text>')
        for i, item in enumerate(extra_items):
            obj(item, "legend.item")
            name = text(item.get("name"), "legend.item.name")
            y = 50 + (len(routes) + i) * 40
            symbol = item.get("symbol", "line")
            if symbol == "line":
                parts.append(track(f"M16 {y} H62", color(item.get("color", "#64748b")), route_width, resolved_pattern(item, structure_patterns, "solid"), inner_color))
            elif symbol in ("station", "interchange", "reserved"):
                palette = [color(c) for c in array(item.get("colors", ["#D8443C", "#247BA0"] if symbol == "interchange" else ["#64748b"]), "legend.item.colors")]
                if symbol == "interchange" and len(palette) < 2:
                    raise MapError("interchange legend item needs at least two colors")
                content = marker(palette, interchange_radius if symbol == "interchange" else 5.5, symbol == "reserved", interchange_style, background, reserved_color)
                parts.append(f'<g transform="translate(39 {y})">{content}</g>')
            else:
                raise MapError(f"Unknown legend symbol: {symbol!r}")
            parts.append(f'<text x="76" y="{y + 5}" font-size="14">{esc(name)}</text>')
        parts.append('</g>')
    parts.append('<g id="annotations">')
    for note in array(data.get("annotations", []), "annotations"):
        obj(note, "annotation")
        x, y = point(note.get("point"), "annotation.point")
        size = number(note.get("size", 14), "annotation.size", 1)
        parts.append(f'<text x="{fmt(x)}" y="{fmt(y)}" font-size="{fmt(size)}" text-anchor="{anchor(note.get("anchor", "start"))}">{esc(text(note.get("text"), "annotation.text"))}</text>')
    parts.append('</g></g></svg>')
    return "\n".join(parts) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="network JSON")
    parser.add_argument("--output", "-o", type=Path, required=True, help="editable .svg output")
    parser.add_argument("--check", action="store_true", help="compare existing SVG without writing")
    args = parser.parse_args(argv)
    try:
        if args.input.resolve() == args.output.resolve():
            raise MapError("Input and output must be different files")
        if args.output.suffix.lower() != ".svg":
            raise MapError("Output must have a .svg extension")
        data = json.loads(args.input.read_text(encoding="utf-8"))
        svg = render(data)
        if args.check:
            if not args.output.is_file() or args.output.read_text(encoding="utf-8") != svg:
                raise MapError(f"Missing or stale SVG: {args.output}; generate it first")
            print(f"Consistent: {args.output}")
        else:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(svg, encoding="utf-8")
            print(f"Generated {args.output}: {len(data['stations'])} stations, {len(data['routes'])} routes")
    except (MapError, OSError, json.JSONDecodeError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
