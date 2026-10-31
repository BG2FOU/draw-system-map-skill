"""Continuous lanes on a shared schematic centerline (standard library only).

Station references remain in each segment. ``station_offsets`` changes only the
route stroke at those references; station symbols retain their network position.
"""
from __future__ import annotations

from collections import defaultdict
import math

LANE_GAP = 9.0
_EPS = 1e-7


def _edge(a, b):
    return tuple(sorted((a, b)))


def _point(value):
    if (not isinstance(value, (list, tuple)) or len(value) != 2
            or any(isinstance(x, bool) or not isinstance(x, (int, float))
                   or not math.isfinite(x) for x in value)):
        raise ValueError("Centerline coordinates must be finite two-dimensional points")
    return [float(value[0]), float(value[1])]


def _same(a, b):
    return math.dist(a, b) < _EPS


def _cross(a, b):
    return a[0] * b[1] - a[1] * b[0]


def _unit(a, b):
    length = math.dist(a, b)
    if length < _EPS:
        raise ValueError("Centerline contains a zero-length edge")
    return [(b[0] - a[0]) / length, (b[1] - a[1]) / length]


def _shift(point, direction, amount):
    return [point[0] - direction[1] * amount,
            point[1] + direction[0] * amount]


def _intersection(first, second):
    delta = [second['start'][i] - first['start'][i] for i in (0, 1)]
    denominator = _cross(first['unit'], second['unit'])
    if abs(denominator) < _EPS:
        return None
    distance = _cross(delta, second['unit']) / denominator
    return [first['start'][i] + distance * first['unit'][i] for i in (0, 1)]


def _join(center, incoming, outgoing):
    first = _shift(center, incoming['unit'], incoming['amount'])
    second = _shift(center, outgoing['unit'], outgoing['amount'])
    if _same(first, second):
        return first, False
    intersection = _intersection(incoming, outgoing)
    limit = max(45, abs(incoming['amount']) * 4, abs(outgoing['amount']) * 4)
    if intersection is not None and math.dist(center, intersection) <= limit:
        return intersection, False
    # Parallel lanes changing membership cannot meet at an infinite miter.
    return [(first[i] + second[i]) / 2 for i in (0, 1)], True


def _canonical(sequence, cyclic):
    sequence = tuple(sequence)
    if not cyclic:
        return min(sequence, tuple(reversed(sequence)))
    reverse = tuple(reversed(sequence))
    return min(*(sequence[i:] + sequence[:i] for i in range(len(sequence))),
               *(reverse[i:] + reverse[:i] for i in range(len(reverse))))


def _pairs(sequence, cyclic):
    return list(zip(sequence, sequence[1:] + (sequence[:1] if cyclic else [])))


def _clip_reversed_legs(nodes, supports, cyclic):
    """Remove the small offset loops caused by a short inside-corner leg.

    Offset line intersections can reverse a centerline segment when its length
    is smaller than the lane offset. Join its surrounding support lines instead.
    Keep every station reference at the clipped join, rather than dropping calls.
    """
    clipped = 0
    # Each pass removes a support, so this bound also covers cyclic paths.
    for _ in range(len(supports)):
        bad = None
        for index, support in enumerate(supports):
            nxt = (index + 1) % len(nodes)
            delta = [nodes[nxt]['point'][j] - nodes[index]['point'][j] for j in (0, 1)]
            if sum(delta[j] * support['unit'][j] for j in (0, 1)) < -1e-5:
                bad = index
                break
        if bad is None or len(nodes) <= (3 if cyclic else 2):
            break
        # Rotate a cyclic polygon so that the removed leg is never its wrap.
        if cyclic and bad == len(nodes) - 1:
            nodes[:] = nodes[-1:] + nodes[:-1]
            supports[:] = supports[-1:] + supports[:-1]
            bad = 0
        first, second = nodes[bad], nodes[bad + 1]
        before = supports[bad - 1] if bad or cyclic else None
        after = supports[bad + 1] if bad + 1 < len(supports) else None
        intersection = _intersection(before, after) if before and after else None
        # An end of an open path can lie inside the miter: trim to that end.
        if intersection is None and before is None:
            intersection = first['point']
        elif intersection is None and after is None:
            intersection = second['point']
        if intersection is None:
            # Parallel surrounding supports do not define a safe local clip.
            break
        limit = max(90, abs(supports[bad]['amount']) * 8)
        if min(math.dist(intersection, node['point']) for node in (first, second)) > limit:
            break
        nodes[bad:bad + 2] = [{'point': intersection,
                              'refs': first['refs'] + second['refs']}]
        del supports[bad]
        clipped += 1
    return clipped


