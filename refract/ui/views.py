"""One view per sheet kind (docs/ui-spec.md §3)."""

from __future__ import annotations

import math

from PySide6.QtCore import QPoint, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QAction, QColor, QFont, QKeySequence, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..model.document import Analysis, InfoSheet
from ..render import native, qt
from ..render.model import TextStyle
from ..stats import catalog, report
from ..stats import inputs as INP
from . import look
from .grid import TableSheet


class InfoView(QSplitter):
    def __init__(self, info: InfoSheet):
        super().__init__(Qt.Vertical)
        grid = QTableWidget(len(info.constants), 2)
        grid.setHorizontalHeaderLabels(["Name", "Value"])
        grid.horizontalHeader().setStretchLastSection(True)
        for r, (name, value) in enumerate(info.constants):
            for k, v in enumerate((name, value)):
                it = QTableWidgetItem(str(v))
                it.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
                grid.setItem(r, k, it)
        notes = QPlainTextEdit(info.notes)
        notes.setReadOnly(True)
        self.addWidget(grid)
        self.addWidget(notes)


def _leaf(v) -> bool:
    return not isinstance(v, dict | list)


def _inline(v):
    """A dict holding a scalar "value" shows it on its own row."""
    if isinstance(v, dict) and _leaf(v.get("value", [])) and "value" in v:
        return _short(v["value"]), {k: x for k, x in v.items() if k != "value"}
    return ("" if not _leaf(v) else _short(v)), v


def _title_in(v, depth: int = 0) -> str | None:
    """The first "title" string inside an entry's "id" (data set / column ids)."""
    if depth > 4:
        return None
    if isinstance(v, dict):
        if isinstance(v.get("title"), str):
            return v["title"]
        for x in v.values():
            t = _title_in(x, depth + 1)
            if t:
                return t
    return None


def _fill_tree(parent: QTreeWidgetItem, value) -> None:
    items = value.items() if isinstance(value, dict) else enumerate(value) if isinstance(value, list) else []
    for k, v in items:
        if k in ("$id", "@class"):
            continue
        shown, rest = _inline(v)
        label = str(k) if not isinstance(k, int) else f"[{k}]"
        if isinstance(v, dict) and isinstance(v.get("id"), dict):
            label = _title_in(v["id"]) or label  # entries keyed by internal ids: their data set's title
        if not _leaf(rest) and not rest:
            shown = "—"  # an empty list or group
        it = QTreeWidgetItem(parent, [label, shown])
        if not _leaf(rest) and rest:
            if shown == "":
                f = it.font(0)
                f.setBold(True)
                it.setFont(0, f)
            _fill_tree(it, rest)


def _short(v) -> str:
    if isinstance(v, float):
        return f"{v:.6g}"
    if isinstance(v, bool):
        return "yes" if v else "no"
    return str(v)


def _tree(data) -> QTreeWidget:
    t = QTreeWidget()
    t.setObjectName("results")
    t.setHeaderLabels(["Item", "Value"])
    t.setAlternatingRowColors(True)
    t.setUniformRowHeights(True)
    _fill_tree(t.invisibleRootItem(), data)
    t.expandToDepth(1)
    t.header().setSectionResizeMode(0, QHeaderView.ResizeToContents)
    return t


class Comparison(QWidget):
    """Prism's stored values next to Refract's, value by value."""

    def __init__(self, stored: dict, ours: dict):
        super().__init__()
        self.diffs = INP.compare(stored, ours)
        both = [d for d in self.diffs if d.stored is not None and d.ours is not None]
        self.agree = sum(d.agrees for d in both)
        self.total = len(both)
        self.summary = QLabel(f"{self.agree} of {self.total} values agree (relative difference below 1e-6)."
                              if self.total else "No values in common to compare.")
        self.only = QCheckBox("Show only differences")
        self.only.toggled.connect(self._fill)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Value", "Stored (Prism)", "Refract", ""])
        self.tree.setRootIsDecorated(False)
        self.tree.setUniformRowHeights(True)
        self.tree.setAlternatingRowColors(True)
        top = QHBoxLayout()
        top.addWidget(self.summary, 1)
        top.addWidget(self.only)
        v = QVBoxLayout(self)
        v.addLayout(top)
        v.addWidget(self.tree, 1)
        self._fill(False)
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)

    def _fill(self, only: bool) -> None:
        self.tree.clear()
        bad = look.color("bad")
        for d in self.diffs:
            if only and d.agrees:
                continue
            mark = "✓" if d.agrees else ("—" if d.stored is None or d.ours is None else "≠")
            it = QTreeWidgetItem(self.tree, [d.path.replace("/", " › "), "" if d.stored is None else _short(d.stored),
                                             "" if d.ours is None else _short(d.ours), mark])
            if not d.agrees and d.stored is not None and d.ours is not None:
                for k in range(4):
                    it.setForeground(k, bad)


class ReportPage(QTableWidget):
    """One page of formatted results (refract.stats.report): its tables one
    below the other, headings in bold, values right-aligned; Ctrl+C copies
    the selection as tab-separated text."""

    def __init__(self, page: report.Page):
        super().__init__()
        self.page = page
        ncol = 1 + max((len(t.columns) for t in page.tables), default=1)
        self.setColumnCount(ncol)
        self.horizontalHeader().hide()
        self.verticalHeader().hide()
        self.setShowGrid(False)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setSelectionMode(QAbstractItemView.ContiguousSelection)
        self.setWordWrap(False)
        bold = QFont()
        bold.setBold(True)
        title_font = QFont()
        title_font.setBold(True)
        title_font.setPointSizeF(title_font.pointSizeF() * 1.1)
        bar = look.color("bar")
        lines: list[tuple[str, list[str], str, int]] = []  # label, cells, kind, level
        for k, t in enumerate(page.tables):
            if k:
                lines.append(("", [], "gap", 0))
            if t.title and t.title != page.name:
                lines.append((t.title, [], "title", 0))
            if t.columns != ["Value"]:
                lines.append(("", t.columns, "header", 0))
            lines += [(r.label, r.cells, "head" if r.head else ("sig" if r.flag == "sig" else "row"), r.level)
                      for r in t.rows]
        self.setRowCount(len(lines))
        for i, (lab, cells, kind, level) in enumerate(lines):
            it = QTableWidgetItem("    " * level + lab)
            if kind in ("title", "head", "header"):
                it.setFont(title_font if kind == "title" else bold)
            self.setItem(i, 0, it)
            for j, c in enumerate(cells):
                ci = QTableWidgetItem(c)
                ci.setTextAlignment((Qt.AlignCenter if kind == "header" else Qt.AlignRight) | Qt.AlignVCenter)
                if kind == "header":
                    ci.setFont(bold)
                self.setItem(i, j + 1, ci)
            if kind == "header":
                for j in range(ncol):
                    if self.item(i, j) is None:
                        self.setItem(i, j, QTableWidgetItem(""))
                    self.item(i, j).setBackground(bar)
        self.resizeColumnsToContents()
        for j in range(ncol):
            cap = 420 if j == 0 else (560 if ncol == 2 else 260)  # one value column: room for text
            self.setColumnWidth(j, min(max(self.columnWidth(j) + 16, 70), cap))
        self.verticalHeader().setDefaultSectionSize(22)
        a = QAction("Copy", self)
        a.setShortcut(QKeySequence.Copy)
        a.setShortcutContext(Qt.WidgetShortcut)
        a.triggered.connect(self.copy)
        self.addAction(a)

    def copy(self) -> None:
        rows = sorted({i.row() for i in self.selectedIndexes()}) or range(self.rowCount())
        cols = sorted({i.column() for i in self.selectedIndexes()}) or range(self.columnCount())
        text = "\n".join("\t".join((self.item(r, c).text() if self.item(r, c) else "") for c in cols) for r in rows)
        QApplication.clipboard().setText(text + "\n")


