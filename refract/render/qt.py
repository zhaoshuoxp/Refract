"""Draw a refract.render.model.Graph with QPainter; export PNG, PDF and SVG.

Drawing happens in points (1/72 inch), y downwards; a PNG at `dpi` scales by
dpi/72. Layout and style follow Prism 11's default graphs as measured on its
own PDF exports (refract.render.style; docs/format/findings.md).

Qt note: Qt cannot find plugins that carry the macOS "hidden" file flag
(QDir skips hidden files); ensure_app() then points Qt at a symlink mirror.
"""

from __future__ import annotations

import itertools
import math
import os
from dataclasses import dataclass, field

from .autoscale import auto_range
from .model import Axis, Graph, Series, TextStyle
from .style import BAR_FILLS, DEFAULT, Style

_APP = None

# rotated category labels: the end of the baseline sits this far right of the
# tick and below its end (fitted on the default column and grouped graphs)
ROT_DX, ROT_DY = 2.6, 10.1
TRACK_TEXT = -0.2  # points per character: titles, axis titles, legend


def _visible_plugins() -> str | None:
    """Qt's plugin folder mirrored as symlinks in a non-hidden place: Qt skips
    files carrying the macOS "hidden" flag, which sync tools keep putting on
    a .venv under ~/Documents (verified); the symlinks themselves are not
    hidden. Returns the mirror, or None when nothing needed it."""
    import tempfile

    from PySide6.QtCore import QLibraryInfo

    src = QLibraryInfo.path(QLibraryInfo.LibraryPath.PluginsPath)
    probe = os.path.join(src, "platforms")
    hidden = any(getattr(os.lstat(os.path.join(probe, f)), "st_flags", 0) & 0x8000 for f in os.listdir(probe))
    if not hidden:
        return None
    dst = os.path.join(tempfile.gettempdir(), f"refract-qt-plugins-{os.getuid()}")
    for root, _dirs, files in os.walk(src):
        rel = os.path.relpath(root, src)
        os.makedirs(os.path.join(dst, rel), exist_ok=True)
        for f in files:
            link = os.path.join(dst, rel, f)
            if not os.path.lexists(link):
                os.symlink(os.path.join(root, f), link)
    return dst


def prepare_qt() -> None:
    """Point Qt at visible plugins (see _visible_plugins); call before the
    application object is created."""
    mirror = _visible_plugins()
    if mirror:
        os.environ["QT_PLUGIN_PATH"] = mirror


def ensure_app():
    """The application object; created offscreen (unless a platform is set)
    as a QApplication, so widgets (refract.ui) can share it."""
    global _APP
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        prepare_qt()
        app = _APP = QApplication([])
    return app


# ----------------------------------------------------------------- axes
@dataclass
class Scale:
    lo: float
    hi: float
    tick: float
    p0: float  # page coordinate of lo
    p1: float  # page coordinate of hi
    log: bool = False  # log10 axis: lo, hi > 0; major ticks at the powers of ten

    def __call__(self, v: float) -> float:
        if self.log:
            v = max(v, self.lo * 1e-6) if v is not None else self.lo
            return self.p0 + (math.log10(v) - math.log10(self.lo)) / \
                (math.log10(self.hi) - math.log10(self.lo)) * (self.p1 - self.p0)
        return self.p0 + (v - self.lo) / (self.hi - self.lo) * (self.p1 - self.p0)

    def ticks(self, step: float | None = None) -> list[float]:
        """Multiples of `step` (default: the major tick) within lo..hi (an
        axis may start between ticks: survival X starts before 0). Log axes:
        the powers of ten, or with a step the 2..9 multiples between them."""
        if self.log:
            k0, k1 = math.floor(math.log10(self.lo) + 1e-9), math.ceil(math.log10(self.hi) - 1e-9)
            vals = [10.0 ** k for k in range(k0, k1 + 1)] if step is None else \
                [m * 10.0 ** k for k in range(k0, k1 + 1) for m in range(2, 10)]
            return [v for v in vals if self.lo * (1 - 1e-9) <= v <= self.hi * (1 + 1e-9)]
        t = step or self.tick
        k0 = math.ceil(self.lo / t - 1e-9)
        k1 = math.floor(self.hi / t + 1e-9)
        return [k * t for k in range(k0, k1 + 1)]


AXIS_BREAK_GAP = 9.2  # points between the segments of a broken axis (Prism's export of the asterisks sample)


class SegmentedScale(Scale):
    """A broken axis: segments (lo, hi, tick, length in points) from the
    bottom up, each a scale of its own, AXIS_BREAK_GAP apart (drawn length
    units scaled to p0..p1). A value in a gap lands on the lower segment's
    end."""

    def __init__(self, segments: list[tuple[float, float, float, float]], p0: float, p1: float):
        total = sum(s[3] for s in segments) + AXIS_BREAK_GAP * (len(segments) - 1)
        k = (p1 - p0) / total if total else 0.0
        self.parts: list[Scale] = []
        at = p0
        for lo, hi, tick, length in segments:
            self.parts.append(Scale(lo, hi, tick, at, at + length * k))
            at += (length + AXIS_BREAK_GAP) * k
        super().__init__(segments[0][0], segments[-1][1], segments[-1][2], p0, p1)

    def __call__(self, v: float) -> float:
        if v is None:
            return self.parts[0].p0
        for i, sc in enumerate(self.parts):
            nxt = self.parts[i + 1] if i + 1 < len(self.parts) else None
            if v <= sc.hi or nxt is None:
                return sc(max(v, sc.lo) if i else v)
            if v < nxt.lo:
                return sc(sc.hi)
        return self.parts[-1](v)

    def ticks(self, step: float | None = None) -> list[float]:
        out: list[float] = []
        for sc in self.parts:
            out += sc.ticks(None if step is None else step * sc.tick / self.tick)
        return sorted(set(out))


def y_scale(g, lo: float, hi: float, tick: float, p0: float, p1: float) -> Scale:
    """The Y axis's scale: segmented when the axis is broken (refract.render.
    from_prism reads the segments), else one linear or log scale."""
    segs = getattr(g.y_axis, "segments", None)
    if segs and len(segs) > 1 and not g.y_axis.log:
        return SegmentedScale(segs, p0, p1)
    return Scale(lo, hi, tick, p0, p1, g.y_axis.log)


def fmt_tick(v: float, tick: float, log: bool = False) -> str:
    """Tick label: as many decimals as the tick needs, the same on every
    label, zero included ("0.00": 139 of 169 zero labels in the corpus PDFs
    with decimal ticks), no exponent. Log axes: each power of ten as a plain
    number (0.01, 1, 100)."""
    if log:
        k = round(math.log10(v))
        return f"{10.0 ** k:.{max(0, -k)}f}" if k < 7 else f"1e{k}"
    d = max(0, -math.floor(math.log10(tick) + 1e-9)) if tick < 1 else 0
    s = f"{v:.{d}f}"
    return s.lstrip("-") if s.strip("-0.") == "" else s


# survival graphs in percent: Y 0..110, labelled every 50, minor ticks every
# 10 (verified on Prism's default survival graph)
SURVIVAL_Y_PERCENT = (0.0, 110.0, 50.0)
SURVIVAL_Y_MINOR = 5


def survival_x_range(tmax: float) -> tuple[float, float, float]:
    """Survival X axis: the bar rule from 0 to the last time, then both ends
    widened by 0.475 of the major tick (verified: 30 of 30 Prism variants,
    times 0.04-930000; e.g. 0..150 -> -23.75..223.75 / 50)."""
    lo, hi, t = auto_range(0.0, tmax, style="bar")
    return lo - SURVIVAL_X_PAD * t, hi + SURVIVAL_X_PAD * t, t


SURVIVAL_X_PAD = 0.475  # of the major tick


def log_range(g: Graph, y: bool) -> tuple[float, float, float]:
    """Decades spanning the positive values plotted on an axis."""
    vals = []
    for s in g.series:
        if y:
            vals += [v for v in s.ys if v is not None]
            vals += [v for e in (s.err_lo, s.err_hi) for v in e if v is not None]
            vals += [v for pts in s.points for v in pts]
        else:
            vals += list(s.xs)
    if y:
        vals += [b["top"] for b in g.significance]
    pos = [v for v in vals if v is not None and v > 0]
    if not pos:
        return 1.0, 10.0, 10.0
    lo = 10.0 ** math.floor(math.log10(min(pos)) + 1e-9)
    hi = 10.0 ** math.ceil(math.log10(max(pos)) - 1e-9)
    return lo, (hi if hi > lo else lo * 10), 10.0


def _y_style(g: Graph) -> str:
    """Bar graphs autoscale like bars, XY like points, column scatter by its
    own margins (refract.render.autoscale)."""
    if g.y_autoscale:
        return g.y_autoscale
    if g.family == "xy":
        return "xy"
    if g.family == "column" and g.series and all(s.kind in ("scatter", "points", "line") + BOX_KINDS
                                                  for s in g.series):
        return "column"  # scatter, symbols, boxes, before-after: the column margins (E-compare)
    if g.family == "column" and g.series and all(s.kind in ("bar", "scatter") for s in g.series):
        return "colbar"  # column bars: the column margins, the bottom one also below 0 (E-pairs)
    return "bar"


def resolve_axes(g: Graph) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    """((xlo, xhi, xtick), (ylo, yhi, ytick)): manual values where set,
    Prism's automatic range otherwise. Category axes: slots at 0..n-1."""
    ext = g.extent() or (0.0, 1.0, 0.0, 1.0)

    def pick(ax: Axis, auto):
        lo, hi, t = auto
        if ax.log:  # whole decades around the positive values; the tick is the decade
            lo, hi, t = log_range(g, ax is g.y_axis)
            mn = ax.min if ax.min is not None and ax.min > 0 else lo
            mx = ax.max if ax.max is not None and ax.max > mn else hi
            return mn, mx, 10.0
        return (ax.min if ax.min is not None else lo, ax.max if ax.max is not None else hi,
                ax.tick if ax.tick is not None else t)

    if g.family == "survival":
        return pick(g.x_axis, survival_x_range(ext[1])), pick(g.y_axis, SURVIVAL_Y_PERCENT)
    y = pick(g.y_axis, auto_range(ext[2], ext[3], style=_y_style(g)))
    if g.family in ("column", "grouped"):
        x = (0.0, float(max(len(g.categories) - 1, 1)), 1.0)
    else:
        x = pick(g.x_axis, auto_range(ext[0], ext[1], style="xy", axis="x"))
    return x, y


# --------------------------------------------------------------- layout
def _font(family: str, size: float, bold: bool = False, italic: bool = False, underline: bool = False):
    from PySide6.QtGui import QFont

    f = QFont(family)
    f.setPointSizeF(size)
    f.setBold(bold)
    f.setItalic(italic)
    f.setUnderline(underline)
    f.setKerning(True)
    return f


def _sfont(g: Graph, ts, size: float, bold: bool):
    """Font for a text role: the graph's TextStyle over Prism's default."""
    return _font(getattr(ts, "family", None) or g.font, ts.size or size, bold if ts.bold is None else ts.bold,
                 ts.italic, getattr(ts, "underline", False))


def _off(g: Graph, key: str) -> tuple[float, float]:
    return g.offsets.get(key, (0.0, 0.0))


def _angle(g: Graph, m, pitch: float, st: Style) -> float:
    """Category label angle: as stored, else Prism's automatic choice: 45 deg
    when the widest label exceeds AUTO_ROTATE of the category pitch,
    horizontal otherwise (findings.md, E-compare)."""
    if g.x_axis.label_angle is not None:
        return g.x_axis.label_angle
    w = max((text_width(m, x) for c in g.categories for x in _lines(c)), default=0.0)
    return st.label_angle if w > AUTO_ROTATE * pitch else 0.0


def _lines(text: str) -> list[str]:
    """A label's lines (Prism stores a line break as CR)."""
    return text.replace("\r\n", "\n").replace("\r", "\n").split("\n")


AUTO_ROTATE = 0.9  # Prism's new graphs: 0.86 stays horizontal, 0.97 turns (E-compare); 128 corpus PDFs agree best at 0.9-1.2
LEGEND_BOX_DX, LEGEND_BOX_PAD = 17.66, 7.5  # legend entry box -> symbol centre / text line box


_METRIC_DEVICE = None


def _metrics(font):
    """Font metrics in points: measured against a 72 dpi device (the offscreen
    screen is 96 dpi, which would scale every text width by 4/3)."""
    global _METRIC_DEVICE
    from PySide6.QtGui import QFontMetricsF, QImage

    if _METRIC_DEVICE is None:
        _METRIC_DEVICE = QImage(4, 4, QImage.Format_ARGB32)
        _METRIC_DEVICE.setDotsPerMeterX(round(72 / 0.0254))
        _METRIC_DEVICE.setDotsPerMeterY(round(72 / 0.0254))
    return QFontMetricsF(font, _METRIC_DEVICE)


def _advances(m, txt: str, track: float) -> list[float]:
    """Pen advance after each character: Qt's advance with pair kerning, plus
    `track`. Prism sets titles, axis titles and legend text 0.2 pt tighter per
    character at any size (TRACK_TEXT; verified on 4 strings, 11-14 pt,
    regular and bold) and tick and category labels without tracking
    (verified: 6.114 pt per 11 pt digit). Qt's own letter spacing is ignored by
    its PDF and raster engines here, so text is set character by character."""
    out = []
    for i, ch in enumerate(txt):
        a = m.horizontalAdvance(ch)
        if i + 1 < len(txt):
            a = m.horizontalAdvance(txt[i:i + 2]) - m.horizontalAdvance(txt[i + 1])
        out.append(a + track)
    return out


def text_width(m, txt: str, track: float = 0.0) -> float:
    return sum(_advances(m, txt, track)) - (track if txt else 0.0)


def draw_text(p, x: float, y: float, txt: str, track: float = 0.0) -> None:
    """Draw txt with its baseline starting at (x, y), Prism's spacing."""
    from PySide6.QtCore import QPointF

    if track == 0:  # Qt's own spacing; one text run (whole words in SVG / PDF)
        p.drawText(QPointF(x, y), txt)
        return
    m = _metrics(p.font())
    for ch, a in zip(txt, _advances(m, txt, track), strict=True):
        p.drawText(QPointF(x, y), ch)
        x += a


@dataclass
class Layout:
    width: float
    height: float
    plot: tuple[float, float, float, float]  # left, top, right, bottom of the axes (page points)
    x: Scale
    y: Scale
    title_baseline: float = 0.0
    y_title_baseline_x: float = 0.0
    x_label_baseline: float = 0.0
    x_title_baseline: float = 0.0
    legend: list[tuple[float, float, float]] = field(default_factory=list)  # (symbol cx, cy, text x)
    label_angle: float = 0.0  # category labels
    title_cx: float = 0.0
    x_title_cx: float = 0.0
    y_title_cy: float = 0.0
    horizontal: bool = False
    right_ticks: list[tuple[float, str]] = field(default_factory=list)  # estimation: (page y, label)
    right_title_left: float = 0.0


def _x_geometry(g: Graph, st: Style) -> tuple[float, float, float]:
    """(X axis length, offset of the first category from the axis start,
    category pitch); (length, 0, 0) for XY."""
    n = max(len(g.categories), 1)
    if g.family == "column" or g.x_as_columns:
        # columns 2/3 slot in from both ends (verified, 3 columns); stacked and separated graphs have a
        # length of their own (E-types: 95.76 and 143.89 pt whatever the number of slots)
        length = g.x_length * DRAWN if g.x_length else g.x_columns_length or st.column_slot * (n + 1 / 3)
        slot = length / (n + 1 / 3)
        return length, slot * 2 / 3, slot
    if g.family == "grouped":
        length = g.x_length * DRAWN if g.x_length else st.grouped_x_length
        k = max(len(g.series), 1)
        units = n * k + (n - 1) * st.grouped_gap + 2 * st.grouped_end
        pitch = length / units  # bar pitch
        return length, st.grouped_end * pitch + k * pitch / 2, k * pitch + st.grouped_gap * pitch
    return (g.x_length * DRAWN if g.x_length else st.xy_x_length), 0.0, 0.0


DRAWN = 215.87 / 216  # Prism draws axes ~0.06 % short of their stored length (measured)


def bar_pitch(g: Graph, st: Style = DEFAULT) -> float:
    """Grouped graphs: distance between neighbouring bars of a group, in X
    data units (category pitch = 1)."""
    k = max(len(g.series), 1)
    return 1 / (k + st.grouped_gap)


