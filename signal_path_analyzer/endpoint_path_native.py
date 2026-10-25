"""Trace routed copper between two selected vias/pads, with explicit passive bridges."""
from __future__ import annotations

import heapq
import math
import re
import time
from collections import defaultdict, deque

import pcbnew

from .chains import series_ohms
from .pathfinder import RAIL


def identity(item):
    return item.m_Uuid.AsString()


def net_name(item):
    return item.GetNetname().replace('{slash}', '/')


def mate_name(net):
    match = re.search(r'_(DP|DN|P|N)(?=_|$)', net)
    if match:
        other = {'P': 'N', 'N': 'P', 'DP': 'DN', 'DN': 'DP'}[match.group(1)]
        return net[:match.start(1)] + other + net[match.end(1):]
    if net.endswith(('+', '-')):
        return net[:-1] + ('-' if net[-1] == '+' else '+')
    return None


def endpoint(item):
    p = item.GetPosition()
    kind = 'Via' if isinstance(item, pcbnew.PCB_VIA) else 'Track'
    label = (f'{item.GetParentFootprint().GetReference()}.{item.GetNumber()}'
             if isinstance(item, pcbnew.PAD) else
             f'{kind} at {p.x / 1e6:.3f}, {p.y / 1e6:.3f} mm')
    return dict(id=identity(item), net=net_name(item), label=label,
                position=[p.x / 1e6, p.y / 1e6])


