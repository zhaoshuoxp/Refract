"""Format Graph and Format Axes dialogs for Refract's graphs (docs/ui-spec.md
§3.4). They show the values in effect and record only what the user changes,
as overrides (refract.render.formatting); OK returns the new format dict."""

from __future__ import annotations

import copy

from PySide6.QtCore import Signal
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..render import formatting as F
from ..render import qt
from ..render.model import Graph
from ..render.style import DEFAULT


class ColorButton(QPushButton):
    """A swatch; a click opens the colour chooser."""

    changed = Signal(str)

    def __init__(self, color: str = "#000000"):
        super().__init__()
        self.setFixedWidth(64)
        self.set_color(color)
        self.clicked.connect(self._choose)

    def set_color(self, color: str) -> None:
        self.color = color
        pm = QPixmap(36, 14)
        pm.fill(QColor(color))
        self.setIcon(QIcon(pm))

    def _choose(self) -> None:
        """The graph's scheme colours first, then other schemes, then a custom colour (refract.ui.color_menu)."""
        from . import color_menu

        c = color_menu.pick(self, self.color, self.mapToGlobal(self.rect().bottomLeft()))
        if c:
            self.set_color(c)
            self.changed.emit(self.color)


def _size_spin(lo=4.0, hi=72.0, step=0.5) -> QDoubleSpinBox:
    w = QDoubleSpinBox()
    w.setRange(lo, hi)
    w.setSingleStep(step)
    w.setDecimals(1)
    w.setSuffix(" pt")
    return w


def _buttons(dialog: QDialog) -> QDialogButtonBox:
    b = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    b.accepted.connect(dialog.accept)
    b.rejected.connect(dialog.reject)
    return b