def layout(g: Graph, st: Style = DEFAULT) -> Layout:
    """Everything is placed relative to the plot rectangle (titles, legend and
    annotations from Prism's stored positions when present, else Prism's
    default rules); the page is then the bounding box plus the margin (Prism
    takes the margin from the leftmost / topmost element: verified on the
    default graphs, including a title wider than the plot)."""
    if g.family == "pie":
        return _layout_pie(g, st)
    if g.heatmap is not None:
        return _layout_heat(g, st)
    if g.waffle is not None:
        return _layout_waffle(g, st)
    if g.horizontal and g.family in ("column", "grouped"):
        return _layout_h(g, st)
    ensure_app()
    (xlo, xhi, xt), (ylo, yhi, yt) = resolve_axes(g)
    lab = _metrics(_sfont(g, g.y_axis.label_style, st.tick_label_size, True))  # Y tick labels
    xlab = _metrics(_sfont(g, g.x_axis.label_style, st.tick_label_size, True))
    ttl = _metrics(_sfont(g, g.y_axis.title_style, st.axis_title_size, True))
    xttl = _metrics(_sfont(g, g.x_axis.title_style, st.axis_title_size, True))
    big = _metrics(_sfont(g, g.title_style, st.title_size, True))
    m = st.margin
    ylen = g.y_length * DRAWN if g.y_length else st.y_length
    xlen, first, pitch = _x_geometry(g, st)
    boxes: list[tuple[float, float, float, float]] = [(0.0, 0.0, xlen, ylen)]
    # Y tick labels, and how far the top label's line box rises above the axis end
    yticks = y_scale(g, ylo, yhi, yt, 0, 1).ticks()
    ylab_w = max((text_width(lab, fmt_tick(v, yt, g.y_axis.log)) for v in yticks), default=0.0)
    lab_left = -(st.tick_length + st.y_label_gap + ylab_w)
    above = 0.0
    if yticks:
        sy = y_scale(g, ylo, yhi, yt, 0, 1)
        dist = (1 - sy(max(yticks))) * (g.y_length or st.y_length)
        above = max(0.0, lab.ascent() - lab.capHeight() / 2 - dist)
    boxes.append((lab_left, -above, 0.0, ylen))
    # Y title (line box rotated; its space is kept when the title is empty;
    # from_prism leaves hidden titles out of title_pos)
    yh = ttl.ascent() + ttl.descent()
    if g.y_axis.title_pos is not None:
        yt_left, yt_cy = g.y_axis.title_pos
    else:
        yt_left, yt_cy = lab_left - st.y_title_gap - yh, ylen / 2
    yt_left, yt_cy = yt_left + _off(g, "y.title")[0], yt_cy + _off(g, "y.title")[1]
    if g.y_axis.title or g.y_axis.title_space:
        half = text_width(ttl, g.y_axis.title, TRACK_TEXT) / 2 if g.y_axis.title else 0.0
        boxes.append((yt_left, yt_cy - half, yt_left + yh, yt_cy + half))
    # panel labels (three-way graphs) above the plot: the title goes above them
    if g.panel_labels:
        pm = _metrics(_sfont(g, g.x_axis.title_style, st.axis_title_size, True))
        boxes.append((0.0, -above - PANEL_GAP - pm.ascent() - pm.descent(), xlen, 0.0))
        above += PANEL_GAP + pm.ascent() + pm.descent()
    # graph title
    title_cx, title_top = xlen / 2, -above - st.title_gap - (big.ascent() + big.descent())
    if g.color_bar is not None or g.size_legend is not None or g.category_legend is not None:  # above the legends' titles
        title_top = min(title_top, -MV_TITLE_LEGENDS - big.ascent())
    if g.title:
        if g.title_pos is not None:
            px, py = g.title_pos
            title_cx = title_cx if px is None else px
            if py is not None and (g.title_snap is None or abs(py - title_top) <= g.title_snap):
                title_top = py
        title_cx, title_top = title_cx + _off(g, "title")[0], title_top + _off(g, "title")[1]
        tw = text_width(big, g.title, TRACK_TEXT)
        boxes.append((title_cx - tw / 2, title_top, title_cx + tw / 2, title_top + big.ascent() + big.descent()))
    # X labels
    angle = 0.0
    if g.family in ("column", "grouped"):
        angle = _angle(g, xlab, pitch, st)
    extra = max((len(_lines(c)) - 1 for c in g.categories), default=0) * xlab.lineSpacing()
    if angle:
        a = math.radians(angle)
        drop = max((text_width(xlab, x) * math.sin(a) for c in g.categories for x in _lines(c)), default=0.0)
        x_label_baseline = ylen + st.tick_length + ROT_DY
        label_bottom = x_label_baseline + drop + (xlab.descent() + extra) * math.cos(a)
    else:
        x_label_baseline = ylen + st.tick_length + st.x_label_gap + xlab.ascent()
        label_bottom = x_label_baseline + xlab.descent() + extra
    boxes.append((0.0, ylen, xlen, label_bottom))
    # X title (its line is kept when the title is empty)
    xt_cx, xt_top = xlen / 2, label_bottom + st.x_title_gap
    if g.x_axis.title_pos is not None:
        xt_cx, xt_top = g.x_axis.title_pos
    xt_cx, xt_top = xt_cx + _off(g, "x.title")[0], xt_top + _off(g, "x.title")[1]
    if g.x_axis.title or g.x_axis.title_space:
        xw = text_width(xttl, g.x_axis.title, TRACK_TEXT) if g.x_axis.title else 0.0
        boxes.append((xt_cx - xw / 2, xt_top, xt_cx + xw / 2, xt_top + xttl.ascent() + xttl.descent()))
    # legend (relative to the plot's top-right corner)
    legend_rel = []
    # a colour bar and a sizes legend beside the plot (Prism's MV graphs): the legend starts after them
    bar_w, size_x = _mv_columns(g, st)
    for sh in g.shapes + [a["shape"] for a in g.annotations if a["kind"] == "shape"]:  # drawn objects are part of it
        w = float(sh.get("width") or 1.0)
        x0, y0, x1, y1 = shape_box(sh)
        boxes.append((x0 - w, y0 - w, x1 + w, y1 + w))
    if g.color_bar is not None:
        boxes.append((xlen + HEAT_BAR[1], -MV_TITLE_UP - lab.ascent(), xlen + bar_w, ylen))
    if g.category_legend is not None:
        n = len(g.category_legend["entries"])
        boxes.append((xlen + MV_GAP, -MV_TITLE_UP - lab.ascent(), xlen + bar_w,
                      MV_SIZE_FIRST + max(n - 1, 0) * MV_SIZE_PITCH + lab.descent() + 6))
    if g.size_legend is not None:
        sl = g.size_legend
        leg = _metrics(_sfont(g, g.legend_style, st.legend_size, False))
        n = len(sl["entries"])
        boxes.append((xlen + size_x, -MV_TITLE_UP - leg.ascent(),
                      xlen + _size_legend_right(g, st), MV_SIZE_FIRST + (n - 1) * MV_SIZE_PITCH + leg.descent() + 6))
        bar_w = _size_legend_right(g, st)
    if g.legend and (g.family != "column" or g.legend_on_columns) and g.series:
        leg = _metrics(_sfont(g, g.legend_style, st.legend_size, False))
        n_shown = sum(1 for s in g.series if s.in_legend)
        shown = 0
        for i, s in enumerate(g.series):
            if not s.in_legend:
                legend_rel.append(None)
                continue
            if g.legend_pos is not None and i < len(g.legend_pos):
                # Prism's entry box: the symbol centre 17.66 pt in, the text's line box
                # 7.5 pt down (verified: reproduces the default legend to 0.05 pt)
                dx, dy = g.legend_pos[i]
                cxi, base = xlen + dx + LEGEND_BOX_DX, dy + LEGEND_BOX_PAD + leg.ascent()
            else:
                slot = n_shown - 1 - shown if g.legend_reverse else shown
                cxi, base = xlen + bar_w + st.legend_symbol_dx, st.legend_first_baseline + slot * st.legend_pitch
            shown += 1
            cxi = cxi + _off(g, f"legend.{i}")[0] + _off(g, "legend")[0]
            base = base + _off(g, f"legend.{i}")[1] + _off(g, "legend")[1]
            legend_rel.append((cxi, base - leg.capHeight() / 2, cxi + st.legend_text_dx))
            boxes.append((cxi - s.symbol_size / 2, base - leg.ascent(),
                          cxi + st.legend_text_dx + text_width(leg, s.title, TRACK_TEXT), base + leg.descent()))
    # estimation plots: the right axis (labels and title) beside the plot
    right_ticks: list[tuple[float, str]] = []
    right_title_left = 0.0
    if g.estimation is not None:
        sy = Scale(ylo, yhi, yt, ylen, 0.0, g.y_axis.log)
        base = g.estimation["mean_a"]
        k0, k1 = math.ceil((ylo - base) / yt - 1e-9), math.floor((yhi - base) / yt + 1e-9)
        right_ticks = [(sy(base + k * yt), fmt_tick(k * yt, yt)) for k in range(k0, k1 + 1)]
        rw = max((text_width(lab, txt) for _, txt in right_ticks), default=0.0)
        lab_right = xlen + st.tick_length + st.y_label_gap + rw
        boxes.append((xlen, -above, lab_right, ylen))
        rts = _metrics(_sfont(g, g.estimation.get("right_style") or g.y_axis.title_style, st.axis_title_size, True))
        right_title_left = lab_right + EST_TITLE_GAP
        half = text_width(rts, g.estimation["right_title"], TRACK_TEXT) / 2
        boxes.append((right_title_left, ylen / 2 - half, right_title_left + rts.ascent() + rts.descent(), ylen / 2 + half))
    # annotations
    am = _metrics(_sfont(g, g.legend_style, st.legend_size, False))
    for a in g.annotations:
        if a["kind"] == "bracket" and a["points"]:
            xs_, ys_ = [x for x, _ in a["points"]], [y for _, y in a["points"]]
            boxes.append((min(xs_), min(ys_), max(xs_), max(ys_)))
        elif a["kind"] == "text" and a["text"]:
            _, w, h = _text_lines(am, a["text"])
            boxes.append((a["cx"] - w / 2, a["top"], a["cx"] + w / 2, a["top"] + h))
    # page: bounding box + margin
    x0 = min(b[0] for b in boxes)
    y0 = min(b[1] for b in boxes)
    x1 = max(b[2] for b in boxes)
    y1 = max(b[3] for b in boxes)
    ox, oy = m - x0, m - y0
    left, top, right, bottom = ox, oy, ox + xlen, oy + ylen
    if g.family in ("column", "grouped"):
        xs = Scale(xlo, xhi, xt, left + first, left + first + pitch * (xhi - xlo))
    else:
        xs = Scale(xlo, xhi, xt, left, right, g.x_axis.log)
    lay = Layout(round(x1 - x0 + 2 * m), round(y1 - y0 + 2 * m), (left, top, right, bottom), xs,
                 y_scale(g, ylo, yhi, yt, bottom, top), oy + title_top + big.ascent(), ox + yt_left + ttl.ascent(),
                 oy + x_label_baseline, oy + xt_top + xttl.ascent(),
                 [(ox + e[0], oy + e[1], ox + e[2]) if e is not None else None for e in legend_rel], angle)
    lay.title_cx, lay.x_title_cx, lay.y_title_cy = ox + title_cx, ox + xt_cx, oy + yt_cy
    lay.right_ticks = [(oy + y, txt) for y, txt in right_ticks]
    lay.right_title_left = ox + right_title_left
    return lay


# ----------------------------------------------------------------- draw
def _text_lines(m, text: str) -> tuple[list[str], float, float]:
    """A free text's lines, its width and its height (lines one line
    spacing apart)."""
    lines = text.split("\n")
    w = max((text_width(m, x, TRACK_TEXT) for x in lines), default=0.0)
    return lines, w, (len(lines) - 1) * m.lineSpacing() + m.ascent() + m.descent()


PIE_SWATCH = (15.34, 8.23)  # pie legend swatch, bottom on the text baseline (measured)


def _layout_pie(g: Graph, st: Style) -> Layout:
    """A pie fills the plot rectangle (no axes); title, legend entries and
    annotations as in layout(); page = bounding box + margin."""
    ensure_app()
    m = st.margin
    d = (g.x_length or st.y_length) * DRAWN
    boxes = [(0.0, 0.0, d, d)]
    big = _metrics(_sfont(g, g.title_style, st.title_size, True))
    title_cx, title_top = d / 2, -st.title_gap - (big.ascent() + big.descent())
    if g.title:
        if g.title_pos is not None:
            px, py = g.title_pos
            title_cx = title_cx if px is None else px
            if py is not None and (g.title_snap is None or abs(py - title_top) <= g.title_snap):
                title_top = py
        tw = text_width(big, g.title, TRACK_TEXT)
        boxes.append((title_cx - tw / 2, title_top, title_cx + tw / 2, title_top + big.ascent() + big.descent()))
    leg = _metrics(_sfont(g, g.legend_style, st.legend_size, False))
    rel = []
    texts = g.legend_texts or []
    for i, (dx, dy) in enumerate(g.legend_pos or []):
        cxi, base = d + dx + LEGEND_BOX_DX, dy + LEGEND_BOX_PAD + leg.ascent()
        txt = texts[i] if i < len(texts) else ""
        swatch = g.legend_fills is not None and i < len(g.legend_fills) and g.legend_fills[i] is not None
        tx = cxi + st.legend_text_dx if swatch else d + dx + LEGEND_BOX_PAD  # a label alone: from the box padding
        rel.append((cxi, base - leg.capHeight() / 2, tx))
        boxes.append((cxi - PIE_SWATCH[0] / 2 if swatch else tx, base - leg.ascent(),
                      tx + text_width(leg, txt, TRACK_TEXT), base + leg.descent()))
    am = _metrics(_sfont(g, g.legend_style, st.legend_size, False))
    for a in g.annotations:
        if a["kind"] == "bracket" and a["points"]:
            xs_, ys_ = [x for x, _ in a["points"]], [y for _, y in a["points"]]
            boxes.append((min(xs_), min(ys_), max(xs_), max(ys_)))
        elif a["kind"] == "text" and a["text"]:
            _, w, h = _text_lines(am, a["text"])
            boxes.append((a["cx"] - w / 2, a["top"], a["cx"] + w / 2, a["top"] + h))
    x0, y0 = min(b[0] for b in boxes), min(b[1] for b in boxes)
    x1, y1 = max(b[2] for b in boxes), max(b[3] for b in boxes)
    ox, oy = m - x0, m - y0
    lay = Layout(round(x1 - x0 + 2 * m), round(y1 - y0 + 2 * m), (ox, oy, ox + d, oy + d), Scale(0, 1, 1, ox, ox + d),
                 Scale(0, 1, 1, oy + d, oy), oy + title_top + big.ascent(),
                 legend=[(ox + a, oy + b, ox + c) for a, b, c in rel])
    lay.title_cx = ox + title_cx
    return lay


STACKED_BAR_WIDTH = 0.5  # of the pie's square (Prism's export of its stacked bar: 306 of 607 px)


def _draw_pie(p, g: Graph, lay: Layout, st: Style) -> None:
    """Slices clockwise from 12 o'clock in row order (verified on the corpus
    pies), a donut's hole cut out; then title, legend swatches and texts,
    annotations."""
    from PySide6.QtCore import QPointF, QRectF, Qt
    from PySide6.QtGui import QPainterPath, QPen

    left, top, right, bottom = lay.plot
    cx, cy, r = (left + right) / 2, (top + bottom) / 2, (right - left) / 2
    s = g.series[0] if g.series else None
    vals = [v or 0.0 for v in (s.ys if s else [])]
    total = sum(vals)
    fills = (s.slice_fills if s else None) or []
    outer = QRectF(cx - r, cy - r, 2 * r, 2 * r)
    ri = r * (s.hole if s else 0.0)
    inner = QRectF(cx - ri, cy - ri, 2 * ri, 2 * ri)
    angle = 90.0  # Qt: degrees counter-clockwise from 3 o'clock
    outline = QPen(_qcolor(s.symbol_border), s.border_width) if s and s.border_width else QPen(Qt.NoPen)
    outline.setJoinStyle(Qt.MiterJoin)
    if s is not None and s.stacked_bar:  # one bar, the square's height and half its width, parts top down
        w, at = (right - left) * STACKED_BAR_WIDTH, top
        if g.horizontal:  # on its side: the square's width and half its height, parts left to right (E-types)
            w, at = (bottom - top) * STACKED_BAR_WIDTH, left
        for i, v in enumerate(vals):
            if total <= 0 or v <= 0:
                continue
            p.setPen(Qt.NoPen)
            p.setBrush(_qcolor(fills[i] if i < len(fills) else BAR_FILLS[i % len(BAR_FILLS)]))
            if g.horizontal:
                h = (right - left) * v / total
                p.drawRect(QRectF(at, cy - w / 2, h, w))
            else:
                h = (bottom - top) * v / total
                p.drawRect(QRectF(cx - w / 2, at, w, h))
            at += h
        if s.border_width:
            p.setPen(outline)
            p.setBrush(Qt.NoBrush)
            p.drawRect(QRectF(left, cy - w / 2, right - left, w) if g.horizontal else
                       QRectF(cx - w / 2, top, w, bottom - top))
        vals = []  # no slices
    for i, v in enumerate(vals):
        if total <= 0 or v <= 0:
            continue
        sweep = 360.0 * v / total
        path = QPainterPath()
        if ri > 0:
            path.arcMoveTo(outer, angle)
            path.arcTo(outer, angle, -sweep)
            path.arcTo(inner, angle - sweep, sweep)
        else:
            path.moveTo(QPointF(cx, cy))
            path.arcTo(outer, angle, -sweep)
        path.closeSubpath()
        p.setBrush(_qcolor(fills[i] if i < len(fills) else BAR_FILLS[i % len(BAR_FILLS)]))
        p.setPen(Qt.NoPen)
        p.drawPath(path)
        angle -= sweep
    if s and s.border_width and not s.stacked_bar:  # the outer border (PCFF_PiePlotData::clOuterBorderColor), a hole
        p.setPen(outline)
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(outer)
        if ri > 0:  # Prism outlines the hole too (E-donut)
            p.drawEllipse(inner)
    if g.title:
        f = _sfont(g, g.title_style, st.title_size, True)
        p.setFont(f)
        p.setPen(_qcolor(g.title_style.color))
        draw_text(p, lay.title_cx - text_width(_metrics(f), g.title, TRACK_TEXT) / 2, lay.title_baseline, g.title, TRACK_TEXT)
    lf = _sfont(g, g.legend_style, st.legend_size, False)
    lm = _metrics(lf)
    texts, lfills = g.legend_texts or [], g.legend_fills or []
    for i, (lx, ly, tx) in enumerate(lay.legend):
        base = ly + lm.capHeight() / 2
        if i < len(lfills) and lfills[i] is not None:
            p.setPen(outline)
            p.setBrush(_qcolor(lfills[i]))
            p.drawRect(QRectF(lx - PIE_SWATCH[0] / 2, base - PIE_SWATCH[1], *PIE_SWATCH))
        p.setFont(lf)
        p.setPen(_qcolor(g.legend_style.color))
        draw_text(p, tx, base, texts[i] if i < len(texts) else "", TRACK_TEXT)
    _draw_annotations(p, g, lay, st)