class RoutedGraph:
    def __init__(self, board, ohms, caps, started):
        self.started = started
        self.items, self.bridges = {}, defaultdict(list)
        self.parts = {}
        self.raw = list(board.GetTracks())
        for fp in board.GetFootprints():
            pads = list(fp.Pads())
            self.raw.extend(pads)
            ref, value = fp.GetReference(), fp.GetValue()
            eligible = (ref.upper().startswith('R') and series_ohms(value) is not None and
                        series_ohms(value) <= ohms) or (caps and ref.upper().startswith('C'))
            if (eligible and len(pads) == 2 and len({net_name(p) for p in pads}) == 2 and
                    all(net_name(p) and not RAIL.search(net_name(p)) for p in pads)):
                a, b = map(identity, pads)
                self.bridges[a].append((b, ref))
                self.bridges[b].append((a, ref))
                self.parts[ref] = dict(reference=ref, value=value, type='R' if
                                       ref.upper().startswith('R') else 'C', id=identity(fp))
        self.all_items = {identity(item): item for item in self.raw}
        self.all_items.update({identity(fp): fp for fp in board.GetFootprints()})
        self.by_net = defaultdict(list)
        for item in self.raw:
            if net_name(item):
                self.by_net[net_name(item)].append(item)
        self.net_bridges = defaultdict(set)
        for source, peers in self.bridges.items():
            for other, _ in peers:
                self.net_bridges[net_name(self.all_items[source])].add(
                    net_name(self.all_items[other]))
        self.buckets, self.long = defaultdict(list), defaultdict(list)
        self.cache = {}
        self.cell = 5_000_000

    def check_time(self):
        if time.monotonic() - self.started > 18:
            raise ValueError('Path search exceeded its time budget. Select closer endpoints '
                             'or narrow passive traversal settings.')

    def prepare(self, start, end):
        nets, queue = {net_name(start)}, deque([net_name(start)])
        while queue:
            self.check_time()
            net = queue.popleft()
            for other in self.net_bridges[net]:
                if other not in nets:
                    nets.add(other)
                    queue.append(other)
            if len(nets) > 500:
                raise ValueError('Too many connected passive nets; reduce the resistor limit.')
        if net_name(end) not in nets:
            raise ValueError('No path connects these endpoints with the current settings. '
                             'Enable AC-coupling capacitor traversal or increase the resistor '
                             'limit if the signal crosses those parts. IC internals and '
                             'unrouted gaps cannot be crossed.')
        layers = list(start.GetBoard().GetEnabledLayers().CuStack())
        for net in nets:
            for item in self.by_net[net]:
                self.check_time()
                key = identity(item)
                if key in self.items:
                    continue
                shape = {layer: item.GetEffectiveShape(layer) for layer in layers
                         if item.IsOnLayer(layer)}
                box = item.GetBoundingBox()
                self.items[key] = (item, shape, box)
                x0, x1 = box.GetX() // self.cell, box.GetRight() // self.cell
                y0, y1 = box.GetY() // self.cell, box.GetBottom() // self.cell
                if (x1 - x0 + 1) * (y1 - y0 + 1) > 256:
                    self.long[net].append(key)
                else:
                    for y in range(y0, y1 + 1):
                        for x in range(x0, x1 + 1):
                            self.buckets[net, x, y].append(key)

    def neighbors(self, key):
        if key in self.cache:
            return self.cache[key]
        self.check_time()
        item, shapes, box = self.items[key]
        net = net_name(item)
        candidates = set(self.long[net])
        cells = ((box.GetRight() // self.cell - box.GetX() // self.cell + 1) *
                 (box.GetBottom() // self.cell - box.GetY() // self.cell + 1))
        if cells > 256:
            candidates.update(identity(t) for t in self.by_net[net])
        else:
            for y in range(box.GetY() // self.cell, box.GetBottom() // self.cell + 1):
                for x in range(box.GetX() // self.cell, box.GetRight() // self.cell + 1):
                    candidates.update(self.buckets[net, x, y])
        found = list(self.bridges[key])
        for other in candidates:
            self.check_time()
            if other == key or other not in self.items:
                continue
            _, peer_shapes, _ = self.items[other]
            if any(shape and peer_shapes.get(layer) and shape.Collide(peer_shapes[layer], 0)
                   for layer, shape in shapes.items()):
                found.append((other, None))
        self.cache[key] = found
        return found

    def route(self, start, end):
        if any(RAIL.search(net_name(item)) for item in (start, end)):
            raise ValueError('This signal-path tool excludes power/ground endpoints.')
        self.prepare(start, end)
        source, target = identity(start), identity(end)
        initial = (start.GetLength() / 1e6 if isinstance(start, pcbnew.PCB_TRACK) and
                   not isinstance(start, pcbnew.PCB_VIA) else 0)
        distances, previous = {source: initial}, {}
        pending = [(initial, source)]
        while pending:
            self.check_time()
            distance, key = heapq.heappop(pending)
            if distance != distances[key]:
                continue
            if key == target:
                break
            for other, part in self.neighbors(key):
                if other not in self.items:
                    continue
                item = self.items[other][0]
                weight = (item.GetLength() / 1e6 if isinstance(item, pcbnew.PCB_TRACK) and
                          not isinstance(item, pcbnew.PCB_VIA) else .001)
                proposed = distance + max(weight, .001)
                if proposed < distances.get(other, math.inf):
                    distances[other] = proposed
                    previous[other] = (key, part)
                    heapq.heappush(pending, (proposed, other))
        else:
            raise ValueError('No continuous routed-copper path was found. Unrouted gaps and '
                             'zone-only connections are not treated as signal tracks.')
        keys, parts = [target], []
        while keys[-1] != source:
            parent, part = previous[keys[-1]]
            if part:
                parts.append(part)
            keys.append(parent)
        keys.reverse()
        parts.reverse()
        nets = list(dict.fromkeys(net_name(self.items[k][0]) for k in keys))
        ids = keys + [self.parts[ref]['id'] for ref in parts]
        tracks = [self.items[k][0] for k in keys if isinstance(self.items[k][0], pcbnew.PCB_TRACK)
                  and not isinstance(self.items[k][0], pcbnew.PCB_VIA)]
        return dict(endpoints=[endpoint(start), endpoint(end)], nets=nets, series=parts,
                    components=[self.parts[ref] for ref in parts], ids=list(dict.fromkeys(ids)),
                    track_mm=sum(t.GetLength() / 1e6 for t in tracks),
                    track_count=len(tracks), branches=any(len(self.neighbors(k)) > 2 for k in keys))


def detect(board, payload):
    started = time.monotonic()
    ohms = float(payload.get('max_ohms', 100))
    if not math.isfinite(ohms) or not 0 <= ohms <= 1_000_000:
        raise ValueError('Resistor traversal limit must be between 0 and 1,000,000 ohms.')
    graph = RoutedGraph(board, ohms, bool(payload.get('capacitors', True)), started)
    if payload.get('endpoints'):
        selected = [graph.all_items.get(k) for k in payload['endpoints']]
    else:
        selected = list(pcbnew.GetCurrentSelection())
    supported = (pcbnew.PCB_TRACK, pcbnew.PAD, pcbnew.FOOTPRINT)
    if (len(selected) != 2 or any(not isinstance(t, supported) for t in selected) or
            identity(selected[0]) == identity(selected[1])):
        raise ValueError('Select exactly two pads, vias, tracks/arcs or footprints as endpoints '
                         'in PCB Editor. Select endpoints, not every item along the route.')
    if any(isinstance(t, pcbnew.FOOTPRINT) for t in selected):
        candidates = [list(t.Pads()) if isinstance(t, pcbnew.FOOTPRINT) else [t]
                      for t in selected]
        choices = []
        for a in candidates[0]:
            if not net_name(a) or RAIL.search(net_name(a)):
                continue
            reachable, queue = {net_name(a)}, deque([net_name(a)])
            while queue:
                graph.check_time()
                for name in graph.net_bridges[queue.popleft()]:
                    if name not in reachable:
                        reachable.add(name)
                        queue.append(name)
            for b in candidates[1]:
                if identity(a) != identity(b) and net_name(b) in reachable:
                    choices.append(dict(endpoints=[identity(a), identity(b)],
                                        label=f"{endpoint(a)['label']} [{net_name(a)}] -> "
                                              f"{endpoint(b)['label']} [{net_name(b)}]"))
                    if len(choices) >= 128:
                        break
            if len(choices) >= 128:
                break
        if not choices:
            raise ValueError('No signal-net path joins the selected components with these '
                             'resistor/capacitor settings. Select individual pads to narrow it.')
        choices.sort(key=lambda choice: choice['label'])
        if len(choices) > 1:
            return dict(choices=choices)
        selected = [graph.all_items[k] for k in choices[0]['endpoints']]
    primary = graph.route(*selected)
    partner, note = None, ''
    if payload.get('include_pair', True):
        mate_nets = payload.get('pair_nets', {})
        names = [mate_nets.get(net_name(t)) or mate_name(net_name(t)) for t in selected]
        if all(names) and all(n in graph.by_net for n in names):
            mates = []
            for item, name in zip(selected, names):
                peers = [t for t in graph.by_net[name] if type(t) is type(item)]
                if isinstance(item, pcbnew.PAD):
                    peers = [t for t in peers if identity(t.GetParentFootprint()) ==
                             identity(item.GetParentFootprint())]
                origin = item.GetPosition()
                peers.sort(key=lambda t: math.hypot(t.GetPosition().x - origin.x,
                                                    t.GetPosition().y - origin.y))
                limit = 3_000_000
                if (not peers or math.hypot(peers[0].GetPosition().x - origin.x,
                                           peers[0].GetPosition().y - origin.y) > limit or
                    (len(peers) > 1 and abs(math.dist(endpoint(peers[0])['position'],
                                                     endpoint(item)['position']) -
                                           math.dist(endpoint(peers[1])['position'],
                                                     endpoint(item)['position'])) < .001)):
                    note = 'Partner net detected, but its endpoint is missing or ambiguous. '
                    break
                mates.append(peers[0])
            else:
                if identity(mates[0]) != identity(mates[1]):
                    try:
                        partner = graph.route(*mates)
                        note = ('Partner inferred from pair-net names and nearby matching '
                                'endpoints; review.')
                    except ValueError as exc:
                        note = f'Partner net detected but not fully routed: {exc}'
                else:
                    note = ('Partner endpoints resolve to the same item; '
                            'select a clearer endpoint pair.')
        elif any(names):
            note = 'Possible partner name detected, but both endpoint nets were not found.'
    return dict(primary=primary, partner=partner, pair_note=note,
                settings=dict(max_ohms=ohms, capacitors=bool(payload.get('capacitors', True)),
                              include_pair=bool(payload.get('include_pair', True))),
                ids=list(dict.fromkeys(primary['ids'] + (partner['ids'] if partner else []))))
