"""Nonlinear regression across data sets: global fits with shared parameters
(constraint type SHARE) and model comparison (`modelComparison.type`
TWO_MODLES [sic], CONSTRAINED_PARAMETER, SHARED_PARAMETERS; method
STAT_TEST = extra sum-of-squares F test, AIC_TEST = AICc), with Prism's
result keys (verified against a Prism-made sample and
tools/nl_compare_parity.py).

Output (`analysis`): {"status", "modelComparison"?, "models"}, where a model
fitted per data set is keyed "<model>|col<i>" and holds refract.stats.nonlinear
.fit_dataset's flat result, and a global model is keyed "<model>|global" with
one layer per parameter: {"shared": entry} or {"0": entry, "1": entry, ...}
(entries carry dsList); its goodnessOfFit r2/ss are {"global", "0", ...} and
its covariance cells {"0": corr, ...} (each data set's parameters).
"""

from __future__ import annotations

import copy
import math

import numpy as np
from scipy import stats

from . import nonlinear as NL
from .equation import Model, expression


def _shared(constraints: dict) -> list[str]:
    return [n for n, c in (constraints or {}).items() if isinstance(c, dict) and c.get("type") == "SHARE"]


class _GlobalModel:
    """Callable for refract.stats.nonlinear.Fit: one expanded parameter vector
    (shared parameters once, the others per data set) over the stacked data."""

    def __init__(self, model: Model, names, layout, xs_list):
        self.model, self.names, self.layout, self.xs_list = model, names, layout, xs_list
        self.pos = {key: i for i, key in enumerate(layout)}

    def ds_params(self, p, d) -> np.ndarray:
        return np.array([p[self.pos[(n, None)]] if (n, None) in self.pos else p[self.pos[(n, d)]] for n in self.names])

    def __call__(self, _xs, p):
        return np.concatenate([self.model(xs, self.ds_params(p, d)) for d, xs in enumerate(self.xs_list)])


