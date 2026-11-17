"""Cox proportional-hazards regression (Prism: MULTIPLE_COX_REGRESSION) on a
multiple-variables table, with Prism's result keys (verified against Prism
11.1: tools/cox_parity.py).

Efron's handling of tied event times; Newton-Raphson on the partial
log-likelihood; Wald or profile-likelihood intervals; categorical
covariates as indicators against the reference (first) level.
"""

from __future__ import annotations

import math

import numpy as np
from scipy import optimize, stats


def _p(value: float, alpha: float = 0.05) -> dict:
    return {"value": float(value), "level": alpha, "isSignificant": bool(value < alpha), "state": "P_VALUE_EQUAL"}


def partial_loglik(beta, t, d, x, grad: bool = False):
    """Efron partial log-likelihood (and gradient, Hessian)."""
    eta = x @ beta
    w = np.exp(eta)
    ll = 0.0
    p = x.shape[1]
    g = np.zeros(p)
    h = np.zeros((p, p))
    for tt in np.unique(t[d == 1]):
        ev = (t == tt) & (d == 1)
        risk = t >= tt
        m = int(ev.sum())
        s0r, s1r = w[risk].sum(), (w[risk, None] * x[risk]).sum(axis=0)
        s2r = (x[risk].T * w[risk]) @ x[risk]
        s0e, s1e = w[ev].sum(), (w[ev, None] * x[ev]).sum(axis=0)
        s2e = (x[ev].T * w[ev]) @ x[ev]
        ll += float(eta[ev].sum())
        g += x[ev].sum(axis=0)
        for k in range(m):
            f = k / m
            s0 = s0r - f * s0e
            s1 = s1r - f * s1e
            s2 = s2r - f * s2e
            ll -= math.log(s0)
            mu = s1 / s0
            g -= mu
            h -= s2 / s0 - np.outer(mu, mu)
    return (ll, g, h) if grad else ll


def fit(t, d, x, fixed: dict | None = None, start=None):
    p = x.shape[1]
    b = np.zeros(p) if start is None else np.array(start, float)
    free = [i for i in range(p) if not fixed or i not in fixed]
    if fixed:
        for i, v in fixed.items():
            b[i] = v
    ll, g, h = partial_loglik(b, t, d, x, True)
    for _ in range(100):
        if not free:
            break
        step = np.linalg.solve(-h[np.ix_(free, free)], g[free])
        nb = b.copy()
        nb[free] += step
        nll = partial_loglik(nb, t, d, x)
        while nll < ll - 1e-12 and np.abs(step).max() > 1e-15:
            step /= 2
            nb = b.copy()
            nb[free] += step
            nll = partial_loglik(nb, t, d, x)
        b = nb
        ll, g, h = partial_loglik(b, t, d, x, True)
        if np.abs(step).max() < 1e-12 * (1 + np.abs(b).max()):
            break
    return b, ll, h


def harrell_c(t, d, risk):
    """Harrell's C: an event at t_i is comparable with every later time and
    with censored observations at the same time; tied risks count 1/2
    (verified)."""
    num = den = 0.0
    n = len(t)
    for i in range(n):
        if not d[i]:
            continue
        for j in range(n):
            if j != i and (t[j] > t[i] or (t[j] == t[i] and not d[j])):
                den += 1
                num += 1.0 if risk[i] > risk[j] else 0.5 if risk[i] == risk[j] else 0.0
    return num / den if den else math.nan


def design(columns, titles, info, model_def):
    """-> (X, column names, variable of each column)."""
    cols, names = [], []
    kinds = {v["variable"]["col"]["idx"]: v for v in info}
    for comp in model_def:
        if comp.get("componentType", "ADDITIVE") != "ADDITIVE" or len(comp["variables"]) != 1:
            raise NotImplementedError("Cox model terms other than additive main effects")
        i = comp["variables"][0]["col"]["idx"]
        k = kinds.get(i, {"variableType": "CONTINUOUS"})
        vals = columns[i]
        if k["variableType"] == "CATEGORICAL":
            levels = list(dict.fromkeys(v for v in vals if v not in (None, "")))  # entry order
            ref = levels[0] if k.get("referenceLevelType", "AUTO_FIRST_LEVEL") == "AUTO_FIRST_LEVEL" \
                else k.get("referenceLevelValue", levels[0])
            if ref in levels:
                levels.remove(ref)
                levels.insert(0, ref)
            for lv in levels[1:]:
                cols.append([None if v in (None, "") else (1.0 if v == lv else 0.0) for v in vals])
                names.append(f"{titles[i]}[{lv}]")
        else:
            cols.append([None if v in (None, "") else float(v) for v in vals])
            names.append(titles[i])
    return cols, names


