"""Graph types for Refract's graphs (Change Graph Type, docs/ui-spec.md
§3.4): for each table kind the families it can be drawn as, each family's
types in tabs, the options a type takes (what the centre and the error bar
show), and the builders that make the render model from the table. The
names and thumbnails are our own.

A NativeGraph keeps its type in `style` and the chosen option in `error`;
type options beyond that (heat-map colours, survival scale) in `options`.
The older style names ("default", "bars", "means", "donut") are aliases."""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field

from ..model.document import DataTable
from . import build
from .model import Axis, Graph, Series
from .style import BAR_FILLS, BARS_ONLY_FILLS

# --------------------------------------------------------------- options
PLOTS_ERROR = [("mean_sd", "Mean with SD"), ("mean_sem", "Mean with SEM"), ("mean_ci", "Mean with 95% CI"),
               ("mean", "Mean only"), ("median_range", "Median with range"), ("median_iqr",
                                                                                 "Median with interquartile range")]
PLOTS_LINE = [("median", "Median"), ("mean", "Mean"), ("mean_sd", "Mean with SD"), ("mean_sem", "Mean with SEM"),
              ("mean_ci", "Mean with 95% CI"), ("median_iqr", "Median with interquartile range"), ("none", "None")]
PLOTS_FLOAT = [("median", "Line at median"), ("mean", "Line at mean"), ("none", "No line")]
PLOTS_BOX = [("min_max", "Whiskers: min to max"), ("min_max_points", "Whiskers: min to max, show all points"),
             ("tukey", "Whiskers: Tukey"), ("p10_90", "Whiskers: 10-90 percentile"),
             ("p5_95", "Whiskers: 5-95 percentile")]  # min to max first: Prism's default (E-compare)
PLOTS_VIOLIN = [("quartiles", "Median and quartiles"), ("median", "Median only")]
PLOTS_CENTRE = [("mean", "Mean"), ("median", "Median")]
OLD_ERRORS = {"sd": "mean_sd", "sem": "mean_sem", "ci": "mean_ci", "none": "mean"}


@dataclass
class GraphType:
    key: str
    family: str  # xy | column | grouped | contingency | survival | parts_of_whole | nested | multivariable
    tab: str
    label: str
    plots: list[tuple[str, str]] = field(default_factory=list)  # the "Plot" choices; first: default
    prism: str | None = None  # the style Refract writes for Prism (graph_patch), None: Prism's default + a note
    thumb: str = ""  # thumbnail drawing (refract.ui.graph_wizard)


def _t(key, family, tab, label, plots=(), prism=None) -> GraphType:
    return GraphType(key, family, tab, label, list(plots), prism, key)


def _h(base: GraphType, label: str | None = None) -> GraphType:
    """The same graph on its side (categories down the left)."""
    prism = "stacked_h" if base.prism == "stacked" else base.prism  # the parts' bar: its own chart kind
    return GraphType(base.key + "_h", base.family, base.tab, label or base.label + ", horizontal", base.plots,
                     prism, base.key + "_h")


_col_ind = [_t("col_scatter", "column", "Individual values", "Scatter", PLOTS_LINE, "default"),
            _t("col_scatter_bar", "column", "Individual values", "Scatter with bar", PLOTS_ERROR, "bars"),
            _t("col_before_after", "column", "Individual values", "Before and after (one line per row)", (),
               "before_after")]
_col_box = [_t("col_floating", "column", "Box and violin", "Floating bars (min to max)", PLOTS_FLOAT),
            _t("col_box", "column", "Box and violin", "Box and whiskers", PLOTS_BOX, "box"),
            _t("col_violin", "column", "Box and violin", "Violin", PLOTS_VIOLIN, "violin")]
_col_err = [_t("col_bar", "column", "Mean or median and error", "Column bars", PLOTS_ERROR, "bars_only"),
            _t("col_means", "column", "Mean or median and error", "Symbols with error bars", PLOTS_ERROR, "means"),
            _t("col_means_line", "column", "Mean or median and error", "Symbols with error bars, connected",
               PLOTS_ERROR, "means_line")]
_grp_sum = [_t("grp_bars", "grouped", "Summary data", "Interleaved bars", PLOTS_ERROR, "bars_only"),
            _t("grp_bars_sep", "grouped", "Summary data", "Separated bars (grouped by data set)", PLOTS_ERROR),
            _t("grp_stacked", "grouped", "Summary data", "Stacked bars", PLOTS_CENTRE)]
_grp_sym = [_t("grp_means", "grouped", "Summary data", "Interleaved symbols with error bars", PLOTS_ERROR, "means"),
            _t("grp_means_line", "grouped", "Summary data", "Symbols with error bars, connected", PLOTS_ERROR,
               "means_line"),
            _t("grp_means_sep", "grouped", "Summary data", "Separated symbols with error bars", PLOTS_ERROR)]
_grp_box = [_t("grp_box", "grouped", "Box and violin", "Interleaved box and whiskers", PLOTS_BOX, "box"),
            _t("grp_floating", "grouped", "Box and violin", "Interleaved floating bars", PLOTS_FLOAT),
            _t("grp_violin", "grouped", "Box and violin", "Interleaved violins", PLOTS_VIOLIN, "violin"),
            _t("grp_box_sep", "grouped", "Box and violin", "Separated box and whiskers", PLOTS_BOX),
            _t("grp_floating_sep", "grouped", "Box and violin", "Separated floating bars", PLOTS_FLOAT),
            _t("grp_violin_sep", "grouped", "Box and violin", "Separated violins", PLOTS_VIOLIN)]
_cont = [_t("cont_bars", "contingency", "", "Interleaved bars", (), "bars_only"),
         _t("cont_bars_sep", "contingency", "", "Separated bars (grouped by outcome)"),
         _t("cont_stacked", "contingency", "", "Stacked bars"),
         _t("cont_percent", "contingency", "", "Stacked to 100 %")]
_pow = [_t("pie", "parts_of_whole", "", "Pie", (), "default"), _t("donut", "parts_of_whole", "", "Donut", (), "donut"),
        _t("pow_stacked", "parts_of_whole", "", "Stacked bar", (), "stacked")]
HEATMAPS = ("viridis", "magma", "inferno", "plasma", "grays", "blues", "greenred", "rainbow")
HEAT_NAMES = {"greenred": "green-black-red"}
MV_CAT = [("mv_scatter_cat", "Scatter by category", PLOTS_LINE), ("mv_means_cat", "Mean and error by category",
                                                                    PLOTS_ERROR),
          ("mv_bars_cat", "Bars with the values, by category", PLOTS_ERROR),
          ("mv_box_cat", "Box and whiskers by category", PLOTS_BOX), ("mv_violin_cat", "Violins by category",
                                                                       PLOTS_VIOLIN),
          ("mv_bar_cat", "Bars by category", PLOTS_ERROR),
          ("mv_before_after", "Before and after by category (a line per group)", PLOTS_CENTRE),
          ("mv_before_after_bars", "Before and after, with bars of the categories", PLOTS_CENTRE)]

