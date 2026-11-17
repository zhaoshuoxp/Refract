"""Nonlinear regression (Prism: NONLINEAR_REGRESSION), least squares, one fit
per data set, with Prism's result keys.

The model comes from parameters.json (`model.equation.definition`, Prism's
equation language, refract.stats.equation); initial values from
`model.initialValues` (the values Prism stored) or the equation's rules;
constraints CONST / GREATER / LESS; confidence intervals WALD (asymptotic)
or PROFILE_LIKELIHOOD; transforms from `equation.transforms`.
"""

from __future__ import annotations

import math

import numpy as np
from scipy import optimize, stats

from .equation import Model, expression


# ------------------------------------------------------------------ helpers
def _points(x, subs, rng=None, individual=True, ids=None):
    """ids: a list that receives (row, subcolumn) of every point (individual)."""
    xs, ys, skipped = [], [], 0
    for r, xv in enumerate(x):
        if xv is None or not math.isfinite(xv):
            continue
        if rng and ((rng[0] is not None and xv < rng[0]) or (rng[1] is not None and xv > rng[1])):
            continue
        vals = [s[r] for s in subs if r < len(s)]
        good = [v for v in vals if v is not None and math.isfinite(v)]
        skipped += len([v for v in vals if v is None]) if individual else 0
        if not good:
            continue
        if individual:
            xs.extend([float(xv)] * len(good))
            ys.extend(good)
            if ids is not None:
                ids.extend((r, si) for si, s in enumerate(subs)
                           if r < len(s) and s[r] is not None and math.isfinite(s[r]))
        else:
            xs.append(float(xv))
            ys.append(float(np.mean(good)))
    return np.array(xs), np.array(ys), skipped


def _rule_value(rule: str, value: float, xs: np.ndarray, ys: np.ndarray) -> float:
    """Prism initial-value rules: "*YMAX" = value * YMAX, "/X_AT_YMID" =
    value / X_AT_YMID, "VALUE", or an expression in YMIN, YMAX, XMIN, XMAX,
    XMID, YMID, X_AT_YMID, YatXMin, YatXMax (and SIGN())."""
    order = np.argsort(xs)
    env = {"ymin": ys.min(), "ymax": ys.max(), "xmin": xs.min(), "xmax": xs.max(), "xmid": (xs.min() + xs.max()) / 2,
           "ymid": (ys.min() + ys.max()) / 2, "yatxmin": ys[order[0]], "yatxmax": ys[order[-1]]}
    env["x_at_ymid"] = float(xs[np.argmin(np.abs(ys - env["ymid"]))])
    r = rule.strip()
    if r.upper() == "VALUE":
        return value
    op = None
    if r[:1] in "*/":
        op, r = r[0], r[1:]
    names = list(env)
    f = expression(r, names)
    v = float(f(np.array([env[k] for k in names])))
    return value * v if op == "*" else value / v if op == "/" else v


def _initial(params: dict, eq: dict, names: list[str], ds_idx: int, xs, ys) -> list[float]:
    stored = params.get("model", {}).get("initialValues", {})
    rules = eq.get("initialValueRules", {})
    out = []
    for p in names:
        entries = stored.get(p) or []
        e = next((e for e in entries if e.get("dataSet", {}).get("col", {}).get("idx") == ds_idx), None)
        # an automatic initial value (isAuto) comes from the equation's rule, not the stored value
        if e is not None and isinstance(e.get("value"), (int, float)) and not (e.get("isAuto") and p in rules):
            out.append(float(e["value"]))
        elif p in rules:
            out.append(_rule_value(rules[p]["rule"], rules[p].get("value", 1.0), xs, ys))
        else:
            out.append(1.0)
    return out


PROFILE_TOL = 1e-12  # profile refits: only the SS level matters
PROFILE_MAX_SE = 6.0  # Prism: defined limits seen up to 4.3 SE, undefined from 9.6 SE (verified)


