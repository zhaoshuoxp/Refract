"""Multifactor (n-way) ANOVA (Prism: MULTI_FACTOR_ANOVA) on a multiple-variables
table: fixed categorical factors, the model terms of
`model.predictor.definition`, Type III sums of squares from effect-coded
regressors (as refract.stats.two_way). Result keys from Prism 11.1
(verified on a Prism-computed two-factor document; Prism does not compute
this analysis under script automation, so larger designs are checked
against the general linear model only).
"""

from __future__ import annotations

import itertools
import math

import numpy as np
from scipy import stats


def _p(value: float, alpha: float = 0.05) -> dict:
    return {"value": float(value), "level": alpha, "isSignificant": bool(value < alpha), "state": "P_VALUE_EQUAL"}


def _effect(idx: np.ndarray, k: int) -> np.ndarray:
    x = np.zeros((len(idx), k - 1))
    for j in range(k - 1):
        x[idx == j, j] = 1.0
    x[idx == k - 1, :] = -1.0
    return x


def _term_matrix(term, codes, levels):
    """Effect-coded regressors of a term (product over its factors)."""
    if not term:
        return np.ones((len(codes[0]) if codes else 0, 1))
    mats = [_effect(codes[f], levels[f]) for f in term]
    out = mats[0]
    for m in mats[1:]:
        out = np.einsum("ni,nj->nij", out, m).reshape(out.shape[0], -1)
    return out


def _sse(x, y):
    beta, *_ = np.linalg.lstsq(x, y, rcond=None)
    r = y - x @ beta
    return float(r @ r), beta


def multifactor(y, factors: list[list], names: list[str], terms: list[list[int]], level_orders=None) -> dict:
    """y: response values; factors[f]: level labels per row; terms: lists of
    factor indices (the empty list = intercept). Rows with a missing value
    are dropped."""
    keep = [i for i, v in enumerate(y) if v is not None and math.isfinite(v)
            and all(f[i] not in (None, "") for f in factors)]
    yv = np.array([float(y[i]) for i in keep])
    codes, levels = [], []
    for fi, f in enumerate(factors):
        order = level_orders[fi] if level_orders else list(dict.fromkeys(f[i] for i in keep))
        codes.append(np.array([order.index(f[i]) for i in keep]))
        levels.append(len(order))
    blocks = [_term_matrix(t, codes, levels) for t in terms]
    full = np.hstack(blocks)
    sse_full, beta = _sse(full, yv)
    n = len(yv)
    df_res = n - np.linalg.matrix_rank(full)
    ms_res = sse_full / df_res
    sst = float(((yv - yv.mean()) ** 2).sum())
    fixed = []
    for ti, t in enumerate(terms):
        if not t:
            continue
        reduced = np.hstack([b for j, b in enumerate(blocks) if j != ti])
        ss = _sse(reduced, yv)[0] - sse_full
        df = blocks[ti].shape[1]
        ms = ss / df
        f = ms / ms_res
        pe2 = ss / (ss + sse_full)
        fixed.append({"name": " : ".join(names[i] for i in t), "ss": ss, "df": float(df), "ms": ms, "variation": ss / sst,
                      "partialEta2": pe2, "CohenF": math.sqrt(pe2 / (1 - pe2)),
                      "fTest": {"status": "VALID", "f": f, "dfNumerator": float(df), "dfDenominator": float(df_res),
                                "pValue": _p(stats.f.sf(f, df, df_res))}})
    out = {"status": {"error": "VALID", "warning": []}, "parameters": [float(b) for b in beta],
           "ordinaryModel": {"status": "VALID", "anovaTable": {
               "fixedEffects": fixed, "residuals": {"ss": sse_full, "df": float(df_res), "ms": ms_res},
               "total": {"ss": sst, "df": float(n - 1)}}},
           "dataSummary": {"pointCount": n}}
    out["_fit"] = {"beta": beta, "xtx_inv": np.linalg.pinv(full.T @ full), "ms_res": ms_res, "df_res": float(df_res),
                   "terms": terms, "levels": levels, "orders": [list(dict.fromkeys(f[i] for i in keep)) for f in factors],
                   "y": yv, "codes": codes}
    return out


def _lsmean_row(fit, f, level):
    """Design row of the least-squares mean of level `level` of factor f
    (average of the cell predictions over the other factors' levels)."""
    levels = fit["levels"]
    grids = [range(k) if i != f else [level] for i, k in enumerate(levels)]
    cells = np.array(list(itertools.product(*grids)))
    codes = [cells[:, i] for i in range(len(levels))]
    rows = np.hstack([_term_matrix(t, codes, levels) if t else np.ones((len(cells), 1)) for t in fit["terms"]])
    return rows.mean(axis=0)


