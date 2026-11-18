"""Run with KiCad Python: hidden full-panel navigation; no live board or user settings edits."""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import wx  # noqa: E402

from signal_path_analyzer import hub_ui  # noqa: E402
from signal_path_analyzer.workspaces import LEGACY_TO_TOOL, TOOLS  # noqa: E402

app = wx.App(False)
if hub_ui.kicad_dark_theme() and hasattr(app, "MSWEnableDarkMode"):
    app.MSWEnableDarkMode(1)
with tempfile.TemporaryDirectory() as folder:
    hub_ui.SETTINGS = Path(folder) / "settings.json"
    tools = hub_ui.Tools(
        lambda: [],
        lambda *args: 0,
        lambda *args: 0,
        lambda *args: "",
        lambda: None,
        lambda *args: "",
        lambda: "",
    )
    panel = hub_ui.TraceForgePanel(tools)
    panel.overlay.Stop()
    panel.activity_timer.Stop()
    panel.schedule_auto_refresh = lambda: None
    panel.unrouted.on_refresh = lambda: None
    panel.visualization.on_refresh = lambda: None
    try:
        assert [panel.notebook.GetPageText(i) for i in range(6)] == [
            "Signals",
            "Layout",
            "Vias",
            "Routing",
            "Components",
            "Manufacturing",
        ]
        for target in sorted(TOOLS - {"view", "about"}):
            panel.activate_tool(target)
            assert panel.current_tool() == target, (target, panel.current_tool())
        for old, target in LEGACY_TO_TOOL.items():
            panel.activate_tool(old)
            if target not in ("view", "about"):
                assert panel.current_tool() == target
        panel.activate_tool("components.assets")
        panel.fields_test = panel.components.fields["mpn"]
        panel.fields_test.SetValue("state-survives")
        panel.activate_tool("signals.paths")
        panel.activate_tool("components.assets")
        assert panel.fields_test.GetValue() == "state-survives"
        from signal_path_analyzer import components_ui

        page = panel.components
        page.research = dict(source="https://www.lcsc.com/product-detail/C702221.html")
        page.fields["lcsc"].SetValue("C702221")
        page.fields["mpn"].SetValue("TPS386000RGPR")
        original_submit, original_lookup = page.submit, components_ui.lcsc_retail.lookup_pricing
        document_calls = []

        class DocumentWorker:
            def browser(self, operation, **arguments):
                document_calls.append((operation, arguments))
                return dict(status="downloaded")

        try:
            components_ui.lcsc_retail.lookup_pricing = lambda *args: dict(
                mpn="TPS386000RGPR", datasheet="https://datasheet.lcsc.com/direct.pdf"
            )
            page.submit = lambda function, done: done(function(DocumentWorker()))
            page.on_datasheet()
            assert document_calls == [
                ("download_datasheet", dict(url="https://datasheet.lcsc.com/direct.pdf"))
            ]
        finally:
            page.submit = original_submit
            components_ui.lcsc_retail.lookup_pricing = original_lookup
        panel.SetSize((820, 560))
        panel.Layout()
        if "--screenshots" in sys.argv:
            import ctypes

            capture = ctypes.windll.user32.PrintWindow
            capture.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint]
            panel.Show()
            panel.Raise()
            for target in ["components.search", "components.assets", "manufacturing.cost"]:
                panel.activate_tool(target)
                panel.Layout()
                panel.Refresh()
                panel.Update()
                app.Yield()
                wx.MilliSleep(150)
                app.Yield()
                rect = panel.GetScreenRect()
                bitmap = wx.Bitmap(rect.width, rect.height)
                memory = wx.MemoryDC(bitmap)
                assert capture(panel.GetHandle(), memory.GetHDC(), 2)
                memory.SelectObject(wx.NullBitmap)
                bitmap.SaveFile("build/" + target + "-compact.png", wx.BITMAP_TYPE_PNG)
            panel.Hide()
        print(
            "PASS: six workspaces, all stable IDs, legacy launchers, retained state, compact layout"
        )
    finally:
        if panel.auto_refresh_later:
            panel.auto_refresh_later.Stop()
        panel.components.shutdown()
        panel.bom_cost.shutdown()
        panel.worker.shutdown(wait=True, cancel_futures=True)
        for hid in list(panel.hotkey_ids):
            panel.UnregisterHotKey(hid)
        panel.Destroy()
