"""Analyses whose output is a data table: Normalize (NORMALIZE), Transform
(TRNSFORM), Remove baseline (REMOVE_BASELINE), Row statistics
(ROW_STATISTICS) and Transpose (TRANSPOSE), with Prism's parameter names
(verified against Prism 11.1: tools/table_parity.py).

Tables in and out are dicts {"x": [values] | None, "rows": [titles] | None,
"title": table title, "sets": [{"title", "subs": [[value per row] per
subcolumn]}]}; the output adds "format" (Prism's data format of the result
table). Values are floats, None for a blank cell.
"""

from __future__ import annotations

import math

import numpy as np
from scipy import stats


def _ok(v) -> bool:
    return v is not None and isinstance(v, (int, float)) and math.isfinite(v)


def _n_rows(table) -> int:
    return max([len(s) for d in table["sets"] for s in d["subs"]] + [len(table.get("x") or [])] + [0])


def _cell(table, d, r) -> list[float]:
    return [s[r] for s in table["sets"][d]["subs"] if r < len(s) and _ok(s[r])]


def _out(table, fmt, sets, rows=None, x=None) -> dict:
    return {"format": fmt, "x": table.get("x") if x is None else x, "rows": table.get("rows") if rows is None else rows,
            "sets": sets}


# ---------------------------------------------------------------- normalize
def normalize(params: dict, table: dict) -> dict:
    """Per data set: 0 % / 100 % from the row means (data.handleReplicatesAs
    AVERAGE): SMALLEST | FIRST | CUSTOM, and LARGEST | LAST | SUM_OF_VALUES |
    CUSTOM; every value becomes 100 (y - v0) / (v100 - v0) (FRACTIONS: no
    factor 100). A data set whose 0 % and 100 % coincide is left unchanged."""
    calc = params.get("calc", {})
    frac = params.get("options", {}).get("reportResultsAs", "PERCENTAGES") == "FRACTIONS"
    nr = _n_rows(table)
    out = []
    for d, ds in enumerate(table["sets"]):
        means = [float(np.mean(c)) if (c := _cell(table, d, r)) else None for r in range(nr)]
        avail = [m for m in means if m is not None]
        z, h = calc.get("value_0", {}), calc.get("value_100", {})

        def pick(spec, kind, avail=avail, d=d):
            how = spec.get("defineAs")
            if how == "CUSTOM":
                v = spec.get("customValue")
                return float(v) if isinstance(v, (int, float)) else None
            if not avail:
                return None
            if how == "SMALLEST":
                return min(avail)
            if how == "LARGEST":
                return max(avail)
            if how == "FIRST":
                return avail[0]
            if how == "LAST":
                return avail[-1]
            if how == "SUM_OF_VALUES":
                return float(sum(avail))  # sum of the row means (verified)
            raise NotImplementedError(f"normalize {kind} {how}")

        v0, v1 = pick(z, "0%"), pick(h, "100%")
        if (v0 is not None and v1 is not None and v1 < v0
                and "CUSTOM" not in (z.get("defineAs"), h.get("defineAs"))):  # FIRST > LAST: Prism swaps (verified)
            v0, v1 = v1, v0
        if v0 is None or v1 is None:
            subs = [[None] * len(s) for s in ds["subs"]]
        elif v1 == v0:
            subs = [list(s) for s in ds["subs"]]
        else:
            k = 1.0 if frac else 100.0
            subs = [[k * (v - v0) / (v1 - v0) if _ok(v) else None for v in s] for s in ds["subs"]]
        out.append({"title": ds["title"], "subs": subs})
    return _out(table, "y_replicates" if len(table["sets"][0]["subs"]) > 1 else "y_single", out)


