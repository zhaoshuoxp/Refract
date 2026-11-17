"""Build a Graph from a data table with Prism 11's default graph for its
table type (verified on Prism's own default graphs, batch5 sample):
grouped -> interleaved bars (mean) with SD error bars and the individual
replicates; column -> scatter of the values with a median line; xy -> symbols
(circle, square, ...) at the mean with SD error bars.
"""

from __future__ import annotations

import math

from ..model.document import DataTable
from .model import Axis, Graph, Series
from .style import BAR_FILLS, DEFAULT, Style

# Prism's symbol cycle for data sets (XY plots, grouped means; corpus and seeds: shape
# codes 5, 1, 2, 3, 4, 10 - the sixth is a circle with a border)
SYMBOLS = ["circle", "square", "triangle", "triangle_down", "diamond", "circle"]
# horizontal step between point slots (one sample each; findings.md)
COLUMN_STEP = 8.62  # column scatter, 4.73 pt symbols
GROUPED_STEP = 3.35  # points over grouped bars, 6.32 pt symbols


def _num(v):
    return None if v is None or not math.isfinite(v) else float(v)


def _half_width(sd: float, n: int, error: str) -> float:
    """Error-bar half width: SD, SEM or the 95 % CI of the mean (t)."""
    if error == "sem":
        return sd / math.sqrt(n)
    if error == "ci":
        from scipy import stats

        return float(stats.t.ppf(0.975, n - 1)) * sd / math.sqrt(n)
    return sd


def cell(t: DataTable, ds: int, row: int, error: str = "sd"):
    """(centre, error low end, error high end, values) of one cell, from the
    table's data format. error: "sd", "sem" or "none" (replicate formats)."""
    f = t.data_format
    sub = [_num(t.values(ds, s)[row]) if row < len(t.values(ds, s)) else None for s in range(t.subcolumns_per_dataset)]
    if f in ("y_replicates", "y_single"):
        vals = [v for v in sub if v is not None]
        if not vals:
            return None, None, None, []
        m = sum(vals) / len(vals)
        if len(vals) < 2 or error == "none":
            return m, None, None, vals
        sd = math.sqrt(sum((v - m) ** 2 for v in vals) / (len(vals) - 1))
        e = _half_width(sd, len(vals), error)
        return m, m - e, m + e, vals
    m = sub[0]
    if m is None:
        return None, None, None, []
    if f in ("y_sd", "y_se", "y_cv", "y_sd_n", "y_se_n", "y_cv_n"):
        e = sub[1]
        if e is not None and f.startswith("y_cv"):
            e = abs(m) * e / 100
        return (m, m - e, m + e, [m]) if e is not None else (m, None, None, [m])
    if f == "y_plus_minus":
        return m, (m - sub[2]) if sub[2] is not None else None, (m + sub[1]) if sub[1] is not None else None, [m]
    if f == "y_high_low":
        return m, sub[2], sub[1], [m]
    return m, None, None, [m]


def used_rows(t: DataTable) -> int:
    """Rows up to the last one holding a number in any data set."""
    last = -1
    for j in range(len(t.datasets)):
        for s in range(t.subcolumns_per_dataset):
            for r, v in enumerate(t.values(j, s)):
                if _num(v) is not None and r > last:
                    last = r
    return last + 1


def pie_graph(t: DataTable, title: str | None = None) -> Graph:
    """Parts-of-whole table -> a pie of its first data set, one slice per row
    (row titles as categories)."""
    ds = t.datasets[0]
    vals = [v if v is not None and v > 0 else 0.0 for v in (_num(x) for x in t.values(0, 0))]
    titles = t.row_titles.subcolumns[0] if t.row_titles is not None and t.row_titles.subcolumns else []
    cats = [(titles[r] if r < len(titles) else "") or "" for r in range(len(vals))]
    return Graph(title=t.title if title is None else title, family="pie",
                 series=[Series(ds.title or "", "pie", list(range(len(vals))), vals)], categories=cats)


# Prism 11's default pie (the shipped seed, drawn by Prism on Refract's neutral
# table, E-pie): slice fills by row, nine in turn (rows 7-9 read from Prism's PDF
# of a 15-row pie), a 1.44 pt black outline, no title, one legend entry per
# drawn slice and "Total=" below.
PIE_FILLS = [(0, 0, 0, 255), (176, 176, 179, 255), (147, 147, 146, 255), (221, 220, 220, 255),
             (116, 115, 115, 255), (176, 176, 179, 255), (116, 115, 115, 255), (237, 237, 237, 255),
             (176, 176, 179, 255)]