def _qcolor(c):
    from PySide6.QtGui import QColor

    return QColor(*c)


def _symbol(p, kind: str, cx: float, cy: float, size: float):
    """Prism's symbols, `size` = the circle's diameter; the other shapes fill
    a square of side 0.909 * size (5.75 next to a 6.32 circle; triangles and
    the diamond measured on the corpus PDFs)."""
    from PySide6.QtCore import QPointF, QRectF
    from PySide6.QtGui import QPolygonF

    h = size * SQUARE / 2
    if kind == "none":
        return
    if kind == "square":
        p.drawRect(QRectF(cx - h, cy - h, 2 * h, 2 * h))
    elif kind == "triangle":
        p.drawPolygon(QPolygonF([QPointF(cx, cy - h), QPointF(cx + h, cy + h), QPointF(cx - h, cy + h)]))
    elif kind == "triangle_down":
        p.drawPolygon(QPolygonF([QPointF(cx - h, cy - h), QPointF(cx + h, cy - h), QPointF(cx, cy + h)]))
    elif kind == "diamond":
        p.drawPolygon(QPolygonF([QPointF(cx, cy - h), QPointF(cx + h, cy), QPointF(cx, cy + h), QPointF(cx - h, cy)]))
    else:
        p.drawEllipse(QPointF(cx, cy), size / 2, size / 2)


SQUARE = 5.75 / 6.32
SYMBOL_BORDER = 0.72


def _symbol_pen(p, s: Series) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QPen

    p.setPen(QPen(_qcolor(s.symbol_border), SYMBOL_BORDER) if s.symbol_border else Qt.NoPen)


def _order(k: int) -> int:
    return 0 if k == 0 else (k + 1) // 2 * (1 if k % 2 else -1)


def spread(ys: list[float], size: float) -> list[float]:
    """Prism's arrangement of a column of points, in slots: from the top
    (largest value) down, each point takes the first free slot of 0, +1, -1,
    +2, ... (a slot is taken where a placed point is closer than one symbol in
    y), then each cluster of overlapping points is shifted so that its slots
    are centred (reproduces the default column scatter and grouped graphs,
    24 points). ys: page coordinates (y downwards)."""
    n = len(ys)
    slots = [0] * n
    placed: list[int] = []
    for i in sorted(range(n), key=lambda i: ys[i]):
        k = 0
        while any(slots[j] == _order(k) and abs(ys[j] - ys[i]) < size for j in placed):
            k += 1
        slots[i] = _order(k)
        placed.append(i)
    seen: set[int] = set()
    out = [0.0] * n
    for i in range(n):
        if i in seen:
            continue
        comp, stack = [], [i]
        while stack:
            a = stack.pop()
            if a in seen:
                continue
            seen.add(a)
            comp.append(a)
            stack += [b for b in range(n) if b not in seen and abs(ys[b] - ys[a]) < size]
        mid = (min(slots[c] for c in comp) + max(slots[c] for c in comp)) / 2
        for c in comp:
            out[c] = slots[c] - mid
    return out


def minor_ticks(ax, sc: Scale) -> int:
    """Minor intervals per major tick drawn on an axis: its setting, or what
    Prism chooses when they are automatic (autoscale.auto_minor)."""
    if not ax.minor_auto or sc.log:
        return ax.minor
    from .autoscale import auto_minor

    return auto_minor(sc.lo, sc.hi, sc.tick, abs(sc.p1 - sc.p0))


def draw(p, g: Graph, lay: Layout, st: Style = DEFAULT) -> None:
    """The graph, then the objects drawn on it (lines, arrows, boxes, ellipses)."""
    _draw_graph(p, g, lay, st)
    if g.shapes:
        _draw_shapes(p, g.shapes, lay, g)


# hatches over a bar's fill, Prism's 19 (0x009C +85 codes 1-19, refract.formats.graph_patch.PATTERN_CODES):
# key -> (kind, spacing pt, line width pt or dot radius); kinds: lines at an angle ("lines", degrees in
# ANGLES), "dots", "checker", "bricks", "texture"
PATTERNS = {".": ("dots", 2.4, 0.35), "checker": ("checker", 2.0, 0.0), "checker_large": ("checker", 4.0, 0.0),
            "-": ("lines", 3.0, 0.5), "|": ("lines", 3.0, 0.5), "/": ("lines", 3.0, 0.5), "\\": ("lines", 3.0, 0.5),
            "+": ("lines", 3.0, 0.5), "x": ("lines", 3.0, 0.5), "\\ bold": ("lines", 6.0, 1.6),
            "/ bold": ("lines", 6.0, 1.6), "| bold": ("lines", 6.0, 1.6), "- bold": ("lines", 6.0, 1.6),
            "+ bold": ("lines", 6.0, 1.6), "x bold": ("lines", 6.0, 1.6), "bricks_dark": ("bricks", 4.0, 0.8),
            "bricks": ("bricks", 4.0, 0.5), "scatter": ("dots", 5.0, 0.6), "texture": ("texture", 3.0, 0.5)}
ANGLES = {"-": (0.0,), "|": (90.0,), "/": (45.0,), "\\": (-45.0,), "+": (0.0, 90.0), "x": (45.0, -45.0)}


def _hatch(p, r, pattern: str | None, color, fill=None) -> None:
    """Prism's hatch `pattern` over rectangle r in `color` (black when None),
    clipped to it; fill: the bar's own fill (a dark pattern's mortar)."""
    from PySide6.QtCore import QPointF, QRectF, Qt
    from PySide6.QtGui import QPen

    spec = PATTERNS.get(pattern or "")
    if spec is None or r.width() <= 0 or r.height() <= 0:
        return
    kind, step, w = spec
    p.save()
    p.setClipRect(r, Qt.IntersectClip)
    c = _qcolor(color or (0, 0, 0, 255))
    pen = QPen(c, w)
    pen.setCapStyle(Qt.FlatCap)
    if kind in ("dots", "checker"):
        p.setPen(Qt.NoPen)
        p.setBrush(c)
        row, y = 0, r.top()
        while y < r.bottom():
            x = r.left() + ((step / 2 if row % 2 else 0.0) if kind == "dots" else (step if row % 2 else 0.0))
            while x < r.right():
                if kind == "dots":
                    p.drawEllipse(QPointF(x + step / 2, y + step / 2), w, w)
                    x += step
                else:
                    p.drawRect(QRectF(x, y, step, step))
                    x += 2 * step
            y += step
            row += 1
    elif kind == "bricks":
        if pattern == "bricks_dark":  # dark bricks, the fill's mortar between them
            p.fillRect(r, c)
            pen.setColor(_qcolor(fill or (255, 255, 255, 255)))
        p.setPen(pen)
        row, y = 0, r.top()
        while y < r.bottom():
            p.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))
            x = r.left() + (step if row % 2 else 0.0)
            while x < r.right():
                p.drawLine(QPointF(x, y), QPointF(x, y + step))
                x += 2 * step
            y += step
            row += 1
    elif kind == "texture":
        p.setPen(pen)
        row, y = 0, r.top() + step / 2
        while y < r.bottom():
            x = r.left() + (step / 2 if row % 2 else 0.0)
            while x < r.right():
                p.drawLine(QPointF(x, y), QPointF(x + step / 2, y))
                x += step
            y += step
            row += 1
    else:
        p.setPen(pen)
        span = r.width() + r.height()
        for a in ANGLES[pattern.split(" ")[0]]:
            if a == 0.0:
                y = r.top() + step / 2
                while y < r.bottom():
                    p.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))
                    y += step
            elif a == 90.0:
                x = r.left() + step / 2
                while x < r.right():
                    p.drawLine(QPointF(x, r.top()), QPointF(x, r.bottom()))
                    x += step
            else:  # diagonals spaced `step` across
                d, k = step * math.sqrt(2), -span
                while k < span:
                    if a > 0:  # "/": up to the right
                        p.drawLine(QPointF(r.left() + k, r.bottom()), QPointF(r.left() + k + span, r.bottom() - span))
                    else:
                        p.drawLine(QPointF(r.left() + k, r.top()), QPointF(r.left() + k + span, r.top() + span))
                    k += d
    p.restore()


NOTE_PAD = 3.0  # a text box written for Prism: its words and this much room around them (pt)
NOTE_ROOM = 1.15  # and some width to spare, so that Prism's own text metrics do not wrap the line


def note_size(note: dict) -> tuple[float, float]:
    """(width, height) pt of a text box (formatting NOTE) with its padding, as drawn."""
    from . import formatting

    m = _metrics(_sfont(Graph(), formatting.styled(TextStyle(), note), DEFAULT.legend_size, False))
    _, w, h = _text_lines(m, str(note.get("text", "")))
    return w * NOTE_ROOM + 2 * NOTE_PAD, h + 2 * NOTE_PAD


def shape_box(sh: dict) -> tuple[float, float, float, float]:
    """(x0, y0, x1, y1) of a drawn object (its marks), points from the plot's top-left."""
    from .shape_kinds import primitives

    xs, ys = [], []
    for pr in primitives(sh):
        x1, y1, x2, y2 = (float(pr.get(k) or 0.0) for k in ("x1", "y1", "x2", "y2"))
        xs += [x1, x2]
        ys += [y1, y2]
    return min(xs), min(ys), max(xs), max(ys)


LABEL_SIZE = 12.0  # pt: a drawn object's text (lines with text), Prism's default text size


def _shape_label(p, g, sh: dict, lay: Layout) -> None:
    from .shape_kinds import label_anchor

    text = str(sh.get("label") or "")
    if not text:
        return
    gg = g if g is not None else Graph()
    base = gg.sig_style or gg.legend_style
    ts = TextStyle(family=getattr(base, "family", None), size=float(sh.get("label_size") or LABEL_SIZE),
                   color=sh.get("label_color") or (0, 0, 0, 255))
    f = _sfont(gg, ts, ts.size, False)
    m = _metrics(f)
    x, y, side = label_anchor(sh)
    x, y = lay.plot[0] + x, lay.plot[1] + y
    w = text_width(m, text)
    p.setFont(f)
    p.setPen(_qcolor(ts.color))
    if side == "above":
        draw_text(p, x - w / 2, y, text)
    elif side == "right":
        draw_text(p, x, y + (m.ascent() - m.descent()) / 2, text)
    else:
        draw_text(p, x - w, y + (m.ascent() - m.descent()) / 2, text)


def _draw_shapes(p, shapes: list[dict], lay: Layout, g=None) -> None:
    from PySide6.QtCore import QPointF, QRectF, Qt
    from PySide6.QtGui import QPen, QPolygonF

    from .shape_kinds import PRIMITIVE, primitives

    left, top = lay.plot[0], lay.plot[1]
    for sh in shapes:
        kind = sh.get("kind", "line")
        if kind not in PRIMITIVE and kind != "roundrect_draw":
            if kind == "roundrect":  # drawn rounded here (a rectangle for Prism)
                _draw_shapes(p, [{**sh, "kind": "roundrect_draw"}], lay)
            else:
                _draw_shapes(p, primitives(sh), lay)
            _shape_label(p, g, sh, lay)
            continue
        x1, y1, x2, y2 = (left + float(sh.get("x1") or 0), top + float(sh.get("y1") or 0),
                          left + float(sh.get("x2") or 0), top + float(sh.get("y2") or 0))
        width = float(sh.get("width") or 1.0)
        col = _qcolor(sh.get("color") or (0, 0, 0, 255))
        pen = QPen(col, width) if width > 0 else QPen(Qt.NoPen)
        pen.setCapStyle(Qt.FlatCap)
        pen.setJoinStyle(Qt.MiterJoin)
        if sh.get("dash"):
            pen.setStyle(Qt.DashLine)
        p.setPen(pen)
        fill = sh.get("fill")
        p.setBrush(_qcolor(fill) if fill is not None and kind in ("rect", "ellipse", "roundrect_draw") else Qt.NoBrush)
        if kind == "roundrect_draw":
            r = QRectF(QPointF(x1, y1), QPointF(x2, y2)).normalized()
            rad = min(8.0, r.width() / 4, r.height() / 4)
            p.setBrush(_qcolor(fill) if fill is not None else Qt.NoBrush)
            p.drawRoundedRect(r, rad, rad)
        elif kind == "rect":
            p.drawRect(QRectF(QPointF(x1, y1), QPointF(x2, y2)).normalized())
        elif kind == "ellipse":
            p.drawEllipse(QRectF(QPointF(x1, y1), QPointF(x2, y2)).normalized())
        else:
            head = 3.0 + 2.5 * width if kind == "arrow" else 0.0
            d = math.hypot(x2 - x1, y2 - y1)
            if head and d > 0:  # the line stops at the head's base; a filled head at (x2, y2)
                ux, uy = (x2 - x1) / d, (y2 - y1) / d
                bx, by = x2 - ux * head, y2 - uy * head
                p.drawLine(QPointF(x1, y1), QPointF(bx, by))
                w = head * 0.45
                p.setPen(Qt.NoPen)
                p.setBrush(col)
                p.drawPolygon(QPolygonF([QPointF(x2, y2), QPointF(bx - uy * w, by + ux * w),
                                         QPointF(bx + uy * w, by - ux * w)]))
            else:
                p.drawLine(QPointF(x1, y1), QPointF(x2, y2))
        _shape_label(p, g, sh, lay)