def _result_table(tb: dict) -> QTableWidget:
    """A computed result table, read-only: its columns, a row per entry (numbers to 6 significant digits)."""
    from PySide6.QtWidgets import QAbstractItemView

    rows = tb.get("rows") or []
    w = QTableWidget(len(rows), len(tb.get("columns") or []))
    w.setHorizontalHeaderLabels([str(c) for c in tb.get("columns") or []])
    if tb.get("row_titles"):
        w.setVerticalHeaderLabels([str(t) for t in tb["row_titles"]])
    for r, row in enumerate(rows):
        for c, v in enumerate(row):
            text = "" if v is None else (f"{v:.6g}" if isinstance(v, float) else str(v))
            w.setItem(r, c, QTableWidgetItem(text))
    w.setEditTriggers(QAbstractItemView.NoEditTriggers)
    return w


class ResultView(QWidget):
    """An analysis sheet. On top: what was analysed, whether the values are
    current, which results are shown (Prism's stored ones or Refract's) and
    Change Parameters. Below, on tabs: the results laid out for reading (one
    tab per page), Prism's result tables, the stored and recomputed values
    compared, every value as a tree, and the parameters."""

    def __init__(self, doc, analysis: Analysis):
        super().__init__()
        self.doc, self.analysis = doc, analysis
        bar = QWidget()
        bar.setObjectName("zoombar")
        bar.setAttribute(Qt.WA_StyledBackground)
        row = QHBoxLayout(bar)
        row.setContentsMargins(10, 4, 10, 4)
        self.info = QLabel()
        self.info.setWordWrap(True)
        self.source = QComboBox()
        self.source.addItem("Prism's stored results", "stored")
        self.source.addItem("Refract's results", "refract")
        self.source.currentIndexChanged.connect(self.refresh)  # a bound method, not a lambda holding self
        self.params_button = QPushButton("Change Parameters…")
        self.params_button.clicked.connect(self._change_parameters)
        row.addWidget(self.info, 1)
        row.addWidget(self.source)
        row.addWidget(self.params_button)
        self.tabs = QTabWidget()
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        v.addWidget(bar)
        v.addWidget(self.tabs, 1)
        doc.analysisChanged.connect(self._changed)
        self.refresh()

    def _changed(self, a) -> None:
        if a is self.analysis:
            self.refresh()

    def _meta(self, src) -> list[tuple[str, str]]:
        a = self.analysis
        out = [("Analysis", catalog.describe(a.analysis_class, a.parameters.get("content", {})))]
        if src is not None:
            t, sets = src
            idx = sets if sets is not None else range(len(t.datasets))
            out += [("Table analyzed", t.title),
                    ("Data sets analyzed", ", ".join(t.datasets[i].title or str(i + 1) for i in idx))]
        return out

    def refresh(self, *_a) -> None:
        a, doc = self.analysis, self.doc
        keep = self.tabs.tabText(self.tabs.currentIndex()) if self.tabs.count() else None
        while self.tabs.count():
            w = self.tabs.widget(0)
            self.tabs.removeTab(0)
            w.deleteLater()
        ours = doc.results(a)
        src = doc.source_of(a)
        what = f"<b>{a.title}</b>"
        if src is not None:
            what += f" · data: {src[0].title}"
        stored = a.results.get("content") if not doc.is_new(a) else None
        current = doc.stored_is_current(a)
        computed = None if ("error" in ours and len(ours) == 1) else ours
        has_both = bool(stored) and current
        self.source.setVisible(has_both and computed is not None)
        show_stored = has_both and (computed is None or self.source.currentData() == "stored")
        if computed is None:
            state = f"Refract cannot compute this analysis: {ours['error']}"
        elif doc.is_new(a):
            state = "Computed by Refract from the current data."
        elif current:
            state = "Prism's stored results are current; Refract's recomputation agrees with them on " \
                    "{} of {} values (Compare tab).".format(*self._agreement(stored, computed))
        else:
            state = "Data or parameters changed since the file was saved: Refract's recomputed results."
        if has_both and computed is None:
            state += " Showing Prism's stored results."
        self.info.setText(f"{what}<br><span style='color:{look.colors()['muted']}'>{state}</span>")
        self.params_button.setEnabled(catalog.for_class(a.analysis_class) is not None and src is not None)
        shown = stored if show_stored else computed
        self.comparison = None
        if shown is None:
            self.tabs.addTab(Message(state), "Results")
        else:
            params = a.parameters.get("content", {})
            for page in report.build(shown, params, self._meta(src)):
                self.tabs.addTab(ReportPage(page), page.name)
            if not show_stored:  # the result tables Refract computed (curves, q values, matrices...)
                for name, tb in (shown.get("_tables") or {}).items():
                    self.tabs.addTab(_result_table(tb), name)
            if show_stored:
                for t in doc.project.tables:
                    if t.is_result and t.title.startswith(a.title):
                        self.tabs.addTab(TableSheet(doc, t, read_only=True),
                                         t.title[len(a.title):].strip(": ") or "Table")
        if has_both and computed is not None:
            self.comparison = Comparison(stored, computed)
            self.tabs.addTab(self.comparison, f"Compare ({self.comparison.agree}/{self.comparison.total})")
        if shown is not None:
            self.tabs.addTab(_tree(shown), "All values")
        self.tabs.addTab(_tree({"analysis": a.analysis_class, **a.parameters}), "Parameters")
        for k in range(self.tabs.count()):
            name = self.tabs.tabText(k)
            if keep and (name == keep or (keep.startswith("Compare") and name.startswith("Compare"))):
                self.tabs.setCurrentIndex(k)

    @staticmethod
    def _agreement(stored, computed) -> tuple[int, int]:
        both = [d for d in INP.compare(stored, computed) if d.stored is not None and d.ours is not None]
        return sum(d.agrees for d in both), len(both)

    def tab_names(self) -> list[str]:
        return [self.tabs.tabText(k) for k in range(self.tabs.count())]

    def page(self, name: str) -> ReportPage | None:
        for k in range(self.tabs.count()):
            if self.tabs.tabText(k) == name and isinstance(self.tabs.widget(k), ReportPage):
                return self.tabs.widget(k)
        return None

    def _change_parameters(self) -> None:
        w = self.window()
        if hasattr(w, "change_parameters"):
            w.change_parameters(self.analysis)


class Message(QLabel):
    def __init__(self, text: str):
        super().__init__(text)
        self.setAlignment(Qt.AlignCenter)
        self.setWordWrap(True)
        self.setObjectName("message")


ZOOMS = [("Fit", None), ("50%", 0.5), ("75%", 0.75), ("100%", 1.0), ("150%", 1.5), ("200%", 2.0)]


LETTER = (612.0, 792.0)  # the page a graph sheet shows (points), portrait
PAGE_MARGIN = 36.0  # a graph wider than the page less this on each side turns it landscape


def page_size(lay) -> tuple[float, float]:
    """The sheet's page: US Letter, portrait, or landscape when the graph is
    too wide for portrait; larger still when the graph does not fit either."""
    w, h = LETTER
    if lay.width > w - 2 * PAGE_MARGIN:
        w, h = h, w
    return max(w, lay.width + 2 * PAGE_MARGIN), max(h, lay.height + 2 * PAGE_MARGIN)


