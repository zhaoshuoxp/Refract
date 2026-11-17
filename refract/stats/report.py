"""Results laid out for reading: the `content` of a results.json (Prism's or
ours, the same vocabulary) turned into pages of labelled rows and tables,
with numbers and P values formatted by the analysis's output settings.

The layout is generic, driven by the shape of the results, so any analysis
class gets a readable page:
  * a P value block ({"value", "level", "isSignificant"}) becomes the P value,
    its summary (stars) and whether it is significant;
  * a confidence interval ({"lower", "upper", "level"}) becomes "a to b";
  * entries keyed by internal ids show their data set's title;
  * data sets side by side (descriptive statistics, per-data-set tests and
    fits) become a table with one column per data set;
  * sources of an ANOVA table, multiple comparisons and per-row tests become
    tables with one row each.
Labels are our own wording, built from the result keys.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------- formatting


@dataclass
class Style:
    digits: int = 4  # significant digits of numbers
    p_style: str = "P_VALUE_STYLE_GP"
    p_digits: int = 6  # P_VALUE_STYLE_FULL: significant digits

    @classmethod
    def of(cls, params: dict | None) -> Style:
        out = (params or {}).get("output", {}) or {}
        ps = out.get("pValueStyle", {}) or {}
        return cls(int(out.get("significantDigitCount", 4) or 4), ps.get("type", "P_VALUE_STYLE_GP"),
                   int(ps.get("decimalDigitCount", 6) or 6))


COUNTISH = ("Count", "Analyzed", "Skipped", "Values", "Replicates", "count")
INT_KEYS = {"n", "n1", "n2", "df", "dfNumerator", "dfDenominator", "count", "levelCount", "pointCount",
            "matchedCount", "missingCount", "comparisonCount", "significantCount", "rank"}


def number(v: Any, s: Style, key: str = "") -> str:
    if isinstance(v, bool):
        return "Yes" if v else "No"
    if isinstance(v, str):
        return SPECIAL.get(v, v)
    if not isinstance(v, int | float):
        return str(v)
    v = float(v)
    if not math.isfinite(v):
        return "Infinity" if v > 0 else "-Infinity" if v < 0 else "Undefined"
    if (key in INT_KEYS or key.endswith(COUNTISH) or re.fullmatch(r"n\d?", key)) and v.is_integer() and abs(v) < 1e15:
        return str(int(v))
    if v == 0:
        return "0"
    a = abs(v)
    if 10 ** s.digits <= a < 1e9:
        return f"{v:.0f}"
    if a < 1e-4 or a >= 1e9:
        return f"{v:.{s.digits - 1}e}"
    return f"{v:#.{s.digits}g}".rstrip(".")


def p_text(p: float, s: Style) -> str:
    if not isinstance(p, int | float) or not math.isfinite(p):
        return number(p, s)
    st = s.p_style
    if st == "P_VALUE_STYLE_APA":
        return "<.001" if p < 0.001 else f"{p:.3f}".lstrip("0")
    if st == "P_VALUE_STYLE_NEJM":
        return "<0.001" if p < 0.001 else f"{p:.3f}" if p < 0.01 else f"{p:.2f}"
    if st == "P_VALUE_STYLE_FULL":
        return f"{p:.{s.p_digits}g}" if p >= 1e-15 else "<1e-15"
    if p < 0.0001:
        return "<0.0001"
    if p > 0.9999:
        return ">0.9999"
    return f"{p:.4f}"


def stars(p: float, s: Style) -> str:
    if not isinstance(p, int | float) or not math.isfinite(p):
        return ""
    cuts = (0.0001, 0.001, 0.01, 0.05) if s.p_style == "P_VALUE_STYLE_GP" else (None, 0.001, 0.01, 0.05)
    marks = ("****", "***", "**", "*")
    for c, m in zip(cuts, marks, strict=True):
        if c is not None and p < c:
            return m
    return "ns"


# -------------------------------------------------------------------- labels
LABELS = {
    "n": "Number of values", "n1": "Number of values, first", "n2": "Number of values, second",
    "mean": "Mean", "mean1": "Mean of first", "mean2": "Mean of second", "sd": "SD", "meanSE": "SEM",
    "sem": "SEM", "meanCI": "CI of mean", "median": "Median", "medianCI": "CI of median",
    "minimum": "Minimum", "maximum": "Maximum", "range": "Range", "firstQuartile": "25% percentile",
    "thirdQuartile": "75% percentile", "sum": "Sum", "cv": "Coefficient of variation",
    "coefficientOfVariation": "Coefficient of variation", "skewness": "Skewness", "kurtosis": "Kurtosis",
    "geometricMean": "Geometric mean", "geometricSD": "Geometric SD factor", "harmonicMean": "Harmonic mean",
    "quadraticMean": "Quadratic mean", "lowerPercentile": "Lower percentile", "upperPercentile": "Upper percentile",
    "t": "t", "df": "df", "f": "F", "q": "q", "u": "Mann-Whitney U", "w": "W", "D": "D", "statistic": "Statistic",
    "dfNumerator": "DFn", "dfDenominator": "DFd", "chiSquared": "Chi-square", "z": "z",
    "ss": "SS", "ms": "MS", "r2": "R squared", "rSquared": "R squared", "r": "r",
    "difference": "Difference", "stdErrorOfDifference": "SE of difference",
    "confidenceIntervalOfDifference": "CI of difference", "meansDifference": "Mean difference",
    "meansDifferenceSE": "SE of difference", "meansDifferenceCI": "CI of difference",
    "colFactor": "Between columns", "rowFactor": "Between rows", "interaction": "Interaction",
    "residual": "Residual", "total": "Total", "subjects": "Subjects (matching)",
    "dataSummary": "Data summary", "levelCount": "Number of groups", "pointCount": "Number of values (total)",
    "matchedCount": "Number of subjects", "missingCount": "Number of missing values",
    "comparisonCount": "Number of comparisons", "significantCount": "Number significant",
    "method": "Method", "equation": "Equation", "goodnessOfFit": "Goodness of fit",
    "syx": "Sy.x", "rmse": "RMSE", "adjR2": "Adjusted R squared", "sumOfSquares": "Sum of squares",
    "parameters": "Best-fit values", "estimate": "Value", "stdError": "SE", "ci": "CI",
    "pValue": "P value", "pValueAdjusted": "Adjusted P value", "pValueExact": "Exact P value",
    "pValueIndividual": "Individual P value", "pValueOneTailed": "P value (one-tailed)",
    "descriptiveStatistics": "Descriptive statistics", "multipleComparisons": "Multiple comparisons",
    "anovaTable": "ANOVA table", "fixedEffects": "Fixed effects", "randomEffects": "Random effects",
    "curveComparison": "Comparison of survival curves", "medianSurvival": "Median survival",
    "ratios": "Hazard ratios", "ratio": "Ratio", "ratioReciprocal": "Reciprocal ratio",
    "ggEpsilon": "Geisser-Greenhouse epsilon", "factorNames": "Factor names", "warning": "Warnings",
    "xIntercept": "X intercept", "yIntercept": "Y intercept", "slope": "Slope",
    "sample1": "First", "sample2": "Second", "rankMeansDifference": "Difference of mean ranks",
    "meanRanks": "Mean rank", "sumOfRanks": "Sum of ranks", "rankSumsDifference": "Difference of rank sums",
    "missing": "Missing values", "hypotheticalValue": "Hypothetical value", "discrepancy": "Discrepancy",
    "rowFactorVsColFactor": "Interaction", "colCount": "Number of columns", "rowCount": "Number of rows",
    "isBalancedDesign": "Balanced design", "nnt": "Number needed to treat", "dAgostinoPearsonTest":
    "D'Agostino-Pearson omnibus test", "coeffOfVariation": "Coefficient of variation", "qcLines": "Quality-control lines",
    "valueCount": "Number of values", "blankRowCount": "Blank rows", "eventCount": "Events",
    "censoredCount": "Censored", "impossibleDataRowCount": "Rows with impossible data",
    "xValuesAnalyzed": "X values analyzed", "yValuesAnalyzed": "Y values analyzed",
    "yValuesSkipped": "Y values skipped", "pointsAnalyzed": "Points analyzed", "pointsSkipped": "Points skipped",
    "lfv": "Sum of squares", "isDiscovery": "Discovery?", "qValue": "q value", "ciMethod": "CI method",
    "allTestsPassed": "Passed all tests?", "variation": "% of total variation",
    "differenceBetweenColMeans": "Difference between column means",
    "differenceBetweenRowMeans": "Difference between row means", "means": "Means", "rows": "Rows", "cols": "Columns", "cells": "Cells",
    # three-way ANOVA (Prism's factor names)
    "colABCDFactor": "(AB vs CD)", "colACBDFactor": "(AC vs BD)", "rowFactorVsColABCDFactor": "Row factor x (AB vs CD)",
    "rowFactorVsColACBDFactor": "Row factor x (AC vs BD)", "colABCDFactorVsColACBDFactor": "(AB vs CD) x (AC vs BD)",
    "rowFactorVsColABCDFactorVsColACBDFactor": "Row factor x (AB vs CD) x (AC vs BD)",
    "colsABCD": "(AB vs CD)", "colsACBD": "(AC vs BD)", "colsABCDRows": "(AB vs CD) by row",
    "colsACBDRows": "(AC vs BD) by row", "colsABCDColsACBD": "(AB vs CD) by (AC vs BD)",
    "ordinaryAnovaModel": "ANOVA",
    # clustering
    "models": "Number of clusters", "iterationCount": "Iterations", "wcss": "WCSS (within-cluster sum of squares)",
    "percentOfTotalVariation": "% of total variation within clusters",
    "percentOfExplainedVariation": "% of variation explained", "silhouetteScore": "Silhouette score",
    "gap": "Gap statistic", "logWObserved": "log(W) observed", "logWExpected": "log(W) expected",
    "calinskiHarabasz": "Calinski-Harabasz", "daviesBouldin": "Davies-Bouldin", "cIndex": "C index",
    "ratkowsky": "Ratkowsky", "ballHall": "Ball-Hall", "gamma": "Gamma", "gplus": "G plus", "tau": "Tau",
    "dunn": "Dunn", "ptbiserial": "Point-biserial", "hartigan": "Hartigan", "mcclain": "McClain-Rao",
    "frey": "Frey", "krzanowskiLai": "Krzanowski-Lai", "optimalClustering": "Optimal number of clusters",
    "optimalClusterCount": "Number of clusters (most indices)", "clusterCount": "Number of clusters",
    "metrics": "By index", "copheneticCorrelation": "Cophenetic correlation", "clusters": "Clusters",
    "variablesCount": "Number of variables", "rowsTotal": "Rows in table", "rowsSkipped": "Rows skipped (missing data)",
    "rowsAnalyzed": "Rows analyzed", "columnsSkipped": "Variables skipped", "columnsAnalyzed": "Variables analyzed",
}
NAMES = {"tukey": "Tukey", "dunnett": "Dunnett", "dunnet": "Dunnett", "welch": "Welch", "brown": "Brown",
         "forsythe": "Forsythe", "bartlett": "Bartlett", "mann": "Mann", "whitney": "Whitney",
         "wilcoxon": "Wilcoxon", "kolmogorov": "Kolmogorov", "smirnov": "Smirnov", "fisher": "Fisher",
         "pearson": "Pearson", "spearman": "Spearman", "gehan": "Gehan", "breslow": "Breslow",
         "mantel": "Mantel", "cox": "Cox", "haenszel": "Haenszel", "kruskal": "Kruskal", "wallis": "Wallis",
         "friedman": "Friedman", "dunn": "Dunn", "shapiro": "Shapiro", "shapro": "Shapiro", "wilks": "Wilk",
         "wilk": "Wilk", "anderson": "Anderson", "darling": "Darling", "agostino": "D'Agostino",
         "geisser": "Geisser", "greenhouse": "Greenhouse", "holm": "Holm", "sidak": "Šídák",
         "bonferroni": "Bonferroni", "kaplan": "Kaplan", "meier": "Meier", "newman": "Newman",
         "keuls": "Keuls", "games": "Games", "howell": "Howell", "tamhane": "Tamhane", "yates": "Yates",
         "koopman": "Koopman", "logrank": "Log-rank", "huber": "Huber", "lowess": "Lowess",
         "hodges": "Hodges", "lehmann": "Lehmann", "anova": "ANOVA", "reml": "REML", "glm": "GLM", "ci": "CI", "sd": "SD", "se": "SE", "sem": "SEM",
         "auc": "AUC", "roc": "ROC", "fdr": "FDR", "lsd": "LSD", "aicc": "AICc", "x": "X", "y": "Y"}
JOIN = [("Mann Whitney", "Mann-Whitney"), ("Brown Forsythe", "Brown-Forsythe"),
        ("Kolmogorov Smirnov", "Kolmogorov-Smirnov"), ("Gehan Breslow Wilcoxon", "Gehan-Breslow-Wilcoxon"),
        ("Mantel Cox", "Mantel-Cox"), ("Mantel Haenszel", "Mantel-Haenszel"), ("Kruskal Wallis", "Kruskal-Wallis"),
        ("Shapiro Wilk", "Shapiro-Wilk"), ("Anderson Darling", "Anderson-Darling"), ("Holm Šídák", "Holm-Šídák"),
        ("Geisser Greenhouse", "Geisser-Greenhouse"), ("D'Agostino Pearson", "D'Agostino-Pearson"),
        ("Newman Keuls", "Newman-Keuls"), ("Games Howell", "Games-Howell"), ("Kaplan Meier", "Kaplan-Meier")]


def label(key: str) -> str:
    if key in LABELS:
        return LABELS[key]
    words = re.findall(r"[A-Z]{2,}(?=[A-Z][a-z]|\d|$)|[A-Z]?[a-z]+|[A-Z]|\d+", key) or [key]
    out = []
    for w in words:
        lw = w.lower()
        out.append(NAMES.get(lw, w if (w.isupper() and len(w) > 1) else lw))
    if len(out) > 1 and out[-1] == "model":
        out = out[:-1]
    s = " ".join(out)
    for a, b in JOIN:
        s = s.replace(a, b)
    s = s.replace(" t test", " t test").replace(" test test", " test")
    return s[:1].upper() + s[1:]


SPECIAL = {"undefined": "Undefined", "+inf": "Infinity", "-inf": "-Infinity", "inf": "Infinity"}


def enum_text(v: str) -> str:
    """UPPER_SNAKE enum values in words; CI method enums by the method's name."""
    if v in SPECIAL:
        return SPECIAL[v]
    if "_METHOD_" in v:
        words = v.split("_METHOD_", 1)[1].split("_")
        return " ".join(w.upper() if len(w) <= 2 else w.capitalize() for w in words)
    if re.fullmatch(r"[A-Z0-9_]+", v) and "_" in v:
        return label("".join(w.capitalize() if i else w.lower() for i, w in enumerate(v.split("_"))))
    return v


