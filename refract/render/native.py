"""Graphs made in Refract (refract.model.document.NativeGraph): built from
the table's current data in Prism's default style for its kind, with
significance stars from an analysis's pairwise comparisons."""

from __future__ import annotations

from collections.abc import Callable

from ..model.document import Analysis, DataTable, NativeGraph, Project
from ..stats import report
from . import build, formatting
from .model import Graph

STYLES = {"default": "Default for the table", "bars": "Bars: mean and error, with the points",
          "means": "Mean and error as symbols", "donut": "Donut"}
KIND_STYLES = {"column": ("default", "bars", "means"), "grouped": ("default", "means"),
               "parts_of_whole": ("default", "donut")}  # other tables: the default only
DONUT_HOLE = 0.5  # inner / outer radius of Prism's donut (measured on its export)


def styles_for(kind: str) -> list[str]:
    """The styles a table kind's graph can take."""
    return list(KIND_STYLES.get(kind, ("default",)))
ERRORS = {"sd": "SD", "sem": "SEM"}
KINDS = {"column", "grouped", "xy", "survival", "parts_of_whole", "contingency", "nested", "multivariable"}
# the graph types whose look Prism's own default (or a style Refract writes) reproduces,
# built the way that was verified against Prism (refract.render.build)
VERIFIED = {("col_scatter", "median"), ("col_scatter_bar", "mean_sd"), ("col_scatter_bar", "mean_sem"),
            ("col_means", "mean_sd"), ("col_means", "mean_sem"), ("grp_bars_points", "mean_sd"),
            ("grp_bars_points", "mean_sem"), ("grp_means", "mean_sd"), ("grp_means", "mean_sem"),
            ("xy_points", "mean_sd"), ("xy_points", "mean_sem"), ("surv_ticks", None), ("pie", None),
            ("donut", None)}


def comparisons(results: dict) -> list[tuple[dict, dict, float]]:
    """Every pairwise comparison in a results tree: (first id, second id,
    adjusted P value; the individual one when there is no adjusted one)."""
    out: list[tuple[dict, dict, float]] = []

    def walk(d):
        if not isinstance(d, dict):
            return
        tests = d.get("tests") if isinstance(d.get("tests"), dict) else None
        if tests is not None and "method" in d:
            for e in tests.values():
                if not (isinstance(e, dict) and isinstance(e.get("id"), dict)):
                    continue
                for f in (e.get("value") or {}).values():
                    if not (isinstance(f, dict) and isinstance(f.get("id"), dict)):
                        continue
                    v = f.get("value") or {}
                    pv = v.get("pValueAdjusted") or v.get("pValueIndividual") or v.get("pValue")
                    if isinstance(pv, dict) and isinstance(pv.get("value"), int | float):
                        out.append((e["id"], f["id"], float(pv["value"])))
            return
        for x in d.values():
            walk(x)

    walk(results)
    return out


def star_source(project: Project, ng: NativeGraph, results: Callable[[Analysis], dict],
                source: Callable[[Analysis], tuple | None]) -> tuple[Analysis, dict, list[int] | None] | None:
    """The analysis whose comparisons the graph shows: the first of its table
    with pairwise comparisons."""
    if ng.stars == "none":
        return None
    for a in project.analyses:
        src = source(a)
        if src is None or src[0] is not ng.table:
            continue
        r = results(a)
        if comparisons(r):
            return a, r, src[1]
    return None


def _positions(g: Graph, t: DataTable, sets: list[int] | None, first: dict, second: dict) -> tuple[float, float] | None:
    """Graph positions of two compared cells (same row) or columns."""
    def col(ident):
        c = ident.get("col")
        if not isinstance(c, dict) or not isinstance(c.get("idx"), int) or c["idx"] < 0:
            return None
        i = c["idx"]
        return (sets[i] if sets is not None and i < len(sets) else i)

    c1, c2 = col(first), col(second)
    if c1 is None or c2 is None or c1 >= len(g.series) or c2 >= len(g.series):
        return None
    r1, r2 = (first.get("row") or {}).get("idx"), (second.get("row") or {}).get("idx")
    if g.family == "grouped":
        if r1 is None or r1 != r2:
            return None  # across rows: not drawn
        s1, s2 = g.series[c1], g.series[c2]
        if r1 >= len(s1.xs) or r1 >= len(s2.xs):
            return None
        return s1.xs[r1], s2.xs[r1]
    if g.family == "column" and r1 is None and r2 is None:
        return float(c1), float(c2)
    return None


class NoGraphType(NotImplementedError):
    """The graph sheet waits for its type to be chosen (Change Graph Type)."""


def graph(project: Project, ng: NativeGraph, results: Callable[[Analysis], dict] | None = None,
          source: Callable[[Analysis], tuple | None] | None = None) -> Graph:
    from . import graph_types as GT

    t = ng.table
    if t.kind not in KINDS:
        raise NotImplementedError(f"Refract cannot graph {t.kind} tables yet")
    gt = GT.resolve(t.kind, ng.style)
    if gt is None:
        raise NoGraphType("choose how to graph this table")
    plot = GT.plot_option(gt, ng.error)
    if (gt.key, plot) in VERIFIED and t.kind == gt.family and ng.options.get("scale") != "fraction" \
            and not ng.options.get("error"):
        if t.kind == "parts_of_whole":  # Prism's default pie (the Prism copy is drawn from the same seed)
            g = build.pie_defaults(build.pie_graph(t, ng.title), t)
            if gt.key == "donut" and g.series:
                g.series[0].hole = DONUT_HOLE
            formatting.apply(g, ng.format)
            return g
        error = {"mean_sd": "sd", "mean_sem": "sem"}.get(plot or "", "sd")
        g = build.from_table(t, error, title=ng.title)
        if gt.key == "col_scatter_bar":
            build.column_bars(g, t, error)
        elif gt.key in ("col_means", "grp_means"):
            build.mean_symbols(g, error)
    else:
        g = GT.make(t, gt, plot, ng.title, ng.options)
    if g.family == "pie" or g.heatmap is not None:
        formatting.apply(g, ng.format)
        return g
    formatting.apply(g, ng.format)
    if results is not None and source is not None:
        found = star_source(project, ng, results, source)
        if found is not None:
            _a, r, sets = found
            s = report.Style()
            pairs = []
            for first, second, p in comparisons(r):
                pos = _positions(g, t, sets, first, second)
                label = report.stars(p, s)
                if pos is not None and (ng.show_ns or label != "ns"):
                    pairs.append((pos[0], pos[1], label))
            build.add_significance(g, pairs)
    return g


def default_for(t: DataTable) -> NativeGraph | None:
    """The graph Refract makes with a new table (as Prism makes one)."""
    if t.kind not in KINDS:
        return None
    return NativeGraph(t.title, t, "default")  # Prism's default for the kind (also what is written for Prism)