# ---------------------------------------------------------------- transform
def _fn(name: str):
    """Prism's standard transform functions (Y or X), with constant K and X."""
    from scipy.special import logit

    f = {
        "*K": lambda v, k, x: v * k, "+K": lambda v, k, x: v + k, "-K": lambda v, k, x: v - k,
        "/K": lambda v, k, x: v / k, "^2": lambda v, k, x: v * v, "^K": lambda v, k, x: v ** k,
        "LOG10": lambda v, k, x: math.log10(v), "LN": lambda v, k, x: math.log(v), "10^": lambda v, k, x: 10.0 ** v,
        "EXP": lambda v, k, x: math.exp(v), "1/": lambda v, k, x: 1.0 / v, "SQRT": lambda v, k, x: math.sqrt(v),
        "LOGIT": lambda v, k, x: float(logit(v)), "PROBIT": lambda v, k, x: float(stats.norm.ppf(v)) + 5.0,  # classic probit (verified)
        "ABS": lambda v, k, x: abs(v), "*X": lambda v, k, x: v * x, "/X": lambda v, k, x: v / x,
        "-X": lambda v, k, x: v - x, "+X": lambda v, k, x: v + x, "K-": lambda v, k, x: k - v,
        "K/": lambda v, k, x: k / v, "LOG2": lambda v, k, x: math.log2(v), "2^": lambda v, k, x: 2.0 ** v,
    }
    s = name.replace(" ", "")
    for var in ("Y", "X"):
        if s.startswith(var) and s[1:] in f and s != var:
            return f[s[1:]]
        if s.endswith(var) and s[:-1] in f:
            return f[s[:-1]]
        if s.startswith(("LOG10(", "LN(", "EXP(", "SQRT(", "LOGIT(", "PROBIT(", "ABS(", "LOG2(")) and s.endswith(f"({var})"):
            return f[s.split("(")[0]]
    raise NotImplementedError(f"transform function {name}")


def _apply(fn, v, k, x):
    if not _ok(v):
        return None
    try:
        r = fn(v, k, x)
    except (ValueError, ZeroDivisionError, OverflowError, TypeError):
        return None
    if r is None or isinstance(r, complex):
        return None
    return float(r) if math.isfinite(r) else None


def transform(params: dict, table: dict) -> dict:
    """calc.transformType STANDARD: xTransform / yTransform (each value; K
    from k or, when kSameForAll is false, kList per data set)."""
    calc = params.get("calc", {})
    if calc.get("transformType", "STANDARD") != "STANDARD":
        raise NotImplementedError(f"transform type {calc.get('transformType')}")
    sf = calc.get("standardFunction", {})
    if sf.get("interchangeXY"):
        raise NotImplementedError("interchange X and Y")
    xt, yt = sf.get("xTransform", {}), sf.get("yTransform", {})
    x = table.get("x")
    if x is not None and xt.get("enabled"):
        fx = _fn(xt.get("function", "X"))
        kx = xt.get("k")
        x = [_apply(fx, v, kx if isinstance(kx, (int, float)) else math.nan, None) for v in x]
    sets = []
    for d, ds in enumerate(table["sets"]):
        subs = [list(s) for s in ds["subs"]]
        if yt.get("enabled"):
            fy = _fn(yt.get("function", "Y"))
            k = yt.get("k")
            if not yt.get("kSameForAll", True) and d < len(yt.get("kList", [])):
                k = yt["kList"][d]
            k = k if isinstance(k, (int, float)) else math.nan
            xs = table.get("x") or [None] * _n_rows(table)
            subs = [[_apply(fy, v, k, xs[r] if r < len(xs) and _ok(xs[r]) else math.nan) for r, v in enumerate(s)]
                    for s in subs]
        sets.append({"title": ds["title"], "subs": subs})
    return _out(table, "y_replicates" if len(table["sets"][0]["subs"]) > 1 else "y_single", sets, x=x)


# ---------------------------------------------------------- remove baseline
_EXPR = {  # calc.expression -> (title template, value(a, b), SE(ma, sa, mb, sb))
    "DIFFERENCE": ("{a} - {b}", lambda a, b: a - b, lambda ma, sa, mb, sb: math.sqrt(sa * sa + sb * sb)),
    "RATIO": ("{a} / {b}", lambda a, b: a / b,
              lambda ma, sa, mb, sb: abs(ma / mb) * math.sqrt((sa / ma) ** 2 + (sb / mb) ** 2)),
    "PERCENT": ("100 * ({a} / {b})", lambda a, b: 100 * a / b,
                lambda ma, sa, mb, sb: 100 * abs(ma / mb) * math.sqrt((sa / ma) ** 2 + (sb / mb) ** 2)),
    "PERCENTAGE_DIFFERENCE": ("100 * (({a} - {b}) / {b})", lambda a, b: 100 * (a - b) / b,
                              lambda ma, sa, mb, sb: 100 * abs(ma / mb) * math.sqrt((sa / ma) ** 2 + (sb / mb) ** 2)),
}