# ---------------------------------------------------------------------- fit
class Fit:
    def __init__(self, model: Model, names: list[str], xs, ys, p0, constraints: dict):
        self.model, self.names, self.xs, self.ys = model, names, xs, ys
        self.fixed = {i: float(constraints[n]["value"]) for i, n in enumerate(names)
                      if constraints.get(n, {}).get("type") == "CONST"}
        self.free = [i for i in range(len(names)) if i not in self.fixed]
        lo, hi = [], []
        for i in self.free:
            c = constraints.get(names[i], {})
            t, v = c.get("type"), c.get("value")
            lo.append(v if t in ("GREATER", "GREATER_OR_EQUAL") else -np.inf)
            hi.append(v if t in ("LESS", "LESS_OR_EQUAL") else np.inf)
        self.bounds = (np.array(lo, float), np.array(hi, float))
        self.p0 = np.array(p0, float)

    def full(self, q) -> np.ndarray:
        p = self.p0.copy()
        for k, i in enumerate(self.free):
            p[i] = q[k]
        for i, v in self.fixed.items():
            p[i] = v
        return p

    def resid(self, q):
        return self.model(self.xs, self.full(q)) - self.ys

    def solve(self, q0=None, hold: dict | None = None, tol: float = 1e-15):
        """Least squares; `hold` fixes free-parameter positions (profiles)."""
        q0 = np.array([self.p0[i] for i in self.free] if q0 is None else q0, float)
        idx = [k for k in range(len(self.free)) if not hold or k not in hold]

        def res(sub):
            q = q0.copy()
            q[idx] = sub
            if hold:
                for k, v in hold.items():
                    q[k] = v
            return self.resid(q)

        lo, hi = self.bounds[0][idx], self.bounds[1][idx]
        start = np.clip(q0[idx], np.nextafter(lo, np.inf), np.nextafter(hi, -np.inf))
        bounded = np.isfinite(lo).any() or np.isfinite(hi).any()
        if len(idx) == 0:
            q = q0.copy()
            if hold:
                for k, v in hold.items():
                    q[k] = v
            r = self.resid(q)
            return q, float(r @ r)
        sol = optimize.least_squares(res, start, method="trf" if bounded else "lm", bounds=(lo, hi) if bounded else (-np.inf, np.inf),
                                     x_scale="jac", ftol=tol, xtol=tol, gtol=tol, max_nfev=20000)
        q = q0.copy()
        q[idx] = sol.x
        if hold:
            for k, v in hold.items():
                q[k] = v
        r = self.resid(q)
        return q, float(r @ r)

    def jacobian(self, q) -> np.ndarray:
        j = np.empty((len(self.xs), len(q)))
        for k in range(len(q)):
            h = 1e-7 * max(abs(q[k]), 1e-8)
            a, b = q.copy(), q.copy()
            a[k] += h
            b[k] -= h
            j[:, k] = (self.resid(a) - self.resid(b)) / (2 * h)
        return j


def robust_fit_scaled(fit: Fit, q: np.ndarray) -> tuple[np.ndarray, float]:
    """Prism's robust fit (fittingMethod ROBUST, and ROUT's first step): the
    Lorentzian fit whose scale is the RSDR of its own residuals, iterated
    from the least-squares fit to a fixed point (Prism's estimates agree to
    ~1e-4, its convergence criterion; ROUT decisions 40 of 40)."""
    k = len(fit.free)
    s = _rsdr(fit.resid(q), k)
    for _ in range(200):
        if s == 0:
            break
        q2 = robust_fit(fit, q, s)
        s2 = _rsdr(fit.resid(q2), k)
        done = abs(s2 - s) <= 1e-14 * s and np.allclose(q2, q, rtol=1e-13, atol=0)
        q, s = q2, s2
        if done:
            break
    return q, s


def _robust_result(fit: Fit, q, eq, names, n, skipped) -> dict:
    """ROBUST: estimates only (transforms too); goodnessOfFit reports the
    Lorentzian merit as ss, the RSDR, and aicc undefined (verified)."""
    q, s = robust_fit_scaled(fit, q)
    full = fit.full(q)
    pars = {names[i]: {"status": "REGULAR", "estimate": float(q[kk])} for kk, i in enumerate(fit.free)}
    for i, v in fit.fixed.items():
        pars[names[i]] = {"status": "CONSTANT", "estimate": v}
    for tr in eq.get("transforms", []):
        pars[tr["name"]] = {"status": "REGULAR", "estimate": float(expression(tr["definition"], names)(full))}
    r = fit.resid(q)
    merit = float(np.log1p((r / s) ** 2).sum()) if s else 0.0
    return {"status": "COMPLETED", "modelDescription": eq.get("name", ""), "parameters": pars,
            "goodnessOfFit": {"ss": merit, "rsdr": s, "aicc": "undefined"},
            "dataSummary": {"xValuesAnalyzed": float(n + skipped), "yValuesAnalyzed": float(n), "yValuesSkipped": float(skipped)}}