def fit_global(params: dict, x, datasets, titles=None, data_format: str = "y_replicates") -> dict:
    """Least-squares fit of all data sets at once, the SHARE parameters common.
    Returns the global model value (see module docstring)."""
    eq = params["model"]["equation"]
    names = list(eq["parameters"])
    cons = params["model"].get("constraints") or {}
    shared = set(_shared(cons))
    model = Model(eq["definition"], names)
    individual = params.get("data", {}).get("handleReplicatesAs", "INDIVIDUAL") == "INDIVIDUAL"
    pts = []
    for subs in datasets:
        if data_format not in ("y_single", "y_replicates"):
            subs = subs[:1]
        pts.append(NL._points(x, subs, None, individual))
    k_ds = len(datasets)
    layout = [(n, None) for n in names if n in shared] + [(n, d) for d in range(k_ds) for n in names if n not in shared]
    init = [NL._initial(params, eq, names, d, xs, ys) for d, (xs, ys, _) in enumerate(pts)]
    p0 = [init[0][names.index(n)] if d is None else init[d][names.index(n)] for n, d in layout]
    keys = [n if d is None else f"{n}#{d}" for n, d in layout]
    econs = {}
    for (n, _d), key in zip(layout, keys, strict=True):
        c = cons.get(n)
        if isinstance(c, dict) and c.get("type") in ("CONST", "GREATER", "LESS"):
            econs[key] = c
    gm = _GlobalModel(model, names, layout, [p[0] for p in pts])
    xs_all = np.concatenate([p[0] for p in pts])
    ys_all = np.concatenate([p[1] for p in pts])
    fit = NL.Fit(gm, keys, xs_all, ys_all, p0, econs)
    q, ss = fit.solve()
    q, ss = fit.solve(q)
    # more starts: each data set's own fit, the shared parameters at each data
    # set's value and at their mean; keep the lowest SS (a single start can
    # stop in a worse local minimum where Prism does not)
    sep = []
    for d, subs in enumerate(datasets):
        sp = {**params, "model": {**params["model"], "constraints": {n_: c for n_, c in cons.items() if n_ not in shared}}}
        try:
            f_d = NL.fit_dataset(sp, x, subs, d, data_format=data_format)
            sep.append({n_: v["estimate"] for n_, v in f_d["parameters"].items()})
        except (ValueError, np.linalg.LinAlgError):
            sep.append(None)
    if all(sep):
        for src in [*range(k_ds), "mean"]:
            start = np.array([(np.mean([sep[e][n_] for e in range(k_ds)]) if src == "mean" else sep[src][n_]) if d is None
                              else sep[d][n_] for n_, d in layout])
            q1, ss1 = fit.solve(np.array([start[i] for i in fit.free]))
            if ss1 < ss * (1 - 1e-12):
                q, ss = fit.solve(q1)
    n, k = len(ys_all), len(fit.free)
    df = n - k
    j = fit.jacobian(q)
    # a parameter whose sensitivity has vanished (e.g. a Hill slope run off to a
    # step) is UNSTABLE: no SE / CI, and left out of the covariance (Prism)
    norms = np.linalg.norm(j, axis=0)
    unstable = {kk for kk in range(k) if norms[kk] <= 1e-9 * max(norms.max(), 1e-300)}
    keep = [kk for kk in range(k) if kk not in unstable]
    cov = np.full((k, k), np.nan)
    sub = j[:, keep]
    cov[np.ix_(keep, keep)] = np.linalg.pinv(sub.T @ sub) * ss / df
    se = np.sqrt(np.abs(np.diag(cov)))
    conf = params.get("confidence", {})
    level = conf.get("confidenceLevel", 95.0)
    profile = conf.get("ciMethod", "PROFILE_LIKELIHOOD") == "PROFILE_LIKELIHOOD"
    tc = stats.t.ppf(1 - (1 - level / 100) / 2, df)
    se_p = np.where(np.isfinite(se), se, 1.0)
    cis = NL._profile_ci(fit, q, ss, df, se_p, level) if profile else [(q[i] - tc * se[i], q[i] + tc * se[i]) for i in range(k)]
    cis = [(None, None) if kk in unstable else c for kk, c in enumerate(cis)]
    full = fit.full(q)
    free_pos = {fit.free[kk]: kk for kk in range(k)}
    undef = {"lower": "undefined", "upper": "undefined", "level": level}

    def entry(i, ds_list):
        if i not in free_pos:
            return {"status": "CONSTANT", "estimate": float(full[i]), "se": "undefined", "ci": dict(undef), "dsList": ds_list}
        kk = free_pos[i]
        if kk in unstable:
            return {"status": "UNSTABLE", "estimate": float(full[i]), "se": "undefined", "ci": dict(undef), "dsList": ds_list}
        lo, hi = cis[kk]
        return {"status": "REGULAR", "estimate": float(full[i]), "se": float(se[kk]),
                "ci": {"lower": "undefined" if lo is None else float(lo), "upper": "undefined" if hi is None else float(hi),
                       "level": level}, "dsList": ds_list}

    pars: dict = {}
    for n_ in names:
        if n_ in shared:
            pars[n_] = {"shared": entry(gm.pos[(n_, None)], list(range(k_ds)))}
        else:
            pars[n_] = {str(d): entry(gm.pos[(n_, d)], [d]) for d in range(k_ds)}
    # transforms: per data set, or shared when every parameter they use is shared
    for tr in eq.get("transforms", []):
        g = expression(tr["definition"], names)
        used = [nm for nm in names if nm.lower() in tr["definition"].lower()]
        groups = [None] if used and all(u in shared for u in used) else list(range(k_ds))
        layer = {}
        for d in groups:
            dd = 0 if d is None else d
            pd = gm.ds_params(full, dd)
            est = float(g(pd))
            grad = np.zeros(k)
            for kk, i in enumerate(fit.free):
                h = 1e-7 * max(abs(full[i]), 1e-8)
                a, b = full.copy(), full.copy()
                a[i] += h
                b[i] -= h
                grad[kk] = (float(g(gm.ds_params(a, dd))) - float(g(gm.ds_params(b, dd)))) / (2 * h)
            e = {"status": "REGULAR", "estimate": est}
            free_used = [gm.pos[(u, None)] if (u, None) in gm.pos else gm.pos[(u, dd)] for u in used]
            free_used = [i for i in free_used if i in free_pos]
            if tr.get("ciMethod") == "ASYMMETRICAL" and len(free_used) == 1:
                lo, hi = cis[free_pos[free_used[0]]]
                ends = []
                for v in (lo, hi):
                    if v is None:
                        ends.append(None)
                        continue
                    pp = full.copy()
                    pp[free_used[0]] = v
                    ends.append(float(g(gm.ds_params(pp, dd))))
                ci = {"lower": "undefined", "upper": "undefined"} if None in ends else {"lower": min(ends), "upper": max(ends)}
            else:
                se_t = float(math.sqrt(grad @ cov @ grad))
                e["se"] = se_t
                ci = {"lower": "undefined", "upper": "undefined"} if profile else {"lower": est - tc * se_t,
                                                                                    "upper": est + tc * se_t}
            e["ci"] = {**ci, "level": level}
            e["dsList"] = list(range(k_ds)) if d is None else [d]
            layer["shared" if d is None else str(d)] = e
        pars[tr["name"]] = layer
    # covariance: the correlation matrix of each data set's parameters (shared ones included)
    sd = np.sqrt(np.diag(cov))
    corr = cov / np.outer(sd, sd)
    covariance: dict = {}
    for a in names:
        covariance[a] = {}
        for b in names:
            cell = {}
            for d in range(k_ds):
                ia = gm.pos[(a, None)] if (a, None) in gm.pos else gm.pos[(a, d)]
                ib = gm.pos[(b, None)] if (b, None) in gm.pos else gm.pos[(b, d)]
                ok = ia in free_pos and ib in free_pos and np.isfinite(corr[free_pos[ia], free_pos[ib]])
                cell[str(d)] = float(corr[free_pos[ia], free_pos[ib]]) if ok else "undefined"
            covariance[a][b] = cell
    r = fit.resid(q)
    sst = float(((ys_all - ys_all.mean()) ** 2).sum())
    r2 = {"global": 1 - ss / sst}
    ssd = {"global": ss}
    off = 0
    for d, (_xs, ys, _) in enumerate(pts):
        rd = r[off:off + len(ys)]
        off += len(ys)
        ssd[str(d)] = float(rd @ rd)
        r2[str(d)] = 1 - ssd[str(d)] / float(((ys - ys.mean()) ** 2).sum())
    kp = k + 1
    gof = {"df": float(df), "r2": r2, "adjR2": 1 - (1 - r2["global"]) * (n - 1) / df, "ss": ssd, "syx": math.sqrt(ss / df),
           "rmse": math.sqrt(ss / (n - 1)), "aicc": n * math.log(ss / n) + 2 * kp + 2 * kp * (kp + 1) / (n - kp - 1)}
    return {"status": "COMPLETED", "modelDescription": eq.get("name", ""), "parameters": pars, "covariance": covariance,
            "goodnessOfFit": gof, "_n": n, "_k": k}


