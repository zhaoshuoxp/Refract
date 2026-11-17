"""Layout sheets (docs/ui-spec.md §3.5): Refract's layouts, where graphs are
placed, moved, resized and arranged on a page, and Prism's layouts shown as
a preview (refract.render.prism_layout) that can be copied into an editable
Refract layout."""

from __future__ import annotations

import copy

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..model.document import LayoutItem
from ..render import page as PG
from ..render import prism_layout as PL
from . import look

PAGES = {"Letter, portrait": (612.0, 792.0), "Letter, landscape": (792.0, 612.0),
         "A4, portrait": (595.28, 841.89), "A4, landscape": (841.89, 595.28)}
HANDLE = 9.0  # px: the resize handle at a selected item's bottom-right corner
PAD = 24.0  # px around the page


class PageCanvas(QWidget):
    """A page drawn on grey with a shadow, fitted to the width of the view.
    In editing mode an item can be selected, dragged and resized; the
    change is reported on release (boxChanged) and Delete removes it."""

    boxChanged = Signal(int, float, float, float, float)  # item, x, y, w, h (page points)
    removeRequested = Signal(int)
    selectionChanged = Signal(int)

    def __init__(self, editable: bool):
        super().__init__()
        self.editable = editable
        self.page: PG.Page | None = None
        self.boxes: list[tuple[float, float, float, float]] = []  # the layout items' boxes (editing)
        self.selected = -1
        self._image, self._image_key = None, None
        self._drag = None  # (mode, index, press point, box at press)
        self._live: tuple[float, float, float, float] | None = None
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMouseTracking(True)
        self.setMinimumSize(300, 300)

    def set_page(self, page: PG.Page, boxes: list | None = None) -> None:
        self.page, self.boxes = page, list(boxes or [])
        self._image = None
        if self.selected >= len(self.boxes):
            self.selected = -1
        self.updateGeometry()
        self.update()

    # ---------------------------------------------------------- geometry
    def scale(self) -> float:
        """The whole page fitted into the visible area (at most 1.5x)."""
        if self.page is None:
            return 1.0
        vp = self.parentWidget()
        w, h = (vp.width(), vp.height()) if vp is not None else (self.width(), self.height())
        return max(0.2, min((w - 2 * PAD) / self.page.width, (h - 2 * PAD) / self.page.height, 1.5))

    def to_page(self, wx: float, wy: float) -> tuple[float, float]:
        k = self.scale()
        return (wx - PAD) / k, (wy - PAD) / k

    def to_widget(self, x: float, y: float) -> tuple[float, float]:
        k = self.scale()
        return PAD + x * k, PAD + y * k

    def _box(self, i: int):
        if self._drag is not None and self._live is not None and self._drag[1] == i:
            return self._live
        return self.boxes[i]

    def item_at(self, wx: float, wy: float) -> tuple[str, int]:
        """("handle" | "item" | "", index) under a widget point."""
        x, y = self.to_page(wx, wy)
        if 0 <= self.selected < len(self.boxes):
            bx, by, bw, bh = self.boxes[self.selected]
            hx, hy = self.to_widget(bx + bw, by + bh)
            if abs(wx - hx) <= HANDLE and abs(wy - hy) <= HANDLE:
                return "handle", self.selected
        for i in range(len(self.boxes) - 1, -1, -1):
            bx, by, bw, bh = self.boxes[i]
            if bx <= x <= bx + bw and by <= y <= by + bh:
                return "item", i
        return "", -1

    # ------------------------------------------------------------- paint
    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), look.color("canvas"))
        if self.page is None:
            return
        k = self.scale()
        w, h = self.page.width * k, self.page.height * k
        for d, alpha in ((4, 25), (2, 45)):
            p.fillRect(QRectF(PAD + d, PAD + d, w, h), QColor(0, 0, 0, alpha))
        dpr = self.devicePixelRatioF()
        key = (k * dpr, id(self.page))
        if self._image is None or self._image_key != key:
            self._image, self._image_key = PG.to_image(self.page, k * dpr), key
            self._image.setDevicePixelRatio(dpr)
        p.drawImage(QPointF(PAD, PAD), self._image)
        if not self.editable:
            return
        p.setRenderHint(QPainter.Antialiasing)
        for i in range(len(self.boxes)):
            bx, by, bw, bh = self._box(i)
            x, y = self.to_widget(bx, by)
            r = QRectF(x, y, bw * k, bh * k)
            if i == self.selected:
                p.setPen(QPen(look.color("accent"), 1.5))
                p.setBrush(Qt.NoBrush)
                p.drawRect(r)
                p.setBrush(look.color("accent"))
                p.drawRect(QRectF(r.right() - HANDLE / 2, r.bottom() - HANDLE / 2, HANDLE, HANDLE))
            else:
                pen = QPen(QColor(160, 165, 172), 0.8, Qt.DashLine)
                p.setPen(pen)
                p.setBrush(Qt.NoBrush)
                p.drawRect(r)
        p.end()

    # ------------------------------------------------------------- mouse
    def mousePressEvent(self, e) -> None:
        if not self.editable or e.button() != Qt.LeftButton:
            return
        mode, i = self.item_at(e.position().x(), e.position().y())
        self.selected = i
        self.selectionChanged.emit(i)
        if i >= 0:
            self._drag = (mode, i, self.to_page(e.position().x(), e.position().y()), self.boxes[i])
            self._live = self.boxes[i]
        self.update()

    def mouseMoveEvent(self, e) -> None:
        if self._drag is None:
            mode, _i = self.item_at(e.position().x(), e.position().y()) if self.editable else ("", -1)
            self.setCursor(Qt.SizeFDiagCursor if mode == "handle" else Qt.ArrowCursor)
            return
        mode, _index, (px, py), (bx, by, bw, bh) = self._drag
        x, y = self.to_page(e.position().x(), e.position().y())
        dx, dy = x - px, y - py
        if mode == "handle":
            self._live = (bx, by, max(36.0, bw + dx), max(36.0, bh + dy))
        else:
            self._live = (bx + dx, by + dy, bw, bh)
        self.update()

    def mouseReleaseEvent(self, e) -> None:
        if self._drag is None:
            return
        _mode, i, _p, start = self._drag
        live, self._drag, self._live = self._live, None, None
        if live is not None and any(abs(a - b) > 0.5 for a, b in zip(live, start, strict=True)):
            self.boxChanged.emit(i, *live)
        self.update()

    def keyPressEvent(self, e) -> None:
        if self.editable and e.key() in (Qt.Key_Delete, Qt.Key_Backspace) and self.selected >= 0:
            self.removeRequested.emit(self.selected)
            return
        super().keyPressEvent(e)