def _eliminate(params, x, subs, ds_idx, level, data_format, fit, q, ids, q_pct, skipped) -> dict:
    """ROUT outlier elimination: flag with rout_flags, then the ordinary fit
    of the remaining points. dataSummary still counts every point and adds
    outliersCount; `_outliers` holds Prism's outliers entry (verified)."""
    flags = rout_flags(fit, q, q_pct)
    p2 = {**params, "method": {**params.get("method", {}), "outliers": {"method": "DO_NOT_HANDLE"}}}
    clean = [list(s) for s in subs]
    for f in flags:
        r, si = ids[f]
        clean[si][r] = None
    out = fit_dataset(p2, x, clean, ds_idx, level, data_format)
    n = len(fit.ys)
    out["dataSummary"] = {"xValuesAnalyzed": float(n + skipped), "yValuesAnalyzed": float(n),
                          "yValuesSkipped": float(skipped), "outliersCount": len(flags)}
    out["_outliers"] = {"status": "VALID", "q": q_pct, "outliersCount": len(flags), "trueOutliersCount": 0,
                        "outliersList": [{"x": float(fit.xs[f]), "y": float(fit.ys[f]), "id": [ds_idx, ids[f][0], ids[f][1]]}
                                         for f in flags]}
    return out


_P68 = 100 * (stats.norm.cdf(1) - stats.norm.cdf(-1))  # 68.2689...: exact, not 68.27 (verified)


def _rsdr(r: np.ndarray, k: int) -> float:
    """Robust SD of the residuals: the 68.27th percentile of |r| (linear
    interpolation) * n / (n - K) (Motulsky & Brown 2006)."""
    n = len(r)
    return float(np.percentile(np.abs(r), _P68, method="linear") * n / (n - k))


def robust_fit(fit: Fit, q: np.ndarray, scale: float) -> np.ndarray:
    """Lorentzian (Cauchy) fit with the scale fixed: minimises
    sum log(1 + (r / scale)^2), started from q."""
    lo, hi = fit.bounds
    bounded = np.isfinite(lo).any() or np.isfinite(hi).any()
    sol = optimize.least_squares(fit.resid, q, loss="cauchy", f_scale=scale, method="trf",
                                 bounds=(lo, hi) if bounded else (-np.inf, np.inf), x_scale="jac",
                                 ftol=1e-15, xtol=1e-15, gtol=1e-15, max_nfev=20000)
    return sol.x


def rout_flags(fit: Fit, q: np.ndarray, q_pct: float) -> list[int]:
    """ROUT: Prism's robust fit (robust_fit_scaled), then each residual's
    two-sided t P value (t = |r| / RSDR at the robust
    fit, df n - K) and Benjamini-Hochberg at Q %: the k largest residuals."""
    n, k = len(fit.ys), len(fit.free)
    if n - k < 1:
        return []
    s0 = _rsdr(fit.resid(q), k)
    if s0 == 0:
        return []
    qr, _ = robust_fit_scaled(fit, q)
    r = np.abs(fit.resid(qr))
    s = _rsdr(r, k)
    if s == 0:
        return []
    ps = 2 * stats.t.sf(r / s, n - k)
    order = np.argsort(-r)
    asc = np.sort(ps)
    cut = 0
    for i, p in enumerate(asc, 1):
        if p <= i * (q_pct / 100) / n:
            cut = i
    return sorted(int(i) for i in order[:cut])


def _profile_ci(fit: Fit, q: np.ndarray, ss: float, df: int, se: np.ndarray, level: float):
    """Profile-likelihood interval: parameter values where the re-minimised SS
    reaches SS * (1 + F(level; 1, df) / df)."""
    target = ss * (1 + stats.f.ppf(level / 100, 1, df) / df)
    out = []
    for k in range(len(q)):
        warm = {"q": q}

        def excess(v, k=k, warm=warm):
            # warm start from the last profile point (fewer iterations on global fits)
            q1, s1 = fit.solve(warm["q"], hold={k: v}, tol=PROFILE_TOL)
            warm["q"] = q1
            return s1 - target

        def root(inner, outer, start, k=k):
            # every evaluation from the same start (the last point inside), so the
            # function brentq sees is deterministic
            def f(v):
                return fit.solve(start, hold={k: v}, tol=PROFILE_TOL)[1] - target

            try:
                return optimize.brentq(f, min(inner, outer), max(inner, outer), xtol=1e-14 * max(1, abs(q[k])),
                                       rtol=1e-12)
            except ValueError:  # no sign change from this start: the outer point
                return outer

        ends = []
        unit = max(se[k], 1e-12 * max(1, abs(q[k])))
        for sgn in (-1, 1):
            warm["q"] = q
            # march outwards in growing steps (the profile need not be monotone,
            # so the first crossing is wanted); no crossing within PROFILE_MAX_SE
            # standard errors -> "undefined" (Prism: defined limits seen up to
            # 4.3 SE, undefined where the profile first crosses at 9.6 SE and beyond)
            step, a = 0.1 * unit, q[k]
            lo_b, hi_b = fit.bounds[0][k], fit.bounds[1][k]
            found = None
            while abs(a - q[k]) < PROFILE_MAX_SE * unit:
                b = a + sgn * step
                start = warm["q"]
                if not (lo_b < b < hi_b):
                    # the interval is cut at the constraint (Prism reports the bound)
                    edge = lo_b if sgn < 0 else hi_b
                    found = edge if excess(edge) <= 0 else root(a, edge, start)
                    break
                if excess(b) > 0:
                    found = root(a, b, start)
                    break
                a, step = b, step * 1.3
            ends.append(found)
        out.append(tuple(ends))
    return out