def _mean_se(vals):
    if not vals:
        return None, None
    m = float(np.mean(vals))
    se = float(np.std(vals, ddof=1) / math.sqrt(len(vals))) if len(vals) > 1 else 0.0  # one value: SE 0 (verified)
    return m, se


def remove_baseline(params: dict, table: dict) -> dict:
    """Baseline column (data.columnBaseline.type EVERY_OTHER_COLUMN_2_4_6:
    A vs B, C vs D, ...; _1_3_5: B vs A, ...) or baseline row (FIRST_ROW /
    LAST_ROW); calc.expression DIFFERENCE | RATIO | PERCENT |
    PERCENTAGE_DIFFERENCE. treatSubcolumnsAs MEANS: mean with SE (delta
    method), REPLICATES: replicate by replicate."""
    data = params.get("data", {})
    expr = params.get("calc", {}).get("expression", "RATIO")
    if expr not in _EXPR:
        raise NotImplementedError(f"baseline expression {expr}")
    tmpl, fval, fse = _EXPR[expr]
    single = all(len(d["subs"]) == 1 for d in table["sets"])
    means_mode = data.get("treatSubcolumnsAs", "MEANS") == "MEANS" and not single
    nr = _n_rows(table)

    def safe(f, *a):
        try:
            v = f(*a)
        except (ZeroDivisionError, TypeError, ValueError):
            return None
        return float(v) if v is not None and math.isfinite(v) else None

    def combine(a_vals, b_vals, a_subs, b_subs, r, rb):
        """-> list of subcolumn values for one result cell."""
        if means_mode:
            ma, sa = _mean_se(a_vals)
            mb, sb = _mean_se(b_vals)
            if ma is None or mb is None:
                return [None, None]
            v = safe(fval, ma, mb)
            se = safe(fse, ma, sa, mb, sb) if sa is not None and sb is not None else None
            return [v, se]
        # replicates: each replicate of the data set against the baseline's mean (verified)
        mb = float(np.mean(b_vals)) if b_vals else None
        return [safe(fval, sa_[r], mb) if mb is not None and r < len(sa_) and _ok(sa_[r]) else None for sa_ in a_subs]

    sets = []
    if data.get("baselineType", "BASELINE_COLUMN") == "BASELINE_COLUMN":
        cb = data.get("columnBaseline", {}).get("type", "EVERY_OTHER_COLUMN_2_4_6")
        if cb not in ("EVERY_OTHER_COLUMN_2_4_6", "EVERY_OTHER_COLUMN_1_3_5"):
            raise NotImplementedError(f"column baseline {cb}")
        n = len(table["sets"])
        for i in range(0, n - 1, 2):
            ai, bi = (i, i + 1) if cb == "EVERY_OTHER_COLUMN_2_4_6" else (i + 1, i)
            a, b = table["sets"][ai], table["sets"][bi]
            cells = [combine(_cell(table, ai, r), _cell(table, bi, r), a["subs"], b["subs"], r, r) for r in range(nr)]
            subs = [[c[s] for c in cells] for s in range(len(cells[0]))] if cells else []
            sets.append({"title": tmpl.format(a=a["title"], b=b["title"]), "subs": subs})
        rows, x = table.get("rows"), table.get("x")
        if rows:  # a row with no result loses its title (verified)
            rows = ["" if all(sub[r] is None for st in sets for sub in st["subs"][:1]) else t for r, t in enumerate(rows)]
    else:
        which = data.get("rowBaseline", {}).get("type", "FIRST_ROW")
        if which not in ("FIRST_ROW", "LAST_ROW"):
            raise NotImplementedError(f"row baseline {which}")
        rb = 0 if which == "FIRST_ROW" else nr - 1
        remove = params.get("options", {}).get("removeBaselineFromResults", True)
        for d, ds in enumerate(table["sets"]):
            cells = []
            for r in range(nr):
                if remove and r == rb:
                    cells.append([None, None] if means_mode else [None] * len(ds["subs"]))
                else:
                    cells.append(combine(_cell(table, d, r), _cell(table, d, rb), ds["subs"], ds["subs"], r, rb))
            subs = [[c[s] for c in cells] for s in range(len(cells[0]))]
            sets.append({"title": ds["title"], "subs": subs})
        rows, x = table.get("rows"), table.get("x")
        if remove and which == "LAST_ROW":  # the last row is dropped; the first row stays, blank (verified)
            sets = [{"title": s["title"], "subs": [sub[:-1] for sub in s["subs"]]} for s in sets]
            rows = rows[:-1] if rows else rows
            x = x[:-1] if x else x
        elif remove:
            if rows:
                rows = ["" if r == rb else t for r, t in enumerate(rows)]
            if x:
                x = [None if r == rb else v for r, v in enumerate(x)]
    return _out(table, "y_se" if means_mode else "y_single" if single else "y_replicates", sets, rows=rows, x=x)


