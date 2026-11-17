"""Icons of the graph types (Change Graph Type): fixed line drawings, the
same whatever the table holds, in the window's palette (light lines on the
dark theme, dark lines on the light one); our own drawings. Only the large
preview below them shows the table's data."""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

from ..render import qt as Q
from . import look

W, H = 112, 84  # logical size
_CACHE: dict[tuple[str, bool], QIcon] = {}


class _Pen:
    """Drawing in category/value units (u across the categories, v up the
    values, both 0..1), upright or on its side."""

    def __init__(self, p: QPainter, horizontal: bool, ink: QColor, fill: QColor, soft: QColor):
        self.p, self.h, self.ink, self.fill, self.soft = p, horizontal, ink, fill, soft
        self.x0, self.y0, self.x1, self.y1 = 14.0, 10.0, W - 10.0, H - 12.0

    def pt(self, u: float, v: float) -> QPointF:
        if self.h:
            return QPointF(self.x0 + v * (self.x1 - self.x0), self.y0 + u * (self.y1 - self.y0))
        return QPointF(self.x0 + u * (self.x1 - self.x0), self.y1 - v * (self.y1 - self.y0))

    def axes(self, frame: bool = False) -> None:
        self.p.setPen(QPen(self.ink, 1.6))
        self.p.drawLine(QPointF(self.x0, self.y0), QPointF(self.x0, self.y1))
        self.p.drawLine(QPointF(self.x0, self.y1), QPointF(self.x1, self.y1))
        if frame:
            self.p.drawLine(QPointF(self.x0, self.y0), QPointF(self.x1, self.y0))
            self.p.drawLine(QPointF(self.x1, self.y0), QPointF(self.x1, self.y1))

    def line(self, pts, width: float = 1.3, dash: bool = False) -> None:
        pen = QPen(self.ink, width)
        if dash:
            pen.setStyle(Qt.DashLine)
        self.p.setPen(pen)
        path = QPainterPath(self.pt(*pts[0]))
        for u, v in pts[1:]:
            path.lineTo(self.pt(u, v))
        self.p.setBrush(Qt.NoBrush)
        self.p.drawPath(path)

    def dot(self, u: float, v: float, r: float = 3.2, filled: bool = True) -> None:
        self.p.setPen(QPen(self.ink, 1.2))
        self.p.setBrush(self.ink if filled else Qt.NoBrush)
        self.p.drawEllipse(self.pt(u, v), r, r)

    def rect(self, u: float, w: float, v0: float, v1: float, fill=None) -> None:
        a, b = self.pt(u - w / 2, v0), self.pt(u + w / 2, v1)
        self.p.setPen(QPen(self.ink, 1.2))
        self.p.setBrush(fill if fill is not None else self.fill)
        self.p.drawRect(QRectF(a, b).normalized())

    def err(self, u: float, lo: float, hi: float, cap: float = 0.04) -> None:
        self.line([(u, lo), (u, hi)], 1.1)
        for v in (lo, hi):
            self.line([(u - cap, v), (u + cap, v)], 1.1)

    def violin(self, u: float, w: float, lo: float, hi: float, fill=None) -> None:
        path = QPainterPath(self.pt(u, lo))
        n = 16
        for k in range(n + 1):
            f = k / n
            path.lineTo(self.pt(u + w / 2 * math.sin(math.pi * f) ** 0.7, lo + (hi - lo) * f))
        for k in range(n, -1, -1):
            f = k / n
            path.lineTo(self.pt(u - w / 2 * math.sin(math.pi * f) ** 0.7, lo + (hi - lo) * f))
        self.p.setPen(QPen(self.ink, 1.2))
        self.p.setBrush(fill if fill is not None else self.fill)
        self.p.drawPath(path)


# positions (u, level, series) of the column-like icons
def _column_slots(n: int = 3, levels=(0.35, 0.55, 0.8)):
    return [((k + 0.5) / n, levels[k % len(levels)], 0) for k in range(n)]


def _interleaved(rows: int = 3, sets: int = 2, levels=((0.25, 0.55), (0.45, 0.7), (0.6, 0.85))):
    out = []
    for r in range(rows):
        for j in range(sets):
            out.append(((r + 0.5) / rows + (j - (sets - 1) / 2) * 0.12, levels[r % len(levels)][j % 2], j))
    return out


def _separated(rows: int = 3, sets: int = 2):
    out = []
    for j in range(sets):
        for r in range(rows):
            out.append((j / sets + (r + 0.5) / (rows * sets) + 0.02, (0.3, 0.5, 0.7)[r] + 0.1 * j, j))
    return out