# -------------------------------------------------------------------- shapes
def is_p(v) -> bool:
    return isinstance(v, dict) and "value" in v and ("isSignificant" in v or "state" in v)


def is_ci(v) -> bool:
    return isinstance(v, dict) and "lower" in v and "upper" in v and len(set(v) - {"lower", "upper", "level"}) == 0


def is_entry(v) -> bool:
    if not (isinstance(v, dict) and "value" in v):
        return False
    i = v.get("id")
    return isinstance(i, dict) or (isinstance(i, list) and bool(i) and all(isinstance(x, dict) for x in i))


def entry_title(ident) -> str:
    if isinstance(ident, list):  # a pair, e.g. the groups of a hazard ratio
        return " / ".join(entry_title(x) for x in ident)
    parts = []
    for k in ("row", "col", "model"):
        x = ident.get(k)
        if isinstance(x, dict):
            t = x.get("title") or x.get("name")
            if t is None and "idx" in x:
                t = f"{k.capitalize()} {x['idx'] + 1}" if x["idx"] >= 0 else "X"
            if t:
                parts.append(str(t))
    for k, x in ident.items():
        if k not in ("row", "col", "model") and isinstance(x, dict) and x.get("title"):
            parts.append(str(x["title"]))
    return " · ".join(parts) or "?"


