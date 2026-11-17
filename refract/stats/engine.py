"""Compute an analysis from Prism's own parameter vocabulary.

    compute("T_TESTS_AND_NONPARAMETRIC", parameters["content"], [colA, colB])
returns a dict shaped like the `content` of Prism's results.json for the
parts we implement (verified field by field against Prism: tools/stats_parity.py,
tools/anova_parity.py).
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
from scipy import stats

from . import contingency as CT
from . import cox as CX
from . import deming as DM
from . import frequency as FQ
from . import logistic as LG
from . import mixed as MX
from . import multiple_comparisons as MC
from . import multiple_regression as MR
from . import multiple_t as MT
from . import nested as NSD
from . import nonlinear as NL
from . import nonlinear_global as NLG
from . import normality as NT
from . import nway as NWY
from . import one_sample as OS
from . import one_way as OW
from . import outliers as OL
from . import p_values as PV
from . import pca as PCA
from . import roc as RC
from . import smooth as SM
from . import survival as SV
from . import two_way as TW
from . import xy_basic as XB
from .descriptive import describe
from .two_sample import DESIGNS, two_sample

IMPLEMENTED = {"COLUMN_STATISTICS", "T_TESTS_AND_NONPARAMETRIC", "ONE_WAY_ANOVA", "TWO_WAY_ANOVA",
               "MULTIPLE_TWO_SAMPLE_TESTS", "ONE_SAMPLE_TESTS", "NORMALITY_TESTS",
               "FREQUENCY_DISTRIBUTION", "SURVIVAL", "CORRELATION", "SIMPLE_LINEAR_REGRESSION",
               "CONTINGENCY_TABLE", "NONLINEAR_REGRESSION", "SIMPLE_LOGISTIC_REGRESSION", "IDENTIFY_OUTLIERS",
               "BLAND_ALTMAN", "MULTI_FACTOR_ANOVA", "MULTIPLE_COX_REGRESSION", "ROC_CURVE", "AREA_UNDER_CURVE",
               "NESTED_T_TEST", "ONE_WAY_NESTED_ANOVA", "MULTIPLE_LINEAR_REGRESSION",
               "MULTIPLE_LOGISTIC_REGRESSION", "PCA", "MULTIPLE_COMPARISONS", "SMOOTH_CURVE", "DEMING_REGRESSION",
               "INTERPOLATION", "FIT_SPLINE_LOWESS", "CHI2", "HIERARCHICAL_CLUSTERING",
               "K_MEANS_CLUSTERING", "THREE_WAY_ANOVA", "DESCRIPTIVE_STATISTICS"}
# analyses whose output is a data table: refract.stats.transforms.ANALYSES

_ONE_WAY = {  # experimentalDesign -> (model function, multiple-comparison kind)
    "ORDINARY_ANOVA": (OW.ordinary, "ordinary"),
    "BROWN_FORSYTHE_ANOVA": (OW.brown_forsythe_welch, "welch"),
    "KRUSKAL_WALLIS_TEST": (OW.kruskal_wallis, "kruskal"),
    "FRIEDMAN_TEST": (OW.friedman, "friedman"),
    "REPEATED_MEASURES_ANOVA": (None, "rm"),
}
_ONE_WAY_DESC = ("n", "mean", "sd", "meanSE", "meanCI", "minimum", "firstQuartile", "median", "thirdQuartile", "maximum")


def _col_id(i: int, titles: list[str]) -> dict:
    return {"col": {"title": titles[i], "idx": i}}


def _swap(t: dict) -> dict:
    """Report a comparison as (second - first), as Prism's swapDirection."""
    t = dict(t)
    for k in ("meansDifference", "rankMeansDifference", "rankSumsDifference"):
        if k in t:
            t[k] = -t[k]
    ci = t.get("meansDifferenceCI")
    if ci and not isinstance(ci["lower"], str):
        t["meansDifferenceCI"] = {"lower": -ci["upper"], "upper": -ci["lower"], "level": ci["level"]}
    t["sample1"], t["sample2"] = t["sample2"], t["sample1"]
    return t


def _first_p(d) -> dict | None:
    """The first P value block ({"value", "isSignificant"}) of a results tree."""
    if isinstance(d, dict):
        if "isSignificant" in d and "value" in d:
            return d
        for v in d.values():
            p = _first_p(v)
            if p is not None:
                return p
    return None