PIE_SIZE = 144.0  # the pie's diameter, points
PIE_LEGEND = (19.92, -7.2, 14.4)  # first entry's (dx, dy) from the pie's top-right corner, step down
PIE_TOTAL = (81.72, 166.5)  # "Total=" text: centre x, line-box top, from the pie's top-left
PIE_OUTLINE = 1.44


def _total(v: float) -> str:
    return f"{v:.10g}"


def pie_defaults(g: Graph, t: DataTable) -> Graph:
    """A pie as Prism draws it by default (from_prism reads these settings
    from the file instead). Rows without a positive value get no slice and no
    legend entry; a row without a title is labelled "Legend" (Prism's
    placeholder)."""
    from .model import TextStyle

    s = g.series[0]
    g.title = ""
    g.x_length = g.y_length = PIE_SIZE
    s.slice_fills = [PIE_FILLS[r % len(PIE_FILLS)] for r in range(len(s.ys))]
    s.border_width = PIE_OUTLINE
    s.symbol_border = (0, 0, 0, 255)
    rows = [r for r, v in enumerate(s.ys) if v and v > 0]
    dx, dy, step = PIE_LEGEND
    g.legend = True
    g.legend_style = TextStyle(size=12)
    g.legend_pos = [(dx, dy + step * k) for k in range(len(rows))]
    g.legend_texts = [(g.categories[r] if r < len(g.categories) else "") or "Legend" for r in rows]
    g.legend_fills = [s.slice_fills[r] for r in rows]
    if rows:
        g.annotations = [{"kind": "text", "cx": PIE_TOTAL[0], "top": PIE_TOTAL[1],
                          "text": "Total=" + _total(sum(s.ys[r] for r in rows)),
                          "style": TextStyle(size=12, bold=True)}]
    return g


def from_table(t: DataTable, error: str = "sd", st: Style = DEFAULT, title: str | None = None) -> Graph:
    if t.kind == "survival":
        return survival_graph(t, title)
    g = Graph(title=t.title if title is None else title)
    if t.kind == "grouped":
        g.family = "grouped"
        n = used_rows(t)
        titles = t.row_titles.subcolumns[0] if t.row_titles else []
        g.categories = [(titles[r] if r < len(titles) else "") or "" for r in range(n)]
        k = len(t.datasets)
        if n == 1:  # one row: Prism shows each data set as its own labelled category
            g.categories = [ds.title or "" for ds in t.datasets]
            for j, ds in enumerate(t.datasets):
                c, lo, hi, vals = cell(t, j, 0, error)
                g.series.append(Series(ds.title or "", "bar", [float(j)], [c], [lo], [hi], [vals],
                                       width=COLUMN_BAR_WIDTH, fill=BAR_FILLS[j % len(BAR_FILLS)],
                                       spread_step=GROUPED_STEP))
            return g
        pitch = 1 / (k + st.grouped_gap)  # bar pitch in category units
        for j, ds in enumerate(t.datasets):
            s = Series(ds.title or "", "bar", [], [], width=st.grouped_bar_fraction * pitch, fill=BAR_FILLS[j % len(BAR_FILLS)],
                       spread_step=GROUPED_STEP)
            for r in range(n):
                c, lo, hi, vals = cell(t, j, r, error)
                s.xs.append(r + (j - (k - 1) / 2) * pitch)
                s.ys.append(c)
                s.err_lo.append(lo)
                s.err_hi.append(hi)
                s.points.append(vals)
            g.series.append(s)
    elif t.kind == "column":
        g.family = "column"
        g.legend = False
        g.categories = [ds.title or "" for ds in t.datasets]
        for j, ds in enumerate(t.datasets):
            vals = [v for v in (_num(x) for x in t.values(j, 0)) if v is not None]
            s = Series(ds.title or "", "scatter", [float(j)], [], symbol_size=st.column_symbol_size, spread_step=COLUMN_STEP)
            if vals:  # default: a line at the median, no error bar (verified)
                srt = sorted(vals)
                h = len(srt) // 2
                s.ys.append(srt[h] if len(srt) % 2 else (srt[h - 1] + srt[h]) / 2)
                s.points.append(vals)
            else:
                s.ys.append(None)
            g.series.append(s)
    elif t.kind == "xy":
        g.family = "xy"
        xs = t.x_values()
        g.x_axis = Axis(title=t.x.title if t.x is not None and t.x.title else "")
        for j, ds in enumerate(t.datasets):
            s = Series(ds.title or "", "points", [], [], symbol=SYMBOLS[j % len(SYMBOLS)])
            for r, x in enumerate(xs):
                if x is None or r >= t.n_rows:
                    continue
                c, lo, hi, _ = cell(t, j, r, error)
                if c is None:
                    continue
                s.xs.append(float(x))
                s.ys.append(c)
                s.err_lo.append(lo)
                s.err_hi.append(hi)
            g.series.append(s)
    else:
        raise NotImplementedError(f"graphs of {t.kind} tables")
    return g


