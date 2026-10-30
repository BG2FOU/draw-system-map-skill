"""Bounded HTTP download with a reusable local source record; no external dependencies."""
from __future__ import annotations
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import tempfile
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as file:
        for block in iter(lambda:file.read(1024*1024),b''): h.update(block)
    return h.hexdigest()


def fetch(url, destination, max_bytes=128*1024*1024, attribution=''):
    parts=urlsplit(url)
    if parts.scheme not in ('http','https') or not parts.hostname or parts.username or parts.password:
        raise ValueError('Source URL must be HTTP(S) without embedded credentials')
    if not isinstance(max_bytes,int) or isinstance(max_bytes,bool) or max_bytes<=0:
        raise ValueError('Download limit must be positive')
    destination=Path(destination)
    record=destination.with_name(destination.name+'.source.json')
    if destination.exists() or record.exists():
        raise ValueError('Source or source record already exists; reuse it or choose a new path')
    destination.parent.mkdir(parents=True,exist_ok=True)
    temp=None
    try:
        with urlopen(Request(url,headers={'User-Agent':'draw-system-map/1.0 source-import'}),timeout=45) as response:
            length=response.headers.get('Content-Length')
            if length and int(length)>max_bytes: raise ValueError('Source exceeds download limit')
            with tempfile.NamedTemporaryFile(dir=destination.parent,prefix='.source-',delete=False) as file:
                temp=Path(file.name)
                total=0
                while True:
                    block=response.read(min(1024*1024,max_bytes-total+1))
                    if not block: break
                    total+=len(block)
                    if total>max_bytes: raise ValueError('Source exceeds download limit')
                    file.write(block)
            if total==0: raise ValueError('Source download was empty')
            metadata={'kind':'http','url':url,'resolved_url':response.geturl(),
                      'retrieved_at':datetime.now(timezone.utc).isoformat(),'bytes':total,
                      'sha256':digest(temp),'attribution':attribution,
                      'last_modified':response.headers.get('Last-Modified')}
        # Exclusive create: never replace an output created during the request.
        with destination.open('xb') as file, temp.open('rb') as source:
            for block in iter(lambda:source.read(1024*1024),b''): file.write(block)
        with record.open('x',encoding='utf-8') as file:
            json.dump(metadata,file,ensure_ascii=False,indent=2);file.write('\n')
        return metadata
    finally:
        if temp is not None: temp.unlink(missing_ok=True)


def source_record(path):
    path=Path(path)
    checksum=digest(path)
    sidecar=path.with_name(path.name+'.source.json')
    if sidecar.is_file():
        record=json.loads(sidecar.read_text(encoding='utf-8'))
        if record.get('sha256')!=checksum:
            raise ValueError('Source file changed since download; source record does not match')
        return record
    return {'kind':'local','file':path.name,'sha256':checksum,
            'attribution':''}