def _draw_graph(p, g: Graph, lay: Layout, st: Style = DEFAULT) -> None:
    from PySide6.QtCore import QPointF, QRectF, Qt
    from PySide6.QtGui import QPen

    if g.background is not None:
        p.fillRect(QRectF(0, 0, lay.width, lay.height), _qcolor(g.background))

    if g.family == "pie":
        _draw_pie(p, g, lay, st)
        return
    if g.heatmap is not None:
        _draw_heat(p, g, lay, st)
        return
    if g.waffle is not None:
        _draw_waffle(p, g, lay, st)
        return
    if lay.horizontal:
        _draw_h(p, g, lay, st)
        return
    left, top, right, bottom = lay.plot
    black = _qcolor(g.axis_color or (0, 0, 0, 255))
    if g.plot_fill is not None:
        p.fillRect(QRectF(left, top, right - left, bottom - top), _qcolor(g.plot_fill))
    for s in g.series:  # bars under the axes (Prism's order)
        if s.kind == "bar" and g.estimation is None:
            _draw_bars(p, s, lay, st)
    pen = QPen(black, st.axis_width)
    pen.setCapStyle(Qt.FlatCap)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    hw = st.axis_width / 2
    p.drawLine(QPointF(left - hw, bottom), QPointF(right, bottom))
    if isinstance(lay.y, SegmentedScale):  # a broken Y axis: a line per segment, a cap on each lower one
        for i, sc in enumerate(lay.y.parts):
            p.drawLine(QPointF(left, sc.p0 + (hw if i == 0 else 0.0)), QPointF(left, sc.p1))
            if i + 1 < len(lay.y.parts):
                p.drawLine(QPointF(left - st.tick_length, sc.p1), QPointF(left + st.tick_length, sc.p1))
    else:
        p.drawLine(QPointF(left, bottom + hw), QPointF(left, top))
    lab_f = _sfont(g, g.y_axis.label_style, st.tick_label_size, True)
    p.setFont(lab_f)
    m = _metrics(lab_f)
    y_minor = minor_ticks(g.y_axis, lay.y)
    if lay.y.log and y_minor:
        for v in lay.y.ticks(1.0):
            p.drawLine(QPointF(left - st.minor_tick_length, lay.y(v)), QPointF(left + hw, lay.y(v)))
    elif y_minor:
        majors = {round(v / lay.y.tick) for v in lay.y.ticks()}
        for v in lay.y.ticks(lay.y.tick / y_minor):
            if round(v / lay.y.tick, 9) in majors:
                continue
            p.drawLine(QPointF(left - st.minor_tick_length, lay.y(v)), QPointF(left + hw, lay.y(v)))
    x_minor = minor_ticks(g.x_axis, lay.x) if g.family not in ("column", "grouped") else 0
    if x_minor and not lay.x.log:  # below the X axis, like its major ticks
        majors = {round(v / lay.x.tick) for v in lay.x.ticks()}
        for v in lay.x.ticks(lay.x.tick / x_minor):
            if round(v / lay.x.tick, 9) in majors:
                continue
            p.drawLine(QPointF(lay.x(v), bottom - hw), QPointF(lay.x(v), bottom + st.minor_tick_length))
    for v in lay.y.ticks():
        yy = lay.y(v)
        p.setPen(pen)
        p.drawLine(QPointF(left - st.tick_length, yy), QPointF(left + hw, yy))
        txt = fmt_tick(v, lay.y.tick, lay.y.log)
        p.setPen(_qcolor(g.y_axis.label_style.color))
        draw_text(p, left - st.tick_length - st.y_label_gap - text_width(m, txt), yy + m.capHeight() / 2, txt)
    xf = _sfont(g, g.x_axis.label_style, st.tick_label_size, True)
    p.setFont(xf)
    xm = _metrics(xf)
    xticks = list(range(len(g.categories))) if g.family in ("column", "grouped") else lay.x.ticks()
    for i, v in enumerate(xticks):
        xx = lay.x(v)
        p.setPen(pen)
        p.drawLine(QPointF(xx, bottom - hw), QPointF(xx, bottom + st.tick_length))
        txt = g.categories[i] if g.family in ("column", "grouped") else fmt_tick(v, lay.x.tick, lay.x.log)
        p.setPen(_qcolor(g.x_axis.label_style.color))
        lines = _lines(txt)
        if lay.label_angle:
            # the block's lines centred on the widest; its end at the tick
            wmax = max(text_width(xm, x) for x in lines)
            p.save()
            p.translate(xx + ROT_DX, lay.x_label_baseline)
            p.rotate(-lay.label_angle)
            for k, line in enumerate(lines):
                draw_text(p, -(wmax + text_width(xm, line)) / 2, k * xm.lineSpacing(), line)
            p.restore()
        else:
            for k, line in enumerate(lines):
                draw_text(p, xx - text_width(xm, line) / 2, lay.x_label_baseline + k * xm.lineSpacing(), line)
    tf = _sfont(g, g.x_axis.title_style, st.axis_title_size, True)
    tm = _metrics(tf)
    p.setFont(tf)
    p.setPen(_qcolor(g.x_axis.title_style.color))
    if g.x_axis.title:
        draw_text(p, lay.x_title_cx - text_width(tm, g.x_axis.title, TRACK_TEXT) / 2, lay.x_title_baseline, g.x_axis.title,
                  TRACK_TEXT)
    tf = _sfont(g, g.y_axis.title_style, st.axis_title_size, True)
    tm = _metrics(tf)
    p.setFont(tf)
    p.setPen(_qcolor(g.y_axis.title_style.color))
    if g.y_axis.title:
        p.save()
        p.translate(lay.y_title_baseline_x, lay.y_title_cy + text_width(tm, g.y_axis.title, TRACK_TEXT) / 2)
        p.rotate(-90)
        draw_text(p, 0, 0, g.y_axis.title, TRACK_TEXT)
        p.restore()
    if g.title:
        f = _sfont(g, g.title_style, st.title_size, True)
        p.setFont(f)
        p.setPen(_qcolor(g.title_style.color))
        draw_text(p, lay.title_cx - text_width(_metrics(f), g.title, TRACK_TEXT) / 2, lay.title_baseline, g.title,
                  TRACK_TEXT)
    if g.panel_labels:
        pf = _sfont(g, g.x_axis.title_style, st.axis_title_size, True)
        pmet = _metrics(pf)
        p.setFont(pf)
        p.setPen(_qcolor(g.x_axis.title_style.color))
        for cx, label in g.panel_labels:
            draw_text(p, lay.x(cx) - text_width(pmet, label, TRACK_TEXT) / 2, top - PANEL_GAP - pmet.descent(), label,
                      TRACK_TEXT)
    if g.dividers:  # groups side by side: a frame on top and a line between groups
        dpen = QPen(black, st.axis_width)
        dpen.setCapStyle(Qt.FlatCap)
        p.setPen(dpen)
        p.drawLine(QPointF(left - hw, top), QPointF(right + hw, top))
        p.drawLine(QPointF(right, top), QPointF(right, bottom))
        for d in g.dividers:
            p.drawLine(QPointF(lay.x(d), top), QPointF(lay.x(d), bottom))
    if g.estimation is not None:
        _draw_estimation(p, g, lay, st)
    else:
        # filled areas: Prism draws each plot whole, the last data set first, so the first one's
        # area lies on top (E-compare probe 11)
        order = g.series[::-1] if any(s.fill_area for s in g.series) else g.series
        for s in order:
            _draw_marks(p, s, lay, st)
    if g.color_bar is not None:
        _draw_color_bar(p, g, lay, st)
    if g.category_legend is not None:
        _draw_entries(p, g, g.category_legend, lay.plot[2] + MV_GAP, lay.plot[1], st)
    if g.size_legend is not None:
        _draw_size_legend(p, g, lay, st)
    _draw_annotations(p, g, lay, st)
    _draw_significance(p, g, lay, st)
    lf = _sfont(g, g.legend_style, st.legend_size, False)
    for s, entry in zip(g.series, lay.legend, strict=False):
        if entry is None:
            continue
        cx, cy, tx = entry
        if s.kind == "steps":  # a line with a censor mark (verified)
            lp = QPen(_qcolor(s.color), st.error_width)
            lp.setCapStyle(Qt.FlatCap)
            p.setPen(lp)
            p.drawLine(QPointF(cx - st.legend_line / 2, cy), QPointF(cx + st.legend_line / 2, cy))
            if s.sizes is not None:  # a symbol at each step: the legend shows the symbol (Prism, E-types)
                _symbol_pen(p, s)
                p.setBrush(_qcolor(s.point_color or s.color))
                _symbol(p, s.symbol, cx, cy, s.symbol_size)
            else:
                _censor(p, s, cx, cy, st)
        elif (s.kind == "bar" and not s.points) or s.kind in BOX_KINDS:
            p.setPen(QPen(black, st.bar_border))
            p.setBrush(_qcolor(s.fill))
            p.drawRect(cx - 5, cy - 5, 10, 10)
        else:
            _symbol_pen(p, s)
            p.setBrush(_qcolor(s.point_color or s.color))
            _symbol(p, s.symbol, cx, cy, s.symbol_size)
        own = s.legend_style
        ef = _sfont(g, own, st.legend_size, False) if own is not None else lf
        p.setPen(QPen(_qcolor(own.color if own is not None else (s.legend_color or g.legend_style.color)), 1))
        p.setFont(ef)
        draw_text(p, tx, cy + _metrics(ef).capHeight() / 2, s.title, TRACK_TEXT)


PANEL_GAP = 6.0  # plot top -> the panel labels' line box
EST_TITLE_GAP = 12.0  # right tick labels -> the right title's line box (Prism PDF)
EST_MEAN_BAR = 31.66 / 43.17  # mean-difference bar width, in category pitches (Prism PDF)
EST_CAP = 15.83 / 43.17  # its confidence interval's caps


def _draw_estimation(p, g: Graph, lay: Layout, st: Style) -> None:
    """The parts of an estimation plot (measured on Prism's PDF of a paired
    t test's plot): a frame line on top, a divider between the groups and the
    difference, the right axis (zero at group A's mean, same scale) with its
    ticks, labels and title, dotted lines at both groups' means across the
    plot; the groups' values (paired: each subject's two values joined); the
    differences, their mean as a bar and its confidence interval."""
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QPen

    e = g.estimation
    left, top, right, bottom = lay.plot
    black = _qcolor((0, 0, 0, 255))
    pen = QPen(black, st.axis_width)
    pen.setCapStyle(Qt.FlatCap)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    hw = st.axis_width / 2
    p.drawLine(QPointF(left - hw, top), QPointF(right + hw, top))
    p.drawLine(QPointF(right, top), QPointF(right, bottom + hw))
    div = lay.x(1.5)
    p.drawLine(QPointF(div, top), QPointF(div, bottom))
    lab_f = _sfont(g, g.y_axis.label_style, st.tick_label_size, True)
    m = _metrics(lab_f)
    p.setFont(lab_f)
    for y, txt in lay.right_ticks:
        p.setPen(pen)
        p.drawLine(QPointF(right - hw, y), QPointF(right + st.tick_length, y))
        p.setPen(_qcolor(g.y_axis.label_style.color))
        draw_text(p, right + st.tick_length + st.y_label_gap, y + m.capHeight() / 2, txt)
    ts = e.get("right_style") or g.y_axis.title_style
    tf = _sfont(g, ts, st.axis_title_size, True)
    tm = _metrics(tf)
    p.setFont(tf)
    p.setPen(_qcolor(ts.color))
    w = text_width(tm, e["right_title"], TRACK_TEXT)
    p.save()  # reads top to bottom
    p.translate(lay.right_title_left + tm.descent(), (top + bottom) / 2 - w / 2)
    p.rotate(90)
    draw_text(p, 0, 0, e["right_title"], TRACK_TEXT)
    p.restore()
    dots = QPen(black, st.axis_width)
    dots.setCapStyle(Qt.RoundCap)
    dots.setDashPattern([0.01, 1.6])  # round dots (pattern in pen widths)
    p.setPen(dots)
    for v in (e["mean_a"], e["mean_b"]):
        p.drawLine(QPointF(left + hw, lay.y(v)), QPointF(right - hw, lay.y(v)))
    color = _qcolor(e["color"])
    size, shape = e["symbol_size"], e.get("symbol", "circle")
    line = QPen(color, e["line_width"])
    line.setCapStyle(Qt.FlatCap)
    x0, x1, x2 = lay.x(0), lay.x(1), lay.x(2)

    def dot(x, y):
        p.setPen(Qt.NoPen)
        p.setBrush(color)
        _symbol(p, shape, x, y, size)

    if e["paired"]:
        for a, b in e["pairs"]:
            p.setPen(line)
            p.drawLine(QPointF(x0, lay.y(a)), QPointF(x1, lay.y(b)))
        for a, b in e["pairs"]:
            dot(x0, lay.y(a))
            dot(x1, lay.y(b))
    else:
        unit = abs(lay.x(1) - lay.x(0))
        for xc, vals, mean_ in ((x0, e["a"], e["mean_a"]), (x1, e["b"], e["mean_b"])):
            for slot, v in zip(spread([lay.y(v) for v in vals], size), vals, strict=False):
                dot(xc + slot * size * 1.36, lay.y(v))  # slots one symbol and a gap apart
            p.setPen(line)
            p.drawLine(QPointF(xc - unit * EST_MEAN_BAR / 2, lay.y(mean_)), QPointF(xc + unit * EST_MEAN_BAR / 2, lay.y(mean_)))
    unit = abs(lay.x(1) - lay.x(0))
    ma = e["mean_a"]
    for d in e["diffs"]:
        dot(x2, lay.y(ma + d))
    p.setPen(pen)
    p.drawLine(QPointF(x2 - unit * EST_MEAN_BAR / 2, lay.y(ma + e["mean"])),
               QPointF(x2 + unit * EST_MEAN_BAR / 2, lay.y(ma + e["mean"])))
    ci = QPen(black, 1.0)
    ci.setCapStyle(Qt.FlatCap)
    p.setPen(ci)
    lo, hi = lay.y(ma + e["lo"]), lay.y(ma + e["hi"])
    p.drawLine(QPointF(x2, lo), QPointF(x2, hi))
    for y in (lo, hi):
        p.drawLine(QPointF(x2 - unit * EST_CAP / 2, y), QPointF(x2 + unit * EST_CAP / 2, y))
    if not e["paired"]:
        dot(x2, lay.y(ma + e["mean"]))


BRACKET_LEG = 4.0  # pt: the bracket's ends reach down this far
BRACKET_PEN = 1.0
BRACKET_GAP = 2.0  # pt between the bracket and its label's baseline


def _draw_significance(p, g: Graph, lay: Layout, st: Style) -> None:
    """Significance brackets (data units) with their labels centred above."""
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QPainterPath, QPen

    if not g.significance:
        return
    pen = QPen(_qcolor((0, 0, 0, 255)), BRACKET_PEN)
    pen.setCapStyle(Qt.FlatCap)
    pen.setJoinStyle(Qt.MiterJoin)
    ts = g.sig_style or g.legend_style
    f = _sfont(g, ts, st.legend_size, False)
    m = _metrics(f)
    for j, b in enumerate(g.significance):
        if b.get("hidden"):
            continue
        bx, by = _off(g, f"bracket.{j}")  # the bracket moved, its label with it
        x1, x2, y = lay.x(b["x1"]) + bx + b.get("dl", 0.0), lay.x(b["x2"]) + bx + b.get("dr", 0.0), lay.y(b["y"]) + by
        ll, lr = max(0.0, BRACKET_LEG + b.get("ll", 0.0)), max(0.0, BRACKET_LEG + b.get("lr", 0.0))  # its legs
        path = QPainterPath(QPointF(x1, y + ll))
        path.lineTo(x1, y)
        path.lineTo(x2, y)
        path.lineTo(x2, y + lr)
        bpen = QPen(pen)
        if b.get("color") is not None:
            bpen.setColor(_qcolor(b["color"]))
        if b.get("width"):
            bpen.setWidthF(float(b["width"]))
        p.setPen(bpen)
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)
        own = b.get("style")
        bf, bm = (_sfont(g, own, st.legend_size, False), None) if own is not None else (f, m)
        bm = bm or _metrics(bf)
        p.setFont(bf)
        p.setPen(_qcolor((own or ts).color))
        dx, dy = _off(g, f"sig.{j}")
        draw_text(p, (x1 + x2) / 2 - text_width(bm, b["label"]) / 2 + dx, y - BRACKET_GAP + dy, b["label"])


