"""Prism's automatic axis range and major tick (linear axes).

Verified with controlled data variants that Prism re-saved
(tools/autoscale_probe.py; docs/format/findings.md, phase 3 batch 1).

style "bar" (bars; 30 of 30 variants):
1. the extent is that of everything plotted (bar tops and error bars, as
   Prism caches it in PCFF 0x0017);
2. head-room: the top is raised by 5 % of the data span (max - min, before
   0 is added) when it is above 0; the bottom gets none;
3. 0 is added to the range;
4. the major tick is the smallest 1-2-5 value >= range / 5;
5. the ends are rounded outwards to whole ticks.

style "xy" (XY graphs, both axes; 278 of 278 axes: 100 variants with random
X and Y, E-xyscale, and the 40 dose-response variants):
1. the axis starts at 0 when the data are on one side of 0 and min/max <
   0.53 (|max|/|min| for negative data; on the X axis negative data start
   at 0 only below 0.27 - the variants put it between 0.22 and 0.32);
2. margins of 5 % of the span on each free end, the span measured after 0
   is added (3.18e3..7.63e3 -> 0..1e4); when the data cross 0, each end
   moves out by 5 % of its own distance from 0 (-9.4..35.1 -> -10..40,
   -489..477 -> -1000..1000);
3. ticks and rounding as for bars.
The variants fix the top margin at 5.0 %, the bottom at 4.9-5.3 % and the
ratio at 0.52-0.54 (Y negative: 0.53-0.57). Checked on 80 further axes
(another 40 variants) that the rule was not fitted to.

style "column" (column scatter; 40 of 40 variants, E-colscale): like "xy"
with margins of 5.05 % (top) and 4 % (bottom) of the data span, 0 added when
min/max < 0.56, and no bottom margin when the data cross 0. The variants fix
the top margin at 4.2-5.1 %, the bottom at 3-5 % and the threshold between
0.516 and 0.573; Refract's sample column (3.8..7.8, which Prism draws 0..10)
needs a top margin above 5 %.

style "colbar" (column bars, with or without the points; 24 of 24 variants,
E-pairs): like "bar" with the column margins - 5.05 % on top, and 4 % below
when the data go below 0.
"""

from __future__ import annotations

import math

HEADROOM = 0.05  # bars: top, fraction of the data span
XY_MARGIN = 0.05  # xy: fraction of the span (after 0 is added), or of each end's distance from 0
ZERO_RATIO = 0.53  # xy: start at 0 when min/max is below this
ZERO_RATIO_NEGATIVE_X = 0.27  # xy X axis, negative data
COLUMN_MARGIN_TOP, COLUMN_MARGIN_BOTTOM, COLUMN_ZERO_RATIO = 0.0505, 0.04, 0.56  # column scatter
DIVISIONS = 5


def nice_ceil(v: float) -> float:
    """The smallest 1-2-5 x 10^k >= v (v > 0)."""
    e = math.floor(math.log10(v))
    for m in (1, 2, 5, 10):
        t = m * 10.0 ** e
        if t >= v * (1 - 1e-12):
            return t
    raise AssertionError("unreachable")


def _xy(dmin: float, dmax: float, include_zero: bool, axis: str) -> tuple[float, float]:
    negative_ratio = ZERO_RATIO_NEGATIVE_X if axis == "x" else ZERO_RATIO
    from_zero = include_zero and 0 <= dmin < ZERO_RATIO * dmax
    to_zero = include_zero and dmax <= 0 and dmax > negative_ratio * dmin and not from_zero
    a, b = (0.0 if from_zero else dmin), (0.0 if to_zero else dmax)
    span = b - a
    if span <= 0:
        span = abs(dmax) or 1.0
    if dmin < 0 < dmax:  # each end by its own distance from 0
        return dmin * (1 + XY_MARGIN), dmax * (1 + XY_MARGIN)
    return (a if from_zero else a - XY_MARGIN * span), (b if to_zero else b + XY_MARGIN * span)


def auto_range(dmin: float, dmax: float, include_zero: bool = True, style: str = "bar",
               axis: str = "y") -> tuple[float, float, float]:
    """(axis min, axis max, major tick) for a plotted extent dmin..dmax.
    style "bar": include_zero adds 0 (bars always do); style "xy": 0 is
    added by Prism's ratio rule unless include_zero is False. axis: "x" or
    "y" (xy: negative X data start at 0 by their own ratio)."""
    if dmin > dmax:
        dmin, dmax = dmax, dmin
    span = dmax - dmin
    if span <= 0:
        span = abs(dmax) or 1.0
    if style == "xy":
        lo, hi = _xy(dmin, dmax, include_zero, axis)
    elif style == "column":
        top, bottom, ratio = COLUMN_MARGIN_TOP, COLUMN_MARGIN_BOTTOM, COLUMN_ZERO_RATIO
        lo, hi = dmin - bottom * span, dmax + top * span
        if include_zero and dmin >= 0 and dmin < ratio * dmax:
            lo = 0.0
        elif include_zero and dmax <= 0 and dmax > ratio * dmin:
            hi = 0.0
        elif dmin < 0 < dmax:
            lo = dmin
    else:
        top = COLUMN_MARGIN_TOP if style == "colbar" else HEADROOM
        hi = dmax + top * span if dmax > 0 else dmax
        lo = dmin - COLUMN_MARGIN_BOTTOM * span if style == "colbar" and dmin < 0 else dmin
        if include_zero:
            lo, hi = min(lo, 0.0), max(hi, 0.0)
    if hi == lo:
        hi = lo + 1.0
    t = nice_ceil((hi - lo) / DIVISIONS)
    return math.floor(lo / t + 1e-9) * t, math.ceil(hi / t - 1e-9) * t, t


MINOR_SPACING = 0.75  # inches between major ticks above which Prism adds minor ticks
AUTO_MINOR = 10  # minor intervals Prism then uses (0x8025 +52; nine minor ticks)


def auto_minor(lo: float, hi: float, tick: float, length_pt: float) -> int:
    """Minor intervals per major tick that Prism chooses for an axis whose
    minor ticks are automatic: 10 once the major ticks are more than 0.75 inch
    apart, else none. Corpus: 1418 of 1440 automatic linear axes of graphs
    Prism displayed (the rest are small integer ranges, where Prism also
    chose 5 or none; findings.md)."""
    if hi <= lo or tick <= 0 or length_pt <= 0:
        return 0
    spacing = tick * length_pt / (hi - lo) / 72.0
    return AUTO_MINOR if spacing > MINOR_SPACING + 1e-9 else 0

