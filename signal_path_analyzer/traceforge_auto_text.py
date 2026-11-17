"""Preview and arrange component reference/value fields on chosen non-copper layers.

The planner is pure Python. Native board edits use the existing undo transaction;
wx widgets run in the panel process. Crowded labels remain for manual cleanup.
"""
from __future__ import annotations

import math
import secrets
from collections import defaultdict
from dataclasses import dataclass, replace
from typing import Any, Optional

IU_PER_MM = 1_000_000.0
MAX_LABELS = 1000
MAX_CANDIDATES_PER_LABEL = 320
_PREVIEW: Optional[dict] = None
TARGET_LAYERS = ('F.SilkS', 'B.SilkS', 'F.Fab', 'B.Fab', 'Dwgs.User', 'Cmts.User',
                 *(f'User.{i}' for i in range(1, 10)))


def _finite(value: Any, name: str, low: float, high: float) -> float:
    try:
        n = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f'{name} must be a number.') from exc
    if not math.isfinite(n) or not low <= n <= high:
        raise ValueError(f'{name} must be between {low:g} and {high:g}.')
    return n


def _uid(item: Any) -> str:
    return item.m_Uuid.AsString()


def _xy(point: Any) -> tuple[float, float]:
    return (float(point.x) / IU_PER_MM, float(point.y) / IU_PER_MM)


def _v(point: tuple[float, float]) -> Any:
    import pcbnew
    return pcbnew.VECTOR2I(round(point[0] * IU_PER_MM), round(point[1] * IU_PER_MM))


@dataclass(frozen=True)
class Rect:
    x0: float
    y0: float
    x1: float
    y1: float

    def __post_init__(self) -> None:
        if self.x1 < self.x0 or self.y1 < self.y0:
            raise ValueError('Invalid rectangle bounds.')

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def cy(self) -> float:
        return (self.y0 + self.y1) / 2

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def height(self) -> float:
        return self.y1 - self.y0

    def expand(self, amount: float) -> Rect:
        return Rect(self.x0 - amount, self.y0 - amount,
                    self.x1 + amount, self.y1 + amount)

    def intersects(self, other: Rect, clearance: float = 0.0) -> bool:
        return not (self.x1 + clearance <= other.x0 or
                    other.x1 + clearance <= self.x0 or
                    self.y1 + clearance <= other.y0 or
                    other.y1 + clearance <= self.y0)

    def corners(self) -> tuple[tuple[float, float], ...]:
        return ((self.x0, self.y0), (self.x1, self.y0),
                (self.x0, self.y1), (self.x1, self.y1))

    def as_list(self) -> list[float]:
        return [round(self.x0, 6), round(self.y0, 6),
                round(self.x1, 6), round(self.y1, 6)]


def rect_from_box(box: Any) -> Rect:
    x0 = float(box.GetX()) / IU_PER_MM
    y0 = float(box.GetY()) / IU_PER_MM
    x1 = float(box.GetRight()) / IU_PER_MM
    y1 = float(box.GetBottom()) / IU_PER_MM
    return Rect(min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))


def centered(x: float, y: float, w: float, h: float) -> Rect:
    return Rect(x - w / 2, y - h / 2, x + w / 2, y + h / 2)


@dataclass(frozen=True)
class Obstacle:
    box: Rect
    side: str  # F/B silk, a drawing-layer channel, or * for physical holes/vias
    kind: str
    key: str


@dataclass(frozen=True)
class Label:
    key: str             # field token: "footprint-uuid:reference" etc.
    owner: str
    reference: str
    kind: str            # Reference / Value
    side: str
    body: Rect
    text: str
    position: tuple[float, float]
    angle: float
    size: tuple[float, float]
    horizontal_size: tuple[float, float]   # conservative width/height at 0 deg
    needs_update: bool = False
    original_side: Optional[str] = None
    was_visible: bool = True
    bbox_offset: tuple[float, float] = (0.0, 0.0)
    family: str = ''
    thickness: float = 0.15


@dataclass(frozen=True)
class Config:
    clearance: float = 0.25
    max_distance: float = 8.0
    prefer_horizontal: bool = True
    preserve_good: bool = True
    standard_size: float = 0.0  # zero means keep sizes
    target_layer: str = 'keep'
    show_hidden_refs: bool = False
    include_reference_copies: bool = True
    text_on_locked_footprints: bool = False
    align_banks: bool = True
    grid_mm: float = 0.25
    text_thickness: float = 0.0  # zero means keep stroke widths

    @classmethod
    def from_payload(cls, value: dict[str, Any]) -> Config:
        layer = str(value.get('target_layer', 'keep'))
        if layer != 'keep' and layer not in TARGET_LAYERS:
            raise ValueError('Choose a supported silkscreen, fabrication or user text layer.')
        return cls(
            clearance=_finite(value.get('clearance', 0.25), 'Clearance (mm)', 0.05, 2),
            max_distance=_finite(value.get('max_distance', 8), 'Search distance (mm)', 1, 30),
            prefer_horizontal=bool(value.get('prefer_horizontal', True)),
            preserve_good=bool(value.get('preserve_good', True)),
            standard_size=_finite(value.get('standard_size', 0), 'Text height (mm)', 0, 3),
            target_layer=layer,
            show_hidden_refs=value.get('show_hidden_refs', False) is True,
            include_reference_copies=value.get('include_reference_copies', True) is True,
            text_on_locked_footprints=value.get('text_on_locked_footprints', False) is True,
            align_banks=value.get('align_banks', True) is True,
            grid_mm=_finite(value.get('grid_mm', .25), 'Alignment grid (mm)', 0, 1),
            text_thickness=_finite(value.get('text_thickness', 0), 'Stroke (mm)', 0, .5),
        )


class SpatialIndex:
    """Simple grid index; candidate checks inspect only neighboring obstacle cells."""
    def __init__(self, cell: float = 6.0) -> None:
        self.cell = cell
        self.buckets: dict[tuple[int, int], list[Obstacle]] = defaultdict(list)

    def add(self, obstacle: Obstacle) -> None:
        r = obstacle.box
        lowx, highx = math.floor(r.x0 / self.cell), math.floor(r.x1 / self.cell)
        lowy, highy = math.floor(r.y0 / self.cell), math.floor(r.y1 / self.cell)
        for ix in range(lowx, highx + 1):
            for iy in range(lowy, highy + 1):
                self.buckets[ix, iy].append(obstacle)

    def collisions(self, candidate: Rect, side: str, gap: float) -> list[Obstacle]:
        b = candidate.expand(gap)
        seen: set[str] = set()
        found = []
        for ix in range(math.floor(b.x0 / self.cell), math.floor(b.x1 / self.cell) + 1):
            for iy in range(math.floor(b.y0 / self.cell), math.floor(b.y1 / self.cell) + 1):
                for obstacle in self.buckets.get((ix, iy), ()):
                    if obstacle.key in seen or obstacle.side not in ('*', side):
                        continue
                    seen.add(obstacle.key)
                    if candidate.intersects(obstacle.box, gap):
                        found.append(obstacle)
        return found