# --------------------------------------------------------------- comparison
def _p(value, alpha):
    if not isinstance(value, float):
        return {"value": "undefined", "level": alpha, "isSignificant": False, "state": "P_VALUE_EQUAL"}
    return {"value": value, "level": alpha, "isSignificant": bool(value < alpha), "state": "P_VALUE_EQUAL"}


def _aicc(ss, n, k):
    kp = k + 1
    return n * math.log(ss / n) + 2 * kp + 2 * kp * (kp + 1) / (n - kp - 1)


def _compare(method: str, alpha: float, m1: tuple, m2: tuple) -> dict:
    """m = (key, name, ss, df, n, k). Simple model: the one with more df."""
    s, c = (m2, m1) if m2[3] > m1[3] else (m1, m2)
    if method == "AIC_TEST":
        delta = _aicc(s[2], s[4], s[5]) - _aicc(c[2], c[4], c[5])
        p_s = 1 / (1 + math.exp(delta / 2))
        pref = s if p_s >= 0.5 else c
        return {"aicTest": {"status": "CALCULATED", "isRun": True, "preferredModelName": pref[1], "preferredModelKey": pref[0],
                            "simpleModel": {"status": "REGULAR", "name": s[1], "key": s[0], "probability": p_s},
                            "complexModel": {"status": "REGULAR", "name": c[1], "key": c[0], "probability": 1 - p_s},
                            "summary": {"aicDifference": delta,
                                        "probabilitiesRatio": max(p_s, 1 - p_s) / min(p_s, 1 - p_s)}}}
    simple = {"status": "REGULAR", "name": s[1], "key": s[0], "ss": s[2], "df": float(s[3])}
    complex_ = {"status": "REGULAR", "name": c[1], "key": c[0], "ss": c[2], "df": float(c[3])}
    if s[3] == c[3]:  # equal df: no test (verified)
        return {"fTest": {"status": "MODELS_EQUAL_DF", "isRun": True, "preferredModelName": m1[1], "preferredModelKey": m1[0],
                          "simpleModel": simple, "complexModel": complex_,
                          "summary": {"f": "undefined", "dfNumerator": 0.0, "dfDenominator": float(c[3]),
                                      "pValue": _p("undefined", alpha)}}}
    dfn = s[3] - c[3]
    f = ((s[2] - c[2]) / dfn) / (c[2] / c[3])
    p = float(stats.f.sf(f, dfn, c[3]))
    pref = c if p < alpha else s
    return {"fTest": {"status": "CALCULATED", "isRun": True, "preferredModelName": pref[1], "preferredModelKey": pref[0],
                      "simpleModel": simple, "complexModel": complex_,
                      "summary": {"f": f, "dfNumerator": float(dfn), "dfDenominator": float(c[3]), "pValue": _p(p, alpha)}}}


