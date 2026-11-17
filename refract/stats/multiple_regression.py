"""Multiple linear regression (Prism: MULTIPLE_LINEAR_REGRESSION) and multiple
logistic regression (MULTIPLE_LOGISTIC_REGRESSION) on a multiple-variables
table, with Prism's result keys (verified against a Prism-made sample and
tools/multreg_parity.py).
"""

from __future__ import annotations

import math

import numpy as np
from scipy import optimize, stats

from . import normality as NT
from .cox import design


def _p(value: float, alpha: float = 0.05) -> dict:
    return {"value": float(value), "level": alpha, "isSignificant": bool(value < alpha), "state": "P_VALUE_EQUAL"}


def _matrix(params, columns, titles, extra_cols=()):
    m = params["model"]
    comps = [c for c in m["modelDef"] if c.get("componentType") != "INTERCEPT"]
    intercept = any(c.get("componentType") == "INTERCEPT" for c in m["modelDef"])
    xcols, names = design(columns, titles, m.get("variableInfo", []), comps)
    yi = m["dependentVariable"]["col"]["idx"]
    keep = [r for r in range(len(columns[yi])) if columns[yi][r] not in (None, "")
            and all(c[r] is not None for c in xcols) and all(columns[i][r] not in (None, "") for i in extra_cols)]
    x = np.array([[c[r] for c in xcols] for r in keep], float).reshape(len(keep), len(xcols))
    if intercept:
        x = np.hstack([np.ones((len(keep), 1)), x])
        names = ["Intercept", *names]
    # one component per model term, mapped to its columns (categoricals span several)
    comp_cols, pos = [], 1 if intercept else 0
    for c in comps:
        i = c["variables"][0]["col"]["idx"]
        n_c = sum(1 for nm in names[pos:] if nm == titles[i] or nm.startswith(titles[i] + "["))
        comp_cols.append((titles[i], list(range(pos, pos + n_c))))
        pos += n_c
    return x, names, keep, yi, intercept, comp_cols


def _vif(x, intercept):
    out_vif, out_r2 = {}, {}
    p = x.shape[1]
    for j in range(p):
        key = f"β{j}" if intercept else f"β{j + 1}"
        if intercept and j == 0:
            out_vif[key], out_r2[key] = "undefined", "undefined"
            continue
        others = np.delete(x, j, axis=1)
        coef, *_ = np.linalg.lstsq(others, x[:, j], rcond=None)
        res = x[:, j] - others @ coef
        tot = x[:, j] - x[:, j].mean() if intercept else x[:, j]
        r2 = float(1 - (res @ res) / (tot @ tot))
        out_r2[key], out_vif[key] = r2, 1 / (1 - r2)
    return {"vif": out_vif, "r2": out_r2}


