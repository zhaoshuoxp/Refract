"""Properties of a Refract graph written into a Prism graph (PLAN §2.4: a
seeded copy at level B, a graph from the file in place at level A), only
where the PCFF field is verified:

  axis range, major tick, log10      0x00A5 flags / scale + 0x8025 (E7e, E7f)
  data-set colours                   0x0852 property store, SEDObject_Array
                                     (E7i; stored in Generic RGB, refract.render.color)
  graph and axis titles, their size  text objects (refract.formats.pcff.texts; E-axes)
  tick label size                    0x8025 +38 and 0x00AD +33 (E-axes)
  category label angle 0 / 90        X 0x8025 +26: 0, 0x40, its 0x0103 copies, and
                                     for 90° 0x00AD +41 = 1 (E-axes, E-layoutfix)
  symbol shape                       0x009C +34, +109 and 0x8028 +60 (E-axes)
  symbol size                        0x009C +81, 0x8028 +62 and the f32 at
                                     0x009C +289 (-3: Prism's default) (E-pairs)
  minor ticks                        0x8025 +52 of the axis's main setting,
                                     0x00AD +29 bit 0 cleared (E-pairs)
  column bars (style "bars")         0x009C +15 bit 0x10 on the scatter plots
                                     (style 3), error bars on (E-pairs)
  SD / SEM error bars                0x8028 +12: 1 / 2; +59 = 4: none, only the
                                     mean (Prism's default column scatter)
  individual values hidden           bars (0x009C +15 bit 0x10) become plot
                                     style 1 (grouped) / 5 (column) in all
                                     seven copies, +66/+212/+224 = 0xFF, with
                                     per-set indices (+85, 0x8028 +96) (E-pairs)
  mean and error as symbols (column) plot style 7 in all seven copies, error
                                     bars on, and the fields Prism sets with
                                     it (MEANS_HEAD, MEANS_REC) (E-pairs)
  legend hidden                      every plot out of the legend (0x8028 +58
                                     bit 0x02 cleared, +113 and 0x009C +113
                                     bit 0x08 set), the entries (0x8020 type
                                     12) and their property-store entries
                                     removed, 0x8018 +4 lowered (E-pairs)
  axis lengths                       main 0x8025 +30 (1/600 in), 0x0017 +42,
                                     the plot rectangle, 0x009E +94 = 0 (E-pairs)
  donut                              0x80D6 +20 = 2 (1: pie) (E-donut)
  font                               text-run attribute 0 and 0x8025 +34: the
                                     index in misc/used_fonts.bin
                                     (refract.formats.pcff.fonts) (E-pairs)

  mean and error as symbols (grouped) plot style 7 in +133/+181/+297, the
                                     fields of Prism's own grouped graphs in it
                                     (94 corpus plots) (E-gmeans)

Everything else is reported, so the save can list what Prism will show
differently (the compatibility report)."""

from __future__ import annotations

import math
import struct

from ..render import autoscale, color, formatting
from .pcff import fields as F
from .pcff import propstore as P
from .pcff import texts as TX
from .pcff.walker import Chunk, subtree_end

COLOR_KEYS = {"fill": ("PCFF_Plot::fillcolor",),
              "color": ("PCFF_Plot::symbolcolor", "PCFF_Plot::symbolBorderColor", "PCFF_Plot::errorcolor",
                        "PCFF_Plot::BarBoxBordercolor",
                        "PCFF_Plot::connectlinecolor"),  # the line: a survival staircase (E-survival)
              # one part each (the Format panel, refract.ui.object_panel); after "color", which sets them all
              "border": ("PCFF_Plot::BarBoxBordercolor", "PCFF_Plot::symbolBorderColor"),
              "error_color": ("PCFF_Plot::errorcolor",), "line_color": ("PCFF_Plot::connectlinecolor",),
              "pattern_color": ("PCFF_Plot::patterncolor",)}  # a hatch's lines (none: ffffff00; E-elements)
COLOR_PROPS = ("fill", "color", "border", "error_color", "line_color", "pattern_color")
LABEL_FONT, LABEL_BOLD = 34, 42  # 0x8025: the tick labels' font-table index and bold flag
SET_UNWRITTEN = {"connect": "connecting line"}
# widths (E-elements: Prism's own graphs with one width changed, and their PDFs): a code in the 0x8028
# header, its copy in the 0x009C record, and the width in 1/600 inch (f32) - Prism draws from all three
# together; code 0 none, else 7 + width / 0.72 pt (8: 0.72 pt, 10: 2.16, 12: 3.6)
WIDTH_FIELDS = {"border_width": (94, 149, 265), "line_width": (92, 145, 261), "error_width": (122, 153, 269)}
# hatch patterns: 0x8028 +96 and 0x009C +85 the pattern (Prism numbers the data sets' unhatched fills 2, 3,
# 4, ...), drawn in PCFF_Plot::patterncolor (none: ffffff00) with copies at 0x8028 +80 (RGB, then 0) and
# 0x009C +221 (RGBA); codes probed one by one in Prism (E-elements)
PATTERN_CODES = {".": 1, "checker": 2, "checker_large": 3, "-": 4, "|": 5, "/": 6, "\\": 7, "+": 8, "x": 9,
                 "\\ bold": 10, "/ bold": 11, "| bold": 12, "- bold": 13, "+ bold": 14, "x bold": 15,
                 "bricks_dark": 16, "bricks": 17, "scatter": 18, "texture": 19}