# ------------------------------------------------------------ row statistics
_ROW_FORMAT = {"MEAN_WITH_SD": "y_sd_n", "MEAN_WITH_SEM": "y_se_n", "MEAN_WITH_CV": "y_cv_n",
               "MEAN_WITH_CI": "y_high_low", "SUM": "y_single", "MEDIAN": "y_single",
               "MEDIAN_WITH_RANGE": "y_high_low", "MEDIAN_WITH_QUARTILES": "y_high_low",
               "MEDIAN_WITH_PERCENTILES": "y_high_low"}


def _row_stat(vals, what, level, pct):
    if not vals:
        return None
    a = np.asarray(vals, float)
    n = len(a)
    m = float(a.mean())
    sd = float(a.std(ddof=1)) if n > 1 else 0.0  # one value: SD 0 (verified)
    if what in ("MEAN_WITH_SD", "MEAN_WITH_CV"):  # %CV tables store the SD (verified)
        return [m, sd, float(n)]
    if what == "MEAN_WITH_SEM":
        return [m, sd / math.sqrt(n) if sd is not None else None, float(n)]
    if what == "MEAN_WITH_CI":
        if n < 2:
            return [m, None, None]
        h = float(stats.t.ppf(1 - (1 - level / 100) / 2, n - 1) * sd / math.sqrt(n))
        return [m, h, h]
    if what == "SUM":
        return [float(a.sum())]
    med = float(np.median(a))
    if what == "MEDIAN":
        return [med]
    if what == "MEDIAN_WITH_RANGE":
        return [med, float(a.max()) - med, med - float(a.min())]
    from .descriptive import percentile  # Prism's percentile rule

    srt = np.sort(a)
    if what == "MEDIAN_WITH_QUARTILES":
        return [med, percentile(srt, 0.75) - med, med - percentile(srt, 0.25)]
    if what == "MEDIAN_WITH_PERCENTILES":
        lo = (1 - pct / 100) / 2
        return [med, percentile(srt, 1 - lo) - med, med - percentile(srt, lo)]
    raise NotImplementedError(f"row statistic {what}")


def row_statistics(params: dict, table: dict) -> dict:
    """data.scope TABLE: per row, each data set's mean of its replicates,
    then the statistic across data sets; COLUMN: per data set, across its
    replicates."""
    what = params.get("calc", {}).get("statistics", "MEAN_WITH_SD")
    if what not in _ROW_FORMAT:
        raise NotImplementedError(f"row statistic {what}")
    opt = params.get("options", {})
    level, pct = opt.get("confidenceLevel", 95.0), opt.get("percentileLevel", 90.0)
    nr = _n_rows(table)
    width = {"y_sd_n": 3, "y_se_n": 3, "y_cv_n": 3, "y_high_low": 3, "y_single": 1}[_ROW_FORMAT[what]]
    groups = []
    single = all(len(d["subs"]) == 1 for d in table["sets"])
    if params.get("data", {}).get("scope", "TABLE") == "TABLE" or single:  # no replicates: whole table (verified)
        vals = [[float(np.mean(c)) for d in range(len(table["sets"])) if (c := _cell(table, d, r))] for r in range(nr)]
        groups.append((table.get("title", ""), vals))
    else:
        for d, ds in enumerate(table["sets"]):
            groups.append((ds["title"], [_cell(table, d, r) for r in range(nr)]))
    sets = []
    for title, vals in groups:
        cells = [_row_stat(v, what, level, pct) or [None] * width for v in vals]
        sets.append({"title": title, "subs": [[c[s] for c in cells] for s in range(width)]})
    return _out(table, _ROW_FORMAT[what], sets)


