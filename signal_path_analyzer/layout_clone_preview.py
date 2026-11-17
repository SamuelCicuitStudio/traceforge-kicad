"""Read-only Layout Clone scene and an interactive wx preview. Coordinates are mm."""
from __future__ import annotations

import math

from .layout_clone_assets import transform_point


def arc_points(start, middle, end):
    ax, ay = start
    bx, by = middle
    cx, cy = end
    d = 2*(ax*(by-cy)+bx*(cy-ay)+cx*(ay-by))
    if abs(d) < 1e-12:
        return [start, middle, end]
    a, b, c = ax*ax+ay*ay, bx*bx+by*by, cx*cx+cy*cy
    ox = (a*(by-cy)+b*(cy-ay)+c*(ay-by))/d
    oy = (a*(cx-bx)+b*(ax-cx)+c*(bx-ax))/d
    first = math.atan2(ay-oy, ax-ox)
    mid = (math.atan2(by-oy, bx-ox)-first) % math.tau
    sweep = (math.atan2(cy-oy, cx-ox)-first) % math.tau
    if mid > sweep:
        sweep -= math.tau
    radius = math.hypot(ax-ox, ay-oy)
    count = max(8, min(128, math.ceil(abs(sweep)*24)))
    return [[ox+radius*math.cos(first+sweep*i/count),
             oy+radius*math.sin(first+sweep*i/count)] for i in range(count+1)]


def footprint_scene(item, ref, x, y, angle, ghost=False):
    transform = dict(origin=[0, 0], target=[x, y], angle=angle)
    shapes = []
    all_points = []
    for pad in item['pads']:
        center = transform_point(pad['local'], transform)
        width, height = pad['size']
        rotation = dict(origin=[0, 0], target=center, angle=angle+pad['local_angle'])
        corners = [[-width/2, -height/2], [width/2, -height/2],
                   [width/2, height/2], [-width/2, height/2]]
        if pad.get('shape') in (0, 2, 4):
            radius = (min(width, height)*pad.get('roundrect_ratio', .25)
                      if pad.get('shape') == 4 else min(width, height)/2)
            corners = []
            for cx, cy, start in [(width/2-radius, height/2-radius, 0),
                                   (-width/2+radius, height/2-radius, 90),
                                   (-width/2+radius, -height/2+radius, 180),
                                   (width/2-radius, -height/2+radius, 270)]:
                for index in range(9):
                    theta = math.radians(start+index*90/8)
                    corners.append([cx+radius*math.cos(theta), cy+radius*math.sin(theta)])
        points = [transform_point(c, rotation) for c in corners]
        all_points.extend(points)
        shapes.append(dict(kind='pad', points=points, ghost=ghost, width=.05,
                           layer=item['layer'], number=pad['number']))
    if all_points:
        left, right = min(p[0] for p in all_points)-.3, max(p[0] for p in all_points)+.3
        top, bottom = min(p[1] for p in all_points)-.3, max(p[1] for p in all_points)+.3
        shapes.append(dict(kind='body', points=[[left, top], [right, top], [right, bottom],
                                               [left, bottom], [left, top]],
                           layer=item['layer'], ghost=ghost, width=.04))
        shapes.append(dict(kind='text', points=[[left, top-.4]], text=ref,
                           layer=item['layer'], ghost=ghost, width=.05))
    return shapes


def make_scene(template, target=None, plan=None, mode='placement', graphics=False,
               show_before=True):
    """Use Apply's transform; routing-only draws the actual unmoved target footprints."""
    if not template:
        return []
    result = []
    source = {s['ref']: s for s in template['items']}
    if plan and target:
        destinations = {s['ref']: s for s in target['items']}
        for pair in plan['pairs']:
            dst = destinations[pair['target']]
            if show_before:
                result.extend(footprint_scene(dst, dst['ref'], dst['x'], dst['y'],
                                              dst['angle'], ghost=True))
            item = dst if mode == 'routing' else source[pair['source']]
            x, y, angle = ((dst['x'], dst['y'], dst['angle']) if mode == 'routing' else
                           (pair['x'], pair['y'], pair['angle']))
            result.extend(footprint_scene(item, dst['ref'], x, y, angle))
        transform = plan['transform']
    else:
        for src in source.values():
            result.extend(footprint_scene(src, src['ref'], src['x'], src['y'], src['angle']))
        transform = dict(origin=[0, 0], target=[0, 0], angle=0)
    for primitive in template.get('assets', {}).get('preview', [])[:10000]:
        routing = primitive['kind'] in ('copper', 'via', 'zone')
        if routing and mode == 'placement' or not routing and not graphics:
            continue
        obj = dict(primitive)
        obj['points'] = [transform_point(point, transform) for point in primitive['points']]
        result.append(obj)
    return result