def ci_text(v: dict, s: Style) -> str:
    return f"{number(v['lower'], s)} to {number(v['upper'], s)}"


def ci_label(key: str, v: dict) -> str:
    lv = v.get("level")
    base = label(key)
    for tail in (" confidence interval", " CI"):
        if base.endswith(tail) and base != tail.strip():
            stem = base[: -len(tail)]
            base = "CI of " + (stem[:1].lower() + stem[1:] if stem[:1].isupper() and stem[1:2].islower()
                               and re.split(r"[ -]", stem)[0].lower() not in NAMES else stem)
    for head in ("Confidence interval of ", "Confidence interval "):
        if base.startswith(head):
            base = "CI of " + base[len(head):]
    if isinstance(lv, int | float):
        pct = lv * 100 if lv <= 1 else lv
        return f"{pct:g}% {base}" if base.startswith("CI") else f"{base} ({pct:g}% CI)"
    return base


# ---------------------------------------------------------------------- model
@dataclass
class Row:
    label: str
    cells: list[str]
    level: int = 0  # indent
    head: bool = False  # a section heading
    flag: str = ""  # "sig" for significant P values
    path: str = ""  # where it came from (aligns data sets side by side)


@dataclass
class Table:
    title: str
    columns: list[str]  # headers of the value columns (the label column has none)
    rows: list[Row] = field(default_factory=list)