def _significant(t: dict) -> bool:
    for k in ("pValueAdjusted", "pValue", "pValueMultiplicityAdjusted"):
        if isinstance(t.get(k), dict) and "isSignificant" in t[k]:
            return bool(t[k]["isSignificant"])
    return bool(t.get("isSignificant", False))


def _letters(columns, tests: dict, titles: list[str]) -> dict:
    """Prism's compact letter display of a one-way ANOVA's comparisons (E-stats8)."""
    means = [float(np.mean([v for v in c if v is not None and np.isfinite(v)])) for c in columns]
    diff = {(min(i, j), max(i, j)) for (i, j), t in tests.items() if _significant(t)}
    letters = MC.compact_letters(means, diff)
    return {"status": "VALID", "letterCount": len({x for s in letters for x in s.split()}), "sampleCount": len(columns),
            "samples": {f"col{i}": {"id": _col_id(i, titles), "value": s} for i, s in enumerate(letters)}}


def one_way(params: dict[str, Any], columns: list[list[float | None]], titles: list[str]) -> dict[str, Any]:
    design = params.get("experimentalDesign", "ORDINARY_ANOVA")
    if design not in _ONE_WAY:
        raise NotImplementedError(f"one-way design {design}")
    fn, kind = _ONE_WAY[design]
    if len(columns) < 3:
        return {"status": {"error": "INVALID_DATA_TOO_FEW_COLUMNS", "warning": []}}
    pt = params.get("postTests", {})
    pw = pt.get("pairwiseTests", {})
    mcp = pw.get("multipleComparisons", {})
    mc_type = mcp.get("type", "STATISTICAL")
    alpha = mcp.get("statistical", {}).get("options", {}).get("significanceLevel", 0.05)
    if mc_type == "NO_CORRECTION":
        alpha = mcp.get("noCorrection", {}).get("options", {}).get("significanceLevel", alpha)
    rm = params.get("repeatedMeasures", {})
    mixed = False
    if kind == "rm":
        x = OW.complete_rows(columns)
        if len(x) < max(len(c) for c in columns):  # missing values: Prism fits a mixed model (REML)
            mixed = True
            model = MX.one_way_mixed(columns, assume_sphericity=rm.get("assumeSphericity", False),
                                     remove_nonpositive=rm.get("removeNonPositiveRandomEffects", True))
            ow_warn = model.pop("_warnings")
            ow_fit = model["repeatedMeasuresRemlAnovaModel"].pop("_fit", None)
        else:
            model = OW.repeated_measures(columns, assume_sphericity=rm.get("assumeSphericity", False))
    else:
        model = fn(columns)  # the ANOVA itself is reported at 0.05 whatever the post-test alpha
    key = next(iter(model))
    body = model[key]
    if pt.get("type") == "PAIRWISE_TESTS":
        pd_ = pw.get("pairwiseDesign", {})
        pair_design = pd_.get("type", "ALL_VS_ALL")
        if pair_design not in ("ALL_VS_ALL", "CONTROL_VS_ALL", "SELECTED_VS_SELECTED"):
            raise NotImplementedError(f"pairwise design {pair_design}")
        if mc_type == "FDR" and mcp.get("fdr", {}).get("test", "BENJAMINI_KRIEGER_YEKUTIELI") != "BENJAMINI_KRIEGER_YEKUTIELI":
            raise NotImplementedError(f"FDR method {mcp['fdr']['test']}")
        control = pd_.get("controlID", {}).get("col", {}).get("idx", 0)
        method = mcp.get("statistical", {}).get("test", "TUKEY")
        pooled = {}
        if mixed and rm.get("assumeSphericity", False):
            pooled = {"ls_fit": (ow_fit["lsm"], ow_fit["lscov"], ow_fit["df"])}
        elif kind == "rm" and rm.get("assumeSphericity", False):
            resid = body.get("anovaTable", {}).get("residual", {"ms": None, "df": None})
            pooled = {"ms_error": resid["ms"], "df_error": resid["df"]}
        chosen = [(int(p[0]["col"]["idx"]), int(p[1]["col"]["idx"])) for p in pd_.get("selectedPairIDList") or []
                  if isinstance(p, list) and len(p) == 2]
        mc = MC.compare(columns, method, pair_design, kind, mc_type, alpha=alpha, control=control, titles=titles,
                        discovery_level=mcp.get("fdr", {}).get("options", {}).get("discoveryLevel", 0.05),
                        selected=chosen, **pooled)
        tests = mc.pop("tests")
        if pw.get("options", {}).get("swapDirection", False):
            tests = {(j, i): _swap(t) for (i, j), t in tests.items()}
        nested: dict[str, dict] = {}
        for (i, j), t in tests.items():
            t["sample1"] = {"id": _col_id(i, titles), "value": t.get("sample1", {}).get("value", {})}
            t["sample2"] = {"id": _col_id(j, titles), "value": t.get("sample2", {}).get("value", {})}
            nested.setdefault(f"col{i}", {"id": _col_id(i, titles), "value": {}})["value"][f"col{j}"] = {
                "id": _col_id(j, titles), "value": t}
        mc["tests"] = nested
        body["multipleComparisons"] = mc
        if pair_design == "ALL_VS_ALL" and mc_type != "FDR":
            body["compactLetterDisplay"] = _letters(columns, tests, titles)
    if mixed:  # dataSummary after the post tests, as Prism
        nmax = max(len(c) for c in columns)
        nobs = sum(1 for c in columns for v in c if v is not None and np.isfinite(v))
        body["dataSummary"] = {"levelCount": len(columns), "matchedCount": nmax, "missingCount": len(columns) * nmax - nobs}
    # descriptive statistics of each column (+ mean ranks for the rank tests)
    desc: dict[str, dict] = {}
    if kind == "kruskal":
        g = OW.clean_groups(columns)
        r = stats.rankdata(np.concatenate(g))
        off = np.cumsum([0] + [len(a) for a in g])
        mean_ranks = [float(r[off[i]:off[i + 1]].mean()) for i in range(len(g))]
    elif kind == "friedman":
        x = OW.complete_rows(columns)
        mean_ranks = [float(v) for v in np.apply_along_axis(stats.rankdata, 1, x).mean(axis=0)]
    for i, col in enumerate(columns):
        d = describe(col)
        v = {k: d[k] for k in _ONE_WAY_DESC if k in d}
        if kind in ("kruskal", "friedman"):
            v["meanRanks"] = mean_ranks[i]
        elif kind == "rm":
            v["missing"] = int(max(len(c) for c in columns) - d["n"])
        desc[f"col{i}"] = {"id": _col_id(i, titles), "value": v}
    return {"status": {"error": "VALID", "warning": ow_warn if mixed else []}, key: body, "descriptiveStatistics": desc}