def _draw_annotations(p, g: Graph, lay: Layout, st: Style) -> None:
    """Brackets (one path through their points) and free texts (centred on
    their box, line box from its top), as placed in Prism."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QPainterPath, QPen

    left, top = lay.plot[0], lay.plot[1]
    for a in g.annotations:
        if a["kind"] == "shape":  # a rectangle or ellipse placed in Prism
            _draw_shapes(p, [a["shape"]], lay)
        elif a["kind"] == "bracket" and a.get("arrow") and len(a["points"]) == 2:  # an arrow placed in Prism
            (xa, ya), (xb, yb) = a["points"]
            _draw_shapes(p, [{"kind": "arrow", "x1": xa, "y1": ya, "x2": xb, "y2": yb, "color": a["color"],
                              "width": a["width"]}], lay)
        elif a["kind"] == "bracket" and len(a["points"]) >= 2:
            path = QPainterPath()
            for k, (x, y) in enumerate(a["points"]):
                path.moveTo(left + x, top + y) if k == 0 else path.lineTo(left + x, top + y)
            pen = QPen(_qcolor(a["color"]), a["width"])
            pen.setCapStyle(Qt.FlatCap)
            pen.setJoinStyle(Qt.MiterJoin)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawPath(path)
        elif a["kind"] == "text" and a["text"]:
            ts = a["style"]
            f = _sfont(g, ts, st.legend_size, False)
            m = _metrics(f)
            if a.get("frame"):  # a text box's border, placed in Prism
                _, w, h = _text_lines(m, a["text"])
                _draw_shapes(p, [{"kind": "rect", "x1": a["cx"] - w / 2 - NOTE_PAD, "y1": a["top"] - NOTE_PAD,
                                  "x2": a["cx"] + w / 2 + NOTE_PAD, "y2": a["top"] + h + NOTE_PAD,
                                  "width": a["frame"][0], "color": a["frame"][1]}], lay)
            p.setFont(f)
            p.setPen(_qcolor(ts.color))
            for k, line in enumerate(_text_lines(m, a["text"])[0]):  # each line centred
                draw_text(p, left + a["cx"] - text_width(m, line, TRACK_TEXT) / 2,
                          top + a["top"] + m.ascent() + k * m.lineSpacing(), line, TRACK_TEXT)


def _draw_bars(p, s: Series, lay: Layout, st: Style) -> None:
    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtGui import QPen

    unit = abs(lay.x(1.0) - lay.x(0.0))
    y0 = lay.y(max(lay.y.lo, min(0.0, lay.y.hi)))
    bw = st.bar_border if s.border_width is None else s.border_width
    pen = QPen(_qcolor(s.color), bw)
    pen.setJoinStyle(Qt.MiterJoin)
    zero = y0
    for i, (x, y) in enumerate(zip(s.xs, s.ys, strict=False)):
        if y is None:
            continue
        b = s.base[i] if s.base is not None and i < len(s.base) else None
        y0 = lay.y(b) if b is not None else zero
        half = s.width * unit / 2
        # the border's outer edge sits at the value: the rectangle is inset by
        # half the border at the value end (verified)
        yv = lay.y(y) + (bw / 2 if lay.y(y) < y0 else -bw / 2)
        r = QRectF(lay.x(x) - half, min(y0, yv), 2 * half, abs(yv - y0))
        own = (s.bar_styles or {}).get(i) or {}  # this bar's own look (Format This Bar)
        fill = own.get("fill", s.fill)
        p.setPen(Qt.NoPen)
        p.setBrush(_qcolor(fill))
        p.drawRect(r)
        _hatch(p, r, own.get("pattern", s.pattern), own.get("pattern_color", s.pattern_color), fill)
        bwi = own.get("border_width", bw)
        if bwi > 0:
            bpen = QPen(_qcolor(own.get("border", s.color)), bwi)
            bpen.setJoinStyle(Qt.MiterJoin)
            p.setPen(bpen if own else pen)
            p.setBrush(Qt.NoBrush)
            p.drawRect(r)


def _draw_marks(p, s: Series, lay: Layout, st: Style) -> None:
    """Error bars, centre lines, then symbols."""
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QPainterPath, QPen

    unit = abs(lay.x(1.0) - lay.x(0.0))
    epen = QPen(_qcolor(s.error_color or s.color), s.error_width or st.error_width)
    pcol = _qcolor(s.point_color or s.color)
    epen.setCapStyle(Qt.FlatCap)
    if s.kind in BOX_KINDS:
        _draw_box(p, s, lay, st)
        return
    if s.fill_area:
        pts = [(lay.x(x), lay.y(y)) for x, y in zip(s.xs, s.ys, strict=False) if y is not None]
        if len(pts) > 1:
            base = lay.y(max(lay.y.lo, min(0.0, lay.y.hi)))
            area = QPainterPath(QPointF(pts[0][0], base))
            for xx, yy in pts:
                area.lineTo(xx, yy)
            area.lineTo(pts[-1][0], base)
            area.closeSubpath()
            p.setPen(Qt.NoPen)
            p.setBrush(_qcolor(s.fill))  # opaque, as Prism's default; a translucent fill keeps its alpha
            p.drawPath(area)
    if s.connect:
        path = QPainterPath()
        pts = [(lay.x(x), lay.y(y)) for x, y in zip(s.xs, s.ys, strict=False) if y is not None]
        for k, (xx, yy) in enumerate(pts):
            path.moveTo(xx, yy) if k == 0 else path.lineTo(xx, yy)
        p.setPen(QPen(_qcolor(s.line_color or s.color), s.line_width))
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)
    if s.kind == "line":
        return
    if s.kind == "steps":
        path = QPainterPath()
        for k, (x, y) in enumerate(zip(s.xs, s.ys, strict=True)):
            path.moveTo(lay.x(x), lay.y(y)) if k == 0 else path.lineTo(lay.x(x), lay.y(y))
        sp = QPen(_qcolor(s.color), st.error_width)
        sp.setCapStyle(Qt.FlatCap)
        sp.setJoinStyle(Qt.MiterJoin)
        if s.dash:
            sp.setStyle(Qt.DotLine)
        p.setPen(sp)
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)
        if s.sizes is None:
            for x, y in s.marks:
                _censor(p, s, lay.x(x), lay.y(y), st)
        else:  # a symbol at each step (where the curve lands) and at each censored subject (Prism, E-types)
            _symbol_pen(p, s)
            p.setBrush(_qcolor(s.point_color or s.color))
            for k, (x, y) in enumerate(zip(s.xs, s.ys, strict=True)):
                if k and s.xs[k - 1] == x and y is not None:
                    _symbol(p, s.symbol, lay.x(x), lay.y(y), s.symbol_size)
            for x, y in s.marks:
                _symbol(p, s.symbol, lay.x(x), lay.y(y), s.symbol_size)
        return
    for i, x in enumerate(s.xs):
        y = s.ys[i] if i < len(s.ys) else None
        xx = lay.x(x)
        lo = s.err_lo[i] if i < len(s.err_lo) else None
        hi = s.err_hi[i] if i < len(s.err_hi) else None
        cap = st.bar_cap_fraction * s.width * unit / 2 if s.kind == "bar" else st.xy_cap_width / 2
        p.setPen(epen)
        p.setBrush(Qt.NoBrush)
        ends = [e for e in (lo, hi) if e is not None]
        if ends and y is not None:  # one path per error bar, as Prism writes it
            path = QPainterPath()
            top, bot = max(ends + [y]), min(ends + [y])
            path.moveTo(xx, lay.y(bot))
            path.lineTo(xx, lay.y(top))
            for e in ends:
                path.moveTo(xx - cap, lay.y(e))
                path.lineTo(xx + cap, lay.y(e))
            p.drawPath(path)
        if s.kind == "scatter" and y is not None and not s.connect:  # connected: a line through the centres
            mpen = QPen(_qcolor(s.color), st.axis_width)
            mpen.setCapStyle(Qt.FlatCap)
            p.setPen(mpen)
            half = (s.width or st.mean_line_fraction) * unit / 2
            p.drawLine(QPointF(xx - half, lay.y(y)), QPointF(xx + half, lay.y(y)))
        if i < len(s.points) and s.points[i]:
            ys = [lay.y(v) for v in s.points[i]]
            _symbol_pen(p, s)
            p.setBrush(pcol)
            for yy, o in zip(ys, spread(ys, s.symbol_size), strict=True):
                _symbol(p, s.symbol, xx + o * s.spread_step, yy, s.symbol_size)
        if s.kind == "points" and y is not None:
            _symbol_pen(p, s)
            p.setBrush(pcol)
            size = s.sizes[i] if s.sizes is not None and i < len(s.sizes) else s.symbol_size
            _symbol(p, s.symbol, xx, lay.y(y), size)


BOX_KINDS = ("box", "violin", "floating")
BOX_MIN_N = 4  # fewer values: Prism draws the median and the whiskers' caps, no box (E-compare probe 16)
VIOLIN_OUTLINE, VIOLIN_LINES = 3.0, 1.0  # violin pens, times the box pen: 2.16 pt and 0.72 pt (Prism exports, E-compare)


def _draw_box(p, s: Series, lay: Layout, st: Style) -> None:
    """Box and whiskers (box q1..q3, a line at the median, whiskers to lo/hi
    with caps, the values beyond them as symbols), violins (the values'
    density, mirrored, with lines at the quartiles and the median) and floating
    bars (lo..hi with a line at the median or mean)."""
    from PySide6.QtCore import QPointF, QRectF, Qt
    from PySide6.QtGui import QPen

    unit = abs(lay.x(1.0) - lay.x(0.0))
    half = s.width * unit / 2
    pen = QPen(_qcolor(s.color), st.error_width if s.border_width is None else max(s.border_width, 0.5))
    pen.setJoinStyle(Qt.MiterJoin)
    pen.setCapStyle(Qt.FlatCap)
    for i, x in enumerate(s.xs):
        b = s.box[i] if s.box is not None and i < len(s.box) else None
        if not b:
            continue
        xx = lay.x(x)
        if s.kind == "violin" and not b.get("kde"):  # fewer than two values: no density to draw
            continue
        if s.kind == "violin":
            _violin(p, s, b, pen, half, xx, lay.y, False)
            continue
        if s.kind == "box" and b.get("n", BOX_MIN_N) < BOX_MIN_N:  # too few values: no box (Prism)
            cap = half * 0.5
            p.setPen(pen)
            p.drawLine(QPointF(xx, lay.y(b["lo"])), QPointF(xx, lay.y(b["hi"])))
            for v in (b["lo"], b["hi"], b["med"]):
                p.drawLine(QPointF(xx - cap, lay.y(v)), QPointF(xx + cap, lay.y(v)))
            continue
        lo, hi = (b["lo"], b["hi"]) if s.kind == "floating" else (b["q1"], b["q3"])
        r = QRectF(xx - half, lay.y(hi), 2 * half, lay.y(lo) - lay.y(hi))
        p.setPen(pen)
        p.setBrush(_qcolor(s.fill))
        p.drawRect(r)
        centre = b.get("centre", "median")
        if centre:
            v = b["mean"] if centre == "mean" else b["med"]
            p.drawLine(QPointF(xx - half, lay.y(v)), QPointF(xx + half, lay.y(v)))
        if s.kind == "box":
            cap = half * 0.5
            for end, edge in ((b["lo"], b["q1"]), (b["hi"], b["q3"])):
                p.drawLine(QPointF(xx, lay.y(edge)), QPointF(xx, lay.y(end)))
                p.drawLine(QPointF(xx - cap, lay.y(end)), QPointF(xx + cap, lay.y(end)))
            out = s.points[i] if i < len(s.points) else []
            if out:
                _symbol_pen(p, s)
                p.setBrush(_qcolor(s.point_color or s.color))
                ys = [lay.y(v) for v in out]
                for yy, o in zip(ys, spread(ys, s.symbol_size), strict=True):
                    _symbol(p, s.symbol, xx + o * s.symbol_size, yy, s.symbol_size)


def _violin(p, s: Series, b: dict, pen, half: float, at: float, value, horizontal: bool) -> None:
    """One violin: the density mirrored about `at` (page units across the
    categories), its values placed by `value`; a heavy outline and thin
    lines at the quartiles and the median, as Prism draws them."""
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QPainterPath, QPen

    def pt(v: float, w: float) -> QPointF:
        return QPointF(value(v), at - w) if horizontal else QPointF(at + w, value(v))

    peak = max(d for _, d in b["kde"]) or 1.0
    side = [(v, half * d / peak) for v, d in b["kde"]]
    path = QPainterPath(pt(*side[0]))
    for v, w in side[1:]:
        path.lineTo(pt(v, w))
    for v, w in reversed(side):
        path.lineTo(pt(v, -w))
    path.closeSubpath()
    outline = QPen(pen)  # Prism: a heavy outline, thin solid quartile and median lines (E-compare)
    outline.setWidthF(pen.widthF() * VIOLIN_OUTLINE)
    outline.setJoinStyle(Qt.RoundJoin)
    p.setPen(outline)
    p.setBrush(_qcolor(s.fill))
    p.drawPath(path)
    thin = QPen(pen)
    thin.setWidthF(pen.widthF() * VIOLIN_LINES)
    p.setPen(thin)
    for key in ("q1", "q3", "med"):
        if b.get(key) is None:
            continue
        w = half * _kde_at(b["kde"], b[key]) / peak
        p.drawLine(pt(b[key], w), pt(b[key], -w))


def _kde_at(kde: list[tuple[float, float]], v: float) -> float:
    for (a, da), (b, db) in itertools.pairwise(kde):
        if min(a, b) <= v <= max(a, b):
            return da + (db - da) * ((v - a) / (b - a) if b != a else 0.0)
    return 0.0


def _censor(p, s: Series, x: float, y: float, st: Style) -> None:
    """Censor mark: a vertical tick rising from the curve (verified)."""
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QPen

    pen = QPen(_qcolor(s.color), st.censor_width)
    pen.setCapStyle(Qt.FlatCap)
    p.setPen(pen)
    p.drawLine(QPointF(x, y), QPointF(x, y - st.censor_height))


# --------------------------------------------------------------- export
OVERFLOW_PAD = 2.0  # pt of room kept around objects beyond the graph's box


def overflow(g: Graph, lay: Layout, st: Style = DEFAULT) -> tuple[float, float, float, float]:
    """How far (pt: left, top, right, bottom; 0 when inside) the objects of
    the graph reach beyond its box (0, 0, lay.width, lay.height): drawn
    objects and their texts, objects and texts placed in Prism, and every
    text, wherever it was moved. Prism draws them all; so do the canvas and
    the exports (to_image / to_png / to_pdf / to_svg with them)."""
    left, top = lay.plot[0], lay.plot[1]
    xs, ys = [0.0, lay.width], [0.0, lay.height]
    for sh in g.shapes:
        if not sh:
            continue
        x0, y0, x1, y1 = shape_box(sh)
        w = float(sh.get("width") or 1.0) + 4.0  # the line and an arrow head
        xs += [left + x0 - w, left + x1 + w]
        ys += [top + y0 - w, top + y1 + w]
        if sh.get("label"):
            from .shape_kinds import label_anchor

            size = float(sh.get("label_size") or LABEL_SIZE)
            tw = 0.6 * size * len(str(sh["label"])) + 2
            x, y, side = label_anchor(sh)
            x0 = x - tw / 2 if side == "above" else (x if side == "right" else x - tw)
            xs += [left + x0, left + x0 + tw]
            ys += [top + y - 1.1 * size, top + y + 0.4 * size]
    for a in g.annotations:
        if a["kind"] == "bracket":
            for x, y in a["points"]:
                xs.append(left + x)
                ys.append(top + y)
        elif a["kind"] == "shape" and a.get("shape"):
            x0, y0, x1, y1 = shape_box(a["shape"])
            xs += [left + x0, left + x1]
            ys += [top + y0, top + y1]
    for t in text_items(g, lay, st):
        if t.text:
            xs += [t.rect[0], t.rect[2]]
            ys += [t.rect[1], t.rect[3]]
    for j in range(len(g.significance)):
        b = object_box(g, lay, f"bracket.{j}")
        if b is not None:
            xs += [b[0], b[2]]
            ys += [b[1], b[3]]
    pad = OVERFLOW_PAD

    def out(v: float) -> float:
        return math.ceil(v + pad) if v > 0 else 0.0

    return out(-min(xs)), out(-min(ys)), out(max(xs) - lay.width), out(max(ys) - lay.height)


def to_image(g: Graph, k: float, st: Style = DEFAULT, lay: Layout | None = None,
             margins: tuple[float, float, float, float] | None = None):
    """The graph as a QImage, k pixels per point. Drawn on a 72-dpi device so
    fonts are in points, then scaled (the geometry the exports use; a screen
    painter would size text by the screen's dpi). margins (pt: left, top,
    right, bottom; see overflow): room around the graph's box, the graph
    drawn that far in from the image's top-left."""
    from PySide6.QtGui import QColor, QImage, QPainter

    lay = lay or layout(g, st)
    ml, mt, mr, mb = margins or (0.0, 0.0, 0.0, 0.0)
    img = QImage(max(1, math.ceil((lay.width + ml + mr) * k)), max(1, math.ceil((lay.height + mt + mb) * k)),
                 QImage.Format_ARGB32)
    img.setDotsPerMeterX(round(72 / 0.0254))
    img.setDotsPerMeterY(round(72 / 0.0254))
    img.fill(QColor(255, 255, 255))
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.TextAntialiasing)
    p.scale(k, k)
    p.translate(ml, mt)
    draw(p, g, lay, st)
    p.end()
    return img


def to_png(g: Graph, path: str, dpi: float = 300, st: Style = DEFAULT) -> tuple[int, int]:
    lay = layout(g, st)
    img = to_image(g, dpi / 72, st, lay, overflow(g, lay, st))
    img.setDotsPerMeterX(round(dpi / 0.0254))
    img.setDotsPerMeterY(round(dpi / 0.0254))
    if not img.save(path):
        raise OSError(f"cannot write {path}")
    return img.width(), img.height()


def to_pdf(g: Graph, path: str, st: Style = DEFAULT) -> tuple[float, float]:
    from PySide6.QtCore import QMarginsF, QSizeF
    from PySide6.QtGui import QPageLayout, QPageSize, QPainter, QPdfWriter

    lay = layout(g, st)
    ml, mt, mr, mb = overflow(g, lay, st)  # objects beyond the graph's box are exported too
    W, H = lay.width + ml + mr, lay.height + mt + mb
    w = QPdfWriter(path)
    w.setResolution(72)
    w.setPageSize(QPageSize(QSizeF(W, H), QPageSize.Point))
    w.setPageMargins(QMarginsF(0, 0, 0, 0), QPageLayout.Point)
    w.setCreator("Refract")
    p = QPainter(w)
    p.setRenderHint(QPainter.Antialiasing)
    p.translate(ml, mt)
    draw(p, g, lay, st)
    p.end()
    return W, H


def to_svg(g: Graph, path: str, st: Style = DEFAULT) -> tuple[float, float]:
    from PySide6.QtCore import QRectF, QSize
    from PySide6.QtGui import QPainter
    from PySide6.QtSvg import QSvgGenerator

    lay = layout(g, st)
    ml, mt, mr, mb = overflow(g, lay, st)
    W, H = lay.width + ml + mr, lay.height + mt + mb
    gen = QSvgGenerator()
    gen.setFileName(path)
    gen.setResolution(72)
    gen.setSize(QSize(math.ceil(W), math.ceil(H)))
    gen.setViewBox(QRectF(0, 0, W, H))
    gen.setTitle(g.title or "graph")
    p = QPainter(gen)
    p.setRenderHint(QPainter.Antialiasing)
    p.translate(ml, mt)
    draw(p, g, lay, st)
    p.end()
    return W, H


