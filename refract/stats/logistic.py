"""Simple logistic regression (Prism: SIMPLE_LOGISTIC_REGRESSION) with
Prism's result keys (verified against Prism 11.1: tools/logistic_parity.py).

Maximum likelihood (Newton-Raphson); profile-likelihood intervals for the
coefficients, the odds ratios and X at 50 %; likelihood-ratio tests; Tjur
and Cox-Snell R squared; ROC area of the fitted probabilities.
"""

from __future__ import annotations

import math

import numpy as np
from scipy import optimize, stats


def _p(value: float, alpha: float = 0.05) -> dict:  # alpha = 1 - confidence level / 100
    return {"value": float(value), "level": alpha, "isSignificant": bool(value < alpha), "state": "P_VALUE_EQUAL"}


def _loglik(beta, x, y):
    eta = beta[0] + beta[1] * x
    return float(np.sum(y * eta - np.logaddexp(0, eta)))


def fit(x, y, fixed: dict | None = None, start=None):
    """ML fit; fixed = {index: value} holds a coefficient (profiles)."""
    b = np.zeros(2) if start is None else np.array(start, float)
    free = [i for i in range(2) if not fixed or i not in fixed]
    if fixed:
        for i, v in fixed.items():
            b[i] = v
    xm = np.column_stack([np.ones_like(x), x])
    for _ in range(200):
        p = 1 / (1 + np.exp(-(xm @ b)))
        g = xm.T @ (y - p)
        h = (xm * (p * (1 - p))[:, None]).T @ xm
        gf, hf = g[free], h[np.ix_(free, free)]
        step = np.linalg.solve(hf, gf)
        b_new = b.copy()
        b_new[free] += step
        while _loglik(b_new, x, y) < _loglik(b, x, y) - 1e-12:  # step halving
            step /= 2
            b_new = b.copy()
            b_new[free] += step
            if np.abs(step).max() < 1e-15:
                break
        b = b_new
        if np.abs(step).max() < 1e-13 * (1 + np.abs(b).max()):
            break
    p = 1 / (1 + np.exp(-(xm @ b)))
    h = (xm * (p * (1 - p))[:, None]).T @ xm
    return b, _loglik(b, x, y), h


def _profile(x, y, b, ll, j, level, crit=None):
    crit = crit if crit is not None else stats.chi2.ppf(level / 100, 1)
    target = ll - crit / 2

    def g(v):
        return fit(x, y, {j: v}, start=b)[1] - target

    se = math.sqrt(np.linalg.inv(fit(x, y)[2])[j, j])
    ends = []
    for sgn in (-1, 1):
        a, step = b[j], se
        bb = a + sgn * step
        for _ in range(60):
            if g(bb) < 0:
                break
            a, step = bb, step * 2
            bb = b[j] + sgn * step
        ends.append(optimize.brentq(g, min(a, bb), max(a, bb), xtol=1e-14, rtol=1e-14))
    return ends[0], ends[1]


def _x50_profile(x, y, b, ll, level):
    """Profile interval of X at 50 % = -b0/b1: reparametrise b0 = -x50 * b1."""
    crit = stats.chi2.ppf(level / 100, 1)
    target = ll - crit / 2
    x50 = -b[0] / b[1]

    def prof(v):  # max over b1 of loglik with b0 = -v * b1: logit = b1 (x - v), Newton in b1
        z = x - v

        def ll1(b1):
            return _loglik(np.array([-v * b1, b1]), x, y)

        b1 = b[1]
        for _ in range(200):  # Newton with step halving (the log-likelihood is concave in b1)
            pr = 1 / (1 + np.exp(-b1 * z))
            g = float(z @ (y - pr))
            hh = float((z * z) @ (pr * (1 - pr)))
            if hh <= 0:
                break
            step = g / hh
            cur = ll1(b1)
            while ll1(b1 + step) < cur and abs(step) > 1e-15:
                step /= 2
            b1 += step
            if abs(step) < 1e-14 * (1 + abs(b1)):
                break
        return ll1(b1) - target

    span = max(abs(x50), 1.0)
    ends = []
    for sgn in (-1, 1):
        a, step = x50, 0.05 * span
        for _ in range(80):
            bb = x50 + sgn * step
            if prof(bb) < 0:
                ends.append(optimize.brentq(prof, min(a, bb), max(a, bb), xtol=1e-13, rtol=1e-13))
                break
            a, step = bb, step * 1.6
        else:
            ends.append(None)
    return ends


