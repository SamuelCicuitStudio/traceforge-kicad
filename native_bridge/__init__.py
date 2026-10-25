"""KiCad 10 native toolbar/menu launchers and live pcbnew board helper."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pcbnew
import wx

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from .server import start  # noqa: E402


def launch(script):
    board = pcbnew.GetBoard()
    if board is None or not board.GetFileName():
        wx.MessageBox('Open and save a board before launching TraceForge.', 'TraceForge')
        return
    server = start()
    python = Path(pcbnew.__file__).resolve().parents[2] / ('python.exe' if os.name == 'nt'
                                                        else 'python3')
    if not python.exists():
        wx.MessageBox(f'KiCad Python was not found at {python}.', 'TraceForge')
        return
    env = dict(os.environ)
    env['TRACEFORGE_NATIVE_ENDPOINT'] = str(server.file)
    env['TRACEFORGE_BOARD_FILE'] = board.GetFileName()
    for key in ('KICAD_API_SOCKET', 'KICAD_API_TOKEN', 'KICAD_API_CLIENT_NAME'):
        env.pop(key, None)
    subprocess.Popen([str(python), str(ROOT / script)], env=env,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)


class NativeLauncher(pcbnew.ActionPlugin):
    def __init__(self, label, script, icon, toolbar=False):
        self.label, self.script, self.icon, self.toolbar = label, script, icon, toolbar
        super().__init__()

    def defaults(self):
        self.name = self.label
        self.category = 'TraceForge'
        self.description = 'TraceForge for KiCad 10: direct pcbnew board access'
        self.show_toolbar_button = self.toolbar
        self.icon_file_name = str(ROOT / 'icons' / f'{self.icon}-light-24.png')
        self.dark_icon_file_name = str(ROOT / 'icons' / f'{self.icon}-dark-24.png')

    def Run(self):
        launch(self.script)


class TraceForgeLauncher(NativeLauncher):
    def __init__(self):
        super().__init__('TraceForge', 'traceforge_action.py', 'traceforge', True)


class HighlightLauncher(NativeLauncher):
    def __init__(self):
        super().__init__('TraceForge: Highlight Signal Chain', 'highlight_net_chain_action.py',
                         'highlight-signal-chain')


class ExportLauncher(NativeLauncher):
    def __init__(self):
        super().__init__('TraceForge: Export Signal Paths', 'signal_path_analyzer_action.py',
                         'export-signal-paths')


class MonitorLauncher(NativeLauncher):
    def __init__(self):
        super().__init__('TraceForge: Signal Timing Monitor', 'net_chain_monitor_action.py',
                         'signal-timing-monitor')


class StitchingCommit(pcbnew.ActionPlugin):
    def defaults(self):
        self.name = 'TraceForge: Apply Stitching Changes'
        self.category = 'TraceForge'
        self.description = 'Internal undoable board transaction; use the TraceForge panel'
        self.show_toolbar_button = False

    def Run(self):
        from signal_path_analyzer.stitching_native import commit_pending

        commit_pending()


for _plugin in (TraceForgeLauncher(), HighlightLauncher(), ExportLauncher(), MonitorLauncher(),
                StitchingCommit()):
    _plugin.register()

wx.CallAfter(start)