def _clean_waypoints(points, positions, offsets, closed):
    """Delete only redundant coordinate controls, never station references."""
    def resolve(value):
        if isinstance(value, str):
            offset = offsets.get(value, (0, 0))
            return [positions[value][j] + offset[j] for j in (0, 1)]
        return value
    result = list(points)
    changed = True
    while changed:
        changed = False
        for index, value in enumerate(result):
            if isinstance(value, str) or len(result) < 3:
                continue
            if not closed and index in (0, len(result) - 1):
                continue
            a, b, c = (resolve(result[(index + delta) % len(result)]) for delta in (-1, 0, 1))
            ab = [b[j] - a[j] for j in (0, 1)]
            bc = [c[j] - b[j] for j in (0, 1)]
            if (_same(a, b) or _same(b, c)
                    or (abs(_cross(ab, bc)) < 1e-5
                        and sum(ab[j] * bc[j] for j in (0, 1)) >= 0)):
                del result[index]
                changed = True
                break
    return result


def route_geometry(drawing_routes, positions, edge_paths, route_overrides=None):
    """Populate editable route lanes without changing route station sequences.

    All validation and geometry construction precedes mutation. A manual
    ``segments`` override is preserved exactly and reported for visual review.
    """
    route_overrides = route_overrides or {}
    records, members = [], defaultdict(set)
    manual = {route_id for route_id, override in route_overrides.items() if 'segments' in override}
    for route in drawing_routes:
        for index, segment in enumerate(route['segments']):
            sequence = [value for value in segment['points'] if isinstance(value, str)]
            repeated = len(sequence) > 1 and sequence[0] == sequence[-1]
            cyclic = bool(segment.get('closed')) or repeated
            working = sequence[:-1] if repeated else sequence[:]
            if len(working) < 2 or (cyclic and len(working) < 3):
                raise ValueError("Route geometry requires two stations, or three for a closed route")
            for sid in working:
                if sid not in positions:
                    raise ValueError(f"Unknown station in route geometry: {sid}")
                _point(positions[sid])
            record = dict(route_id=route['id'], index=index, segment=segment, sequence=working,
                          original=sequence, cyclic=cyclic, repeated=repeated,
                          canonical=_canonical(working, cyclic))
            records.append(record)
            for a, b in _pairs(working, cyclic):
                if a == b:
                    raise ValueError("Consecutive route stations must be distinct")
                members[_edge(a, b)].add(route['id'])

    # Orient a complete longest path first. Sorting each edge by station ID would
    # flip lane normals repeatedly when source identifiers are non-geographic.
    orientation = {}
    for record in sorted(records, key=lambda r: (-len(r['sequence']), r['canonical'],
                                                  r['route_id'], r['index'])):
        sequence = list(record['canonical'])
        pairs = _pairs(sequence, record['cyclic'])
        score = sum(1 if orientation[_edge(a, b)] == (a, b) else -1
                    for a, b in pairs if _edge(a, b) in orientation)
        if score < 0:
            sequence.reverse()
        for a, b in _pairs(sequence, record['cyclic']):
            orientation.setdefault(_edge(a, b), (a, b))

    shared = {edge for edge, lines in members.items() if len(lines) > 1}
    incident = defaultdict(set)
    for edge in shared:
        for sid in edge:
            incident[sid].add(edge)
    lanes, remaining = {}, set(shared)
    while remaining:
        pending, component = [min(remaining)], set()
        while pending:
            edge = pending.pop()
            if edge in component:
                continue
            component.add(edge)
            pending.extend(other for sid in edge for other in incident[sid] - component)
        remaining.difference_update(component)
        routes = sorted(set().union(*(members[edge] for edge in component)))
        amounts = {route_id: (index - (len(routes) - 1) / 2) * LANE_GAP
                   for index, route_id in enumerate(routes)}
        for edge in component:
            lanes[edge] = amounts

    plans, transitions, warnings = [], [], []
    offset_edges = station_count = clip_count = 0
    unique_edges, unique_stations, physical_stations = set(), set(), set()
    manual_shared = sorted({record['route_id'] for record in records if record['route_id'] in manual
                            and any(_edge(a, b) in shared for a, b in _pairs(record['sequence'], record['cyclic']))})
    for record in records:
        route_id, sequence = record['route_id'], record['sequence']
        if route_id in manual:
            continue
        nodes = [{'center': _point(positions[sequence[0]]), 'refs': [sequence[0]]}]
        supports = []
        for a, b in _pairs(sequence, record['cyclic']):
            path = edge_paths.get((a, b))
            if path is None and (b, a) in edge_paths:
                path = list(reversed(edge_paths[(b, a)]))
            if path is None:
                raise ValueError(f"Missing centerline for edge {a!r} -> {b!r}")
            path = [_point(point) for point in path]
            if len(path) < 2 or not _same(path[0], positions[a]) or not _same(path[-1], positions[b]):
                raise ValueError(f"Centerline endpoints do not match stations {a!r} -> {b!r}")
            clean = [path[0]]
            for point in path[1:]:
                if not _same(point, clean[-1]):
                    clean.append(point)
            if len(clean) < 2:
                raise ValueError(f"Centerline is degenerate for {a!r} -> {b!r}")
            edge = _edge(a, b)
            amount = lanes.get(edge, {}).get(route_id, 0)
            if orientation[edge] != (a, b):
                amount = -amount
            if abs(amount) > _EPS:
                offset_edges += 1
                unique_edges.add((route_id, edge))
            for index, (first, second) in enumerate(zip(clean, clean[1:])):
                direction = _unit(first, second)
                supports.append({'start': _shift(first, direction, amount),
                                 'unit': direction, 'amount': amount})
                nodes.append({'center': second, 'refs': [b] if index == len(clean) - 2 else []})
        if record['cyclic']:
            nodes.pop()  # Closing station reference is restored after clipping.
        located = []
        for index, node in enumerate(nodes):
            entry = exit_point = None
            incoming = supports[index - 1] if index or record['cyclic'] else None
            outgoing = supports[index] if index < len(supports) else None
            if incoming and outgoing:
                point, fallback = _join(node['center'], incoming, outgoing)
                if fallback and abs(_cross(incoming['unit'], outgoing['unit'])) < _EPS:
                    # Keep each long leg on its own support. A short transition
                    # at the station is covered by its symbol; averaging only
                    # the join would tilt both neighboring corridor segments.
                    entry = _shift(node['center'], incoming['unit'], incoming['amount'])
                    exit_point = _shift(node['center'], outgoing['unit'], outgoing['amount'])
                if fallback or abs(incoming['amount'] - outgoing['amount']) > _EPS:
                    transitions.append({'route_id': route_id, 'segment_index': record['index'],
                                        'station_ids': node['refs'], 'point': [round(v, 4) for v in point],
                                        'reason': 'parallel transition' if fallback else 'lane membership or orientation'})
            else:
                support = incoming or outgoing
                point = _shift(node['center'], support['unit'], support['amount'])
            located.append({'point': point, 'refs': node['refs'],
                            'entry': entry, 'exit': exit_point})
        clip_count += _clip_reversed_legs(located, supports, record['cyclic'])
        # A cyclic cleanup may rotate controls; restore the original first call.
        if record['cyclic']:
            first = next(i for i, node in enumerate(located) if sequence[0] in node['refs'])
            located = located[first:] + located[:first]
            # Rare clipping across the cyclic seam can combine last and first.
            refs = located[0]['refs']
            if refs and refs[0] != sequence[0]:
                pivot = refs.index(sequence[0])
                located[0] = {'point': located[0]['point'], 'refs': refs[pivot:]}
                located.append({'point': located[0]['point'], 'refs': refs[:pivot]})
        offsets, resolved = {}, {}
        for node in located:
            for sid in node['refs']:
                if sid in resolved and not _same(resolved[sid], node['point']):
                    warnings.append(f"Route {route_id}: repeated station {sid} needs different offsets; retained its center")
                    resolved[sid] = list(positions[sid])
                else:
                    resolved[sid] = node['point']
        for sid, point in resolved.items():
            offset = [round(point[i] - positions[sid][i], 4) for i in (0, 1)]
            if math.hypot(*offset) > _EPS:
                offsets[sid] = offset
                station_count += 1
                unique_stations.add((route_id, sid)); physical_stations.add(sid)
        points = []
        for node in located:
            if node.get('entry') is not None:
                points.append([round(value, 4) for value in node['entry']])
            points.extend(node['refs'] or [[round(value, 4) for value in node['point']]])
            if node.get('exit') is not None:
                points.append([round(value, 4) for value in node['exit']])
        if record['repeated']:
            points.append(sequence[0])
        points = _clean_waypoints(points, positions, offsets, record['cyclic'])
        if [value for value in points if isinstance(value, str)] != record['original']:
            raise ValueError("Lane geometry changed station reference order")
        plans.append((record['segment'], points, offsets))

    for segment, points, offsets in plans:
        segment['points'] = points
        if offsets:
            segment['station_offsets'] = offsets
        else:
            segment.pop('station_offsets', None)
    if manual_shared:
        warnings.append('Manual shared routes retain their supplied geometry: ' + ', '.join(manual_shared))
    return {'offset_shared_segments': offset_edges,
            'shared_edge_count': len(shared),
            'continuous_lane_station_count': station_count,
            'unique_offset_route_edges': len(unique_edges),
            'unique_offset_route_stations': len(unique_stations),
            'unique_offset_station_count': len(physical_stations),
            'clipped_short_legs': clip_count,
            'transition_count': len(transitions), 'transitions': transitions,
            'manual_route_ids': sorted(manual), 'manual_shared_route_ids': manual_shared,
            'warnings': sorted(set(warnings))}