# ------------------------------------------------------------------ transpose
def transpose(params: dict, table: dict) -> dict:
    """XY_TABLE result: each original row becomes a data set (titled with its
    X value or row title), each original data set a row; replicates stay
    subcolumns. X of the result: the original data-set titles as numbers
    (0 when not numeric)."""
    tt = params.get("calc", {}).get("transposedTable", {})
    if tt.get("type", "XY_TABLE") != "XY_TABLE":
        raise NotImplementedError(f"transposed table {tt.get('type')}")
    nr = _n_rows(table)
    reps = max(len(d["subs"]) for d in table["sets"])
    xs = table.get("x")
    rts = table.get("rows")
    sets = []
    for r in range(nr):
        if tt.get("columnTitles", "X_VALUES_OF_ORIGINAL_TABLE") == "X_VALUES_OF_ORIGINAL_TABLE" and xs:
            v = xs[r]
            title = ("" if v is None else (str(int(v)) if float(v).is_integer() else repr(float(v))))
        else:
            title = rts[r] if rts and r < len(rts) else ""
        subs = [[d["subs"][s][r] if s < len(d["subs"]) and r < len(d["subs"][s]) else None for d in table["sets"]]
                for s in range(reps)]
        sets.append({"title": title, "subs": subs})

    def as_num(t):
        try:
            return float(t)
        except (TypeError, ValueError):
            return 0.0

    x = [as_num(d["title"]) for d in table["sets"]]
    return {"format": "y_replicates" if reps > 1 else "y_single", "x": x, "rows": None, "sets": sets}


ANALYSES = {"NORMALIZE": normalize, "TRNSFORM": transform, "REMOVE_BASELINE": remove_baseline,
            "ROW_STATISTICS": row_statistics, "TRANSPOSE": transpose}


# ---------------------------------------------------------- fraction of total
def _g4(v) -> str:
    """Prism's text summary: four significant digits, trailing zeros kept, halves rounded up."""
    from decimal import ROUND_HALF_UP, Decimal

    if v is None:
        return ""
    if v == 0:
        return "0.000"
    d = Decimal(repr(float(v)))
    q = Decimal(1).scaleb(d.adjusted() - 3)
    return f"{d.quantize(q, rounding=ROUND_HALF_UP):f}"


def _pct2(v) -> str:
    from decimal import ROUND_HALF_UP, Decimal

    return "" if v is None else f"{Decimal(repr(float(v))).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):f}%"