def post_tests(params: dict, fit: dict, columns, titles, resp_ref: dict, factor_refs: list[dict]) -> dict | None:
    """Comparisons of the levels of one factor against a control level
    (pairwiseTests.design CONTROL_VS_ALL): LS means, SE from the residual MS
    and (X'X)^-1, df residual, Dunnett (verified on a Prism-made sample)."""
    from . import multiple_comparisons as MC

    pt = params.get("postTests", {})
    pw = pt.get("pairwiseTests", {})
    if pt.get("type") != "PAIRWISE_TESTS" or pw.get("design") != "CONTROL_VS_ALL":
        return None
    ctl = pw["ctrlVsAll"]["controlID"]["var"]
    fl = ctl["factorList"]
    if len(fl) != 1:
        raise NotImplementedError("post tests on factor combinations")
    fidx_col = fl[0]["var"]["idx"]
    f = [r["col"]["idx"] for r in factor_refs].index(fidx_col)
    order = fit["orders"][f]
    c = order.index(fl[0]["value"])
    mcp = pw["ctrlVsAll"]["multipleComparisons"]
    method = mcp.get("statistical", {}).get("test", "DUNNET")
    alpha = mcp.get("statistical", {}).get("options", {}).get("significanceLevel", 0.05)
    rows = [_lsmean_row(fit, f, lv) for lv in range(len(order))]
    est = [float(r @ fit["beta"]) for r in rows]
    cov = np.array(rows) @ fit["xtx_inv"] @ np.array(rows).T * fit["ms_res"]
    prs = [(c, j) for j in range(len(order)) if j != c]
    raw = []
    for i, j in prs:
        d = est[i] - est[j]
        se = math.sqrt(cov[i, i] + cov[j, j] - 2 * cov[i, j])
        t = abs(d) / se
        raw.append((i, j, d, se, t, fit["df_res"], float(2 * stats.t.sf(t, fit["df_res"]))))
    lam = [math.sqrt(0.5)] * len(prs) if method == "DUNNET" else None
    tests, name, _ = MC.adjust_family(raw, method, mcp.get("type", "STATISTICAL"), alpha, len(order), np.array(est), prs, lam)

    def ident(lv):
        return {"var": {"response": dict(resp_ref), "factorList": [{"var": {k: v for k, v in fl[0]["var"].items()},
                                                                     "value": order[lv]}]}}

    out_tests = {}
    for (i, j), tv in tests.items():
        pa = tv.get("pValueAdjusted")
        if pa and isinstance(pa["value"], float) and pa["value"] < 1e-15:  # Prism's floor (verified)
            tv["pValueAdjusted"] = {**pa, "value": 1e-15, "state": "P_VALUE_LESS"}
        sel = [k for k, lv in enumerate(fit["codes"][f]) if lv == i], [k for k, lv in enumerate(fit["codes"][f]) if lv == j]
        tv["sample1"] = {"id": ident(i), "value": {"mean": float(fit["y"][sel[0]].mean()), "n": len(sel[0])}}
        tv["sample2"] = {"id": ident(j), "value": {"mean": float(fit["y"][sel[1]].mean()), "n": len(sel[1])}}
        out_tests[f"{i}-{j}"] = {"id": [ident(i), ident(j)], "value": tv}
    return {"status": "VALID", "method": name, "familyCount": 1, "comparisonPerFamilyCount": len(prs), "tests": out_tests}


def from_params(params: dict, columns: list[list], titles: list[str]) -> dict:
    """columns: the multiple-variables table, one list per variable."""
    m = params["model"]
    yi = m["response"]["variable"]["id"]["col"]["idx"]
    fidx = [v["id"]["col"]["idx"] for v in m["predictor"]["variables"]]
    if any(v.get("effectType", "FIXED") != "FIXED" for v in m["predictor"]["variables"]):
        raise NotImplementedError("random factors")
    terms = [[t["varIdx"] for t in term] for term in m["predictor"]["definition"]]
    y = [float(v) if v not in (None, "") else None for v in columns[yi]]
    out = multifactor(y, [columns[i] for i in fidx], [titles[i] for i in fidx], terms)
    fit = out.pop("_fit")
    mc = post_tests(params, fit, columns, titles, m["response"]["variable"]["id"]["col"],
                    [v["id"] for v in m["predictor"]["variables"]])
    if mc is not None:
        out = {k: v for k, v in out.items() if k != "dataSummary"} | {"multipleComparisons": mc,
                                                                       "dataSummary": out["dataSummary"]}
    return out


def full_factorial(k: int) -> list[list[int]]:
    return [[]] + [list(c) for r in range(1, k + 1) for c in itertools.combinations(range(k), r)]
