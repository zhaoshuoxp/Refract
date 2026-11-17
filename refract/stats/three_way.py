"""Three-way ANOVA (Prism: THREE_WAY_ANOVA) of a grouped table, with Prism's
result keys (verified against Prism 11.1, E-three-way).

The four data sets A, B, C, D cross two two-level factors - "AB vs CD" (A and
B against C and D) and "AC vs BD" - and the rows are the third factor. The
model holds the three main effects and every interaction; each term's sum of
squares is Type III (the full model against the model without it, with
effect coding), which for a balanced design equals the classic partition.
"""

from __future__ import annotations

import itertools
import math

import numpy as np
from scipy import stats

TERMS = [  # (key, factors) in Prism's order
    ("rowFactor", ("r",)), ("colABCDFactor", ("a",)), ("colACBDFactor", ("b",)),
    ("rowFactorVsColABCDFactor", ("r", "a")), ("rowFactorVsColACBDFactor", ("r", "b")),
    ("colABCDFactorVsColACBDFactor", ("a", "b")), ("rowFactorVsColABCDFactorVsColACBDFactor", ("r", "a", "b")),
]


def _p(v: float, alpha: float) -> dict:
    return {"value": float(v), "level": alpha, "isSignificant": bool(v < alpha), "state": "P_VALUE_EQUAL"}


def _effect(levels: np.ndarray, k: int) -> np.ndarray:
    """Sum-to-zero coding of a factor with k levels: k - 1 columns."""
    out = np.zeros((len(levels), k - 1))
    for j in range(k - 1):
        out[:, j] = (levels == j).astype(float)
    out[levels == k - 1, :] = -1.0
    return out


def _sse(x: np.ndarray, y: np.ndarray) -> float:
    beta, *_ = np.linalg.lstsq(x, y, rcond=None)
    r = y - x @ beta
    return float(r @ r)


def three_way(params: dict, columns: list, titles: list[str], row_titles: list[str] | None = None) -> dict:
    """columns: per data set (A, B, C, D) its replicate subcolumns, each a list over the rows."""
    design = params.get("experimentalDesign", "ORDINARY_ANOVA")
    if design != "ORDINARY_ANOVA":
        raise NotImplementedError(f"three-way ANOVA design {design}")
    if len(columns) != 4:
        raise ValueError("three-way ANOVA needs four data sets (two levels of each column factor)")
    alpha = float(((((params.get("postTests") or {}).get("pairwiseTests") or {}).get("multipleComparisons") or {})
                   .get("statistical") or {}).get("options", {}).get("significanceLevel", 0.05))
    if all(len(ds) <= 1 for ds in columns):  # Prism: one value per cell is not analysed
        return {"status": {"error": "INVALID_DATA_TABLE_FORMAT_NO_REPLICATES", "warning": []}}
    n_rows = max((len(sub) for ds in columns for sub in ds), default=0)
    obs = []  # (row, a, b, y)
    for j, ds in enumerate(columns):
        for sub in ds:
            for r, v in enumerate(sub):
                if v is not None and isinstance(v, (int, float)) and math.isfinite(v):
                    obs.append((r, 0 if j < 2 else 1, j % 2, float(v)))
    rows_used = sorted({o[0] for o in obs})
    remap = {r: i for i, r in enumerate(rows_used)}
    kr = len(rows_used)
    if kr < 2 or not obs:
        return {"status": {"error": "NOT_ENOUGH_DATA", "warning": []}}
    lv = {"r": np.array([remap[o[0]] for o in obs]), "a": np.array([o[1] for o in obs]),
          "b": np.array([o[2] for o in obs])}
    ks = {"r": kr, "a": 2, "b": 2}
    y = np.array([o[3] for o in obs])
    coded = {f: _effect(lv[f], ks[f]) for f in lv}
    blocks = {}
    for key, fs in TERMS:
        cols = [np.prod(np.column_stack(c), axis=1) for c in itertools.product(*[coded[f].T for f in fs])]
        blocks[key] = np.column_stack(cols)
    full = np.column_stack([np.ones(len(y)), *blocks.values()])
    sse = _sse(full, y)
    n = len(y)
    df_res = n - np.linalg.matrix_rank(full)
    names = (params.get("factorNames") or {})
    label = {"r": names.get("rowFactor", "Row factor"), "a": names.get("colABCDFactor", "(AB vs CD)"),
             "b": names.get("colACBDFactor", "(AC vs BD)")}
    ms_res = sse / df_res if df_res > 0 else math.nan
    table, ss_all = {}, []
    for key, fs in TERMS:
        reduced = np.column_stack([np.ones(len(y)), *(b for k, b in blocks.items() if k != key)])
        ss = _sse(reduced, y) - sse
        df = float(blocks[key].shape[1])
        entry = {"name": " x ".join(label[f] for f in fs), "ss": ss, "df": df, "ms": ss / df}
        if df_res > 0 and ms_res > 0:
            f = (ss / df) / ms_res
            entry["fTest"] = {"status": "VALID", "f": f, "dfNumerator": df, "dfDenominator": float(df_res),
                              "pValue": _p(float(stats.f.sf(f, df, df_res)), alpha)}
        table[key] = entry
        ss_all.append(ss)
    total = float(((y - y.mean()) ** 2).sum())  # % of the total variation (unbalanced too: verified)
    for key, _ in TERMS:
        table[key] = {k: v for k, v in table[key].items() if k != "fTest"} | \
            {"variation": 100 * table[key]["ss"] / total if total else 0.0} | \
            ({"fTest": table[key]["fTest"]} if "fTest" in table[key] else {})
    table["residual"] = {"ss": sse, "df": float(df_res), "ms": ms_res}
    counts = {}
    for o in obs:
        counts[(remap[o[0]], o[1], o[2])] = counts.get((remap[o[0]], o[1], o[2]), 0) + 1
    balanced = len(counts) == kr * 4 and len(set(counts.values())) == 1
    model = {"status": "VALID", "factorNames": label, "anovaTable": table}
    if (params.get("report") or {}).get("means"):
        model["means"] = _means(obs, remap, rows_used, titles, row_titles)
    model["dataSummary"] = {"rowCount": n_rows, "isBalancedDesign": balanced}
    return {"status": {"error": "VALID", "warning": []}, "ordinaryAnovaModel": model}


