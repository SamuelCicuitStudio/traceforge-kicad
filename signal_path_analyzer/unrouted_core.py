"""Closest-anchor spanning links between disconnected native copper clusters."""
import hashlib
import math


def links_between(clusters):
    """Prim spanning tree: one genuine missing connection per separate cluster."""
    if len(clusters) < 2:
        return []
    pending = set(range(1, len(clusters)))
    best = {}
    links = []
    current = 0
    while pending:
        for index in pending:
            nearest = min(((math.dist(a['position'], b['position']), a, b)
                           for a in clusters[current] for b in clusters[index]),
                          key=lambda row: row[0])
            if index not in best or nearest[0] < best[index][0]:
                best[index] = nearest
        index = min(pending, key=lambda i: (best[i][0], i))
        distance, a, b = best[index]
        links.append(dict(a=a, b=b, gap_mm=distance))
        pending.remove(index)
        current = index
    return links


def row_identity(net, a, b):
    ends = sorted((a['id']+str(a['position']), b['id']+str(b['position'])))
    return hashlib.sha256((net+'|'+str(ends)).encode()).hexdigest()[:24]