TYPES: list[GraphType] = [
    _t("xy_points", "xy", "", "Points with error bars", PLOTS_ERROR, "default"),
    _t("xy_points_line", "xy", "", "Points and connecting line", PLOTS_ERROR, "points_line"),
    _t("xy_replicates", "xy", "", "Each replicate"),
    _t("xy_replicates_line", "xy", "", "Each replicate, line through the means"),
    _t("xy_line", "xy", "", "Line with error bars, no symbols", PLOTS_ERROR, "line"),
    _t("xy_rep_lines", "xy", "", "Each replicate as its own line"),
    _t("xy_bars", "xy", "", "Bars at each X", PLOTS_ERROR),
    _t("xy_area", "xy", "", "Line with the area below filled", PLOTS_ERROR, "area"),
    *_col_ind, _h(_col_ind[0]), _h(_col_ind[1]),
    _t("col_before_after_bars", "column", "Individual values", "Before and after, with bars of the means"),
    *_col_box, *(_h(x) for x in _col_box),
    *_col_err, *(_h(x) for x in _col_err),
    _t("grp_scatter", "grouped", "Individual values", "Interleaved scatter", PLOTS_LINE, "scatter"),
    _t("grp_scatter_sep", "grouped", "Individual values", "Separated scatter (grouped by data set)", PLOTS_LINE),
    _t("grp_bars_points", "grouped", "Individual values", "Interleaved bars with the values", PLOTS_ERROR, "default"),
    _t("grp_bars_points_sep", "grouped", "Individual values", "Separated bars with the values", PLOTS_ERROR),
    _t("grp_dots", "grouped", "Individual values", "Each replicate, no centre line", (), "dots"),
    _t("grp_rep_lines", "grouped", "Individual values", "Each replicate connected across rows"),
    *_grp_sum, *(_h(x) for x in _grp_sum), *_grp_sym, _h(_grp_sym[0]), _h(_grp_sym[1]),
    *[_t(f"grp_heat_{c}", "grouped", "Heat map", f"Heat map ({HEAT_NAMES.get(c, c)})", PLOTS_CENTRE)
      for c in HEATMAPS],
    _t("grp3_means_line", "grouped", "Three-way", "Two panels: symbols with error bars, connected", PLOTS_ERROR),
    _t("grp3_bars", "grouped", "Three-way", "Two panels: interleaved bars", PLOTS_ERROR),
    _t("grp3_scatter", "grouped", "Three-way", "Two panels: interleaved scatter", PLOTS_LINE),
    _t("grp3_scatter_side", "grouped", "Three-way", "Two panels: scatter side by side", PLOTS_LINE),
    *_grp_box, *(_h(x) for x in _grp_box[:3]),
    *_cont, _h(_cont[0]), _h(_cont[2]), _h(_cont[3]),
    _t("surv_ticks", "survival", "", "Staircase with censor ticks", (), "default"),
    _t("surv_plain", "survival", "", "Staircase without ticks"),
    _t("surv_points", "survival", "", "Points at each step, connected"),
    _t("surv_steps_symbols", "survival", "", "Staircase with a symbol at each step"),
    _t("surv_inverted_ticks", "survival", "", "Deaths (rising staircase) with censor ticks"),
    _t("surv_inverted_plain", "survival", "", "Deaths (rising staircase) without ticks"),
    _t("surv_inverted_points", "survival", "", "Deaths at each step, connected"),
    *_pow, _h(_pow[2], "Stacked bar, horizontal"), _t("waffle", "parts_of_whole", "", "Waffle (10 x 10 grid)"),
    _t("nest_scatter", "nested", "", "Scatter by subgroup", PLOTS_LINE),
    _t("nest_scatter_bar", "nested", "", "Scatter with bars, by subgroup", PLOTS_ERROR),
    _t("nest_bars", "nested", "", "Bars with error, by subgroup", PLOTS_ERROR),
    _t("nest_floating", "nested", "", "Floating bars by subgroup", PLOTS_FLOAT),
    _t("nest_box", "nested", "", "Box and whiskers by subgroup", PLOTS_BOX),
    _t("nest_violin", "nested", "", "Violins by subgroup", PLOTS_VIOLIN),
    _t("mv_bubble", "multivariable", "", "Bubble plot"),
    _t("mv_scatter", "multivariable", "", "Scatter of two variables"),
    _t("mv_heat", "multivariable", "", "Heat map of the variables (z scores)"),
    *[_t(k, "multivariable", "", label, plots) for k, label, plots in MV_CAT],
]
BY_KEY = {t.key: t for t in TYPES}
FAMILY_NAMES = {"xy": "XY", "column": "Column", "grouped": "Grouped", "contingency": "Contingency",
                "survival": "Survival", "parts_of_whole": "Parts of whole", "nested": "Nested",
                "multivariable": "Multiple variables"}
# the families a table kind can be drawn as (an XY table as columns: each data set's values
# pooled; as grouped: its X values as the rows)
FAMILIES = {"xy": ["xy", "column", "grouped"], "column": ["column"], "grouped": ["grouped", "column"],
            "contingency": ["contingency", "grouped"], "survival": ["survival"],
            "parts_of_whole": ["parts_of_whole", "column"], "nested": ["nested", "column"],
            "multivariable": ["multivariable"]}
DEFAULTS = {"xy": "xy_points", "column": "col_scatter", "grouped": "grp_bars_points", "contingency": "cont_bars",
            "survival": "surv_ticks", "parts_of_whole": "pie", "nested": "nest_scatter", "multivariable": "mv_bubble"}
ALIASES = {("column", "bars"): "col_scatter_bar", ("column", "means"): "col_means", ("grouped", "means"): "grp_means",
           ("parts_of_whole", "donut"): "donut"}


def resolve(kind: str, style: str | None) -> GraphType | None:
    """The graph type a NativeGraph's style names (None / "" : not chosen yet)."""
    if not style:
        return None
    if style in BY_KEY:
        return BY_KEY[style]
    return BY_KEY.get(ALIASES.get((kind, style), DEFAULTS.get(kind, "")))


def types_for(family: str) -> list[GraphType]:
    return [t for t in TYPES if t.family == family]


def tabs_for(family: str) -> list[str]:
    out: list[str] = []
    for t in types_for(family):
        if t.tab not in out:
            out.append(t.tab)
    return out


def plot_option(gt: GraphType, error: str | None) -> str | None:
    """The type's plot option from a NativeGraph's error (older values mapped)."""
    keys = [k for k, _ in gt.plots]
    if not keys:
        return None
    e = OLD_ERRORS.get(error or "", error)
    return e if e in keys else keys[0]


# the graph types written from a seed of Prism's own graph of that type (refract.formats.seeds.type_seed)
SEEDED = frozenset({'nest_scatter_bar', 'col_floating', 'grp_scatter_sep', 'grp_bars_points_sep', 'grp_rep_lines', 'grp_bars_sep', 'grp_stacked', 'grp_means_sep', 'grp_bars_h', 'grp_floating', 'grp_box_sep', 'grp_violin_sep', 'xy_replicates', 'xy_replicates_line', 'xy_rep_lines', 'xy_bars', 'surv_points', 'surv_inverted_points', 'cont_bars_sep', 'cont_stacked', 'cont_bars_h', 'nest_scatter',
                    # the second reference batch (E-types round 2)
                    'surv_inverted_ticks', 'surv_steps_symbols', 'cont_stacked_h', 'grp_stacked_h', 'grp_bars_sep_h',
                    'grp_box_h', 'col_floating_h', 'nest_box', 'nest_floating', 'nest_violin',
                    'grp_heat_viridis'})  # E-heat: the other colour maps are drawn from this one (HEAT_SEED)


def from_prism_plots(kind: str, plots: list[dict], horizontal: bool) -> tuple[str, str | None] | None:
    """The Refract graph type (key, plot choice) a Prism graph of a `kind`
    table draws, from its plots (refract.render.prism_sync.summary: style
    code, bar flag, connect, area, symbol shape, plot choice, whiskers);
    None when its look is none of Refract's types."""
    if not plots:
        return None
    p = plots[0]
    st, bar, connect = p.get("style"), p.get("bar"), p.get("connect")
    key = None
    if kind == "xy" and st == 0:
        key = "xy_area" if p.get("area") else "xy_line" if connect and p.get("shape") == 0 else \
            "xy_points_line" if connect else "xy_points"
    elif kind == "column":
        key = {3: "col_scatter_bar" if bar else "col_scatter", 5: "col_bar", 6: "col_bar",
               7: "col_means_line" if connect else "col_means", 4: "col_box", 11: "col_violin",
               8: "col_before_after"}.get(st)
    elif kind in ("grouped", "contingency"):
        key = {3: "grp_bars_points" if bar else "grp_scatter", 1: "grp_bars", 5: "grp_bars",
               7: "grp_means_line" if connect else "grp_means", 4: "grp_box", 11: "grp_violin", 8: "grp_dots"}.get(st)
        if kind == "contingency":
            key = "cont_bars" if key in ("grp_bars", "grp_bars_points") else None
    elif kind == "survival":
        key = "surv_ticks"
    elif kind == "parts_of_whole":
        key = "donut" if p.get("style") == 9 and p.get("pie") == 2 else "pie"
    if key is None:
        return None
    if horizontal and f"{key}_h" in BY_KEY:
        key = f"{key}_h"
    gt = BY_KEY[key]
    choices = [c for c, _ in gt.plots]
    plot = p.get("whiskers") if st == 4 else p.get("plot")
    return key, plot if plot in choices else None