def _angle_norm(angle: float) -> float:
    return (angle % 180.0 + 180.0) % 180.0


def _text_dims(label: Label, angle: float, standard_size: float,
               thickness: float = 0) -> tuple[float, float]:
    w, h = label.horizontal_size
    if standard_size:
        w *= standard_size / max(0.1, label.size[0])
        h *= standard_size / max(0.1, label.size[1])
    growth = max(0, thickness - label.thickness)
    w, h = w + growth, h + growth
    if abs(_angle_norm(angle) - 90) < 2:
        return h, w
    return w, h


def _candidate_centers(body: Rect, w: float, h: float, clearance: float,
                       max_distance: float):
    """Near-edge slots, corners, and outward/lateral sweeps; deterministic order."""
    g = clearance + 0.10
    dx = body.width / 2 + w / 2 + g
    dy = body.height / 2 + h / 2 + g
    # Put the text outside the component, not on its own pads or body.
    span_x = max(0.8, min(2.4, w * 0.75))
    span_y = max(0.8, min(2.4, h * 1.5))
    lateral = [0, -1, 1, -2, 2, -3, 3]
    outward = [0, 0.75, 1.5, 2.5, 4, 6, 8, 11, 15, 20, 25, 30]
    emitted = set()
    for d in outward:
        if d > max_distance + 0.01:
            continue
        for k in lateral:
            # Top / bottom, left / right, then offset rows around own component.
            for x, y, direction in (
                (body.cx + k * span_x, body.cy - dy - d, 'top'),
                (body.cx + k * span_x, body.cy + dy + d, 'bottom'),
                (body.cx - dx - d, body.cy + k * span_y, 'left'),
                (body.cx + dx + d, body.cy + k * span_y, 'right'),
            ):
                center = (round(x, 6), round(y, 6))
                if center not in emitted:
                    emitted.add(center)
                    yield center, direction


def _nearest_distance(box: Rect, point: tuple[float, float]) -> float:
    dx = max(box.x0 - point[0], 0, point[0] - box.x1)
    dy = max(box.y0 - point[1], 0, point[1] - box.y1)
    return math.hypot(dx, dy)


def _snap(value, grid):
    return round(round(value / grid) * grid, 6) if grid else round(value, 6)


def _bank_groups(labels):
    """Find compact runs of >=3 comparable parts using their physical order."""
    families = defaultdict(list)
    for label in labels:
        if label.kind != 'Reference' or label.body.width * label.body.height > 64:
            continue
        family = label.family or (round(label.body.width, 1), round(label.body.height, 1))
        families[label.side, family].append(label)
    groups = []
    for items in families.values():
        for axis in ('row', 'column'):
            cross = (lambda a: a.body.cy) if axis == 'row' else (lambda a: a.body.cx)
            along = (lambda a: a.body.cx) if axis == 'row' else (lambda a: a.body.cy)
            lines = []
            for item in sorted(items, key=lambda a: (cross(a), along(a), a.key)):
                line = next((g for g in lines if abs(cross(g[0]) - cross(item)) <= .35), None)
                if line is None:
                    lines.append([item])
                else:
                    line.append(item)
            for line in lines:
                run = []
                for item in sorted(line, key=lambda a: (along(a), a.key)):
                    if run:
                        limit = max(3, (run[-1].body.width + item.body.width) * 1.25
                                    if axis == 'row' else
                                    (run[-1].body.height + item.body.height) * 1.25)
                        if along(item) - along(run[-1]) > limit:
                            if len(run) >= 3:
                                groups.append((axis, run))
                            run = []
                    run.append(item)
                if len(run) >= 3:
                    groups.append((axis, run))
    return sorted(groups, key=lambda g: (-len(g[1]), g[0], g[1][0].key))


def _aligned_banks(labels, index, config, board_polygon):
    rows = {}
    for axis, bank in _bank_groups(labels):
        if any(label.key in rows for label in bank):
            continue
        ignored = {'original:' + label.key for label in bank}
        bounds = Rect(min(a.body.x0 for a in bank), min(a.body.y0 for a in bank),
                      max(a.body.x1 for a in bank), max(a.body.y1 for a in bank))
        best = None
        for angle in (0, 90):
            dims = [_text_dims(a, angle, config.standard_size, config.text_thickness) for a in bank]
            width, height = max(d[0] for d in dims), max(d[1] for d in dims)
            for outward in (0, .5, 1, 1.5, 2.5, 4, 6, 8):
                for sign in (-1, 1):
                    boxes, positions = [], []
                    for label, (w, h) in zip(bank, dims):
                        if axis == 'row':
                            edge = bounds.y0 if sign < 0 else bounds.y1
                            x = _snap(label.body.cx, config.grid_mm)
                            y = _snap(edge + sign * (height / 2 + config.clearance + .1 + outward),
                                      config.grid_mm)
                        else:
                            edge = bounds.x0 if sign < 0 else bounds.x1
                            x = _snap(edge + sign * (width / 2 + config.clearance + .1 + outward),
                                      config.grid_mm)
                            y = _snap(label.body.cy, config.grid_mm)
                        box = centered(x, y, w, h)
                        if (_nearest_distance(label.body, (x, y)) > config.max_distance or
                                (board_polygon and not board_polygon(box)) or
                                any(o.key not in ignored for o in
                                    index.collisions(box, label.side, config.clearance)) or
                                any(box.intersects(b, config.clearance) for b in boxes)):
                            break
                        positions.append((x, y))
                        boxes.append(box)
                    if len(positions) != len(bank):
                        continue
                    score = sum(_nearest_distance(a.body, pos)
                                for a, pos in zip(bank, positions)) / len(bank)
                    score += .75 if angle and config.prefer_horizontal else 0
                    if best is None or score < best[0]:
                        best = score, angle, positions, boxes
        if best is None:
            continue
        _, angle, positions, boxes = best
        for label, pos, box in zip(bank, positions, boxes):
            changed = (label.needs_update or math.dist(pos, label.position) > .000002 or
                       abs((label.angle - angle) % 360) > .00001 or
                       (config.standard_size and any(abs(v - config.standard_size) > .00001
                                                     for v in label.size)) or
                       (config.text_thickness and
                        abs(label.thickness - config.text_thickness) > .00001))
            rows[label.key] = dict(key=label.key, reference=label.reference, kind=label.kind,
                                   status='move' if changed else 'keep',
                                   old=[*label.position, label.angle], new=[*pos, angle],
                                   size=config.standard_size or label.size[1],
                                   why=f'Aligned {axis}; component order preserved',
                                   center_text=True, bank=True)
            index.add(Obstacle(box, label.side, 'text', 'occupied:' + label.key))
    return rows