PATTERN_AT, PATTERN_COLOR_AT = (96, 85), (80, 221)
SIZE_STEP = 1.58  # points of symbol diameter per size code (from_prism.plot_settings)
SIZE_DEFAULT = -3.0  # 0x009C +289 when the size is Prism's default
MINOR_AUTO = 0x01  # 0x00AD +29: Prism chooses the minor ticks
# symbol shape codes (from_prism.SHAPES): 1-5 filled, 6-10 the same with a border
SHAPE_CODES = {"none": 0, "square": 1, "triangle": 2, "triangle_down": 3, "diamond": 4, "circle": 5}
ANGLES = {0: 0x00, 90: 0x40}  # X category labels; 45 is Prism's automatic choice only
ANGLE_AUTO = 0x04  # 0x00AD +29: Prism chooses the label angle (bit 0x01: the minor ticks)
ANGLE_SET = 41  # 0x00AD +41 = 1: a 90° angle the user set (4 of 4 corpus axes at 90°, 0 of 841 others)
ERROR_KINDS = {"sd": 1, "sem": 2}  # 0x8028 +12
NO_ERROR = 4  # 0x8028 +59: the median (no error bars with SD or SEM; see PLOT_CODES)
# a plot's centre and error bars (E-compare error probe, Prism's drawing of column bars):
# 0x8028 +59 the centre (0 mean, 4 median), +12 the error bars (0 none, 1 SD, 2 SEM,
# 3 the mean's 95 % CI or the median's interquartile range, 4 the range)
CENTRE_AT, KIND_AT = 59, 12
PLOT_CODES = {"mean_sd": (0, 1), "mean_sem": (0, 2), "mean_ci": (0, 3), "mean_range": (0, 4), "mean": (0, 0),
              "median": (4, 0), "median_iqr": (4, 3), "median_range": (4, 4)}
NOT_ERROR_PLOTS = ("box", "violin", "before_after", "dots")  # their plot choices are not error bars
BAR = 0x10  # 0x009C +15: a bar under the plot's points (style 3)
SCATTER = 3  # 0x009C +133: scatter (the points, with the mean)
STYLE_COPIES = (67, 129, 133, 177, 181, 293, 297)  # 0x009C: the plot style and its copies
BARS_ONLY = {"grouped": 1, "column": 5}  # the style of bars without the points
MEANS = 7  # 0x009C +133: mean and error as a symbol (column)
BOX, BEFORE_AFTER = 4, 8  # 0x009C +133: box and whiskers; a line to the next data set (bundled samples)
VIOLIN = 11  # 0x009C +133: violin (style probe E-compare: column and grouped)
# the styles written by setting the style code alone (E-compare probe: Prism draws each
# from the data; grouped: in its three copies, with the grouped base code 1 at +67)
CODE_STYLES = {"column": {"box": BOX, "before_after": BEFORE_AFTER, "violin": VIOLIN},
               "grouped": {"scatter": SCATTER, "box": BOX, "violin": VIOLIN, "dots": BEFORE_AFTER}}
# 0x009C +8 = 1: a line joins the plot's points (before-after; connected means). On a grouped
# style-8 plot it joins each row's values to the next data set's (E-compare probe), not the
# replicates across rows (grp_rep_lines), so that type is not written.
CONNECT = 8
WHISKERS_AT = 125  # 0x009C +125: box whiskers (E-compare whisker probe; from_prism.WHISKERS)
WHISKERS = {"min_max": 0, "tukey": 1, "p10_90": 2, "p5_95": 3, "min_max_points": 6}  # 6: the asterisks sample
XY_LINES = ("points_line", "line", "area")  # XY plots joined by a line; without symbols; the area below filled
XY_AREA = 8  # 0x8028 +59 on an XY plot: the area below its line filled (E-compare probe 11)
PLOT_CHOICES = frozenset(PLOT_CODES) | frozenset(WHISKERS)  # plot choices written as they are
HORIZONTAL = 0x80  # 0x0013 +29: a horizontal graph (7 of 7 bundled sample graphs, 0 of 96 others)
MEANS_HEAD = {94: 0, 110: 4, 122: 9, 126: 7}  # 0x8028 fields Prism sets with it (no border, ...)
MEANS_REC = {149: 0, 153: 9}  # 0x009C, with f32 +265 = 0 and +269 = 12
# grouped means (94 corpus plots of Prism's own grouped graphs in this style): the style
# in three copies only, the bar flag off, 0x8028 +110 = 3, shapes in Prism's cycle
GROUPED_MEANS_COPIES = (133, 181, 297)
MEANS_SHAPES = (5, 1, 2, 3, 4, 10)
# 0x80D6 +20 (from_prism.PIE_PIE / PIE_DONUT; 3, 4: Prism's stacked bar on its side and upright, E-types)
PIE_CHARTS = {"default": 1, "donut": 2, "stacked_h": 3, "stacked": 4}
IN_LEGEND = 0x02  # 0x8028 +58: the data set has a legend entry
NOT_IN_LEGEND = 0x08  # 0x8028 +113 and 0x009C +113: Prism does not add it to the legend


