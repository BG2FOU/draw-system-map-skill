"""Corridor-first octilinear layout, using only the Python standard library."""
from __future__ import annotations
import math
from collections import defaultdict


def corridors(adjacency, anchors=None):
    anchors = set(anchors or ()) | {s for s, neighbors in adjacency.items() if len(neighbors) != 2}
    seen, result = set(), []
    # Also seed a closed component with no junctions.
    for start in sorted(anchors) + sorted(set(adjacency) - anchors):
        for neighbor in sorted(adjacency[start]):
            edge = frozenset((start, neighbor))
            if edge in seen:
                continue
            chain = [start, neighbor]; seen.add(edge)
            while chain[-1] not in anchors and chain[-1] != start:
                choices = adjacency[chain[-1]] - {chain[-2]}
                if len(choices) != 1:
                    break
                nxt = next(iter(choices)); seen.add(frozenset((chain[-1], nxt))); chain.append(nxt)
            result.append(chain)
    return result


def _distance_to_line(p, a, b):
    dx, dy = b[0]-a[0], b[1]-a[1]
    if not dx and not dy:
        return math.dist(p,a)
    return abs(dx*(p[1]-a[1])-dy*(p[0]-a[0]))/math.hypot(dx,dy)


def _bend_indices(chain, reference):
    if len(chain) < 5:
        return []
    a,b=reference[chain[0]],reference[chain[-1]]
    tolerance=max(55,math.dist(a,b)*.16)
    index=max(range(1,len(chain)-1),key=lambda i:_distance_to_line(reference[chain[i]],a,b))
    if _distance_to_line(reference[chain[index]],a,b) <= tolerance:
        return []
    # A bend is an anchor of a whole corridor, never a repelled individual stop.
    return (_bend_indices(chain[:index+1],reference)+[chain[index]]+
            _bend_indices(chain[index:],reference))


def _octilinear(a,b):
    dx,dy=b[0]-a[0],b[1]-a[1]
    if not dx or not dy or abs(abs(dx)-abs(dy)) < .001:
        return [[a,b]]
    length=min(abs(dx),abs(dy)); sx=1 if dx>0 else -1; sy=1 if dy>0 else -1
    return [[a,[a[0]+sx*length,a[1]+sy*length],b],
            [a,[b[0]-sx*length,b[1]-sy*length],b]]


def _cross(a,b,c,d):
    if a in (c,d) or b in (c,d): return False
    def area(p,q,r): return (q[0]-p[0])*(r[1]-p[1])-(q[1]-p[1])*(r[0]-p[0])
    return area(a,b,c)*area(a,b,d)<-1e-6 and area(c,d,a)*area(c,d,b)<-1e-6


def _overlap_length(a,b,c,d):
    dx,dy=b[0]-a[0],b[1]-a[1];length=math.hypot(dx,dy)
    if not length or _distance_to_line(c,a,b)>.001 or _distance_to_line(d,a,b)>.001:return 0
    one=((c[0]-a[0])*dx+(c[1]-a[1])*dy)/length
    two=((d[0]-a[0])*dx+(d[1]-a[1])*dy)/length
    return max(0,min(length,max(one,two))-max(0,min(one,two)))


def _length(path): return sum(math.dist(a,b) for a,b in zip(path,path[1:]))


def _at(path,distance):
    for a,b in zip(path,path[1:]):
        length=math.dist(a,b)
        if distance<=length+1e-7:
            t=distance/length if length else 0
            return [a[0]+(b[0]-a[0])*t,a[1]+(b[1]-a[1])*t]
        distance-=length
    return list(path[-1])


def _span(path,start,end):
    result=[_at(path,start)]; distance=0
    for a,b in zip(path,path[1:]):
        distance+=math.dist(a,b)
        if start+1e-5<distance<end-1e-5:result.append(list(b))
    result.append(_at(path,end))
    return result