def _choose(labels: list[Label], obstacles: list[Obstacle], config: Config,
            board_polygon: Any = None) -> list[dict]:
    """Pure deterministic placement engine; board_polygon receives Rect -> bool."""
    index = SpatialIndex()
    for obstacle in obstacles:
        index.add(obstacle)
    # Reserve original visible positions too. A later unplaceable label must not
    # be left underneath a new placement chosen earlier in this greedy pass.
    for label in labels:
        if label.was_visible:
            w, h = _text_dims(label, label.angle, 0)
            x, y = label.position
            ox, oy = label.bbox_offset
            index.add(Obstacle(centered(x + ox, y + oy, w, h),
                               label.original_side or label.side,
                               'original text', 'original:' + label.key))

    # Most constrained labels go first; references have priority over values.
    def priority(label: Label):
        near = len(index.collisions(label.body.expand(3), label.side, 0))
        return (0 if label.kind == 'Reference' else 1, -near,
                label.reference, label.key)

    rows = (_aligned_banks(labels, index, config, board_polygon) if config.align_banks else {})
    order = sorted(labels, key=priority)
    for label in order:
        if label.key in rows:
            continue
        oldpos = label.position
        oldangle = label.angle
        gap = config.clearance
        allowed_angles = [0.0, 90.0]
        # Avoid a duplicate angle in the candidate list.
        angles = list(dict.fromkeys(round(v % 180, 6) for v in allowed_angles))
        base_size = config.standard_size or label.size[1]

        def legal(box: Rect, label=label, gap=gap) -> bool:
            if board_polygon is not None and not board_polygon(box):
                return False
            return not any(o.key != 'original:' + label.key
                           for o in index.collisions(box, label.side, gap))

        # Retain already-good near-footprint labels; avoid unnecessary changes.
        if (config.preserve_good and not config.standard_size and not config.text_thickness and
                any(abs(oldangle % 360 - a) < .00001 for a in (0, 90))) and (
                not label.needs_update or math.hypot(*label.bbox_offset) < 0.00001) and (
                _nearest_distance(label.body, oldpos) < min(3.0, config.max_distance)):
            dims = _text_dims(label, oldangle, 0)
            previous = centered(oldpos[0] + label.bbox_offset[0],
                                oldpos[1] + label.bbox_offset[1], *dims)
            if legal(previous):
                rows[label.key] = dict(key=label.key, reference=label.reference,
                                       kind=label.kind,
                                       status='move' if label.needs_update else 'keep',
                                       old=[*oldpos, oldangle],
                                       new=[*oldpos, oldangle],
                                       size=base_size, why='Existing location is clear',
                                       center_text=False)
                index.add(Obstacle(previous, label.side, 'text', 'occupied:' + label.key))
                continue

        best: Optional[tuple[float, float, float, Rect, float, str]] = None
        # Prefer horizontal by a small penalty; hard collisions are rejected.
        for angle in angles:
            count = 0  # Always evaluate alternate orientations when space is tight.
            w, h = _text_dims(label, angle, config.standard_size, config.text_thickness)
            for (x, y), direction in _candidate_centers(label.body, w, h, gap,
                                                           config.max_distance):
                x, y = _snap(x, config.grid_mm), _snap(y, config.grid_mm)
                count += 1
                if count > MAX_CANDIDATES_PER_LABEL:
                    break
                box = centered(x, y, w, h)
                if _nearest_distance(label.body, (x, y)) > config.max_distance:
                    continue
                if not legal(box):
                    continue
                distance = _nearest_distance(label.body, (x, y))
                old_dist = math.hypot(x - oldpos[0], y - oldpos[1])
                score = (distance + 0.035 * old_dist +
                         (0 if _angle_norm(angle) < 2 else
                          (1.2 if config.prefer_horizontal else 0.1)) +
                         (0.06 if direction in ('top', 'bottom') else 0.15) +
                         (0.006 * abs(y - label.body.cy)))
                result = (score, x, y, box, angle, direction)
                if best is None or score < best[0]:
                    best = result
            # Never stop here: the next angle may fit even if this one cannot.

        if best is None:
            rows[label.key] = dict(key=label.key, reference=label.reference,
                                   kind=label.kind, status='unplaced',
                                   old=[*oldpos, oldangle],
                                   new=[*oldpos, oldangle], size=base_size, center_text=False,
                                   why='No collision-free position in search radius')
            # Keep this label as an obstacle, even if it already overlaps a pad.
            dims = _text_dims(label, oldangle, 0)
            index.add(Obstacle(centered(*oldpos, *dims), label.side,
                               'text', 'occupied:' + label.key))
            continue
        score, x, y, box, angle, direction = best
        same_position = (math.hypot(x - oldpos[0], y - oldpos[1]) < 0.000002)
        same_angle = abs((oldangle - angle + 180) % 360 - 180) < 0.00001
        same_size = not config.standard_size or all(
            abs(config.standard_size - v) < .00001 for v in label.size)
        same_stroke = (not config.text_thickness or
                       abs(config.text_thickness - label.thickness) < .00001)
        rows[label.key] = dict(key=label.key, reference=label.reference, kind=label.kind,
                               status=('keep' if same_position and same_angle and same_size and
                                       same_stroke and not label.needs_update else 'move'),
                               old=[*oldpos, oldangle], new=[x, y, angle],
                               size=base_size, why=f'Clear position to {direction}',
                               center_text=True)
        index.add(Obstacle(box, label.side, 'text', 'occupied:' + label.key))
    # Return in natural reference order, independent from greedy planning order.
    return sorted(rows.values(), key=lambda r: (r['reference'], r['kind']))