def _axis(ch: list[Chunk], which: int, fmt: dict, resolved: tuple[float, float, float], numeric: bool) -> None:
    """which: 0 = X, 1 = Y. resolved: the (lo, hi, tick) Refract draws."""
    if not numeric or not any(k in fmt for k in ("min", "max", "tick", "log")):
        return
    modes, sets = F.axis_modes(ch), F.axis_settings(ch)
    if len(modes) <= which or len(sets) <= 3 * which:
        raise ValueError("the seed has no such axis")
    m = F.AxisMode.read(modes[which])
    s = F.AxisSettings.read(sets[3 * which])
    lo, hi, tick = resolved
    log = bool(fmt.get("log"))
    if log:
        m.scale, m.scale2 = F.AxisMode.LOG10, 1
        m.flags |= F.AxisMode.MANUAL_RANGE
        s.log10, s.min, s.max, s.major_tick = 1, math.log10(lo), math.log10(hi), 1.0
    else:
        m.scale = m.scale2 = 0
        s.log10 = 0
        if "min" in fmt or "max" in fmt:
            m.flags |= F.AxisMode.MANUAL_RANGE
            s.min, s.max = lo, hi
        if "tick" in fmt:
            m.flags |= F.AxisMode.MANUAL_TICK
            s.major_tick = tick
    m.write(modes[which])
    s.write(sets[3 * which])


def write_ranges(ch: list[Chunk], family: str, extent, resolved_x, resolved_y, horizontal: bool = False) -> None:
    """The drawn range and tick of the numeric axes (main 0x8025 setting) and
    the data extent and drawn range cached in 0x0017, as Prism would compute
    them (refract.render.autoscale), and the minor ticks Prism would add
    (autoscale.auto_minor), without making them manual. A graph
    built from a skeleton (refract.formats.pcff.skeleton) carries the
    defaults' caches, and Prism does not always refresh them on open (level
    C check: a formatted XY graph kept the seed's 0..6 / 0..40)."""
    sets, axes = F.axis_settings(ch), F.axes(ch)
    x0, x1, y0, y1 = extent
    pairs = ((0, resolved_y, (y0, y1)),) if horizontal else ((0, resolved_x, (x0, x1)), (1, resolved_y, (y0, y1)))
    for which, (lo, hi, tick), (dmin, dmax) in pairs:  # horizontal: the values are on the stored X axis
        if which == 0 and family not in ("xy", "survival") and not horizontal:
            continue
        if len(sets) <= 3 * which or len(axes) <= which:
            continue
        s = F.AxisSettings.read(sets[3 * which])
        if s.log10:
            continue
        s.min, s.max, s.major_tick = lo, hi, tick
        s.write(sets[3 * which])
        p = bytearray(sets[3 * which].payload)  # +52: the minor ticks Prism chooses (stays automatic)
        p[52] = autoscale.auto_minor(lo, hi, tick, s.length * 72 / 600)
        sets[3 * which].payload = bytes(p)
        a = F.Axis.read(axes[which])
        if horizontal and lo <= 0.0 <= hi:  # Prism autoscales a horizontal graph's value axis from the cached
            dmin, dmax = min(dmin, 0.0), max(dmax, 0.0)  # extent, without the baseline (bars of 4.3..7: 4..8)
        a.data_min, a.data_max, a.draw_min, a.draw_max = dmin, dmax, lo, hi
        a.write(axes[which])


def _title(ch: list[Chunk], tid: int | None, f: dict, what: str, notes: list[str]) -> None:
    """Text and size of a title (f: its "title" / "title_size" keys)."""
    if "title" not in f and "title_size" not in f:
        return
    if tid is None or TX.index(ch, tid) is None:
        notes.append(f"{what} (the seed has no such text)")
        return
    if "title" in f:
        text = str(f["title"])
        if not TX.encodable(text):
            notes.append(f"{what}: characters outside Windows-1252 (shown as ?)")
        TX.set_text(ch, tid, text)
    if formatting._num(f.get("title_size")):
        TX.set_size(ch, tid, float(f["title_size"]))


def _labels(ch: list[Chunk], which: int, f: dict, axis: str, notes: list[str]) -> None:
    """Tick / category labels of an axis: size (each of its three 0x8025
    settings and the 0x00AD after it) and, on X, the angle."""
    if not formatting._num(f.get("label_size")) and "angle" not in f:
        return
    idx = [i for i, c in enumerate(ch) if c.tag == F.TAG_AXIS_SETTINGS and c.payload and len(c.payload) > 46]
    mine = idx[3 * which:3 * which + 3]
    if not mine:
        notes.append(f"{axis} axis labels (the seed has no such axis)")
        return
    size = formatting._num(f.get("label_size"))
    angle = f.get("angle")
    if angle is not None and (which != 0 or round(float(angle)) not in ANGLES):
        notes.append(f"{axis} axis label angle {angle:g}°" if isinstance(angle, (int, float)) else f"{axis} axis label angle")
        angle = None
    for n, i in enumerate(mine):
        p = bytearray(ch[i].payload)
        end = idx[3 * which + n + 1] if 3 * which + n + 1 < len(idx) else len(ch)
        sub = ch[i + 1:end]  # this setting's own chunks, up to the next 0x8025
        if size:  # Prism reads the size from the 0x00AD (it restored +38 from it, E-axes)
            struct.pack_into("<H", p, 38, round(size))
            for ad in (c for c in sub if c.tag == 0x00AD and c.payload and len(c.payload) >= 37):
                q = bytearray(ad.payload)
                struct.pack_into("<f", q, 33, size)
                ad.payload = bytes(q)
        if angle is not None:  # +26, and its copy in each 0x0103 entry (u32 count, 8-byte entries)
            code = ANGLES[round(float(angle))]
            p[26] = code
            for ad in (c for c in sub if c.tag == 0x00AD and c.payload and len(c.payload) > ANGLE_SET):
                q = bytearray(ad.payload)  # the angle no longer automatic, and 90° marked as set
                q[29] &= ~ANGLE_AUTO & 0xFF
                q[ANGLE_SET] = 1 if code == ANGLES[90] else 0
                ad.payload = bytes(q)
            for c in (c for c in sub if c.tag == 0x0103 and c.payload and len(c.payload) >= 4):
                q = bytearray(c.payload)
                for k in range(struct.unpack_from("<I", q, 0)[0]):
                    if 8 + 8 * k < len(q):
                        q[8 + 8 * k] = code
                c.payload = bytes(q)
        ch[i].payload = bytes(p)


