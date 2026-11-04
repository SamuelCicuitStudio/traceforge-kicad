"""Small in-memory check for TraceForge's native PCB rotation."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pcbnew

from signal_path_analyzer import board_rotate_native as rotate
from signal_path_analyzer import stitching_native as undo_bridge


def point(x, y):
    return pcbnew.VECTOR2I(round(x * 1_000_000), round(y * 1_000_000))


board = pcbnew.BOARD()
footprint = pcbnew.FOOTPRINT(board)
footprint.SetReference('U1')
footprint.SetPosition(point(10, 10))
pad = pcbnew.PAD(footprint)
pad.SetPosition(point(12, 10))
footprint.Add(pad)
board.Add(footprint)

polygon = pcbnew.PCB_SHAPE(board)
polygon.SetShape(pcbnew.SHAPE_T_POLY)
polygon.SetPolyPoints([point(20, 20), point(24, 20), point(24, 22), point(20, 22)])
polygon.SetLayer(pcbnew.Dwgs_User)
board.Add(polygon)

zone = pcbnew.ZONE(board)
zone.SetLayer(pcbnew.F_Cu)
zone.Outline().NewOutline()
for x, y in ((30, 30), (34, 30), (34, 32), (30, 32)):
    zone.Outline().Append(point(x, y))
board.Add(zone)

rotate._selected = lambda: [footprint]


class FreshBoardWrapper:
    """The ActionPlugin sees a different Python wrapper for the same board."""

    def __init__(self, live):
        self.live = live

    def __getattr__(self, name):
        return getattr(self.live, name)


rotate.refill = lambda live: None
pcbnew.Refresh = lambda: None
pcbnew.GetBoard = lambda: FreshBoardWrapper(board)


class MenuItem:
    def __init__(self, item_id):
        self.item_id = item_id

    def GetId(self):
        return self.item_id


class Editor:
    def __init__(self):
        self.commits = 0
        self.undos = 0

    def GetMenuBar(self):
        return self

    def GetMenus(self):
        return [(object(), 'Tools')]

    def GetEventHandler(self):
        return self

    def ProcessEvent(self, event):
        if event.GetId() == 1:
            self.commits += 1
            undo_bridge.commit_pending()
            return True
        self.undos += 1
        return True


editor = Editor()
undo_bridge.editor_frame = lambda: editor
undo_bridge.menu_item = lambda _menu, label: MenuItem(
    1 if label == undo_bridge.COMMIT_LABEL else 2)

result = rotate.apply(board, 45)
assert result == dict(components=1, shapes=0, zones=0, angle=45.0), result
assert (editor.commits, editor.undos) == (1, 0)
assert round(footprint.GetOrientationDegrees(), 5) == 45, footprint.GetOrientationDegrees()
assert (footprint.GetPosition().x, footprint.GetPosition().y) == (10_000_000, 10_000_000)
assert (pad.GetPosition().x, pad.GetPosition().y) != (12_000_000, 10_000_000)
assert polygon.GetPolyShape().CVertex(0) == point(20, 20)
assert zone.Outline().CVertex(0) == point(30, 30)

for invalid in (0, 'nan', 'inf', 361, 'forty-five'):
    try:
        rotate._angle(invalid)
    except ValueError:
        pass
    else:
        raise AssertionError(f'Invalid angle accepted: {invalid}')

print('Native rotation: footprint and angle validation OK')