# ------------------------------------------------------------- hit testing
HIT_SLOP = 6.0  # pt around lines and symbols that still count as a hit


def _seg_dist(x: float, y: float, x1: float, y1: float, x2: float, y2: float) -> float:
    dx, dy = x2 - x1, y2 - y1
    t = max(0.0, min(1.0, ((x - x1) * dx + (y - y1) * dy) / (dx * dx + dy * dy))) if dx or dy else 0.0
    return math.hypot(x - (x1 + t * dx), y - (y1 + t * dy))


def bracket_handles(g: Graph, lay: Layout, key: str) -> list[tuple[int, float, float]]:
    """A bracket's handles, page points: 1 / 2 its left / right end (wider, narrower), 3 / 4 the tips of
    its legs (longer, shorter): a significance bracket ("bracket.<j>"), one placed in Prism ("abr.<k>")."""
    kind, _, rest = key.partition(".")
    if not rest.isdigit():
        return []
    i = int(rest)
    if kind == "bracket" and i < len(g.significance) and not g.significance[i].get("hidden") and not lay.horizontal:
        b = g.significance[i]
        bx, by = _off(g, key)
        xa, xb, y = lay.x(b["x1"]) + bx + b.get("dl", 0.0), lay.x(b["x2"]) + bx + b.get("dr", 0.0), lay.y(b["y"]) + by
        ll, lr = max(0.0, BRACKET_LEG + b.get("ll", 0.0)), max(0.0, BRACKET_LEG + b.get("lr", 0.0))
        return [(1, xa, y), (2, xb, y), (3, xa, y + ll), (4, xb, y + lr)]
    if kind == "abr" and i < len(g.annotations) and g.annotations[i]["kind"] == "bracket":
        pts = g.annotations[i]["points"]
        if len(pts) < 2:
            return []
        left, top = lay.plot[0], lay.plot[1]
        lo, hi = min(q[0] for q in pts), max(q[0] for q in pts)
        ys_lo = [q[1] for q in pts if abs(q[0] - lo) < 1e-6]
        ys_hi = [q[1] for q in pts if abs(q[0] - hi) < 1e-6]
        bar = [q[1] for q in pts[1:-1]] or [pts[0][1]]  # the bar: the inner points
        out = [(1, left + lo, top + min(ys_lo, key=lambda v: abs(v - bar[0]))),
               (2, left + hi, top + min(ys_hi, key=lambda v: abs(v - bar[-1])))]
        if len(pts) >= 3:
            out += [(3, left + pts[0][0], top + pts[0][1]), (4, left + pts[-1][0], top + pts[-1][1])]
        return out
    return []


def object_box(g: Graph, lay: Layout, key: str) -> tuple[float, float, float, float] | None:
    """Page box (x0, y0, x1, y1) of a graph object other than a text:
    "shape.<n>", "bracket.<j>", "set.<i>" (its bars or symbols)."""
    kind, _, rest = key.partition(".")
    if not rest.isdigit():
        return None
    i = int(rest)
    left, top = lay.plot[0], lay.plot[1]
    if kind == "shape" and i < len(g.shapes):
        x0, y0, x1, y1 = shape_box(g.shapes[i])
        return left + x0, top + y0, left + x1, top + y1
    if kind == "bracket" and i < len(g.significance) and not lay.horizontal and not g.significance[i].get("hidden"):
        b = g.significance[i]
        bx, by = _off(g, f"bracket.{i}")
        xa, xb, yy = lay.x(b["x1"]) + bx + b.get("dl", 0.0), lay.x(b["x2"]) + bx + b.get("dr", 0.0), lay.y(b["y"]) + by
        leg = max(BRACKET_LEG + b.get("ll", 0.0), BRACKET_LEG + b.get("lr", 0.0), 0.0)
        return min(xa, xb), yy, max(xa, xb), yy + leg
    if kind == "abr" and i < len(g.annotations) and g.annotations[i]["kind"] == "bracket" and \
            len(g.annotations[i]["points"]) >= 2:
        pts = g.annotations[i]["points"]
        return (left + min(q[0] for q in pts), top + min(q[1] for q in pts), left + max(q[0] for q in pts),
                top + max(q[1] for q in pts))
    if kind == "set" and i < len(g.series) and not lay.horizontal and g.family != "pie":
        s, xs, ys = g.series[i], [], []
        unit = abs(lay.x(1.0) - lay.x(0.0))
        for k, sx in enumerate(s.xs):
            sy = s.ys[k] if k < len(s.ys) else None
            vals = ([sy] if sy is not None else []) + (list(s.points[k]) if k < len(s.points) else [])
            if s.kind == "bar" and sy is not None:
                vals.append(max(lay.y.lo, min(0.0, lay.y.hi)) if not s.base or s.base[k] is None else s.base[k])
            half = max(s.width * unit / 2, s.symbol_size / 2)
            for v in vals:
                xs += [lay.x(sx) - half, lay.x(sx) + half]
                ys.append(lay.y(v))
        if xs:
            return min(xs), min(ys) - s.symbol_size / 2, max(xs), max(ys) + s.symbol_size / 2
    return None


def _hits_primitive(sh: dict, x: float, y: float, left: float, top: float) -> bool:
    x1, y1, x2, y2 = (float(sh.get(k) or 0.0) for k in ("x1", "y1", "x2", "y2"))
    x1, x2, y1, y2 = left + x1, left + x2, top + y1, top + y2
    slop = max(HIT_SLOP, float(sh.get("width") or 1.0) / 2 + 2)
    kind = sh.get("kind")
    if kind in ("line", "arrow"):
        return _seg_dist(x, y, x1, y1, x2, y2) <= slop
    x0, xa = sorted((x1, x2))
    y0, ya = sorted((y1, y2))
    inside = x0 - slop <= x <= xa + slop and y0 - slop <= y <= ya + slop
    if kind == "ellipse" and inside:
        rx, ry = max((xa - x0) / 2, 1e-6), max((ya - y0) / 2, 1e-6)
        r = math.hypot((x - (x0 + xa) / 2) / rx, (y - (y0 + ya) / 2) / ry)
        return bool((r <= 1 and sh.get("fill") is not None) or abs(r - 1) * min(rx, ry) <= slop)
    return bool(inside and (sh.get("fill") is not None or
                            min(abs(x - x0), abs(x - xa), abs(y - y0), abs(y - ya)) <= slop))


def object_at(g: Graph, lay: Layout, x: float, y: float) -> str | None:
    """The graph object (not a text) at page point (x, y): a drawn object
    (the topmost), a significance bracket, or a data set's bars or symbols."""
    from .shape_kinds import primitives

    left, top = lay.plot[0], lay.plot[1]
    for n in range(len(g.shapes) - 1, -1, -1):
        if g.shapes[n] and any(_hits_primitive(pr, x, y, left, top) for pr in primitives(g.shapes[n])):
            return f"shape.{n}"
    for k, a in enumerate(g.annotations):  # brackets and arrows placed in Prism
        b = object_box(g, lay, f"abr.{k}")
        if b is not None and b[0] - HIT_SLOP <= x <= b[2] + HIT_SLOP and b[1] - HIT_SLOP <= y <= b[3] + HIT_SLOP and \
                any(_seg_dist(x, y, left + xa, top + ya, left + xb, top + yb) <= HIT_SLOP
                    for (xa, ya), (xb, yb) in zip(a["points"], a["points"][1:], strict=False)):
            return f"abr.{k}"
    for j in range(len(g.significance)):
        b = object_box(g, lay, f"bracket.{j}")
        if b is not None and b[0] - HIT_SLOP <= x <= b[2] + HIT_SLOP and b[1] - HIT_SLOP <= y <= b[3] + 1:
            return f"bracket.{j}"
    kind, i = hit(g, lay, x, y)
    if kind == "set" and i is not None and lay.plot[0] <= x <= lay.plot[2] and lay.plot[1] - HIT_SLOP <= y \
            <= lay.plot[3]:
        return f"set.{i}"
    return None


def hit(g: Graph, lay: Layout, x: float, y: float, st: Style = DEFAULT) -> tuple[str, int | None]:
    """What is at page point (x, y): ("title", None), ("x", None), ("y", None),
    ("set", i) for a data set (its bars, symbols, line or legend entry), or
    ("graph", None) for anything else on the page."""
    if g.family == "pie" or g.heatmap is not None or g.waffle is not None or lay.horizontal:
        return "graph", None
    left, top, right, bottom = lay.plot
    if g.title:
        big = _metrics(_sfont(g, g.title_style, st.title_size, True))
        w = text_width(big, g.title, TRACK_TEXT) / 2
        if abs(x - lay.title_cx) <= w + HIT_SLOP and lay.title_baseline - big.ascent() - HIT_SLOP <= y \
                <= lay.title_baseline + big.descent() + HIT_SLOP:
            return "title", None
    for i, entry in enumerate(lay.legend):  # legend entries: their symbol and text
        if entry is None:
            continue
        cx, cy, tx = entry
        if i < len(g.series) and cx - 10 <= x <= tx + 8 * max(1, len(g.series[i].title)) and abs(y - cy) <= 9:
            return "set", i
    if left <= x <= right + HIT_SLOP and top - HIT_SLOP <= y <= bottom:
        best, dist = None, HIT_SLOP
        unit = abs(lay.x(1.0) - lay.x(0.0))
        for i, s in enumerate(g.series):
            for k, sx in enumerate(s.xs):
                px = lay.x(sx)
                sy = s.ys[k] if k < len(s.ys) else None
                if s.kind == "bar" and sy is not None:
                    half = s.width * unit / 2
                    y0, y1 = sorted((lay.y(max(lay.y.lo, min(0.0, lay.y.hi))), lay.y(sy)))
                    if px - half <= x <= px + half and y0 - HIT_SLOP <= y <= y1 + HIT_SLOP:
                        return "set", i
                pts = ([sy] if sy is not None else []) + (list(s.points[k]) if k < len(s.points) else [])
                for v in pts:
                    d = math.hypot(x - px, y - lay.y(v))
                    if d <= max(dist, s.symbol_size / 2 + 2) and (best is None or d < dist):
                        best, dist = i, d
        if best is not None:
            return "set", best
        return "graph", None
    if x < left and top - HIT_SLOP <= y <= bottom + HIT_SLOP:
        return "y", None
    if y > bottom and left - HIT_SLOP <= x <= right + HIT_SLOP:
        return "x", None
    return "graph", None


# ------------------------------------------------------------- heat maps
COLORMAPS = {  # stops, low to high (the viridis family's are samples of the open colour maps)
    "viridis": ["#440154", "#414487", "#2a788e", "#22a884", "#7ad151", "#fde725"],
    "magma": ["#000004", "#3b0f70", "#8c2981", "#de4968", "#fe9f6d", "#fcfdbf"],
    "inferno": ["#000004", "#420a68", "#932667", "#dd513a", "#fca50a", "#fcffa4"],
    "plasma": ["#0d0887", "#6a00a8", "#b12a90", "#e16462", "#fca636", "#f0f921"],
    "grays": ["#000000", "#ffffff"],
    "blues": ["#f7fbff", "#9ecae1", "#2171b5", "#08306b"],
    "greenred": ["#1a9850", "#0b3d1f", "#000000", "#5c0f0f", "#d73027"],
    "rainbow": ["#6e40aa", "#2f6fe0", "#1ac7c2", "#52f667", "#d2e31f", "#fe9b2d", "#d23c4e"],
}
HEAT_BAR = (20.0, 18.0)  # colour bar width, gap from the cells
# Prism's MV legends (E-mv, its own bubble graphs measured at 300 dpi): titles 8.7 pt above the plot's
# top, left-aligned; a sizes legend in the next column, 18 pt after the colour bar's (its title or
# labels, whichever is wider), its symbols 7.6 pt in from the title's left, rows 18.5 pt apart, the
# first 8.7 pt below the plot's top, texts 4.5 pt after the largest symbol
MV_TITLE_UP, MV_GAP, MV_SIZE_IN, MV_SIZE_FIRST, MV_SIZE_PITCH, MV_SIZE_TEXT = 8.1, 18.0, 7.6, 8.7, 18.5, 4.5
MV_TITLE_LEGENDS = 28.8  # the graph title's baseline above the plot when legends sit beside it


def _entries_width(g: Graph, legend: dict, st: Style) -> float:
    """A titled MV legend's width: its symbols, the texts after the largest, or its title."""
    lf = _metrics(_sfont(g, g.legend_style, st.legend_size, False))
    big = max((e[-1] for e in legend["entries"]), default=0.0)
    texts = max((text_width(lf, e[0]) for e in legend["entries"]), default=0.0)
    return max(MV_SIZE_IN + big / 2 + MV_SIZE_TEXT + texts, text_width(lf, legend.get("title") or ""))


def _draw_entries(p, g: Graph, legend: dict, x: float, top: float, st: Style) -> None:
    """A titled MV legend at x: its title above the plot's top, then a symbol and text per entry."""
    from PySide6.QtCore import Qt

    lf = _sfont(g, g.legend_style, st.legend_size, False)
    m = _metrics(lf)
    big = max((e[-1] for e in legend["entries"]), default=0.0)
    p.setFont(lf)
    p.setPen(_qcolor((0, 0, 0, 255)))
    if legend.get("title"):
        draw_text(p, x, top - MV_TITLE_UP, legend["title"])
    for k, e in enumerate(legend["entries"]):
        text, d = e[0], e[-1]
        rgba = e[1] if len(e) == 3 else (0, 0, 0, 255)
        cy = top + MV_SIZE_FIRST + k * MV_SIZE_PITCH
        p.setPen(Qt.NoPen)
        p.setBrush(_qcolor(rgba))
        _symbol(p, "circle", x + MV_SIZE_IN, cy, d)
        p.setPen(_qcolor((0, 0, 0, 255)))
        draw_text(p, x + MV_SIZE_IN + big / 2 + MV_SIZE_TEXT, cy + m.capHeight() / 2, text)


def _mv_columns(g: Graph, st: Style) -> tuple[float, float]:
    """(right end of the first legend column - the colour bar's, or the
    categories' - and left of the sizes legend's), in points from the plot's
    right edge; (0, gap) with neither."""
    if g.color_bar is None and g.category_legend is not None:
        right = MV_GAP + _entries_width(g, g.category_legend, st)
        return right, right + MV_GAP
    if g.color_bar is None:
        return 0.0, MV_GAP
    cb = g.color_bar
    lf = _metrics(_sfont(g, g.legend_style, st.legend_size, False))
    step, ticks = _heat_ticks(cb["lo"], cb["hi"], MV_TICK_PARTS)
    tw = max((text_width(lf, fmt_tick(v, step)) for v in ticks), default=0.0)
    right = HEAT_BAR[1] + max(HEAT_BAR[0] + st.y_label_gap + tw, text_width(lf, cb.get("title") or ""))
    return right, right + MV_GAP


def _size_legend_right(g: Graph, st: Style) -> float:
    sl = g.size_legend or {"entries": [], "title": ""}
    lf = _metrics(_sfont(g, g.legend_style, st.legend_size, False))
    x = _mv_columns(g, st)[1]
    big = max((d for _t, d in sl["entries"]), default=0.0)
    texts = max((text_width(lf, t) for t, _d in sl["entries"]), default=0.0)
    return x + max(MV_SIZE_IN + big / 2 + MV_SIZE_TEXT + texts, text_width(lf, sl.get("title") or ""))


def _draw_size_legend(p, g: Graph, lay: Layout, st: Style) -> None:
    """The symbol sizes of a graph sized by a numeric variable (Prism's MV
    ContinuousSizesLegend): its title, then the smallest, middle and largest
    values with their symbols."""
    from PySide6.QtCore import Qt

    sl = g.size_legend
    _left, top, right, _bottom = lay.plot
    lf = _sfont(g, g.legend_style, st.legend_size, False)
    m = _metrics(lf)
    x = right + _mv_columns(g, st)[1]
    big = max((d for _t, d in sl["entries"]), default=0.0)
    p.setFont(lf)
    p.setPen(_qcolor((0, 0, 0, 255)))
    if sl.get("title"):
        draw_text(p, x, top - MV_TITLE_UP, sl["title"])
    for k, (text, d) in enumerate(sl["entries"]):
        cy = top + MV_SIZE_FIRST + k * MV_SIZE_PITCH
        p.setPen(Qt.NoPen)
        p.setBrush(_qcolor((0, 0, 0, 255)))
        _symbol(p, "circle", x + MV_SIZE_IN, cy, d)
        p.setPen(_qcolor((0, 0, 0, 255)))
        draw_text(p, x + MV_SIZE_IN + big / 2 + MV_SIZE_TEXT, cy + m.capHeight() / 2, text)


def colormap(name: str, f: float) -> tuple[int, int, int, int]:
    stops = COLORMAPS.get(name, COLORMAPS["viridis"])
    f = min(1.0, max(0.0, f))
    pos = f * (len(stops) - 1)
    i = min(int(pos), len(stops) - 2)
    t = pos - i
    a, b = stops[i].lstrip("#"), stops[i + 1].lstrip("#")
    ca = [int(a[k:k + 2], 16) for k in (0, 2, 4)]
    cb = [int(b[k:k + 2], 16) for k in (0, 2, 4)]
    return (*(round(x + (y - x) * t) for x, y in zip(ca, cb, strict=True)), 255)