def _minor(ch: list[Chunk], which: int, f: dict, axis: str, notes: list[str]) -> None:
    """Minor intervals per major tick: the axis's main 0x8025 +52, and the
    0x00AD after it no longer automatic (E-pairs: Prism made exactly this
    change for "minor ticks" on a default XY graph)."""
    n = formatting._num(f.get("minor"))
    if n is None:
        return
    idx = [i for i, c in enumerate(ch) if c.tag == F.TAG_AXIS_SETTINGS and c.payload and len(c.payload) > 52]
    if len(idx) <= 3 * which:
        notes.append(f"{axis} axis minor ticks (the seed has no such axis)")
        return
    i = idx[3 * which]
    end = idx[3 * which + 1] if 3 * which + 1 < len(idx) else len(ch)
    p = bytearray(ch[i].payload)
    p[52] = max(0, min(255, int(n)))
    ch[i].payload = bytes(p)
    for ad in (c for c in ch[i + 1:end] if c.tag == 0x00AD and c.payload and len(c.payload) > 29):
        q = bytearray(ad.payload)
        q[29] &= ~MINOR_AUTO & 0xFF
        ad.payload = bytes(q)


def _lengths(ch: list[Chunk], fmt: dict, notes: list[str]) -> None:
    """Axis lengths in inches (E-pairs): the axis's main 0x8025 +30 (1/600
    in), its 0x0017 cache +42 and the plot rectangle (0x0013 +0, x0 y0 x1 y1
    in 1/600 in), with 0x009E +94 cleared as Prism clears it (with it set,
    Prism keeps the graph's proportions and scales everything, E-misc)."""
    todo = [(which, formatting._num(fmt.get(key))) for which, key in ((0, "width"), (1, "height"))]
    todo = [(w, v) for w, v in todo if v]
    if not todo:
        return
    sets = [c for c in ch if c.tag == F.TAG_AXIS_SETTINGS and c.payload and len(c.payload) > 34]
    axes = [c for c in ch if c.tag == F.TAG_AXIS and c.payload and len(c.payload) >= 44]
    head = next((c for c in ch if c.tag == 0x0013 and c.payload and len(c.payload) >= 8), None)
    if len(sets) < 4 or len(axes) < 2 or head is None:
        notes.append("axis lengths (the seed has no such axes)")
        return
    rect = list(struct.unpack_from("<4h", head.payload, 0))
    for which, inches in todo:
        n = max(60, min(12000, round(inches * 600)))
        c = sets[3 * which]
        p = bytearray(c.payload)
        struct.pack_into("<I", p, 30, n)
        c.payload = bytes(p)
        a = bytearray(axes[which].payload)
        struct.pack_into("<H", a, 42, n)
        axes[which].payload = bytes(a)
        if which == 0:
            rect[2] = rect[0] + n
        else:
            rect[1] = rect[3] - n  # the X axis stays where it is
    h = bytearray(head.payload)
    struct.pack_into("<4h", h, 0, *rect)
    head.payload = bytes(h)
    for c in (c for c in ch if c.tag == 0x009E and c.payload and len(c.payload) > 95):
        q = bytearray(c.payload)
        q[94] = 0
        c.payload = bytes(q)


def _font(ch: list[Chunk], name: str, fonts) -> None:
    """Every text and every axis's tick labels in this font, bold where they
    were bold (E-pairs: Prism's own font change). fonts(name, bold) -> the
    document font-table index."""
    TX.set_fonts(ch, lambda bold: fonts(name, bold))
    for c in (c for c in ch if c.tag == F.TAG_AXIS_SETTINGS and c.payload and len(c.payload) > LABEL_BOLD):
        p = bytearray(c.payload)
        struct.pack_into("<H", p, LABEL_FONT, fonts(name, p[LABEL_BOLD] == 1))
        c.payload = bytes(p)