def _perfect(fit: Fit, q, eq: dict, names: list[str], cov_u, n: int, skipped: int, df: int) -> dict:
    """A fit with no scatter at all: Prism's PERFECT_FIT - estimates without SE or interval, the
    parameters' correlation from the fit's shape alone, no AICc (verified, E-stats8b)."""
    sd = np.sqrt(np.diag(cov_u))
    corr = cov_u / np.outer(sd, sd)
    free = [names[i] for i in fit.free]
    return {"status": "PERFECT_FIT", "modelDescription": eq.get("name", ""),
            "parameters": {names[i]: {"status": "REGULAR", "estimate": float(q[k])} for k, i in enumerate(fit.free)},
            "covariance": {a: {b: float(corr[ia, ib]) for ib, b in enumerate(free)} for ia, a in enumerate(free)},
            "goodnessOfFit": {"df": float(df), "r2": 1.0, "adjR2": 1.0, "ss": 0.0, "aicc": "undefined"},
            "dataSummary": {"xValuesAnalyzed": float(n + skipped), "yValuesAnalyzed": float(n),
                            "yValuesSkipped": float(skipped)}}


def fit_dataset(params: dict, x, subs, ds_idx: int, level: float | None = None, data_format: str = "y_replicates") -> dict:
    """subs: the data set's subcolumns [sub][row]. For mean/SD/SEM/N formats
    only the mean (first subcolumn) is fitted, as Prism does by default."""
    if data_format not in ("y_single", "y_replicates"):
        subs = subs[:1]
    eq = params["model"]["equation"]
    names = list(eq["parameters"])
    model = Model(eq["definition"], names)
    data = params.get("data", {})
    rng = data.get("range", {})
    lim = (rng.get("minX", {}).get("value") if rng.get("minX", {}).get("enabled") else None,
           rng.get("maxX", {}).get("value") if rng.get("maxX", {}).get("enabled") else None)
    ids: list = []
    xs, ys, skipped = _points(x, subs, lim, data.get("handleReplicatesAs", "INDIVIDUAL") == "INDIVIDUAL", ids)
    conf = params.get("confidence", {})
    level = level or conf.get("confidenceLevel", 95.0)
    cons = params.get("model", {}).get("constraints") or {}
    fit = Fit(model, names, xs, ys, _initial(params, eq, names, ds_idx, xs, ys), cons)
    q, ss = fit.solve()
    # refine from the optimum (LM restarts converge more tightly), then polish
    # with Gauss-Newton steps while they lower SS and stay inside the bounds
    q, ss = fit.solve(q)
    for _ in range(3):
        jq = fit.jacobian(q)
        q2 = q - np.linalg.lstsq(jq, fit.resid(q), rcond=None)[0]
        if np.any(q2 <= fit.bounds[0]) or np.any(q2 >= fit.bounds[1]):
            break
        r2 = fit.resid(q2)
        if not float(r2 @ r2) <= ss * (1 + 1e-14):  # SS is flat near the optimum
            break
        q, ss = q2, float(r2 @ r2)
    meth = params.get("method", {})
    if meth.get("fittingMethod", "LS") == "ROBUST":
        return _robust_result(fit, q, eq, names, len(ys), skipped)
    out_cfg = meth.get("outliers", {})
    if out_cfg.get("method", "DO_NOT_HANDLE") == "ELIMINATE" and ids:
        return _eliminate(params, x, subs, ds_idx, level, data_format, fit, q, ids, out_cfg.get("q", 1.0), skipped)
    n, k = len(ys), len(fit.free)
    df = n - k
    j = fit.jacobian(q)
    cov_u = np.linalg.pinv(j.T @ j)
    sst0 = float(((ys - ys.mean()) ** 2).sum())
    if not fit.fixed and ss <= 1e-24 * max(sst0, 1e-300):  # the curve goes through every point
        return _perfect(fit, q, eq, names, cov_u, n, skipped, df)
    cov = cov_u * ss / df
    se = np.sqrt(np.diag(cov))
    tc = stats.t.ppf(1 - (1 - level / 100) / 2, df)
    if conf.get("ciMethod", "PROFILE_LIKELIHOOD") == "PROFILE_LIKELIHOOD":
        cis = _profile_ci(fit, q, ss, df, se, level)
    else:
        cis = [(q[i] - tc * se[i], q[i] + tc * se[i]) for i in range(k)]
    full = fit.full(q)
    pars = {}
    hit = False
    undef = {"lower": "undefined", "upper": "undefined", "level": level}
    for kk, i in enumerate(fit.free):
        lo, hi = cis[kk]
        b_lo, b_hi = fit.bounds[0][kk], fit.bounds[1][kk]
        if any(math.isfinite(b) and abs(q[kk] - b) <= 1e-9 * max(1.0, abs(b)) for b in (b_lo, b_hi)):
            # Prism: a bound that is active -> HIT_CONSTRAINT, no SE / CI; the
            # parameter still counts in df and in the covariance (verified, LESS)
            hit = True
            pars[names[i]] = {"status": "HIT_CONSTRAINT", "estimate": float(q[kk]), "se": "undefined", "ci": dict(undef)}
            continue
        pars[names[i]] = {"status": "REGULAR", "estimate": float(q[kk]), "se": float(se[kk]),
                          "ci": {"lower": "undefined" if lo is None else float(lo), "upper": "undefined" if hi is None else float(hi),
                                 "level": level}}
    for i, v in fit.fixed.items():
        pars[names[i]] = {"status": "CONSTANT", "estimate": v, "se": "undefined", "ci": dict(undef)}
    # transforms
    for tr in eq.get("transforms", []):
        g = expression(tr["definition"], names)
        est = float(g(full))
        used = [i for i, nm in enumerate(names) if nm.lower() in tr["definition"].lower() and i in fit.free]
        grad = np.zeros(k)
        for kk, i in enumerate(fit.free):
            h = 1e-7 * max(abs(full[i]), 1e-8)
            a, b = full.copy(), full.copy()
            a[i] += h
            b[i] -= h
            grad[kk] = (float(g(a)) - float(g(b))) / (2 * h)
        entry = {"status": "REGULAR", "estimate": est}
        if tr.get("ciMethod") == "ASYMMETRICAL" and len(used) == 1:
            kk = fit.free.index(used[0])
            lo, hi = cis[kk]
            ends = []
            for v in (lo, hi):
                if v is None:
                    ends.append(None)
                    continue
                pp = full.copy()
                pp[used[0]] = v
                ends.append(float(g(pp)))
            if None in ends:
                ci = {"lower": "undefined", "upper": "undefined"}
            else:
                ci = {"lower": min(ends), "upper": max(ends)}
        else:
            se_t = float(math.sqrt(grad @ cov @ grad))
            entry["se"] = se_t
            if conf.get("ciMethod", "PROFILE_LIKELIHOOD") == "PROFILE_LIKELIHOOD":
                ci = {"lower": "undefined", "upper": "undefined"}
            else:
                ci = {"lower": est - tc * se_t, "upper": est + tc * se_t}
        entry["ci"] = {**ci, "level": level}
        pars[tr["name"]] = entry
    sd = np.sqrt(np.diag(cov))
    corr = cov / np.outer(sd, sd)
    free_names = [names[i] for i in fit.free]
    covariance = {a: {b: float(corr[ia, ib]) for ib, b in enumerate(free_names)} for ia, a in enumerate(free_names)}
    for i in fit.fixed:  # constants: "undefined" rows and columns (Prism)
        covariance[names[i]] = {b: "undefined" for b in names}
        for a in free_names:
            covariance[a][names[i]] = "undefined"
    sst = float(((ys - ys.mean()) ** 2).sum())
    kp = k + 1
    gof = {"df": float(df), "r2": 1 - ss / sst, "adjR2": 1 - (1 - (1 - ss / sst)) * (n - 1) / df, "ss": ss,
           "syx": math.sqrt(ss / df), "rmse": math.sqrt(ss / (n - 1)),  # Prism: SS / (n - 1)
           # too few points for AICc's correction (n <= K + 1): "undefined", as Prism's other undefined values
           "aicc": n * math.log(ss / n) + 2 * kp + 2 * kp * (kp + 1) / (n - kp - 1) if n - kp - 1 > 0 and ss > 0
           else "undefined"}
    return {"status": "HIT_CONSTRAINT" if hit else "COMPLETED", "modelDescription": eq.get("name", ""), "parameters": pars, "covariance": covariance,
            "goodnessOfFit": gof,
            "dataSummary": {"xValuesAnalyzed": float(n + skipped),  # Prism: point slots with an X
                            "yValuesAnalyzed": float(n), "yValuesSkipped": float(skipped)}}