def roc_area(scores, y):
    """ROC area (Mann-Whitney) and Prism's SE: Hanley & McNeil (1982) with
    Q1, Q2 computed from the data, ties broken at random (verified):
    Q1 = mean over controls of g^2 + g e + e^2 / 3 (g, e: fraction of
    patients above / tied with the control), Q2 likewise over patients."""
    pos, neg = np.asarray(scores)[y == 1], np.asarray(scores)[y == 0]
    return roc_area_groups(pos, neg)


def roc_area_groups(pos, neg):
    pos, neg = np.asarray(pos, float), np.asarray(neg, float)
    n1, n0 = len(pos), len(neg)
    gt01 = (pos[None, :] > neg[:, None]).mean(axis=1)
    eq01 = (pos[None, :] == neg[:, None]).mean(axis=1)
    gt10 = (pos[:, None] > neg[None, :]).mean(axis=1)
    eq10 = (pos[:, None] == neg[None, :]).mean(axis=1)
    a = float((gt10 + 0.5 * eq10).mean())
    q1 = float(np.mean(gt01 ** 2 + gt01 * eq01 + eq01 ** 2 / 3))
    q2 = float(np.mean(gt10 ** 2 + gt10 * eq10 + eq10 ** 2 / 3))
    var = (a * (1 - a) + (n1 - 1) * (q1 - a * a) + (n0 - 1) * (q2 - a * a)) / (n1 * n0)
    return a, math.sqrt(max(var, 0.0))


def _mw_p(scores, y) -> float:
    """P of the ROC area: the Mann-Whitney normal approximation (no continuity
    correction, no tie correction) of positives vs negatives (verified)."""
    pos, neg = scores[y == 1], scores[y == 0]
    n1, n0 = len(pos), len(neg)
    r = stats.rankdata(np.concatenate([pos, neg]))
    u = r[:n1].sum() - n1 * (n1 + 1) / 2
    n = n1 + n0
    var = n1 * n0 * (n + 1) / 12  # no tie correction (verified)
    return float(2 * stats.norm.sf(abs(u - n1 * n0 / 2) / math.sqrt(var)))


def _not_converged(level, summary) -> dict:
    u = "undefined"
    ci = {"lower": u, "upper": u, "level": level}
    pars = {"β0": {"estimate": u, "se": u, "ci": dict(ci)},
            "β1": {"estimate": u, "se": u, "ci": dict(ci), "significanceTest": {"status": "INVALID"}},
            "X when Y=50%": {"estimate": u, "se": u, "ci": dict(ci)}}
    model = {"status": "INTERRUPTED", "isFitStable": False, "equation": "", "parameters": pars,
             "oddsRatios": {k: {"estimate": u, "ci": dict(ci)} for k in ("β0", "β1")},
             "goodnessOfFit": {"r2TJ": u, "r2CS": u, "deviance": u}}
    value = {"model": model,
             "rocAnalysis": {"status": "INVALID", "area": u, "se": u, "ci": {"lower": u, "upper": u, "level": 95.0},
                             "pValue": {"value": u, "level": 0.05, "isSignificant": False, "state": "P_VALUE_EQUAL"}},
             "hypothesisTests": {"likelihoodRatioTest": {"status": "INVALID"}}, "dataSummary": summary}
    return {"status": {"error": "VALID", "warning": ["NOT_CONVERGED"]},
            "models": {"col0": {"id": {"col": {"title": "Y", "idx": 0}}, "value": value}}}