_TWO_WAY = {"ORDINARY_ANOVA": None, "REPEATED_MEASURES_BY_ROWS": TW.rm_by_rows,
            "REPEATED_MEASURES_BY_COLS": TW.rm_by_cols, "REPEATED_MEASURES_BY_BOTH_FACTORS": TW.rm_by_both}


def two_way(params: dict[str, Any], columns: list[list[list[float | None]]], titles: list[str],
            row_titles: list[str] | None = None) -> dict[str, Any]:
    """columns[c][s][r]: data set c, replicate subcolumn s, row r (Prism's grouped table)."""
    design = params.get("experimentalDesign", "ORDINARY_ANOVA")
    if design not in _TWO_WAY:
        raise NotImplementedError(f"two-way design {design}")
    nr = max(len(sc) for col in columns for sc in col)
    cells = [[[col[s][r] if r < len(col[s]) else None for s in range(len(col))] for col in columns] for r in range(nr)]
    row_titles = row_titles or [f"Row {r + 1}" for r in range(nr)]
    rm = params.get("repeatedMeasures", {})
    sph = rm.get("assumeSphericity", False)
    mixed_warn: Any = None
    mixed_fit = None
    if design == "ORDINARY_ANOVA":
        model = TW.ordinary(cells, interaction=params.get("options", {}).get("includeInteractionTerm", True),
                            row_titles=row_titles, col_titles=titles)
    elif any(v is None or not np.isfinite(v) for row in cells for cell in row for v in cell):
        # missing values: Prism fits a mixed-effects model (REML) instead
        mixed_warn = MX.two_way_mixed(cells, design, assume_sphericity=sph, row_titles=row_titles, col_titles=titles,
                                      remove_nonpositive=rm.get("removeNonPositiveRandomEffects", True))
        model = {k: v for k, v in mixed_warn.items() if not k.startswith("_")}
        mixed_fit = model["repeatedMeasuresRemlAnovaModel"].pop("_fit", None)
        mixed_warn = mixed_warn["_warnings"]
    else:
        model = _TWO_WAY[design](cells, assume_sphericity=sph, row_titles=row_titles, col_titles=titles)
    key = next(iter(model))
    body = model[key]
    errors = body.pop("_errors", None)
    if errors is not None:  # RM designs: two-level difference blocks before the means
        extra = TW.rm_difference_blocks(cells, errors)
        body = {**{k: v for k, v in body.items() if k not in ("means", "dataSummary")}, **extra,
                "means": body["means"], "dataSummary": body["dataSummary"]}
    body = {"status": body["status"], "factorNames": {"rowFactor": params.get("factorNames", {}).get("rowFactor", "Row Factor"),
                                                      "colFactor": params.get("factorNames", {}).get("colFactor", "Column Factor"),
                                                      **({"matchedFactor": params.get("factorNames", {}).get("matchedFactor", "Subject")}
                                                         if design != "ORDINARY_ANOVA" else {})},
            **{k: v for k, v in body.items() if k != "status"}}
    warnings: list[str] = list(mixed_warn or [])
    pt = params.get("postTests", {})
    pw = pt.get("pairwiseTests", {})
    if pt.get("type") == "PAIRWISE_TESTS" and pw.get("meansDesignType", "NO_TESTS") != "NO_TESTS":
        mcp = pw.get("multipleComparisons", {})
        mc_type = mcp.get("type", "STATISTICAL")
        alpha = mcp.get("statistical", {}).get("options", {}).get("significanceLevel", 0.05)
        if mc_type == "NO_CORRECTION":
            alpha = mcp.get("noCorrection", {}).get("options", {}).get("significanceLevel", alpha)
        md = pw["meansDesignType"]
        pd_ = pw.get("pairwiseDesign", {})
        pair_design = pd_.get("type", "ALL_VS_ALL")
        if pair_design not in ("ALL_VS_ALL", "CONTROL_VS_ALL"):
            raise NotImplementedError(f"pairwise design {pair_design}")
        cid = pd_.get("controlID", {})
        ci, ri = cid.get("col", {}).get("idx", 0), cid.get("row", {}).get("idx", 0)
        control = {"COMPARE_COLUMNS": ci, "COMPARE_ROWS": ri, "COMPARE_CELLS": ri * len(columns) + ci}.get(md, 0)
        if md in TW.SIMPLE:  # control level within each family
            control = ri if TW.SIMPLE[md][0] else ci
        subjects, warn, run = None, None, True
        resid = body.get("anovaTable", {}).get("residual", {"ms": None, "df": None})
        two_levels = (md == "COMPARE_COLUMNS" and len(columns) == 2) or (md == "COMPARE_ROWS" and nr == 2)
        if md in TW.SIMPLE and not TW.SIMPLE[md][1]:  # separate families of a single comparison: none
            two_levels = two_levels or (nr == 2 if TW.SIMPLE[md][0] else len(columns) == 2)
        if two_levels:
            run = False  # one comparison: reported in differenceBetween...Means instead
        elif design != "ORDINARY_ANOVA":
            subjects, warn = TW.rm_subjects(design, md, cells)
            run = subjects is not None
            if warn:
                warnings.append(warn)
            if subjects == "BETWEEN" and errors is not None:
                key_ = "col" if md == "COMPARE_COLUMNS" else "row"
                resid = {"ms": errors[key_][0], "df": errors[key_][1]}
        if run:
            mc = TW.compare(cells, design, md, pw.get("multipleComparisons", {}).get("statistical", {}).get("test", "TUKEY")
                            if mc_type == "STATISTICAL" else "TUKEY", pair_design, mc_type, alpha, control,
                            row_titles, titles, resid["ms"], resid["df"],
                            mcp.get("fdr", {}).get("options", {}).get("discoveryLevel", 0.05),
                            subjects=subjects,
                            interaction=params.get("options", {}).get("includeInteractionTerm", True),
                            rm_pooled=design != "ORDINARY_ANOVA" and sph, mixed_fit=mixed_fit)
            blk = mc.pop("tests")
            items, tests = blk["items"], blk["pairs"]
            if pw.get("options", {}).get("swapDirection", False):
                tests = {(j, i): _swap(t) for (i, j), t in tests.items()}
            nested: dict[str, dict] = {}
            for (i, j), t in tests.items():
                nested.setdefault(f"item{i}", {"id": items[i][0], "value": {}})["value"][f"item{j}"] = {
                    "id": items[j][0], "value": t}
            mc["tests"] = nested
            body = {**{k: v for k, v in body.items() if k != "dataSummary"}, "multipleComparisons": mc,
                    "dataSummary": body["dataSummary"]}
    return {"status": {"error": "VALID", "warning": warnings}, key: body}


