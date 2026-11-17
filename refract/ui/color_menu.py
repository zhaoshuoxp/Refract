"""Choosing a colour for one element of a graph: the colours of the graph's
colour scheme first, then any other scheme's colours, then the custom
colour chooser (docs/ui-spec.md §3.4). Also the swatches of Prism's fill
patterns, drawn by the renderer itself.

The graph view sets the scheme in use (set_scheme) whenever it shows a
graph; ColorButton and the right-click menus ask for a colour with pick().
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QColorDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMenu,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

_SCHEME: tuple[str, list[str]] = ("", [])


def set_scheme(name: str, colors: list[str]) -> None:
    """The colour scheme of the graph being edited (its name, its colours)."""
    global _SCHEME
    seen, out = set(), []
    for c in colors:
        if c and c.lower() not in seen:
            seen.add(c.lower())
            out.append(c)
    _SCHEME = (name, out)


def scheme() -> tuple[str, list[str]]:
    return _SCHEME


def swatch_icon(color: str, w: int = 18, h: int = 14) -> QIcon:
    pm = QPixmap(w, h)
    pm.fill(QColor(color))
    p = QPainter(pm)
    p.setPen(QPen(QColor(0, 0, 0, 90), 1))
    p.drawRect(0, 0, w - 1, h - 1)
    p.end()
    return QIcon(pm)


def pattern_icon(key: str, w: int = 56, h: int = 18, fill: str = "#ffffff", color: str = "#000000") -> QIcon:
    """A swatch of Prism's fill pattern `key` ("" : a solid fill), drawn as the renderer draws it."""
    from ..render import formatting as F
    from ..render import qt

    pm = QPixmap(w * 2, h * 2)
    pm.setDevicePixelRatio(2.0)
    pm.fill(QColor(0, 0, 0, 0))
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    r = QRectF(0.5, 0.5, w - 1, h - 1)
    p.fillRect(r, QColor(fill))
    if key:
        qt._hatch(p, r, key, F.rgba(color), F.rgba(fill))
    p.setPen(QPen(QColor(0, 0, 0, 160), 1))
    p.setBrush(Qt.NoBrush)
    p.drawRect(r)
    p.end()
    return QIcon(pm)


def _row(menu: QMenu, title: str, colors: list[str], choose) -> None:
    """A menu row: the scheme's name and a swatch per colour (a click picks it)."""
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(10, 2, 10, 2)
    h.setSpacing(3)
    lab = QLabel(title)
    lab.setMinimumWidth(150)
    h.addWidget(lab)
    for c in colors[:12]:
        b = QToolButton()
        b.setIcon(swatch_icon(c))
        b.setIconSize(QSize(18, 14))
        b.setAutoRaise(True)
        b.setToolTip(c)
        b.clicked.connect(lambda _x=False, c=c: choose(c))
        h.addWidget(b)
    h.addStretch(1)
    act = QWidgetAction(menu)
    act.setDefaultWidget(w)
    menu.addAction(act)


def _grid(menu: QMenu, colors: list[str], choose, current: str | None) -> None:
    w = QWidget()
    g = QGridLayout(w)
    g.setContentsMargins(10, 4, 10, 4)
    g.setSpacing(4)
    for k, c in enumerate(colors):
        b = QToolButton()
        b.setIcon(swatch_icon(c, 28, 22))
        b.setIconSize(QSize(28, 22))
        b.setToolTip(c)
        b.setAutoRaise(True)
        b.setCheckable(True)
        b.setChecked(bool(current) and c.lower() == (current or "").lower())
        b.clicked.connect(lambda _x=False, c=c: choose(c))
        g.addWidget(b, k // 8, k % 8)
    act = QWidgetAction(menu)
    act.setDefaultWidget(w)
    menu.addAction(act)


def build(menu: QMenu, current: str | None, choose) -> None:
    """Fill `menu`: the graph's scheme, every other scheme, a custom colour."""
    from ..render import schemes
    from . import schemes_dialog as SD

    def pick(c: str) -> None:
        menu.close()
        top = menu
        while isinstance(top.parent(), QMenu):  # close the whole cascade
            top = top.parent()
            top.close()
        choose(c)

    name, colors = _SCHEME
    head = QWidgetAction(menu)
    lab = QLabel(f"  {name or 'This graph'}")
    f = lab.font()
    f.setBold(True)
    lab.setFont(f)
    box = QWidget()
    v = QVBoxLayout(box)
    v.setContentsMargins(6, 4, 6, 0)
    v.addWidget(lab)
    head.setDefaultWidget(box)
    menu.addAction(head)
    _grid(menu, colors or ["#000000", "#ffffff"], pick, current)
    menu.addSeparator()
    others = menu.addMenu("Other Color Schemes")
    built = others.addMenu("Refract")
    for n, cols in schemes.BUILT_IN.items():
        _row(built, n, cols, pick)
    for pkg, groups in schemes.LIBRARY.items():
        pm = others.addMenu(pkg)
        for grp, pals in groups.items():
            gm = pm.addMenu(grp)
            for pal, cols in pals.items():
                _row(gm, pal, cols, pick)
    yours = SD.custom()
    if yours:
        ym = others.addMenu("Your Schemes")
        for n, cols in yours.items():
            _row(ym, n, cols, pick)
    menu.addSeparator()
    menu.addAction("Custom Color…", lambda: _custom(menu, current, choose))


def _custom(parent, current: str | None, choose) -> None:
    c = QColorDialog.getColor(QColor(current or "#000000"), parent.parentWidget() if parent else None, "Colour")
    if c.isValid():
        choose(c.name())


def pick(parent: QWidget, current: str | None, global_pos) -> str | None:
    """A colour chosen from the menu at global_pos (None: dismissed)."""
    out: list[str] = []
    m = QMenu(parent)
    build(m, current, out.append)
    m.exec(global_pos)
    return out[-1] if out else None


def shape_icon(kind: str, labelled: bool = False, size: int = 26) -> QIcon:
    """A drawing tool's icon: the object itself, drawn by the renderer in the window's text colour."""
    from ..render import qt
    from . import look

    pm = QPixmap(size * 2, size * 2)
    pm.setDevicePixelRatio(2.0)
    pm.fill(QColor(0, 0, 0, 0))
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    col = look.color("text")
    m = 4.0
    tall = kind in ("ellipse", "circle", "rect", "square", "roundrect", "elbow", "elbow_arrow", "bracket_left",
                    "bracket_right")
    y1, y2 = (m + 2, size - m) if tall else (size / 2 + (2 if labelled else -2), size / 2 + (2 if labelled else -2))
    if kind in ("bracket", "bracket_up"):
        y1, y2 = size / 2 - 1 + (3 if labelled else 0), size / 2 + 5 + (3 if labelled else 0)
    x2 = size - m - (7 if labelled and kind in ("bracket_left", "bracket_right") else 0)
    sh = {"kind": kind, "x1": m, "y1": y1, "x2": x2, "y2": y2, "color": col.getRgb(), "width": 1.3}

    class _Lay:  # the icon's own frame: no plot offset
        plot = (0.0, 0.0, size, size)

    qt._draw_shapes(p, [sh], _Lay())
    if labelled:  # a small text box beside or above the line
        p.setPen(Qt.NoPen)
        p.setBrush(col)
        if kind in ("bracket_left", "bracket_right"):
            p.drawRect(QRectF(size - m - 4, size / 2 - 2, 4, 4))
        else:
            p.drawRect(QRectF(size / 2 - 2, y1 - 8, 4, 4))
    p.end()
    return QIcon(pm)
