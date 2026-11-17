"""Turn a data table into the inputs `engine.compute` takes, and recompute a
stored analysis from its own parameters and input data sets.

The shapes follow `engine.compute`: column analyses take one list of values
per data set; grouped and XY analyses one list of replicate subcolumns per
data set (with the X column or row titles alongside). Excluded values are
left out (None), as Prism does.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from ..model.document import REPLICATE_FORMATS, Analysis, DataSet, DataTable, Project
from . import engine

# analysis class -> how its data sets are passed
COLUMNS = {"COLUMN_STATISTICS", "T_TESTS_AND_NONPARAMETRIC", "ONE_WAY_ANOVA", "NORMALITY_TESTS",
           "ONE_SAMPLE_TESTS", "CONTINGENCY_TABLE", "SURVIVAL", "FREQUENCY_DISTRIBUTION", "IDENTIFY_OUTLIERS",
           "MULTIPLE_COMPARISONS"}
REPLICATES = {"TWO_WAY_ANOVA", "THREE_WAY_ANOVA", "MULTIPLE_TWO_SAMPLE_TESTS", "CORRELATION", "SIMPLE_LINEAR_REGRESSION",
              "NONLINEAR_REGRESSION", "INTERPOLATION", "DEMING_REGRESSION", "FIT_SPLINE_LOWESS"}
# their parameters name data sets by their index in the table (two of them): every data set is passed
WHOLE_TABLE = {"ROC_CURVE", "BLAND_ALTMAN", "CHI2"}
XY_MEANS = {"AREA_UNDER_CURVE", "SIMPLE_LOGISTIC_REGRESSION", "SMOOTH_CURVE"}  # X, and each Y data set (replicates averaged)
NESTED = {"NESTED_T_TEST", "ONE_WAY_NESTED_ANOVA"}  # per group (data set), its subcolumns
# Multiple-variables tables: one list per variable (numbers, or the text of a categorical one), every variable
VARIABLES = {"MULTIPLE_LINEAR_REGRESSION", "MULTIPLE_LOGISTIC_REGRESSION", "MULTIPLE_COX_REGRESSION", "PCA",
             "MULTI_FACTOR_ANOVA", "HIERARCHICAL_CLUSTERING", "K_MEANS_CLUSTERING",
             "DESCRIPTIVE_STATISTICS"}
# analyses whose output is a data table (refract.stats.transforms): the whole table, as a table dict
TABLE_OUT = {"NORMALIZE", "TRNSFORM", "REMOVE_BASELINE", "ROW_STATISTICS", "TRANSPOSE", "FRACTION_OF_TOTAL",
             "PRUNE_ROWS", "SELECT_TRANSFORM", "EXTRACT_REARRANGE"}
SUPPORTED = COLUMNS | REPLICATES | WHOLE_TABLE | XY_MEANS | NESTED | VARIABLES | TABLE_OUT
# column tables of entered mean, SD or SEM, and N: the parametric tests depend on these alone
SUMMARY_FORMATS = {"y_sd_n", "y_se_n"}
SUMMARY_OK = {"T_TESTS_AND_NONPARAMETRIC", "ONE_WAY_ANOVA"}


@dataclass
class Inputs:
    columns: list
    titles: list[str]
    row_titles: list[str] | None = None
    x_values: list | None = None
    summary: bool = False  # the columns rebuilt from entered mean, SD and N


def _letters(i: int) -> str:
    s, i = "", i + 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def _title(t: DataTable, i: int) -> str:
    return t.datasets[i].title or _letters(i)


def gather(analysis_class: str, t: DataTable, sets: list[int] | None = None) -> Inputs:
    """The inputs of `analysis_class` from data sets `sets` (indices into
    t.datasets; None = all) of table t."""
    if analysis_class not in SUPPORTED:
        raise NotImplementedError(f"{analysis_class} is not run from the user interface yet")
    sets = list(range(len(t.datasets))) if sets is None else list(sets)
    titles = [_title(t, i) for i in sets]
    n = t.subcolumns_per_dataset
    rows = t.n_rows

    def col(i: int, k: int) -> list:
        v = t.values(i, k)
        return (v + [None] * rows)[:rows]

    if analysis_class in WHOLE_TABLE | VARIABLES:  # the parameters index the table's own data sets
        sets = list(range(len(t.datasets)))
        titles = [_title(t, i) for i in sets]
    if analysis_class in VARIABLES:
        columns = [_variable(t, i, rows) for i in sets]
        return Inputs(columns, titles)
    if analysis_class == "CORRELATION" and t.x is None:
        # a correlation matrix names data sets by their index in the table: every data set is passed,
        # those not analysed (and categorical variables) without values, and left out
        chosen = set(sets)
        columns = [[col(i, k) if i in chosen else [] for k in range(n)] for i in range(len(t.datasets))]
        return Inputs(columns, [_title(t, i) for i in range(len(t.datasets))])
    if analysis_class in NESTED:
        columns = [[_trim(col(i, k)) for k in range(len(t.datasets[i].subcolumns))] for i in sets]
        return Inputs(columns, titles)
    if analysis_class in XY_MEANS:
        columns = [_row_means([col(i, k) for k in range(n)]) for i in sets]
    elif analysis_class in SUMMARY_OK and t.data_format in SUMMARY_FORMATS:
        columns = [_from_summary(t, i) for i in sets]  # entered mean, SD (or SEM) and N
    elif analysis_class in COLUMNS or analysis_class in WHOLE_TABLE:
        if n != 1 and t.data_format not in REPLICATE_FORMATS:
            raise NotImplementedError(f"{analysis_class} on a table with {n} subcolumns per data set")
        # an XY or grouped table's replicates: each row's mean, as Prism analyses them (E-kinds)
        columns = [col(i, 0) if n == 1 else _row_means([col(i, k) for k in range(n)]) for i in sets]
        if analysis_class != "SURVIVAL":  # rows past the last value do not exist for these
            columns = [_trim(c) for c in columns]
    elif t.data_format in REPLICATE_FORMATS:
        columns = [[col(i, k) for k in range(n)] for i in sets]
    else:  # entered mean with SD/SEM/N...: the means, one value per row
        columns = [[col(i, 0)] for i in sets]
    row_titles = None
    if t.row_titles is not None:
        cells = t.row_titles.subcolumns[0] if t.row_titles.subcolumns else []
        row_titles = [(cells[r] if r < len(cells) else "") or f"Row {r + 1}" for r in range(rows)]
    x = t.x_values() if t.x is not None else None
    if x is not None:
        x = [(v if not (t.x.is_excluded(0, r) if t.x.generated is None else False) else None)
             for r, v in enumerate((x + [None] * rows)[:rows])]
    return Inputs(columns, titles, row_titles, x,
                  analysis_class in SUMMARY_OK and t.data_format in SUMMARY_FORMATS)


def _from_summary(t: DataTable, i: int) -> list:
    """N values with exactly the entered mean and SD (the first row's; SD from SEM x sqrt(N)): what the
    parametric tests compute from (E-stats8: Prism's t tests and one-way ANOVA of such tables)."""
    mean, err, n = (t.values(i, k) for k in range(3))
    m, e, k = (v[0] if v else None for v in (mean, err, n))
    if m is None or k is None or k < 1:
        return []
    k = round(k)
    sd = (e or 0.0) * (math.sqrt(k) if t.data_format == "y_se_n" else 1.0)
    if k == 1:
        return [m]
    z = [j - (k - 1) / 2 for j in range(k)]  # centred, then scaled to a sample SD of exactly 1
    s = math.sqrt(sum(v * v for v in z) / (k - 1))
    return [m + sd * v / s for v in z]


def _row_means(subs: list[list]) -> list:
    out = []
    for r in range(max((len(s) for s in subs), default=0)):
        v = [s[r] for s in subs if r < len(s) and s[r] is not None and math.isfinite(s[r])]
        out.append(sum(v) / len(v) if v else None)
    return out


def _variable(t: DataTable, i: int, rows: int) -> list:
    """A variable's values: numbers, or (a text variable) its trimmed texts; blanks None."""
    vals = (t.values(i, 0) + [None] * rows)[:rows]
    ds = t.datasets[i]
    texts = ((ds.subcolumns[0] if ds.subcolumns else []) + [""] * rows)[:rows]
    if any(v is None and str(c).strip() for v, c in zip(vals, texts, strict=True)):  # a categorical variable
        return [str(c).strip() or None for c in texts]
    return vals


def _trim(c: list) -> list:
    while c and c[-1] is None:
        c = c[:-1]
    return c


SUB_NAMES = {"y_sd_n": ["Mean", "SD", "N"], "y_se": ["Mean", "SEM"], "y_se_n": ["Mean", "SEM", "N"],
             "y_cv_n": ["Mean", "%CV", "N"],
             "y_high_low": ["", "Upper", "Lower"], "y_plus_minus": ["", "+", "-"]}


def table_dict(t: DataTable, sets: list[int] | None = None) -> dict:
    """Table t (data sets `sets`, None: all) in refract.stats.transforms' form."""
    rows = t.n_rows
    sets = list(range(len(t.datasets))) if sets is None else list(sets)
    x = t.x_values() if t.x is not None else None
    titles = None
    if t.row_titles is not None:
        cells = t.row_titles.subcolumns[0] if t.row_titles.subcolumns else []
        titles = [(cells[r] if r < len(cells) else "") or "" for r in range(rows)]
    return {"title": t.title, "x": None if x is None else (list(x) + [None] * rows)[:rows], "rows": titles,
            "sets": [{"title": _title(t, i),
                      "subs": ([_variable(t, i, rows)] if t.kind == "multivariable" else  # numbers, or a text variable
                               [(t.values(i, k) + [None] * rows)[:rows] for k in range(len(t.datasets[i].subcolumns))])}
                     for i in sets]}


def table_results(out: dict) -> dict[str, Any]:
    """A table-making analysis's output as results: its table, shown as a result table."""
    names = SUB_NAMES.get(out.get("format", ""))
    cols, colvals = [], []
    if out.get("x") is not None:
        cols.append("X")
        colvals.append(list(out["x"]))
    for st in out["sets"]:
        for k, sub in enumerate(st["subs"]):
            label = st["title"] or "" if st["title"] is not None else ""
            if len(st["subs"]) > 1:
                extra = names[k] if names and k < len(names) else f"{k + 1}"
                label = f"{label} {extra}".strip() if extra else label
            cols.append(label)
            colvals.append(list(sub))
    n = max((len(c) for c in colvals), default=0)
    rows = [[(c[r] if r < len(c) else None) for c in colvals] for r in range(n)]
    rt = out.get("rows")
    return {"status": {"error": out.get("error", "VALID"), "warning": []},
            "_tables": {"Result": {"columns": cols, "rows": rows,
                                   "row_titles": None if rt is None else [str(v or "") for v in rt][:n] +
                                   [""] * max(0, n - len(rt))}}}


def _fmt(v) -> str:
    return "" if v is None else (repr(float(v)) if isinstance(v, (int, float)) else str(v))


def mv_design(analysis_class: str, content: dict, t: DataTable) -> DataTable | None:
    """A t test, nonlinear fit or survival analysis of a Multiple-variables table
    (content.variableDesign: responseList, factorList, x, subject), as the table Prism
    analyses: a column table with a data set per level of the factor (a paired test: rows
    matched by subject), or an XY / survival table with X from the x variable and a data set
    per level holding its rows' responses. Levels in first-appearance order. None for any
    other analysis."""
    vd = content.get("variableDesign") if isinstance(content, dict) else None
    if t.kind != "multivariable" or not isinstance(vd, dict) or not vd.get("responseList"):
        return None

    def ix(ref):
        i = ((ref or {}).get("col") or {}).get("idx")
        return i if isinstance(i, int) and 0 <= i < len(t.datasets) else None

    rows = t.n_rows
    resp = ix(vd["responseList"][0])
    fac = ix((vd.get("factorList") or [None])[0])
    xv, subj = ix(vd.get("x")), ix(vd.get("subject"))
    if resp is None:
        return None
    rv, fv = _variable(t, resp, rows), _variable(t, fac, rows) if fac is not None else ["" for _ in range(rows)]
    xs = _variable(t, xv, rows) if xv is not None else None
    keep = [r for r in range(rows) if rv[r] is not None and fv[r] is not None and (xs is None or xs[r] is not None)]
    levels = list(dict.fromkeys(fv[r] for r in keep))

    def title(lv):
        return lv if isinstance(lv, str) else f"{lv:g}" if lv != "" else t.datasets[resp].title or ""

    meta = {"response": _var_ref(t, resp), "factor": _var_ref(t, fac) if fac is not None else None, "levels": levels}
    if analysis_class == "T_TESTS_AND_NONPARAMETRIC" or xv is None:
        if subj is not None and str(content.get("experimentalDesign", "")).startswith(("PAIRED", "RATIO_PAIRED",
                                                                                         "WILCOXON")):
            sv = _variable(t, subj, rows)
            subjects = list(dict.fromkeys(sv[r] for r in keep if sv[r] is not None))
            cells = {(sv[r], fv[r]): rv[r] for r in keep}
            sets = [DataSet(title(lv), [[_fmt(cells.get((s_, lv))) for s_ in subjects]]) for lv in levels]
            n = len(subjects)
        else:
            vals = {lv: [rv[r] for r in keep if fv[r] == lv] for lv in levels}
            n = max((len(v) for v in vals.values()), default=0)
            sets = [DataSet(title(lv), [[_fmt(v) for v in vals[lv]] + [""] * (n - len(vals[lv]))]) for lv in levels]
        out = DataTable(t.title, "column", "y_single", sets, n)
        out.mv_design = meta
        return out
    kind = "survival" if analysis_class == "SURVIVAL" else "xy"
    sets = [DataSet(title(lv), [[_fmt(rv[r]) if fv[r] == lv else "" for r in keep]]) for lv in levels]
    x = DataSet(t.datasets[xv].title, [[_fmt(xs[r]) for r in keep]], role="X")
    out = DataTable(t.title, kind, "y_single", sets, len(keep), x=x)
    out.mv_design = meta
    return out


def _var_ref(t: DataTable, i: int) -> dict:
    d = t.datasets[i]
    return {k: v for k, v in (("uid", d.uid), ("title", d.title or ""), ("idx", i)) if v is not None}


def _mv_refs(content, meta: dict):
    """Parameters naming a group by its level ({"var": ..., "value": level}, e.g. a post-test
    control) name the reshaped table's data set instead ({"col": {"idx": level index}})."""
    if isinstance(content, dict):
        v = content.get("var")
        if isinstance(v, dict) and v.get("factorList") and set(content) == {"var"}:
            level = v["factorList"][0].get("value")
            if level in meta["levels"]:
                return {"col": {"idx": meta["levels"].index(level)}}
        return {k: _mv_refs(x, meta) for k, x in content.items()}
    if isinstance(content, list):
        return [_mv_refs(x, meta) for x in content]
    return content


def _mv_ids(out, meta: dict):
    """Prism names a group of a Multiple-variables analysis by the response and the factor's level
    ({"var": {"response", "factorList": [{"var", "value"}]}}) where a table's data set has {"col"}."""
    def var(j):
        v = {"response": meta["response"]}
        if meta["factor"] is not None and 0 <= j < len(meta["levels"]):
            v["factorList"] = [{"var": meta["factor"], "value": meta["levels"][j]}]
        return {"var": v}

    def fix(o):
        if isinstance(o, dict):
            o = {k: fix(v) for k, v in o.items()}
            ident = o.get("id")
            if isinstance(ident, dict) and isinstance(ident.get("col"), dict) and isinstance(ident["col"].get("idx"), int):
                o["id"] = {**var(ident["col"]["idx"]), **{k: v for k, v in ident.items() if k != "col"}}
            elif isinstance(ident, list):
                o["id"] = [var(x["col"]["idx"]) if isinstance(x, dict) and isinstance(x.get("col"), dict) else x
                           for x in ident]
            return o
        if isinstance(o, list):
            return [fix(v) for v in o]
        return o
    return fix(out)


def run(analysis_class: str, content: dict, t: DataTable, sets: list[int] | None = None) -> dict[str, Any]:
    """Compute an analysis of table t: the `content` of a results.json."""
    shaped = mv_design(analysis_class, content, t)
    if shaped is not None:
        inner = _mv_refs({k: v for k, v in content.items() if k != "variableDesign"}, shaped.mv_design)
        out = run(analysis_class, {**inner, "_mv": True}, shaped)
        if analysis_class == "T_TESTS_AND_NONPARAMETRIC" and len(shaped.datasets) == 2:
            out = engine.two_group_descriptives(out, gather(analysis_class, shaped).columns,
                                                [d.title or "" for d in shaped.datasets], content)
            desc = out["descriptiveStatistics"]  # Prism: sample1 the second level, sample2 the first
            out["descriptiveStatistics"] = {"sample1": desc.pop("col1"), "sample2": desc.pop("col0"), **desc}
        if analysis_class == "NONLINEAR_REGRESSION":  # Prism: each group's data summary beside the models
            summ = {}
            for key, m in (out.get("models") or {}).items():
                v = m.get("value") if isinstance(m, dict) else None
                if isinstance(v, dict) and "dataSummary" in v:
                    ident = m.get("id") or {}
                    ds = dict(v.pop("dataSummary"))
                    j = (ident.get("col") or {}).get("idx")
                    if isinstance(j, int) and 0 <= j < len(shaped.datasets):  # not the other groups' rows
                        other = sum(1 for c in shaped.datasets[j].subcolumns[0] if c == "")
                        for f in ("xValuesAnalyzed", "yValuesSkipped"):
                            if isinstance(ds.get(f), (int, float)):
                                ds[f] = max(0, ds[f] - other)
                    summ[key] = {"id": {k: x for k, x in ident.items() if k != "model"}, "value": ds}
            if summ:
                out["dataSummary"] = summ
        return _mv_ids(out, shaped.mv_design)
    if analysis_class in TABLE_OUT:
        from . import transforms as TR

        return table_results(TR.ANALYSES[analysis_class](content, table_dict(t, sets)))
    i = gather(analysis_class, t, sets)
    if analysis_class == "FREQUENCY_DISTRIBUTION" and t.kind == "xy" and t.subcolumns_per_dataset > 1 and \
            t.data_format in REPLICATE_FORMATS:  # XY: Prism's automatic bin width from every replicate (E-kinds)
        idx = list(range(len(t.datasets))) if sets is None else list(sets)
        content = {**content, "_replicates": [[v for k in range(t.subcolumns_per_dataset) for v in t.values(j, k)]
                                              for j in idx]}
    out = engine.compute(analysis_class, content, i.columns, i.titles, i.row_titles, i.x_values)
    if i.summary:
        return engine.from_summary(analysis_class, out, i.columns, i.titles, content)
    if analysis_class == "T_TESTS_AND_NONPARAMETRIC" and (t.kind in ("xy", "grouped") or (
            (content.get("report") or {}).get("descriptiveStatistics") and not content.get("_mv"))):
        out = engine.two_group_descriptives(out, i.columns, i.titles, content)
    return out


def source(project: Project, a: Analysis) -> tuple[DataTable, list[int]] | None:
    """The table and data-set indices a stored analysis reads."""
    t = next((t for t in project.tables if t.sheet_uid and t.sheet_uid in a.input_sheets), None)
    if t is None:
        return None
    uids = [d.uid for d in t.datasets]
    sets = [uids.index(u) for u in a.input_datasets if u in uids]
    return t, (sets or None)


def recompute(project: Project, a: Analysis) -> dict[str, Any]:
    src = source(project, a)
    if src is None:
        raise ValueError("the analysed data table was not found")
    content = a.parameters.get("content", a.parameters)
    return run(a.analysis_class, content, *src)


# ------------------------------------------------------------- comparison
def _sig(ident: dict) -> str:
    """A stable name for an {"id": ...} entry: its column / row / model indices."""
    parts = []
    for k, v in sorted(ident.items()):
        if k == "var" and isinstance(v, dict):  # a Multiple-variables group: the response and its levels
            levels = [str(f.get("value")) for f in v.get("factorList") or []]
            parts.append(f"var{(v.get('response') or {}).get('idx', '')}" + "".join(f"={x}" for x in levels))
        elif isinstance(v, dict):
            parts.append(f"{k}{v.get('idx', v.get('name', ''))}")
        else:
            parts.append(f"{k}{v}")
    return "+".join(parts)


def leaves(d, path: str = "") -> dict[str, float]:
    """Numeric leaves of a results tree, keyed by their path."""
    out: dict[str, float] = {}
    if isinstance(d, dict):
        for k, v in d.items():
            if k == "id" and path:  # an entry's identity (indices), not a result
                continue
            if str(k).startswith("_"):  # Refract's own extras ("_tables": result tables), not Prism's results
                continue
            if isinstance(v, dict) and "value" in v and isinstance(v.get("id"), dict):
                k, v = _sig(v["id"]), v["value"]  # entries keyed by uids in Prism, by index here
                if not k:  # an entry with an empty identity (a fit's parameter per data set): no level
                    out.update(leaves(v, path))
                    continue
            out.update(leaves(v, f"{path}/{k}" if path else str(k)))
    elif isinstance(d, list):
        for k, v in enumerate(d):
            out.update(leaves(v, f"{path}[{k}]"))
    elif isinstance(d, bool):
        pass
    elif isinstance(d, (int, float)) and math.isfinite(d):
        out[path] = float(d)
    return out


@dataclass
class Diff:
    path: str
    stored: float | None
    ours: float | None

    @property
    def agrees(self) -> bool:
        if self.stored is None or self.ours is None:
            return False
        return math.isclose(self.stored, self.ours, rel_tol=1e-6, abs_tol=1e-9)


def compare(stored: dict, ours: dict) -> list[Diff]:
    """Every numeric value of either tree, paired by path (stored order first)."""
    a, b = leaves(stored), leaves(ours)
    out = [Diff(p, v, b.get(p)) for p, v in a.items()]
    out += [Diff(p, None, v) for p, v in b.items() if p not in a]
    return out