@dataclass
class Page:
    name: str
    tables: list[Table] = field(default_factory=list)


SKIP = {"status", "$id", "@class", "id", "_errors", "factorNames",
        "points", "dendrogram", "clusteringDetails"}  # clustering: shown in its result tables


MAIN_P = {"pValue", "pValueAdjusted"}


def _p_rows(key: str, v: dict, s: Style, level: int, path: str = "") -> list[Row]:
    p = v.get("value")
    lv = v.get("level", 0.05)
    out = [Row(label(key), [p_text(p, s)], level, flag="sig" if v.get("isSignificant") else "", path=path)]
    if key in MAIN_P and isinstance(p, int | float):
        out.append(Row(f"{label(key)} summary", [stars(p, s)], level, path=path + "#stars"))
        if "isSignificant" in v:
            out.append(Row(f"Significant (P < {lv:g})?", ["Yes" if v["isSignificant"] else "No"], level,
                           path=path + "#sig"))
    return out


def _collapse(parent: str, v: dict) -> dict:
    """{"unpairedTTest": {...}} inside "unpairedTTestModel": one heading, not two."""
    out = {}
    for k, x in v.items():
        if isinstance(x, dict) and not is_p(x) and not is_ci(x) and not is_entry(x) and label(k) == parent:
            out.update(x)
        else:
            out[k] = x
    return out