def _draw_color_bar(p, g: Graph, lay: Layout, st: Style) -> None:
    """The colour bar of a graph coloured by a numeric variable (Prism's
    MV graphs: GradientColorLegend), beside the plot, its title above."""
    from PySide6.QtCore import QPointF, QRectF, Qt
    from PySide6.QtGui import QLinearGradient, QPen

    cb = g.color_bar
    _left, top, right, bottom = lay.plot
    bx = right + HEAT_BAR[1]
    alpha = cb.get("alpha", 255)
    grad = QLinearGradient(QPointF(0, bottom), QPointF(0, top))
    for k in range(11):
        grad.setColorAt(k / 10, _qcolor((*colormap(cb["cmap"], k / 10)[:3], alpha)))
    p.setPen(Qt.NoPen)
    p.setBrush(grad)
    bar = QRectF(bx, top, HEAT_BAR[0], bottom - top)
    p.drawRect(bar)
    pen = QPen(_qcolor((0, 0, 0, 255)), 0.5)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    p.drawRect(bar)
    lf = _sfont(g, g.legend_style, st.legend_size, False)
    m = _metrics(lf)
    p.setFont(lf)
    span = (cb["hi"] - cb["lo"]) or 1.0
    step, ticks = _heat_ticks(cb["lo"], cb["hi"], MV_TICK_PARTS)
    for v in ticks:
        y = bottom - (v - cb["lo"]) / span * (bottom - top)
        p.setPen(pen)
        p.drawLine(QPointF(bx + HEAT_BAR[0] - st.tick_length, y), QPointF(bx + HEAT_BAR[0], y))
        p.setPen(_qcolor((0, 0, 0, 255)))
        draw_text(p, bx + HEAT_BAR[0] + st.y_label_gap, y + m.capHeight() / 2, fmt_tick(v, step))
    if cb.get("title"):
        draw_text(p, bx, top - MV_TITLE_UP, cb["title"])


MV_TICK_PARTS = 5  # Prism's MV colour bar: 1.8..5.9 ticked by 1 (E-mv), a finer rule than the heat map's


def _heat_ticks(lo: float, hi: float, parts: int = 4) -> tuple[float, list[float]]:
    span = hi - lo or 1.0
    raw = span / parts
    mag = 10 ** math.floor(math.log10(raw))
    step = next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)
    k0, k1 = math.ceil(lo / step - 1e-9), math.floor(hi / step + 1e-9)
    return step, [k * step for k in range(k0, k1 + 1)]


HEAT_SIDE = 216.0


def _layout_heat(g: Graph, st: Style) -> Layout:
    """Cells (rows down, columns across) with row labels on the left, column
    labels below and a colour bar on the right."""
    ensure_app()
    h = g.heatmap
    nr, nc = max(len(h["rows"]), 1), max(len(h["cols"]), 1)
    # Prism's heat maps: square cells, the larger side 3 in (E-heat: 2 x 3, 2 x 5, 6 x 5 cells)
    cw = ch = min(HEAT_SIDE / nr, HEAT_SIDE / nc)
    lab = _metrics(_sfont(g, g.y_axis.label_style, st.tick_label_size, True))
    rw = max((text_width(lab, r) for r in h["rows"]), default=0.0)
    step, ticks = _heat_ticks(h["lo"], h["hi"])
    tw = max((text_width(lab, fmt_tick(v, step)) for v in ticks), default=0.0)
    big = _metrics(_sfont(g, g.title_style, st.title_size, True))
    m = st.margin
    title_h = (big.ascent() + big.descent() + st.title_gap) if g.title else 0.0
    left = m + rw + st.tick_length + st.y_label_gap
    top = m + title_h
    right, bottom = left + cw * nc, top + ch * nr
    width = right + HEAT_BAR[1] + HEAT_BAR[0] + st.tick_length + st.y_label_gap + tw + m
    height = bottom + st.tick_length + st.x_label_gap + lab.ascent() + lab.descent() + m
    lay = Layout(round(width), round(height), (left, top, right, bottom),
                 Scale(-0.5, nc - 0.5, 1.0, left, right), Scale(-0.5, nr - 0.5, 1.0, top, bottom),
                 m + big.ascent(), 0.0, bottom + st.tick_length + st.x_label_gap + lab.ascent(), 0.0, [], 0.0)
    lay.title_cx = (left + right) / 2
    return lay