class GraphCanvas(QWidget):
    """Draws one graph with refract.render on a white Letter page (the graph
    centred on it, as a graph sheet shows it): the page fitted to the view
    (never above 2x) when `zoom` is None, else at that scale (scrolling).
    A double-click reports the object under the pointer (qt.hit). Exports
    hold the graph alone."""

    activated = Signal(str, int)  # "title" | "x" | "y" | "set" | "graph", data-set index or -1
    textSelected = Signal(str)  # a text object's id ("" when none)
    textMoved = Signal(str, float, float)  # id, dx, dy (points)
    textEdited = Signal(str, str)  # id, new text
    textDeleted = Signal(str)
    # other graph objects (refract.render.qt.object_at): "set.<i>", "bracket.<j>", "shape.<n>"
    objectMoved = Signal(str, float, float)  # id, dx, dy (points)
    shapeEndMoved = Signal(str, int, float, float)  # id, end 1 or 2, dx, dy
    shapeDrawn = Signal(str, float, float, float, float)  # kind, x1, y1, x2, y2 (points from the plot's top-left)

    contextRequested = Signal(str, QPoint, float, float)  # object id ("" none), global point, graph point x, y
    graphMoved = Signal(float, float)  # the whole graph moved on the page (points)
    zoomRequested = Signal(float, QPointF)  # new scale, the widget point to keep in place

    def __init__(self, graph, zoom: float | None = None, selected: str | None = None,
                 page_offset: tuple[float, float] = (0.0, 0.0)):
        super().__init__()
        self.graph = graph
        self.lay = qt.layout(graph)
        self.items = qt.text_items(graph, self.lay)
        self.margins = qt.overflow(graph, self.lay)  # objects beyond the graph's box are drawn too
        self.tool: str | None = None  # a drawing tool: a kind of refract.render.shape_kinds.KINDS
        self.tool_label: str | None = None  # lines with text: the text the new object starts with
        self._draw: tuple | None = None  # drawing: start and current page points
        self._end: int | None = None  # dragging a drawn object's end (1, 2)
        self.selected = selected if selected == "graph" or self._known(selected) else None
        self.group: list[str] = [self.selected] if (self.selected or "").startswith("set.") else []  # sets chosen
        self.editor = None
        self._drag, self._delta = None, (0.0, 0.0)
        self._band = None  # rubber band (widget points): start, current
        self._pan = None  # panning: last widget point
        self._preview = None  # (image, dx, dy) drawn while dragging a text
        self.setFocusPolicy(Qt.ClickFocus)
        self.setMouseTracking(False)
        self.page = page_size(self.lay)
        # the graph's top-left corner on the page: its plot centred (so moving a
        # title does not shift the axes), then where the user moved it
        left, top, right, bottom = self.lay.plot
        self.page_offset = page_offset
        self.graph_at = (self.page[0] / 2 - (left + right) / 2 + page_offset[0],
                         self.page[1] * 0.45 - (top + bottom) / 2 + page_offset[1])
        self._origin, self._k = (20.0, 20.0), 1.0  # where the graph was last drawn, and its scale
        self._page_origin = (20.0, 20.0)
        self._image, self._image_k = None, 0.0  # rendered graph, cached per scale
        self.set_zoom(zoom)

    def set_zoom(self, zoom: float | None) -> None:
        self.zoom = zoom
        if zoom is None:
            self.setMinimumSize(200, 150)
        else:
            self.setMinimumSize(int(self.page[0] * zoom) + 40, int(self.page[1] * zoom) + 40)
        self.update()

    def scale(self) -> float:
        pad = 20
        if self.zoom is not None:
            return self.zoom
        return min((self.width() - 2 * pad) / self.page[0], (self.height() - 2 * pad) / self.page[1], 2.0)

    def sizeHint(self) -> QSize:
        return QSize(int(self.page[0]) + 40, int(self.page[1]) + 40)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), look.color("canvas"))
        k = self.scale()
        if k <= 0:
            return
        w, h = self.page[0] * k, self.page[1] * k
        x, y = max(20, (self.width() - w) / 2), max(20, (self.height() - h) / 2)
        for d, alpha in ((4, 25), (2, 45)):  # soft shadow
            p.fillRect(QRectF(x + d, y + d, w, h), QColor(0, 0, 0, alpha))
        p.fillRect(QRectF(x, y, w, h), QColor(255, 255, 255))
        dpr = self.devicePixelRatioF()
        if self._image is None or self._image_k != k * dpr:
            self._image = qt.to_image(self.graph, k * dpr, lay=self.lay, margins=self.margins)
            self._image_k = k * dpr
            self._image.setDevicePixelRatio(dpr)
        gx, gy = x + self.graph_at[0] * k, y + self.graph_at[1] * k
        self._page_origin, self._origin, self._k = (x, y), (gx, gy), k
        ml, mt = self.margins[0], self.margins[1]  # the image starts this far left of and above the graph
        if self.selected == "graph" and self._drag is not None:
            p.drawImage(QPointF(gx + (self._delta[0] - ml) * k, gy + (self._delta[1] - mt) * k), self._image)
        elif self._preview is not None:
            img, ddx, ddy = self._preview
            p.drawImage(QPointF(gx + ddx * k, gy + ddy * k), img)
        else:
            p.drawImage(QPointF(gx - ml * k, gy - mt * k), self._image)
        self.paint_overlay(p)
        p.end()

    def page_point(self, wx: float, wy: float) -> tuple[float, float]:
        """Widget coordinates -> graph points."""
        return (wx - self._origin[0]) / self._k, (wy - self._origin[1]) / self._k

    def object_at(self, wx: float, wy: float) -> tuple[str, int | None]:
        return qt.hit(self.graph, self.lay, *self.page_point(wx, wy))

    # ------------------------------------------------------ text objects
    def text_at(self, wx: float, wy: float):
        return qt.text_at(self.items, *self.page_point(wx, wy))

    def _known(self, key: str | None) -> bool:
        return key is not None and (any(t.id == key for t in self.items) or
                                    qt.object_box(self.graph, self.lay, key) is not None)

    def object_box(self, key: str | None):
        return qt.object_box(self.graph, self.lay, key) if key else None

    def _ends(self, key: str | None) -> list[tuple[int, float, float]]:
        """A selected object's handles: (end, page x, page y) - a drawn object's
        two ends (corners), a bracket's left and right ends."""
        if key and key.startswith(("bracket.", "abr.")):  # its ends and its legs' tips
            return qt.bracket_handles(self.graph, self.lay, key)
        if not key or not key.startswith("shape."):
            return []
        n = int(key.split(".")[1])
        if n >= len(self.graph.shapes):
            return []
        from ..render.shape_kinds import leg_tips

        sh, (left, top) = self.graph.shapes[n], self.lay.plot[:2]
        return [(k, left + float(sh.get(f"x{k}") or 0), top + float(sh.get(f"y{k}") or 0)) for k in (1, 2)] + \
            [(k, left + x, top + y) for k, x, y in leg_tips(sh)]  # a bracket: its legs' tips too

    def select(self, key: str | None) -> None:
        if key is not None and key != "graph" and not self._known(key):
            key = None
        self.group = [key] if (key or "").startswith("set.") else []
        if key != self.selected:
            self.selected = key
            self.textSelected.emit(key or "")
        self.update()

    def toggle_set(self, key: str) -> None:
        """Shift / Cmd-click on a data set: added to the chosen data sets, or taken out of them."""
        if not (self.selected or "").startswith("set."):
            self.select(key)
            return
        if key in self.group:
            if len(self.group) > 1:
                self.group.remove(key)
                if self.selected == key:
                    self.selected = self.group[0]
        else:
            self.group.append(key)
        self.textSelected.emit(self.selected or "")
        self.update()

    def set_group(self, keys: list[str]) -> None:
        keys = [k for k in keys if self._known(k)]
        if keys:
            self.selected, self.group = keys[0], list(keys)
            self.textSelected.emit(self.selected)
            self.update()

    def item(self, key: str | None):
        return next((t for t in self.items if t.id == key), None)

    def graph_rect(self) -> QRectF:
        """The graph's box in widget coordinates."""
        return QRectF(self._origin[0], self._origin[1], self.lay.width * self._k, self.lay.height * self._k)

    def mousePressEvent(self, e) -> None:
        self.setFocus()
        if self.editor is not None:
            self.finish_edit(True)
        pos = e.position()
        if e.button() == Qt.MiddleButton or (e.button() == Qt.LeftButton and e.modifiers() & Qt.AltModifier):
            self._pan = (pos.x(), pos.y())  # Option-drag or the middle button pans
            self.setCursor(Qt.ClosedHandCursor)
            return
        if e.button() != Qt.LeftButton:
            return
        if self.tool is not None:  # drawing an object: drag from one end (corner) to the other
            pt = self.page_point(pos.x(), pos.y())
            self._draw = (pt, pt)
            return
        pt = self.page_point(pos.x(), pos.y())
        near = [(math.hypot(pt[0] - hx, pt[1] - hy), k) for k, hx, hy in self._ends(self.selected)]
        near = [x for x in near if x[0] <= 5 / max(self._k, 0.1) + 2]
        if near:  # a selected object's handle (the nearest): move that end or leg
            self._end, self._drag, self._delta = min(near)[1], (pos.x(), pos.y()), (0.0, 0.0)
            return
        obj = qt.object_at(self.graph, self.lay, *pt)
        if obj is not None and obj.startswith("set.") and e.modifiers() & (Qt.ShiftModifier | Qt.ControlModifier |
                                                                             Qt.MetaModifier):
            self.toggle_set(obj)  # several data sets chosen together
            return
        if obj is not None and obj.startswith("shape."):  # drawn objects lie on top of everything
            self.select(obj)
            self._drag, self._delta = (pos.x(), pos.y()), (0.0, 0.0)
            return
        t = self.text_at(pos.x(), pos.y())
        if t is not None and t.id.startswith("legend.") and self.selected not in ("legend",) + tuple(
                x.id for x in self.items if x.id.startswith("legend.")):
            t = self.item("legend")  # a first click takes the whole legend, the next one the entry
        if t is not None:
            self.select(t.id)
        elif obj is not None:
            self.select(obj)
        elif self.graph_rect().contains(pos):
            self.select("graph")
        else:
            self.select(None)
            self._band = (pos, pos)
            return
        self._drag = (pos.x(), pos.y())
        self._delta = (0.0, 0.0)

    def mouseMoveEvent(self, e) -> None:
        pos = e.position()
        if self._pan is not None:
            self.panRequested.emit(pos.x() - self._pan[0], pos.y() - self._pan[1])
            self._pan = (pos.x(), pos.y())
            return
        if self._band is not None:
            self._band = (self._band[0], pos)
            self.update()
            return
        if self._draw is not None:
            pt = self.page_point(pos.x(), pos.y())
            if e.modifiers() & Qt.ShiftModifier:  # Shift: lines at 45-degree steps, squares and circles
                pt = _constrained(self._draw[0], pt, self.tool)
            self._draw = (self._draw[0], pt)
            self.update()
            return
        if self._drag is None or self.selected is None:
            return
        self._delta = ((pos.x() - self._drag[0]) / self._k, (pos.y() - self._drag[1]) / self._k)
        if self.selected.startswith("set."):  # data sets are formatted, not moved
            self._delta = (0.0, 0.0)
            return
        if self.selected != "graph":
            self._preview = self._moved_preview(self.selected, *self._delta, end=self._end)
        self.update()

    def mouseReleaseEvent(self, e) -> None:
        if self._pan is not None:
            self._pan = None
            self.unsetCursor()
            return
        if self._band is not None:
            a, b = self._band
            self._band = None
            band = QRectF(a, b).normalized()
            if band.width() > 3 and band.intersects(self.graph_rect()):
                self.select("graph")
            self.update()
            return
        if self._draw is not None:
            (x1, y1), (x2, y2) = self._draw
            self._draw = None
            self.update()
            left, top = self.lay.plot[:2]
            if math.hypot(x2 - x1, y2 - y1) >= 3:
                self.shapeDrawn.emit(self.tool + (":text" if self.tool_label else ""), x1 - left, y1 - top, x2 - left,
                                     y2 - top)
            return
        moved = self._drag is not None and self.selected is not None and math.hypot(*self._delta) >= 1.0
        dx, dy = self._delta
        end, self._end = self._end, None
        self._drag, self._delta, self._preview = None, (0.0, 0.0), None
        self.update()
        if moved and self.selected == "graph":  # the view redraws: this canvas is replaced
            self.graphMoved.emit(round(dx, 2), round(dy, 2))
        elif moved and end is not None:
            self.shapeEndMoved.emit(self.selected, end, round(dx, 2), round(dy, 2))
        elif moved and self.selected.startswith(("shape.", "bracket.", "abr.")):
            self.objectMoved.emit(self.selected, round(dx, 2), round(dy, 2))
        elif moved:
            self.textMoved.emit(self.selected, round(dx, 2), round(dy, 2))

    def _moved_preview(self, key: str, dx: float, dy: float, end: int | None = None):
        """The graph drawn with object `key` moved (dx, dy) - a drawn object's
        `end` only, when given - and where to put it so that its plot stays in
        place: what a drag shows."""
        import copy

        g = copy.deepcopy(self.graph)
        kind, _, rest = key.partition(".")
        if kind == "shape":
            sh = g.shapes[int(rest)]
            if end in (3, 4):  # a leg's tip
                from ..render.shape_kinds import leg_change, legs

                sh[f"leg{end - 2}"] = max(0.0, legs(sh)[end - 3] + leg_change(sh, dx, dy))
            else:
                for k in ((end,) if end else (1, 2)):
                    sh[f"x{k}"] = float(sh.get(f"x{k}") or 0) + dx
                    sh[f"y{k}"] = float(sh.get(f"y{k}") or 0) + dy
        elif kind == "abr":
            from ..render import formatting as FM

            f = {1: {"left": dx}, 2: {"right": dx}, 3: {"leg_first": dy}, 4: {"leg_last": dy}}.get(end) or \
                {"dx": dx, "dy": dy}
            FM._annotation_bracket(g, int(rest), f)
        elif kind == "bracket" and end:
            b = g.significance[int(rest)] = dict(g.significance[int(rest)])
            name, d = {1: ("dl", dx), 2: ("dr", dx), 3: ("ll", dy), 4: ("lr", dy)}[end]
            b[name] = b.get(name, 0.0) + d
        elif kind in ("ann", "note"):
            for k, a in enumerate(g.annotations):
                if a["kind"] == "text" and (a.get("note") == int(rest) if kind == "note" else k == int(rest)
                                            and "note" not in a):
                    a["cx"] += dx
                    a["top"] += dy
        else:
            ox, oy = g.offsets.get(key, (0.0, 0.0))
            g.offsets[key] = (ox + dx, oy + dy)
        lay = qt.layout(g)
        k = self._k * self.devicePixelRatioF()
        m = qt.overflow(g, lay)
        img = qt.to_image(g, k, lay=lay, margins=m)
        img.setDevicePixelRatio(self.devicePixelRatioF())
        return img, self.lay.plot[0] - lay.plot[0] - m[0], self.lay.plot[1] - lay.plot[1] - m[1]

    panRequested = Signal(float, float)
    toolDone = Signal()  # Escape: leave the drawing tool

    def wheelEvent(self, e) -> None:
        """Pinch (or Ctrl / Cmd + wheel) zooms about the pointer; plain scrolling pans."""
        if e.modifiers() & (Qt.ControlModifier | Qt.MetaModifier):
            step = e.angleDelta().y() or e.pixelDelta().y()
            if step:
                self.zoomRequested.emit(self._k * (1.0015 ** step), e.position())
            e.accept()
            return
        e.ignore()  # the scroll area scrolls

    def event(self, e) -> bool:
        from PySide6.QtCore import QEvent

        if e.type() == QEvent.NativeGesture and e.gestureType() == Qt.ZoomNativeGesture:
            self.zoomRequested.emit(self._k * (1.0 + e.value()), e.position())
            return True
        return super().event(e)

    def contextMenuEvent(self, e) -> None:
        """Right-click: the object under the pointer is selected and its menu asked for."""
        if self.editor is not None:
            self.finish_edit(True)
        pos = e.pos()
        x, y = self.page_point(pos.x(), pos.y())
        obj = qt.object_at(self.graph, self.lay, x, y)
        t = self.text_at(pos.x(), pos.y())
        key = obj if obj is not None and obj.startswith("shape.") else (t.id if t is not None else obj)
        if key is None and self.graph_rect().contains(QPointF(pos)):
            key = "graph"
        if not (key in self.group and len(self.group) > 1):  # a right-click on a chosen data set keeps them all
            self.select(key)
        self.contextRequested.emit(key or "", e.globalPos(), x, y)

    def mouseDoubleClickEvent(self, e) -> None:
        t = self.text_at(e.position().x(), e.position().y())
        if t is not None and t.editable:
            self.select(t.id)
            self.edit(t.id)
            return
        kind, i = self.object_at(e.position().x(), e.position().y())
        self.activated.emit(kind, -1 if i is None else i)

    def keyPressEvent(self, e) -> None:
        arrows = {Qt.Key_Left: (-1, 0), Qt.Key_Right: (1, 0), Qt.Key_Up: (0, -1), Qt.Key_Down: (0, 1)}
        if self.selected and e.key() in arrows:  # nudge: 1 pt, 10 with Shift
            dx, dy = arrows[e.key()]
            step = 10.0 if e.modifiers() & Qt.ShiftModifier else 1.0
            if self.selected == "graph":
                self.graphMoved.emit(dx * step, dy * step)
            elif self.selected.startswith(("shape.", "bracket.", "abr.")):
                self.objectMoved.emit(self.selected, dx * step, dy * step)
            elif not self.selected.startswith("set."):
                self.textMoved.emit(self.selected, dx * step, dy * step)
            return
        if (self.selected == "graph" or (self.selected or "").startswith("set.")) and \
                e.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            return
        if self.selected and e.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            self.textDeleted.emit(self.selected)
        elif self.selected and self.item(self.selected) is not None and e.key() in (Qt.Key_Return, Qt.Key_Enter) \
                and self.item(self.selected).editable:
            self.edit(self.selected)
        elif e.key() == Qt.Key_Escape:
            if self.tool is not None:
                self.toolDone.emit()
            self.select(None)
        else:
            super().keyPressEvent(e)

    def widget_rect(self, rect) -> QRectF:
        x0, y0, x1, y1 = rect
        ox, oy, k = self._origin[0], self._origin[1], self._k
        return QRectF(ox + x0 * k, oy + y0 * k, (x1 - x0) * k, (y1 - y0) * k)

    def edit(self, key: str) -> None:
        """Type over a text object in place: the text is drawn where it is,
        in its own font and direction (the Y title bottom up), black on white,
        with a cursor; a hidden line edit takes the keys (input methods,
        selection, the clipboard). Return keeps the text, Escape leaves it,
        clicking elsewhere keeps it."""
        t = self.item(key)
        if t is None:
            return
        from PySide6.QtWidgets import QLineEdit

        self.finish_edit(False)
        ed = QLineEdit(t.text.replace("\n", " / ") if "\n" in t.text else t.text, self)
        ed.setObjectName("textEditor")
        ed.setProperty("key", key)
        ed.setFrame(False)
        ed.setStyleSheet("background: transparent; color: transparent; selection-background-color: transparent;"
                         " selection-color: transparent; border: none;")
        ed.setGeometry(0, 0, 2, 2)  # takes the keys; the canvas draws the text
        ed.returnPressed.connect(lambda: self.finish_edit(True))
        for sig in (ed.textChanged, ed.cursorPositionChanged, ed.selectionChanged):
            sig.connect(self.update)
        ed.installEventFilter(self)
        ed.show()
        ed.setFocus()
        ed.selectAll()
        self.editor = ed
        self.update()

    def eventFilter(self, obj, ev) -> bool:
        from PySide6.QtCore import QEvent

        if obj is self.editor and ev.type() == QEvent.KeyPress and ev.key() == Qt.Key_Escape:
            self.finish_edit(False)
            return True
        if obj is self.editor and ev.type() == QEvent.FocusOut:
            self.finish_edit(True)
        return False

    def finish_edit(self, keep: bool) -> None:
        ed, self.editor = self.editor, None
        if ed is None:
            return
        key, text = ed.property("key"), ed.text()
        ed.hide()
        ed.deleteLater()
        self.update()
        t = self.item(key)
        if keep and t is not None:
            if "\n" in t.text:
                text = text.replace(" / ", "\n")
            if text != t.text:
                self.textEdited.emit(key, text)

    def _paint_editor(self, p) -> None:
        """The text being typed, drawn in place on white, with its cursor."""
        from PySide6.QtGui import QPen

        ed = self.editor
        t = self.item(ed.property("key"))
        if t is None:
            return
        text = ed.text()
        font = qt._sfont(self.graph, t.style or TextStyle(), t.size, t.bold)
        m = qt._metrics(font)
        w = qt.text_width(m, text, qt.TRACK_TEXT)
        cur = qt.text_width(m, text[:ed.cursorPosition()], qt.TRACK_TEXT)
        p.save()
        p.translate(self._origin[0], self._origin[1])
        p.scale(self._k, self._k)
        x0, y0, x1, y1 = t.rect
        p.fillRect(QRectF(x0 - 2, y0 - 1, x1 - x0 + 4, y1 - y0 + 2), QColor(255, 255, 255))  # hide the old text
        ox, oy = t.origin
        if t.angle:
            p.translate(ox, oy)
            p.rotate(t.angle)
            ox = oy = 0.0
        if t.id in ("title", "x.title"):  # centred texts grow both ways
            ox -= (w - (x1 - x0)) / 2
        box = QRectF(ox - 3, oy - m.ascent() - 2, max(w, 8) + 6, m.ascent() + m.descent() + 4)
        p.fillRect(box, QColor(255, 255, 255))
        p.setPen(QPen(look.color("accent"), 0.8))
        p.setBrush(Qt.NoBrush)
        p.drawRect(box)
        if ed.hasSelectedText():
            a = qt.text_width(m, text[:ed.selectionStart()], qt.TRACK_TEXT)
            b = qt.text_width(m, text[:ed.selectionStart() + len(ed.selectedText())], qt.TRACK_TEXT)
            sel = QColor(look.color("accent"))
            sel.setAlpha(70)
            p.fillRect(QRectF(ox + a, oy - m.ascent(), b - a, m.ascent() + m.descent()), sel)
        p.setFont(font)
        p.setPen(qt._qcolor(t.style.color if t.style is not None else (0, 0, 0, 255)))
        qt.draw_text(p, ox, oy, text, qt.TRACK_TEXT)
        p.setPen(QPen(QColor(0, 0, 0), 1.0))
        p.drawLine(QPointF(ox + cur, oy - m.ascent()), QPointF(ox + cur, oy + m.descent()))
        p.restore()

    def _paint_placeholders(self, p) -> None:
        """Empty titles show where a click types one (on screen only)."""
        hint = QColor(look.color("faint"))
        for t in self.items:
            if not t.placeholder or t.text or (self.editor is not None and self.editor.property("key") == t.id):
                continue
            font = qt._sfont(self.graph, t.style or TextStyle(), t.size, t.bold)
            font.setItalic(True)
            p.save()
            p.translate(self._origin[0], self._origin[1])
            p.scale(self._k, self._k)
            p.translate(*t.origin)
            if t.angle:
                p.rotate(t.angle)
            p.setFont(font)
            p.setPen(hint)
            qt.draw_text(p, 0, 0, t.placeholder, qt.TRACK_TEXT)
            p.restore()

    def paint_overlay(self, p) -> None:
        from PySide6.QtGui import QPen

        self._paint_placeholders(p)
        if self.editor is not None:
            self._paint_editor(p)
            return
        if self._band is not None:
            a, b = self._band
            p.setPen(QPen(look.color("accent"), 1.0, Qt.DashLine))
            fill = QColor(look.color("accent"))
            fill.setAlpha(30)
            p.setBrush(fill)
            p.drawRect(QRectF(a, b).normalized())
        if self._draw is not None:  # the object being drawn
            (x1, y1), (x2, y2) = self._draw
            ox, oy, k = self._origin[0], self._origin[1], self._k
            p.setPen(QPen(look.color("accent"), 1.2, Qt.DashLine))
            p.setBrush(Qt.NoBrush)
            left, top = self.lay.plot[:2]
            sh = {"kind": self.tool, "x1": x1 - left, "y1": y1 - top, "x2": x2 - left, "y2": y2 - top,
                  "color": tuple(look.color("accent").getRgb()), "width": 1.2,
                  "label": "*" if (self.tool_label or "") else ""}
            p.save()
            p.translate(ox, oy)
            p.scale(k, k)
            qt._draw_shapes(p, [sh], self.lay, self.graph)
            p.restore()
            return
        for other in self.group[1:] if len(self.group) > 1 else []:  # the other chosen data sets
            ob = self.object_box(other)
            if ob is not None:
                p.setPen(QPen(look.color("accent"), 1.2, Qt.DashLine))
                p.setBrush(Qt.NoBrush)
                p.drawRect(self.widget_rect(ob).adjusted(-3, -3, 3, 3))
        box = self.object_box(self.selected) if self.selected and self.item(self.selected) is None and \
            self.selected != "graph" else None
        if box is not None:  # a data set, a bracket or a drawn object
            dx, dy = self._delta if self._end is None else (0.0, 0.0)
            if self.selected.startswith("set."):
                dx = dy = 0.0
            r = self.widget_rect((box[0] + dx, box[1] + dy, box[2] + dx, box[3] + dy)).adjusted(-3, -3, 3, 3)
            p.setPen(QPen(look.color("accent"), 1.2, Qt.DashLine))
            p.setBrush(Qt.NoBrush)
            if self._preview is None or not self.selected.startswith("shape.") or self._end is None:
                p.drawRect(r)
            p.setBrush(look.color("accent"))
            for k_, hx, hy in self._ends(self.selected):
                ex, ey = (self._delta if self._end in (None, k_) else (0.0, 0.0))
                w = self.widget_rect((hx + ex, hy + ey, hx + ex, hy + ey))
                p.drawEllipse(QPointF(w.x(), w.y()), 4, 4)
            return
        if self.selected == "graph":
            r = self.graph_rect().translated(self._delta[0] * self._k, self._delta[1] * self._k)
            p.setPen(QPen(look.color("accent"), 1.2, Qt.DashLine))
            p.setBrush(Qt.NoBrush)
            p.drawRect(r)
            p.setBrush(look.color("accent"))
            for cx, cy in ((r.left(), r.top()), (r.right(), r.top()), (r.left(), r.bottom()), (r.right(), r.bottom()),
                           (r.center().x(), r.top()), (r.center().x(), r.bottom()), (r.left(), r.center().y()),
                           (r.right(), r.center().y())):
                p.drawRect(QRectF(cx - 3, cy - 3, 6, 6))
            return
        t = self.item(self.selected)
        if t is None:
            return

        x0, y0, x1, y1 = t.rect
        dx, dy = self._delta
        r = self.widget_rect((x0 + dx, y0 + dy, x1 + dx, y1 + dy)).adjusted(-3, -2, 3, 2)
        pen = QPen(look.color("accent"), 1.2, Qt.DashLine)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawRect(r)
        if t.editable:  # corner handles
            p.setBrush(look.color("accent"))
            for cx, cy in ((r.left(), r.top()), (r.right(), r.top()), (r.left(), r.bottom()), (r.right(), r.bottom())):
                p.drawRect(QRectF(cx - 2, cy - 2, 4, 4))