def result_table(columns: list[str], rows: list[list], row_titles: list[str] | None = None) -> dict:
    """A result table as Refract shows it (results "_tables": title -> table)."""
    return {"columns": list(columns), "rows": [list(r) for r in rows], "row_titles": row_titles}


_SUMMARY_DESC = ("n", "mean", "sd", "meanSE", "meanCI")


def from_summary(analysis_class: str, out: dict, columns: list, titles: list[str], params: dict) -> dict:
    """Results of a table of entered mean, SD and N, as Prism gives them (E-stats8): a t test adds each
    group's n, mean, SD, SEM and CI; an ANOVA leaves out the tests of equal variances and the medians
    and quartiles (none can be had from summaries)."""
    level = 100 * (1 - (params.get("options", {}) or {}).get("significanceLevel", 0.05))
    if analysis_class == "T_TESTS_AND_NONPARAMETRIC":
        desc = {}
        for i, col in enumerate(columns):
            d = describe(col, level)
            desc[f"col{i}"] = {"id": _col_id(i, titles), "value": {k: d[k] for k in _SUMMARY_DESC if k in d}}
        return {**out, "descriptiveStatistics": desc}
    if analysis_class == "ONE_WAY_ANOVA":
        out = dict(out)
        for k, body in list(out.items()):
            if isinstance(body, dict) and k.endswith("Model"):
                out[k] = {kk: vv for kk, vv in body.items() if kk not in ("brownForsytheTest", "bartlettTest")}
        if "descriptiveStatistics" in out:
            out["descriptiveStatistics"] = {c: {**e, "value": {kk: vv for kk, vv in e["value"].items()
                                                                if kk in _SUMMARY_DESC}}
                                            for c, e in out["descriptiveStatistics"].items()}
    return out