def _draw_heat(p, g: Graph, lay: Layout, st: Style) -> None:
    from PySide6.QtCore import QPointF, QRectF, Qt
    from PySide6.QtGui import QLinearGradient, QPen

    h = g.heatmap
    left, top, right, bottom = lay.plot
    nr, nc = len(h["rows"]), len(h["cols"])
    cw, ch = (right - left) / max(nc, 1), (bottom - top) / max(nr, 1)
    span = (h["hi"] - h["lo"]) or 1.0
    p.setPen(Qt.NoPen)
    for r in range(nr):
        for c in range(nc):
            v = h["values"][r][c] if c < len(h["values"][r]) else None
            if v is None:
                continue
            p.setBrush(_qcolor(colormap(h["cmap"], (v - h["lo"]) / span)))
            p.drawRect(QRectF(left + c * cw, top + r * ch, cw + 0.3, ch + 0.3))
    pen = QPen(_qcolor(g.axis_color or (0, 0, 0, 255)), st.axis_width)
    pen.setJoinStyle(Qt.MiterJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    p.drawRect(QRectF(left, top, right - left, bottom - top))
    lf = _sfont(g, g.y_axis.label_style, st.tick_label_size, True)
    m = _metrics(lf)
    p.setFont(lf)
    for r, name in enumerate(h["rows"]):
        y = top + (r + 0.5) * ch
        p.setPen(pen)
        p.drawLine(QPointF(left - st.tick_length, y), QPointF(left, y))
        p.setPen(_qcolor(g.y_axis.label_style.color))
        draw_text(p, left - st.tick_length - st.y_label_gap - text_width(m, name), y + m.capHeight() / 2, name)
    xf = _sfont(g, g.x_axis.label_style, st.tick_label_size, True)
    xm = _metrics(xf)
    p.setFont(xf)
    for c, name in enumerate(h["cols"]):
        x = left + (c + 0.5) * cw
        p.setPen(pen)
        p.drawLine(QPointF(x, bottom), QPointF(x, bottom + st.tick_length))
        p.setPen(_qcolor(g.x_axis.label_style.color))
        draw_text(p, x - text_width(xm, name) / 2, lay.x_label_baseline, name)
    # colour bar
    bx = right + HEAT_BAR[1]
    grad = QLinearGradient(QPointF(0, bottom), QPointF(0, top))
    for k in range(11):
        grad.setColorAt(k / 10, _qcolor(colormap(h["cmap"], k / 10)))
    p.setPen(Qt.NoPen)
    p.setBrush(grad)
    bar = QRectF(bx, top, HEAT_BAR[0], bottom - top)
    p.drawRect(bar)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    p.drawRect(bar)
    step, ticks = _heat_ticks(h["lo"], h["hi"])
    p.setFont(lf)
    for v in ticks:
        y = bottom - (v - h["lo"]) / span * (bottom - top)
        p.setPen(pen)
        p.drawLine(QPointF(bx + HEAT_BAR[0], y), QPointF(bx + HEAT_BAR[0] + st.tick_length, y))
        p.setPen(_qcolor(g.y_axis.label_style.color))
        draw_text(p, bx + HEAT_BAR[0] + st.tick_length + st.y_label_gap, y + m.capHeight() / 2, fmt_tick(v, step))
    if g.title:
        f = _sfont(g, g.title_style, st.title_size, True)
        p.setFont(f)
        p.setPen(_qcolor(g.title_style.color))
        draw_text(p, lay.title_cx - text_width(_metrics(f), g.title, TRACK_TEXT) / 2, lay.title_baseline, g.title,
                  TRACK_TEXT)


# ------------------------------------------------------------- horizontal graphs
def _layout_h(g: Graph, st: Style) -> Layout:
    """Column and grouped graphs turned on their side: the categories down
    the left axis (first on top), the values along the bottom axis; titles,
    labels and the legend placed by the same rules as upright graphs."""
    ensure_app()
    (clo, chi, ct), (vlo, vhi, vt) = resolve_axes(g)
    lab = _metrics(_sfont(g, g.x_axis.label_style, st.tick_label_size, True))  # category labels
    vlab = _metrics(_sfont(g, g.y_axis.label_style, st.tick_label_size, True))  # value labels
    vtt = _metrics(_sfont(g, g.y_axis.title_style, st.axis_title_size, True))
    ctt = _metrics(_sfont(g, g.x_axis.title_style, st.axis_title_size, True))
    big = _metrics(_sfont(g, g.title_style, st.title_size, True))
    m = st.margin
    # Prism turns the upright graph on its side: the categories take the value axis's
    # length, the values the category axis's (E-compare)
    from dataclasses import replace as _replace

    cat_len = g.x_length * DRAWN if g.x_length else st.y_length
    clen, first, pitch = _x_geometry(_replace(g, x_length=cat_len / DRAWN), st)
    vlen = g.y_length * DRAWN if g.y_length else _x_geometry(_replace(g, x_length=None), st)[0]
    cat_w = max((text_width(lab, x) for c in g.categories for x in _lines(c)), default=0.0)
    ct_w = (ctt.ascent() + ctt.descent() + st.y_title_gap) if g.x_axis.title else 0.0
    title_h = (big.ascent() + big.descent() + st.title_gap) if g.title else 0.0
    left = m + ct_w + cat_w + st.tick_length + st.y_label_gap
    title_w = text_width(big, g.title, TRACK_TEXT) if g.title else 0.0  # centred over the plot: room for it
    left += max(0.0, m + title_w / 2 - (left + vlen / 2))
    top = m + title_h  # no value label above the plot (upright: the top tick label's half) (E-compare)
    right, bottom = left + vlen, top + clen
    vticks = Scale(vlo, vhi, vt, 0, 1, g.y_axis.log).ticks()
    last_w = text_width(vlab, fmt_tick(vticks[-1], vt, g.y_axis.log)) / 2 if vticks else 0.0
    lab_base = bottom + st.tick_length + st.x_label_gap + vlab.ascent()
    vt_base = lab_base + vlab.descent() + st.x_title_gap + vtt.ascent()
    height = (vt_base + vtt.descent() if g.y_axis.title else lab_base + vlab.descent()) + m
    legend = []
    leg_w = 0.0
    if g.legend and g.family != "column" and g.series:
        leg = _metrics(_sfont(g, g.legend_style, st.legend_size, False))
        shown, n_shown = 0, sum(1 for s in g.series if s.in_legend)
        for i, s in enumerate(g.series):
            if not s.in_legend:
                legend.append(None)
                continue
            slot = n_shown - 1 - shown if g.legend_reverse else shown  # stacked bars: last data set first
            cxi = right + last_w + st.legend_symbol_dx + _off(g, "legend")[0] + _off(g, f"legend.{i}")[0]
            base = top + st.legend_first_baseline + slot * st.legend_pitch + _off(g, "legend")[1] + \
                _off(g, f"legend.{i}")[1]
            shown += 1
            legend.append((cxi, base - leg.capHeight() / 2, cxi + st.legend_text_dx))
            leg_w = max(leg_w, cxi - right + st.legend_text_dx + text_width(leg, s.title, TRACK_TEXT))
    width = max(right + max(last_w, leg_w) + m, (left + right) / 2 + title_w / 2 + m)
    lay = Layout(round(width), round(height), (left, top, right, bottom),  # the first category at the bottom (Prism)
                 Scale(vlo, vhi, vt, left, right, g.y_axis.log), Scale(clo, chi, ct, bottom - first,
                                                                     bottom - first - pitch * (chi - clo)),
                 m + big.ascent() + _off(g, "title")[1], m + ctt.ascent(), lab_base, vt_base, legend, 0.0)
    lay.horizontal = True
    lay.title_cx = (left + right) / 2 + _off(g, "title")[0]
    lay.x_title_cx = (left + right) / 2
    lay.y_title_cy = (top + bottom) / 2
    return lay


def _draw_h(p, g: Graph, lay: Layout, st: Style) -> None:
    from PySide6.QtCore import QPointF, QRectF, Qt
    from PySide6.QtGui import QPainterPath, QPen

    left, top, right, bottom = lay.plot
    V, C = lay.x, lay.y  # value -> page x, category position -> page y
    black = _qcolor(g.axis_color or (0, 0, 0, 255))
    if g.plot_fill is not None:
        p.fillRect(QRectF(left, top, right - left, bottom - top), _qcolor(g.plot_fill))
    unit = abs(C(1.0) - C(0.0))
    zero = V(max(V.lo, min(0.0, V.hi)))
    for s in g.series:  # bars first, under the axes
        if s.kind != "bar":
            continue
        bw = st.bar_border if s.border_width is None else s.border_width
        for i, (c, v) in enumerate(zip(s.xs, s.ys, strict=False)):
            if v is None:
                continue
            b = s.base[i] if s.base is not None and i < len(s.base) else None
            x0 = V(b) if b is not None else zero
            half = s.width * unit / 2
            r = QRectF(min(x0, V(v)), C(c) - half, abs(V(v) - x0), 2 * half)
            p.setPen(Qt.NoPen)
            p.setBrush(_qcolor(s.fill))
            p.drawRect(r)
            _hatch(p, r, s.pattern, s.pattern_color, s.fill)
            if bw > 0:
                pen = QPen(_qcolor(s.color), bw)
                pen.setJoinStyle(Qt.MiterJoin)
                p.setPen(pen)
                p.setBrush(Qt.NoBrush)
                p.drawRect(r)
    pen = QPen(black, st.axis_width)
    pen.setCapStyle(Qt.FlatCap)
    hw = st.axis_width / 2
    p.setPen(pen)
    p.drawLine(QPointF(left - hw, bottom), QPointF(right, bottom))
    p.drawLine(QPointF(left, bottom + hw), QPointF(left, top))
    vf = _sfont(g, g.y_axis.label_style, st.tick_label_size, True)
    vm = _metrics(vf)
    p.setFont(vf)
    for v in V.ticks():
        xx = V(v)
        p.setPen(pen)
        p.drawLine(QPointF(xx, bottom - hw), QPointF(xx, bottom + st.tick_length))
        txt = fmt_tick(v, V.tick, V.log)
        p.setPen(_qcolor(g.y_axis.label_style.color))
        draw_text(p, xx - text_width(vm, txt) / 2, lay.x_label_baseline, txt)
    cf = _sfont(g, g.x_axis.label_style, st.tick_label_size, True)
    cm = _metrics(cf)
    p.setFont(cf)
    for i, name in enumerate(g.categories):
        yy = C(float(i))
        p.setPen(pen)
        p.drawLine(QPointF(left - st.tick_length, yy), QPointF(left + hw, yy))
        p.setPen(_qcolor(g.x_axis.label_style.color))
        lines = _lines(name)
        for k, line in enumerate(lines):
            dy = (k - (len(lines) - 1) / 2) * cm.lineSpacing()
            draw_text(p, left - st.tick_length - st.y_label_gap - text_width(cm, line), yy + dy + cm.capHeight() / 2,
                      line)
    if g.y_axis.title:  # the values' title, below
        tf = _sfont(g, g.y_axis.title_style, st.axis_title_size, True)
        p.setFont(tf)
        p.setPen(_qcolor(g.y_axis.title_style.color))
        draw_text(p, lay.x_title_cx - text_width(_metrics(tf), g.y_axis.title, TRACK_TEXT) / 2, lay.x_title_baseline,
                  g.y_axis.title, TRACK_TEXT)
    if g.x_axis.title:  # the categories' title, on the left, bottom up
        tf = _sfont(g, g.x_axis.title_style, st.axis_title_size, True)
        tm = _metrics(tf)
        p.setFont(tf)
        p.setPen(_qcolor(g.x_axis.title_style.color))
        w = text_width(tm, g.x_axis.title, TRACK_TEXT)
        p.save()
        p.translate(lay.y_title_baseline_x, lay.y_title_cy + w / 2)
        p.rotate(-90)
        draw_text(p, 0, 0, g.x_axis.title, TRACK_TEXT)
        p.restore()
    if g.title:
        f = _sfont(g, g.title_style, st.title_size, True)
        p.setFont(f)
        p.setPen(_qcolor(g.title_style.color))
        draw_text(p, lay.title_cx - text_width(_metrics(f), g.title, TRACK_TEXT) / 2, lay.title_baseline, g.title,
                  TRACK_TEXT)
    for s in g.series:
        epen = QPen(_qcolor(s.error_color or s.color), s.error_width or st.error_width)
        epen.setCapStyle(Qt.FlatCap)
        pcol = _qcolor(s.point_color or s.color)
        half = s.width * unit / 2
        if s.connect:
            path = QPainterPath()
            pts = [(V(v), C(c)) for c, v in zip(s.xs, s.ys, strict=False) if v is not None]
            for k, (xx, yy) in enumerate(pts):
                path.moveTo(xx, yy) if k == 0 else path.lineTo(xx, yy)
            p.setPen(QPen(_qcolor(s.line_color or s.color), s.line_width))
            p.setBrush(Qt.NoBrush)
            p.drawPath(path)
        for i, c in enumerate(s.xs):
            yy = C(c)
            v = s.ys[i] if i < len(s.ys) else None
            if s.kind in BOX_KINDS:
                b = s.box[i] if s.box is not None and i < len(s.box) else None
                if not b:
                    continue
                bp = QPen(_qcolor(s.color), st.error_width)
                p.setPen(bp)
                p.setBrush(_qcolor(s.fill))
                if s.kind == "violin":
                    if not b.get("kde"):
                        continue
                    _violin(p, s, b, bp, half, yy, V, True)
                    continue
                if s.kind == "box" and b.get("n", BOX_MIN_N) < BOX_MIN_N:  # too few values: no box (Prism)
                    cap = half * 0.5
                    p.drawLine(QPointF(V(b["lo"]), yy), QPointF(V(b["hi"]), yy))
                    for v_ in (b["lo"], b["hi"], b["med"]):
                        p.drawLine(QPointF(V(v_), yy - cap), QPointF(V(v_), yy + cap))
                    continue
                lo, hi = (b["lo"], b["hi"]) if s.kind == "floating" else (b["q1"], b["q3"])
                p.drawRect(QRectF(V(lo), yy - half, V(hi) - V(lo), 2 * half))
                centre = b.get("centre", "median")
                if centre:
                    cv = b["mean"] if centre == "mean" else b["med"]
                    p.drawLine(QPointF(V(cv), yy - half), QPointF(V(cv), yy + half))
                if s.kind == "box":
                    cap = half * 0.5
                    for end, edge in ((b["lo"], b["q1"]), (b["hi"], b["q3"])):
                        p.drawLine(QPointF(V(edge), yy), QPointF(V(end), yy))
                        p.drawLine(QPointF(V(end), yy - cap), QPointF(V(end), yy + cap))
                    out = s.points[i] if i < len(s.points) else []
                    if out:  # the values beyond the whiskers (or all of them), as upright
                        _symbol_pen(p, s)
                        p.setBrush(pcol)
                        xs_ = [V(val) for val in out]
                        for xx, o in zip(xs_, spread(xs_, s.symbol_size), strict=True):
                            _symbol(p, s.symbol, xx, yy - o * s.symbol_size, s.symbol_size)
                continue
            lo = s.err_lo[i] if i < len(s.err_lo) else None
            hi = s.err_hi[i] if i < len(s.err_hi) else None
            ends = [e for e in (lo, hi) if e is not None]
            if ends and v is not None:
                cap = st.bar_cap_fraction * half if s.kind == "bar" else st.xy_cap_width / 2
                p.setPen(epen)
                a, z = min(ends + [v]), max(ends + [v])
                p.drawLine(QPointF(V(a), yy), QPointF(V(z), yy))
                for e in ends:
                    p.drawLine(QPointF(V(e), yy - cap), QPointF(V(e), yy + cap))
            if s.kind == "scatter" and v is not None and not s.connect:
                mp = QPen(_qcolor(s.color), st.axis_width)
                mp.setCapStyle(Qt.FlatCap)
                p.setPen(mp)
                mh = (s.width or st.mean_line_fraction) * unit / 2
                p.drawLine(QPointF(V(v), yy - mh), QPointF(V(v), yy + mh))
            if i < len(s.points) and s.points[i]:
                xs_ = [V(val) for val in s.points[i]]
                _symbol_pen(p, s)
                p.setBrush(pcol)
                for xx, o in zip(xs_, spread(xs_, s.symbol_size), strict=True):
                    _symbol(p, s.symbol, xx, yy + o * s.spread_step, s.symbol_size)
            if s.kind == "points" and v is not None:
                _symbol_pen(p, s)
                p.setBrush(pcol)
                _symbol(p, s.symbol, V(v), yy, s.symbol_size)
    lf = _sfont(g, g.legend_style, st.legend_size, False)
    for s, entry in zip(g.series, lay.legend, strict=False):
        if entry is None:
            continue
        cx, cy, tx = entry
        if s.kind in ("bar",) + BOX_KINDS:
            p.setPen(QPen(black, st.bar_border))
            p.setBrush(_qcolor(s.fill))
            p.drawRect(QRectF(cx - 5, cy - 5, 10, 10))
        else:
            _symbol_pen(p, s)
            p.setBrush(_qcolor(s.point_color or s.color))
            _symbol(p, s.symbol, cx, cy, s.symbol_size)
        p.setPen(_qcolor(s.legend_color or g.legend_style.color))
        p.setFont(lf)
        draw_text(p, tx, cy + _metrics(lf).capHeight() / 2, s.title, TRACK_TEXT)


# ------------------------------------------------------------- waffle charts
WAFFLE_CELL, WAFFLE_GAP = 14.0, 2.0


def _layout_waffle(g: Graph, st: Style) -> Layout:
    ensure_app()
    w = g.waffle
    big = _metrics(_sfont(g, g.title_style, st.title_size, True))
    leg = _metrics(_sfont(g, g.legend_style, st.legend_size, False))
    m = st.margin
    title_h = (big.ascent() + big.descent() + st.title_gap) if g.title else 0.0
    left, top = m, m + title_h
    size = w["cols"] * (WAFFLE_CELL + WAFFLE_GAP) - WAFFLE_GAP
    right, bottom = left + size, top + w["rows"] * (WAFFLE_CELL + WAFFLE_GAP) - WAFFLE_GAP
    legend = []
    lw = 0.0
    for i, (name, _v, _f) in enumerate(w["parts"]):
        cx, base = right + 24.0, top + 10 + i * st.legend_pitch
        legend.append((cx, base - leg.capHeight() / 2, cx + 14.0))
        lw = max(lw, 38.0 + text_width(leg, name, TRACK_TEXT))
    lay = Layout(round(right + lw + m), round(max(bottom, top + len(w["parts"]) * st.legend_pitch) + m),
                 (left, top, right, bottom), Scale(0, 1, 1, left, right), Scale(0, 1, 1, bottom, top),
                 m + big.ascent(), 0.0, 0.0, 0.0, legend, 0.0)
    lay.title_cx = (left + right) / 2
    return lay


def _draw_waffle(p, g: Graph, lay: Layout, st: Style) -> None:
    """Parts of a whole as cells of a 10 x 10 grid, filled part by part (rounded to whole cells)."""
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QPen

    w = g.waffle
    total = sum(v for _, v, _ in w["parts"]) or 1.0
    n = w["rows"] * w["cols"]
    counts = [round(v / total * n) for _, v, _ in w["parts"]]
    if counts:
        counts[-1] = max(0, n - sum(counts[:-1]))
    fills = [f for (_, _, f), c in zip(w["parts"], counts, strict=True) for _ in range(c)]
    left, top = lay.plot[0], lay.plot[1]
    p.setPen(QPen(_qcolor((0, 0, 0, 255)), 0.5))
    for k in range(n):
        r, c = divmod(k, w["cols"])
        p.setBrush(_qcolor(fills[k] if k < len(fills) else (255, 255, 255, 255)))
        p.drawRect(QRectF(left + c * (WAFFLE_CELL + WAFFLE_GAP), top + (w["rows"] - 1 - r) * (WAFFLE_CELL + WAFFLE_GAP),
                          WAFFLE_CELL, WAFFLE_CELL))
    lf = _sfont(g, g.legend_style, st.legend_size, False)
    p.setFont(lf)
    for (name, _v, f), (cx, cy, tx) in zip(w["parts"], lay.legend, strict=False):
        p.setPen(QPen(_qcolor((0, 0, 0, 255)), 0.8))
        p.setBrush(_qcolor(f))
        p.drawRect(QRectF(cx - 6, cy - 6, 12, 12))
        p.setPen(_qcolor(g.legend_style.color))
        draw_text(p, tx, cy + _metrics(lf).capHeight() / 2, name, TRACK_TEXT)
    if g.title:
        f = _sfont(g, g.title_style, st.title_size, True)
        p.setFont(f)
        p.setPen(_qcolor(g.title_style.color))
        draw_text(p, lay.title_cx - text_width(_metrics(f), g.title, TRACK_TEXT) / 2, lay.title_baseline, g.title,
                  TRACK_TEXT)


# ------------------------------------------------------------- text objects
@dataclass
class TextItem:
    """A text on the graph the user can select, move, restyle and (where
    `editable`) retype: its id (refract.render.formatting "texts"), its box in
    page points (x0, y0, x1, y1) and its text."""

    id: str
    rect: tuple[float, float, float, float]
    text: str
    editable: bool = True
    # how it is drawn (for typing over it in place): style, default size and
    # weight, baseline origin (page points) and angle (0, or -90 read bottom up)
    style: object = None
    size: float = 12.0
    bold: bool = False
    origin: tuple[float, float] = (0.0, 0.0)
    angle: float = 0.0
    placeholder: str = ""  # an empty title: the hint the canvas shows in its place (never exported)


def text_items(g: Graph, lay: Layout, st: Style = DEFAULT) -> list[TextItem]:
    """Every text object of the graph and where it is drawn (the same
    geometry as draw): titles, legend entries, significance labels, texts
    placed in Prism, text boxes added in Refract, and the tick-label groups
    (style only)."""
    if g.family == "pie":
        return []
    out: list[TextItem] = []
    if lay.horizontal:  # titles, the axis titles and the legend entries
        if g.title:
            m = _metrics(_sfont(g, g.title_style, st.title_size, True))
            w = text_width(m, g.title, TRACK_TEXT)
            out.append(TextItem("title", (lay.title_cx - w / 2, lay.title_baseline - m.ascent(), lay.title_cx + w / 2,
                                          lay.title_baseline + m.descent()), g.title, True, g.title_style,
                                st.title_size, True, (lay.title_cx - w / 2, lay.title_baseline)))
        vm = _metrics(_sfont(g, g.y_axis.title_style, st.axis_title_size, True))
        vt = g.y_axis.title
        vw = text_width(vm, vt or "Y title", TRACK_TEXT)
        out.append(TextItem("y.title", (lay.x_title_cx - vw / 2, lay.x_title_baseline - vm.ascent(),
                                        lay.x_title_cx + vw / 2, lay.x_title_baseline + vm.descent()), vt, True,
                            g.y_axis.title_style, st.axis_title_size, True, (lay.x_title_cx - vw / 2,
                                                                             lay.x_title_baseline), 0.0,
                            "" if vt else "Y title"))
        for i, (s, entry) in enumerate(zip(g.series, lay.legend, strict=False)):
            if entry is None:
                continue
            cx, cy, tx = entry
            m = _metrics(_sfont(g, g.legend_style, st.legend_size, False))
            base = cy + m.capHeight() / 2
            out.append(TextItem(f"legend.{i}", (tx, base - m.ascent(), tx + text_width(m, s.title, TRACK_TEXT),
                                                base + m.descent()), s.title, True, g.legend_style, st.legend_size,
                                False, (tx, base)))
        return out
    if g.heatmap is not None or g.waffle is not None:
        if g.title:
            m = _metrics(_sfont(g, g.title_style, st.title_size, True))
            w = text_width(m, g.title, TRACK_TEXT)
            out.append(TextItem("title", (lay.title_cx - w / 2, lay.title_baseline - m.ascent(), lay.title_cx + w / 2,
                                          lay.title_baseline + m.descent()), g.title, True, g.title_style,
                                st.title_size, True, (lay.title_cx - w / 2, lay.title_baseline)))
        return out
    left, top, right, bottom = lay.plot

    def line_box(ts, size, bold, cx, baseline, text):
        m = _metrics(_sfont(g, ts, size, bold))
        w = text_width(m, text, TRACK_TEXT)
        return (cx - w / 2, baseline - m.ascent(), cx + w / 2, baseline + m.descent())

    def centred(key, ts, size, bold, cx, baseline, text):
        r = line_box(ts, size, bold, cx, baseline, text)
        return TextItem(key, r, text, True, ts, size, bold, (r[0], baseline))

    if g.title:
        out.append(centred("title", g.title_style, st.title_size, True, lay.title_cx, lay.title_baseline, g.title))
    if g.x_axis.title:
        out.append(centred("x.title", g.x_axis.title_style, st.axis_title_size, True, lay.x_title_cx,
                           lay.x_title_baseline, g.x_axis.title))
    elif g.x_axis.title_space and g.estimation is None:  # an empty title: a place to click and type one
        it = centred("x.title", g.x_axis.title_style, st.axis_title_size, True, lay.x_title_cx, lay.x_title_baseline,
                     "X title")
        it.text, it.placeholder = "", "X title"
        out.append(it)
    if g.y_axis.title or (g.y_axis.title_space and g.estimation is None):
        m = _metrics(_sfont(g, g.y_axis.title_style, st.axis_title_size, True))
        shown = g.y_axis.title or "Y title"
        w = text_width(m, shown, TRACK_TEXT)
        x = lay.y_title_baseline_x
        out.append(TextItem("y.title", (x - m.ascent(), lay.y_title_cy - w / 2, x + m.descent(), lay.y_title_cy + w / 2),
                            g.y_axis.title, True, g.y_axis.title_style, st.axis_title_size, True,
                            (x, lay.y_title_cy + w / 2), -90.0, "" if g.y_axis.title else "Y title"))
    lm = _metrics(_sfont(g, g.y_axis.label_style, st.tick_label_size, True))
    yw = max((text_width(lm, fmt_tick(v, lay.y.tick, lay.y.log)) for v in lay.y.ticks()), default=0.0)
    out.append(TextItem("y.labels", (left - st.tick_length - st.y_label_gap - yw, top - lm.ascent() / 2,
                                     left - st.tick_length, bottom + lm.ascent() / 2), "", False))
    xm = _metrics(_sfont(g, g.x_axis.label_style, st.tick_label_size, True))
    drop = (max((text_width(xm, x) for c in g.categories for x in _lines(c)), default=0.0)
            * math.sin(math.radians(lay.label_angle))) if lay.label_angle else 0.0
    out.append(TextItem("x.labels", (left, bottom + st.tick_length, right,
                                     lay.x_label_baseline + xm.descent() + drop), "", False))
    entries = []
    for i, (s, entry) in enumerate(zip(g.series, lay.legend, strict=False)):
        if entry is None:
            continue
        cx, cy, tx = entry
        ts = s.legend_style or g.legend_style
        m = _metrics(_sfont(g, ts, st.legend_size, False))
        base = cy + m.capHeight() / 2
        out.append(TextItem(f"legend.{i}", (tx, base - m.ascent(), tx + text_width(m, s.title, TRACK_TEXT),
                                            base + m.descent()), s.title, True, ts, st.legend_size, False, (tx, base)))
        entries.append((cx - s.symbol_size / 2 - 2, base - m.ascent(), out[-1].rect[2], base + m.descent()))
    if entries:  # the legend as a whole (its symbols too): moved and styled together
        out.append(TextItem("legend", (min(e[0] for e in entries), min(e[1] for e in entries),
                                       max(e[2] for e in entries), max(e[3] for e in entries)), "", False,
                            g.legend_style, st.legend_size, False))
    for j, b in enumerate(g.significance):
        sts = b.get("style") or g.sig_style or g.legend_style
        sm = _metrics(_sfont(g, sts, st.legend_size, False))
        dx, dy = _off(g, f"sig.{j}")
        bx, by = _off(g, f"bracket.{j}")
        cx = (lay.x(b["x1"]) + b.get("dl", 0.0) + lay.x(b["x2"]) + b.get("dr", 0.0)) / 2 + dx + bx
        base = lay.y(b["y"]) - BRACKET_GAP + dy + by
        w = text_width(sm, b["label"])
        out.append(TextItem(f"sig.{j}", (cx - w / 2, base - sm.ascent(), cx + w / 2, base + sm.descent()), b["label"],
                            True, sts, st.legend_size, False, (cx - w / 2, base)))
    for k, a in enumerate(g.annotations):
        if a["kind"] != "text" or not a["text"]:
            continue
        m = _metrics(_sfont(g, a["style"], st.legend_size, False))
        _, w, h = _text_lines(m, a["text"])
        key = f"note.{a['note']}" if "note" in a else f"ann.{k}"
        out.append(TextItem(key, (left + a["cx"] - w / 2, top + a["top"], left + a["cx"] + w / 2, top + a["top"] + h),
                            a["text"], True, a["style"], st.legend_size, False,
                            (left + a["cx"] - w / 2, top + a["top"] + m.ascent())))
    return out


def text_at(items: list[TextItem], x: float, y: float, slop: float = 2.0) -> TextItem | None:
    """The text object under page point (x, y): the smallest box holding it
    (labels groups lose to the texts placed over them)."""
    hits = [t for t in items if t.rect[0] - slop <= x <= t.rect[2] + slop and t.rect[1] - slop <= y <= t.rect[3] + slop]
    return min(hits, key=lambda t: (not t.editable, (t.rect[2] - t.rect[0]) * (t.rect[3] - t.rect[1])), default=None)