def _constrained(a: tuple[float, float], b: tuple[float, float], tool: str | None) -> tuple[float, float]:
    """End point b with Shift held: lines at 0, 45, 90 degrees; boxes square."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    if tool in ("rect", "ellipse", "circle", "square", "roundrect"):
        d = max(abs(dx), abs(dy))
        return a[0] + math.copysign(d, dx or 1), a[1] + math.copysign(d, dy or 1)
    ang = round(math.atan2(dy, dx) / (math.pi / 4)) * (math.pi / 4)
    r = math.hypot(dx, dy)
    return a[0] + r * math.cos(ang), a[1] + r * math.sin(ang)


class GraphView(QWidget):
    """A graph sheet: rebuilt from the project on refresh(); graphs of edited
    tables autoscale instead of using the ranges cached in the file. A zoom
    bar on top."""

    def __init__(self, doc, index: int):
        super().__init__()
        self.doc, self.index = doc, index
        self.graph = None
        self.canvas: GraphCanvas | None = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        bar = QWidget()
        bar.setObjectName("zoombar")
        bar.setAttribute(Qt.WA_StyledBackground)
        row = QHBoxLayout(bar)
        row.setContentsMargins(10, 3, 10, 3)
        self.zoom = QComboBox()
        self.zoom.addItems([z for z, _ in ZOOMS])
        self.zoom.currentIndexChanged.connect(self._zoom_changed)
        self.size_label = QLabel()
        self.size_label.setObjectName("muted")
        row.addWidget(QLabel("Zoom"))
        row.addWidget(self.zoom)
        self.bar_row = row
        self._extra_controls(row)
        row.addStretch(1)
        row.addWidget(self.size_label)
        outer.addWidget(bar)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.NoFrame)
        from .object_panel import ObjectPanel

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(self.scroll, 1)
        self.tool: str | None = None  # the drawing tool in use (refract.ui.main_window's Draw group)
        self._select_next: str | None = None
        self.panel = ObjectPanel(self)
        body.addWidget(self.panel)
        outer.addLayout(body, 1)
        self.refresh()

    def _extra_controls(self, row) -> None:
        """Subclasses add their own controls to the bar."""

    def _activated(self, kind: str, index: int) -> None:
        w = self.window()
        if hasattr(w, "format_object"):
            w.format_object(kind, None if index < 0 else index)

    def build_graph(self):
        return self.doc.prism_graph(self.index)

    # formatting (the window's Format dialogs work on any graph view)
    def current_format(self) -> dict:
        return self.doc.prism_format(self.index)

    def set_format(self, fmt: dict) -> bool:
        return self.doc.set_prism_format(self.index, fmt)

    def zoom_value(self) -> float | None:
        i = self.zoom.currentIndex()
        if i < len(ZOOMS):
            return ZOOMS[i][1]
        return self.zoom.itemData(i)

    def _zoom_changed(self, i: int) -> None:
        if self.canvas is not None:
            self.canvas.set_zoom(self.zoom_value())

    def zoom_to(self, k: float, anchor=None) -> None:
        """Zoom to scale k (pinch, Ctrl/Cmd + wheel), keeping the page point
        under `anchor` (widget point) where it is."""
        if self.canvas is None:
            return
        k = max(0.1, min(8.0, k))
        bar_h, bar_v = self.scroll.horizontalScrollBar(), self.scroll.verticalScrollBar()
        if anchor is not None:
            px = (anchor.x() - self.canvas._page_origin[0]) / self.canvas._k
            py = (anchor.y() - self.canvas._page_origin[1]) / self.canvas._k
            view_x, view_y = anchor.x() - bar_h.value(), anchor.y() - bar_v.value()
        label = f"{k * 100:.0f}%"
        self.zoom.blockSignals(True)
        while self.zoom.count() > len(ZOOMS):
            self.zoom.removeItem(len(ZOOMS))
        self.zoom.addItem(label, k)
        self.zoom.setCurrentIndex(len(ZOOMS))
        self.zoom.blockSignals(False)
        self.canvas.set_zoom(k)
        self.canvas.adjustSize()
        self.scroll.widget().resize(max(self.scroll.viewport().width(), self.canvas.minimumWidth()),
                                    max(self.scroll.viewport().height(), self.canvas.minimumHeight()))
        self.canvas.repaint()
        if anchor is not None:
            x0, y0 = self.canvas._page_origin
            bar_h.setValue(int(x0 + px * k - view_x))
            bar_v.setValue(int(y0 + py * k - view_y))

    def pan(self, dx: float, dy: float) -> None:
        bar_h, bar_v = self.scroll.horizontalScrollBar(), self.scroll.verticalScrollBar()
        bar_h.setValue(int(bar_h.value() - dx))
        bar_v.setValue(int(bar_v.value() - dy))

    def move_graph(self, dx: float, dy: float) -> bool:
        """Move the graph on its page; one undo step."""
        import copy

        fmt = copy.deepcopy(self.current_format() or {})
        x, y = fmt.get("page") or (0.0, 0.0)
        fmt["page"] = [round(float(x) + dx, 2), round(float(y) + dy, 2)]
        return self.set_format(fmt)

    def refresh(self) -> None:
        keep = self.canvas.selected if self.canvas is not None else None
        keep, self._select_next = getattr(self, "_select_next", None) or keep, None
        edit, self._edit_next = getattr(self, "_edit_next", None), None
        try:
            self.graph = self.build_graph()
            page = (self.current_format() or {}).get("page") or (0.0, 0.0)
            self.canvas = GraphCanvas(self.graph, self.zoom_value(), edit or keep, (float(page[0]), float(page[1])))
            self.canvas.graphMoved.connect(self.move_graph)
            self.canvas.zoomRequested.connect(self.zoom_to)
            self.canvas.panRequested.connect(self.pan)
            self.canvas.activated.connect(self._activated)
            self.canvas.textSelected.connect(self._text_selected)
            self.canvas.textMoved.connect(lambda key, dx, dy: self.change_text(key, move=(dx, dy)))
            self.canvas.textEdited.connect(lambda key, text: self.change_text(key, text=text))
            self.canvas.textDeleted.connect(self.delete_text)
            self.canvas.objectMoved.connect(lambda key, dx, dy: self.change_object(key, {"move": (dx, dy)}))
            self.canvas.shapeEndMoved.connect(lambda key, k, dx, dy: self.change_object(key, {"end": (k, dx, dy)}))
            self.canvas.shapeDrawn.connect(self.add_shape)
            self.canvas.toolDone.connect(lambda: self.set_tool(None))
            self.canvas.contextRequested.connect(self.show_context_menu)
            group, self._group_next = getattr(self, "_group_next", None), None
            if group:  # the chosen data sets stay chosen after the change
                self.canvas.set_group(group)
            self._share_scheme()
            self.set_tool(self.tool)
            if edit:
                self.canvas.edit(edit)
            if self.canvas.selected:
                self._text_selected(self.canvas.selected)  # the toolbar shows the redrawn text's style
            lay, page = self.canvas.lay, self.canvas.page
            self.size_label.setText(f"Graph {lay.width / 72:.2f} × {lay.height / 72:.2f} in on a "
                                    f"{page[0] / 72:g} × {page[1] / 72:g} in page")
            self.scroll.setWidget(self.canvas)
            if hasattr(self, "panel"):
                self.panel.show_for(self.canvas.selected)
        except NotImplementedError as e:
            self.graph, self.canvas = None, None
            self.size_label.setText("")
            self.scroll.setWidget(Message(f"This graph cannot be drawn yet:\n{e}"))

    def _share_scheme(self) -> None:
        """Tell the colour menus which scheme this graph uses (its own colours when none was chosen)."""
        from ..render import schemes
        from . import color_menu
        from . import schemes_dialog as SD

        name = (self.current_format() or {}).get("scheme")
        cols = SD.all_schemes().get(name) if name else None
        if cols:
            color_menu.set_scheme(name, cols)
        elif self.graph is not None:
            color_menu.set_scheme("This graph's colours", schemes.colors_of(self.graph))

    def show_context_menu(self, key: str, pos, x: float, y: float) -> None:
        from . import context_menu

        context_menu.show(self, key, pos, x, y)

    # ---------------------------------------------------- text objects
    def _text_selected(self, key: str) -> None:
        w = self.window()
        if hasattr(w, "_text_controls"):
            w._text_controls(self)
        if hasattr(self, "panel"):
            self.panel.show_for(key or None)

    # ---------------------------------------------------- graph objects
    def set_tool(self, tool: str | None) -> None:
        """Draw lines, arrows, boxes or ellipses by dragging on the graph (None: select)."""
        self.tool = tool
        if self.canvas is not None:
            base, _, lab = (tool or "").partition(":")  # "<kind>:text": a line with text
            self.canvas.tool = base or None
            self.canvas.tool_label = "*" if lab else None
            if tool:
                self.canvas.setCursor(Qt.CrossCursor)
            else:
                self.canvas.unsetCursor()
        w = self.window()
        if hasattr(w, "_tool_changed"):
            w._tool_changed(tool)

    def add_shape(self, kind: str, x1: float, y1: float, x2: float, y2: float) -> str | None:
        """A drawn object (points from the plot's top-left), selected; one undo step."""
        from ..render import formatting

        kind, _, lab = kind.partition(":")
        fmt, key = formatting.add_shape(self.current_format(), kind, x1, y1, x2, y2)
        if lab:  # a line with text: starts with "*", edited in the Format panel
            fmt = formatting.with_shape(fmt, key, {"label": "*"})
        self.tool = None
        self._select_next = key
        if not self.set_format(fmt):
            self._select_next = None
            return None
        self.set_tool(None)
        return key

    def change_object(self, key: str, values: dict) -> bool:
        """Change a graph object (formatting.with_object); one undo step. With several data sets chosen
        (Shift / Cmd-click), a change of one of them is made to every one of them."""
        from ..render import formatting

        keys = self.chosen_sets() if key.startswith("set.") and key in self.chosen_sets() else [key]
        fmt = self.current_format()
        for k in keys:
            fmt = formatting.with_object(fmt, k, dict(values))
        self._select_next, self._group_next = key, keys if len(keys) > 1 else None
        return self.set_format(fmt)

    def chosen_sets(self) -> list[str]:
        """The data sets chosen together on the canvas (the selected one first)."""
        return list(self.canvas.group) if self.canvas is not None and len(self.canvas.group) > 1 else []

    def change_graph(self, values: dict) -> bool:
        from ..render import formatting

        return self.set_format(formatting.merged(self.current_format(), [], values))

    def reset_object(self, key: str | None) -> bool:
        """A data set back to its default look."""
        import copy

        if not key or not key.startswith("set."):
            return False
        keys = self.chosen_sets() if key in self.chosen_sets() else [key]  # every chosen data set
        fmt = copy.deepcopy(self.current_format() or {})
        for k in keys:
            (fmt.get("sets") or {}).pop(k.split(".")[1], None)
        self._select_next, self._group_next = key, keys if len(keys) > 1 else None
        return self.set_format(fmt)

    def selected_text(self) -> str | None:
        return self.canvas.selected if self.canvas is not None else None

    def change_text(self, key: str, **values) -> bool:
        """Change a text object (text, move, style keys); one undo step."""
        from ..render import formatting

        return self.set_format(formatting.with_text(self.current_format(), key, values))

    def delete_text(self, key: str) -> bool:
        from ..render import formatting

        if self.canvas is not None:
            self.canvas.select(None)
        if key.startswith("shape."):
            return self.set_format(formatting.remove_shape(self.current_format(), key))
        if key.startswith(("abr.", "bracket.")):  # a bracket: hidden (with its label)
            fmt = formatting.with_object(self.current_format(), key, {"hidden": True})
            if key.startswith("bracket."):
                fmt = formatting.with_text(fmt, "sig." + key.split(".")[1], {"text": ""})
            return self.set_format(fmt)
        return self.set_format(formatting.remove_text(self.current_format(), key))

    def add_text(self, text: str = "Text") -> str | None:
        """A text box in the middle of the plot, opened for typing."""
        from ..render import formatting

        if self.canvas is None:
            return None
        left, top, right, bottom = self.canvas.lay.plot
        fmt, key = formatting.add_note(self.current_format(), (right - left) / 2, (bottom - top) / 2 - 8, text)
        self._edit_next = key
        if not self.set_format(fmt):
            self._edit_next = None
            return None
        return key

    def text_state(self) -> dict | None:
        """The selected text object's style in effect (for the toolbar)."""
        from ..render import formatting

        key = self.selected_text()
        if key is None or self.graph is None or key.startswith(("set.", "shape.", "bracket.")) or key == "graph":
            return None
        ts = formatting.text_style(self.graph, key)
        size, bold = formatting.text_defaults(key)
        if ts is None:
            return {"key": key, "family": self.graph.font, "size": size, "bold": bold, "italic": False,
                    "underline": False}
        return {"key": key, "family": ts.family or self.graph.font, "size": ts.size or size,
                "bold": bold if ts.bold is None else ts.bold, "italic": ts.italic, "underline": ts.underline}

    def export(self, path: str) -> None:
        if self.graph is None:
            raise ValueError("nothing to export")
        low = path.lower()
        if low.endswith(".pdf"):
            qt.to_pdf(self.graph, path)
        elif low.endswith(".svg"):
            qt.to_svg(self.graph, path)
        else:
            qt.to_png(self.graph, path)


class NativeGraphView(GraphView):
    """A graph made in Refract: built from its table's current data as the
    graph type chosen for it (Change Graph Type), with stars from the
    table's analysis. A new table's graph sheet waits for its type: the
    sheet offers the choice, and opens it the first time it is shown."""

    def __init__(self, doc, ng):
        self.ng = ng
        self._asked = False
        super().__init__(doc, -1)

    def _extra_controls(self, row) -> None:
        from PySide6.QtWidgets import QPushButton

        self.kind_label = QLabel()
        self.change = QPushButton("Change Graph Type…")
        self.change.clicked.connect(self.choose_type)
        self.stars = QComboBox()
        for k, v in (("auto", "Significance stars"), ("ns", "Stars, and ns"), ("none", "No stars")):
            self.stars.addItem(v, k)
        self._sync()
        row.addSpacing(12)
        row.addWidget(self.kind_label)
        row.addWidget(self.change)
        row.addSpacing(12)
        row.addWidget(self.stars)
        self.stars.currentIndexChanged.connect(self._changed)
        self.note = QLabel("Made in Refract")
        self.note.setObjectName("muted")
        self.note.setToolTip("Saved with the project (x-refract/graphs.json), and written as a Prism graph on save")
        row.addSpacing(12)
        row.addWidget(self.note)

    def _sync(self) -> None:
        from ..render import graph_types as GT

        gt = GT.resolve(self.ng.table.kind, self.ng.style)
        self.kind_label.setText(gt.label if gt is not None else "No graph type chosen")
        self.stars.blockSignals(True)
        self.stars.setCurrentIndex(max(0, self.stars.findData(
            "none" if self.ng.stars == "none" else ("ns" if self.ng.show_ns else "auto"))))
        self.stars.blockSignals(False)

    def _changed(self, *_a) -> None:
        stars = self.stars.currentData()
        self.doc.set_native_options(self.ng, stars="none" if stars == "none" else "auto", show_ns=stars == "ns")

    def choose_type(self) -> bool:
        from .graph_wizard import run_wizard

        w = self.window()
        return run_wizard(w, self, first=not self.ng.style) if hasattr(w, "_exec") else False

    def build_graph(self):
        return native.graph(self.doc.project, self.ng, self.doc.results, self.doc.source_of)

    def current_format(self) -> dict:
        return self.ng.format

    def set_format(self, fmt: dict) -> bool:
        return self.doc.set_native_options(self.ng, format=fmt)

    def _activated(self, kind: str, index: int) -> None:
        w = self.window()
        if hasattr(w, "format_object"):
            w.format_object(kind, None if index < 0 else index)

    def refresh(self) -> None:
        if hasattr(self, "stars"):
            self._sync()
        if not self.ng.style:  # waiting for its type
            from PySide6.QtWidgets import QPushButton

            self.graph, self.canvas = None, None
            self.size_label.setText("")
            box = QWidget()
            v = QVBoxLayout(box)
            v.addStretch(1)
            msg = Message(f"Choose how to graph \u201c{self.ng.table.title}\u201d.")
            v.addWidget(msg, 0, Qt.AlignHCenter)
            b = QPushButton("Choose a Graph Type…")
            b.setObjectName("primary")
            b.clicked.connect(self.choose_type)
            v.addWidget(b, 0, Qt.AlignHCenter)
            v.addStretch(2)
            self.scroll.setWidget(box)
            return
        super().refresh()

    def showEvent(self, e) -> None:
        super().showEvent(e)
        if not self.ng.style and not self._asked:  # the first look at a new graph sheet asks for its type
            self._asked = True
            from PySide6.QtCore import QTimer

            QTimer.singleShot(0, self.choose_type)


