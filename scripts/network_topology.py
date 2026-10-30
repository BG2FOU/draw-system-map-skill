"""Validate source topology and import a compact, source-neutral station-sequence CSV."""
from __future__ import annotations
import csv
import math
import re
from pathlib import Path
from draw_map import color


def require(value, message):
    if not value:
        raise ValueError(message)


def nonempty(value, where):
    require(isinstance(value, str) and bool(value.strip()), f'{where}: expected a nonempty string')
    return value


def coordinates(value, where):
    require(isinstance(value, list) and len(value) == 2, f'{where}: expected [longitude, latitude]')
    for number, limit in zip(value, [180, 90]):
        require(not isinstance(number, bool) and isinstance(number, (int, float)) and math.isfinite(number)
                and abs(number) <= limit, f'{where}: invalid longitude/latitude')
    return value


def validate_topology(data):
    require(isinstance(data, dict), 'Topology must be an object')
    require(type(data.get('schema_version')) is int and data['schema_version'] == 1, 'schema_version must be 1')
    nonempty(data.get('title'), 'title')
    for key in ['stations', 'routes']:
        require(isinstance(data.get(key), list) and data[key], f'{key}: expected a nonempty array')
    for key in ['sources', 'warnings', 'transfers']:
        require(isinstance(data.get(key, []), list), f'{key}: expected an array')
    for warning in data.get('warnings', []):
        nonempty(warning, 'warning')
    for source in data.get('sources', []):
        require(isinstance(source, dict), 'source: expected an object')
    ids = set()
    for station in data['stations']:
        require(isinstance(station, dict), 'station: expected an object')
        sid = nonempty(station.get('id'), 'station.id')
        require(sid not in ids, f'Duplicate station ID: {sid}')
        ids.add(sid)
        nonempty(station.get('name'), f'{sid}.name')
        if 'secondary_name' in station:
            nonempty(station['secondary_name'], f'{sid}.secondary_name')
        if 'coordinates' in station:
            coordinates(station['coordinates'], f'{sid}.coordinates')
        refs = station.get('source_stop_ids', [])
        require(isinstance(refs, list) and all(isinstance(x, str) and x for x in refs), f'{sid}.source_stop_ids: invalid IDs')
    route_ids, served = set(), set()
    for route in data['routes']:
        require(isinstance(route, dict), 'route: expected an object')
        rid = nonempty(route.get('id'), 'route.id')
        require(rid not in route_ids, f'Duplicate route ID: {rid}')
        route_ids.add(rid)
        nonempty(route.get('name'), f'{rid}.name')
        if 'color' in route:
            color(route['color'])
        patterns = route.get('patterns')
        require(isinstance(patterns, list) and patterns, f'{rid}: needs ordered patterns')
        pattern_ids = set()
        for pattern in patterns:
            require(isinstance(pattern, dict), f'{rid}.pattern: expected an object')
            pid = nonempty(pattern.get('id'), f'{rid}.pattern.id')
            require(pid not in pattern_ids, f'{rid}: duplicate pattern ID {pid}')
            pattern_ids.add(pid)
            stations = pattern.get('station_ids')
            require(isinstance(stations, list) and len(stations) >= 2, f'{rid}/{pid}: needs at least two station IDs')
            for sid in stations:
                nonempty(sid, f'{rid}/{pid}.station_id')
                require(sid in ids, f'{rid}/{pid}: unknown station {sid}')
                served.add(sid)
            require(all(a != b for a, b in zip(stations, stations[1:])), f'{rid}/{pid}: consecutive identical stations')
            if 'direction' in pattern:
                require(isinstance(pattern['direction'], (str, int)), f'{rid}/{pid}: invalid direction')
    require(ids == served, f'Unserved station IDs: {sorted(ids - served)}')
    for transfer in data.get('transfers', []):
        require(isinstance(transfer, dict), 'transfer: expected an object')
        require(isinstance(transfer.get('from'), str) and isinstance(transfer.get('to'), str)
                and transfer['from'] in ids and transfer['to'] in ids, 'transfer: unknown from/to station')
    return data