# ---------------------------------------------------------------- the curve
def curve_range(params: dict, eq: dict, x) -> tuple[float, float, int]:
    """Prism's fitted curve: graph.curve.pointCount points (1000) from the
    smallest X (the equation's defaultMinCurveX "X=0": from zero) to the
    largest, unless the range is set (minX / maxX not isAuto)."""
    known = [float(v) for v in x if v is not None and math.isfinite(v)]
    cv = (params.get("graph") or {}).get("curve") or {}
    lo, hi = (min(known), max(known)) if known else (0.0, 1.0)
    if eq.get("defaultMinCurveX") == "X=0" and lo > 0:
        lo = 0.0
    mn, mx = cv.get("minX") or {}, cv.get("maxX") or {}
    if mn and not mn.get("isAuto", True) and isinstance(mn.get("value"), (int, float)):
        lo = float(mn["value"])
    if mx and not mx.get("isAuto", True) and isinstance(mx.get("value"), (int, float)):
        hi = float(mx["value"])
    return lo, hi, int(cv.get("pointCount", 1000) or 1000)


def curve_table(params: dict, x, columns: list, titles: list[str], fits: list[dict], bands: float | None = None,
                data_format: str = "y_replicates") -> dict:
    """The "Curve" result table: X (a series) and each data set's fitted Y;
    with bands (a confidence level), each Y with the half-width of its
    confidence band (Prism: Y +/- error), from the fit's covariance."""
    eq = params["model"]["equation"]
    names = list(eq["parameters"])
    model = Model(eq["definition"], names)
    lo, hi, n = curve_range(params, eq, x)
    grid = np.linspace(lo, hi, n)
    out = []
    for i, fit in enumerate(fits):
        p = np.array([fit["parameters"][nm]["estimate"] for nm in names], float)
        y = np.asarray(model(grid, p), float)
        band = None
        if bands is not None and fit.get("status") != "PERFECT_FIT":
            subs = columns[i] if data_format in ("y_single", "y_replicates") else columns[i][:1]
            xs, ys, _ = _points(x, subs)
            free = [k for k, nm in enumerate(names) if fit["parameters"][nm].get("status") != "CONSTANT"]

            def jac(at, p=p, free=free):
                j = np.empty((len(at), len(free)))
                for c, k in enumerate(free):
                    h = 1e-7 * max(abs(p[k]), 1e-8)
                    a, b = p.copy(), p.copy()
                    a[k] += h
                    b[k] -= h
                    j[:, c] = (np.asarray(model(at, a), float) - np.asarray(model(at, b), float)) / (2 * h)
                return j

            jd = jac(xs)
            df = len(ys) - len(free)
            ss = float(((ys - np.asarray(model(xs, p), float)) ** 2).sum())
            cov = np.linalg.pinv(jd.T @ jd) * ss / df
            jg = jac(grid)
            se = np.sqrt(np.einsum("ij,jk,ik->i", jg, cov, jg))
            band = stats.t.ppf(1 - (1 - bands / 100) / 2, df) * se
        out.append((y, band))
    rows = []
    for k, xv in enumerate(grid):
        row = [float(xv)]
        for y, band in out:
            row.append(float(y[k]) if math.isfinite(y[k]) else None)
            if band is not None:
                row += [float(band[k]), float(band[k])]
        rows.append(row)
    head = ["X"]
    for t, (_, band) in zip(titles, out, strict=False):
        head += [t] if band is None else [t, f"{t} (+)", f"{t} (-)"]
    return {"columns": head, "rows": rows, "row_titles": None}