def _combined(d: dict, s: Style) -> tuple[list[tuple[str, str, str]], set[str]]:
    """Statistics read together: F with its two df, t (or another statistic)
    with its df. -> [(key, label, text)], keys used."""
    out, used = [], set()
    def num(k: str) -> bool:
        return isinstance(d.get(k), int | float) and not isinstance(d.get(k), bool)

    for stat in ("f", "statistic", "w"):
        if num(stat) and num("dfNumerator") and num("dfDenominator"):
            dfs = f"{number(d['dfNumerator'], s, 'df')}, {number(d['dfDenominator'], s, 'df')}"
            out.append((stat, f"{label(stat)} (DFn, DFd)", f"{number(d[stat], s)} ({dfs})"))
            used |= {stat, "dfNumerator", "dfDenominator"}
            break
    if not used:
        for stat in ("t", "q"):
            if num(stat) and num("df"):
                out.append((stat, f"{label(stat)}, df", f"{label(stat)}={number(d[stat], s)}, df={number(d['df'], s, 'df')}"))
                used |= {stat, "df"}
                break
    return out, used


def _rows(d: dict, s: Style, level: int = 0, path: str = "") -> list[Row]:
    """Label/value rows of a results subtree (one value column)."""
    out: list[Row] = []
    combos, used = _combined(d, s)
    for k, v in d.items():
        here = f"{path}/{k}"
        if k in used:
            for ck, lab, txt in combos:
                if ck == k:
                    out.append(Row(lab, [txt], level, path=here))
            continue
        if k in SKIP:
            if k == "status" and isinstance(v, str) and v not in ("VALID", "COMPLETED"):
                out.append(Row("Note", [enum_text(v)], level, path=here))
            continue
        if is_entry(v):
            name, v = entry_title(v["id"]), v["value"]
        else:
            name = label(k)
        if is_p(v):
            out += _p_rows(k, v, s, level, here)
        elif is_ci(v):
            out.append(Row(ci_label(k, v), [ci_text(v, s)], level, path=here))
        elif isinstance(v, dict):
            sub = _rows(_collapse(name, v), s, level + 1, here)
            if sub:
                out.append(Row(name, [""], level, head=True, path=here))
                out += sub
        elif isinstance(v, list):
            if not v:
                continue
            if all(not isinstance(x, dict | list) for x in v):
                out.append(Row(name, [", ".join(enum_text(x) if isinstance(x, str) else number(x, s, k) for x in v)],
                               level, path=here))
            else:
                for i, x in enumerate(v):
                    if isinstance(x, dict):
                        sub = _rows(x, s, level + 1, f"{here}[{i}]")
                        if sub:
                            out.append(Row(f"{name} {i + 1}", [""], level, head=True, path=f"{here}[{i}]"))
                            out += sub
        elif isinstance(v, str):
            out.append(Row(name, [enum_text(v)], level, path=here))
        else:
            out.append(Row(name, [number(v, s, k)], level, path=here))
    return out