def _means(obs, remap, rows_used, titles, row_titles) -> dict:
    """Prism's means: unweighted means of the cell means (verified with missing values). A level of
    "AB vs CD" is named by data set A or C, of "AC vs BD" by A or B."""
    cells: dict = {}
    for r, a, b, v in obs:
        cells.setdefault((remap[r], a, b), []).append(v)
    cm = {k: float(np.mean(v)) for k, v in cells.items()}

    def mean(pred):
        vals = [v for k, v in cm.items() if pred(k)]
        return float(np.mean(vals)) if vals else math.nan

    def col(j):
        return {"col": {"title": titles[j] if j < len(titles) else "", "idx": j}}

    def row(i):
        r = rows_used[i]
        return {"row": {"idx": r, "title": (row_titles[r] if row_titles and r < len(row_titles) else "")}}

    a_ids, b_ids = (col(0), col(2)), (col(0), col(1))
    rows = range(len(rows_used))
    return {
        "total": mean(lambda k: True),
        "rows": {f"row{i}": {"id": row(i), "value": mean(lambda k, i=i: k[0] == i)} for i in rows},
        "colsABCD": {f"a{a}": {"id": a_ids[a], "value": mean(lambda k, a=a: k[1] == a)} for a in (0, 1)},
        "colsACBD": {f"b{b}": {"id": b_ids[b], "value": mean(lambda k, b=b: k[2] == b)} for b in (0, 1)},
        "colsABCDRows": {f"a{a}": {"id": a_ids[a], "value": {
            f"row{i}": {"id": row(i), "value": mean(lambda k, a=a, i=i: k[1] == a and k[0] == i)} for i in rows}}
            for a in (0, 1)},
        "colsACBDRows": {f"b{b}": {"id": b_ids[b], "value": {
            f"row{i}": {"id": row(i), "value": mean(lambda k, b=b, i=i: k[2] == b and k[0] == i)} for i in rows}}
            for b in (0, 1)},
        "colsABCDColsACBD": {f"a{a}": {"id": a_ids[a], "value": {
            f"b{b}": {"id": b_ids[b], "value": mean(lambda k, a=a, b=b: k[1] == a and k[2] == b)} for b in (0, 1)}}
            for a in (0, 1)},
        "cells": {f"a{a}": {"id": a_ids[a], "value": {f"b{b}": {"id": b_ids[b], "value": {
            f"row{i}": {"id": row(i), "value": cm.get((i, a, b), math.nan)} for i in rows}} for b in (0, 1)}}
            for a in (0, 1)},
    }