def schematic_layout(adjacency,reference,geographic,canvas,canvas_overrides,label_margin=140):
    """Return station positions and per-edge centerlines, preserving station order."""
    initial=corridors(adjacency)
    anchors=set(); loop_anchors=set()
    for chain in initial:
        if chain[0]==chain[-1]:
            loop_anchors.update(chain[i] for i in (0,len(chain)//3,2*len(chain)//3))
            anchors.update(loop_anchors)
        elif geographic:
            anchors.update(_bend_indices(chain,reference))
    chains=corridors(adjacency,anchors)
    # Distinct branches with the same endpoints need their own interior anchor;
    # otherwise a corridor router would place every branch on the same chord.
    groups=defaultdict(list)
    for chain in chains: groups[tuple(sorted((chain[0],chain[-1])))].append(chain)
    for group in groups.values():
        if len(group)>1:
            for chain in group:
                if len(chain)>2: anchors.add(chain[len(chain)//2])
    chains=corridors(adjacency,anchors)
    ids=sorted({sid for chain in chains for sid in (chain[0],chain[-1])})
    position={sid:list(reference[sid]) for sid in ids}
    incidence=defaultdict(list); directions=defaultdict(set); targets=[]
    for chain in sorted(chains,key=lambda c:(-len(c),c)):
        a,b=chain[0],chain[-1]; dx,dy=reference[b][0]-reference[a][0],reference[b][1]-reference[a][1]
        angle=math.atan2(dy,dx)
        def score(k):
            delta=abs(math.atan2(math.sin(k*math.pi/4-angle),math.cos(k*math.pi/4-angle)))
            def crowd(node, outgoing):
                return sum(5 if min((outgoing-old)%8,(old-outgoing)%8)==0 else
                           2.5 if node not in loop_anchors and len(adjacency[node])==2 and min((outgoing-old)%8,(old-outgoing)%8)==1 else 0
                           for old in directions[node])
            return delta + crowd(a,k) + crowd(b,(k+4)%8)
        k=min(range(8),key=lambda k:(score(k),k))
        directions[a].add(k);directions[b].add((k+4)%8)
        length=max(80*(len(chain)-1),math.hypot(dx,dy)*.58)
        target=[math.cos(k*math.pi/4)*length,math.sin(k*math.pi/4)*length]
        targets.append((chain,target))
        incidence[a].append((b,[-v for v in target]));incidence[b].append((a,target))
    # Solve a small anchored graph system; ordinary stations are not free variables.
    for _ in range(300):
        for sid in ids:
            for axis in (0,1):
                position[sid][axis]=(.025*reference[sid][axis]+sum(position[n][axis]+delta[axis] for n,delta in incidence[sid]))/(.025+len(incidence[sid]))
    occupied=set()
    for sid in ids:
        p=[round(v/24)*24 for v in position[sid]]
        while tuple(p) in occupied:p[0]+=24
        position[sid]=p;occupied.add(tuple(p))
    # Only skeleton junctions move for clearance. Ordinary stations are placed
    # afterwards along their corridor and can never become a zigzag of springs.
    for _ in range(80):
        for i,a in enumerate(ids):
            for b in ids[i+1:]:
                dx,dy=position[b][0]-position[a][0],position[b][1]-position[a][1]
                distance=math.hypot(dx,dy)
                if distance<96:
                    if distance<.001:dx,dy,distance=1.,0.,1.
                    amount=(96-distance)*.26
                    for axis,delta in enumerate((dx,dy)):
                        position[a][axis]-=delta/distance*amount
                        position[b][axis]+=delta/distance*amount
    position={sid:[round(v/12)*12 for v in p] for sid,p in position.items()}
    chosen=[]; edges={}; stations={}
    for chain,target in targets:
        a,b=position[chain[0]],position[chain[-1]]
        def route_score(path):
            crossings=sum(_cross(p,q,u,v) for p,q in zip(path,path[1:]) for other in chosen for u,v in zip(other,other[1:]))
            dx,dy=path[1][0]-a[0],path[1][1]-a[1]
            turn=abs(math.atan2(dx*target[1]-dy*target[0],dx*target[0]+dy*target[1]))
            overlap=sum(_overlap_length(p,q,u,v) for p,q in zip(path,path[1:]) for other in chosen for u,v in zip(other,other[1:]))
            return crossings*1000+overlap*100+turn
        path=min(_octilinear(a,b),key=route_score)
        chosen.append(path); total=_length(path)
        for i,sid in enumerate(chain):stations[sid]=_at(path,total*i/(len(chain)-1))
        for i,(u,v) in enumerate(zip(chain,chain[1:])):
            geometry=_span(path,total*i/(len(chain)-1),total*(i+1)/(len(chain)-1))
            edges[(u,v)]=geometry;edges[(v,u)]=list(reversed(geometry))
    for sid in adjacency:
        if sid not in stations:stations[sid]=list(reference[sid])
    # Enlarge the default sheet; never squeeze the new corridor spacing back down.
    all_points=[p for path in chosen for p in path]+list(stations.values())
    min_x,min_y=min(p[0] for p in all_points),min(p[1] for p in all_points)
    extent_x=max(p[0] for p in all_points)-min_x;extent_y=max(p[1] for p in all_points)-min_y
    padding=max(600,2*label_margin+320)
    required_w,required_h=extent_x+padding,extent_y+400
    if 'width' not in canvas_overrides:canvas['width']=max(canvas['width'],math.ceil(required_w/50)*50)
    if 'height' not in canvas_overrides:canvas['height']=max(canvas['height'],math.ceil(required_h/50)*50)
    scale=min(1,(canvas['width']-600)/max(extent_x,1),(canvas['height']-400)/max(extent_y,1))
    if scale <= 0: raise ValueError("Canvas leaves no room for the schematic")
    left=(canvas['width']-320-extent_x*scale)/2
    top=160+(canvas['height']-300-extent_y*scale)/2
    def transform(p):return [round((p[0]-min_x)*scale+left,4),round((p[1]-min_y)*scale+top,4)]
    stations={sid:transform(p) for sid,p in stations.items()}
    edges={key:[transform(p) for p in path] for key,path in edges.items()}
    return stations,edges,{'corridors':len(chains),'anchors':len(ids),'scale':round(scale,4),'station_spacing_target':80,'directions':'0/45/90 degrees'}