def create_preview(parent):
    import wx

    class Preview(wx.Panel):
        def __init__(self):
            super().__init__(parent)
            self.SetMinSize((300, 240))
            self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
            self.scene = []
            self.scale = None
            self.offset = [0, 0]
            self.drag = None
            self.layer = 'All layers'
            self.notice = 'Record a source layout to preview it.'
            self.Bind(wx.EVT_PAINT, self.paint)
            self.Bind(wx.EVT_SIZE, lambda e: self.Refresh())
            self.Bind(wx.EVT_MOUSEWHEEL, self.wheel)
            self.Bind(wx.EVT_LEFT_DOWN, self.down)
            self.Bind(wx.EVT_LEFT_UP, self.up)
            self.Bind(wx.EVT_MOTION, self.motion)
            self.Bind(wx.EVT_MOUSE_CAPTURE_LOST, lambda e: setattr(self, 'drag', None))
            self.Bind(wx.EVT_LEFT_DCLICK, lambda e: self.fit())
            self.SetToolTip('Wheel: zoom. Drag: pan. Double-click: fit. '
                            'Pads and body bounds are simplified; Apply checks copper clearance.')

        def set_scene(self, scene, notice):
            self.scene = scene
            self.notice = notice
            self.fit()

        def fit(self):
            self.scale = None
            self.Refresh()

        def visible(self):
            return [p for p in self.scene if self.layer == 'All layers' or
                    p.get('layer') in (self.layer, 'via') or self.layer in p.get('layers', []) or
                    p['kind'] in ('pad', 'body', 'text')]

        def paint(self, _event):
            dc = wx.AutoBufferedPaintDC(self)
            self.draw(dc, self.GetClientSize())

        def draw(self, dc, size):
            dc.SetBackground(wx.Brush('#101923'))
            dc.Clear()
            visible = self.visible()
            points = [point for obj in visible for point in obj['points']]
            if points and self.scale is None:
                left, right = min(p[0] for p in points), max(p[0] for p in points)
                top, bottom = min(p[1] for p in points), max(p[1] for p in points)
                self.scale = min(max(1, size.width-70)/max(right-left, 2),
                                 max(1, size.height-90)/max(bottom-top, 2))
                self.offset = [size.width/2-(left+right)/2*self.scale,
                               (size.height+30)/2-(top+bottom)/2*self.scale]
            scale = self.scale or 1
            def pixel(point):
                return wx.Point(round(point[0]*scale+self.offset[0]),
                                round(point[1]*scale+self.offset[1]))
            draw = wx.GCDC(dc)
            for obj in visible:
                kind = obj['kind']
                ghost = obj.get('ghost', False)
                color = ('#536171' if ghost else '#f39485' if obj.get('layer') == 'F.Cu'
                         else '#75adff' if obj.get('layer') == 'B.Cu' else '#d2ba65')
                if kind == 'body' and not ghost:
                    color = '#77c8c6'
                draw.SetPen(wx.Pen(color, max(1, round(obj.get('width', .1)*scale)),
                                   wx.PENSTYLE_SHORT_DASH if ghost else wx.PENSTYLE_SOLID))
                pts = [pixel(point) for point in obj['points']]
                draw.SetBrush(wx.TRANSPARENT_BRUSH)
                if kind == 'pad':
                    draw.SetBrush(wx.Brush(color))
                    draw.DrawPolygon(pts)
                elif kind == 'via':
                    draw.SetBrush(wx.Brush('#d2ba65'))
                    radius = max(2, round(obj['width']*scale/2))
                    draw.DrawCircle(pts[0], radius)
                    draw.SetBrush(wx.Brush('#101923'))
                    draw.SetPen(wx.TRANSPARENT_PEN)
                    draw.DrawCircle(pts[0], max(1, round(obj.get('drill', .2)*scale/2)))
                elif kind == 'text':
                    draw.SetTextForeground(color)
                    draw.SetFont(wx.Font(9, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL,
                                         wx.FONTWEIGHT_NORMAL))
                    draw.DrawText(obj.get('text', '')[:100], pts[0])
                elif len(pts) > 1:
                    draw.DrawLines(pts)
            draw.SetTextForeground('#d9e4ef')
            draw.SetFont(wx.Font(9, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL,
                                 wx.FONTWEIGHT_NORMAL))
            draw.DrawText(self.notice, 8, 8)
            draw.DrawText('Red: top | Blue: bottom | Grey: before | Wheel: zoom / Drag: pan',
                          8, max(28, size.height-22))

        def wheel(self, event):
            if not self.scale:
                return
            old = self.scale
            new = max(.1, min(10000, old*(1.2 if event.GetWheelRotation() > 0 else 1/1.2)))
            point = event.GetPosition()
            self.offset = [point[i]-(point[i]-self.offset[i])*new/old for i in (0, 1)]
            self.scale = new
            self.Refresh()

        def down(self, event):
            self.drag = event.GetPosition()
            self.CaptureMouse()

        def up(self, _event):
            self.drag = None
            if self.HasCapture():
                self.ReleaseMouse()

        def motion(self, event):
            if self.drag is not None and event.Dragging():
                pos = event.GetPosition()
                self.offset = [self.offset[i]+pos[i]-self.drag[i] for i in (0, 1)]
                self.drag = pos
                self.Refresh()

    return Preview()
