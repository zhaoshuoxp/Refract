"""The Format panel beside a graph: the selected object's own settings, as in
a slide editor (docs/ui-spec.md §3.4). A data set's fill, hatch pattern,
border, error bars, symbols and line; a significance bracket's line; a
drawn object's line, dashes and fill; a text's colour and size; with
nothing selected, the graph's background, plotting area and axis colour.

Every change is one formatting override (refract.render.formatting
with_object), one undo step, made through the graph view."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..render import formatting as F
from .format_graph import ColorButton

# what each kind of object is called in the panel's heading
NAMES = {"set": "Data set", "bracket": "Significance bracket", "shape": "Drawn object", "title": "Graph title",
         "legend": "Legend", "note": "Text box", "sig": "Significance label", "ann": "Text", "abr": "Bracket"}


def _width_spin(lo: float = 0.0, hi: float = 20.0, step: float = 0.25) -> QDoubleSpinBox:
    w = QDoubleSpinBox()
    w.setRange(lo, hi)
    w.setSingleStep(step)
    w.setDecimals(2)
    w.setSuffix(" pt")
    w.setKeyboardTracking(False)  # one change when typing is done
    return w


class ObjectPanel(QWidget):
    def __init__(self, view):
        super().__init__()
        self.view = view
        self.key: str | None = None
        self.setObjectName("objectPanel")
        self.setMinimumWidth(220)
        self.setMaximumWidth(280)
        self.box = QVBoxLayout(self)
        self.box.setContentsMargins(10, 8, 10, 8)
        self.heading = QLabel()
        self.heading.setObjectName("panelHeading")
        f = self.heading.font()
        f.setBold(True)
        self.heading.setFont(f)
        self.box.addWidget(self.heading)
        self.form_host = QWidget()
        self.box.addWidget(self.form_host)
        self.box.addStretch(1)
        self.form: QFormLayout | None = None
        self.show_for(None)

    # ------------------------------------------------------------ building
    def _new_form(self) -> QFormLayout:
        old = self.form_host
        self.form_host = QWidget()
        self.box.replaceWidget(old, self.form_host)
        old.hide()  # gone at once (deleteLater waits for the event loop)
        old.setParent(None)
        old.deleteLater()
        self.form = QFormLayout(self.form_host)
        self.form.setContentsMargins(0, 6, 0, 0)
        self.form.setLabelAlignment(Qt.AlignRight)
        return self.form

    def _change(self, values: dict) -> None:
        if self.key is None:
            self.view.change_graph(values)
        else:
            self.view.change_object(self.key, values)

    def _color(self, label: str, value: str, name: str) -> ColorButton:
        b = ColorButton(value)
        b.setObjectName(f"panel_{name}")
        b.changed.connect(lambda c, n=name: self._change({n: c}))
        self.form.addRow(label, b)
        return b

    def _width(self, label: str, value: float, name: str, lo: float = 0.0, hi: float = 20.0) -> QDoubleSpinBox:
        w = _width_spin(lo, hi)
        w.setObjectName(f"panel_{name}")
        w.setValue(value)
        w.valueChanged.connect(lambda v, n=name: self._change({n: round(v, 2)}))
        self.form.addRow(label, w)
        return w

    def _combo(self, label: str, items: dict[str, str], value: str, name: str, icons=None) -> QComboBox:
        c = QComboBox()
        c.setObjectName(f"panel_{name}")
        for k, v in items.items():
            c.addItem(v, k)
            if icons is not None:
                c.setItemIcon(c.count() - 1, icons(k))
        if icons is not None:
            from PySide6.QtCore import QSize

            c.setIconSize(QSize(56, 18))
        c.setCurrentIndex(max(0, c.findData(value)))
        c.currentIndexChanged.connect(lambda _i, n=name, c=c: self._change({n: c.currentData()}))
        self.form.addRow(label, c)
        return c

    def _note(self, text: str) -> None:
        hint = QLabel(text)
        hint.setWordWrap(True)
        hint.setObjectName("muted")
        self.form.addRow(hint)

    def show_for(self, key: str | None) -> None:
        """Rebuild the panel for object `key` of the view's graph (None: the graph)."""
        self.key = key if key and key != "graph" else None
        g = getattr(self.view, "graph", None)
        self._new_form()
        if g is None:
            self.heading.setText("Format")
            return
        kind, _, rest = (self.key or "").partition(".")
        i = int(rest) if rest.isdigit() else None
        if self.key is None:
            self.heading.setText("Graph")
            self._color("Background", F.hex_color(g.background or (255, 255, 255, 255)), "background")
            self._color("Plotting area", F.hex_color(g.plot_fill or (255, 255, 255, 255)), "plot_fill")
            self._color("Axes", F.hex_color(g.axis_color or (0, 0, 0, 255)), "axis_color")
            self._note("Click a bar, a symbol, a bracket, a text or a drawn object to format it; draw lines, "
                       "arrows, boxes and ellipses from the Draw group.")
        elif kind == "set" and i is not None and i < len(g.series):
            self._set_rows(g.series[i], i)
        elif kind == "bracket" and i is not None and i < len(g.significance):
            b = g.significance[i]
            self.heading.setText(f"{NAMES['bracket']} {i + 1} ({b.get('label', '')})")
            self._color("Line colour", F.hex_color(b.get("color") or (0, 0, 0, 255)), "color")
            self._width("Line width", float(b.get("width") or 1.0), "width", 0.25)
            self._note("Drag it to move it with its label; drag its end handles to make it longer or shorter; "
                       "Delete hides it. The label's own text, font and place are edited on the label.")
        elif kind == "abr" and i is not None and i < len(g.annotations):
            a = g.annotations[i]
            self.heading.setText(f"{NAMES['abr']} (placed in Prism)")
            self._color("Line colour", F.hex_color(a.get("color") or (0, 0, 0, 255)), "color")
            self._width("Line width", float(a.get("width") or 1.0), "width", 0.25)
            self._note("Drag it to move it; drag its end handles to make it longer or shorter; Delete hides it.")
        elif kind == "shape" and i is not None and i < len(g.shapes):
            self._shape_rows(g.shapes[i], i)
        else:
            self._text_rows(g, self.key)

    def _set_rows(self, s, i: int) -> None:
        self.heading.setText(f"{NAMES['set']} {i + 1}: {s.title}" if s.title else f"{NAMES['set']} {i + 1}")
        chosen = self.view.chosen_sets() if hasattr(self.view, "chosen_sets") else []
        if len(chosen) > 1:  # several chosen with Shift / Cmd-click: every change goes to each of them
            names = ", ".join(str(int(k.split(".")[1]) + 1) for k in chosen)
            self.heading.setText(f"{len(chosen)} data sets ({names})")
        bars = s.kind in ("bar", "box", "violin", "floating")
        if bars or s.fill_area:
            self._color("Fill", F.hex_color(s.fill), "fill")
            from . import color_menu

            fill = F.hex_color(s.fill)
            self._combo("Pattern", F.PATTERNS, s.pattern or "", "pattern",
                        icons=lambda k, fill=fill: color_menu.pattern_icon(k, fill=fill))
            self._color("Pattern colour", F.hex_color(s.pattern_color or (0, 0, 0, 255)), "pattern_color")
            self._color("Border", F.hex_color(s.color), "border")
            self._width("Border width", s.border_width if s.border_width is not None else 2.16, "border_width")
        if (s.kind == "bar" and any(s.points)) or (s.kind in ("points", "scatter") and s.symbol != "none"):
            if not bars:
                self._color("Symbol colour", F.hex_color(s.point_color or s.color), "color")
            self._combo("Symbol", F.SYMBOLS, s.symbol, "symbol")
            self._width("Symbol size", s.symbol_size, "size", 1.0, 40.0)
            if not bars:
                self._color("Symbol border", F.hex_color(s.symbol_border or (0, 0, 0, 255)), "border")
        if s.err_lo or s.err_hi or bars:
            self._color("Error bars", F.hex_color(s.error_color or s.color), "error_color")
            self._width("Error bar width", s.error_width or 1.0, "error_width", 0.25)
        if s.connect or s.kind in ("steps", "line"):
            self._color("Line colour", F.hex_color(s.line_color or s.color), "line_color")
            self._width("Line width", s.line_width, "line_width", 0.25)
        reset = QPushButton("Reset to default")
        reset.clicked.connect(lambda: self.view.reset_object(self.key))
        self.form.addRow(reset)
        if len(chosen) <= 1:
            self._note("Shift-click (or Cmd-click) other bars or symbols to format several data sets at once.")

    def _shape_rows(self, sh: dict, i: int) -> None:
        self.heading.setText(f"{F.SHAPES.get(sh.get('kind'), 'Object')} {i + 1}")
        if sh.get("kind") in ("line", "arrow", "arrow2", "ibeam", "cap"):
            self._combo("Kind", {k: F.SHAPES[k] for k in ("line", "arrow", "arrow2", "ibeam", "cap")}, sh.get("kind"),
                        "kind")
        from ..render.shape_kinds import LABELLED

        if sh.get("kind") in LABELLED:  # lines with text: their text
            from PySide6.QtWidgets import QLineEdit

            ed = QLineEdit(str(sh.get("label") or ""))
            ed.setObjectName("panel_label")
            ed.setPlaceholderText("No text")
            ed.editingFinished.connect(lambda ed=ed: self._change({"label": ed.text() or None}))
            self.form.addRow("Text", ed)
            if sh.get("label"):
                self._color("Text colour", F.hex_color(sh.get("label_color") or (0, 0, 0, 255)), "label_color")
                self._width("Text size", float(sh.get("label_size") or 12.0), "label_size", 4.0, 72.0)
        self._color("Line colour", F.hex_color(sh.get("color") or (0, 0, 0, 255)), "color")
        self._width("Line width", float(sh.get("width") if sh.get("width") is not None else 1.0), "width")
        dash = QCheckBox("Dashed")
        dash.setObjectName("panel_dash")
        dash.setChecked(bool(sh.get("dash")))
        dash.toggled.connect(lambda on: self._change({"dash": on or None}))
        self.form.addRow("", dash)
        if sh.get("kind") in ("rect", "ellipse", "circle", "square", "roundrect"):
            filled = QCheckBox("Filled")
            filled.setObjectName("panel_filled")
            filled.setChecked(sh.get("fill") is not None)
            colour = ColorButton(F.hex_color(sh.get("fill") or (255, 255, 255, 255)))
            colour.setObjectName("panel_fill")
            filled.toggled.connect(lambda on: self._change({"fill": colour.color if on else None}))
            colour.changed.connect(lambda c: self._change({"fill": c}))
            self.form.addRow("", filled)
            self.form.addRow("Fill", colour)
        delete = QPushButton("Delete")
        delete.clicked.connect(lambda: self.view.delete_text(self.key))
        self.form.addRow(delete)

    def _text_rows(self, g, key: str) -> None:
        kind = key.partition(".")[0]
        self.heading.setText(NAMES.get(kind, {"x": "X axis", "y": "Y axis"}.get(kind, "Text")))
        ts = F.text_style(g, key)
        if ts is None:
            return
        size, _bold = F.text_defaults(key)
        self._color("Colour", F.hex_color(ts.color), "color")
        w = _width_spin(2.0, 200.0, 1.0)
        w.setDecimals(1)
        w.setObjectName("panel_size")
        w.setValue(ts.size or size)
        w.valueChanged.connect(lambda v: self._change({"size": round(v, 1)}))
        self.form.addRow("Size", w)
        self._note("Drag the text to move it; double-click to type over it; font, bold and italic are in the "
                   "Text group.")