HORIZONTAL_KINDS = {"column"}  # table kinds whose horizontal graphs Prism keeps on their side


def is_horizontal(gt: GraphType | None) -> bool:
    return gt is not None and gt.key.endswith("_h")


HEAT_SEED = "grp_heat_viridis"  # the heat maps' seed (Prism's default heat map: viridis; E-heat)


def is_heat(gt: GraphType | None) -> bool:
    return gt is not None and gt.key.startswith("grp_heat_")


# horizontal types written from the seed of a near type (its plot style patched in, or set on its side):
# Prism keeps a grouped graph on its side only when it starts from one of its own (E-types round 2)
# key -> (the seed's type, the plot written on it: refract.formats.graph_patch.on_side)
BORROWED = {"grp_means_h": ("grp_bars_h", "means"), "grp_means_line_h": ("grp_bars_h", "means_line"),
            "grp_violin_h": ("grp_box_h", "violin"), "grp_floating_h": ("grp_box_h", "floating")}


# graph types Prism has no graph for (its own Create New Graph window, checked by the user: survival
# staircases always show their censor ticks; contingency bars have no 100 % stacking)
PRISM_HAS_NONE = frozenset({"surv_plain", "surv_inverted_plain", "cont_percent", "cont_percent_h", "waffle"})


def in_prism(gt: GraphType | None, table_kind: str | None = None) -> str:
    """What Prism shows of a graph of this type once saved (the wizard says it)."""
    if gt is None:
        return ""
    if gt.key in PRISM_HAS_NONE:
        return "In Prism: its default graph of the table (Prism has no such graph)"
    if is_horizontal(gt) and (table_kind or gt.family) not in HORIZONTAL_KINDS and gt.key not in SEEDED and \
            gt.prism != "stacked_h" and gt.key not in BORROWED:
        return "In Prism: the same graph, upright"
    if is_heat(gt) and gt.key != HEAT_SEED and HEAT_SEED in SEEDED:
        return "In Prism: the same heat map, in Prism's viridis colours"
    if gt.key in SEEDED or gt.key in BORROWED or gt.prism is not None or gt.key in ("mv_bubble", "mv_scatter"):
        return "In Prism: the same graph"
    return "In Prism: its default graph of the table (not written as this type yet)"


def prism_style(gt: GraphType | None) -> tuple[str, str | None]:
    """(style the Prism writer takes, a note when Prism will show something else);
    "seed": written from the type's seed (SEEDED)."""
    if gt is None:
        return "default", "no graph type chosen yet"
    if gt.key in SEEDED:
        return "seed", None
    if gt.prism is not None:
        return gt.prism, None
    if gt.key in PRISM_HAS_NONE:
        return "default", f"graph type “{gt.label}” (Prism has no such graph: it shows its default graph of the table)"
    return "default", f"graph type “{gt.label}” (Prism shows its default graph of the table)"


# --------------------------------------------------------------- statistics
def _vals(xs) -> list[float]:
    return [float(v) for v in xs if v is not None and math.isfinite(v)]


def _quantile(s: list[float], q: float) -> float:
    """The q quantile of sorted values as Prism computes it (rank (n+1)q, as
    refract.stats.descriptive.percentile; E-compare: Prism's boxes of the
    box-and-whiskers sample sit at these quartiles, not at rank 1+(n-1)q)."""
    if not s:
        return float("nan")
    pos = (len(s) + 1) * q
    if pos <= 1:
        return s[0]
    if pos >= len(s):
        return s[-1]
    lo = math.floor(pos)
    return s[lo - 1] + (s[lo] - s[lo - 1]) * (pos - lo)


def summary(vals: list[float], plot: str | None) -> tuple[float | None, float | None, float | None]:
    """(centre, error low end, error high end) of values for a plot option."""
    v = sorted(_vals(vals))
    if not v:
        return None, None, None
    n = len(v)
    mean = sum(v) / n
    med = _quantile(v, 0.5)
    plot = plot or "mean_sd"
    if plot in ("median", "median_range", "median_iqr"):
        if plot == "median_range":
            return med, v[0], v[-1]
        if plot == "median_iqr":
            return med, _quantile(v, 0.25), _quantile(v, 0.75)
        return med, None, None
    if plot == "mean_range":
        return mean, v[0], v[-1]
    if plot in ("mean", "none") or n < 2:
        return (None if plot == "none" else mean), None, None
    sd = math.sqrt(sum((x - mean) ** 2 for x in v) / (n - 1))
    e = {"mean_sd": sd, "mean_sem": sd / math.sqrt(n)}.get(plot)
    if e is None:  # 95 % CI
        from scipy import stats

        e = float(stats.t.ppf(0.975, n - 1)) * sd / math.sqrt(n)
    return mean, mean - e, mean + e


def box_stats(vals: list[float], plot: str | None, centre: str | None = "median") -> tuple[dict | None, list[float]]:
    """Box (or floating bar) statistics and the values beyond the whiskers."""
    v = sorted(_vals(vals))
    if not v:
        return None, []
    q1, med, q3 = _quantile(v, 0.25), _quantile(v, 0.5), _quantile(v, 0.75)
    b = {"q1": q1, "med": med, "q3": q3, "mean": sum(v) / len(v), "lo": v[0], "hi": v[-1], "centre": centre,
         "n": len(v)}
    out: list[float] = list(v) if plot == "min_max_points" else []  # every value drawn over the box
    if plot == "tukey":
        iqr = q3 - q1
        lo_f, hi_f = q1 - 1.5 * iqr, q3 + 1.5 * iqr
        b["lo"] = min(x for x in v if x >= lo_f)
        b["hi"] = max(x for x in v if x <= hi_f)
        out = [x for x in v if x < lo_f or x > hi_f]
    elif plot in ("p10_90", "p5_95"):
        a = 0.10 if plot == "p10_90" else 0.05
        b["lo"], b["hi"] = _quantile(v, a), _quantile(v, 1 - a)
        out = [x for x in v if x < b["lo"] or x > b["hi"]]
    return b, out


VIOLIN_TAIL = 3.6  # bandwidths drawn beyond the extremes (E-compare probe 8: 3.55-3.65 on 6, 12 and 25 values)
VIOLIN_BANDWIDTH = 0.5  # of Silverman's rule (probe 8: 0.47-0.57 on six violins of 6-25 values)


def kde(vals: list[float], n: int = 80) -> list[tuple[float, float]]:
    """A Gaussian kernel density as Prism draws its violins: half Silverman's
    bandwidth, out to 3.6 bandwidths past the extremes (E-compare: fitted to
    the outlines of Prism's violins of 6, 12 and 25 values)."""
    v = _vals(vals)
    if len(v) < 2:
        return []
    m = sum(v) / len(v)
    sd = math.sqrt(sum((x - m) ** 2 for x in v) / (len(v) - 1)) or 1e-9
    h = VIOLIN_BANDWIDTH * 1.06 * sd * len(v) ** -0.2
    lo, hi = min(v) - VIOLIN_TAIL * h, max(v) + VIOLIN_TAIL * h
    pts = []
    for k in range(n + 1):
        y = lo + (hi - lo) * k / n
        pts.append((y, sum(math.exp(-0.5 * ((y - x) / h) ** 2) for x in v)))
    return pts


# --------------------------------------------------------------- the data, by family
def groups(t: DataTable) -> list[tuple[str, list[float]]]:
    """One group per column: a column / nested / parts-of-whole table's data
    sets, an XY or grouped table's data sets with their values pooled."""
    out = []
    for j, ds in enumerate(t.datasets):
        vals: list[float] = []
        for s in range(t.subcolumns_per_dataset if t.data_format in ("y_replicates", "y_single") else 1):
            vals += _vals(t.values(j, s))
        out.append((ds.title or f"Data set {j + 1}", vals))
    return out


