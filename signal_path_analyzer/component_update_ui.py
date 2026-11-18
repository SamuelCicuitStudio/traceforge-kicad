"""Read-only pad comparison followed by an explicit undoable selected-reference update."""

from __future__ import annotations

import math

import wx


class PadComparison(wx.Panel):
    def __init__(self, parent):
        super().__init__(parent, size=(-1, 230))
        self.row = None
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.Bind(wx.EVT_PAINT, self.paint)

    def paint(self, event):
        dc = wx.AutoBufferedPaintDC(self)
        dc.SetBackground(wx.Brush("#17202D"))
        dc.Clear()
        if not self.row or self.row.get("status") != "ready":
            return
        # Plot the same footprint-local coordinate frame for both definitions.
        points = [p for key in ("old", "new") for p in self.row[key]["pads"]]
        extent = max([abs(p["local"][i]) + p["size"][i] / 2 for p in points for i in (0, 1)] + [1])
        width, height = self.GetClientSize()
        scale = min(width / 4 - 25, height / 2 - 25) / extent
        for index, (key, color, label) in enumerate(
            [
                ("old", "#7DCFFF", "Current placed footprint"),
                ("new", "#6EE7A0", "Library result (same anchor / side / angle)"),
            ]
        ):
            cx, cy = width * (index * 2 + 1) / 4, height / 2
            dc.SetTextForeground(wx.Colour(color))
            dc.DrawText(label, round(width * index / 2 + 8), 5)
            dc.SetPen(wx.Pen(color, 1))
            dc.SetBrush(wx.TRANSPARENT_BRUSH)
            dc.DrawLine(round(cx - 5), round(cy), round(cx + 5), round(cy))
            dc.DrawLine(round(cx), round(cy - 5), round(cx), round(cy + 5))
            for pad in self.row[key]["pads"]:
                x, y = pad["local"]
                sx, sy = pad["size"]
                angle = math.radians(-pad["local_angle"])
                poly = []
                for dx, dy in [
                    (-sx / 2, -sy / 2),
                    (sx / 2, -sy / 2),
                    (sx / 2, sy / 2),
                    (-sx / 2, sy / 2),
                ]:
                    px = x + dx * math.cos(angle) - dy * math.sin(angle)
                    py = y + dx * math.sin(angle) + dy * math.cos(angle)
                    poly.append(wx.Point(round(cx + px * scale), round(cy + py * scale)))
                dc.DrawPolygon(poly)
                dc.DrawText(str(pad["number"]), round(cx + x * scale), round(cy + y * scale))


class ComponentUpdatePanel(wx.Panel):
    def __init__(self, parent, host, native):
        super().__init__(parent)
        self.host, self.native = host, native
        self.token, self.rows = None, []
        if host.dark:
            self.SetBackgroundColour("#222C3A")
            self.SetForegroundColour("#E5EDF8")
        box = wx.BoxSizer(wx.VERTICAL)
        note = wx.StaticText(
            self,
            label="Refresh only the selected PCB footprints from their "
            "assigned project-local libraries. Identity fields, text layout, "
            "placement and routing stay intact. Electrical pad numbers and "
            "existing routed contacts must match. Run DRC afterwards.",
        )
        note.Wrap(820)
        box.Add(note, 0, wx.EXPAND | wx.ALL, 8)
        row = wx.BoxSizer(wx.HORIZONTAL)
        self.models = wx.CheckBox(
            self, label="Use library 3D models (otherwise keep placed models)"
        )
        self.models.Bind(wx.EVT_CHECKBOX, self.invalidate)
        row.Add(self.models, 1, wx.ALIGN_CENTER_VERTICAL)
        preview = wx.Button(self, label="Preview selected footprints")
        preview.Bind(wx.EVT_BUTTON, self.on_preview)
        preview.Enable(native is not None)
        row.Add(preview)
        self.apply = wx.Button(self, label="Apply selected updates (Undoable)")
        self.apply.Disable()
        self.apply.Bind(wx.EVT_BUTTON, self.on_apply)
        row.Add(self.apply, 0, wx.LEFT, 6)
        box.Add(row, 0, wx.EXPAND | wx.ALL, 8)
        self.table = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        for i, (name, width) in enumerate(
            [("Reference", 95), ("Assigned footprint", 260), ("Result / checks", 440)]
        ):
            self.table.InsertColumn(i, name, width=width)
        self.table.Bind(wx.EVT_LIST_ITEM_SELECTED, self.on_row)
        box.Add(self.table, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)
        self.canvas = PadComparison(self)
        box.Add(self.canvas, 1, wx.EXPAND | wx.ALL, 8)
        self.status = wx.StaticText(self, label="Select footprints in PCB Editor, then preview.")
        box.Add(self.status, 0, wx.EXPAND | wx.ALL, 8)
        self.SetSizer(box)

    def message(self, text, state="pending"):
        self.status.SetLabel(str(text))
        self.status.Wrap(max(300, self.GetClientSize().width - 20))
        self.Layout()

    def invalidate(self, event=None):
        self.token = None
        self.apply.Disable()

    def on_row(self, event):
        self.canvas.row = self.rows[event.GetIndex()]
        self.canvas.Refresh()

    def on_preview(self, event=None):
        self.invalidate()
        models = self.models.GetValue()

        def done(result):
            if not self:
                return
            if self.models.GetValue() != models:
                self.invalidate()
                self.message("Model policy changed; preview again.")
                return
            self.token, self.rows = result["token"], result["rows"]
            self.table.DeleteAllItems()
            for row in self.rows:
                i = self.table.InsertItem(self.table.GetItemCount(), row["reference"])
                self.table.SetItem(i, 1, row["footprint"])
                text = row.get("reason") or (
                    str(row["pads"])
                    + " pads; "
                    + str(row["checked_contacts"])
                    + " routed contacts; "
                    + row["models"]
                )
                self.table.SetItem(i, 2, text)
            if self.rows:
                self.table.Select(0)
                self.canvas.row = self.rows[0]
                self.canvas.Refresh()
            self.apply.Enable(result["ready"])
            self.message(
                "Ready for reviewed selected-reference update."
                if result["ready"]
                else "Blocked updates must be resolved before applying."
            )

        self.host.submit_stitching(
            lambda: self.native("component_update_preview", library_models=models), done, self
        )

    def on_apply(self, event=None):
        token = self.token
        self.invalidate()

        def done(result):
            if not self:
                return
            self.host.refresh_policy.invalidate()
            self.message("Updated " + ", ".join(result["updated"]) + ". " + result["note"])

        self.host.submit_stitching(
            lambda: self.native("component_update_apply", token=token), done, self
        )