def _nested():
    out = []
    for g_ in range(2):
        for s in range(3):
            out.append((g_ * 0.5 + (s + 0.5) / 6, (0.35, 0.5, 0.42)[s] + 0.25 * g_, g_))
    return out


def _element(d: _Pen, kind: str, slots, width: float, line_through: bool = False) -> None:
    """One element per slot: values (dots), bars, symbols with error bars, boxes, ..."""
    for u, v, j in slots:
        fill = d.fill if j == 0 else d.soft
        if kind in ("dots", "dots_bar", "dots_line"):
            if kind == "dots_bar":
                d.rect(u, width, 0, v, fill)
            for k, dv in enumerate((-0.12, -0.04, 0.05, 0.13)):
                d.dot(u + (0.018 if k % 2 else -0.018) * (width / 0.12), v + dv, 2.4, j == 0)
            if kind == "dots_line":
                d.line([(u - width / 2, v), (u + width / 2, v)], 1.6)
        elif kind == "dots_only":
            for k, dv in enumerate((-0.14, -0.05, 0.04, 0.13)):
                d.dot(u, v + dv, 2.4, j == 0)
        elif kind == "bar":
            d.rect(u, width, 0, v, fill)
            d.err(u, v, min(0.98, v + 0.1), width / 4)
        elif kind == "means":
            d.err(u, v - 0.1, v + 0.1, width / 4)
            d.dot(u, v, 3.0, j == 0)
        elif kind == "floating":
            d.rect(u, width, v - 0.2, v + 0.15, fill)
            d.line([(u - width / 2, v - 0.02), (u + width / 2, v - 0.02)], 1.2)
        elif kind == "box":
            d.line([(u, v - 0.28), (u, v + 0.25)], 1.1)
            for e in (v - 0.28, v + 0.25):
                d.line([(u - width / 4, e), (u + width / 4, e)], 1.1)
            d.rect(u, width, v - 0.12, v + 0.12, fill)
            d.line([(u - width / 2, v - 0.02), (u + width / 2, v - 0.02)], 1.2)
        elif kind == "violin":
            d.violin(u, width * 1.3, v - 0.25, v + 0.22, fill)
    if line_through:
        by: dict[int, list] = {}
        for u, v, j in slots:
            by.setdefault(j, []).append((u, v))
        for pts in by.values():
            d.line(sorted(pts), 1.3)


COLUMN_KIND = {"col_scatter": "dots_line", "col_scatter_bar": "dots_bar", "col_floating": "floating", "col_box": "box",
               "col_violin": "violin", "col_bar": "bar", "col_means": "means", "col_means_line": "means"}
GROUPED_KIND = {"grp_scatter": "dots_line", "grp_bars_points": "dots_bar", "grp_dots": "dots_only", "grp_bars": "bar",
                "grp_means": "means", "grp_means_line": "means", "grp_box": "box", "grp_floating": "floating",
                "grp_violin": "violin"}
NESTED_KIND = {"nest_scatter": "dots_line", "nest_scatter_bar": "dots_bar", "nest_bars": "bar",
               "nest_floating": "floating", "nest_box": "box", "nest_violin": "violin"}
MV_KIND = {"mv_scatter_cat": "dots_line", "mv_means_cat": "means", "mv_bars_cat": "dots_bar", "mv_box_cat": "box",
           "mv_violin_cat": "violin", "mv_bar_cat": "bar"}


def _heat(p: QPainter, cmap: str, x0=22.0, y0=12.0, cols=3, rows=6, cw=20.0, ch=10.0) -> None:
    import random

    rnd = random.Random(7)
    p.setPen(Qt.NoPen)
    for r in range(rows):
        for c in range(cols):
            f = min(1.0, max(0.0, r / (rows - 1) + (rnd.random() - 0.5) * 0.25))
            p.setBrush(QColor(*Q.colormap(cmap, f)[:3]))
            p.drawRect(QRectF(x0 + c * cw, y0 + r * ch, cw, ch))