def fraction_of_total(params: dict, table: dict) -> dict:
    """calc.type COLUMN | ROW | GRAND: each value over its column's, row's or
    the table's total (blanks left out); ALL: a text summary of the data,
    the totals and all three. calc.ci.calculate: Wilson/Brown or
    Clopper-Pearson interval of each fraction (counts; y_high_low: the
    fraction, then its distances to the upper and lower limits).
    options.reportResultsAs FRACTIONS | PERCENTAGES."""
    from .roc import _prop_ci

    calc = params.get("calc", {})
    if any(len(d["subs"]) != 1 for d in table["sets"]):  # replicates: Prism's error, an empty table
        width = 3 if calc.get("ci", {}).get("calculate") else 1
        return {**_out(table, "y_high_low" if width == 3 else "y_single",
                       [{"title": d["title"], "subs": [[None] * _n_rows(table)] * width} for d in table["sets"]]),
                "error": "INVALID_DATA_FORMAT_SUBCOLUMNS"}
    kind = calc.get("type", "COLUMN")
    scale = 100.0 if params.get("options", {}).get("reportResultsAs", "FRACTIONS") == "PERCENTAGES" else 1.0
    nr = _n_rows(table)
    vals = [[(d["subs"][0][r] if r < len(d["subs"][0]) and _ok(d["subs"][0][r]) else None) for r in range(nr)]
            for d in table["sets"]]
    col_tot = [sum(v for v in c if v is not None) for c in vals]
    row_tot = [sum(c[r] for c in vals if c[r] is not None) for r in range(nr)]
    grand = sum(col_tot)

    def frac(how):
        out = []
        for j, c in enumerate(vals):
            tot = col_tot[j] if how == "COLUMN" else None
            out.append([None if v is None else (v / (tot if how == "COLUMN" else row_tot[r] if how == "ROW" else grand)
                                                if (tot if how == "COLUMN" else row_tot[r] if how == "ROW" else grand)
                                                else None)
                        for r, v in enumerate(c)])
        return out

    if kind == "ALL":
        rows = table.get("rows") or [f"Row {r + 1}" for r in range(nr)]
        names = [d["title"] for d in table["sets"]]
        label = "Percentage of" if scale == 100 else "Fraction of"
        heads = ["Data analyzed", *(f"  {t}" for t in rows), "  Total", ""]
        for w in ("column", "row", "grand"):
            heads += [f"{label} {w} total", *(f"  {t}" for t in rows), ""]
        heads = heads[:-1]
        cols = []
        parts = {w: frac(k) for w, k in (("column", "COLUMN"), ("row", "ROW"), ("grand", "GRAND"))}
        for j, nm in enumerate(names):
            cells = [nm, *("" if v is None else _num_text(v) for v in vals[j]), _g4(col_tot[j]), ""]
            for w in ("column", "row", "grand"):
                cells += [nm, *((_pct2 if scale == 100 else _g4)(None if f is None else f * scale)
                                for f in parts[w][j]), ""]
            cols.append(cells[:-1])
        total = ["Total", *(_g4(v) for v in row_tot), _g4(grand)]
        cols.append(total + [""] * (len(heads) - len(total)))
        return {"format": "text", "x": None, "rows": heads, "sets": [{"title": None, "subs": [c]} for c in cols]}
    if kind not in ("COLUMN", "ROW", "GRAND"):
        raise NotImplementedError(f"fraction of total type {kind}")
    fr = frac(kind)
    ci = calc.get("ci", {})
    sets = []
    for j, d in enumerate(table["sets"]):
        f = [None if v is None else v * scale for v in fr[j]]
        if not ci.get("calculate"):
            sets.append({"title": d["title"], "subs": [f]})
            continue
        level = float(ci.get("level", 95.0))
        alpha = 1 - level / 100
        z = stats.norm.ppf(1 - alpha / 2)
        method = "CLOPPER_PEARSON" if ci.get("method") == "CLOPPER_PEARSON" else "WILSON_BROWN"
        up, lo = [], []
        for r, v in enumerate(vals[j]):
            n = col_tot[j] if kind == "COLUMN" else row_tot[r] if kind == "ROW" else grand
            if v is None or not n or not float(v).is_integer() or not float(n).is_integer():
                up.append(None)
                lo.append(None)
                continue
            a, b = _prop_ci(method, int(v), int(n), z, alpha)
            p = v / n
            up.append((b - p) * scale)
            lo.append((p - a) * scale)
        sets.append({"title": d["title"], "subs": [f, up, lo]})
    return _out(table, "y_high_low" if ci.get("calculate") else "y_single", sets)


def _num_text(v: float) -> str:
    return str(int(v)) if float(v).is_integer() else repr(float(v))


# ----------------------------------------------------------------- prune rows
def prune_rows(params: dict, table: dict) -> dict:
    """calc.pruneByRange: keep the rows whose X lies in xRangeToKeep (ends
    included). Otherwise average groups of rows - EVERY_OTHER_ROW: pairs,
    EVERY_NTH_ROW (and any other): n rows - each value the mean of the
    group's values (blanks left out), X the group's mean X; rows left over
    at the end are dropped. averageOnly.greaterThan: rows with X up to
    xThreshold stay as they are, only the rest are averaged."""
    calc = params.get("calc", {})
    x = table.get("x") or []
    nr = _n_rows(table)
    if calc.get("pruneByRange", True):
        rng = calc.get("xRangeToKeep", {})
        lo, hi = float(rng.get("from", -math.inf)), float(rng.get("to", math.inf))
        keep = [r for r in range(nr) if r < len(x) and _ok(x[r]) and lo <= x[r] <= hi]
        sets = [{"title": d["title"], "subs": [[s[r] if r < len(s) else None for r in keep] for s in d["subs"]]}
                for d in table["sets"]]
        return {"format": _fmt_of(table), "x": [x[r] for r in keep], "rows": None, "sets": sets}
    n = 2 if calc.get("averageType", "EVERY_NTH_ROW") == "EVERY_OTHER_ROW" else max(1, int(calc.get("n", 2)))
    only = calc.get("averageOnly", {})
    first = 0
    if only.get("greaterThan"):
        thr = float(only.get("xThreshold", 0.0))
        first = next((r for r in range(nr) if r < len(x) and _ok(x[r]) and x[r] > thr), nr)
    groups = [[r] for r in range(first)] + [list(range(s, s + n)) for s in range(first, nr - n + 1, n)]

    replicated = any(len(d["subs"]) > 1 for d in table["sets"])

    def mean(vs, last_needed=False):
        if last_needed and len(vs) > 1 and not _ok(vs[-1]):  # replicates: the group's last row blank (verified)
            return None
        vs = [v for v in vs if _ok(v)]
        return float(np.mean(vs)) if vs else None

    xo = [mean([x[r] for r in g if r < len(x)]) for g in groups]
    sets = [{"title": d["title"], "subs": [[mean([s[r] if r < len(s) else None for r in g], replicated) for g in groups]
                                           for s in d["subs"]]}
            for d in table["sets"]]
    return {"format": _fmt_of(table), "x": xo, "rows": None, "sets": sets}