def cells(t: DataTable) -> tuple[list[str], list[str], list[list[list[float]]]]:
    """(row labels, data set titles, values[row][set]) of a grouped-like table:
    an XY table's X values as the rows."""
    if t.kind == "xy":
        xs = t.x_values()
        rows = [f"{x:g}" if x is not None else "" for x in xs]
    else:
        titles = t.row_titles.subcolumns[0] if t.row_titles else []
        n = build.used_rows(t)
        rows = [(titles[r] if r < len(titles) else "") or str(r + 1) for r in range(n)]
    n = len(rows)
    sub = t.subcolumns_per_dataset if t.data_format in ("y_replicates", "y_single") else 1
    vals = []
    for r in range(n):
        row = []
        for j in range(len(t.datasets)):
            if t.data_format in ("y_replicates", "y_single"):
                row.append(_vals([t.values(j, s)[r] if r < len(t.values(j, s)) else None for s in range(sub)]))
            else:
                c = build.cell(t, j, r)[0]
                row.append([] if c is None else [c])
        vals.append(row)
    keep = [r for r in range(n) if any(vals[r])]
    return [rows[r] for r in keep], [ds.title or "" for ds in t.datasets], [vals[r] for r in keep]


# --------------------------------------------------------------- builders
COL_WIDTH = 0.6
# Prism's stacked and separated graphs: bars 0.67 of the slot, the X axis 95.76 pt (stacked) or the grouped
# graphs' 143.89 pt (separated) long whatever the number of slots (E-types, Prism's exports)
TYPE_BAR_WIDTH = 0.67
STACKED_LENGTH, SEPARATED_LENGTH = 95.76, 143.89
WIDE_LENGTH = 215.87  # Prism's nested graphs and grouped replicates joined across rows: 3 in, as an XY graph's
BOX_SYMBOL = 2.88  # the values over a box: Prism draws size 4 (its default) at 0.72 pt a step (E-compare)


def _column(t: DataTable, gt: GraphType, plot: str | None, title: str, gs=None) -> Graph:
    g = Graph(title=title, family="column", legend=False)
    gs = groups(t) if gs is None else gs
    g.categories = [n for n, _ in gs]
    k = gt.key
    for j, (name, vals) in enumerate(gs):
        fill = BAR_FILLS[j % len(BAR_FILLS)]
        x = float(j)
        if k in ("col_box", "col_floating", "col_violin"):
            kind = {"col_box": "box", "col_floating": "floating", "col_violin": "violin"}[k]
            centre = None if plot == "none" else ("mean" if plot == "mean" else "median")
            b, out = box_stats(vals, plot if kind == "box" else "min_max", centre)
            if b is not None and kind == "violin":
                b["kde"] = kde(vals)
                if plot == "median":
                    b["q1"] = b["q3"] = None
            s = Series(name, kind, [x], [b["med"] if b else None], [b["lo"] if b else None], [b["hi"] if b else None],
                       [out], fill=fill, width=COL_WIDTH, box=[b], symbol_size=BOX_SYMBOL if kind == "box" else 4.73)
        elif k in ("col_bar", "col_scatter_bar"):
            c, lo, hi = summary(vals, plot)
            s = Series(name, "bar", [x], [c], [lo], [hi], [vals] if k == "col_scatter_bar" else [],
                       fill=fill, width=COL_WIDTH, spread_step=build.COLUMN_STEP, symbol_size=4.73)
        elif k in ("col_means", "col_means_line"):
            c, lo, hi = summary(vals, plot)
            s = Series(name, "points", [x], [c], [lo], [hi])
        else:  # scatter
            c, lo, hi = summary(vals, plot)
            s = Series(name, "scatter", [x], [c], [lo], [hi], [vals], symbol_size=4.73, spread_step=build.COLUMN_STEP)
        g.series.append(s)
    if k == "col_means_line":
        pts = [(s.xs[0], s.ys[0]) for s in g.series if s.ys and s.ys[0] is not None]
        g.series.insert(0, Series("", "line", [x for x, _ in pts], [y for _, y in pts], connect=True))
    if k in ("col_before_after", "col_before_after_bars"):  # one line per row across the columns
        bars = []
        if k == "col_before_after_bars":
            for j, (name, vals) in enumerate(gs):
                c = summary(vals, "mean")[0]
                bars.append(Series(name, "bar", [float(j)], [c], fill=BAR_FILLS[j % len(BAR_FILLS)], width=COL_WIDTH))
        g.series = bars
        n = max((len(t.values(j, 0)) for j in range(len(t.datasets))), default=0)
        for r in range(n):
            ys = [t.values(j, 0)[r] if r < len(t.values(j, 0)) else None for j in range(len(t.datasets))]
            pts = [(float(j), y) for j, y in enumerate(ys) if y is not None]
            if len(pts) >= 1:
                g.series.append(Series(f"Row {r + 1}", "points", [x for x, _ in pts], [y for _, y in pts],
                                       connect=True, symbol_size=5.5))
    return g


def _transpose(rows, sets, vals):
    """Separated graphs: the data sets become the categories, the rows the series."""
    return sets, rows, [[vals[r][j] for r in range(len(rows))] for j in range(len(sets))]


def _common_prefix(names: list[str]) -> str:
    words = [n.split() for n in names]
    out = []
    for parts in zip(*words, strict=False):
        if len(set(parts)) != 1:
            break
        out.append(parts[0])
    return " ".join(out)


def _grouped_series(g: Graph, rows, sets, vals, k: str, plot: str | None, offset: float = 0.0,
                    names: list[str] | None = None) -> None:
    """Interleaved series of one block of rows starting at category `offset`."""
    n, m = len(rows), max(len(sets), 1)
    pitch = 1 / (m + 0.5)
    fills = BARS_ONLY_FILLS if k == "grp_bars" else BAR_FILLS
    for j, name in enumerate(sets):
        fill = fills[j % len(fills)]
        sym = build.SYMBOLS[j % len(build.SYMBOLS)]
        xs = [offset + r + ((j - (m - 1) / 2) * pitch if k != "grp_stacked" else 0.0) for r in range(n)]
        col = [vals[r][j] for r in range(n)]
        label = names[j] if names else name
        if k in ("grp_box", "grp_floating", "grp_violin"):
            kind = {"grp_box": "box", "grp_floating": "floating", "grp_violin": "violin"}[k]
            centre = None if plot == "none" else ("mean" if plot == "mean" else "median")
            stats = [box_stats(v, plot if kind == "box" else "min_max", centre) for v in col]
            boxes = [b_ for b_, _ in stats]
            for b_, v in zip(boxes, col, strict=True):
                if b_ is not None and kind == "violin":
                    b_["kde"] = kde(v)
                    if plot == "median":
                        b_["q1"] = b_["q3"] = None
            s_ = Series(label, kind, xs, [b_["med"] if b_ else None for b_ in boxes],
                        [b_["lo"] if b_ else None for b_ in boxes], [b_["hi"] if b_ else None for b_ in boxes],
                        [o for _, o in stats], fill=fill, width=0.8 * pitch, box=boxes,
                        symbol_size=BOX_SYMBOL if kind == "box" else 4.0)
        elif k == "grp_stacked":
            s_ = Series(label, "bar", xs, [], fill=fill, width=0.6)
        elif k in ("grp_bars", "grp_bars_points"):
            sm = [summary(v, plot) for v in col]
            s_ = Series(label, "bar", xs, [c for c, _, _ in sm], [lo for _, lo, _ in sm], [hi for _, _, hi in sm],
                        col if k == "grp_bars_points" else [], fill=fill, width=0.8 * pitch,
                        spread_step=build.GROUPED_STEP)
        elif k in ("grp_means", "grp_means_line"):
            sm = [summary(v, plot) for v in col]
            s_ = Series(label, "points", xs, [c for c, _, _ in sm], [lo for _, lo, _ in sm], [hi for _, _, hi in sm],
                        symbol=sym, connect=k == "grp_means_line")
        else:  # interleaved scatter (grp_dots: no centre line)
            sm = [summary(v, "none" if k == "grp_dots" else plot) for v in col]
            s_ = Series(label, "scatter", xs, [c for c, _, _ in sm], [lo for _, lo, _ in sm], [hi for _, _, hi in sm],
                        col, symbol=sym, symbol_size=4.73, spread_step=2.6, width=0.8 * pitch)
        g.series.append(s_)
    if k == "grp_stacked":
        base = [0.0] * n
        for j, s_ in enumerate(g.series[-len(sets):]):
            tops = [base[r] + (summary(vals[r][j], plot or "mean")[0] or 0.0) for r in range(n)]
            s_.base, s_.ys = list(base), tops
            s_.border_width = 0.0  # Prism's stacked bars have no border (E-types)
            base = tops
        g.legend_reverse = True  # Prism lists a stack's parts top down
        g.x_as_columns, g.x_columns_length = True, STACKED_LENGTH  # one bar per row (E-types)
        for s_ in g.series[-len(sets):]:
            s_.width = TYPE_BAR_WIDTH