def draw(p: QPainter, key: str) -> None:
    pal = look.colors()
    ink = QColor(pal["text"])
    fill = QColor(pal["faint"])
    fill.setAlpha(150)
    soft = QColor(pal["muted"])
    soft.setAlpha(110)
    horizontal = key.endswith("_h")
    base = key.removesuffix("_h")
    d = _Pen(p, horizontal, ink, fill, soft)
    if base.startswith(("grp_heat_",)):
        _heat(p, base.removeprefix("grp_heat_"), 22, 10, 3, 6, 22, 10.5)
        return
    if base == "mv_heat":
        _heat(p, "viridis", 22, 10, 3, 6, 22, 10.5)
        return
    if base in ("pie", "donut"):
        r = QRectF(W / 2 - 30, H / 2 - 30, 60, 60)
        p.setPen(QPen(ink, 1.4))
        for start, span, c in ((90, -130, fill), (-40, -140, soft), (180, -90, QColor(pal["text"]))):
            col = QColor(c)
            if c is not fill and c is not soft:
                col.setAlpha(60)
            p.setBrush(col)
            p.drawPie(r, start * 16, span * 16)
        if base == "donut":
            p.setBrush(QColor(pal["window"]))
            p.drawEllipse(QPointF(W / 2, H / 2), 13, 13)
        return
    if base == "waffle":
        for r_ in range(8):
            for c in range(8):
                k = r_ * 8 + c
                col = QColor(ink) if k < 20 else (QColor(pal["muted"]) if k < 38 else QColor(pal["faint"]))
                col.setAlpha(200 if k < 20 else 160)
                p.setPen(Qt.NoPen)
                p.setBrush(col)
                p.drawRect(QRectF(26 + c * 8, 8 + (7 - r_) * 8.5, 7, 7.5))
        return
    if base == "pow_stacked":
        d.axes()
        for v0, v1, c in ((0, 0.45, fill), (0.45, 0.75, soft), (0.75, 1.0, None)):
            d.rect(0.5, 0.3, v0, v1, c if c is not None else QColor(0, 0, 0, 0))
        return
    if base.startswith("surv_"):
        d.axes()
        inverted = "inverted" in base
        for k, drop in enumerate((0.09, 0.13)):
            v = 0.95 if not inverted else 0.05
            pts = [(0.0, v)]
            for s in range(6):
                u = 0.1 + s * 0.15 + k * 0.04
                pts.append((u, v))
                v = v - drop if not inverted else v + drop
                if "points" in base:
                    pts[-1] = (u, v)
                else:
                    pts.append((u, v))
            pts.append((1.0, v))
            d.line(pts, 1.4)
            if "ticks" in base:
                for s in (1, 3):
                    u, vv = pts[2 * s + 1]
                    d.line([(u + 0.05, vv), (u + 0.05, vv + 0.06)], 1.0)
            if "points" in base or "symbols" in base:
                for u, vv in pts[1:-1:2 if "symbols" in base else 1]:
                    d.dot(u, vv, 2.4, k == 0)
        return
    if base in ("cont_bars", "cont_bars_sep", "cont_stacked", "cont_percent"):
        d.axes()
        if base in ("cont_bars", "cont_bars_sep"):
            for i, (u, v, j) in enumerate(_interleaved(3, 2) if base == "cont_bars" else _separated(3, 2)):
                d.rect(u, 0.1, 0, v * (0.6 + 0.4 * (i % 2)), fill if j == 0 else soft)
        else:
            for k, u in enumerate((0.2, 0.5, 0.8)):
                a = (0.3, 0.5, 0.65)[k] if base == "cont_percent" else (0.2, 0.35, 0.3)[k]
                top = 0.95 if base == "cont_percent" else (0.5, 0.85, 0.65)[k]
                d.rect(u, 0.2, 0, a, fill)
                d.rect(u, 0.2, a, top, soft)
        return
    if base.startswith("xy_"):
        d.axes()
        xs = [0.12, 0.4, 0.65, 0.9]
        lines = ([0.2, 0.42, 0.58, 0.82], [0.12, 0.28, 0.36, 0.5])
        if base == "xy_bars":
            for k, x in enumerate(xs):
                d.rect(x - 0.03, 0.05, 0, lines[0][k], fill)
                d.rect(x + 0.03, 0.05, 0, lines[1][k], soft)
            return
        if base == "xy_area":
            path = QPainterPath(d.pt(xs[0], 0))
            for x, v in zip(xs, lines[0], strict=True):
                path.lineTo(d.pt(x, v))
            path.lineTo(d.pt(xs[-1], 0))
            p.setPen(Qt.NoPen)
            p.setBrush(fill)
            p.drawPath(path)
        for j, ys in enumerate(lines):
            pts = list(zip(xs, ys, strict=True))
            if base in ("xy_points_line", "xy_replicates_line", "xy_line", "xy_area", "xy_rep_lines"):
                if base == "xy_rep_lines":
                    for off in (-0.05, 0.0, 0.05):
                        d.line([(x, v + off) for x, v in pts], 1.0)
                else:
                    d.line(pts, 1.3)
            for x, v in pts:
                if base in ("xy_points", "xy_points_line", "xy_line"):
                    d.err(x, v - 0.07, v + 0.07, 0.025)
                if base in ("xy_points", "xy_points_line"):
                    d.dot(x, v, 2.8, j == 0)
                if base in ("xy_replicates", "xy_replicates_line"):
                    for off in (-0.06, 0.0, 0.06):
                        d.dot(x, v + off, 2.2, j == 0)
                if base == "xy_rep_lines":
                    for off in (-0.05, 0.0, 0.05):
                        d.dot(x, v + off, 1.8, j == 0)
        return
    if base == "mv_bubble":
        d.axes()
        for u, v, r in ((0.15, 0.15, 2.5), (0.35, 0.35, 7), (0.6, 0.3, 5), (0.75, 0.7, 10)):
            d.dot(u, v, r, r < 6)
        return
    if base == "mv_scatter":
        d.axes()
        import random

        rnd = random.Random(3)
        for k in range(16):
            u = 0.08 + rnd.random() * 0.85
            d.dot(u, min(0.92, max(0.08, 0.2 + 0.6 * u + (rnd.random() - 0.5) * 0.3)), 2.2, k % 2 == 0)
        return
    if base in ("mv_before_after", "mv_before_after_bars"):
        base = base.replace("mv_", "col_")
    if base in ("col_before_after", "col_before_after_bars"):
        d.axes()
        if base.endswith("bars"):
            d.rect(0.3, 0.25, 0, 0.45, fill)
            d.rect(0.7, 0.25, 0, 0.7, soft)
        for a, b in ((0.3, 0.55), (0.42, 0.78), (0.55, 0.62), (0.2, 0.45)):
            d.line([(0.3, a), (0.7, b)], 1.1)
            d.dot(0.3, a, 2.3)
            d.dot(0.7, b, 2.3, False)
        return
    if base == "grp_rep_lines":
        d.axes()
        for k, ys in enumerate(((0.2, 0.6, 0.45), (0.35, 0.7, 0.3), (0.5, 0.4, 0.8))):
            pts = [(0.15 + 0.35 * i, y) for i, y in enumerate(ys)]
            d.line(pts, 1.1)
            for u, v in pts:
                d.dot(u, v, 2.3, k != 1)
        return
    if base.startswith("grp3_"):
        d.axes(frame=True)
        p.setPen(QPen(ink, 1.4))
        mid = d.pt(0.5, 0)
        p.drawLine(QPointF(mid.x(), d.y0), QPointF(mid.x(), d.y1))
        kind = {"grp3_means_line": "means", "grp3_bars": "bar", "grp3_scatter": "dots_only",
                "grp3_scatter_side": "dots_only"}[base]
        for panel in range(2):
            slots = [(panel * 0.5 + (r + 0.5) / 4 + (j - 0.5) * 0.08, (0.3, 0.6)[r] + 0.12 * j - 0.1 * panel, j)
                     for r in range(2) for j in range(2)]
            _element(d, kind, slots, 0.07, line_through=base == "grp3_means_line")
        return
    d.axes(frame=base.startswith("nest_"))
    if base.startswith("nest_"):
        p.setPen(QPen(ink, 1.4))
        a, b = d.pt(0.5, 0), d.pt(0.5, 1)
        p.drawLine(a, b)
        _element(d, NESTED_KIND[base], _nested(), 0.1)
        return
    if base in GROUPED_KIND or base.removesuffix("_sep") in GROUPED_KIND:
        sep = base.endswith("_sep")
        kind = GROUPED_KIND[base.removesuffix("_sep")]
        slots = _separated() if sep else _interleaved()
        _element(d, kind, slots, 0.1 if not sep else 0.11, line_through=base.startswith("grp_means_line"))
        return
    if base == "grp_stacked":
        for k, u in enumerate((0.2, 0.5, 0.8)):
            a, top = (0.25, 0.4, 0.3)[k], (0.55, 0.85, 0.7)[k]
            d.rect(u, 0.2, 0, a, fill)
            d.rect(u, 0.2, a, top, soft)
        return
    kind = COLUMN_KIND.get(base) or MV_KIND.get(base, "dots_line")
    _element(d, kind, _column_slots(), 0.16, line_through=base == "col_means_line")


def icon(key: str) -> QIcon:
    dark = look.is_dark()
    if (key, dark) in _CACHE:
        return _CACHE[(key, dark)]
    pm = QPixmap(W * 2, H * 2)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.scale(2, 2)
    draw(p, key)
    p.end()
    pm.setDevicePixelRatio(2)
    _CACHE[(key, dark)] = QIcon(pm)
    return _CACHE[(key, dark)]