def km_steps(times, codes, event: float = 1, censor: float = 0):
    """Kaplan-Meier staircase in percent: (xs, ys, censor marks). Starts at
    (0, 100); at each distinct time a horizontal run, then the drop for its
    deaths; a time with only censored subjects adds a vertex (Prism's path),
    and each censored time a mark on the curve; ends at the last time."""
    import numpy as np

    from ..stats.survival import _subjects, kaplan_meier

    tt, ee = _subjects(times, codes, event, censor)
    xs, ys, marks = [0.0], [100.0], []
    s = 100.0
    for u, _n, d, c, surv, _gw in kaplan_meier(np.asarray(tt), np.asarray(ee)):
        xs.append(u)
        ys.append(s)
        if d:
            s = 100.0 * surv
            xs.append(u)
            ys.append(s)
        if c:
            marks.append((u, s))
    return xs, ys, marks


def survival_graph(t: DataTable, title: str | None = None) -> Graph:
    """Prism's default survival graph: one Kaplan-Meier staircase per data
    set, in percent, black, censored subjects marked (verified on Prism's
    default survival graph)."""
    g = Graph(title=t.title if title is None else title, family="survival")
    g.x_axis = Axis(title=t.x.title if t.x is not None and t.x.title else "")
    g.y_axis = Axis(title="Probability of Survival", minor=5, minor_auto=False)
    x = t.x_values()
    for j, ds in enumerate(t.datasets):
        codes = [_num(v) for v in t.values(j, 0)]
        xs, ys, marks = km_steps(x, codes)
        g.series.append(Series(ds.title or "", "steps", xs, ys, marks=marks))
    g.legend = len(g.series) > 1  # Prism shows no legend on a one-group survival graph (E-survival)
    return g


BRACKET_STEP = 0.09  # fraction of the data span between stacked brackets
BRACKET_LABEL = 0.075  # room above a bracket for its label (fraction of the span)


def _top_near(g: Graph, x1: float, x2: float) -> float | None:
    """The highest thing plotted between two positions (bars, error bars, points)."""
    lo, hi = min(x1, x2) - 1e-9, max(x1, x2) + 1e-9
    vals = []
    for s in g.series:
        for i, x in enumerate(s.xs):
            if lo <= x <= hi:
                vals += [v for v in ([s.ys[i]] if i < len(s.ys) else []) if v is not None]
                vals += [v for e in (s.err_hi,) if i < len(e) for v in [e[i]] if v is not None]
                vals += list(s.points[i]) if i < len(s.points) else []
    return max(vals) if vals else None


def add_significance(g: Graph, pairs: list[tuple[float, float, str]]) -> Graph:
    """Brackets with labels (stars) between pairs of positions, over the data:
    narrow pairs first, each above everything it spans and above the brackets
    it overlaps."""
    ext = g.extent()
    if ext is None or not pairs:
        return g
    log = g.y_axis.log
    if log:  # stacked in decades: work in log10 units
        tops = [v for v in (ext[2], ext[3]) if v > 0]
        if not tops:
            return g
        span = max(math.log10(max(tops)) - math.log10(min(tops)), 1.0)  # at least a decade
    else:
        span = (ext[3] - min(ext[2], 0.0)) or 1.0
    placed: list[dict] = []
    for x1, x2, label in sorted(pairs, key=lambda p: (abs(p[1] - p[0]), min(p[0], p[1]))):
        base = _top_near(g, x1, x2)
        if base is None or (log and base <= 0):
            continue
        lo, hi = min(x1, x2), max(x1, x2)
        for b in placed:
            if b["x1"] <= hi + 1e-9 and lo - 1e-9 <= b["x2"]:  # overlapping (touching counts)
                base = max(base, b["top"])
        if log:
            y = 10 ** (math.log10(base) + BRACKET_STEP * span * 0.8)
            top = 10 ** (math.log10(y) + BRACKET_LABEL * span)
        else:
            y = base + BRACKET_STEP * span * 0.8
            top = y + BRACKET_LABEL * span
        b = {"x1": lo, "x2": hi, "y": y, "top": top, "label": label}
        placed.append(b)
    g.significance = placed
    return g