_TWO_GROUP_DESC = ("n", "mean", "sd", "meanSE", "meanCI", "minimum", "firstQuartile", "median", "thirdQuartile",
                   "maximum")


def _effect_sizes(design: str, out: dict, columns: list) -> None:
    """report.effectSizes: Cohen's d and Hedges' g in the t test's model. Paired: the mean of the
    differences over their SD, g = d (1 - 3 / (4 df - 1)), df = n - 1 (verified on Prism's own
    template). Unpaired: the difference of the means over the pooled SD, g = d (1 - 3 / (4 (n1 + n2) - 9))."""
    key = {"PAIRED_T_TEST": "pairedTTestModel", "UNPAIRED_T_TEST": "unpairedTTestModel",
           "WELCH_T_TEST": "welchTTestModel"}.get(design)
    model = out.get(key) if key else None
    if not isinstance(model, dict):
        return
    if design == "PAIRED_T_TEST":
        m = model["meanOfDifferences"]
        n = model["pairedTTest"]["df"] + 1
        d = m["mean"] / m["stdDeviationOfDifferences"] if m["stdDeviationOfDifferences"] else math.nan
        g = d * (1 - 3 / (4 * (n - 1) - 1))
    else:
        a, b = ([v for v in c if v is not None and math.isfinite(v)] for c in columns[:2])
        n1, n2 = len(a), len(b)
        v1, v2 = float(np.var(a, ddof=1)), float(np.var(b, ddof=1))
        sp = math.sqrt(((n1 - 1) * v1 + (n2 - 1) * v2) / (n1 + n2 - 2))
        d = model["differenceOfMeans"]["difference"] / sp if sp else math.nan
        g = d * (1 - 3 / (4 * (n1 + n2) - 9))
    model["effectSizes"] = {"cohenD": d, "hedgesG": g}