def _board_polygon(board: Any, clearance: float):
    """Use board Edge.Cuts outline if valid. Missing outline is allowed for drafts."""
    import pcbnew
    poly = pcbnew.SHAPE_POLY_SET()
    try:
        if not board.GetBoardPolygonOutlines(poly, False) or not poly.OutlineCount():
            return None
        inset = pcbnew.SHAPE_POLY_SET(poly)
        inset.Inflate(-round(clearance * IU_PER_MM),
                      pcbnew.CORNER_STRATEGY_ROUND_ALL_CORNERS, 1000)
        if not inset.OutlineCount():
            return lambda _rect: False
        def accept(rect: Rect) -> bool:
            return all(inset.Contains(_v(p), -1, 0, True) for p in rect.corners())
        return accept
    except Exception:
        return None  # Draft/snapshot without a usable outline: warn in preview.


def _side_for_layer(layer: int) -> Optional[str]:
    import pcbnew
    if layer == pcbnew.F_SilkS:
        return 'F'
    if layer == pcbnew.B_SilkS:
        return 'B'
    for name in TARGET_LAYERS[2:]:
        if layer == _target_layer_id(name):
            return name
    return None


def _target_layer_id(name):
    import pcbnew
    if name not in TARGET_LAYERS:
        raise ValueError('Unsupported destination layer: ' + str(name))
    aliases = {'Dwgs.User': 'Dwgs_User', 'Cmts.User': 'Cmts_User'}
    return getattr(pcbnew, aliases.get(name, name.replace('.', '_')))


def _physical_channels(side):
    return [side, side + '.Fab', *TARGET_LAYERS[4:]]


def _text_size(field: Any) -> tuple[float, float]:
    s = field.GetTextSize()
    return max(0.1, s.x / IU_PER_MM), max(0.1, s.y / IU_PER_MM)


def _label_from_field(fp: Any, field: Any, kind: str, body: Rect,
                      config: Config, *, key: Optional[str] = None) -> Label:
    original_side = _side_for_layer(field.GetLayer())
    side = (_side_for_layer(_target_layer_id(config.target_layer))
            if config.target_layer != 'keep' else original_side)
    assert side
    ref = str(fp.GetReference())
    position = _xy(field.GetPosition())
    angle = float(field.GetTextAngleDegrees())
    font_w, font_h = _text_size(field)
    rendered = (str(field.GetShownText(False)) if hasattr(field, 'GetShownText')
                else str(field.GetText()))
    text = rendered or (ref if kind == 'Reference' else str(fp.GetValue()))
    measured = rect_from_box(field.GetBoundingBox())
    # AABB of current text is authoritative where possible; a conservative
    # estimate protects when an embedded font or multiline field reports zero.
    if abs(_angle_norm(angle) - 90) < 2:
        measured_w, measured_h = measured.height, measured.width
    else:
        measured_w, measured_h = measured.width, measured.height
    width = max(measured_w, len(text) * font_w * 0.60, 0.35)
    height = max(measured_h, font_h * 1.15, 0.35)
    return Label(key=key or f'{_uid(fp)}:{kind.lower()}', owner=_uid(fp),
                 reference=ref, kind=kind, side=side, body=body,
                 text=text, position=position, angle=angle,
                 size=(font_w, font_h), horizontal_size=(width, height),
                 needs_update=(not field.IsVisible() or
                               (config.target_layer != 'keep' and
                                field.GetLayer() != _target_layer_id(config.target_layer))),
                 original_side=original_side, was_visible=bool(field.IsVisible()),
                 bbox_offset=(measured.cx - position[0], measured.cy - position[1]),
                 family=str(fp.GetFPIDAsString()),
                 thickness=field.GetTextThickness() / IU_PER_MM)


def _selection_ids(board: Any, scope: str) -> list[str]:
    import pcbnew
    if scope == 'all':
        return sorted(_uid(fp) for fp in board.GetFootprints())
    if scope != 'selected':
        raise ValueError('Scope must be selected or all.')
    current = list(pcbnew.GetCurrentSelection())
    keys = set()
    visited = set()

    def visit(obj):
        identity = _uid(obj)
        if identity in visited:
            return
        visited.add(identity)
        if isinstance(obj, pcbnew.FOOTPRINT):
            keys.add(_uid(obj))
        elif isinstance(obj, pcbnew.PCB_GROUP):
            for child in obj.GetItems():
                visit(child)
        elif hasattr(obj, 'GetParentFootprint'):
            fp = obj.GetParentFootprint()
            if fp is not None and isinstance(fp, pcbnew.FOOTPRINT):
                keys.add(_uid(fp))
    for obj in current:
        visit(obj)
    if not keys:
        raise ValueError('Select one or more components in KiCad PCB Editor first.')
    return sorted(keys)


def _pad_sides(pad: Any) -> list[str]:
    import pcbnew
    faces = []
    for side, mask, copper in (('F', pcbnew.F_Mask, pcbnew.F_Cu),
                               ('B', pcbnew.B_Mask, pcbnew.B_Cu)):
        try:
            if pad.IsOnLayer(mask) or pad.IsOnLayer(copper):
                faces.append(side)
        except Exception:
            pass
    return faces