def _titles(mc: dict, params: dict, other: dict) -> tuple[str, str]:
    """Model titles from `modelComparison.options` (Prism builds them from it;
    the fits come from modelToCompare's constraints)."""
    t = mc.get("type")
    opt = mc.get("options") or {}
    e1, e2 = params["model"]["equation"].get("name", ""), other["model"]["equation"].get("name", "")
    if t == "CONSTRAINED_PARAMETER":
        nm, v = opt.get("parameterName", ""), opt.get("hypoteticalValue", 0.0)  # sic
        return f"{nm} unconstrained", f"{nm} = {v:g}"
    if t == "SHARED_PARAMETERS":
        sp = opt.get("sharedParameters") or []
        what = sp[0] if len(sp) == 1 else f"{len(sp)} parameters"
        return f"{what} different for at least one data set", f"{what} same for all data sets"
    if e1 == e2:
        return "Equation 1", "Equation 2"
    return e1, e2


def _fits(params, x, datasets, fmt):
    """[(col idx or None, flat value)] for one model specification."""
    if _shared(params["model"].get("constraints")):
        return [(None, fit_global(params, x, datasets, data_format=fmt))]
    return [(i, NL.fit_dataset(params, x, subs, i, data_format=fmt)) for i, subs in enumerate(datasets)]


def analysis(params: dict, x, datasets, titles, fmt: str) -> dict:
    mc = params.get("modelComparison", {}) or {}
    specs = [("Model 1", params)]
    if mc.get("type", "NO_COMPARISON") != "NO_COMPARISON":
        other = copy.deepcopy(params)
        mtc = mc.get("modelToCompare", {})
        other["model"] = {**other["model"], **{k: v for k, v in mtc.items() if k in ("equation", "constraints", "initialValues")}}
        specs.append(("Model 2", other))
        names = _titles(mc, params, other)
    else:
        names = (params["model"]["equation"].get("name", ""),)
    models, per = {}, {}
    for (mname, spec), title in zip(specs, names, strict=True):
        if spec is not params and (spec.get("method", {}).get("fittingMethod", "LS") != "LS"
                                   or spec.get("method", {}).get("outliers", {}).get("method", "DO_NOT_HANDLE") != "DO_NOT_HANDLE"):
            raise NotImplementedError("model comparison with robust fitting or ROUT")
        fits = _fits(spec, x, datasets, fmt)
        per[mname] = (title, fits)
        for i, v in fits:
            v["modelDescription"] = title  # the model's title (verified)
            mid = {"model": {"name": mname, "title": title}}
            if i is not None:
                mid = {"col": {"title": titles[i], "idx": i}, **mid}
            models[f"{mname}|{'global' if i is None else f'col{i}'}"] = {"id": mid, "value": v}
    out = {"status": {"error": "VALID", "warning": []}}
    if len(specs) == 2:
        alpha = mc.get("alpha", 0.05)
        method = mc.get("method", "STAT_TEST")
        (t1, f1), (t2, f2) = per["Model 1"], per["Model 2"]

        def stat(fits, key, title):
            ss = sum(v["goodnessOfFit"]["ss"]["global"] if i is None else v["goodnessOfFit"]["ss"] for i, v in fits)
            df = sum(v["goodnessOfFit"]["df"] for _, v in fits)
            n = sum(v["_n"] if i is None else v["dataSummary"]["yValuesAnalyzed"] for i, v in fits)
            k = sum(v["_k"] if i is None else int(v["dataSummary"]["yValuesAnalyzed"] - v["goodnessOfFit"]["df"]) for i, v in fits)
            return (key, title, ss, df, n, k)

        comp = {}
        if all(i is not None for i, _ in f1 + f2):  # per data set
            for (i, v1), (_, v2) in zip(f1, f2, strict=True):
                ids = [{"col": {"title": titles[i], "idx": i}, "model": {"name": "Model 1", "title": t1}},
                       {"col": {"title": titles[i], "idx": i}, "model": {"name": "Model 2", "title": t2}}]
                comp[f"col{i}"] = {"id": ids, "value": _compare(method, alpha, stat([(i, v1)], "Model 1", t1),
                                                                stat([(i, v2)], "Model 2", t2))}
        else:
            ids = [{"model": {"name": "Model 1", "title": t1}}, {"model": {"name": "Model 2", "title": t2}}]
            comp["global"] = {"id": ids, "value": _compare(method, alpha, stat(f1, "Model 1", t1), stat(f2, "Model 2", t2))}
        out["modelComparison"] = comp
    for m in models.values():
        m["value"].pop("_n", None)
        m["value"].pop("_k", None)
    out["models"] = models
    return out