def _legend(ch: list[Chunk], shown: bool, notes: list[str]) -> None:
    """Hidden, as Prism hides it (E-pairs): every plot out of the legend and
    kept out (0x8028 +58 bit 0x02 cleared, +113 and 0x009C +113 bit 0x08
    set), the legend entries (0x8020 type 12) removed with their property-
    store entries (SEDObject_Array: one per graph object, in order), and the
    object count 0x8018 +4 lowered."""
    objects = [i for i, c in enumerate(ch) if c.tag == 0x8020 and c.payload]
    entries = [i for i in objects if ch[i].payload[:2] == b"\x0c\x00"]
    if shown:
        if not entries:
            notes.append("legend (the seed has none)")
        return
    for head, rec in plot_records(ch):
        if head is not None and head.payload and len(head.payload) > 113 and len(rec.payload) > 113:
            h, r = bytearray(head.payload), bytearray(rec.payload)
            h[58] &= ~IN_LEGEND & 0xFF
            h[113] |= NOT_IN_LEGEND
            r[113] |= NOT_IN_LEGEND
            head.payload, rec.payload = bytes(h), bytes(r)
    store = next((c for c in ch if c.tag == P.TAG and c.payload), None)
    if store is not None and entries:
        v, _raw, tail = P.decode_payload(store.payload)
        arr = v.get("SEDObject_Array") if isinstance(v, P.Dict) else None
        if arr is not None and len(arr.items) == len(objects):
            gone = {objects.index(i) for i in entries}
            arr.items = [it for k, it in enumerate(arr.items) if k not in gone]
            store.payload = P.encode_payload(v, 6, tail)
    for i in reversed(entries):
        del ch[i:subtree_end(ch, i)]
    count = next((c for c in ch if c.tag == 0x8018 and c.payload and len(c.payload) >= 8), None)
    if count is not None and entries:
        q = bytearray(count.payload)
        struct.pack_into("<I", q, 4, max(0, struct.unpack_from("<I", q, 4)[0] - len(entries)))
        count.payload = bytes(q)


def plot_records(ch: list[Chunk]) -> list[tuple[Chunk | None, Chunk]]:
    """(0x8028 header, 0x009C record) of each data-set plot object (0x8020
    type 9), in stream order."""
    out = []
    for k, c in enumerate(ch):
        if c.tag != 0x8020 or not c.payload or c.payload[:2] != b"\x09\x00":
            continue
        head = None
        for x in ch[k + 1:k + 8]:
            if x.tag == 0x8028:
                head = x
            elif x.tag == 0x009C and x.payload and len(x.payload) > 140:
                out.append((head, x))
                break
    return out


def _symbols(ch: list[Chunk], sets: dict, n_plots: int, reverse: bool, notes: list[str]) -> None:
    """Shape and size of each data set's symbols."""
    recs = plot_records(ch)
    n = min(n_plots, len(recs))
    for key, f in sets.items():
        i = int(key)
        shape = f.get("symbol") in SHAPE_CODES
        size = formatting._num(f.get("size"))
        if not shape and not size:
            continue
        if i >= n:
            what = " and ".join(w for w, on in (("symbol shape", shape), ("symbol size", size)) if on)
            notes.append(f"data set {i + 1}: {what} (Prism gives it its default)")
            continue
        head, rec = recs[n - 1 - i if reverse else i]
        r = bytearray(rec.payload)
        h = bytearray(head.payload) if head is not None and head.payload and len(head.payload) > 62 else None
        if shape:
            base = SHAPE_CODES[f["symbol"]]
            code = base + 5 if base and r[34] in range(6, 11) else base  # keep the seed's border
            r[34] = r[109] = code
            if h is not None:
                h[60] = code
        if size:  # the code, its copy in the header, and +289: the size as set (else Prism's default)
            code = max(1, min(40, round(size / SIZE_STEP)))
            r[81] = code
            if len(r) >= 293:
                struct.pack_into("<f", r, 289, float(code))
            if h is not None:
                h[62] = code
        rec.payload = bytes(r)
        if h is not None:
            head.payload = bytes(h)


def _box_form(r: bytearray, h: bytearray, family: str, style: str) -> None:
    """A box or violin plot in the form Prism saves it (E-compare: Prism's
    re-save of Refract's own): the style at +67 (the plot's own kind) with
    the box code in the drawing copies, violins marked 11 at +67, +293/+297
    and 0x8028 +126; the values hidden (+66 = FF; a box shows them through
    its whisker mode); grouped plots flag +15 = 4."""
    if style == "violin":
        for o in (129, 133, 177, 181) if family == "column" else (133, 181):
            r[o] = BOX
        for o in (67, 293, 297) if family == "column" else (67, 297):
            r[o] = VIOLIN
        h[126], h[110] = VIOLIN, 3 if family == "column" else h[110]
    else:
        r[67] = BOX
        if family == "column":
            h[126] = BOX
    r[66] = 0xFF
    if family == "grouped":
        r[15] = 0x04


GROUPED_SIDE = 2  # 0x009C base-style copies (+67 too for symbols) and 0x8028 +126 of a horizontal grouped plot
SIDE_CODES = (129, 177, 293)  # the base copies; 133, 181, 297 hold the plot's own style (E-types round 2)


def on_side(ch: list[Chunk], style: str) -> None:
    """A horizontal grouped plot of another style written on Prism's own
    horizontal bars (means) or box plot (violin, floating bars) - as Prism
    stores the upright ones, with its horizontal base code 2 where they have
    1 (E-types round 2: the style copies of Prism's horizontal bars and box)."""
    for i, (head, rec) in enumerate(plot_records(ch)):
        if head is None or not head.payload or len(head.payload) <= 126 or len(rec.payload) < 298:
            continue
        r, h = bytearray(rec.payload), bytearray(head.payload)
        if style in ("means", "means_line"):
            for o in GROUPED_MEANS_COPIES:
                r[o] = MEANS
            r[67] = GROUPED_SIDE
            r[15], r[66] = 0, 0
            h[59], h[110] = 0, 3
            code = MEANS_SHAPES[i % len(MEANS_SHAPES)]
            r[34] = r[109] = h[60] = code
            if style == "means_line":
                r[CONNECT] = 1
                r[4:8] = b"\xff\xff\xff\xff"
        elif style == "violin":
            r[67] = r[297] = VIOLIN
        elif style == "floating":
            r[24:28] = r[105:109] = r[125:129] = b"\xff\xff\xff\xff"
        rec.payload, head.payload = bytes(r), bytes(h)