def import_csv(path, title):
    """Each row represents a station occurrence in one route pattern; IDs determine identity."""
    stations, routes, sequences = {}, {}, {}
    required = {'route_id', 'route_name', 'pattern_id', 'sequence', 'station_id', 'station_name'}
    with Path(path).open(encoding='utf-8-sig', newline='') as file:
        reader = csv.DictReader(file)
        require(required <= set(reader.fieldnames or []), f'Station CSV needs columns: {", ".join(sorted(required))}')
        for line, row in enumerate(reader, 2):
            require(None not in row and all(row[k] is not None for k in required), f'CSV line {line}: malformed row')
            rid, pid, sid = [nonempty(row[k], f'CSV line {line}: {k}') for k in ['route_id', 'pattern_id', 'station_id']]
            name, route_name = [nonempty(row[k], f'CSV line {line}: {k}') for k in ['station_name', 'route_name']]
            require(bool(re.fullmatch(r'\d+', row['sequence'])), f'CSV line {line}: sequence must be a nonnegative integer')
            sequence = int(row['sequence'])
            station = {'id': sid, 'name': name, 'source_stop_ids': [sid]}
            lon, lat = row.get('lon', ''), row.get('lat', '')
            require(bool(lon) == bool(lat), f'CSV line {line}: supply both lon and lat or neither')
            if lon:
                station['coordinates'] = coordinates([float(lon), float(lat)], f'CSV line {line}')
            if row.get('secondary_name'):
                station['secondary_name'] = row['secondary_name']
            if sid in stations:
                previous = stations[sid]
                require(previous['name'] == name, f'{sid}: conflicting station names')
                for key in ['coordinates', 'secondary_name']:
                    if key in previous and key in station:
                        require(previous[key] == station[key], f'{sid}: conflicting {key}')
                previous.update(station)
            else:
                stations[sid] = station
            if rid not in routes:
                routes[rid] = {'id': rid, 'name': route_name, 'patterns': []}
            route = routes[rid]
            require(route['name'] == route_name, f'{rid}: conflicting route names')
            if row.get('color'):
                value = color(row['color'])
                require('color' not in route or route['color'] == value, f'{rid}: conflicting colors')
                route['color'] = value
            key = (rid, pid)
            if key not in sequences:
                sequences[key] = {'rows': {}, 'direction': row.get('direction', '') or ''}
            record = sequences[key]
            require(sequence not in record['rows'], f'{rid}/{pid}: duplicate sequence {sequence}')
            require(record['direction'] == (row.get('direction', '') or ''), f'{rid}/{pid}: conflicting directions')
            record['rows'][sequence] = sid
    for (rid, pid), record in sorted(sequences.items()):
        routes[rid]['patterns'].append({'id': pid, 'direction': record['direction'],
                                        'station_ids': [sid for _, sid in sorted(record['rows'].items())]})
    result = {'schema_version': 1, 'title': title, 'sources': [], 'stations': list(stations.values()),
              'routes': list(routes.values()), 'transfers': [],
              'warnings': ['CSV represents supplied station sequences; source accuracy and transfer identity require review.']}
    return validate_topology(result)


def group_routes(topology, groups):
    """Apply an explicit source-ID mapping, never guess line identity from names/colors."""
    import copy
    data=copy.deepcopy(validate_topology(topology))
    require(isinstance(groups,list) and groups,'Route groups must be a nonempty array')
    existing={route['id']:route for route in data['routes']}
    consumed,new_ids,result=set(),set(),[]
    for group in groups:
        require(isinstance(group,dict),'Route group must be an object')
        require(set(group)<={'id','name','route_ids','color'},'Unknown route-group fields')
        rid=nonempty(group.get('id'),'group.id')
        name=nonempty(group.get('name'),'group.name')
        require(rid not in new_ids,f'Duplicate group ID: {rid}')
        new_ids.add(rid)
        members=group.get('route_ids')
        require(isinstance(members,list) and members and all(isinstance(x,str) for x in members),'group.route_ids must list source route IDs')
        require(len(set(members))==len(members),'Duplicate source ID in route group')
        require(set(members)<=existing.keys(),f'Unknown source routes in group {rid}')
        require(not consumed.intersection(members),'A source route cannot belong to multiple groups')
        consumed.update(members)
        merged={'id':rid,'name':name,'patterns':[],'source_route_ids':list(members)}
        colors={existing[x].get('color') for x in members}
        if 'color' in group:merged['color']=color(group['color'])
        elif len(colors)>1:raise ValueError(f'Group {rid}: source colors differ; supply an explicit group color')
        elif next(iter(colors)) is not None:merged['color']=next(iter(colors))
        modes={existing[x].get('mode','') for x in members}
        merged['mode']=next(iter(modes)) if len(modes)==1 else 'mixed'
        for member in members:
            for pattern in existing[member]['patterns']:
                item=copy.deepcopy(pattern)
                item['id']=f'{member}/{pattern["id"]}'
                item['source_route_id']=member
                merged['patterns'].append(item)
        result.append(merged)
    remaining=[route for route in data['routes'] if route['id'] not in consumed]
    require(not new_ids.intersection(route['id'] for route in remaining),'Group ID collides with an ungrouped route')
    data['routes']=sorted([*remaining,*result],key=lambda r:r['id'])
    data.setdefault('warnings',[]).append('Visual lines were grouped using an explicit source-route mapping; original route IDs remain in patterns.')
    return validate_topology(data)