class _Base(QWidget):
    def __init__(self, doc):
        super().__init__()
        self.doc = doc
        self.page: PG.Page | None = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        bar = QWidget()
        bar.setObjectName("zoombar")
        bar.setAttribute(Qt.WA_StyledBackground)
        self.row = QHBoxLayout(bar)
        self.row.setContentsMargins(10, 3, 10, 3)
        outer.addWidget(bar)
        self.notes = QLabel()
        self.notes.setObjectName("muted")
        self.notes.setWordWrap(True)
        self.notes.setContentsMargins(10, 2, 10, 2)
        outer.addWidget(self.notes)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.NoFrame)
        outer.addWidget(self.scroll, 1)

    @property
    def graph(self):  # the window enables Export for views with something to export
        return self.page if self.page is not None and self.page.items else None

    def export(self, path: str) -> None:
        if self.page is None:
            raise ValueError("nothing to export")
        PG.export(self.page, path)

    def _show_notes(self) -> None:
        notes = self.page.notes if self.page else []
        self.notes.setText(("Not drawn: " + "; ".join(notes)) if notes else "")
        self.notes.setVisible(bool(notes))


class PrismLayoutView(_Base):
    """A Prism layout: its graphs drawn by Refract where Prism places them."""

    def __init__(self, doc, index: int):
        super().__init__(doc)
        self.index = index
        self.row.addWidget(QLabel("Preview of a Prism layout (its graphs as Refract draws them)"))
        self.row.addStretch(1)
        self.copy_button = QPushButton("Copy as Refract Layout")
        self.copy_button.setToolTip("An editable Refract layout with these graphs in the same places")
        self.copy_button.clicked.connect(self._copy)
        self.row.addWidget(self.copy_button)
        self.canvas = PageCanvas(editable=False)
        self.scroll.setWidget(self.canvas)
        self.refresh()

    def refresh(self, *_a) -> None:
        try:
            self.page = PL.page(self.doc.project, self.index, self.doc.archive)
        except NotImplementedError as e:
            self.page = PG.Page(200, 100, [], [str(e)])
        self.canvas.set_page(self.page)
        self.copy_button.setEnabled(bool(self.page.items))
        self._show_notes()

    def _copy(self) -> None:
        w = self.window()
        if hasattr(w, "copy_prism_layout"):
            w.copy_prism_layout(self.index)