def _fmt_of(table: dict) -> str:
    return table.get("format") or ("y_replicates" if any(len(d["subs"]) > 1 for d in table["sets"]) else "y_single")


# ---------------------------------------------------------- select and transform
def select_transform(params: dict, table: dict) -> dict:
    """A Multiple-variables table rebuilt: one variable per enabled entry of
    params.transforms, titled with its title, its values the definition
    evaluated per row (Prism's syntax; A, B, C... the table's variables in
    order; a text variable passes through as text); rowFilters.range keeps
    rows from..to (1-based, inclusive; -1: all)."""
    from .equation import expression

    filt = params.get("rowFilters", {})
    if filt.get("variableVariable"):
        raise NotImplementedError("row filters comparing two variables")
    nr = _n_rows(table)
    rng = filt.get("range", {})
    a, b = int(rng.get("from", -1)), int(rng.get("to", -1))
    rows = list(range(nr)) if a < 0 or b < 0 else list(range(max(a, 1) - 1, min(b, nr)))
    letters = [chr(65 + i) for i in range(len(table["sets"]))]
    cols = [d["subs"][0] if d["subs"] else [] for d in table["sets"]]
    tests = {">": lambda x, v: x > v, ">=": lambda x, v: x >= v, "<": lambda x, v: x < v,
             "<=": lambda x, v: x <= v, "=": lambda x, v: x == v, "==": lambda x, v: x == v,
             "!=": lambda x, v: x != v, "<>": lambda x, v: x != v}
    for f in filt.get("variableValue") or []:  # every filter must hold (verified on Prism's own sample)
        i, op = int(f.get("variableIdx", -1)), str(f.get("logic", ""))
        if not 0 <= i < len(cols) or op not in tests:
            raise NotImplementedError(f"row filter {f}")
        rows = [r for r in rows if r < len(cols[i]) and isinstance(cols[i][r], (int, float))
                and tests[op](cols[i][r], f.get("value"))]
    sets = []
    for tr in params.get("transforms", []):
        if not tr.get("enabled", True):
            continue
        dfn = str(tr.get("definition", "")).strip()
        if dfn.upper() in letters and any(isinstance(v, str) for v in cols[letters.index(dfn.upper())]):
            src = cols[letters.index(dfn.upper())]
            sets.append({"title": tr.get("title", ""), "subs": [[src[r] if r < len(src) else None for r in rows]]})
            continue
        g = expression(dfn, letters)
        out = []
        for r in rows:
            vals = [c[r] if r < len(c) and isinstance(c[r], (int, float)) else math.nan for c in cols]
            try:
                with np.errstate(all="ignore"):
                    res = g(np.array(vals, float))
                if isinstance(res, (str, np.str_)) or (isinstance(res, np.ndarray) and res.dtype.kind == "U"):
                    out.append(str(res))  # a text value: a categorical variable
                    continue
                v = float(res)
            except (ValueError, ZeroDivisionError, OverflowError):
                v = math.nan
            out.append(v if math.isfinite(v) else None)
        sets.append({"title": tr.get("title", ""), "subs": [out]})
    return {"format": "y_single", "x": None, "rows": None, "sets": sets}


ANALYSES.update({"FRACTION_OF_TOTAL": fraction_of_total, "PRUNE_ROWS": prune_rows,
                 "SELECT_TRANSFORM": select_transform})