def _plot_style(ch: list[Chunk], family: str, style: str, error: str, sets: dict, n_plots: int,
                reverse: bool, notes: list[str]) -> None:
    """Refract's plot style and error bars, and individual values hidden,
    written as Prism wrote them in its own graphs (E-pairs: bars and points
    / bars only / scatter with SEM / grouped bars only)."""
    recs = plot_records(ch)
    n = min(n_plots, len(recs))
    connect = style == "means_line"
    if connect:
        style = "means"
    if style == "bars_only":  # bars without the values: the bars style, every data set's points hidden
        style = "bars" if family == "column" else "default"
        sets = {str(i): {**(sets.get(str(i)) or {}), "points": False} for i in range(n)}
    if family == "pie":  # the chart kind is in the pie data, 0x80D6 +20 (E-donut)
        for c in (c for c in ch if c.tag == 0x80D6 and c.payload and len(c.payload) >= 24):
            q = bytearray(c.payload)
            struct.pack_into("<I", q, 20, PIE_CHARTS.get(style, PIE_CHARTS["default"]))
            c.payload = bytes(q)
        return
    if style == "means" and family not in ("column", "grouped"):
        notes.append("style (mean and error as symbols): Prism shows its default style")
    for i in range(n):
        head, rec = recs[n - 1 - i if reverse else i]
        if head is None or not head.payload or len(head.payload) <= 96 or len(rec.payload) < 298:
            continue
        r, h = bytearray(rec.payload), bytearray(head.payload)
        if style == "bars" and family == "column" and r[133] == SCATTER:
            r[15] |= BAR
            h[59] = 0  # with error bars
        elif style == "means" and family == "column" and r[133] == SCATTER:
            for o in STYLE_COPIES:
                r[o] = MEANS
            r[15] = 0
            h[59] = 0  # with error bars
            for o, v in MEANS_HEAD.items():
                h[o] = v
            for o, v in MEANS_REC.items():
                r[o] = v
            struct.pack_into("<2f", r, 265, 0.0, 12.0)
        elif style in CODE_STYLES.get(family, {}) and r[133] == SCATTER:
            code = CODE_STYLES[family][style]
            for o in (STYLE_COPIES if family == "column" else GROUPED_MEANS_COPIES):
                r[o] = code
            if family == "grouped":
                r[67] = 1
            r[15] = 0
            if style in ("box", "violin"):  # as Prism stores them when it saves (E-compare re-save)
                _box_form(r, h, family, style)
            if style == "box":
                r[WHISKERS_AT] = WHISKERS.get(error, 0)
            if style == "before_after":  # the lines on, as Prism's own before-after graphs (bundled sample)
                r[CONNECT] = 1
                r[4:8] = b"\xff\xff\xff\xff"
        elif family == "xy" and style in XY_LINES:  # E-compare probes 9 and 11
            r[CONNECT] = 1
            r[4:8] = b"\xff\xff\xff\xff"
            if style == "line":
                r[34] = r[109] = h[60] = 0  # no symbols
            if style == "area":
                h[CENTRE_AT] = XY_AREA
        elif style == "means" and family == "grouped" and r[133] == SCATTER:
            for o in GROUPED_MEANS_COPIES:  # the other copies hold the grouped base style (1)
                r[o] = MEANS
            r[67] = 1
            r[15] = 0
            h[59] = 0
            h[110] = 3
            code = MEANS_SHAPES[i % len(MEANS_SHAPES)]  # Prism's symbol cycle (build.SYMBOLS)
            r[34] = r[109] = h[60] = code
        if connect and r[133] == MEANS:  # connected means (E-compare probe)
            r[CONNECT] = 1
            r[4:8] = b"\xff\xff\xff\xff"
        if error in PLOT_CODES and family in ("column", "grouped") and style not in NOT_ERROR_PLOTS:
            h[CENTRE_AT], h[KIND_AT] = PLOT_CODES[error]
        elif h[59] != NO_ERROR and error in ERROR_KINDS:
            h[12] = ERROR_KINDS[error]
        f = sets.get(str(i)) or {}
        if f.get("points") is False and family in BARS_ONLY and style != "means":  # means: no points
            if r[133] == SCATTER and r[15] & BAR:
                code = BARS_ONLY[family]
                for o in STYLE_COPIES:
                    r[o] = code
                r[15] = 0
                r[66] = r[212] = r[224] = 0xFF
                r[85] = h[96] = 2 + i  # per-set indices, as Prism numbers them
                h[110] = 5
                if family == "column":
                    h[126] = 5
            else:
                notes.append(f"data set {i + 1}: individual values hidden (only over bars)")
        elif f.get("points") is True and r[66] == 0xFF:
            notes.append(f"data set {i + 1}: individual values shown")
        rec.payload, head.payload = bytes(r), bytes(h)