def multiple_linear(params: dict, columns, titles) -> dict:
    conf, diag = params.get("confidence", {}), params.get("diagnostics", {})
    level, alpha = conf.get("confidenceLevel", 95.0), diag.get("alpha", 0.05)
    x, names, keep, yi, intercept, comp_cols = _matrix(params, columns, titles)
    y = np.array([float(columns[yi][r]) for r in keep])
    n, p = x.shape
    xtx_inv = np.linalg.inv(x.T @ x)
    b = xtx_inv @ x.T @ y
    res = y - x @ b
    ss = float(res @ res)
    df = n - p
    ms = ss / df
    cov = xtx_inv * ms
    se = np.sqrt(np.diag(cov))
    tc = stats.t.ppf(1 - (1 - level / 100) / 2, df)
    keys = [f"β{j}" if intercept else f"β{j + 1}" for j in range(p)]
    wald = conf.get("ciMethod", "PROFILE_LIKELIHOOD") != "PROFILE_LIKELIHOOD"
    pars = {}
    for j, k in enumerate(keys):
        t = b[j] / se[j]
        pars[k] = {"variableName": names[j], "estimate": float(b[j]), "se": float(se[j]) if wald else "undefined",
                   "ci": {"lower": float(b[j] - tc * se[j]), "upper": float(b[j] + tc * se[j]), "level": level}}
        if diag.get("parSignificanceTest", True):
            pars[k]["significanceTest"] = {"status": "VALID", "statistic": float(abs(t)),
                                           "pValue": _p(2 * stats.t.sf(abs(t), df), alpha)}
    model = {"status": "COMPLETED", "fitStatus": "CONVERGED", "isFitStable": True, "parameters": pars}
    if diag.get("parMulticollinearity"):
        model["multcollinearity"] = _vif(x, intercept)
    if diag.get("parCorrelation"):
        sd = np.sqrt(np.diag(cov))
        corr = cov / np.outer(sd, sd)
        model["covariance"] = {a: {c: float(corr[ia, ic]) for ic, c in enumerate(keys)} for ia, a in enumerate(keys)}
    ybar = y.mean() if intercept else 0.0
    sst = float(((y - ybar) ** 2).sum())
    ssr = sst - ss
    df_reg = p - (1 if intercept else 0)
    f = (ssr / df_reg) / ms
    comps = {}
    for name, cols_ in comp_cols:
        xr = np.delete(x, cols_, axis=1)
        br, *_ = np.linalg.lstsq(xr, y, rcond=None)
        rr = y - xr @ br
        ssc = float(rr @ rr) - ss
        dfc = len(cols_)
        fc = (ssc / dfc) / ms
        comps[name] = {"ss": ssc, "ms": ssc / dfc,
                       "fStatistic": {"f": fc, "dfNumerator": float(dfc), "dfDenominator": float(df),
                                      "pValue": _p(stats.f.sf(fc, dfc, df), alpha)}}
    anova = {"regression": {"ss": ssr, "ms": ssr / df_reg,
                            "fStatistic": {"f": f, "dfNumerator": float(df_reg), "dfDenominator": float(df),
                                           "pValue": _p(stats.f.sf(f, df_reg, df), alpha)}},
             "componentList": comps, "residual": {"ss": ss, "df": float(df), "ms": ms},
             "total": {"ss": sst, "df": float(n - (1 if intercept else 0))}}
    r2 = 1 - ss / sst
    k = p + 1
    gof = {"df": float(df), "multipleR": math.sqrt(max(r2, 0.0)), "r2": r2,
           "adjR2": 1 - (1 - r2) * (n - (1 if intercept else 0)) / df, "ss": ss, "syx": math.sqrt(ms),
           "rmse": math.sqrt(ss / (n - 1)), "aicc": n * math.log(ss / n) + 2 * k + 2 * k * (k + 1) / (n - k - 1)}
    out = {"equation": "", "anovaTable": anova, "model": model, "goodnessOfFit": gof}
    nt = {}
    for flag, key, fn in (("normalityTestDP", "dAgostinoPearsonTest", NT.dagostino_pearson),
                          ("normalityTestAD", "andersonDarlingTest", NT.anderson_darling),
                          ("normalityTestSW", "shapiroWilkTest", NT.shapiro_wilk),
                          ("normalityTestKS", "kolmogorovSmirnovTest", NT.kolmogorov_smirnov)):
        if diag.get(flag):
            nt[key] = fn(res, alpha)
    if nt:
        out["normalityTests"] = nt
    total = len(columns[yi])
    summary = {"rowsTotal": total, "rowsSkipped": total - n, "rowsAnalyzed": n, "parTotal": p, "casesParRatio": n / p}
    warn = []
    if params.get("interpolation", {}).get("fromData"):
        xi = {v["col"]["idx"] for c in params["model"]["modelDef"] for v in c.get("variables", [])}
        nrows = max(len(c) for c in columns)
        unknown = [r for r in range(nrows) if (r >= len(columns[yi]) or columns[yi][r] in (None, ""))
                   and all(r < len(columns[i]) and columns[i][r] not in (None, "") for i in xi)]
        if not unknown:  # nothing to interpolate (verified)
            warn.append("INTERPOLATION_UNDEFINED_VARIABLE")
    return {"status": {"error": "VALID", "warning": warn}, "models": {"Model 1": out}, "dataSummary": summary}


# --------------------------------------------------------------- logistic
def _loglik(b, x, y):
    eta = x @ b
    return float(np.sum(y * eta - np.logaddexp(0, eta)))