def two_group_descriptives(out: dict, columns: list, titles: list[str], params: dict) -> dict:
    """A t test (or its nonparametric form) of an XY or grouped table: Prism adds each group's
    descriptive statistics, and their mean ranks for a rank test (E-kinds)."""
    from scipy import stats as _st

    level = 100 * (1 - (params.get("options", {}) or {}).get("significanceLevel", 0.05))
    design = params.get("experimentalDesign", "UNPAIRED_T_TEST")
    clean = [[v for v in c if v is not None and np.isfinite(v)] for c in columns]
    ranks = None
    if design == "MANN_WHITNEY_TEST" and len(clean) == 2:  # the mean ranks of the pooled values
        r = _st.rankdata(clean[0] + clean[1])
        ranks = [float(np.mean(r[:len(clean[0])])), float(np.mean(r[len(clean[0]):]))]
    desc = {}
    for i, col in enumerate(clean):
        d = describe(col, level)
        v = {k: d[k] for k in _TWO_GROUP_DESC if k in d}
        if ranks is not None:
            v["meanRanks"] = ranks[i]
        desc[f"col{i}"] = {"id": _col_id(i, titles), "value": v}
    if design == "PAIRED_T_TEST" and len(columns) == 2:  # (checked for the paired t test)
        pairs = [(a, b) for a, b in zip(columns[0], columns[1], strict=False)
                 if a is not None and b is not None and np.isfinite(a) and np.isfinite(b)]
        d = describe([b - a for a, b in pairs], level)  # the second minus the first, as Prism
        desc["differences"] = {"id": [_col_id(1, titles), _col_id(0, titles)],
                               "value": {k: d[k] for k in _TWO_GROUP_DESC if k in d}}
    elif design == "WILCOXON_TEST" and len(columns) == 2:  # Prism: the differences, with no id (E-mv)
        pairs = [(a, b) for a, b in zip(columns[0], columns[1], strict=False)
                 if a is not None and b is not None and np.isfinite(a) and np.isfinite(b)]
        d = describe([b - a for a, b in pairs], level)
        desc["differences"] = {"value": {k: d[k] for k in _TWO_GROUP_DESC if k in d}}
    return {**out, "descriptiveStatistics": desc}