def _colors(ch: list[Chunk], sets: dict, n_plots: int, reverse: bool, notes: list[str]) -> None:
    store = next((c for c in ch if c.tag == P.TAG and c.payload), None)
    if store is None:
        if sets:
            notes.append("data-set colours (the seed has no colour store)")
        return
    v, _raw, tail = P.decode_payload(store.payload)
    arr = v.get("SEDObject_Array") if isinstance(v, P.Dict) else None
    # the array holds every graph object; data-set plots are the ones with an XYPlot_Map
    plots = [it for it in (arr.items if arr is not None else [])
             if isinstance(it, P.Dict) and isinstance(it.get("XYPlot_Map"), P.Dict)]
    n_plots = min(n_plots, len(plots))
    changed = False
    for key, f in sets.items():
        i = int(key)
        for prop in COLOR_PROPS:
            if prop not in f:
                continue
            if i >= n_plots or arr is None:
                notes.append(f"data set {i + 1}: {prop} colour (Prism gives it a default colour)")
                continue
            pm = plots[n_plots - 1 - i if reverse else i].get("XYPlot_Map")
            rgba = color.from_srgb(formatting.rgba(f[prop]))
            hit = False
            for name in COLOR_KEYS[prop]:
                sc = pm.get(name) if isinstance(pm, P.Dict) else None
                if isinstance(sc, P.Scalar) and len(sc.raw) == 4:
                    sc.raw = bytes(rgba)
                    hit = changed = True
            if not hit:
                notes.append(f"data set {i + 1}: {prop} colour (no such colour in the seed)")
    if changed:
        store.payload = P.encode_payload(v, 6, tail)


def _width_code(w: float) -> int:
    return 0 if w <= 0 else max(8, min(255, round(w / 0.72) + 7))


def _parts(ch: list[Chunk], sets: dict, n_plots: int, reverse: bool, notes: list[str]) -> None:
    """Each data set's border, line and error-bar widths and its hatch pattern."""
    recs = plot_records(ch)
    n = min(n_plots, len(recs))
    for key, f in sets.items():
        i = int(key)
        widths = {k: formatting._num(f.get(k)) for k in WIDTH_FIELDS if formatting._num(f.get(k)) is not None}
        if not widths and "pattern" not in f:
            continue
        if i >= n:
            notes.append(f"data set {i + 1}: widths and pattern (Prism gives it its default)")
            continue
        head, rec = recs[n - 1 - i if reverse else i]
        if head is None or not head.payload or len(head.payload) <= 126 or len(rec.payload) < 273:
            notes.append(f"data set {i + 1}: widths and pattern (not in this seed)")
            continue
        h, r = bytearray(head.payload), bytearray(rec.payload)
        for k, w in widths.items():
            ha, ra, fa = WIDTH_FIELDS[k]
            code = _width_code(w)
            h[ha] = r[ra] = code
            struct.pack_into("<f", r, fa, (code - 7) * 6.0 if code else 0.0)
        if "pattern" in f:
            code = PATTERN_CODES.get(f["pattern"])
            if code is None:  # none: the unhatched fill, as Prism numbers it, and no pattern colour
                h[PATTERN_AT[0]] = r[PATTERN_AT[1]] = 2 + (n - 1 - i if reverse else i)
                h[80:84], r[221:225] = b"\xff\xff\xff\xff", b"\xff\xff\xff\x00"
                _store_color(ch, i, n_plots, reverse, "PCFF_Plot::patterncolor", b"\xff\xff\xff\x00")
            else:
                h[PATTERN_AT[0]] = r[PATTERN_AT[1]] = code
                rgb = bytes(color.from_srgb(formatting.rgba(f.get("pattern_color") or "#000000"))[:3])
                h[80:84], r[221:225] = rgb + b"\x00", rgb + b"\xff"
        head.payload, rec.payload = bytes(h), bytes(r)


def _store_color(ch: list[Chunk], i: int, n_plots: int, reverse: bool, name: str, raw: bytes) -> None:
    store = next((c for c in ch if c.tag == P.TAG and c.payload), None)
    if store is None:
        return
    v, _raw, tail = P.decode_payload(store.payload)
    arr = v.get("SEDObject_Array") if isinstance(v, P.Dict) else None
    plots = [it for it in (arr.items if arr is not None else [])
             if isinstance(it, P.Dict) and isinstance(it.get("XYPlot_Map"), P.Dict)]
    n = min(n_plots, len(plots))
    if i >= n:
        return
    sc = plots[n - 1 - i if reverse else i].get("XYPlot_Map").get(name)
    if isinstance(sc, P.Scalar) and len(sc.raw) == 4:
        sc.raw = raw
        store.payload = P.encode_payload(v, 6, tail)


HEAT_DIMS = 68  # 0x80F4 +68 rows, +72 columns of a heat map (E-heat: Prism fills in the values and colours)
HEAT_ROWS, HEAT_RECORDS, HEAT_RECORD = 40, 64, 20  # 0x80F6 (a column): +40 its rows, then a record per row


def fit_heat(ch: list[Chunk], rows: int, cols: int) -> None:
    """A heat map's caches sized for a table of `rows` x `cols` cells: the
    counts, and each column's per-row records (valid flag, colour, value,
    row) blank - Prism computes the values and colours when it draws."""
    for c in ch:
        if c.tag == 0x80F4 and c.payload and len(c.payload) >= HEAT_DIMS + 8:
            q = bytearray(c.payload)
            struct.pack_into("<2I", q, HEAT_DIMS, rows, cols)
            c.payload = bytes(q)
        elif c.tag == 0x80F6 and c.payload and len(c.payload) >= HEAT_RECORDS:
            q = bytearray(c.payload[:HEAT_RECORDS])
            struct.pack_into("<I", q, HEAT_ROWS, rows)
            for r in range(rows):
                q += struct.pack("<I4sdI", 1, b"\x00\x00\x00\xff", 0.0, r)
            c.payload = bytes(q)