def _scan(board: Any, ids: list[str], include_values: bool,
          config: Config) -> tuple[list[Label], list[Obstacle], dict, Any]:
    import pcbnew
    wanted = set(ids)
    selected = set()
    labels = []
    obstacles = []
    fields = {}
    signature = []
    skipped = defaultdict(int)
    rules = board.GetDesignSettings()
    signature.append(('silk rules', rules.m_MinSilkTextHeight,
                      rules.m_MinSilkTextThickness, rules.m_SilkClearance))

    def obstacle(box, side, kind, key):
        obstacles.append(Obstacle(box, side, kind, key))
        signature.append((kind, key, side, *box.as_list()))

    def physical(box, side, kind, key):
        for channel in _physical_channels(side):
            obstacle(box, channel, kind, key + ':' + channel)

    for fp in board.GetFootprints():
        identity = _uid(fp)
        side = 'B' if fp.IsFlipped() else 'F'
        body = rect_from_box(fp.GetBoundingBox(False))
        physical(body, side, 'component', 'component:' + identity)
        signature.append(('component lock', identity, bool(fp.IsLocked())))
        for pad in fp.Pads():
            pad_id = _uid(pad)
            pbox = rect_from_box(pad.GetBoundingBox())
            for face in _pad_sides(pad):
                mask = pcbnew.F_Mask if face == 'F' else pcbnew.B_Mask
                expansion = max(0, pad.GetSolderMaskExpansion(mask)) / IU_PER_MM
                physical(pbox.expand(expansion), face, 'pad/mask', 'pad:' + pad_id + ':' + face)
            hole = pad.GetDrillSize()
            radius = max(hole.x, hole.y) / (2 * IU_PER_MM)
            if radius > 0:
                obstacle(centered(*_xy(pad.GetPosition()), radius * 2, radius * 2),
                         '*', 'hole', 'hole:' + pad_id)
        for drawing in fp.GraphicalItems():
            channel = _side_for_layer(drawing.GetLayer())
            reference_copy = (isinstance(drawing, pcbnew.PCB_TEXT) and
                              str(drawing.GetText()).strip().upper() == '${REFERENCE}')
            copy_moving = (reference_copy and config.include_reference_copies and
                           identity in wanted and channel is not None and
                           drawing.IsVisible() and not drawing.IsLocked() and
                           (not fp.IsLocked() or config.text_on_locked_footprints))
            if copy_moving:
                key = identity + ':graphic:' + _uid(drawing)
                labels.append(_label_from_field(fp, drawing, 'Reference copy', body,
                                                config, key=key))
                fields[key] = drawing
                signature.append(('reference copy', key, channel,
                                  *rect_from_box(drawing.GetBoundingBox()).as_list(),
                                  *_xy(drawing.GetPosition()), drawing.GetTextAngleDegrees(),
                                  *_text_size(drawing), drawing.GetTextThickness(),
                                  drawing.IsMirrored(), drawing.IsLocked(), drawing.GetText(),
                                  str(drawing.GetHorizJustify()), str(drawing.GetVertJustify())))
            elif channel and (not hasattr(drawing, 'IsVisible') or drawing.IsVisible()):
                obstacle(rect_from_box(drawing.GetBoundingBox()), channel,
                         'footprint graphic', 'fp_graphic:' + _uid(drawing))
        if identity in wanted:
            selected.add(identity)
        for kind, text_obj in (('Reference', fp.Reference()), ('Value', fp.Value())):
            channel = _side_for_layer(text_obj.GetLayer())
            if channel is None:
                continue
            visible = bool(text_obj.IsVisible())
            eligible = visible or (kind == 'Reference' and config.show_hidden_refs)
            key = identity + ':' + kind.lower()
            text_box = rect_from_box(text_obj.GetBoundingBox())
            pos = _xy(text_obj.GetPosition())
            angle = round(float(text_obj.GetTextAngleDegrees()), 6)
            size = _text_size(text_obj)
            signature.append(('field', key, channel, *text_box.as_list(),
                              *pos, angle, *size, str(text_obj.GetText()), visible,
                              bool(text_obj.IsLocked()), bool(text_obj.IsMirrored()),
                              text_obj.GetTextThickness(),
                              str(text_obj.GetHorizJustify()), str(text_obj.GetVertJustify())))
            if identity in wanted and (kind == 'Reference' or include_values):
                if fp.IsLocked() and not config.text_on_locked_footprints:
                    skipped['locked footprints'] += 1
                elif text_obj.IsLocked():
                    skipped['locked text fields'] += 1
                elif not eligible:
                    skipped['hidden fields'] += 1
            moving = (eligible and identity in wanted and
                      (not fp.IsLocked() or config.text_on_locked_footprints) and
                      (kind == 'Reference' or include_values) and not text_obj.IsLocked())
            if moving:
                labels.append(_label_from_field(fp, text_obj, kind, body, config))
                fields[key] = text_obj
            elif visible:
                obstacle(text_box, channel, 'fixed text', 'fixed:' + key)
        # Custom visible fields are obstacles too; their content is never edited.
        for field in fp.GetFields():
            if field.GetName() in ('Reference', 'Value'):
                continue
            channel = _side_for_layer(field.GetLayer())
            if channel and field.IsVisible():
                obstacle(rect_from_box(field.GetBoundingBox()), channel,
                         'custom field', 'custom:' + _uid(field))

    for tr in board.GetTracks():
        if isinstance(tr, pcbnew.PCB_VIA):
            diameter = max(tr.GetWidth(pcbnew.F_Cu), tr.GetDrillValue()) / IU_PER_MM
            obstacle(centered(*_xy(tr.GetPosition()), diameter, diameter),
                     '*', 'via', 'via:' + _uid(tr))
    for drawing in board.GetDrawings():
        channel = _side_for_layer(drawing.GetLayer())
        if channel:
            obstacle(rect_from_box(drawing.GetBoundingBox()), channel,
                     'board drawing', 'drawing:' + _uid(drawing))
        elif drawing.GetLayer() == pcbnew.Edge_Cuts:
            signature.append(('outline', _uid(drawing),
                              *rect_from_box(drawing.GetBoundingBox()).as_list(),
                              *_xy(drawing.GetStart()), *_xy(drawing.GetEnd())))

    if wanted != selected:
        raise ValueError('Selected components disappeared. Preview again.')
    if len(labels) > MAX_LABELS:
        raise ValueError(f'Too many labels (>{MAX_LABELS}). Narrow your selection.')
    if not labels:
        detail = ', '.join(f'{count} {name}' for name, count in sorted(skipped.items()))
        raise ValueError(f'No editable reference/value fields found in {len(selected)} components. '
                         + (detail + '. ' if detail else '')
                         + 'For locked placement, enable Text on locked footprints; '
                         'the component stays locked and stationary. For hidden references, '
                         'enable Show hidden references. Individually locked text stays protected.')
    signature.sort(key=repr)
    return (labels, obstacles, dict(fields=fields, signature=signature),
            _board_polygon(board, config.clearance))


def _preview_plan(board: Any, ids: list[str], include_values: bool,
                  config: Config) -> tuple[list[dict], list, dict, bool]:
    labels, obstacles, snapshot, polygon = _scan(board, ids, include_values, config)
    rows = _choose(labels, obstacles, config, polygon)
    for row in rows:
        field = snapshot['fields'][row['key']]
        row['layer'] = (config.target_layer if config.target_layer != 'keep' and
                        row['status'] != 'unplaced'
                        else str(board.GetLayerName(field.GetLayer())))
        row['thickness'] = (config.text_thickness if config.text_thickness and
                            row['status'] != 'unplaced' else
                            field.GetTextThickness() / IU_PER_MM)
        if row['status'] == 'unplaced':
            row['size'] = _text_size(field)[1]
    return rows, snapshot['signature'], snapshot['fields'], polygon is not None


