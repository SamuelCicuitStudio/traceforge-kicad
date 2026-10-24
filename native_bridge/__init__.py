"""KiCad 10 legacy plugin loader for TraceForge native board access."""
import pcbnew
import wx

from .server import start


class NativeBridgePlugin(pcbnew.ActionPlugin):
    def defaults(self):
        self.name = 'TraceForge: Native board access'
        self.category = 'TraceForge'
        self.description = 'Enable direct KiCad 10 board access for TraceForge'
        self.show_toolbar_button = False

    def Run(self):
        start()
        wx.MessageBox('Native TraceForge board access is enabled.', 'TraceForge')


NativeBridgePlugin().register()
# Called after KiCad finishes discovering legacy plugins, on its existing GUI thread.
wx.CallAfter(start)