def _cells(v, s: Style, key: str = "") -> dict[str, str]:
    """Flat cells of one table row: {column label: text}."""
    out: dict[str, str] = {}
    if not isinstance(v, dict):
        return {"Value": number(v, s)} if v is not None else out
    combos, used = _combined(v, s)
    for k, x in v.items():
        if k in used:
            for ck, lab, txt in combos:
                if ck == k:
                    out[lab] = txt
            continue
        if k in SKIP:
            continue
        if is_entry(x):
            x = x["value"]
        if is_p(x):
            out[label(k)] = p_text(x.get("value"), s)
            if k in MAIN_P:
                out["Summary"] = stars(x.get("value"), s)
                if "isSignificant" in x:
                    out["Significant?"] = "Yes" if x["isSignificant"] else "No"
        elif is_ci(x):
            out[ci_label(k, x)] = ci_text(x, s)
        elif isinstance(x, dict):
            for ck, cv in _cells(x, s).items():
                name = label(k) if ck in ("Value", "Statistic") else ck
                if k in ("sample1", "sample2"):
                    name = f"{ck} ({label(k).lower()})"
                out.setdefault(name, cv)
        elif isinstance(x, list):
            continue
        else:
            out[label(k)] = enum_text(x) if isinstance(x, str) else number(x, s, k)
    return out


def _row_table(title: str, rows: list[tuple[str, dict]], s: Style) -> Table:
    """One row per item, the union of their cells as columns (first-seen order)."""
    cells = [(name, _cells(v, s)) for name, v in rows]
    cols: list[str] = []
    for _n, c in cells:
        cols += [k for k in c if k not in cols]
    return Table(title, cols, [Row(n, [c.get(k, "") for k in cols]) for n, c in cells])


def _column_table(title: str, entries: list[tuple[str, dict]], s: Style) -> Table:
    """One column per data set; rows from the first data set's layout."""
    per = [(n, _rows(v, s)) for n, v in entries]
    order: list[str] = []
    first: dict[str, Row] = {}
    for _n, rows in per:
        for r in rows:
            if r.path not in first:
                first[r.path] = r
                order.append(r.path)
    t = Table(title, [n for n, _ in per])
    look = [{r.path: r.cells[0] for r in rows} for _n, rows in per]
    for p in order:
        r = first[p]
        t.rows.append(Row(r.label, ["" if r.head else m.get(p, "") for m in look], r.level, r.head, path=p))
    return t


def _entries(v) -> list[tuple[str, dict]] | None:
    """A dict whose values are all id entries -> [(title, value)]."""
    if isinstance(v, dict) and v and all(is_entry(x) for x in v.values()):
        return [(entry_title(x["id"]), x["value"]) for x in v.values()]
    return None


def _pairs(tests: dict) -> list[tuple[str, dict]]:
    """Multiple-comparison tests nested as {item i: {item j: test}} -> rows "i vs. j"."""
    out = []
    for e in tests.values():
        if not is_entry(e):
            continue
        a = entry_title(e["id"])
        for f in (e["value"] or {}).values():
            if is_entry(f):
                out.append((f"{a} vs. {entry_title(f['id'])}", f["value"]))
    return out


def _sources(v) -> bool:
    """An ANOVA-style table: named sources, each a dict of statistics."""
    return isinstance(v, dict) and len(v) >= 2 and all(isinstance(x, dict) and not is_entry(x) and not is_p(x)
                                                        for k, x in v.items() if k not in SKIP)