def _validate_scope(payload: dict) -> tuple[str, bool, Config]:
    scope = str(payload.get('scope', 'selected')).lower()
    if scope not in ('selected', 'all'):
        raise ValueError('Choose selected components or entire PCB.')
    return scope, bool(payload.get('include_values', False)), Config.from_payload(payload)


def _effective_config(board, config):
    rules = board.GetDesignSettings()
    warnings = []
    if config.target_layer in ('keep', 'F.SilkS', 'B.SilkS'):
        changes = {'clearance': max(config.clearance, rules.m_SilkClearance / IU_PER_MM)}
        if config.standard_size:
            changes['standard_size'] = max(config.standard_size,
                                            rules.m_MinSilkTextHeight / IU_PER_MM)
        if config.text_thickness:
            changes['text_thickness'] = max(config.text_thickness,
                                             rules.m_MinSilkTextThickness / IU_PER_MM)
        if any(getattr(config, key) != value for key, value in changes.items()):
            warnings.append('Text settings raised to the board silkscreen minima.')
        config = replace(config, **changes)
    if config.standard_size and config.text_thickness > config.standard_size / 3:
        raise ValueError('Stroke is too thick for the selected text height; use height/3 or less.')
    return config, warnings


def native_dispatch(board: Any, operation: str, payload: dict) -> dict:
    """Run only from TraceForge native_bridge on KiCad's in-editor wx GUI thread."""
    global _PREVIEW
    if operation == 'text_layout_preview':
        scope, values, config = _validate_scope(payload)
        config, warnings = _effective_config(board, config)
        ids = _selection_ids(board, scope)
        rows, signature, _fields, bounded = _preview_plan(board, ids, values, config)
        token = secrets.token_hex(14)
        _PREVIEW = dict(board=str(board.GetFileName()), token=token,
                        ids=ids, config=config, values=values,
                        signature=signature, rows=rows)
        counts = {name: sum(row['status'] == name for row in rows)
                  for name in ('move', 'keep', 'unplaced')}
        aligned = sum(bool(r.get('bank')) for r in rows)
        return dict(token=token, rows=rows, counts=counts, board_outline=bounded,
                    aligned=aligned, warnings=warnings,
                    message=f"{counts['move']} labels can be repositioned; "
                            f"{counts['unplaced']} need manual placement. "
                            f"{aligned} references aligned in rows/columns. "
                            + ' '.join(warnings) + ' '
                            + ('' if bounded else 'No valid Edge.Cuts outline found.'))
    if operation != 'text_layout_apply':
        raise ValueError('Unsupported text-layout operation: ' + operation)
    saved = _PREVIEW
    _PREVIEW = None  # A preview is always single-use.
    if not saved or saved['token'] != payload.get('token'):
        raise ValueError('Preview expired. Preview again before applying.')
    if str(board.GetFileName()) != saved['board']:
        raise ValueError('The open PCB changed. Preview again.')
    rows, signature, fields, _ = _preview_plan(
        board, saved['ids'], saved['values'], saved['config'])
    if signature != saved['signature'] or rows != saved['rows']:
        raise ValueError('Board geometry or text changed since preview. Preview again.')
    changes = [row for row in rows if row['status'] == 'move']
    if not changes:
        return dict(moved=0, skipped=sum(r['status'] == 'unplaced' for r in rows),
                    message='No collision-safe text changes needed.')

    # Leverage the existing TraceForge ActionPlugin transaction for real KiCad
    # Undo. Avoid modifying the board outside that native transaction.
    from signal_path_analyzer.stitching_native import transaction

    def apply(live):
        # No footprints, pad properties, nets, orientations or geometry moved.
        current_by_fp = {_uid(fp): fp for fp in live.GetFootprints()}
        for row in changes:
            owner_uuid, kind = row['key'].split(':', 1)
            fp = current_by_fp.get(owner_uuid)
            if fp is None:
                raise RuntimeError('A component disappeared during apply.')
            if kind.startswith('graphic:'):
                field = next((g for g in fp.GraphicalItems()
                              if _uid(g) == kind.removeprefix('graphic:')), None)
                if field is None:
                    raise RuntimeError('A reference text copy disappeared during apply.')
            else:
                field = fp.Reference() if kind == 'reference' else fp.Value()
            _, _, degrees = row['new']
            field.SetTextAngleDegrees(float(degrees))
            if saved['config'].target_layer != 'keep':
                field.SetLayer(_target_layer_id(saved['config'].target_layer))
                field.SetMirrored(saved['config'].target_layer.startswith('B.'))
            if row.get('center_text'):
                import pcbnew
                field.SetHorizJustify(pcbnew.GR_TEXT_H_ALIGN_CENTER)
                field.SetVertJustify(pcbnew.GR_TEXT_V_ALIGN_CENTER)
            if saved['config'].text_thickness:
                field.SetAutoThickness(False)
                field.SetTextThickness(round(saved['config'].text_thickness * IU_PER_MM))
            if kind == 'reference' and saved['config'].show_hidden_refs:
                field.SetVisible(True)
            if saved['config'].standard_size:
                size = round(saved['config'].standard_size * IU_PER_MM)
                import pcbnew
                field.SetTextSize(pcbnew.VECTOR2I(size, size))
            field.SetPosition(_v((row['new'][0], row['new'][1])))
            actual = _xy(field.GetPosition())
            if (abs(actual[0] - row['new'][0]) > 0.000005 or
                    abs(actual[1] - row['new'][1]) > 0.000005):
                raise RuntimeError(f'KiCad refused to move {row["reference"]} text. '
                                   'Undo the transaction.')
        import pcbnew
        pcbnew.Refresh()
        skipped = sum(r['status'] == 'unplaced' for r in rows)
        return dict(moved=len(changes), skipped=skipped,
                    message=f'Arranged {len(changes)} labels. '
                            f'{skipped} crowded labels remain. KiCad Undo restores changes.')
    return transaction(board, apply)