def set_horizontal(ch: list[Chunk], on: bool) -> None:
    """The graph turned on its side (0x0013 +29 bit 0x80), or upright."""
    for c in ch:
        if c.tag == F.TAG_GRAPH_KIND and c.payload and len(c.payload) > 29:
            q = bytearray(c.payload)
            q[29] = (q[29] | HORIZONTAL) if on else (q[29] & ~HORIZONTAL & 0xFF)
            c.payload = bytes(q)
            return


def apply(ch: list[Chunk], fmt: dict, family: str, n_plots: int, resolved_x, resolved_y,
          style: str = "default", error: str | None = None, fonts=None, measure=None) -> list[str]:
    """Write what can be written; returns what could not (for the report).
    style / error: a Refract graph's own options (level B); None / "default"
    leave the graph's. fonts(name, bold): the document's font-table index
    (refract.formats.pcff.fonts.index on the bundle being written).
    measure(note) -> (width, height) pt of a text box (refract.render.qt):
    text boxes are written as Prism's own when given."""
    notes: list[str] = []
    fmt = fmt or {}
    if fmt.get("font"):
        if fonts is None:
            notes.append("font")
        else:
            _font(ch, str(fmt["font"]), fonts)
    _title(ch, TX.graph_title_id(ch), fmt, "graph title", notes)
    for axis, which, resolved in (("x", 0, resolved_x), ("y", 1, resolved_y)):
        f = fmt.get(axis) or {}
        _title(ch, TX.axis_title_id(ch, which), f, f"{axis.upper()} axis title", notes)
        _labels(ch, which, f, axis.upper(), notes)
        if axis == "y" or family in ("xy", "survival"):
            _minor(ch, which, f, axis.upper(), notes)
        elif "minor" in f:
            notes.append(f"{axis.upper()} axis minor ticks (a category axis)")
        numeric = axis == "y" or family in ("xy", "survival")
        try:
            _axis(ch, which, f, resolved, numeric)
        except ValueError as e:
            notes.append(f"{axis.upper()} axis range ({e})")
    sets = fmt.get("sets") or {}
    for key, f in sets.items():
        for k, label in SET_UNWRITTEN.items():
            if k in (f or {}):
                notes.append(f"data set {int(key) + 1}: {label}")
    reverse = family in ("xy", "survival")
    _plot_style(ch, family, style, error, sets, n_plots, reverse, notes)
    _symbols(ch, {k: v for k, v in sets.items() if v}, n_plots, reverse, notes)
    hatched = {}
    for k, v in sets.items():  # a hatch is drawn in its colour (black unless set); none: no colour
        if v:
            v = dict(v)
            if v.get("pattern"):
                v.setdefault("pattern_color", "#000000")
            elif "pattern" in v:
                v.pop("pattern_color", None)
            hatched[k] = v
    _colors(ch, {k: v for k, v in hatched.items() if any(p in v for p in COLOR_PROPS)}, n_plots, reverse, notes)
    _parts(ch, hatched, n_plots, reverse, notes)
    _lengths(ch, fmt, notes)
    # formatting made on the canvas or by the colour menu that Prism's graph does not take yet
    texts = fmt.get("texts") or {}
    if any(k in v for v in texts.values() if isinstance(v, dict) for k in ("dx", "dy")):
        notes.append("texts moved on the graph")
    if any(k in v for v in texts.values() if isinstance(v, dict) for k in ("bold", "italic", "underline", "color",
                                                                          "family", "text")):
        notes.append("text styles changed on the graph")
    if any(isinstance(v, dict) and v.get("bars") for v in (fmt.get("sets") or {}).values()):
        notes.append("single bars formatted on their own (Prism shows the data set's format)")
    if any(k.startswith("abr.") for k in (fmt.get("texts") or {})):
        notes.append("brackets placed in Prism moved, stretched or hidden")
    from ..render.shape_kinds import for_prism

    # every kind drawn in Refract as Prism's lines, arrows, boxes and ellipses; texts of lines with text as text boxes
    drawn, labels = for_prism([s for s in fmt.get("shapes") or [] if s], measure)
    boxes = [n for n in fmt.get("notes") or [] if n and str(n.get("text", "")).strip()] + labels
    if drawn or boxes:  # as Prism's own graph objects (refract.formats.graph_objects)
        from . import graph_objects as GO

        try:
            ch[:] = GO.add(ch, drawn, boxes, measure)
        except (ValueError, KeyError, OSError):
            if drawn:
                notes.append("lines, arrows, boxes and ellipses drawn in Refract")
            if boxes:
                notes.append("text boxes added in Refract")
        else:
            if boxes and measure is None:
                notes.append("text boxes added in Refract")
            if any(s.get("dash") for s in drawn):
                notes.append("dashed drawn lines (Prism draws them solid)")
            if any(k in n for n in boxes for k in formatting.STYLE_KEYS):
                notes.append("text boxes' fonts and styles (Prism uses its default)")
    if any(k in v for key, v in texts.items() if key.startswith("bracket.") and isinstance(v, dict)
           for k in ("color", "width", "dx", "dy")):
        notes.append("significance brackets moved or restyled")
    if any(fmt.get(k) for k in ("background", "plot_fill", "axis_color")):
        notes.append("background, plotting area or axis colours")
    if fmt.get("page"):
        notes.append("the graph's place on its page")
    if "legend" in fmt:  # last: it removes objects
        _legend(ch, bool(fmt["legend"]), notes)
    return notes