TABLE_KEYS = {"anovaTable", "fixedEffects"}


def build(content: dict, params: dict | None = None, meta: list[tuple[str, str]] | None = None) -> list[Page]:
    """Pages for a results `content`. meta: rows put first on the summary
    (what was analysed)."""
    content = {k: v for k, v in content.items() if not str(k).startswith("_")}  # "_tables": shown on their own
    s = Style.of(params)
    pages: list[Page] = []
    summary = Table("", ["Value"], [Row(k, [v]) for k, v in (meta or [])])
    extra: list[Page] = []

    def visit(d: dict, level: int, into: Table, page_name: str | None = None) -> None:
        combos, used = _combined(d, s)
        for k, v in d.items():
            if k in used:
                into.rows += [Row(lab, [txt], level) for ck, lab, txt in combos if ck == k]
                continue
            if k in SKIP:
                if k == "status" and isinstance(v, dict) and v.get("error") not in (None, "VALID"):
                    into.rows.append(Row("Status", [enum_text(str(v.get("error")))], level))
                if k == "status" and isinstance(v, dict) and v.get("warning"):
                    into.rows.append(Row("Warnings", ["; ".join(enum_text(str(w)) for w in v["warning"])], level))
                continue
            ents = _entries(v)
            if ents is not None and all(not isinstance(e[1], dict | list) for e in ents):
                into.rows.append(Row(label(k), [""], level, head=True))  # e.g. row means: one row each
                into.rows += [Row(n, [number(x, s)], level + 1) for n, x in ents]
                continue
            if k == "multipleComparisons" and isinstance(v, dict):
                mc = Page("Multiple comparisons")
                info = Table("", ["Value"], _rows({a: b for a, b in v.items() if a != "tests"}, s))
                if info.rows:
                    mc.tables.append(info)
                pairs = _pairs(v.get("tests", {}) or {})
                if pairs:
                    mc.tables.append(_row_table("Comparisons", pairs, s))
                extra.append(mc)
                continue
            if k in TABLE_KEYS and _sources(v):
                for src, x in v.items():  # the F tests also on the summary
                    test = x.get("fTest") if isinstance(x, dict) else None
                    if isinstance(test, dict) and is_p(test.get("pValue")):
                        into.rows.append(Row(label(src), [""], level, head=True))
                        into.rows += _rows({a: b for a, b in test.items() if a != "status"}, s, level + 1)
                extra.append(Page(label(k), [_row_table(label(k), [(label(a), b) for a, b in v.items()
                                                                     if a not in SKIP], s)]))
                continue
            if ents is not None and len(ents) >= 1:
                kinds = {next(iter(x["id"]), "") if isinstance(x["id"], dict) else "pair" for x in v.values()}
                name = label(k) if k not in ("samples", "models", "rows") else \
                    {"samples": "Data sets", "models": "Fits", "rows": "Rows"}[k]
                if kinds <= {"col", "model"} and len(ents) <= 12 and all(isinstance(e[1], dict) for e in ents):
                    extra.append(Page(name, [_column_table(name, ents, s)]))
                else:
                    extra.append(Page(name, [_row_table(name, ents, s)]))
                continue
            if is_p(v):
                into.rows += _p_rows(k, v, s, level)
            elif is_ci(v):
                into.rows.append(Row(ci_label(k, v), [ci_text(v, s)], level))
            elif isinstance(v, dict):
                n0 = len(into.rows)
                into.rows.append(Row(label(k), [""], level, head=True))
                visit(_collapse(label(k), v), level + 1, into)
                if len(into.rows) == n0 + 1:
                    into.rows.pop()
            else:
                into.rows += _rows({k: v}, s, level)

    visit(content, 0, summary)
    if summary.rows:
        pages.append(Page("Summary", [summary]))
    pages += extra
    return pages


def text(pages: list[Page]) -> str:
    """Tab-separated text of the pages (for copying)."""
    out = []
    for p in pages:
        out.append(p.name)
        for t in p.tables:
            if t.title:
                out.append(t.title)
            out.append("\t".join(["", *t.columns]))
            out += ["\t".join(["  " * r.level + r.label, *r.cells]) for r in t.rows]
            out.append("")
    return "\n".join(out)