THREE_WAY = {"grp3_means_line": "grp_means_line", "grp3_bars": "grp_bars", "grp3_scatter": "grp_scatter",
             "grp3_scatter_side": "grp_scatter"}


def _separated(rows, sets, vals, k: str, plot: str | None, title: str) -> Graph:
    """Data sets side by side, each a block of every row (labelled by row,
    coloured by data set), one empty category between blocks, as Prism draws
    its separated grouped graphs (E-types)."""
    g = Graph(title=title, family="grouped", x_as_columns=True, x_columns_length=SEPARATED_LENGTH)
    n = len(rows)
    for j, name in enumerate(sets):
        before = len(g.series)
        _grouped_series(g, rows, [name], [[vals[r][j]] for r in range(n)], k, plot, float(j * (n + 1)), [name])
        for s_ in g.series[before:]:
            s_.fill = BAR_FILLS[j % len(BAR_FILLS)]
            s_.symbol = build.SYMBOLS[(j + 1) % len(build.SYMBOLS)]  # Prism's separated graphs start at the square
            if s_.kind in ("bar",) or s_.box is not None:
                s_.width = TYPE_BAR_WIDTH
        g.categories += rows + ([""] if j + 1 < len(sets) else [])
    return g


def _letters(j: int) -> str:
    """A, B, ..., Z, AA, AB, ... (Prism's column names)."""
    s = ""
    j += 1
    while j:
        j, r = divmod(j - 1, 26)
        s = chr(65 + r) + s
    return s


