"""Validated, editable SVG geometry for schematic administrative/geographic maps.

The public entry point accepts a ``basemap`` object, not the whole network.
Only explicit absolute path commands are supported; input is never SVG markup.
"""
from __future__ import annotations

import html
import math
import re


class BasemapError(ValueError):
    """A basemap field does not satisfy the portable data contract."""


KINDS = ("land", "island", "admin", "water", "river", "boundary", "coastline")
LAYERS = ("land", "admin", "water", "boundary")
LAYER_FOR = {"land": "land", "island": "land", "admin": "admin",
             "water": "water", "river": "water", "boundary": "boundary",
             "coastline": "boundary"}
STYLE_KEYS = {"fill", "stroke", "stroke_width", "opacity", "dash"}


def _object(value, where, allowed):
    if not isinstance(value, dict):
        raise BasemapError(f"{where}: expected an object")
    unknown = set(value) - set(allowed)
    if unknown:
        raise BasemapError(f"{where}: unknown fields {', '.join(sorted(map(str, unknown)))}")
    return value


def _array(value, where, nonempty=False):
    if not isinstance(value, list) or (nonempty and not value):
        qualifier = "a nonempty" if nonempty else "an"
        raise BasemapError(f"{where}: expected {qualifier} array")
    return value


def _number(value, where, minimum=None, maximum=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BasemapError(f"{where}: expected a finite number")
    try:
        finite = math.isfinite(value)
    except OverflowError:
        finite = False
    if not finite:
        raise BasemapError(f"{where}: expected a finite number")
    if minimum is not None and value < minimum:
        raise BasemapError(f"{where}: must be >= {minimum}")
    if maximum is not None and value > maximum:
        raise BasemapError(f"{where}: must be <= {maximum}")
    return value


def _text(value, where):
    if not isinstance(value, str) or not value.strip():
        raise BasemapError(f"{where}: expected a nonempty string")
    if any(not (ord(c) in (9, 10, 13) or 32 <= ord(c) <= 0xD7FF
                or 0xE000 <= ord(c) <= 0xFFFD or 0x10000 <= ord(c) <= 0x10FFFF)
           for c in value):
        raise BasemapError(f"{where}: contains characters unsupported by XML")
    return value


def _identifier(value, where):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", value):
        raise BasemapError(f"{where}: expected a letter followed by letters, digits, _ or -")
    return value


def _color(value, where):
    if not isinstance(value, str) or not re.fullmatch(r"(?:#[0-9a-fA-F]{3}|#[0-9a-fA-F]{6}|[a-zA-Z]+)", value):
        raise BasemapError(f"{where}: use #RGB, #RRGGBB or a CSS color name")
    return value


def _fmt(value):
    # Preserve coordinate precision instead of rounding a tiny valid shape away.
    return "0" if value == 0 else str(value)


def _esc(value):
    return html.escape(str(value), quote=True)


def _style(value, where):
    result = dict(_object(value, where, STYLE_KEYS))
    for key in ("fill", "stroke"):
        if key in result:
            _color(result[key], f"{where}.{key}")
    if "stroke_width" in result:
        _number(result["stroke_width"], f"{where}.stroke_width", 0)
    if "opacity" in result:
        _number(result["opacity"], f"{where}.opacity", 0, 1)
    if "dash" in result:
        for index, value in enumerate(_array(result["dash"], f"{where}.dash")):
            if _number(value, f"{where}.dash[{index}]", 0) == 0:
                raise BasemapError(f"{where}.dash[{index}]: must be > 0")
    return result


def _collinear(points):
    """Detect the obvious all-collinear degeneracy, not arbitrary topology."""
    unique = list(dict.fromkeys(points))
    if len(unique) < 3:
        return True
    # Scale before subtraction to avoid overflow for finite large coordinates.
    scale = max(abs(v) for point in unique for v in point) or 1
    normalized = [(x / scale, y / scale) for x, y in unique]
    first, second = normalized[:2]
    ux, uy = second[0] - first[0], second[1] - first[1]
    return all(ux * (p[1] - first[1]) == uy * (p[0] - first[0])
               for p in normalized[2:])


def _path(value, where, area):
    commands = _array(value, where, nonempty=True)
    counts = {"M": 3, "L": 3, "Q": 5, "C": 7, "Z": 1}
    anchors = []
    control_points = []
    result = []
    has_curve = False
    has_length = False
    for index, raw in enumerate(commands):
        at = f"{where}[{index}]"
        command = _array(raw, at, nonempty=True)
        code = command[0]
        if not isinstance(code, str) or code not in counts:
            raise BasemapError(f"{at}: expected an absolute M, L, Q, C or Z command")
        if len(command) != counts[code]:
            raise BasemapError(f"{at}: {code} requires {counts[code] - 1} coordinates")
        if index == 0 and code != "M":
            raise BasemapError(f"{at}: a path must start with M")
        if index != 0 and code == "M":
            raise BasemapError(f"{at}: M is only allowed at the start")
        if code == "Z" and index != len(commands) - 1:
            raise BasemapError(f"{at}: Z is only allowed at the end")
        coordinates = [_number(v, f"{at}[{j}]") for j, v in enumerate(command[1:], 1)]
        points = list(zip(coordinates[::2], coordinates[1::2]))
        if code != "Z":
            if anchors and any(p != anchors[-1] for p in points):
                has_length = True
            anchors.append(points[-1])
            control_points.extend(points[:-1])
        has_curve = has_curve or code in ("Q", "C")
        result.append(code + (" " + " ".join(_fmt(v) for v in coordinates) if coordinates else ""))
    if not has_length:
        raise BasemapError(f"{where}: a path needs at least one nondegenerate drawing segment")
    if area:
        if commands[-1][0] != "Z":
            raise BasemapError(f"{where}: an area contour must end with Z")
        minimum = 2 if has_curve else 3
        if len(set(anchors)) < minimum:
            raise BasemapError(f"{where}: an area needs at least {minimum} different anchor points")
        if _collinear(anchors + control_points):
            raise BasemapError(f"{where}: an area contour cannot be entirely collinear")
    return " ".join(result)


def _geometry(value, where, kind):
    geometry = _object(value, where, {"type", "parts", "paths"})
    geometry_type = geometry.get("type")
    if geometry_type not in ("area", "line"):
        raise BasemapError(f"{where}.type: expected area or line")
    if kind in ("land", "island", "admin", "water") and geometry_type != "area":
        raise BasemapError(f"{where}: {kind} requires area geometry")
    if kind in ("boundary", "coastline") and geometry_type != "line":
        raise BasemapError(f"{where}: {kind} requires line geometry")
    paths = []
    if geometry_type == "area":
        if "paths" in geometry:
            raise BasemapError(f"{where}: area geometry does not accept paths")
        for index, value in enumerate(_array(geometry.get("parts"), f"{where}.parts", True)):
            at = f"{where}.parts[{index}]"
            part = _object(value, at, {"outer", "holes"})
            contours = [_path(part.get("outer"), f"{at}.outer", True)]
            for hole_index, hole in enumerate(_array(part.get("holes", []), f"{at}.holes")):
                contours.append(_path(hole, f"{at}.holes[{hole_index}]", True))
            # Each part is a separate evenodd compound path: independent parts
            # overlap as a union, while only that part's own rings make holes.
            paths.append(" ".join(contours))
    else:
        if "parts" in geometry:
            raise BasemapError(f"{where}: line geometry does not accept parts")
        for index, path in enumerate(_array(geometry.get("paths"), f"{where}.paths", True)):
            paths.append(_path(path, f"{where}.paths[{index}]", False))
    return geometry_type, paths


def _defaults(kind, geometry_type):
    result = {"fill": "none", "stroke": "none", "stroke_width": 0,
              "opacity": 1, "dash": []}
    if geometry_type == "area":
        result["fill"] = {"land": "#f6f3eb", "island": "#f6f3eb",
                          "admin": "#ede7dc", "water": "#dceef6",
                          "river": "#dceef6"}[kind]
    else:
        result.update({"stroke": {"river": "#dceef6", "boundary": "#9da8af",
                                  "coastline": "#bbc6c9"}[kind],
                       "stroke_width": {"river": 12, "boundary": 1.2,
                                        "coastline": 1}[kind]})
        if kind == "boundary":
            result["dash"] = [6, 4]
    return result


def _clip_contour(commands, positive):
    """Normalize explicit outer/hole winding for a nonzero union clip.

    Some SVG rasterizers accumulate evenodd clips across sibling paths, cutting
    overlaps out. Nonzero winding with positive outers and negative holes gives
    the union of valid parts, including their explicit holes. Compute signed
    Bezier area analytically so curve control points need not lie on the contour.
    """
    start = tuple(commands[0][1:])
    current = start
    segments = []
    for command in commands[1:]:
        if command[0] == "Z":
            if current != start:
                segments.append(("L", [current, start]))
            continue
        points = [current, *list(zip(command[1::2], command[2::2]))]
        segments.append((command[0], points))
        current = points[-1]
    scale = max(abs(v) for _, points in segments for p in points for v in p) or 1

    def coefficients(values):
        if len(values) == 2:
            a, b = values
            return [a, b - a]
        if len(values) == 3:
            a, b, c = values
            return [a, 2 * (b - a), a - 2 * b + c]
        a, b, c, d = values
        return [a, 3 * (b - a), 3 * (a - 2 * b + c), -a + 3 * b - 3 * c + d]

    signed_area = 0
    for _, points in segments:
        xs = coefficients([p[0] / scale for p in points])
        ys = coefficients([p[1] / scale for p in points])
        signed_area += sum((xs[i] * j * ys[j] - ys[i] * j * xs[j]) / (i + j)
                           for i in range(len(xs)) for j in range(1, len(xs)))
    if (signed_area > 0) != positive:
        segments = [(code, list(reversed(points))) for code, points in reversed(segments)]
    first = segments[0][1][0]
    output = ["M " + " ".join(_fmt(v) for v in first)]
    for code, points in segments:
        output.append(code + " " + " ".join(_fmt(v) for p in points[1:] for v in p))
    output.append("Z")
    return " ".join(output)


def _clip_geometry(geometry):
    return [" ".join([_clip_contour(part["outer"], True),
                      *[_clip_contour(hole, False) for hole in part.get("holes", [])]])
            for part in geometry["parts"]]


def _labels(values, features):
    output, seen = ['<g id="basemap-labels">'], set()
    for index, value in enumerate(values):
        at = f"basemap.labels[{index}]"
        label = _object(value, at, {"id", "feature", "point", "text", "secondary_text",
                                   "anchor", "size", "secondary_size", "color", "opacity", "line_height"})
        identifier = _identifier(label.get("id"), f"{at}.id")
        if identifier in seen:
            raise BasemapError(f"{at}.id: duplicate label ID {identifier!r}")
        seen.add(identifier)
        reference = _identifier(label.get("feature"), f"{at}.feature")
        if reference not in features:
            raise BasemapError(f"{at}.feature: unknown feature {reference!r}")
        point = _array(label.get("point"), f"{at}.point")
        if len(point) != 2:
            raise BasemapError(f"{at}.point: expected [x, y]")
        x, y = [_number(v, f"{at}.point") for v in point]
        content = _text(label.get("text"), f"{at}.text")
        secondary = _text(label["secondary_text"], f"{at}.secondary_text") if "secondary_text" in label else None
        align = label.get("anchor", "middle")
        if align not in ("start", "middle", "end"):
            raise BasemapError(f"{at}.anchor: use start, middle or end")
        size = _number(label.get("size", 22), f"{at}.size", 1)
        second_size = _number(label.get("secondary_size", 14), f"{at}.secondary_size", 1)
        height = _number(label.get("line_height", size * 1.25), f"{at}.line_height", 1)
        stroke = _color(label.get("color", "#7b8991"), f"{at}.color")
        opacity = _number(label.get("opacity", .85), f"{at}.opacity", 0, 1)
        if not features[reference]["visible"]:
            continue
        output.append(f'<text id="basemap-label-{identifier}" data-feature="{reference}" '
                      f'x="{_fmt(x)}" y="{_fmt(y)}" text-anchor="{align}" '
                      f'fill="{_esc(stroke)}" font-size="{_fmt(size)}" opacity="{_fmt(opacity)}">')
        lines = content.splitlines()
        for line_index, line in enumerate(lines):
            output.append(f'<tspan x="{_fmt(x)}" y="{_fmt(y + line_index * height)}">{_esc(line)}</tspan>')
        if secondary:
            for line_index, line in enumerate(secondary.splitlines()):
                baseline = y + (len(lines) - 1) * height + (line_index + 1) * (second_size + 4)
                output.append(f'<tspan x="{_fmt(x)}" y="{_fmt(baseline)}" '
                              f'font-size="{_fmt(second_size)}">{_esc(line)}</tspan>')
        output.append('</text>')
    output.append('</g>')
    return '\n'.join(output)


def render_basemap(data, width, height):
    """Validate a basemap object and return a frame-clipped SVG group.

    Hidden geometry is validated and remains available for administrative clips.
    Every clip contains normalized nonzero paths, providing the union of the
    referenced parts without incorrectly XOR-ing overlaps between land masses.
    """
    _number(width, "canvas.width", 0)
    _number(height, "canvas.height", 0)
    basemap = _object(data, "basemap", {"frame", "background", "styles", "features", "labels"})
    frame = _array(basemap.get("frame"), "basemap.frame")
    if len(frame) != 4:
        raise BasemapError("basemap.frame: expected [x, y, width, height]")
    x, y, w, h = [_number(v, f"basemap.frame[{i}]", 0) for i, v in enumerate(frame)]
    if w == 0 or h == 0:
        raise BasemapError("basemap.frame: width and height must be > 0")
    if x > width or y > height or w > width - x or h > height - y:
        raise BasemapError("basemap.frame: must be fully inside the canvas")
    background = _color(basemap["background"], "basemap.background") if "background" in basemap else None
    styles = _object(basemap.get("styles", {}), "basemap.styles", KINDS)
    kind_styles = {kind: _style(style, f"basemap.styles.{kind}") for kind, style in styles.items()}
    labels = _array(basemap.get("labels", []), "basemap.labels")

    features = []
    by_id = {}
    for index, value in enumerate(_array(basemap.get("features"), "basemap.features")):
        at = f"basemap.features[{index}]"
        feature = _object(value, at, {"id", "kind", "geometry", "name", "source", "order", "visible", "style", "clip_to"})
        identifier = _identifier(feature.get("id"), f"{at}.id")
        if identifier in by_id:
            raise BasemapError(f"{at}.id: duplicate feature ID {identifier!r}")
        kind = feature.get("kind")
        if kind not in KINDS:
            raise BasemapError(f"{at}.kind: expected one of {', '.join(KINDS)}")
        geometry_type, paths = _geometry(feature.get("geometry"), f"{at}.geometry", kind)
        order = _number(feature.get("order", 0), f"{at}.order")
        visible = feature.get("visible", True)
        if not isinstance(visible, bool):
            raise BasemapError(f"{at}.visible: expected a boolean")
        for key in ("name", "source"):
            if key in feature:
                _text(feature[key], f"{at}.{key}")
        style = {**_defaults(kind, geometry_type), **kind_styles.get(kind, {}),
                 **_style(feature.get("style", {}), f"{at}.style")}
        if geometry_type == "line":
            style["fill"] = "none"
        if kind == "admin":
            if "clip_to" not in feature:
                raise BasemapError(f"{at}.clip_to: admin requires explicit land/island IDs or null")
            clip_to = feature["clip_to"]
            if clip_to is not None:
                _array(clip_to, f"{at}.clip_to", True)
                for clip_index, reference in enumerate(clip_to):
                    _identifier(reference, f"{at}.clip_to[{clip_index}]")
                if len(set(clip_to)) != len(clip_to):
                    raise BasemapError(f"{at}.clip_to: duplicate feature references")
        elif "clip_to" in feature:
            raise BasemapError(f"{at}.clip_to: only admin features accept clip_to")
        else:
            clip_to = None
        validated = {"id": identifier, "kind": kind, "type": geometry_type,
                     "paths": paths, "order": order, "visible": visible,
                     "clip_paths": _clip_geometry(feature["geometry"]) if kind in ("land", "island") else [],
                     "style": style, "clip_to": clip_to,
                     "name": feature.get("name"), "source": feature.get("source")}
        features.append(validated)
        by_id[identifier] = validated

    for feature in features:
        for reference in feature["clip_to"] or []:
            target = by_id.get(reference)
            if target is None or target["kind"] not in ("land", "island"):
                raise BasemapError(f"basemap feature {feature['id']!r}.clip_to: {reference!r} must reference a land/island feature")

    rect = f'x="{_fmt(x)}" y="{_fmt(y)}" width="{_fmt(w)}" height="{_fmt(h)}"'
    output = ['<g id="basemap" clip-path="url(#basemap-frame)">',
              f'<defs><clipPath id="basemap-frame" clipPathUnits="userSpaceOnUse"><rect {rect}/></clipPath>']
    for feature in features:
        if feature["clip_to"] is not None:
            output.append(f'<clipPath id="basemap-clip-{feature["id"]}" clipPathUnits="userSpaceOnUse">')
            for reference in feature["clip_to"]:
                for path in by_id[reference]["clip_paths"]:
                    output.append(f'<path d="{path}" fill-rule="nonzero" clip-rule="nonzero"/>')
            output.append('</clipPath>')
    output.append('</defs>')
    if background is not None:
        output.append(f'<rect id="basemap-background" {rect} fill="{_esc(background)}"/>')
    for layer in LAYERS:
        output.append(f'<g id="basemap-{layer}">')
        for feature in sorted(features, key=lambda f: f["order"]):
            if not feature["visible"] or LAYER_FOR[feature["kind"]] != layer:
                continue
            style = feature["style"]
            attributes = [f'id="basemap-feature-{feature["id"]}"',
                          f'data-feature="{feature["id"]}"', f'data-kind="{feature["kind"]}"',
                          f'fill="{_esc(style["fill"])}"', f'stroke="{_esc(style["stroke"])}"',
                          f'stroke-width="{_fmt(style["stroke_width"])}"',
                          f'opacity="{_fmt(style["opacity"])}"',
                          'stroke-linecap="round"', 'stroke-linejoin="round"']
            if style["dash"]:
                attributes.append('stroke-dasharray="' + ' '.join(_fmt(v) for v in style["dash"]) + '"')
            if feature["clip_to"] is not None:
                attributes.append(f'clip-path="url(#basemap-clip-{feature["id"]})"')
            output.append('<g ' + ' '.join(attributes) + '>')
            if feature["name"] is not None:
                output.append(f'<title>{_esc(feature["name"])}</title>')
            if feature["source"] is not None:
                output.append(f'<desc>{_esc(feature["source"])}</desc>')
            for index, path in enumerate(feature["paths"]):
                rule = ' fill-rule="evenodd"' if feature["type"] == "area" else ''
                output.append(f'<path id="basemap-geometry-{feature["id"]}-{index}" d="{path}"{rule}/>')
            output.append('</g>')
        output.append('</g>')
    output.extend([_labels(labels, by_id), '</g>'])
    return '\n'.join(output)
