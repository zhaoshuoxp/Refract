"""Right-click menus on a graph (docs/ui-spec.md §3.4): what is under the
pointer is selected and its menu opens - a bar or symbol (Format This Bar,
Format Entire Data Set, Format All Data Sets), a bracket, a drawn object,
a text, or the graph itself. Colours open the scheme-first colour menu
(refract.ui.color_menu), patterns show their swatches; each change is one
undo step through the graph view."""

from __future__ import annotations

from PySide6.QtWidgets import QMenu

from ..render import formatting as F
from . import color_menu

WIDTHS = [0.0, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 4.0, 6.0]
SIZES = [2.0, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0, 12.0, 16.0, 20.0]
TEXT_SIZES = [6, 7, 8, 9, 10, 11, 12, 14, 16, 18, 20, 24, 28, 36]


def _pt(v: float) -> str:
    return "None" if v == 0 else f"{v:g} pt"


class _Menus:
    def __init__(self, view):
        self.view = view

    # ------------------------------------------------------------ helpers
    def apply(self, keys: list[str], values: dict) -> None:
        """One undo step: `values` for every object in `keys`."""
        fmt = self.view.current_format()
        for k in keys:
            fmt = F.with_object(fmt, k, dict(values))
        self.view._select_next = keys[0] if len(keys) == 1 else None
        self.view.set_format(fmt)

    def color(self, menu: QMenu, title: str, current: str | None, keys: list[str], name: str, extra=None,
              enabled: bool = True) -> None:
        sub = menu.addMenu(title)
        sub.setEnabled(enabled)
        sub.aboutToShow.connect(lambda sub=sub: (sub.clear(), color_menu.build(
            sub, current, lambda c: self.apply(keys, {name: c, **(extra or {})}))))

    def choice(self, menu: QMenu, title: str, options: list, current, keys: list[str], name: str, extra=None,
               enabled: bool = True, label=str, icon=None) -> QMenu:
        sub = menu.addMenu(title)
        sub.setEnabled(enabled)
        for v in options:
            a = sub.addAction(label(v), lambda v=v: self.apply(keys, {name: v, **(extra or {})}))
            a.setCheckable(True)
            a.setChecked(v == current)
            if icon is not None:
                a.setIcon(icon(v))
        return sub

    def patterns(self, menu: QMenu, current: str, fill: str, keys: list[str], extra=None, enabled: bool = True) -> None:
        """Fill Pattern: a swatch of each of Prism's patterns, drawn as the graph draws it."""
        from PySide6.QtCore import QSize, Qt
        from PySide6.QtWidgets import QToolButton, QWidgetAction

        sub = menu.addMenu("Fill Pattern")
        sub.setEnabled(enabled)
        for k, name in F.PATTERNS.items():
            b = QToolButton()
            b.setIcon(color_menu.pattern_icon(k, fill=fill))
            b.setIconSize(QSize(56, 18))
            b.setText(("✓ " if k == current else "   ") + ("Solid fill" if k == "" else name))
            b.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            b.setAutoRaise(True)
            b.setMinimumWidth(220)
            b.setObjectName(f"pattern_{k or 'solid'}")
            b.clicked.connect(lambda _x=False, k=k, sub=sub: (self._close(sub),
                                                               self.apply(keys, {"pattern": k, **(extra or {})})))
            act = QWidgetAction(sub)
            act.setDefaultWidget(b)
            sub.addAction(act)

    @staticmethod
    def _close(menu: QMenu) -> None:
        while isinstance(menu, QMenu):
            menu.close()
            menu = menu.parent()

    # ------------------------------------------------------------ data sets
    def series_items(self, menu: QMenu, s, keys: list[str], extra: dict | None = None, bar_only: bool = False) -> None:
        """Format items for data sets `keys` (shown with series s's values); extra: e.g. {"bar": k}."""
        bars = s.kind in ("bar", "box", "violin", "floating")
        sym = (s.kind == "bar" and any(s.points)) or (s.kind in ("points", "scatter") and s.symbol != "none")
        line = s.connect or s.kind in ("steps", "line")
        own = ((s.bar_styles or {}).get(extra["bar"]) if extra and "bar" in extra else None) or {}
        fill = F.hex_color(own.get("fill", s.fill))
        if not bar_only:
            self.color(menu, "Symbol Color", F.hex_color(s.point_color or s.color), keys, "color", enabled=sym and not bars)
            self.choice(menu, "Symbol Shape", list(F.SYMBOLS), s.symbol, keys, "symbol", enabled=sym,
                        label=lambda k: F.SYMBOLS[k])
            self.choice(menu, "Symbol Size", SIZES, s.symbol_size, keys, "size", enabled=sym, label=_pt)
            menu.addSeparator()
        self.color(menu, "Fill Color", fill, keys, "fill", extra, enabled=bars or s.fill_area)
        self.patterns(menu, own.get("pattern", s.pattern) or "", fill, keys, extra, enabled=bars or s.fill_area)
        self.color(menu, "Pattern Color", F.hex_color(own.get("pattern_color", s.pattern_color) or (0, 0, 0, 255)), keys,
                   "pattern_color", extra, enabled=bars and bool(own.get("pattern", s.pattern)))
        menu.addSeparator()
        self.color(menu, "Border Color", F.hex_color(own.get("border", s.color)), keys, "border", extra, enabled=bars)
        bw = own.get("border_width", s.border_width if s.border_width is not None else 2.16)
        self.choice(menu, "Border Thickness", WIDTHS, bw, keys, "border_width", extra, enabled=bars, label=_pt)
        if bar_only:
            return
        menu.addSeparator()
        err = bool(s.err_lo or s.err_hi)
        self.color(menu, "Error Bars Color", F.hex_color(s.error_color or s.color), keys, "error_color", enabled=err)
        self.choice(menu, "Error Bars Thickness", WIDTHS[1:], s.error_width or 1.0, keys, "error_width", enabled=err,
                    label=_pt)
        menu.addSeparator()
        self.color(menu, "Line Color", F.hex_color(s.line_color or s.color), keys, "line_color", enabled=line)
        self.choice(menu, "Line Thickness", WIDTHS[1:], s.line_width, keys, "line_width", enabled=line, label=_pt)

    def data_set(self, menu: QMenu, i: int, x: float) -> None:
        g = self.view.graph
        s = g.series[i]
        lay = self.view.canvas.lay
        chosen = self.view.chosen_sets() if hasattr(self.view, "chosen_sets") else []
        if f"set.{i}" in chosen:  # several data sets chosen (Shift / Cmd-click): format them together
            self.series_items(menu.addMenu(f"Format Selected Data Sets ({len(chosen)})"), s, chosen)
            menu.addSeparator()
        if s.kind == "bar" and s.xs:  # the bar under the pointer
            k = min(range(len(s.xs)), key=lambda j: abs(lay.x(s.xs[j]) - x))
            this = menu.addMenu("Format This Bar")
            self.series_items(this, s, [f"set.{i}"], {"bar": k}, bar_only=True)
            this.addSeparator()
            this.addAction("Reset This Bar", lambda: self._reset_bar(i, k))
        self.series_items(menu.addMenu("Format Entire Data Set"), s, [f"set.{i}"])
        self.series_items(menu.addMenu("Format All Data Sets"), s, [f"set.{j}" for j in range(len(g.series))])
        menu.addSeparator()
        menu.addAction("Reset Data Set to Default", lambda: self.view.reset_object(f"set.{i}"))

    def _reset_bar(self, i: int, k: int) -> None:
        import copy

        fmt = copy.deepcopy(self.view.current_format() or {})
        bars = (((fmt.get("sets") or {}).get(str(i))) or {}).get("bars") or {}
        bars.pop(str(k), None)
        self.view.set_format(F._prune(fmt))

    # ------------------------------------------------------------ other objects
    def bracket(self, menu: QMenu, key: str) -> None:
        g = self.view.graph
        kind, _, rest = key.partition(".")
        i = int(rest)
        if kind == "bracket":
            b = g.significance[i]
            col, w = b.get("color") or (0, 0, 0, 255), float(b.get("width") or 1.0)
        else:
            a = g.annotations[i]
            col, w = a.get("color") or (0, 0, 0, 255), float(a.get("width") or 1.0)
        self.color(menu, "Line Color", F.hex_color(col), [key], "color")
        self.choice(menu, "Line Thickness", WIDTHS[1:], w, [key], "width", label=_pt)
        menu.addSeparator()
        menu.addAction("Delete Bracket", lambda: self.view.delete_text(key))

    def shape(self, menu: QMenu, key: str) -> None:
        sh = self.view.graph.shapes[int(key.split(".")[1])]
        self.color(menu, "Line Color", F.hex_color(sh.get("color") or (0, 0, 0, 255)), [key], "color")
        self.choice(menu, "Line Thickness", WIDTHS, float(sh.get("width") if sh.get("width") is not None else 1.0),
                    [key], "width", label=_pt)
        dash = menu.addAction("Dashed", lambda: self.apply([key], {"dash": None if sh.get("dash") else True}))
        dash.setCheckable(True)
        dash.setChecked(bool(sh.get("dash")))
        if sh.get("kind") in ("rect", "ellipse", "circle", "square", "roundrect"):
            menu.addSeparator()
            self.color(menu, "Fill Color", F.hex_color(sh.get("fill") or (255, 255, 255, 255)), [key], "fill")
            menu.addAction("No Fill", lambda: self.apply([key], {"fill": None}))
        menu.addSeparator()
        menu.addAction("Delete", lambda: self.view.delete_text(key))

    def text(self, menu: QMenu, key: str) -> None:
        canvas = self.view.canvas
        t = canvas.item(key)
        ts = F.text_style(self.view.graph, key)
        if ts is not None:
            self.color(menu, "Text Color", F.hex_color(ts.color), [key], "color")
            size, _bold = F.text_defaults(key)
            self.choice(menu, "Text Size", TEXT_SIZES, round(ts.size or size), [key], "size",
                        label=lambda v: f"{v} pt")
            b = menu.addAction("Bold", lambda: self.view.change_text(key, bold=not bool(ts.bold)))
            b.setCheckable(True)
            b.setChecked(bool(ts.bold))
            it = menu.addAction("Italic", lambda: self.view.change_text(key, italic=not ts.italic))
            it.setCheckable(True)
            it.setChecked(bool(ts.italic))
        if t is not None and t.editable:
            menu.addSeparator()
            menu.addAction("Edit Text", lambda: canvas.edit(key))
            menu.addAction("Delete Text", lambda: self.view.delete_text(key))

    def graph(self, menu: QMenu) -> None:
        g = self.view.graph
        for title, name, col in (("Background Color", "background", g.background or (255, 255, 255, 255)),
                                 ("Plotting Area Color", "plot_fill", g.plot_fill or (255, 255, 255, 255)),
                                 ("Axis Color", "axis_color", g.axis_color or (0, 0, 0, 255))):
            sub = menu.addMenu(title)
            sub.aboutToShow.connect(lambda sub=sub, name=name, col=col: (sub.clear(), color_menu.build(
                sub, F.hex_color(col), lambda c, name=name: self.view.change_graph({name: c}))))


def show(view, key: str, global_pos, x: float, y: float) -> None:
    """The right-click menu of object `key` of the view's graph at global_pos."""
    if view.graph is None or view.canvas is None:
        return
    m = QMenu(view)
    menus = _Menus(view)
    kind, _, rest = key.partition(".")
    if kind == "set" and rest.isdigit():
        menus.data_set(m, int(rest), x)
    elif kind in ("bracket", "abr") and rest.isdigit():
        menus.bracket(m, key)
    elif kind == "shape" and rest.isdigit():
        menus.shape(m, key)
    elif key and key != "graph":
        menus.text(m, key)
    else:
        menus.graph(m)
    w = view.window()
    m.addSeparator()
    for name in ("a_format_graph", "a_format_axes", "a_colors"):
        a = getattr(w, name, None)
        if a is not None:
            m.addAction(a)
    draw = getattr(w, "draw_menu", None)
    if draw is not None:
        m.addMenu(draw)
    m.exec(global_pos)