def simple_logistic(params: dict, x, y) -> dict:
    opt = params.get("options", {})
    calc = params.get("calc", {})
    level = opt.get("confidenceLevel", 95.0)
    alpha = 1 - level / 100
    pts = [(float(a), float(b)) for a, b in zip(x, y, strict=False)
           if a is not None and b is not None and math.isfinite(a) and math.isfinite(b)]
    rows_total = sum(1 for v in y if v is not None and math.isfinite(v))  # rows with an outcome (verified)
    xa = np.array([p[0] for p in pts])
    ya = np.array([p[1] for p in pts])
    n = len(ya)
    k1 = int(ya.sum())
    summary = {"rowsTotal": rows_total, "rowsSkipped": rows_total - n, "rowsAnalyzed": n,
               "outcome1Count": k1, "outcome0Count": n - k1, "parTotal": 2,
               "observationsParRatio": n / 2, "observations1ParRatio": k1 / 2,
               "observations0ParRatio": (n - k1) / 2}
    x0, x1 = xa[ya == 0], xa[ya == 1]
    if len(x0) == 0 or len(x1) == 0 or x0.max() < x1.min() or x1.max() < x0.min():
        return _not_converged(level, summary)  # complete separation: the ML estimate does not exist
    b, ll, h = fit(xa, ya)
    cov = np.linalg.inv(h)
    se = np.sqrt(np.diag(cov))
    p0 = ya.mean()
    ll0 = float(n * (p0 * math.log(p0) + (1 - p0) * math.log(1 - p0)))
    g2 = 2 * (ll - ll0)
    ci = [_profile(xa, ya, b, ll, j, level) for j in range(2)]
    x50 = -b[0] / b[1]
    grad = np.array([-1 / b[1], b[0] / b[1] ** 2])
    se50 = float(math.sqrt(grad @ cov @ grad))
    lo50, hi50 = _x50_profile(xa, ya, b, ll, level)

    def c(lo, hi):
        return {"lower": "undefined" if lo is None else float(lo), "upper": "undefined" if hi is None else float(hi),
                "level": level}

    pars = {"β0": {"estimate": float(b[0]), "se": float(se[0]), "ci": c(*ci[0])},
            "β1": {"estimate": float(b[1]), "se": float(se[1]), "ci": c(*ci[1]),
                   "significanceTest": {"status": "VALID", "statistic": g2, "pValue": _p(stats.chi2.sf(g2, 1), alpha)}},
            "X when Y=50%": {"estimate": float(x50), "se": se50, "ci": c(lo50, hi50)}}
    ors = {k: {"estimate": math.exp(b[j]), "ci": c(math.exp(ci[j][0]), math.exp(ci[j][1]))}
           for j, k in enumerate(("β0", "β1"))}
    phat = 1 / (1 + np.exp(-(b[0] + b[1] * xa)))
    gof = {}
    if calc.get("r2TJ", True):
        gof["r2TJ"] = float(phat[ya == 1].mean() - phat[ya == 0].mean())
    if calc.get("r2CS", True):
        gof["r2CS"] = float(1 - math.exp(-g2 / n))
    if calc.get("deviance", True):
        gof["deviance"] = float(-2 * ll)
    model = {"status": "COMPLETED", "isFitStable": True,
             "equation": f"log odds = {b[0]:.4g}{'+' if b[1] >= 0 else ''}{b[1]:.4g}*X",
             "parameters": pars, "oddsRatios": ors, "goodnessOfFit": gof}
    value = {"model": model}
    if calc.get("rocCurve", True):
        a, sa = roc_area(phat, ya)
        z = stats.norm.ppf(1 - (1 - level / 100) / 2)
        value["rocAnalysis"] = {"status": "VALID", "area": a, "se": sa,
                                "ci": {"lower": max(0.0, a - z * sa), "upper": min(1.0, a + z * sa), "level": level},
                                "pValue": _p(_mw_p(phat, ya), alpha)}
    if calc.get("likelihoodRatioTest", True):
        value["hypothesisTests"] = {"likelihoodRatioTest": {"status": "VALID", "statistic": g2,
                                                            "pValue": _p(stats.chi2.sf(g2, 1), alpha)}}
    value["dataSummary"] = summary
    return {"status": {"error": "VALID", "warning": []},
            "models": {"col0": {"id": {"col": {"title": "Y", "idx": 0}}, "value": value}}}