class FormatGraphDialog(QDialog):
    """Data sets (colours, symbols, points, lines) and the graph as a whole
    (title, font, legend, size)."""

    def __init__(self, fmt: dict, g: Graph, lay: qt.Layout, set_index: int | None = None, page: str = "sets",
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle("Format Graph")
        self.fmt = copy.deepcopy(fmt or {})
        self.g, self.lay = g, lay
        self._loading = False
        self.tabs = QTabWidget()
        self.tabs.addTab(self._sets_page(), "Data sets")
        self.tabs.addTab(self._graph_page(), "Graph")
        v = QVBoxLayout(self)
        v.addWidget(self.tabs, 1)
        v.addWidget(_buttons(self))
        self.resize(560, 380)
        if g.series:
            self.sets.setCurrentRow(set_index if set_index is not None and 0 <= set_index < len(g.series) else 0)
        self.tabs.setCurrentIndex(1 if page == "graph" or not g.series else 0)

    # ------------------------------------------------------------- data sets
    def _sets_page(self) -> QWidget:
        page = QWidget()
        self.sets = QListWidget()
        self.sets.setFixedWidth(170)
        for s in self.g.series:
            self.sets.addItem(s.title or "(untitled)")
        self.sets.currentRowChanged.connect(self._load_set)
        self.fill = ColorButton()
        self.color = ColorButton()
        self.symbol = QComboBox()
        for k, v in F.SYMBOLS.items():
            self.symbol.addItem(v, k)
        self.size = _size_spin(1.0, 30.0)
        self.points = QCheckBox("Show the individual values")
        self.connect_ = QCheckBox("Connect the points with a line")
        self.reset = QPushButton("Reset to default")
        form = QFormLayout()
        form.addRow("Fill", self.fill)
        form.addRow("Border, symbols, line", self.color)
        form.addRow("Symbol", self.symbol)
        form.addRow("Symbol size", self.size)
        form.addRow("", self.points)
        form.addRow("", self.connect_)
        form.addRow("", self.reset)
        self.fill.changed.connect(self._fill_changed)
        self.color.changed.connect(self._color_changed)
        self.symbol.currentIndexChanged.connect(self._symbol_changed)
        self.size.valueChanged.connect(self._size_changed)
        self.points.toggled.connect(self._points_changed)
        self.connect_.toggled.connect(self._connect_changed)
        self.reset.clicked.connect(self._reset_set)
        row = QHBoxLayout(page)
        row.addWidget(self.sets)
        box = QWidget()
        box.setLayout(form)
        row.addWidget(box, 1)
        return page

    def _set_key(self) -> str:
        return str(self.sets.currentRow())

    def _put(self, **values) -> None:
        if not self._loading and self.sets.currentRow() >= 0:
            self.fmt = F.merged(self.fmt, ["sets", self._set_key()], values)

    def _fill_changed(self, c: str) -> None:
        self._put(fill=c)

    def _color_changed(self, c: str) -> None:
        self._put(color=c)

    def _symbol_changed(self, _i: int) -> None:
        self._put(symbol=self.symbol.currentData())

    def _size_changed(self, v: float) -> None:
        self._put(size=v)

    def _points_changed(self, on: bool) -> None:
        self._put(points=on)

    def _connect_changed(self, on: bool) -> None:
        self._put(connect=on)

    def _reset_set(self) -> None:
        sets = dict(self.fmt.get("sets") or {})
        sets.pop(self._set_key(), None)
        self.fmt = F.merged({**self.fmt, "sets": sets}, [], {})
        self._load_set(self.sets.currentRow(), defaults=True)

    def _load_set(self, i: int, defaults: bool = False) -> None:
        if i < 0 or i >= len(self.g.series):
            return
        s = self.g.series[i]
        over = {} if defaults else (self.fmt.get("sets") or {}).get(str(i), {})
        self._loading = True
        self.fill.set_color(over.get("fill", F.hex_color(s.fill)))
        self.color.set_color(over.get("color", F.hex_color(s.point_color or s.color)))
        self.symbol.setCurrentIndex(max(0, self.symbol.findData(over.get("symbol", s.symbol))))
        self.size.setValue(float(over.get("size", s.symbol_size)))
        has_points = bool(s.points) or "points" in over
        self.points.setChecked(bool(over.get("points", bool(s.points))))
        self.connect_.setChecked(bool(over.get("connect", s.connect)))
        self.fill.setEnabled(s.kind in ("bar", "pie"))
        self.symbol.setEnabled(s.kind in ("points", "scatter") or bool(s.points))
        self.size.setEnabled(self.symbol.isEnabled())
        self.points.setEnabled(has_points)
        self.connect_.setEnabled(self.g.family == "xy" and s.kind == "points")
        self._loading = False

    # ----------------------------------------------------------------- graph
    def _graph_page(self) -> QWidget:
        page = QWidget()
        g, f = self.g, self.fmt
        self.title = QLineEdit(f.get("title", g.title))
        self.title_size = _size_spin()
        self.title_size.setValue(float(f.get("title_size", g.title_style.size or DEFAULT.title_size)))
        self.font = QComboBox()
        self.font.addItems(F.FONTS if g.font in F.FONTS else [g.font, *F.FONTS])
        self.font.setCurrentText(f.get("font", g.font))
        self.legend = QCheckBox("Show the legend")
        self.legend.setChecked(bool(f.get("legend", g.legend)))
        self.legend.setEnabled(g.family not in ("column", "pie"))
        left, top, right, bottom = self.lay.plot
        self.width_ = QDoubleSpinBox()
        self.height_ = QDoubleSpinBox()
        for w, key, cur in ((self.width_, "width", (right - left) / F.POINTS_PER_INCH),
                            (self.height_, "height", (bottom - top) / F.POINTS_PER_INCH)):
            w.setRange(0.5, 12.0)
            w.setDecimals(2)
            w.setSingleStep(0.25)
            w.setSuffix(" in")
            w.setValue(float(f.get(key, round(cur, 2))))
        self._graph_start = self._graph_values()
        form = QFormLayout(page)
        form.addRow("Title", self.title)
        form.addRow("Title size", self.title_size)
        form.addRow("Font", self.font)
        form.addRow("", self.legend)
        form.addRow("X axis length", self.width_)
        form.addRow("Y axis length", self.height_)
        return page

    def _graph_values(self) -> dict:
        return {"title": self.title.text(), "title_size": self.title_size.value(), "font": self.font.currentText(),
                "legend": self.legend.isChecked(), "width": self.width_.value(), "height": self.height_.value()}

    def result_format(self) -> dict:
        """The format with this dialog's changes (graph values only where changed)."""
        now = self._graph_values()
        changed = {k: v for k, v in now.items() if v != self._graph_start[k]}
        return F.merged(self.fmt, [], changed)


class FormatAxesDialog(QDialog):
    """X and Y axes: titles, text sizes, range (blank: automatic), log scale,
    minor ticks, category label angle."""

    ANGLES = (("Automatic", None), ("Horizontal", 0.0), ("45°", 45.0), ("Vertical", 90.0))

    def __init__(self, fmt: dict, g: Graph, lay: qt.Layout, axis: str = "y", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Format Axes")
        self.fmt = copy.deepcopy(fmt or {})
        self.g, self.lay = g, lay
        self.tabs = QTabWidget()
        self.fields: dict[str, dict[str, QWidget]] = {}
        self.start: dict[str, dict] = {}
        for key, label in (("x", "X axis"), ("y", "Y axis")):
            self.tabs.addTab(self._axis_page(key), label)
            self.start[key] = self._values(key)
        v = QVBoxLayout(self)
        v.addWidget(self.tabs, 1)
        v.addWidget(_buttons(self))
        self.tabs.setCurrentIndex(0 if axis == "x" else 1)
        self.resize(460, 360)

    def numeric(self, key: str) -> bool:
        return key == "y" or self.g.family == "xy"

    def _axis_page(self, key: str) -> QWidget:
        page = QWidget()
        ax = self.g.x_axis if key == "x" else self.g.y_axis
        sc = self.lay.x if key == "x" else self.lay.y
        f = self.fmt.get(key) or {}
        w: dict[str, QWidget] = {}
        form = QFormLayout(page)
        w["title"] = QLineEdit(f.get("title", ax.title))
        form.addRow("Title", w["title"])
        w["title_size"] = _size_spin()
        w["title_size"].setValue(float(f.get("title_size", ax.title_style.size or DEFAULT.axis_title_size)))
        form.addRow("Title size", w["title_size"])
        w["label_size"] = _size_spin()
        w["label_size"].setValue(float(f.get("label_size", ax.label_style.size or DEFAULT.tick_label_size)))
        form.addRow("Number / label size", w["label_size"])
        if self.numeric(key):
            for name, auto in (("min", sc.lo), ("max", sc.hi), ("tick", sc.tick)):
                e = QLineEdit("" if f.get(name) is None else f"{f[name]:g}")
                e.setPlaceholderText(f"automatic ({auto:g})" if not (name == "tick" and sc.log) else "a decade")
                w[name] = e
                form.addRow({"min": "Minimum", "max": "Maximum", "tick": "Major tick"}[name], e)
            w["log"] = QCheckBox("Logarithmic (log10)")
            w["log"].setChecked(bool(f.get("log", ax.log)))
            form.addRow("", w["log"])
            w["minor"] = QSpinBox()
            w["minor"].setRange(0, 10)
            w["minor"].setValue(int(f.get("minor", ax.minor)))
            w["minor"].setToolTip("Minor intervals per major tick (log axes: any value shows 2-9 per decade)")
            form.addRow("Minor ticks", w["minor"])
        else:
            w["angle"] = QComboBox()
            for label, a in self.ANGLES:
                w["angle"].addItem(label, a)
            angles = [a for _l, a in self.ANGLES]
            w["angle"].setCurrentIndex(angles.index(f.get("angle")) if f.get("angle") in angles else 0)
            form.addRow("Labels", w["angle"])
        form.addRow(QLabel("Leave a range value blank for Prism's automatic choice."))
        self.fields[key] = w
        return page

    def set_text(self, key: str, name: str, text: str) -> None:
        self.fields[key][name].setText(text)

    def _values(self, key: str) -> dict:
        w = self.fields[key]
        out: dict = {"title": w["title"].text(), "title_size": w["title_size"].value(),
                     "label_size": w["label_size"].value()}
        if "log" in w:
            for name in ("min", "max", "tick"):
                t = w[name].text().strip().replace(",", ".")
                try:
                    out[name] = float(t) if t else None
                except ValueError:
                    out[name] = None
            out["log"] = w["log"].isChecked()
            out["minor"] = w["minor"].value()
        if "angle" in w:
            out["angle"] = w["angle"].currentData()
        return out

    def result_format(self) -> dict:
        fmt = copy.deepcopy(self.fmt)
        for key in ("x", "y"):
            now = self._values(key)
            changed = {k: v for k, v in now.items() if v != self.start[key][k]}  # None: back to automatic
            fmt = F.merged(fmt, [key], changed)
        return fmt
