"""Native LCSC catalog workspace; shares the tested research prototype backend."""

from __future__ import annotations

import dataclasses
import io
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import wx
import wx.dataview as dv

from . import lcsc_research_backend as api
from .combined_research import CombinedBackend

BG, INPUT, FG, MUTED = "#222c3a", "#17212e", "#e5edf8", "#a8b4c7"
BLUE, GOLD, GREEN = "#285aa0", "#ffd166", "#6ee7a0"


def style(window, primary=False):
    window.SetBackgroundColour(BLUE if primary else BG)
    window.SetForegroundColour(FG)
    return window


def button(parent, label, handler, primary=False):
    control = style(wx.Button(parent, label=label), primary)
    control.Bind(wx.EVT_BUTTON, handler)
    return control


def money(value):
    return format(Decimal(str(value)).normalize(), "f")


def verification_colour(state):
    state = state.casefold()
    if "unavailable" in state or "failed" in state or "error" in state:
        return "#ff8585", "[X]"
    if state in ("confirmed metadata", "confirmed step header"):
        return GREEN, "[OK]"
    if "unverified" in state or "linked" in state:
        return GOLD, "[!]"
    return MUTED, "[-]"


class TierRenderer(dv.DataViewCustomRenderer):
    """Four readable price breaks inside the result row, without horizontal scrolling."""

    def __init__(self):
        super().__init__("string", dv.DATAVIEW_CELL_INERT)
        self.value = ""

    def SetValue(self, value):
        self.value = str(value)
        return True

    def GetValue(self):
        return self.value

    def GetSize(self):
        return wx.Size(155, 68)

    def Render(self, rect, dc, state):
        dc.SetTextForeground(wx.Colour(GOLD))
        for i, line in enumerate(self.value.split("\n")[:4]):
            dc.DrawText(line, rect.x + 5, rect.y + 3 + i * 16)
        return True


class ResultStore(dv.DataViewListStore):
    def GetAttrByRow(self, row, col, attr):
        if col == 1:
            attr.SetColour(wx.Colour("#7dcfff"))
            attr.SetBold(True)
            return True
        if col == 6:
            text = str(self.GetValueByRow(row, col))
            attr.SetColour(
                wx.Colour(GREEN if "Basic" in text else GOLD if "Extended" in text else MUTED)
            )
            if text.startswith("0 /") or "mismatch" in text.casefold():
                attr.SetColour(wx.Colour("#ff8585"))
            attr.SetBold(True)
            return True
        if col in (4, 5):
            attr.SetColour(wx.Colour(GOLD if col == 5 else GREEN))
            attr.SetBackgroundColour(wx.Colour("#332d24" if col == 5 else "#20392f"))
            if col == 4:
                stock = str(self.GetValueByRow(row, col))
                if stock in ("Unknown", "0"):
                    attr.SetColour(wx.Colour(MUTED if stock == "Unknown" else "#ff8585"))
                    attr.SetBackgroundColour(wx.Colour(INPUT))
            attr.SetBold(True)
            return True
        return False