def _grouped(t: DataTable, gt: GraphType, plot: str | None, title: str) -> Graph:
    rows, sets, vals = cells(t)
    k = gt.key
    if k.startswith("grp_heat_"):
        centre = plot or "mean"
        mat = [[summary(v, centre)[0] if v else None for v in row] for row in vals]
        flat = [x for row in mat for x in row if x is not None]
        # Prism's default heat map: rows numbered, columns lettered, no title (E-heat)
        g = Graph(title="", family="grouped", legend=False)
        g.heatmap = {"values": mat, "rows": [str(r + 1) for r in range(len(rows))],
                     "cols": [_letters(j) for j in range(len(sets))], "cmap": k.removeprefix("grp_heat_"),
                     "lo": min(flat, default=0.0), "hi": max(flat, default=1.0)}
        return g
    if k.endswith("_sep"):  # Prism's separated graph: a block of the rows per data set, a gap between blocks
        return _separated(rows, sets, vals, k.removesuffix("_sep"), plot, title)
    if k in THREE_WAY:  # the data sets split in two halves, one panel each (the third factor)
        half = max(1, (len(sets) + 1) // 2)
        blocks = [list(range(half)), list(range(half, len(sets)))]
        g = Graph(title=title, family="grouped")
        base_k = THREE_WAY[k]
        n = len(rows)
        for p_, idx in enumerate(blocks):
            if not idx:
                continue
            names = [sets[j] for j in idx]
            prefix = _common_prefix(names)
            short = [nm[len(prefix):].strip() or nm for nm in names]
            sub_vals = [[vals[r][j] for j in idx] for r in range(n)]
            if k == "grp3_scatter_side":  # the data sets side by side, not interleaved: rows x sets slots
                for jj, j in enumerate(idx):
                    xs = [p_ * n + r + (jj - (len(idx) - 1) / 2) * 0.35 for r in range(n)]
                    col = [vals[r][j] for r in range(n)]
                    sm = [summary(v, plot) for v in col]
                    g.series.append(Series(short[jj], "scatter", xs, [c for c, _, _ in sm], [lo for _, lo, _ in sm],
                                           [hi for _, _, hi in sm], col, symbol=build.SYMBOLS[jj % 6],
                                           symbol_size=4.73, spread_step=2.6, width=0.3))
            else:
                _grouped_series(g, rows, [sets[j] for j in idx], sub_vals, base_k, plot, float(p_ * n), short)
            g.categories += rows
            g.panel_labels.append((p_ * n + (n - 1) / 2, prefix or f"Panel {p_ + 1}"))
        g.dividers = [n - 0.5] if len(blocks[1]) else []
        seen: set[str] = set()
        for s_ in g.series:  # one legend entry per pairing: the panels share them
            s_.in_legend = s_.title not in seen
            seen.add(s_.title)
        return g
    if k == "grp_rep_lines":  # each replicate (subcolumn) joined across the rows
        g = Graph(title=title, family="grouped", categories=rows,  # a legend entry per data set (Prism)
                  x_as_columns=True, x_columns_length=WIDE_LENGTH)
        for j, name in enumerate(sets):
            reps = max((len(vals[r][j]) for r in range(len(rows))), default=0)
            for q in range(reps):
                pts = [(float(r), vals[r][j][q]) for r in range(len(rows)) if q < len(vals[r][j])]
                g.series.append(Series(name, "points", [x for x, _ in pts], [y for _, y in pts],
                                       symbol=build.SYMBOLS[(j + 1) % 6], connect=True, symbol_size=5.0,
                                       in_legend=q == 0))
        return g
    g = Graph(title=title, family="grouped", categories=rows)
    _grouped_series(g, rows, sets, vals, k, plot)
    return g


def _contingency(t: DataTable, gt: GraphType, title: str) -> Graph:
    if gt.key in ("cont_bars", "cont_bars_sep"):  # Prism's grouped graphs of the counts (E-compare, E-types)
        return _grouped(t, BY_KEY["grp_bars" if gt.key == "cont_bars" else "grp_bars_sep"], "mean", title)
    rows, sets, vals = cells(t)
    counts = [[(v[0] if v else 0.0) for v in row] for row in vals]
    g = Graph(title=title, family="grouped", categories=rows)
    n, m = len(rows), max(len(sets), 1)
    if gt.key == "cont_bars_sep":  # grouped by outcome: the outcomes are the categories
        g.categories, n, m = sets, len(sets), max(len(rows), 1)
        pitch = 1 / (m + 0.5)
        for i, name in enumerate(rows):
            g.series.append(Series(name, "bar", [j + (i - (m - 1) / 2) * pitch for j in range(n)],
                                   [counts[i][j] for j in range(n)], fill=BAR_FILLS[i % len(BAR_FILLS)],
                                   width=0.8 * pitch))
        g.y_axis = Axis(title="Number of subjects")
        return g
    base = [0.0] * n
    for j, name in enumerate(sets):
        tops = []
        for r in range(n):
            total = sum(counts[r]) or 1.0
            c = counts[r][j] * (100.0 / total if gt.key == "cont_percent" else 1.0)
            tops.append(base[r] + c)
        g.series.append(Series(name, "bar", [float(r) for r in range(n)], tops, fill=BAR_FILLS[j % len(BAR_FILLS)],
                               width=0.6, base=list(base)))
        base = tops
    for s_ in g.series:
        s_.border_width = 0.0  # Prism's stacked bars have no border (E-types)
    g.legend_reverse = True  # Prism lists a stack's parts top down
    g.x_as_columns, g.x_columns_length = True, STACKED_LENGTH  # one bar per row (E-types)
    for s_ in g.series:
        s_.width = TYPE_BAR_WIDTH
    g.y_axis = Axis()  # Prism's stacked graphs of a contingency table have no Y title (E-types)
    if gt.key == "cont_percent":
        g.y_axis.min, g.y_axis.max, g.y_axis.tick = 0.0, 100.0, 25.0
    return g


def _survival(t: DataTable, gt: GraphType, options: dict, title: str) -> Graph:
    """Kaplan-Meier curves: staircases (with or without censor ticks, or a
    symbol at each step), points at each step joined, and the same as deaths
    (100 - survival, rising); in percent or as fractions."""
    g = build.survival_graph(t, title)
    fraction = options.get("scale") == "fraction"
    full = 1.0 if fraction else 100.0
    k = gt.key
    inverted = k.startswith("surv_inverted")
    shape = k.replace("surv_inverted_", "surv_")
    f = 0.01 if fraction else 1.0
    for j, s_ in enumerate(g.series):
        s_.ys = [None if y is None else (y * f if not inverted else full - y * f) for y in s_.ys]
        s_.marks = [(x, y * f if not inverted else full - y * f) for x, y in s_.marks]
        s_.symbol = build.SYMBOLS[j % 6]
        if shape == "surv_plain":
            s_.marks = []
        elif shape == "surv_steps_symbols":
            s_.sizes = []  # steps: a symbol at each step (refract.render.qt)
            s_.symbol_size = 5.0
        elif shape == "surv_points":
            xs, ys = [], []
            for x, y in zip(s_.xs, s_.ys, strict=False):  # one point per step: its value after the change
                if xs and x == xs[-1]:
                    ys[-1] = y
                else:
                    xs.append(x)
                    ys.append(y)
            s_.kind, s_.xs, s_.ys, s_.connect, s_.marks = "points", xs, ys, True, []
            s_.symbol_size = 5.0
    error = options.get("error")
    if error in ("se", "ci"):
        _survival_error(t, g, error, f, full, inverted, shape)
    if inverted:  # Prism's deaths graphs: X from 0 to the last major tick, without the survival padding (E-accept4)
        tmax = max((x for s_ in g.series for x in s_.xs if x is not None), default=1.0)
        from .autoscale import auto_range

        _lo, hi, tick = auto_range(0.0, tmax, style="bar")
        if g.x_axis.min is None and g.x_axis.max is None:
            g.x_axis.min, g.x_axis.max, g.x_axis.tick = 0.0, hi, tick
    if inverted and not fraction:  # Prism's own title of a deaths graph (E-types)
        g.y_axis.title = "Probability of Death"
    elif fraction:
        g.y_axis.title = "Fraction " + ("who died" if inverted else "surviving")
    if shape in ("surv_points", "surv_steps_symbols") or (inverted and not fraction):
        # Prism autoscales these to 110 % (E-types), deaths staircases too (E-accept4)
        g.y_axis.min = g.y_axis.max = g.y_axis.tick = None
    else:
        g.y_axis.min, g.y_axis.max, g.y_axis.tick = 0.0, full, full / 2
    return g


def _km_bounds(t: DataTable, j: int, error: str):
    """[(time, low, high)] of data set j's survival (fractions): S +- SE
    (Greenwood), or its 95 % CI (log(-log), as the survival analysis)."""
    import numpy as np

    from ..stats.survival import _ci_loglog, _subjects, kaplan_meier

    tt, ee = _subjects(t.x_values(), [v for v in t.values(j, 0)], 1, 0)
    out = []
    for u, _n, d, _c, s, gw in kaplan_meier(np.asarray(tt), np.asarray(ee)):
        if not d:
            continue
        if error == "se":
            se = s * math.sqrt(gw) if math.isfinite(gw) else 0.0
            out.append((u, max(0.0, s - se), min(1.0, s + se)))
        else:
            out.append((u, *_ci_loglog(s, gw, 1.959963984540054)))
    return out


def _survival_error(t: DataTable, g: Graph, error: str, f: float, full: float, inverted: bool, shape: str) -> None:
    """Error bars (points) or dotted bounds (staircases) of each curve."""
    k = 100.0 * f  # fraction -> the graph's unit

    def unit(v: float) -> float:
        return full - v * k if inverted else v * k

    bands = []
    for j, s_ in enumerate(list(g.series)):
        bounds = _km_bounds(t, j, error)
        if shape == "surv_points":
            by_t = {u: (lo, hi) for u, lo, hi in bounds}
            s_.err_lo = [unit(by_t[x][0]) if x in by_t else None for x in s_.xs]
            s_.err_hi = [unit(by_t[x][1]) if x in by_t else None for x in s_.xs]
            continue
        for side in (1, 2):  # the low and the high bound as dotted staircases
            xs, ys = [0.0], [full if not inverted else 0.0]
            for u, lo, hi in bounds:
                v = unit(lo if side == 1 else hi)
                xs += [u, u]
                ys += [ys[-1], v]
            if s_.xs:
                xs.append(max(s_.xs))
                ys.append(ys[-1])
            bands.append(Series("", "steps", xs, ys, color=s_.color, dash=True, in_legend=False))
    g.series += bands


def _parts(t: DataTable, gt: GraphType, title: str) -> Graph:
    if gt.key == "waffle":
        rows = t.row_titles.subcolumns[0] if t.row_titles else []
        vals = t.values(0, 0) if t.datasets else []
        parts = [((rows[r] if r < len(rows) else "") or f"Part {r + 1}", v, BAR_FILLS[r % len(BAR_FILLS)])
                 for r, v in enumerate(vals) if v is not None and v > 0]
        return Graph(title=title, family="column", legend=False, waffle={"parts": parts, "rows": 10, "cols": 10})
    if gt.key in ("pie", "donut", "pow_stacked"):  # Prism's stacked bar is its pie drawn as a bar (E-types)
        g = build.pie_defaults(build.pie_graph(t, title), t)
        if gt.key == "pow_stacked" and g.series:
            g.series[0].stacked_bar = True
        if gt.key == "donut" and g.series:
            from .native import DONUT_HOLE

            g.series[0].hole = DONUT_HOLE
        return g
    rows = t.row_titles.subcolumns[0] if t.row_titles else []
    vals = [v for v in t.values(0, 0)] if t.datasets else []
    total = sum(v for v in vals if v is not None) or 1.0
    g = Graph(title=title, family="column", categories=[t.datasets[0].title or ""] if t.datasets else [""])
    base = 0.0
    for r, v in enumerate(vals):
        if v is None:
            continue
        top = base + 100.0 * v / total
        g.series.append(Series((rows[r] if r < len(rows) else "") or f"Part {r + 1}", "bar", [0.0], [top],
                               fill=BAR_FILLS[r % len(BAR_FILLS)], width=0.6, base=[base]))
        base = top
    g.y_axis = Axis(title="Percent of total", min=0.0, max=100.0, tick=25.0)
    g.legend = True
    return g


def _nested(t: DataTable, gt: GraphType, plot: str | None, title: str) -> Graph:
    """Each subgroup (subcolumn) at its own position, the groups side by side
    with a line between them."""
    g = Graph(title=title, family="column", legend=True, legend_on_columns=True,  # Prism: with a legend
              x_columns_length=WIDE_LENGTH)
    if gt.key in ("nest_scatter", "nest_box", "nest_floating"):
        g.y_autoscale = "xy"  # Prism's nested scatter, box, floating: 0 only by the XY ratio rule (E-types: 4..9)
    x = 0.0
    k = gt.key
    sub_titles = t.subcolumn_titles
    for j, ds in enumerate(t.datasets):
        fill = BAR_FILLS[j % len(BAR_FILLS)]
        sym = build.SYMBOLS[(j + 1) % len(build.SYMBOLS)]  # Prism's nested graphs start at the square
        xs, ys, lo, hi, pts, boxes = [], [], [], [], [], []
        for s in range(len(ds.subcolumns)):
            vals = _vals(t.values(j, s))
            name = ""
            subs = sub_titles.subcolumns if sub_titles is not None else []
            row = subs[0] if subs else []  # Prism labels every group with the first title row (E-types)
            if s < len(row):
                name = row[s]
            g.categories.append(name or f"{t.datasets[0].title or ''} {s + 1}".strip())  # untitled: as Prism
            xs.append(x)
            if k in ("nest_box", "nest_floating", "nest_violin"):
                centre = None if plot == "none" else ("mean" if plot == "mean" else "median")
                b, out = box_stats(vals, plot if k == "nest_box" else "min_max", centre)
                if b is not None and k == "nest_violin":
                    b["kde"] = kde(vals)
                    if plot == "median":
                        b["q1"] = b["q3"] = None
                boxes.append(b)
                ys.append(b["med"] if b else None)
                lo.append(b["lo"] if b else None)
                hi.append(b["hi"] if b else None)
                pts.append(out)
            else:
                c, a, z = summary(vals, plot)
                ys.append(c)
                lo.append(a)
                hi.append(z)
                pts.append(vals)
            x += 1.0
        if k in ("nest_box", "nest_floating", "nest_violin"):
            kind = {"nest_box": "box", "nest_floating": "floating", "nest_violin": "violin"}[k]
            s_ = Series(ds.title or "", kind, xs, ys, lo, hi, pts if kind == "box" else [], fill=fill, width=0.6,
                        box=boxes, symbol_size=4.0)
        elif k in ("nest_bars", "nest_scatter_bar"):
            s_ = Series(ds.title or "", "bar", xs, ys, lo if k == "nest_bars" else [], hi if k == "nest_bars" else [],
                        pts if k == "nest_scatter_bar" else [], fill=fill, width=0.6, spread_step=3.0, symbol_size=4.0)
        else:
            s_ = Series(ds.title or "", "scatter", xs, ys, lo, hi, pts, symbol=sym, symbol_size=6.32, spread_step=3.0)
        g.series.append(s_)
        if j < len(t.datasets) - 1:
            g.dividers.append(x - 0.5)
    return g


def variables(t: DataTable) -> list[tuple[str, bool]]:
    """A Multiple-variables table's variables: (name, numeric)."""
    out = []
    for j, ds in enumerate(t.datasets):
        vals = t.values(j, 0)
        num = sum(1 for v in vals if v is not None)
        text = sum(1 for c in (ds.subcolumns[0] if ds.subcolumns else []) if c.strip()) - num
        out.append((ds.title or f"Variable {j + 1}", num > 0 and text <= 0))
    return out


MV_AS_COLUMN = {"mv_scatter_cat": "col_scatter", "mv_means_cat": "col_means", "mv_bars_cat": "col_scatter_bar",
                "mv_box_cat": "col_box", "mv_violin_cat": "col_violin", "mv_bar_cat": "col_bar",
                "mv_before_after": "col_scatter", "mv_before_after_bars": "col_bar"}


BUBBLE_SMALLEST, BUBBLE_LARGEST = 4.0, 18.0  # symbol sizes (pt) of the smallest value and at most


def bubble_size(v: float, lo: float, hi: float) -> float:
    """A bubble's diameter as Prism draws it (E-mv: its area in proportion to
    the value, the smallest value BUBBLE_SMALLEST, at most BUBBLE_LARGEST);
    with values not all positive, spread over the range by area."""
    if lo > 0 and v > 0:
        return min(BUBBLE_LARGEST, BUBBLE_SMALLEST * math.sqrt(v / lo))
    return BUBBLE_SMALLEST + (BUBBLE_LARGEST - BUBBLE_SMALLEST) * math.sqrt(max(0.0, v - lo) / ((hi - lo) or 1.0))


def _multivariable(t: DataTable, gt: GraphType, options: dict, title: str, plot: str | None = None) -> Graph:
    names = [n for n, _ in variables(t)]
    if gt.key == "mv_heat":  # observations down, numeric variables across, each as z scores
        cols = [i for i, (_, numeric) in enumerate(variables(t)) if numeric]
        n = max((len(t.values(i, 0)) for i in cols), default=0)
        mat = [[None] * len(cols) for _ in range(n)]
        for c, i in enumerate(cols):
            v = t.values(i, 0)
            ok = _vals(v)
            m = sum(ok) / len(ok) if ok else 0.0
            sd = math.sqrt(sum((x - m) ** 2 for x in ok) / (len(ok) - 1)) if len(ok) > 1 else 1.0
            for r in range(n):
                if r < len(v) and v[r] is not None:
                    mat[r][c] = (v[r] - m) / (sd or 1.0)
        flat = [x for row in mat for x in row if x is not None]
        g = Graph(title=title, family="grouped", legend=False)
        g.heatmap = {"values": mat, "rows": [str(r + 1) for r in range(n)], "cols": [names[i] for i in cols],
                     "cmap": "viridis", "lo": min(flat, default=-1.0), "hi": max(flat, default=1.0)}
        return g
    if gt.key in MV_AS_COLUMN:  # Y (a number) grouped by X (a category)
        cats = [i for i, (_, numeric) in enumerate(variables(t)) if not numeric]
        nums = [i for i, (_, numeric) in enumerate(variables(t)) if numeric]
        xi = names.index(options["x"]) if options.get("x") in names and names.index(options["x"]) in cats else \
            (cats[0] if cats else 0)  # the categories: a text variable
        yi = names.index(options["y"]) if options.get("y") in names and names.index(options["y"]) in nums else \
            (nums[0] if nums else 0)
        keys = t.datasets[xi].subcolumns[0] if t.datasets[xi].subcolumns else []
        ys = t.values(yi, 0)
        order: list[str] = []
        for c in keys:
            if c.strip() and c not in order:
                order.append(c)
        gs = [(c, [ys[r] for r in range(min(len(keys), len(ys))) if keys[r] == c and ys[r] is not None]) for c in order]
        before_after = gt.key.startswith("mv_before_after")
        g = _column(t, BY_KEY[MV_AS_COLUMN[gt.key]], "mean" if before_after else plot, title, gs)
        g.x_axis.title, g.y_axis.title = names[xi], names[yi]
        if before_after:  # each group's centre per category, joined across the categories
            if gt.key == "mv_before_after":
                g.series = []
            li = names.index(options["lines"]) if options.get("lines") in names else -1
            groups_of = (t.datasets[li].subcolumns[0] if li >= 0 and t.datasets[li].subcolumns else
                         [""] * len(keys))
            lines: list[str] = []
            for c in groups_of:
                if c not in lines:
                    lines.append(c)
            for q, grp in enumerate(lines):
                pts = []
                for k_, cat in enumerate(order):
                    v = [ys[r] for r in range(min(len(keys), len(ys)))
                         if keys[r] == cat and (li < 0 or groups_of[r] == grp) and ys[r] is not None]
                    c_ = summary(v, plot or "mean")[0]
                    if c_ is not None:
                        pts.append((float(k_), c_))
                g.series.append(Series(grp or names[yi], "points", [x for x, _ in pts], [y for _, y in pts],
                                       symbol=build.SYMBOLS[q % 6], connect=True, symbol_size=5.5))
            g.legend = li >= 0
        return g
    nums = [i for i, (_, numeric) in enumerate(variables(t)) if numeric]

    def pick(key, default):
        v = options.get(key)
        return names.index(v) if v in names else default

    xi = pick("x", nums[0] if nums else 0)
    yi = pick("y", nums[1] if len(nums) > 1 else xi)
    ci = pick("color", -1) if options.get("color") else -1
    si = pick("size", -1) if options.get("size") and gt.key == "mv_bubble" else -1
    xs, ys = t.values(xi, 0), t.values(yi, 0)
    cats = ([c for c in (t.datasets[ci].subcolumns[0] if t.datasets[ci].subcolumns else [])]
            if ci >= 0 else [""] * len(xs))
    sizes = t.values(si, 0) if si >= 0 else None
    smin = min((v for v in (sizes or []) if v is not None), default=0.0)
    smax = max((v for v in (sizes or []) if v is not None), default=1.0)
    if smin > 0 or si < 0:  # drawn from the settings it is written to Prism with (refract.formats.mv_writer)
        from ..formats import mv_writer as MW
        from . import mv_prism

        numeric = ci >= 0 and variables(t)[ci][1]
        order = list(dict.fromkeys(cats)) if ci >= 0 and not numeric else []
        fills = {c: BAR_FILLS[k % len(BAR_FILLS)] for k, c in enumerate(order)}
        fig = MW.figure(t, ci if ci >= 0 else None, si if si >= 0 else None, fills, (0, 0, 0, 255),
                        (BUBBLE_SMALLEST, BUBBLE_LARGEST) if si >= 0 else (6.0, 0.0), numeric, ref=lambda j: j)
        spec = {"xVariables": [xi], "yVariables": [yi], "gdoTypes": {"defaults": ["symbols"]},
                "gdoSettings": {"symbols": fig}}
        g = mv_prism.read_table(t, spec, title)
        g.x_axis.title, g.y_axis.title = (names[xi], names[yi]) if names else ("", "")
        return g
    g = Graph(title=title, family="xy", legend=ci >= 0)
    g.x_axis, g.y_axis = Axis(title=names[xi] if names else ""), Axis(title=names[yi] if names else "")
    order: list[str] = []
    for c in cats:
        if c not in order:
            order.append(c)
    for k, cat in enumerate(order):
        s = Series(cat if ci >= 0 else (names[yi] if names else ""), "points", [], [], fill=BAR_FILLS[k % len(BAR_FILLS)],
                   symbol="circle", symbol_size=6.0)
        s.color = s.point_color = BAR_FILLS[k % len(BAR_FILLS)] if ci >= 0 else (0, 0, 0, 255)
        s.sizes = [] if sizes is not None else None
        for r in range(min(len(xs), len(ys))):
            if xs[r] is None or ys[r] is None or (r < len(cats) and cats[r] != cat):
                continue
            s.xs.append(xs[r])
            s.ys.append(ys[r])
            if sizes is not None:
                v = sizes[r] if r < len(sizes) and sizes[r] is not None else smin
                s.sizes.append(bubble_size(v, smin, smax))
        g.series.append(s)
    return g


# Prism's default fills of these types' first data set: black, not the interleaved bars' 50 % black (E-types)
BLACK_FIRST = frozenset({"grp_bars_sep", "grp_bars_points_sep", "grp_stacked", "grp_bars_h", "cont_bars_sep",
                         "cont_stacked", "cont_percent", "cont_bars_h", "grp_stacked_h", "cont_stacked_h",
                         "grp_bars_sep_h"})
# the value axis of these horizontal types: Prism's own graphs of them are 3 in long (E-types round 2), not
# the upright type's X length
H_VALUE_LENGTH = {"col_floating_h": 216.0, "grp_stacked_h": 216.0, "cont_stacked_h": 216.0}


def make(t: DataTable, gt: GraphType, plot: str | None, title: str, options: dict | None = None) -> Graph:
    """The graph of table t as type gt (its family may differ from the
    table's kind: an XY table drawn as columns, ...)."""
    g = _make(t, gt, plot, title, options)
    if gt.key in BLACK_FIRST:
        bars = [s for s in g.series if s.kind == "bar"]
        names = list(dict.fromkeys(s.title for s in bars))
        for s in bars:
            if names and s.title == names[0]:
                s.fill = (0, 0, 0, 255)
    return g


def _make(t: DataTable, gt: GraphType, plot: str | None, title: str, options: dict | None = None) -> Graph:
    options = options or {}
    if gt.key.endswith("_h") and gt.key[:-2] in BY_KEY:  # on its side
        g = _make(t, BY_KEY[gt.key[:-2]], plot, title, options)
        g.horizontal = True
        if gt.key in H_VALUE_LENGTH and g.y_length is None:
            g.y_length = H_VALUE_LENGTH[gt.key]
        return g
    if gt.family == "column":
        g = _column(t, gt, plot, title)
    elif gt.family == "grouped":
        g = _grouped(t, gt, plot, title)
    elif gt.family == "contingency":
        g = _contingency(t, gt, title)
    elif gt.family == "survival":
        g = _survival(t, gt, options, title)
    elif gt.family == "parts_of_whole":
        g = _parts(t, gt, title)
    elif gt.family == "nested":
        g = _nested(t, gt, plot, title)
    elif gt.family == "multivariable":
        g = _multivariable(t, gt, options, title, plot)
    else:  # xy
        g = build.from_table(t, "none", title=title)
        g.family = "xy"
        rows_x = t.x_values()
        for j, s in enumerate(g.series):
            xs, ys, lo, hi, pts = [], [], [], [], []
            for r, x in enumerate(rows_x):
                if x is None:
                    continue
                vals = _vals([t.values(j, k)[r] if r < len(t.values(j, k)) else None
                              for k in range(t.subcolumns_per_dataset)]) \
                    if t.data_format in ("y_replicates", "y_single") else [build.cell(t, j, r)[0]] \
                    if build.cell(t, j, r)[0] is not None else []
                if not vals:
                    continue
                if t.data_format in ("y_replicates", "y_single"):
                    c, a, z = summary(vals, plot)
                else:
                    c, a, z = build.cell(t, j, r, "sd" if (plot or "mean_sd") != "mean" else "none")[:3]
                xs.append(float(x))
                ys.append(c)
                lo.append(a)
                hi.append(z)
                pts.append(vals)
            s.xs, s.ys, s.err_lo, s.err_hi = xs, ys, lo, hi
            if gt.key in ("xy_replicates", "xy_replicates_line"):
                s.kind, s.points, s.spread_step = "scatter", pts, 0.0
                s.err_lo, s.err_hi = [], []
                s.width = 0.0
                if gt.key == "xy_replicates_line":
                    s.connect = True  # a line through the means, no centre marks
            if gt.key == "xy_bars":  # bars at the X values, the data sets side by side
                s.kind = "bar"
                s.fill = BAR_FILLS[j % len(BAR_FILLS)]
            if gt.key in ("xy_points_line", "xy_line", "xy_area"):
                s.connect = True
            if gt.key == "xy_line":
                s.symbol = "none"
            if gt.key == "xy_area":  # Prism: the symbols kept, the area in the data set's colour
                s.fill_area = True
                s.fill = s.color
        if gt.key == "xy_bars":  # Prism: every data set's bar at the X itself, the first on top (E-types)
            xs_all = sorted({x for s in g.series for x in s.xs})
            gap = min((b - a for a, b in itertools.pairwise(xs_all)), default=1.0) or 1.0
            for j, s in enumerate(g.series):
                s.width = 0.45 * gap
                s.fill = (0, 0, 0, 255) if j == 0 else BAR_FILLS[1]
            g.series.reverse()
            g.legend_reverse = True
        if gt.key == "xy_rep_lines":  # each subcolumn joined on its own
            out = []
            for j, ds in enumerate(t.datasets):
                for q in range(t.subcolumns_per_dataset if t.data_format in ("y_replicates", "y_single") else 1):
                    pts = [(float(x), t.values(j, q)[r]) for r, x in enumerate(rows_x)
                           if x is not None and r < len(t.values(j, q)) and t.values(j, q)[r] is not None]
                    out.append(Series(ds.title or "", "points", [x for x, _ in pts], [y for _, y in pts],
                                      symbol=build.SYMBOLS[(j + 1) % 6], connect=True, symbol_size=5.0,
                                      in_legend=q == 0))  # a legend entry per data set, as Prism
            g.series = out
        if gt.key in ("xy_replicates", "xy_replicates_line", "xy_rep_lines"):  # Prism starts these at the square
            for j, s in enumerate(g.series):
                if gt.key != "xy_rep_lines":
                    s.symbol = build.SYMBOLS[(j + 1) % 6]
        if gt.key in ("xy_replicates", "xy_replicates_line"):
            for s in g.series:  # no centre line: the points themselves
                s.ys = [None if gt.key == "xy_replicates" else y for y in s.ys]
    return g