def _level(v) -> str:
    """An outcome as text: 1.0 and "1" alike (a numeric event column)."""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def cox_from_params(params: dict, columns, titles) -> dict:
    m = params["model"]
    conf = params.get("confidence", {})
    diag = params.get("diagnostics", {})
    level = conf.get("confidenceLevel", 95.0)
    alpha = diag.get("alpha", 0.05)
    ti, di = m["timeVariable"]["col"]["idx"], m["dependentVariable"]["col"]["idx"]
    one = m.get("outcome1", {}).get("value", "1")
    xcols, names = design(columns, titles, m.get("variableInfo", []), m["modelDef"])
    n_total = len(columns[ti])
    keep = [r for r in range(n_total) if columns[ti][r] not in (None, "") and columns[di][r] not in (None, "")
            and all(c[r] is not None for c in xcols)]
    t = np.array([float(columns[ti][r]) for r in keep])
    d = np.array([1 if _level(columns[di][r]) == _level(one) else 0 for r in keep])
    x = np.array([[c[r] for c in xcols] for r in keep], float)
    p = x.shape[1]
    b, ll, h = fit(t, d, x)
    cov = np.linalg.inv(-h)
    se = np.sqrt(np.diag(cov))
    ll0 = partial_loglik(np.zeros(p), t, d, x)
    z = stats.norm.ppf(1 - (1 - level / 100) / 2)
    keys = [f"β{j + 1}" for j in range(p)]
    if conf.get("ciMethod", "PROFILE_LIKELIHOOD") == "PROFILE_LIKELIHOOD":
        crit = stats.chi2.ppf(level / 100, 1)
        cis = []
        for j in range(p):
            def gfun(v, j=j):
                return fit(t, d, x, {j: v}, start=b)[1] - (ll - crit / 2)

            ends = []
            for sgn in (-1, 1):
                a_, step = b[j], se[j]
                bb = a_ + sgn * step
                for _ in range(60):
                    if gfun(bb) < 0:
                        break
                    a_, step = bb, step * 2
                    bb = b[j] + sgn * step
                ends.append(optimize.brentq(gfun, min(a_, bb), max(a_, bb), xtol=1e-13, rtol=1e-13))
            cis.append(tuple(ends))
        se_out = ["undefined"] * p
    else:
        cis = [(b[j] - z * se[j], b[j] + z * se[j]) for j in range(p)]
        se_out = [float(s) for s in se]
    # per-parameter test: Wald z with Wald intervals, likelihood ratio (drop the term) with profile intervals
    profile = conf.get("ciMethod", "PROFILE_LIKELIHOOD") == "PROFILE_LIKELIHOOD"
    tests = []
    for j in range(p):
        if profile:
            stat = 2 * (ll - fit(t, d, x, {j: 0.0}, start=b)[1])
            tests.append({"status": "VALID", "statistic": float(stat), "pValue": _p(stats.chi2.sf(stat, 1), alpha)})
        else:
            zz = b[j] / se[j]
            tests.append({"status": "VALID", "statistic": float(abs(zz)), "pValue": _p(2 * stats.norm.sf(abs(zz)), alpha)})
    pars = {k: {"variableName": names[j], "estimate": float(b[j]), "se": se_out[j],
                "ci": {"lower": float(cis[j][0]), "upper": float(cis[j][1]), "level": level}}
            for j, k in enumerate(keys)}
    if diag.get("parSignificanceTest"):
        for j, k in enumerate(keys):
            pars[k]["significanceTest"] = tests[j]
    sd = np.sqrt(np.diag(cov))
    corr = cov / np.outer(sd, sd)
    model = {"status": "COMPLETED", "fitStatus": "CONVERGED", "isFitStable": True, "parameters": pars}
    # the parameters' correlations: Prism reports them whatever parCorrelation says (corpus: cox_try, cx0)
    model["covariance"] = {a: {c: float(corr[ia, ic]) for ic, c in enumerate(keys)} for ia, a in enumerate(keys)}
    if diag.get("parMulticollinearity") and p == 1:
        model["multcollinearity"] = {"vif": {keys[0]: 1.0}, "r2": {keys[0]: 0.0}}
    elif diag.get("parMulticollinearity"):
        # R2 of each regressor on the others, without intercept (uncentred; verified), VIF = 1 / (1 - R2)
        r2 = {}
        for j, k in enumerate(keys):
            others = np.delete(x, j, axis=1)
            coef, *_ = np.linalg.lstsq(others, x[:, j], rcond=None)
            res = x[:, j] - others @ coef
            r2[k] = float(1 - (res @ res) / (x[:, j] @ x[:, j]))
        model["multcollinearity"] = {"vif": {k: 1 / (1 - v) for k, v in r2.items()}, "r2": r2}
    out_model: dict = {"equation": "", "model": model, "tiesMethod": "EFRON"}
    if diag.get("hazardRatio", True):
        out_model["hazardRatios"] = {k: {"variableName": names[j], "estimate": math.exp(b[j]),
                                         "se": "undefined" if se_out[j] == "undefined" else float(math.exp(b[j]) * se[j]),
                                         "ci": {"lower": math.exp(cis[j][0]), "upper": math.exp(cis[j][1]), "level": level},
                                         **({"significanceTest": tests[j]} if diag.get("parSignificanceTest") else {})}
                                     for j, k in enumerate(keys)}
    n = len(t)
    events = int(d.sum())
    lr = 2 * (ll - ll0)
    nm, sm = {"parameterCount": float(n - 1)}, {"parameterCount": float(n - p)}
    if diag.get("aic", True):
        nm["aic"], sm["aic"] = float(-2 * ll0), float(-2 * ll + 2 * p)
    if diag.get("logLikelihood"):  # Prism reports minus the log partial likelihood
        nm["logLikelihood"], sm["logLikelihood"] = float(-ll0), float(-ll)
    if diag.get("neg2logLikelihood"):
        nm["neg2logLikelihood"], sm["neg2logLikelihood"] = float(-2 * ll0), float(-2 * ll)
    if diag.get("pseudoR2"):  # Cox-Snell
        nm["pseudoR2"], sm["pseudoR2"] = 0.0, float(1 - math.exp(-lr / n))
    out_model["modelDiagnostics"] = {"nullModel": nm, "selectedModel": sm}
    ht = {}
    if diag.get("likelihoodRatioTest"):
        ht["likelihoodRatioTest"] = {"status": "VALID", "statistic": float(lr), "pValue": _p(stats.chi2.sf(lr, p), alpha)}
    if diag.get("waldTest"):
        w = float(b @ np.linalg.solve(cov, b))
        ht["waldTest"] = {"status": "VALID", "statistic": w, "pValue": _p(stats.chi2.sf(w, p), alpha)}
    if diag.get("scoreTest"):
        _, g0, h0 = partial_loglik(np.zeros(p), t, d, x, True)
        sc = float(g0 @ np.linalg.solve(-h0, g0))
        ht["scoreTest"] = {"status": "VALID", "statistic": sc, "pValue": _p(stats.chi2.sf(sc, p), alpha)}
    if ht:
        out_model["hypothesisTests"] = ht
    if diag.get("harrellC"):
        c = harrell_c(t, d, x @ b)
        # CI: Prism's SE is not found (within ~5 % of the jackknife); reported as undefined here
        out_model["concordanceProbability"] = {"harrellC": {"value": c, "ci": {"lower": "undefined", "upper": "undefined",
                                                                               "level": 1.0}}}
    # events sharing their time with another event (verified)
    ties = int(sum(int(((t == tt) & (d == 1)).sum()) for tt in np.unique(t[d == 1]) if ((t == tt) & (d == 1)).sum() > 1))
    summary = {"rowsTotal": n_total, "rowsSkipped": n_total - n, "rowsAnalyzed": n, "tiesCount": ties,
               "censoredCount": n - events, "eventsCount": events, "parTotal": p,
               "censoredEventsRatio": (n - events) / events if events else math.inf,
               "censoredObservationsRatio": (n - events) / n, "eventsParRatio": events / p}
    return {"status": {"error": "VALID", "warning": ["INTERPOLATION_UNDEFINED_VARIABLE"]},
            "models": {"Model 1": out_model}, "dataSummary": summary}