def _fit_logit(x, y, fixed=None, start=None):
    p = x.shape[1]
    b = np.zeros(p) if start is None else np.array(start, float)
    free = [i for i in range(p) if not fixed or i not in fixed]
    if fixed:
        for i, v in fixed.items():
            b[i] = v
    for _ in range(200):
        pr = 1 / (1 + np.exp(-(x @ b)))
        g = x.T @ (y - pr)
        h = (x * (pr * (1 - pr))[:, None]).T @ x
        if not free:
            break
        step = np.linalg.solve(h[np.ix_(free, free)], g[free])
        cur = _loglik(b, x, y)
        nb = b.copy()
        nb[free] += step
        while _loglik(nb, x, y) < cur - 1e-12 and np.abs(step).max() > 1e-15:
            step /= 2
            nb = b.copy()
            nb[free] += step
        b = nb
        if np.abs(step).max() < 1e-13 * (1 + np.abs(b).max()):
            break
    pr = 1 / (1 + np.exp(-(x @ b)))
    h = (x * (pr * (1 - pr))[:, None]).T @ x
    return b, _loglik(b, x, y), h


def hosmer_lemeshow(p, y, groups: int = 10):
    """Hosmer-Lemeshow: groups bounded by the deciles of the predicted
    probabilities (Weibull quantiles, (n+1)p; tied probabilities stay
    together), group i holding q_i < p <= q_(i+1); chi2 with groups - 2 df
    (verified on a Prism sample with ties and 4 Prism runs without: only this
    quantile rule fits all)."""
    q = np.quantile(p, np.linspace(0, 1, groups + 1), method="weibull")
    chi = 0.0
    for i in range(groups):
        sel = (p > q[i]) if i else (p >= q[0])
        idx = np.where(sel & (p <= q[i + 1]))[0]
        if not len(idx):
            continue
        o, e, m = y[idx].sum(), p[idx].sum(), len(idx)
        chi += (o - e) ** 2 / (e * (1 - e / m)) if 0 < e < m else 0.0
    return float(chi), groups - 2