def compute(analysis_class: str, params: dict[str, Any], columns: list,
            titles: list[str] | None = None, row_titles: list[str] | None = None,
            x_values: list | None = None) -> dict[str, Any]:
    """columns: one list of values per data set; for TWO_WAY_ANOVA,
    MULTIPLE_TWO_SAMPLE_TESTS, CORRELATION and SIMPLE_LINEAR_REGRESSION, one
    list of replicate subcolumns (each a list of row values) per data set;
    for CONTINGENCY_TABLE, one list of row counts per outcome column. XY
    analyses take the X column as x_values."""
    titles = titles or [chr(65 + i) for i in range(len(columns))]
    if analysis_class == "COLUMN_STATISTICS":
        opt = params.get("options", {})
        samples = {}
        for i, col in enumerate(columns):
            samples[f"col{i}"] = {"id": {"col": {"title": titles[i], "idx": i}},
                                  "value": {"descriptiveStatistics": describe(
                                      col, opt.get("confidenceLevel", 95.0), opt.get("percentileLevel", 90.0))}}
        return {"status": {"error": "VALID", "warning": []}, "samples": samples}
    if analysis_class == "T_TESTS_AND_NONPARAMETRIC":
        design = params.get("experimentalDesign", "UNPAIRED_T_TEST")
        if design not in DESIGNS:
            raise NotImplementedError(f"two-sample design {design}")
        if len(columns) != 2:
            raise ValueError("two-sample tests need exactly two columns")
        opt = params.get("options", {})
        res = two_sample(design, columns[0], columns[1], swap=opt.get("swapDirection", True),
                         alpha=opt.get("significanceLevel", 0.05), level=100 * (1 - opt.get("significanceLevel", 0.05)))
        out = {"status": {"error": "VALID", "warning": []}, **res}
        if (params.get("report") or {}).get("effectSizes") and params.get("_mv"):  # Prism: a Multiple-variables
            _effect_sizes(design, out, columns)  # table's t test only (a column table's ignores it, E-mv)
        p = _first_p(res)
        if p is not None:  # Prism's letters: one when the two do not differ (E-stats8)
            out["compactLetterDisplay"] = _letters(columns, {(0, 1): {"pValue": p}}, titles)
        return out
    if analysis_class == "ONE_WAY_ANOVA":
        return one_way(params, columns, titles)
    if analysis_class == "TWO_WAY_ANOVA":
        return two_way(params, columns, titles, row_titles)
    if analysis_class == "SURVIVAL":  # columns: event codes per group; x_values: times
        return SV.survival(params, x_values or [], columns, titles)
    if analysis_class == "FREQUENCY_DISTRIBUTION":
        # results.json content; the histogram table and automatic bin values are
        # in refract.stats.frequency.frequency(...)["table"] / ["auto"]
        fq = FQ.frequency(params, columns, titles)
        return {**fq["results"], "_tables": {"Frequency distribution": result_table(
            ["Bin center", *titles], [[x, *(s[r] for s in fq["table"]["sets"])] for r, x in enumerate(fq["table"]["x"])])}}
    if analysis_class == "NORMALITY_TESTS":
        return NT.normality(params, columns, titles)
    if analysis_class == "ONE_SAMPLE_TESTS":
        return OS.one_sample(params, columns, titles)
    if analysis_class == "MULTIPLE_TWO_SAMPLE_TESTS":
        if len(columns) != 2:
            raise ValueError("multiple two-sample tests need exactly two data sets")
        nr = max(len(sc) for col in columns for sc in col)
        return MT.multiple_t(params, columns[0], columns[1], row_titles or [f"Row {r + 1}" for r in range(nr)])
    if analysis_class == "CORRELATION":
        # every pair of data sets: a column or Multiple-variables table, or an XY table's Y data sets
        if x_values is None or (params.get("pairwiseDesign") or {}).get("type") == "ALL_VS_ALL":
            return XB.correlation_matrix(params, columns, titles)
        return XB.correlation(params, x_values or [], columns, titles)
    if analysis_class == "SIMPLE_LINEAR_REGRESSION":
        return XB.linear_regression(params, x_values or [], columns, titles)
    if analysis_class == "CHI2":  # observed vs expected
        from . import observed_expected as OE

        return OE.observed_expected(params, columns)
    if analysis_class == "FIT_SPLINE_LOWESS":
        from . import spline as SPL

        return SPL.fit_spline(params, x_values or [], columns, titles)
    if analysis_class == "INTERPOLATION":  # a standard curve: columns [subcolumn][row] per data set
        from . import interpolation as IP

        fmt = "y_replicates" if any(len(c) > 1 for c in columns) else "y_single"
        return IP.interpolate(params, x_values or [], columns, titles, fmt)
    if analysis_class == "NONLINEAR_REGRESSION":  # columns: [subcolumn][row] per data set
        eq = params["model"]["equation"]
        fmt = "y_replicates" if any(len(c) > 1 for c in columns) else "y_single"
        if (params.get("modelComparison") or {}).get("type", "NO_COMPARISON") != "NO_COMPARISON" or \
                NLG._shared(params["model"].get("constraints")):
            return NLG.analysis(params, x_values or [], columns, titles, fmt)
        models = {f"col{i}": {"id": {"col": {"title": titles[i], "idx": i},
                                     "model": {"name": "Model 1", "title": eq.get("name", "")}},
                              "value": NL.fit_dataset(params, x_values or [], subs, i, data_format=fmt)}
                  for i, subs in enumerate(columns)}
        out = {"status": {"error": "VALID", "warning": []}, "models": models}
        outl = {k: m["value"].pop("_outliers") for k, m in models.items() if "_outliers" in m["value"]}
        fits = [m["value"] for m in models.values()]
        if all(isinstance(f.get("parameters", {}).get(p, {}).get("estimate"), float) for f in fits
               for p in eq.get("parameters", [])):
            out["_tables"] = {"Curve": NL.curve_table(params, x_values or [], columns, titles, fits, data_format=fmt)}
        if outl:  # ROUT elimination: Prism's top-level outliers entry per data set
            out["outliers"] = {k: {"id": {"col": dict(models[k]["id"]["col"])}, "value": v} for k, v in outl.items()}
        return out
    if analysis_class == "SIMPLE_LOGISTIC_REGRESSION":  # columns: [Y outcomes]; x_values: X
        y = columns[0][0] if columns and isinstance(columns[0], list) and columns[0] and isinstance(columns[0][0], list) \
            else columns[0]
        return LG.simple_logistic(params, x_values or [], y)
    if analysis_class == "IDENTIFY_OUTLIERS":
        return OL.identify_outliers(params, columns)["results"]
    if analysis_class == "BLAND_ALTMAN":
        return OL.bland_altman(params, columns)["results"]
    if analysis_class == "ROC_CURVE":  # columns: one list of values per data set
        return RC.roc_curve(params, columns)
    if analysis_class == "AREA_UNDER_CURVE":  # columns: Y data sets; x_values: X (None: row numbers)
        return RC.area_under_curve(params, x_values, columns)
    if analysis_class == "NESTED_T_TEST":  # columns: per group, its subcolumns (lists of values)
        return NSD.nested_t(params, columns)
    if analysis_class == "ONE_WAY_NESTED_ANOVA":
        return NSD.nested_one_way(params, columns)
    if analysis_class == "MULTIPLE_COX_REGRESSION":  # columns: the multiple-variables table
        return CX.cox_from_params(params, columns, titles)
    if analysis_class == "MULTI_FACTOR_ANOVA":  # columns: the multiple-variables table, one list per variable
        return NWY.from_params(params, columns, titles)
    if analysis_class == "MULTIPLE_LINEAR_REGRESSION":  # columns: the multiple-variables table
        return MR.multiple_linear(params, columns, titles)
    if analysis_class == "MULTIPLE_LOGISTIC_REGRESSION":
        return MR.multiple_logistic(params, columns, titles)
    if analysis_class == "DEMING_REGRESSION":  # columns: each Y data set (replicates averaged); x_values: X
        return DM.deming(params, x_values or [], columns, titles)
    if analysis_class == "SMOOTH_CURVE":  # columns: each Y data set (replicates averaged); x_values: X
        return SM.smooth_curve(params, x_values or [], columns, titles)
    if analysis_class == "MULTIPLE_COMPARISONS":  # a stack of P values: the first column
        return PV.stack(params, columns)
    if analysis_class == "DESCRIPTIVE_STATISTICS":  # a Multiple-variables table: each numeric variable
        opt = params.get("options", {}) or {}
        calc = params.get("calc", {}) or {}
        samples = {}
        for i, col in enumerate(columns):
            vals = [v for v in col if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)]
            if any(isinstance(v, str) for v in col) or not vals:  # a categorical variable: not described
                continue
            d = describe(vals, opt.get("confidenceLevel", 95.0), opt.get("percentileLevel", 90.0))
            if not calc.get("geometricMean"):
                for k in ("geometricMean", "geometricMeanCI", "geometricSD"):
                    d.pop(k, None)
            from .descriptive import extras

            d.update(extras(vals, opt.get("confidenceLevel", 95.0), calc))
            q1, q3 = d.get("firstQuartile"), d.get("thirdQuartile")
            if isinstance(q1, float) and isinstance(q3, float):  # Prism: Tukey's fences
                d["iqr"] = {"iqr": q3 - q1, "q1MinusIQR": q1 - 1.5 * (q3 - q1), "q3PlusIQR": q3 + 1.5 * (q3 - q1)}
            samples[f"col{i}"] = {"id": {"col": {"title": titles[i], "idx": i}}, "value": d}
        return {"status": {"error": "VALID", "warning": []}, "samples": samples}
    if analysis_class == "THREE_WAY_ANOVA":  # columns: per data set its replicate subcolumns
        from .three_way import three_way

        return three_way(params, columns, titles, row_titles)
    if analysis_class == "HIERARCHICAL_CLUSTERING":  # columns: the multiple-variables table
        from . import clustering as CL

        return CL.hierarchical(params, columns, titles)
    if analysis_class == "K_MEANS_CLUSTERING":
        from . import clustering as CL

        return CL.k_means(params, columns, titles)
    if analysis_class == "PCA":  # the results only; the loadings/scores tables: refract.stats.pca.pca
        return PCA.pca(params, columns, titles)["results"]
    if analysis_class == "CONTINGENCY_TABLE":
        nr = max(len(c) for c in columns)
        table = [[(c[r] if r < len(c) and c[r] is not None else 0) for c in columns] for r in range(nr)]
        return CT.contingency(params, table)
    raise NotImplementedError(analysis_class)