class ResearchPanel(wx.Panel):
    def __init__(self, parent, use_part):
        super().__init__(parent)
        style(self)
        self.use_part = use_part
        self.backend = CombinedBackend()
        self.gate = api.RequestGate()
        self.executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="lcsc-research")
        self.image_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="lcsc-images")
        self.closed = False
        self.requests = {}
        self.loading_jobs = {}
        self.image_requests = []
        self.cancel_action = None
        self.category_items = {}
        self.rebuilding_tree = False
        self.category_filter_timer = None
        self.filter_signature = None
        self.parts, self.categories, self.pending, self.cards = [], [], {}, []
        self.category_source = "retail"
        self.category_id = None
        self.category_ids = ()
        self.page = 1
        self.pages = 1
        self.selected = None
        outer = wx.BoxSizer(wx.VERTICAL)
        search = wx.BoxSizer(wx.HORIZONTAL)
        title = wx.StaticText(self, label="LCSC + JLCPCB / Component Research")
        title.SetForegroundColour("#7dcfff")
        title.SetFont(title.GetFont().Bold())
        outer.Add(title, 0, wx.ALL, 6)
        self.query = wx.SearchCtrl(self, style=wx.TE_PROCESS_ENTER)
        self.query.SetDescriptiveText("Keyword, exact MPN or LCSC C-number")
        self.query.Bind(wx.EVT_TEXT_ENTER, self.search)
        search.Add(self.query, 1, wx.RIGHT, 5)
        search.Add(button(self, "Search", self.search, True), 0, wx.RIGHT, 5)
        search.Add(button(self, "Cancel", self.on_cancel))
        outer.Add(search, 0, wx.EXPAND | wx.ALL, 6)
        loading = wx.BoxSizer(wx.HORIZONTAL)
        self.loading_activity = wx.ActivityIndicator(self)
        loading.Add(self.loading_activity, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self.loading_label = wx.StaticText(self, label="Ready")
        self.loading_label.SetForegroundColour(MUTED)
        loading.Add(self.loading_label, 1, wx.ALIGN_CENTER_VERTICAL)
        outer.Add(loading, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)
        body = wx.BoxSizer(wx.HORIZONTAL)
        left = wx.Panel(self)
        lb = wx.BoxSizer(wx.VERTICAL)
        self.category_find = wx.SearchCtrl(left)
        self.category_find.SetDescriptiveText("Find category...")
        self.category_find.Bind(wx.EVT_TEXT, self.schedule_category_filter)
        lb.Add(self.category_find, 0, wx.EXPAND | wx.BOTTOM, 5)
        self.tree = wx.TreeCtrl(left, style=wx.TR_HIDE_ROOT | wx.TR_HAS_BUTTONS | wx.TR_SINGLE)
        # Native tree rebuild/selection events are not user search commands.
        self.tree.Bind(wx.EVT_LEFT_UP, self.category_clicked)
        self.tree.Bind(wx.EVT_KEY_DOWN, self.category_key)
        lb.Add(self.tree, 1, wx.EXPAND)
        lb.Add(button(left, "Reload categories", self.load_categories), 0, wx.EXPAND | wx.TOP, 5)
        left.SetSizer(lb)
        left.SetMinSize((190, -1))
        body.Add(left, 0, wx.EXPAND | wx.RIGHT, 8)
        right = wx.Panel(self)
        rb = wx.BoxSizer(wx.VERTICAL)
        self.filter_area = wx.ScrolledWindow(right, size=(-1, 183), style=wx.HSCROLL)
        self.filter_area.SetScrollRate(15, 0)
        self.filter_area.SetMinSize((-1, 183))
        self.filter_box = wx.BoxSizer(wx.HORIZONTAL)
        self.filter_area.SetSizer(self.filter_box)
        rb.Add(self.filter_area, 0, wx.EXPAND)
        self.filter_area.Hide()
        bar = wx.BoxSizer(wx.HORIZONTAL)
        self.stock = wx.CheckBox(right, label="LCSC retail stock only")
        bar.Add(self.stock, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.assembly_stock = wx.CheckBox(right, label="JLCPCB stock only")
        self.assembly_stock.Bind(wx.EVT_CHECKBOX, self.assembly_changed)
        bar.Add(self.assembly_stock, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.assembly_tier = wx.Choice(
            right, choices=["All classes", "Basic", "Extended", "Preferred Extended"]
        )
        self.assembly_tier.SetSelection(0)
        self.assembly_tier.Bind(wx.EVT_CHOICE, self.assembly_changed)
        bar.Add(self.assembly_tier, 0, wx.RIGHT, 6)
        self.sort = wx.Choice(
            right, choices=["Default", "Price: low to high", "Price: high to low"]
        )
        self.sort.SetSelection(0)
        bar.Add(self.sort, 1, wx.RIGHT, 6)
        self.page_size = wx.Choice(right, choices=["25", "50", "100"])
        self.page_size.SetSelection(0)
        bar.Add(self.page_size, 0, wx.RIGHT, 6)
        bar.Add(button(right, "Clear filters", self.clear_filters), 0, wx.RIGHT, 5)
        bar.Add(button(right, "Apply filters", self.search, True))
        rb.Add(bar, 0, wx.EXPAND | wx.TOP | wx.BOTTOM, 5)
        self.info = wx.StaticText(
            right, label="Choose a category or search LCSC.", style=wx.ST_ELLIPSIZE_END
        )
        self.info.SetMinSize((1, -1))
        self.info.SetForegroundColour(MUTED)
        rb.Add(self.info, 0, wx.EXPAND | wx.BOTTOM, 4)
        self.results = dv.DataViewListCtrl(
            right, style=dv.DV_ROW_LINES | dv.DV_VERT_RULES | dv.DV_SINGLE
        )
        self.results.AppendIconTextColumn("LCSC / photo", width=140)
        for label, width in [
            ("MPN", 180),
            ("Manufacturer", 115),
            ("Package", 95),
            ("LCSC stock", 105),
        ]:
            self.results.AppendTextColumn(label, width=width)
        self.results.AppendColumn(
            dv.DataViewColumn("Unit price / quantity", TierRenderer(), 5, width=170)
        )
        self.results.AppendTextColumn("JLCPCB stock / class", width=155)
        self.results.AppendColumn(
            dv.DataViewColumn("JLCPCB USD / quantity", TierRenderer(), 7, width=170)
        )
        self.results.SetRowHeight(72)
        self.result_store = ResultStore()
        self.result_store.AppendColumn("wxDataViewIconText")
        for _ in range(7):
            self.result_store.AppendColumn("string")
        self.results.AssociateModel(self.result_store)
        self.results.Bind(dv.EVT_DATAVIEW_SELECTION_CHANGED, self.select)
        rb.Add(self.results, 1, wx.EXPAND)
        paging = wx.BoxSizer(wx.HORIZONTAL)
        self.prev = button(right, "< Previous", lambda e: self.search(page=self.page - 1))
        self.next = button(right, "Next >", lambda e: self.search(page=self.page + 1))
        paging.Add(self.prev)
        self.page_label = wx.StaticText(right, label="Page 1")
        paging.Add(self.page_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 6)
        paging.Add(self.next)
        rb.Add(paging, 0, wx.TOP | wx.BOTTOM, 4)
        self.detail = wx.Panel(right)
        db = wx.BoxSizer(wx.VERTICAL)
        head = wx.BoxSizer(wx.HORIZONTAL)
        self.photo = wx.StaticBitmap(self.detail, size=(56, 56))
        head.Add(self.photo, 0, wx.RIGHT, 6)
        self.identity = wx.StaticText(self.detail, label="", style=wx.ST_ELLIPSIZE_END)
        self.identity.SetMinSize((1, 40))
        self.identity.SetFont(self.identity.GetFont().Bold())
        head.Add(self.identity, 1, wx.ALIGN_CENTER_VERTICAL)
        self.use_button = button(self.detail, "Use in project", self.use_selected, True)
        head.Add(self.use_button, 0, wx.RIGHT, 5)
        head.Add(button(self.detail, "Hide details", self.hide_details, True))
        db.Add(head, 0, wx.EXPAND | wx.BOTTOM, 5)
        columns = wx.BoxSizer(wx.HORIZONTAL)
        self.specs = dv.DataViewListCtrl(self.detail, size=(-1, 112), style=dv.DV_ROW_LINES)
        self.specs.SetMinSize((1, 84))
        self.specs.AppendTextColumn("Specification", width=155)
        self.specs.AppendTextColumn("Value", width=205)
        columns.Add(self.specs, 2, wx.EXPAND | wx.RIGHT, 6)
        self.prices = dv.DataViewListCtrl(self.detail, size=(190, 112))
        self.prices.SetMinSize((1, 84))
        self.prices.AppendTextColumn("Quantity", width=65)
        self.prices.AppendTextColumn("Unit price", width=115)
        columns.Add(self.prices, 1, wx.EXPAND | wx.RIGHT, 6)
        cad = wx.BoxSizer(wx.VERTICAL)
        self.cad_labels = {}
        for name in ("Symbol", "Footprint", "STEP"):
            label = wx.StaticText(self.detail, label=name + ": not checked")
            self.cad_labels[name] = label
            cad.Add(label, 0, wx.BOTTOM, 3)
        cad.AddStretchSpacer(1)
        cb = wx.BoxSizer(wx.HORIZONTAL)
        cb.Add(button(self.detail, "Check CAD", self.check_cad), 0, wx.RIGHT, 4)
        self.verify_button = button(self.detail, "Verify STEP", self.verify_step)
        cb.Add(self.verify_button)
        cad.Add(cb)
        columns.Add(cad, 0, wx.EXPAND)
        db.Add(columns, 0, wx.EXPAND)
        actions = wx.BoxSizer(wx.HORIZONTAL)
        actions.Add(button(self.detail, "All specifications", self.all_specs), 0, wx.RIGHT, 5)
        actions.Add(button(self.detail, "Datasheet", self.datasheet), 0, wx.RIGHT, 5)
        actions.Add(button(self.detail, "Copy CAD record", self.copy_cad))
        db.Add(actions, 0, wx.TOP, 5)
        self.detail.SetSizer(db)
        rb.Add(self.detail, 0, wx.EXPAND | wx.TOP, 4)
        self.detail.Hide()
        right.SetSizer(rb)
        right.SetMinSize((1, 1))
        self.results.SetMinSize((1, 80))
        body.Add(right, 1, wx.EXPAND)
        outer.Add(body, 1, wx.EXPAND | wx.ALL, 6)
        self.SetSizer(outer)
        self.Bind(wx.EVT_SIZE, self.on_size)
        self.colour_children(self)
        wx.CallAfter(self.load_categories)

    def on_size(self, event):
        available = self.results.GetClientSize().width - 18
        bases = [120, 160, 90, 65, 85, 130, 135, 130]
        if available > 700:
            scale = available / sum(bases)
            for col, width in enumerate(bases):
                self.results.GetColumn(col).SetWidth(int(width * scale))
        height = max(115, min(183, int(self.GetClientSize().height * 0.23)))
        if self.filter_area.GetMinSize().height != height:
            self.filter_area.SetMinSize((-1, height))
            for card in self.cards:
                card.SetMinSize((212, height - 18))
            self.filter_area.FitInside()
            self.Layout()
        event.Skip()

    def colour_children(self, parent):
        for child in parent.GetChildren():
            if isinstance(
                child,
                (wx.TextCtrl, wx.SearchCtrl, wx.TreeCtrl, dv.DataViewListCtrl, wx.CheckListBox),
            ):
                child.SetBackgroundColour(INPUT)
                child.SetForegroundColour(FG)
            elif not isinstance(child, wx.Button):
                style(child)
            self.colour_children(child)

    def update_loading(self):
        if self.closed:
            return
        active = [
            kind
            for kind, (version, event) in self.loading_jobs.items()
            if self.gate.current(kind, version, event)
        ]
        labels = {
            "categories": "Loading categories",
            "filters": "Loading filters",
            "search": "Scanning component catalogue",
            "assembly": "Checking supplier stock",
            "details": "Loading selected component",
            "cad": "Verifying CAD assets",
        }
        if active:
            self.loading_activity.Start()
            self.loading_label.SetLabel("Working: " + " / ".join(labels.get(k, k) for k in active))
            self.loading_label.SetForegroundColour(GOLD)
        else:
            self.loading_activity.Stop()
            self.loading_label.SetLabel("Ready")
            self.loading_label.SetForegroundColour(MUTED)

    def task(self, kind, work, done):
        if self.closed:
            return
        version, cancel = self.gate.begin(kind)
        self.loading_jobs[kind] = (version, cancel)
        self.update_loading()

        def run():
            try:
                value, error = work(cancel), None
            except Exception as exc:
                value, error = None, str(exc)
            if not self.closed:
                wx.CallAfter(finish, value, error)

        def finish(value, error):
            self.requests.pop((kind, version), None)
            if self.loading_jobs.get(kind, (None,))[0] == version:
                self.loading_jobs.pop(kind, None)
            self.update_loading()
            if self.closed or not self.gate.current(kind, version, cancel):
                return
            if error:
                self.info.SetLabel(error)
                if kind == "cad":
                    names = ["STEP"] if self.cad_action == "STEP" else ["Symbol", "Footprint"]
                    for name in names:
                        self.cad_labels[name].SetLabel("[X] " + name + ": check failed")
                        self.cad_labels[name].SetForegroundColour("#ff8585")
                        self.cad_labels[name].SetToolTip(error)
            else:
                done(value)

        self.requests[(kind, version)] = self.executor.submit(run)

    def assembly_changed(self, event=None):
        mode = (
            "assembly"
            if self.assembly_tier.GetSelection() or self.assembly_stock.GetValue()
            else "retail"
        )
        if self.category_source != mode:
            self.category_source = mode
            self.category_id = None
            self.category_ids = ()
            self.pending.clear()
            self.set_categories([])
            self.show_filters([])
            self.load_categories()
        self.search()

    def load_categories(self, event=None):
        loader = (
            self.backend.categories_assembly
            if self.category_source == "assembly"
            else self.backend.categories
        )
        self.task("categories", lambda c: loader(c)[0], self.set_categories)

    def set_categories(self, categories):
        self.categories = categories
        self.filter_categories()

    def schedule_category_filter(self, event=None):
        if self.category_filter_timer:
            self.category_filter_timer.Stop()
        self.category_filter_timer = wx.CallLater(180, self.filter_categories)

    def filter_categories(self, event=None):
        if self.closed:
            return
        focus = wx.Window.FindFocus()
        typing = bool(
            focus and (focus == self.category_find or self.category_find.IsDescendant(focus))
        )
        caret = self.category_find.GetSelection() if typing else None
        needle = self.category_find.GetValue().casefold()
        self.rebuilding_tree = True
        self.category_items = {}
        self.tree.Freeze()
        self.tree.DeleteAllItems()
        root = self.tree.AddRoot("Categories")
        item = self.tree.AppendItem(root, "All categories")
        self.tree.SetItemData(item, None)
        self.category_items[int(item.GetID())] = None

        def add(parent, category):
            matches = needle in category.name.casefold()

            def contains(c):
                return needle in c.name.casefold() or any(contains(x) for x in c.children)

            if needle and not contains(category):
                return
            item = self.tree.AppendItem(parent, category.name)
            self.tree.SetItemData(item, category.id)
            self.category_items[int(item.GetID())] = category.id
            for child in category.children:
                add(item, child)
            if needle and not matches:
                self.tree.Expand(item)

        for category in self.categories:
            add(root, category)
        self.tree.UnselectAll()
        self.tree.Thaw()
        self.rebuilding_tree = False
        if typing:
            focus.SetFocus()
            self.category_find.SetSelection(*caret)

    def category_clicked(self, event):
        item, flags = self.tree.HitTest(event.GetPosition())
        event.Skip()
        if flags & (wx.TREE_HITTEST_ONITEMLABEL | wx.TREE_HITTEST_ONITEMICON):
            self.select_category(item)

    def category_key(self, event):
        if event.GetKeyCode() in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER, wx.WXK_SPACE):
            self.select_category(self.tree.GetSelection())
        else:
            event.Skip()

    def category_changed(self, event):
        """Compatibility entry point for explicit category commands, never auto-selection."""
        self.select_category(event.GetItem())

    def select_category(self, item):
        if self.rebuilding_tree or not item.IsOk() or int(item.GetID()) not in self.category_items:
            return
        # Queued events may refer to nodes destroyed by the category text filter.
        # Read the current ID mapping, never dereference an obsolete tree item.
        self.category_id = self.category_items[int(item.GetID())]
        self.category_ids = api.category_leaves(self.categories, self.category_id)
        self.pending.clear()
        self.query.SetValue("")
        self.show_filters([])
        self.search()

    def on_cancel(self, event=None):
        if self.cancel_action:
            self.cancel_action()
        else:
            self.cancel_pending()

    def cancel_pending(self):
        busy = bool(self.requests) or any(not f.done() for f in self.image_requests)
        self.gate.cancel_all()
        for future in list(self.requests.values()) + self.image_requests:
            future.cancel()
        self.requests.clear()
        self.loading_jobs.clear()
        self.update_loading()
        self.image_requests = []
        if not self.closed:
            self.info.SetLabel("Cancelled. You can start another search.")
        return busy

    def reset_context(self, keyword=""):
        self.cancel_pending()
        self.category_id = None
        self.category_ids = ()
        self.pending.clear()
        self.stock.SetValue(False)
        self.assembly_stock.SetValue(False)
        self.assembly_tier.SetSelection(0)
        if self.category_source != "retail":
            self.category_source = "retail"
            self.load_categories()
        self.tree.UnselectAll()
        self.query.SetValue(keyword)
        self.parts = []
        self.results.DeleteAllItems()
        self.hide_details()
        self.show_filters([])
        self.info.SetLabel("Choose a category or search LCSC.")

    def build_query(self, page=1):
        attrs = {k: tuple(v) for k, v in self.pending.items() if not k.startswith("__") and v}
        return api.Query(
            keyword=self.query.GetValue().strip(),
            category_id=self.category_id,
            category_ids=self.category_ids,
            attributes=attrs,
            manufacturers=tuple(self.pending.get("__manufacturer__", [])),
            packages=tuple(self.pending.get("__package__", [])),
            packaging=tuple(self.pending.get("__packaging__", [])),
            in_stock=self.stock.GetValue(),
            assembly_tier=("all", "basic", "extended", "preferred")[
                self.assembly_tier.GetSelection()
            ],
            assembly_stock_only=self.assembly_stock.GetValue(),
            category_source=self.category_source,
            page=page,
            page_size=int(self.page_size.GetStringSelection()),
            sort_field="price" if self.sort.GetSelection() else "",
            sort_dir="desc" if self.sort.GetSelection() == 2 else "asc",
        )

    def search(self, event=None, page=1):
        if api.C_RE.fullmatch(self.query.GetValue().strip()):
            self.category_id = None
            self.category_ids = ()
            self.pending.clear()
            self.stock.SetValue(False)
        assembly_mode = self.assembly_tier.GetSelection() != 0 or self.assembly_stock.GetValue()
        self.stock.Enable(not assembly_mode)
        if assembly_mode:
            self.stock.SetValue(False)
        query = self.build_query(max(1, page))
        self.gate.begin("assembly")
        self.gate.begin("details")
        self.gate.begin("cad")
        self.hide_details()
        self.parts = []
        self.results.DeleteAllItems()
        self.info.SetLabel("Searching component catalogue...")
        self.task("search", lambda c: self.backend.search(query, c), self.show_page)
        # Keep each facet's alternatives available. Querying options with that same
        # facet already selected reduces its choices to the selected value only.
        facets = dataclasses.replace(
            query, attributes={}, manufacturers=(), packages=(), packaging=(), page=1
        )
        self.task("filters", lambda c: self.backend.filter_groups(facets, c)[0], self.show_filters)

    def show_filters(self, groups):
        signature = tuple((g.key, tuple((o.value, o.label) for o in g.options)) for g in groups)
        if signature == self.filter_signature:
            for card in self.cards:
                card.refresh_options()
            return
        searches = {card.group_key: card.find.GetValue() for card in self.cards}
        self.filter_signature = signature
        self.filter_box.Clear(True)
        self.cards = []
        groups = sorted(
            groups,
            key=lambda g: (
                0
                if g.key == "__package__"
                else 1
                if g.key == "__manufacturer__"
                else 3
                if g.key == "__packaging__"
                else 2
            ),
        )
        for group in groups:
            card = wx.Panel(self.filter_area, size=(212, 165))
            card.SetMinSize((212, 165))
            box = wx.BoxSizer(wx.VERTICAL)
            box.Add(wx.StaticText(card, label=group.title), 0, wx.BOTTOM, 3)
            find = wx.SearchCtrl(card)
            find.SetDescriptiveText("Find within " + group.title)
            find.ChangeValue(searches.get(group.key, ""))
            box.Add(find, 0, wx.EXPAND | wx.BOTTOM, 3)
            choices = wx.CheckListBox(card)
            box.Add(choices, 1, wx.EXPAND)
            card.SetSizer(box)

            def fill(event=None, g=group, f=find, cl=choices):
                top = cl.GetTopItem() if cl.GetCount() else 0
                options = [o for o in g.options if f.GetValue().casefold() in o.label.casefold()]
                cl.Set([o.label for o in options])
                cl.options = options
                for i, o in enumerate(options):
                    cl.Check(i, o.value in self.pending.get(g.key, []))
                if options:
                    cl.SetFirstItem(min(max(0, top), len(options) - 1))

            def check(event, g=group, cl=choices):
                values = set(self.pending.get(g.key, []))
                for i, o in enumerate(cl.options):
                    if cl.IsChecked(i):
                        values.add(o.value)
                    else:
                        values.discard(o.value)
                self.pending[g.key] = sorted(values)

            card.group_key, card.find, card.choices = group.key, find, choices
            card.refresh_options = fill
            fill()
            find.Bind(wx.EVT_TEXT, fill)
            choices.Bind(wx.EVT_CHECKLISTBOX, check)
            self.filter_box.Add(card, 0, wx.EXPAND | wx.ALL, 5)
            self.cards.append(card)
        self.filter_area.Show(bool(groups))
        self.colour_children(self.filter_area)
        self.filter_area.FitInside()
        self.Layout()

    def clear_filters(self, event=None):
        self.pending.clear()
        self.assembly_stock.SetValue(False)
        self.assembly_tier.SetSelection(0)
        self.stock.SetValue(False)
        self.assembly_changed()

    def show_page(self, page):
        self.parts = page.parts
        self.page, self.pages = page.current_page, page.total_pages or 1
        self.results.DeleteAllItems()
        for p in self.parts:
            tiers = (
                "\n".join(
                    str(t["quantity"])
                    + "+: "
                    + ("$" if t["currency"] == "USD" else t["currency"] + " ")
                    + money(t["unit_price"])
                    for t in p.price_tiers[:4]
                )
                or "Unknown"
            )
            self.results.AppendItem(
                [
                    dv.DataViewIconText(p.code),
                    p.mpn,
                    p.manufacturer,
                    p.package,
                    "Unknown" if p.stock is None else f"{p.stock:,}",
                    tiers,
                    self.assembly_summary(p),
                    self.assembly_price_text(p),
                ]
            )

        if page.parts:
            self.task("assembly", lambda c: self.backend.enrich(page.parts, c), self.show_assembly)
        self.load_result_images()
        self.page_label.SetLabel(f"Page {self.page} of {self.pages}")
        self.prev.Enable(self.page > 1)
        self.next.Enable(self.page < self.pages)
        self.info.SetToolTip(page.note or f"Observed {page.observed_at}")
        total = page.total if page.total is not None else "Unknown"
        self.info.SetLabel(
            f"{len(page.parts)} displayed / {total} results "
            f"| {page.source} | {page.observed_at} " + page.note
        )
        self.Layout()

    @staticmethod
    def assembly_summary(part):
        stock = "Unknown" if part.assembly_stock is None else f"{part.assembly_stock:,}"
        return "Identity mismatch" if part.identity_warning else stock + " / " + part.assembly_tier

    @staticmethod
    def assembly_price_text(part):
        return (
            "\n".join(
                f"{t['quantity']}+: ${money(t['unit_price'])}"
                for t in part.assembly_prices[:4]
                if t.get("currency") == "USD"
            )
            or "Unknown"
        )

    def show_assembly(self, parts):
        if [p.code for p in parts] != [p.code for p in self.parts]:
            return
        self.parts = parts
        for index, part in enumerate(parts):
            self.results.SetTextValue(
                "Unknown" if part.stock is None else f"{part.stock:,}", index, 4
            )
            self.results.SetTextValue(self.assembly_summary(part), index, 6)
            self.results.SetTextValue(self.assembly_price_text(part), index, 7)
            tiers = (
                "\n".join(
                    f"{t['quantity']}+: ${money(t['unit_price'])}"
                    for t in part.price_tiers[:4]
                    if t.get("currency") == "USD"
                )
                or "Unknown"
            )
            self.results.SetTextValue(tiers, index, 5)
        if self.selected:
            selected = next((p for p in parts if p.code == self.selected.code), None)
            if selected:
                self.selected = selected
                self.render_details(selected)

    def load_result_images(self):
        version, cancel = self.gate.begin("thumbnails")
        parts = list(self.parts)

        def update(row, code, data):
            if self.closed or not self.gate.current("thumbnails", version, cancel):
                return
            if row >= len(self.parts) or self.parts[row].code != code:
                return
            image = wx.Image(io.BytesIO(data))
            if image.IsOk():
                bitmap = wx.Bitmap(image.Scale(44, 44, wx.IMAGE_QUALITY_HIGH))
                self.results.SetValue(dv.DataViewIconText(code, wx.BitmapBundle(bitmap)), row, 0)

        def load(batch):
            for row, part in batch:
                if cancel.is_set() or self.closed:
                    return
                if part.image_url:
                    try:
                        data = self.backend.image(part.image_url, cancel)
                        wx.CallAfter(update, row, part.code, data)
                    except (api.LCSCError, OSError, ValueError):
                        pass

        for offset in range(2):
            self.image_requests.append(
                self.image_executor.submit(load, list(enumerate(parts))[offset::2])
            )

    def hide_details(self, event=None):
        self.selected = None
        self.results.UnselectAll()
        self.detail.Hide()
        self.Layout()

    def select(self, event=None):
        row = self.results.GetSelectedRow()
        if row < 0 or row >= len(self.parts):
            return
        part = self.parts[row]
        self.selected = part
        self.render_details(part)
        self.task("details", lambda c: self.backend.details(part, c), self.detail_loaded)
        if part.image_url:
            self.task(
                "image",
                lambda c: self.backend.image(part.image_url, c),
                lambda data: self.show_image(part.code, data),
            )

    def show_image(self, code, data):
        if self.selected and self.selected.code == code:
            image = wx.Image(io.BytesIO(data)).Scale(56, 56, wx.IMAGE_QUALITY_HIGH)
            self.photo.SetBitmap(wx.Bitmap(image))

    def detail_loaded(self, part):
        if self.selected and self.selected.code == part.code:
            if self.selected.assembly_source != "not checked":
                part = dataclasses.replace(
                    part,
                    **{
                        f.name: getattr(self.selected, f.name)
                        for f in dataclasses.fields(part)
                        if f.name.startswith("assembly_") or f.name == "identity_warning"
                    },
                )
            self.selected = part
            self.render_details(part)

    def render_details(self, part):
        self.identity.SetLabel(
            f"{part.mpn}  /  {part.code}\n{part.manufacturer}  |  {part.package}  |  Stock: "
            + ("Unknown" if part.stock is None else f"{part.stock:,}")
            + " | JLCPCB: "
            + self.assembly_summary(part)
        )
        self.identity.SetToolTip(
            part.description
            + "\nLCSC observed: "
            + part.observed_at
            + "\nJLCPCB observed: "
            + part.assembly_observed_at
            + "\nJLCPCB: "
            + part.assembly_source
        )
        self.specs.DeleteAllItems()
        for name, value in part.specs.items():
            self.specs.AppendItem([name, str(value)])
        self.prices.DeleteAllItems()
        for supplier, tier in [("LCSC", t) for t in part.price_tiers] + [
            ("JLC", t) for t in part.assembly_prices
        ]:
            self.prices.AppendItem(
                [
                    supplier + " " + str(tier["quantity"]) + "+",
                    ("$" if tier["currency"] == "USD" else tier["currency"] + " ")
                    + money(tier["unit_price"]),
                ]
            )
        for name, state in (
            ("Symbol", part.cad_symbol),
            ("Footprint", part.cad_footprint),
            ("STEP", part.cad_step),
        ):
            colour, mark = verification_colour(state)
            label = self.cad_labels[name]
            label.SetLabel(f"{mark} {name}: {state}")
            label.SetForegroundColour(colour)
            label.SetFont(label.GetFont().Bold())
            label.SetToolTip(
                "Availability/header check only; package and orientation are checked during import."
            )
        self.verify_button.SetBackgroundColour(
            "#20392f" if part.cad_step == "confirmed STEP header" else BLUE
        )
        self.detail.Show()
        self.Layout()

    def use_selected(self, event=None):
        if self.selected:
            self.use_part(self.selected)

    def check_cad(self, event=None):
        self.cad_action = "all"
        if self.selected:
            part = dataclasses.replace(self.selected)
            self.task("cad", lambda c: self.backend.check_cad(part, c), self.detail_loaded)

    def verify_step(self, event=None):
        self.cad_action = "STEP"
        if self.selected:
            part = dataclasses.replace(self.selected)
            self.task("cad", lambda c: self.backend.verify_step(part, c), self.detail_loaded)

    def datasheet(self, event=None):
        if self.selected and self.selected.datasheet_url.startswith("https://"):
            wx.LaunchDefaultBrowser(self.selected.datasheet_url)

    def copy_cad(self, event=None):
        import json

        if self.selected and wx.TheClipboard.Open():
            try:
                wx.TheClipboard.SetData(
                    wx.TextDataObject(json.dumps(self.selected.cad_record(), indent=2))
                )
            finally:
                wx.TheClipboard.Close()

    def all_specs(self, event=None):
        if not self.selected:
            return
        dialog = wx.Dialog(self, title=self.selected.mpn + " / specifications", size=(700, 520))
        box = wx.BoxSizer(wx.VERTICAL)
        table = dv.DataViewListCtrl(dialog, style=dv.DV_ROW_LINES)
        table.AppendTextColumn("Specification", width=280)
        table.AppendTextColumn("Value", width=370)
        for key, value in self.selected.specs.items():
            table.AppendItem([key, str(value)])
        box.Add(table, 1, wx.EXPAND | wx.ALL, 8)
        box.Add(dialog.CreateButtonSizer(wx.OK), 0, wx.EXPAND | wx.ALL, 8)
        dialog.SetSizer(box)
        self.colour_children(dialog)
        dialog.ShowModal()
        dialog.Destroy()

    def shutdown(self):
        self.closed = True
        if self.category_filter_timer:
            self.category_filter_timer.Stop()
        self.cancel_pending()
        self.executor.shutdown(wait=False, cancel_futures=True)
        self.image_executor.shutdown(wait=False, cancel_futures=True)