def multiple_logistic(params: dict, columns, titles) -> dict:
    from .logistic import _mw_p, roc_area_groups

    m = params["model"]
    conf, diag = params.get("confidence", {}), params.get("diagnostics", {})
    level, alpha = conf.get("confidenceLevel", 95.0), diag.get("alpha", 0.05)
    x, names, keep, yi, intercept, _ = _matrix(params, columns, titles)
    ylab = [columns[yi][r] for r in keep]
    info = {v["variable"]["col"]["idx"]: v for v in m.get("variableInfo", [])}
    levels = list(dict.fromkeys(v for v in columns[yi] if v not in (None, "")))
    yinfo = info.get(yi, {})
    o0 = (m.get("outcome0") or {}).get("value")
    if o0 in levels and (m.get("outcome1") or {}).get("value") in levels:  # the model's coding wins (verified)
        ref = o0
    elif yinfo.get("referenceLevelType", "AUTO_FIRST_LEVEL") == "AUTO_FIRST_LEVEL":
        ref = levels[0]
    else:
        ref = yinfo.get("referenceLevelValue", levels[0])
    other = next(v for v in levels if v != ref)
    y = np.array([0.0 if v == ref else 1.0 for v in ylab])
    n, p = x.shape
    b, ll, h = _fit_logit(x, y)
    cov = np.linalg.inv(h)
    se = np.sqrt(np.diag(cov))
    p0 = y.mean()
    ll0 = float(n * (p0 * math.log(p0) + (1 - p0) * math.log(1 - p0)))
    keys = [f"β{j}" if intercept else f"β{j + 1}" for j in range(p)]
    z = stats.norm.ppf(1 - (1 - level / 100) / 2)
    profile = conf.get("ciMethod", "PROFILE_LIKELIHOOD") == "PROFILE_LIKELIHOOD"
    crit = stats.chi2.ppf(level / 100, 1)
    cis = []
    for j in range(p):
        if not profile:
            cis.append((b[j] - z * se[j], b[j] + z * se[j]))
            continue

        def gfun(v, j=j):
            return _fit_logit(x, y, {j: v}, start=b)[1] - (ll - crit / 2)

        ends = []
        for sgn in (-1, 1):
            a_, step = b[j], se[j]
            bb = a_ + sgn * step
            for _ in range(60):
                if gfun(bb) < 0:
                    break
                a_, step = bb, step * 2
                bb = b[j] + sgn * step
            ends.append(optimize.brentq(gfun, min(a_, bb), max(a_, bb), xtol=1e-14, rtol=1e-14))
        cis.append(tuple(ends))
    se_out = ["undefined"] * p if profile else [float(s) for s in se]
    pars, ors = {}, {}
    for j, k in enumerate(keys):
        pars[k] = {"variableName": names[j], "estimate": float(b[j]), "se": se_out[j],
                   "ci": {"lower": float(cis[j][0]), "upper": float(cis[j][1]), "level": level}}
        ors[k] = {"variableName": names[j], "estimate": math.exp(b[j]),
                  "se": "undefined" if profile else float(math.exp(b[j]) * se[j]),
                  "ci": {"lower": math.exp(cis[j][0]), "upper": math.exp(cis[j][1]), "level": level}}
        if diag.get("parSignificanceTest"):
            zz = b[j] / se[j]
            pars[k]["significanceTest"] = {"status": "VALID", "statistic": float(abs(zz)),
                                           "pValue": _p(2 * stats.norm.sf(abs(zz)), alpha)}
    model = {"status": "COMPLETED", "fitStatus": "CONVERGED", "isFitStable": True, "parameters": pars}
    sd = np.sqrt(np.diag(cov))
    corr = cov / np.outer(sd, sd)
    model["covariance"] = {a: {c: float(corr[ia, ic]) for ic, c in enumerate(keys)} for ia, a in enumerate(keys)}
    if diag.get("parMulticollinearity"):
        model["multcollinearity"] = _vif(x, intercept)
    out = {"equation": "", "model": model}
    if diag.get("oddsRatio", True):
        out["oddsRatios"] = ors

    def aicc(ll_, k):
        return -2 * ll_ + 2 * k + 2 * k * (k + 1) / (n - k - 1)

    out["modelDiagnostics"] = {
        "nullModel": {"df": float(n - 1), "aicc": aicc(ll0, 1), "logLikelihood": -ll0, "deviance": -2 * ll0},
        "selectedModel": {"df": float(n - p), "aicc": aicc(ll, p), "logLikelihood": -ll, "deviance": -2 * ll}}
    pr = 1 / (1 + np.exp(-(x @ b)))
    if diag.get("roc", True):
        a, sa = roc_area_groups(pr[y == 1], pr[y == 0])
        out["rocAnalysis"] = {"status": "VALID", "area": a, "se": sa,
                              "ci": {"lower": max(0.0, a - z * sa), "upper": min(1.0, a + z * sa), "level": level},
                              "pValue": _p(_mw_p(pr, y), alpha)}
    if diag.get("classificationTable", True):
        cut = diag.get("classificationCutoff", 0.5)
        pred = pr >= cut
        tab = {}
        for lab, obs in (("observed0", 0.0), ("observed1", 1.0)):
            sel = y == obs
            p1 = int((pred & sel).sum())
            tot = int(sel.sum())
            tab[lab] = {"predicted0": tot - p1, "predicted1": p1, "total": tot,
                        "percentCorrect": 100 * ((tot - p1) if obs == 0 else p1) / tot}
        out["classificationTable"] = tab
    lr = 2 * (ll - ll0)
    cs = 1 - math.exp(-lr / n)
    out["r2"] = {"r2TJ": float(pr[y == 1].mean() - pr[y == 0].mean()), "r2MF": 1 - ll / ll0, "r2CS": cs,
                 "r2NA": cs / (1 - math.exp(2 * ll0 / n))}
    ht = {}
    if diag.get("hlTest"):
        chi, dfh = hosmer_lemeshow(pr, y)
        ht["hlTest"] = {"status": "VALID", "statistic": chi, "pValue": _p(stats.chi2.sf(chi, dfh), alpha)}
    if diag.get("likelihoodRatioTest"):
        ht["likelihoodRatioTest"] = {"status": "VALID", "statistic": lr, "pValue": _p(stats.chi2.sf(lr, p - 1), alpha)}
    if ht:
        out["hypothesisTests"] = ht
    total = len(columns[yi])
    k1 = int(y.sum())
    summary = {"outcome0Label": ref, "outcome1Label": other, "rowsTotal": total, "rowsSkipped": total - n,
               "rowsAnalyzed": n, "outcome0Count": n - k1, "outcome1Count": k1, "parTotal": p,
               "observationsParRatio": n / p, "observations0ParRatio": (n - k1) / p, "observations1ParRatio": k1 / p}
    return {"status": {"error": "VALID", "warning": []}, "models": {"Model 1": out}, "dataSummary": summary}