def column_bars(g: Graph, t: DataTable, error: str = "sd", st: Style = DEFAULT) -> Graph:
    """Column table as bars (mean, SD error bars, the values as points) in
    place of the default scatter; one bar per column."""
    out = []
    for j, s in enumerate(g.series):
        vals = s.points[0] if s.points else []
        b = Series(s.title, "bar", [float(j)], [], width=COLUMN_BAR_WIDTH, fill=BAR_FILLS[j % len(BAR_FILLS)],
                   points=[vals], symbol_size=s.symbol_size, spread_step=s.spread_step)
        if vals:
            m = sum(vals) / len(vals)
            sd = math.sqrt(sum((v - m) ** 2 for v in vals) / (len(vals) - 1)) if len(vals) > 1 else None
            e = None if sd is None else _half_width(sd, len(vals), error)
            b.ys.append(m)
            b.err_lo.append(None if e is None else m - e)
            b.err_hi.append(None if e is None else m + e)
        else:
            b.ys.append(None)
        out.append(b)
    g.series = out
    return g


COLUMN_BAR_WIDTH = 0.6  # of the column slot (PROVISIONAL: not measured yet)


def mean_symbols(g: Graph, error: str = "sd") -> Graph:
    """Bars / column scatter -> the mean as a symbol with error bars (Prism
    plot styles 7 and 8)."""
    for j, s in enumerate(g.series):
        vals_list = s.points or []
        if s.kind == "scatter":  # column scatter: recompute mean and SD from the values
            vals = vals_list[0] if vals_list else []
            if vals:
                m = sum(vals) / len(vals)
                sd = math.sqrt(sum((v - m) ** 2 for v in vals) / (len(vals) - 1)) if len(vals) > 1 else None
                e = None if sd is None else _half_width(sd, len(vals), error)
                s.ys = [m]
                s.err_lo, s.err_hi = [None if e is None else m - e], [None if e is None else m + e]
        s.kind = "points"
        s.points = []
        s.symbol = SYMBOLS[j % len(SYMBOLS)] if g.family == "grouped" else "circle"
    return g


# ------------------------------------------------------------ estimation plots
ESTIMATION_TITLES = {True: "Mean of differences", False: "Difference between means"}


def estimation_graph(view: DataTable, paired: bool, title: str = "", level: float = 0.95) -> Graph:
    """The estimation plot of a t test, from the analysis's view table (three
    data sets: group A, group B, and B - A). Paired: one row per subject,
    the third set the differences, their mean and its t confidence interval
    computed here. Unpaired / Welch: the third set holds the interval's low
    end, the difference of the means and the high end (as Prism stores it).
    The groups are categories 0 and 1, the difference category 2, drawn on
    a right axis whose zero is group A's mean (refract.render.qt)."""
    from statistics import mean, stdev

    from scipy import stats

    from ..model.document import to_number

    a, b, d = view.datasets[:3]

    def col(ds) -> list[float | None]:
        return [to_number(c) for c in (ds.subcolumns[0] if ds.subcolumns else [])]

    ca, cb, cd = col(a), col(b), col(d)
    va = [x for x in ca if x is not None]
    vb = [x for x in cb if x is not None]
    if not va or not vb:
        raise NotImplementedError("estimation plot without data")
    pairs = [(x, y) for x, y in zip(ca, cb, strict=False) if x is not None and y is not None]
    ma, mb = mean(va), mean(vb)
    if paired:
        diffs = [x for x in cd if x is not None] or [y - x for x, y in pairs]
        md = mean(diffs)
        n = len(diffs)
        half = float(stats.t.ppf(0.5 + level / 2, n - 1)) * stdev(diffs) / math.sqrt(n) if n > 1 else 0.0
        lo, hi = md - half, md + half
    else:
        diffs = []
        vals = [x for x in cd if x is not None]
        if len(vals) >= 3:
            lo, md, hi = vals[:3]
        else:
            md = mb - ma
            lo = hi = md
    cats = [a.title or "", b.title or "", (d.title or "").replace("\r", "\n")]
    # series: what the axes autoscale on (everything drawn, in left-axis units)
    series = [Series(cats[0], "scatter", [0.0], [ma], points=[va]),
              Series(cats[1], "scatter", [1.0], [mb], points=[vb]),
              Series(cats[2], "scatter", [2.0], [ma + md], [ma + lo], [ma + hi],
                     points=[[ma + x for x in diffs]])]
    g = Graph(title=title, family="column", series=series, categories=cats, legend=False)
    g.estimation = {"paired": paired, "a": va, "b": vb, "pairs": pairs, "diffs": diffs, "lo": lo, "mean": md,
                    "hi": hi, "mean_a": ma, "mean_b": mb, "right_title": ESTIMATION_TITLES[paired],
                    "color": (0, 0, 0, 255), "symbol_size": 6.32, "line_width": 1.0}
    return g
