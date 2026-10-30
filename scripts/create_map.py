#!/usr/bin/env python3
"""Fetch transit sources, list GTFS routes, or build an editable map draft."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
from urllib.error import URLError
from urllib.parse import urlsplit
import zipfile
from draw_map import render
from fetch_source import fetch, source_record
from network_topology import import_csv, validate_topology, group_routes
from import_gtfs import list_routes, import_gtfs
from layout_network import layout


def write_json(path, value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


def build(args):
    folder=args.output_dir
    if folder.exists(): raise ValueError('Output directory already exists; choose a new directory to preserve edits')
    folder.mkdir(parents=True)
    try:
        is_url=urlsplit(args.source).scheme in ('http','https')
        if is_url:
            source=folder/'source.download'
            metadata=fetch(args.source,source,args.max_download_mb*1024*1024,args.attribution)
        else:
            original=Path(args.source)
            metadata=source_record(original)
            source=folder/('source'+original.suffix)
            shutil.copyfile(original,source)
        if args.source_url: metadata['url']=args.source_url
        if args.attribution: metadata['attribution']=args.attribution
        write_json(folder/'source-record.json',metadata)
        source_format=args.format
        if source_format=='auto':
            if zipfile.is_zipfile(source): source_format='gtfs'
            else:
                with source.open('rb') as file: head=file.read(1024)
                source_format='topology' if head.lstrip(b'\xef\xbb\xbf \r\n\t').startswith(b'{') else 'csv'
        title=args.title or 'Transit network draft'
        if source_format=='gtfs':
            if not args.route_id and not args.route_type:
                raise ValueError('Choose --route-id or --route-type; use the routes command to list the feed first')
            topology=import_gtfs(source,title,route_ids=args.route_id,route_types=args.route_type,service_date=args.service_date)
        else:
            if args.route_id or args.route_type or args.service_date:
                raise ValueError('Route and service-date filters apply to GTFS input only')
            if source_format=='csv': topology=import_csv(source,title)
            else:
                topology=json.loads(source.read_text(encoding='utf-8-sig'))
                if args.title: topology['title']=args.title
                validate_topology(topology)
        topology.setdefault('sources',[]).append(metadata)
        if args.route_groups:
            write_json(folder/'imported-topology.json',topology)
            groups=json.loads(args.route_groups.read_text(encoding='utf-8-sig'))
            topology=group_routes(topology,groups)
            write_json(folder/'route-groups.json',groups)
        overrides=None
        if args.overrides:
            overrides=json.loads(args.overrides.read_text(encoding='utf-8-sig'))
            shutil.copyfile(args.overrides,folder/'layout-overrides.json')
        validate_topology(topology)
        write_json(folder/'topology.json',topology)
        network,layout_report=layout(topology,overrides)
        write_json(folder/'network.json',network)
        (folder/'network.svg').write_text(render(network),encoding='utf-8')
        report={'status':'draft_ready','source_format':source_format,'source':metadata,
                'counts':{'stations':len(topology['stations']),'routes':len(topology['routes']),
                          'patterns':sum(len(r['patterns']) for r in topology['routes'])},
                'data_warnings':topology.get('warnings',[]),'layout':layout_report,
                'review':'Check source coverage, transfer identities, labels, shared tracks and source attribution before delivery.'}
        if not any(source.get('attribution') for source in topology['sources']):
            report['data_warnings'].append('Source attribution was not supplied; check source terms before sharing.')
        if args.png:
            result=subprocess.run([sys.executable,str(Path(__file__).with_name('export_png.py')),
                                   str(folder/'network.svg'),str(folder/'network.png'),'--scale','1.5'],
                                  capture_output=True,text=True)
            report['png']={'ok':result.returncode==0,'message':(result.stdout+result.stderr).strip()}
            if result.returncode: report['status']='draft_ready_png_failed'
        write_json(folder/'report.json',report)
        return report
    except Exception as error:
        # Keep a successfully fetched source for offline diagnosis/retry.
        write_json(folder/'report.json',{'status':'failed','error':str(error),
                                      'note':'Any saved source is retained; retry into a new output directory.'})
        raise


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    commands=parser.add_subparsers(dest='command',required=True)
    download=commands.add_parser('fetch',help='Download once, retaining source URL and timestamp')
    download.add_argument('url')
    download.add_argument('--output',type=Path,required=True)
    download.add_argument('--max-download-mb',type=int,default=128)
    download.add_argument('--attribution',default='')
    routes=commands.add_parser('routes',help='List route IDs from a local GTFS ZIP')
    routes.add_argument('source',type=Path)
    routes.add_argument('--route-type',action='append')
    generate=commands.add_parser('build',help='Generate a draft from a URL or local GTFS/CSV/topology')
    generate.add_argument('source')
    generate.add_argument('--format',choices=['auto','gtfs','csv','topology'],default='auto')
    generate.add_argument('--output-dir',type=Path,required=True)
    generate.add_argument('--title')
    generate.add_argument('--route-id',action='append')
    generate.add_argument('--route-type',action='append')
    generate.add_argument('--service-date')
    generate.add_argument('--source-url')
    generate.add_argument('--attribution',default='')
    generate.add_argument('--max-download-mb',type=int,default=128)
    generate.add_argument('--overrides',type=Path)
    generate.add_argument('--route-groups',type=Path,help='Explicit JSON mapping of source route IDs to visual lines')
    generate.add_argument('--png',action='store_true')
    args=parser.parse_args()
    try:
        if args.command=='fetch':
            metadata=fetch(args.url,args.output,args.max_download_mb*1024*1024,args.attribution)
            print(f"Saved {args.output}: {metadata['bytes']} bytes; source record alongside")
        elif args.command=='routes':
            rows=list_routes(args.source)
            if args.route_type: rows=[r for r in rows if str(r['type']) in args.route_type]
            print(json.dumps(rows,ensure_ascii=False,indent=2))
        else:
            report=build(args)
            print(f"{report['status']}: {args.output_dir}; {report['counts']}; review report.json")
            if report['status']=='draft_ready_png_failed': return 1
    except (ValueError,OSError,URLError,zipfile.BadZipFile,KeyError) as error:
        print(f'Error: {error}',file=sys.stderr);return 1
    return 0

if __name__=='__main__': sys.exit(main())