def create_tab(parent: Any, host: Any, native_call: Any) -> Any:
    """Create an embeddable wx.Panel (call this in TraceForge's UI process)."""
    import wx

    class AutoTextPanel(wx.Panel):
        def __init__(self):
            super().__init__(parent)
            self.host = host
            self.native = native_call
            self.token: Optional[str] = None
            self.records = []
            self.setting_style = False
            if getattr(host, 'dark', False):
                self.SetBackgroundColour('#222C3A')
                self.SetForegroundColour('#E5EDF8')

            root = wx.BoxSizer(wx.VERTICAL)
            title = wx.StaticText(self, label='Auto Text | Readable reference layout')
            title.SetFont(title.GetFont().Bold())
            root.Add(title, 0, wx.ALL, 10)
            explain = wx.StaticText(self, label=(
                'Arranges component references on your chosen text layer, '
                'with consistent typography and ordered rows/columns. '
                'Protects existing polarity marks, pin labels and assembly graphics. '
                'Preview first; unresolved crowded labels stay untouched.'))
            explain.Wrap(760)
            root.Add(explain, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

            settings = wx.FlexGridSizer(cols=4, vgap=8, hgap=10)
            settings.AddGrowableCol(1, 1)
            settings.AddGrowableCol(3, 1)
            settings.Add(wx.StaticText(self, label='Scope'), 0, wx.ALIGN_CENTER_VERTICAL)
            self.scope = wx.Choice(self, choices=['Selected footprints', 'Entire PCB'])
            self.scope.SetSelection(0)
            settings.Add(self.scope, 1, wx.EXPAND)
            settings.Add(wx.StaticText(self, label='Destination layer'), 0,
                         wx.ALIGN_CENTER_VERTICAL)
            self.layer = wx.Choice(self, choices=['Keep current layers', *TARGET_LAYERS])
            self.layer.SetSelection(0)
            settings.Add(self.layer, 1, wx.EXPAND)
            settings.Add(wx.StaticText(self, label='Text style'), 0, wx.ALIGN_CENTER_VERTICAL)
            self.style = wx.Choice(self, choices=[
                'Uniform references', 'Preserve existing typography', 'Custom'])
            self.style.SetSelection(0)
            settings.Add(self.style, 1, wx.EXPAND)
            settings.Add(wx.StaticText(self, label='Clearance (mm)'), 0, wx.ALIGN_CENTER_VERTICAL)
            self.clearance = wx.TextCtrl(self, value='0.25')
            settings.Add(self.clearance, 1, wx.EXPAND)
            settings.Add(wx.StaticText(self, label='Search radius (mm)'), 0,
                         wx.ALIGN_CENTER_VERTICAL)
            self.radius = wx.TextCtrl(self, value='8')
            settings.Add(self.radius, 1, wx.EXPAND)
            settings.Add(wx.StaticText(self, label='Text height (mm; 0 = keep)'), 0,
                         wx.ALIGN_CENTER_VERTICAL)
            self.size = wx.TextCtrl(self, value='1.0')
            settings.Add(self.size, 1, wx.EXPAND)
            settings.Add(wx.StaticText(self, label='Stroke (mm; 0 = keep)'), 0,
                         wx.ALIGN_CENTER_VERTICAL)
            self.stroke = wx.TextCtrl(self, value='0.15')
            settings.Add(self.stroke, 1, wx.EXPAND)
            settings.Add(wx.StaticText(self, label='Alignment grid (mm; 0 = off)'), 0,
                         wx.ALIGN_CENTER_VERTICAL)
            self.grid_size = wx.TextCtrl(self, value='0.25')
            settings.Add(self.grid_size, 1, wx.EXPAND)
            root.Add(settings, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

            choices = wx.WrapSizer(wx.HORIZONTAL)
            self.include_values = wx.CheckBox(self, label='Also arrange visible values')
            self.show_hidden = wx.CheckBox(self, label='Show hidden references')
            self.reference_copies = wx.CheckBox(self, label='Include reference text copies')
            self.reference_copies.SetValue(True)
            self.locked_text = wx.CheckBox(self, label='Text on locked footprints')
            self.horizontal = wx.CheckBox(self, label='Prefer horizontal text')
            self.horizontal.SetValue(True)
            self.preserve = wx.CheckBox(self, label='Keep already-clear nearby labels')
            self.preserve.SetValue(True)
            self.banks = wx.CheckBox(self, label='Align repeated rows / columns')
            self.banks.SetValue(True)
            for opt in (self.include_values, self.show_hidden, self.reference_copies,
                        self.locked_text, self.horizontal,
                        self.preserve, self.banks):
                choices.Add(opt, 0, wx.RIGHT | wx.ALIGN_CENTER_VERTICAL, 15)
            root.Add(choices, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

            actions = wx.BoxSizer(wx.HORIZONTAL)
            self.preview_button = wx.Button(self, label='Preview placement')
            self.apply_button = wx.Button(self, label='Apply safe placements')
            self.apply_button.Enable(False)
            self.preview_button.Enable(native_call is not None)
            self.preview_button.Bind(wx.EVT_BUTTON, self.on_preview)
            self.apply_button.Bind(wx.EVT_BUTTON, self.on_apply)
            actions.Add(self.preview_button, 0, wx.RIGHT, 10)
            actions.Add(self.apply_button, 0)
            root.Add(actions, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

            self.summary = wx.StaticText(
                self, label='Select footprints in PCB Editor, then Preview.')
            root.Add(self.summary, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
            self.grid = wx.ListCtrl(self, style=wx.LC_REPORT | wx.BORDER_SUNKEN)
            for index, (heading, width) in enumerate([
                ('Component', 112), ('Field', 78), ('Result', 95), ('Layer', 100),
                ('New X (mm)', 100), ('New Y (mm)', 100), ('Angle', 65),
                ('Height / stroke (mm)', 150),
                ('Detail', 380),
            ]):
                self.grid.InsertColumn(index, heading, width=width)
            root.Add(self.grid, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
            footer = wx.StaticText(self, label=(
                'Default style: 1.0 mm height / 0.15 mm stroke; board silkscreen minima take '
                'precedence. Numbers are adjustable TraceForge defaults. Preview is read-only. '
                'Apply uses KiCad Undo; inspect crowded labels and run DRC afterward.'))
            footer.Wrap(740)
            root.Add(footer, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
            self.SetSizer(root)

            # Changing any option invalidates a previous plan.
            for control in (self.clearance, self.radius, self.size, self.stroke, self.grid_size):
                control.Bind(wx.EVT_TEXT, self.invalidate_event)
            for control in (self.include_values, self.show_hidden, self.reference_copies,
                        self.locked_text, self.horizontal,
                            self.preserve, self.banks):
                control.Bind(wx.EVT_CHECKBOX, self.invalidate_event)
            self.scope.Bind(wx.EVT_CHOICE, self.invalidate_event)
            self.layer.Bind(wx.EVT_CHOICE, self.invalidate_event)
            self.style.Bind(wx.EVT_CHOICE, self.on_style)

        def message(self, text: str, state: str = 'pending') -> None:
            self.summary.SetLabel(text)
            if hasattr(host, 'colors') and state in host.colors:
                self.summary.SetForegroundColour(host.colors[state])
            self.Layout()

        def invalidate_event(self, event) -> None:
            if not self.setting_style and event.GetEventObject() in (self.size, self.stroke):
                self.style.SetSelection(2)
            self.invalidate()
            event.Skip()

        def on_style(self, _event) -> None:
            self.setting_style = True
            try:
                if self.style.GetSelection() == 0:
                    self.size.SetValue('1.0')
                    self.stroke.SetValue('0.15')
                elif self.style.GetSelection() == 1:
                    self.size.SetValue('0')
                    self.stroke.SetValue('0')
            finally:
                self.setting_style = False
            self.invalidate()

        def invalidate(self) -> None:
            self.token = None
            self.apply_button.Enable(False)

        def options(self) -> dict:
            return dict(scope='selected' if self.scope.GetSelection() == 0 else 'all',
                        target_layer=('keep' if self.layer.GetSelection() == 0 else
                                      self.layer.GetStringSelection()),
                        show_hidden_refs=self.show_hidden.GetValue(),
                        include_reference_copies=self.reference_copies.GetValue(),
                        text_on_locked_footprints=self.locked_text.GetValue(),
                        align_banks=self.banks.GetValue(),
                        grid_mm=_finite(self.grid_size.GetValue(), 'Grid', 0, 1),
                        text_thickness=_finite(self.stroke.GetValue(), 'Stroke', 0, .5),
                        include_values=self.include_values.GetValue(),
                        prefer_horizontal=self.horizontal.GetValue(),
                        preserve_good=self.preserve.GetValue(),
                        clearance=_finite(self.clearance.GetValue(), 'Clearance', .05, 2),
                        max_distance=_finite(self.radius.GetValue(), 'Search radius', 1, 30),
                        standard_size=_finite(self.size.GetValue(), 'Text size', 0, 3))

        def _submit(self, task, done) -> None:
            if hasattr(host, 'submit_stitching'):
                host.submit_stitching(task, done, self)
            else:
                # Standalone host compatibility; caller must guarantee that the
                # native_call executes in the editor thread (never direct pcbnew
                # calls across process/thread boundaries).
                try:
                    done(task())
                except Exception as exc:
                    self.message(str(exc), 'pending')
                    wx.MessageBox(str(exc), 'Auto Text', wx.OK | wx.ICON_ERROR, self)

        def on_preview(self, _event=None) -> None:
            self.invalidate()
            try:
                options = self.options()
            except ValueError as exc:
                wx.MessageBox(str(exc), 'Invalid Auto Text settings', wx.OK | wx.ICON_WARNING, self)
                return
            self.message('Analyzing component labels…')
            def done(result):
                self.token = result.get('token')
                self.records = result.get('rows', [])
                self.grid.DeleteAllItems()
                for row in self.records:
                    x, y, deg = row['new']
                    idx = self.grid.InsertItem(self.grid.GetItemCount(), row['reference'])
                    for col, entry in enumerate((row['kind'], row['status'], row['layer'],
                                                  f'{x:.3f}', f'{y:.3f}',
                                                  f'{deg:g}°',
                                                  f'{row["size"]:g} / {row["thickness"]:g}',
                                                  row['why']), 1):
                        self.grid.SetItem(idx, col, str(entry))
                moved = result.get('counts', {}).get('move', 0)
                self.apply_button.Enable(bool(moved and self.token))
                self.message(result.get('message', 'Preview ready.'),
                             'ok' if moved else 'pending')
            self._submit(lambda: self.native('text_layout_preview', **options), done)

        def on_apply(self, _event=None) -> None:
            if not self.token:
                self.message('Preview again before applying.')
                return
            token = self.token
            self.invalidate()
            self.message('Applying reviewed label changes…')
            def done(result):
                self.message(result.get('message', 'Applied.'), 'ok')
                if hasattr(host, 'refresh_policy'):
                    host.refresh_policy.invalidate()
            self._submit(lambda: self.native('text_layout_apply', token=token), done)

        def on_refresh(self, _event=None) -> None:
            self.invalidate()
            self.message('Select footprints, then Preview placement.')
    return AutoTextPanel()


def _self_test() -> None:
    # These tests run without KiCad/wx, covering collision & deterministic logic.
    body1 = Rect(0, 0, 3, 3)
    body2 = Rect(8, 0, 11, 3)
    labels = [
        Label('a:reference', 'a', 'U1', 'Reference', 'F', body1, 'U1',
              (1.5, 1.5), 0, (1, 1), (1.9, 1)),
        Label('b:reference', 'b', 'U2', 'Reference', 'F', body2, 'U2',
              (9.5, 1.5), 90, (1, 1), (1.9, 1)),
    ]
    obs = [Obstacle(body1, 'F', 'component', 'one'),
           Obstacle(body2, 'F', 'component', 'two'),
           Obstacle(Rect(0.2, -2, 2.7, -0.4), 'F', 'pad', 'p1'),
           Obstacle(Rect(5.2, 0.5, 5.9, 2), '*', 'hole', 'h1')]
    cfg = Config(clearance=0.25, max_distance=8, preserve_good=True)
    result = _choose(labels, obs, cfg)
    assert len(result) == 2 and all(r['status'] == 'move' for r in result), result
    index = SpatialIndex()
    for item in obs:
        index.add(item)
    for row, label in zip(result, labels):
        x, y, ang = row['new']
        w, h = _text_dims(label, ang, cfg.standard_size)
        box = centered(x, y, w, h)
        assert not index.collisions(box, label.side, cfg.clearance), row
        index.add(Obstacle(box, label.side, 'reserved', row['key']))
    assert result == _choose(labels, obs, cfg), 'Planner should be deterministic.'
    # A truly blocked board must leave the label alone and report it.
    cover = Obstacle(Rect(-50, -50, 50, 50), '*', 'blocked', 'all')
    result = _choose(labels[:1], [cover], cfg)
    assert result[0]['status'] == 'unplaced'
    # Additional obstacle should not cause preview-time modifications.
    assert labels[0].position == (1.5, 1.5)
    print('PASS: collision rejection, safe move, deterministic results, no-solution handling')


if __name__ == '__main__':
    import sys
    if sys.argv[1:] == ['--self-test']:
        _self_test()
    else:
        raise SystemExit('This module is imported by TraceForge. '
                         'Run --self-test for its pure-Python tests.')
