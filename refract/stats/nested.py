"""Nested t test (Prism: NESTED_T_TEST) and nested one-way ANOVA
(ONE_WAY_NESTED_ANOVA): REML with a random nested factor (the subcolumns
of each group), with Prism's result keys (verified against Prism 11.1:
tools/nested_parity.py).

groups[g][s] = values of subcolumn s of group (data set) g.
Denominator df: nested subcolumns - groups (Prism's legacy rule).
"""

from __future__ import annotations

import math

import numpy as np
from scipy import stats

from .mixed import Reml, _effect, _p, _wald


def _fit(groups):
    ys, gi, si = [], [], []
    for g, subs in enumerate(groups):
        for s, vals in enumerate(subs):
            for v in vals:
                if v is not None and math.isfinite(v):
                    ys.append(float(v))
                    gi.append(g)
                    si.append((g, s))
    y, gi = np.array(ys), np.array(gi)
    n, k = len(y), len(groups)
    x = np.hstack([np.ones((n, 1)), _effect(gi, k)])
    keys = sorted(set(si))
    z = np.zeros((n, len(keys)))
    for i, s in enumerate(si):
        z[i, keys.index(s)] = 1.0
    full = Reml(y, x, [z]).fit()
    null = Reml(y, x, []).fit()
    return y, x, full, null, len(keys), k


def _common(groups, alpha):
    y, x, f, null, n_sub, k = _fit(groups)
    s2, g = f["s2"], float(f["g"][0])
    chi = 2 * (null["nll"] - f["nll"])
    random_effects = {"nestedFactor": {"sd": math.sqrt(g * s2), "variance": g * s2},
                      "residual": {"sd": math.sqrt(s2), "variance": s2}}
    nesting = {"status": "VALID", "chiSquared": float(chi), "df": 1.0, "pValue": _p(stats.chi2.sf(chi, 1), alpha)}
    summary = {"treatmentCount": k, "matchedCount": n_sub, "pointCount": len(y)}
    return y, x, f, n_sub, k, random_effects, nesting, summary


def nested_t(params: dict, groups) -> dict:
    opt = params.get("options", {})
    alpha = opt.get("significanceLevel", 0.05)
    y, x, f, n_sub, k, re_, nesting, summary = _common(groups, alpha)
    df = n_sub - k
    beta, cov = f["beta"], f["cov"]
    m = [float(beta[0] + beta[1]), float(beta[0] - beta[1])]
    se = 2 * math.sqrt(cov[1, 1])
    diff = m[0] - m[1]
    if opt.get("swapDirection", True):  # second minus first (verified)
        m, diff = [m[1], m[0]], -diff
    t = diff / se
    fstat = t * t
    tc = stats.t.ppf(1 - alpha / 2, df)
    p = float(2 * stats.t.sf(abs(t), df))
    level = 100 * (1 - alpha)
    n = len(y)
    model = {"status": "VALID", "fitStatus": "CONVERGED",
             "fixedEffects": {"colFactor": {"tTest": {"status": "VALID", "t": abs(t), "df": float(df), "pValue": _p(p, alpha)},
                                            "fTest": {"status": "VALID", "f": fstat, "dfNumerator": 1.0,
                                                      "dfDenominator": float(df), "pValue": _p(p, alpha)}}},
             "randomEffects": re_,
             "differenceOfMeans": {"mean1": m[0], "mean2": m[1], "difference": diff, "stdErrorOfDifference": se,
                                   "confidenceIntervalOfDifference": {"lower": diff - tc * se, "upper": diff + tc * se,
                                                                      "level": level}},
             "nestingTest": nesting,
             "goodnessOfFit": {"df": float(n - x.shape[1] - 2),
                               "remlCriterion": float(f["nll"] + (n - x.shape[1]) / 2 * math.log(2 * math.pi))},
             "dataSummary": summary}
    return {"status": {"error": "VALID", "warning": []}, "tTestModel": model}


def nested_one_way(params: dict, groups) -> dict:
    alpha = 0.05
    _, _, f, n_sub, k, re_, nesting, summary = _common(groups, alpha)
    df = n_sub - k
    fstat = _wald(f["beta"], f["cov"], list(range(1, k)))
    model = {"status": "VALID", "fitStatus": "CONVERGED",
             "fixedEffects": {"colFactor": {"fTest": {"status": "VALID", "f": fstat, "dfNumerator": float(k - 1),
                                                      "dfDenominator": float(df),
                                                      "pValue": _p(stats.f.sf(fstat, k - 1, df), alpha)}}},
             "randomEffects": re_, "nestingTest": nesting, "dataSummary": summary}
    return {"status": {"error": "VALID", "warning": []}, "anovaModel": model}