class NativeLayoutView(_Base):
    """A Refract layout: add, move, resize, arrange and remove graphs."""

    def __init__(self, doc, nl):
        super().__init__(doc)
        self.nl = nl
        self.page_size = QComboBox()
        for name, size in PAGES.items():
            self.page_size.addItem(name, size)
        self.graphs = QComboBox()
        self.add_button = QPushButton("Add Graph")
        self.cols = QSpinBox()
        self.cols.setRange(1, 6)
        self.cols.setValue(2)
        self.cols.setPrefix("columns: ")
        self.arrange_button = QPushButton("Arrange")
        self.remove_button = QPushButton("Remove")
        for w in (QLabel("Page"), self.page_size, QLabel("  Graph"), self.graphs, self.add_button,
                  QLabel("  "), self.cols, self.arrange_button, self.remove_button):
            self.row.addWidget(w)
        self.row.addStretch(1)
        self.page_size.currentIndexChanged.connect(self._page_size_changed)
        self.add_button.clicked.connect(self.add_selected_graph)
        self.arrange_button.clicked.connect(self.arrange)
        self.remove_button.clicked.connect(self.remove_selected)
        self.canvas = PageCanvas(editable=True)
        self.canvas.boxChanged.connect(self._box_changed)
        self.canvas.removeRequested.connect(self.remove_item)
        self.canvas.selectionChanged.connect(self._selection_changed)
        self.scroll.setWidget(self.canvas)
        doc.layoutChanged.connect(self._changed)
        self.refresh()

    def _changed(self, nl) -> None:
        if nl is self.nl:
            self.refresh()

    def refresh(self, *_a) -> None:
        nl = self.nl
        self.page = PG.native_page(nl, self.doc.graph_for)
        self.canvas.set_page(self.page, [(it.x, it.y, it.w, it.h) for it in nl.items])
        self.page_size.blockSignals(True)
        k = next((i for i, (_n, s) in enumerate(PAGES.items()) if abs(s[0] - nl.width) < 1 and abs(s[1] - nl.height) < 1),
                 -1)
        if k < 0:
            self.page_size.addItem(f"Custom, {nl.width / 72:.1f} × {nl.height / 72:.1f} in", (nl.width, nl.height))
            k = self.page_size.count() - 1
        self.page_size.setCurrentIndex(k)
        self.page_size.blockSignals(False)
        cur = self.graphs.currentData()
        self.graphs.clear()
        for ref, title in self.doc.graph_refs():
            self.graphs.addItem(title or "(untitled)", ref)
        self.graphs.setCurrentIndex(max(0, self.graphs.findData(cur)))
        self.add_button.setEnabled(self.graphs.count() > 0)
        self.arrange_button.setEnabled(bool(nl.items))
        self.remove_button.setEnabled(0 <= self.canvas.selected < len(nl.items))
        self._show_notes()

    def _selection_changed(self, i: int) -> None:
        self.remove_button.setEnabled(0 <= i < len(self.nl.items))

    def _page_size_changed(self, _i: int) -> None:
        w, h = self.page_size.currentData()
        self.doc.set_layout(self.nl, "Page size", width=w, height=h)

    def _box_changed(self, i: int, x: float, y: float, w: float, h: float) -> None:
        items = copy.deepcopy(self.nl.items)
        items[i] = LayoutItem(items[i].graph, x, y, w, h)
        self.doc.set_layout(self.nl, "Move graph", items=items)

    def add_graph(self, ref: str) -> None:
        """Add a graph in the first free grid place (the page re-arranged if full)."""
        items = copy.deepcopy(self.nl.items)
        boxes = PG.grid(len(items) + 1, self.nl.width, self.nl.height, self.cols.value() if items else None)
        items.append(LayoutItem(ref, *boxes[-1]))
        self.doc.set_layout(self.nl, "Add graph", items=items)

    def add_selected_graph(self) -> None:
        if self.graphs.currentData():
            self.add_graph(self.graphs.currentData())

    def arrange(self) -> None:
        self.doc.arrange_layout(self.nl, self.cols.value())

    def remove_item(self, i: int) -> None:
        if 0 <= i < len(self.nl.items):
            items = copy.deepcopy(self.nl.items)
            del items[i]
            self.canvas.selected = -1
            self.doc.set_layout(self.nl, "Remove graph", items=items)

    def remove_selected(self) -> None:
        self.remove_item(self.canvas.selected)