def _levels(values: list) -> list:
    """A factor's levels in the order they first appear (Prism's "entry" order)."""
    out: list = []
    for v in values:
        if v not in (None, "") and v not in out:
            out.append(v)
    return out


def extract_rearrange(params: dict, table: dict) -> dict:
    """Extract and rearrange (Prism: EXTRACT_REARRANGE): a Multiple-variables
    table rearranged as a grouped table (dataArrangement.rowFactorVariable's
    levels as rows, columnFactorVariable's as data sets, the response values
    of each cell as its replicates, in table order) or a column table
    (groupingVariable's levels as data sets; without one, the response as a
    single column). Rows whose response or factor is blank are left out;
    levels keep their first-appearance order. includeVarNamePrefix titles a
    level `Name = "level"`; rowTitles.VARIABLE titles the rows of a column
    table without groups. Verified against Prism 11.1 (E-extract)."""
    arr = params.get("dataArrangement") or {}
    fmt = params.get("resultTableFormat", "GROUPED")
    cols = [d["subs"][0] if d["subs"] else [] for d in table["sets"]]
    names = [d.get("title") or "" for d in table["sets"]]
    nr = max((len(c) for c in cols), default=0)

    def ref(key):
        v = arr.get(key)
        i = v.get("col", {}).get("idx") if isinstance(v, dict) else None
        return i if isinstance(i, int) and 0 <= i < len(cols) else None

    def cell(i, r):
        c = cols[i]
        return c[r] if r < len(c) else None

    def label(i, lv):
        text = lv if isinstance(lv, str) else f"{lv:g}" if isinstance(lv, float) else str(lv)
        return f'{names[i]} = "{text}"' if params.get("includeVarNamePrefix") else text

    resp = ref("responseVariable")
    if resp is None:
        raise ValueError("no response variable")
    blank = (None, "")
    if fmt == "GROUPED":
        rf, cf = ref("rowFactorVariable"), ref("columnFactorVariable")
        if rf is None or cf is None:
            raise ValueError("a grouped table needs a row and a column factor")
        keep = [r for r in range(nr) if cell(resp, r) not in blank and cell(rf, r) not in blank
                and cell(cf, r) not in blank]
        rows_lv = _levels([cell(rf, r) for r in range(nr)])
        cols_lv = _levels([cell(cf, r) for r in range(nr)])
        cells = {(a, b): [cell(resp, r) for r in keep if cell(rf, r) == a and cell(cf, r) == b]
                 for a in rows_lv for b in cols_lv}
        reps = max((len(v) for v in cells.values()), default=1) or 1
        sets = [{"title": label(cf, b),
                 "subs": [[cells[(a, b)][k] if k < len(cells[(a, b)]) else None for a in rows_lv] for k in range(reps)]}
                for b in cols_lv]
        return {"kind": "grouped", "format": "y_replicates", "replicates": reps, "x": None,
                "rows": [label(rf, a) for a in rows_lv], "sets": sets}
    if fmt == "COLUMN":
        g = ref("groupingVariable")
        if g is None:
            keep = [r for r in range(nr) if cell(resp, r) not in blank]
            rt = params.get("rowTitles") or {}
            ti = (rt.get("variable") or {}).get("col", {}).get("idx") if rt.get("type") == "VARIABLE" else None
            rows = [str(cell(ti, r) if cell(ti, r) is not None else "") for r in keep] \
                if isinstance(ti, int) and 0 <= ti < len(cols) else None
            return {"kind": "column", "format": "y_single", "x": None, "rows": rows,
                    "sets": [{"title": names[resp], "subs": [[cell(resp, r) for r in keep]]}]}
        keep = [r for r in range(nr) if cell(resp, r) not in blank and cell(g, r) not in blank]
        groups = {lv: [cell(resp, r) for r in keep if cell(g, r) == lv] for lv in _levels([cell(g, r) for r in range(nr)])}
        n = max((len(v) for v in groups.values()), default=0)
        return {"kind": "column", "format": "y_single", "x": None, "rows": None,
                "sets": [{"title": label(g, lv), "subs": [v + [None] * (n - len(v))]} for lv, v in groups.items()]}
    raise NotImplementedError(f"Extract and rearrange to a {fmt} table")


ANALYSES["EXTRACT_REARRANGE"] = extract_rearrange
