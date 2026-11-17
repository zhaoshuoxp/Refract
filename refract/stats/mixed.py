"""Mixed-effects (REML) fits that Prism 11.1 uses instead of repeated-measures
ANOVA when values are missing (results key repeatedMeasuresRemlAnovaModel).

Verified against Prism (tools/mixed_parity.py):
- REML with independent random intercepts: subject (one-way, two-way with
  one repeated factor), or subject, subject x row and subject x column (both
  factors repeated); fixed effects effect-coded with the interaction.
  Components estimated at 0 are removed (RANDOM_EFFECT_REMOVED; parameter
  repeatedMeasures.removeNonPositiveRandomEffects).
- Fixed effects: Wald F = b' (L C L')^-1 b / q (Type III).
- Denominator df: Prism's "legacy" error strata, the within-subject
  residual stratum losing one df per missing value; ordinary residual df
  N - cells when every random effect was removed.
- Geisser-Greenhouse epsilon from the covariance matrix of the repeated
  levels computed from all available pairs, centred at each level's mean of
  all its values: divided by (pairs - 1) in one-way designs, by the number
  of pairs (pooled over groups) in two-way designs.
- matchingTest: REML likelihood ratio against the model without random
  effects, df = random effects kept.
"""

from __future__ import annotations

import math

import numpy as np
from scipy import optimize, stats


def _p(value: float, alpha: float) -> dict:
    return {"value": float(value), "level": alpha, "isSignificant": bool(value < alpha), "state": "P_VALUE_EQUAL"}


def _effect(idx: np.ndarray, k: int) -> np.ndarray:
    x = np.zeros((len(idx), k - 1))
    for j in range(k - 1):
        x[idx == j, j] = 1.0
    x[idx == k - 1, :] = -1.0
    return x


def _code(level, k):
    v = np.zeros(k - 1)
    if level is None:
        return v
    if level == k - 1:
        v[:] = -1.0
    else:
        v[level] = 1.0
    return v


# --------------------------------------------------------------------- REML
class Reml:
    """y = X b + sum_k Z_k u_k + e, u_k ~ N(0, g_k s2 I), e ~ N(0, s2 I);
    REML profiled over s2, maximised over the ratios g_k >= 0."""

    def __init__(self, y: np.ndarray, x: np.ndarray, zs: list[np.ndarray]):
        self.y, self.x, self.zs = y, x, zs
        self.n, self.p = x.shape
        self.zz = [z @ z.T for z in zs]

    def _parts(self, g):
        h = np.eye(self.n) + sum(gk * zz for gk, zz in zip(g, self.zz, strict=True))
        hi = np.linalg.inv(h)
        xhi = self.x.T @ hi
        a = xhi @ self.x
        b = np.linalg.solve(a, xhi @ self.y)
        r = self.y - self.x @ b
        s2 = float(r @ hi @ r) / (self.n - self.p)
        return h, hi, a, b, s2

    def nll(self, g) -> float:
        """-REML log-likelihood (up to a constant); +inf where it is not defined."""
        with np.errstate(all="ignore"):
            try:
                h, _, a, _, s2 = self._parts(g)
            except np.linalg.LinAlgError:
                return math.inf
            if not (s2 > 0 and math.isfinite(s2)):
                return math.inf
            v = 0.5 * ((self.n - self.p) * math.log(s2) + np.linalg.slogdet(h)[1] + np.linalg.slogdet(a)[1]
                       + (self.n - self.p))
        return v if math.isfinite(v) else math.inf

    def grad(self, g) -> np.ndarray:
        """d nll / d g_k of the profiled REML criterion (analytic)."""
        _h, hi, a, b, _s2 = self._parts(g)
        r = self.y - self.x @ b
        hr = hi @ r
        ai = np.linalg.inv(a)
        xhi = self.x.T @ hi
        out = []
        for zz in self.zz:
            quad = float(hr @ zz @ hr)
            tr1 = float(np.sum(hi * zz))  # trace(H^-1 ZZ')
            tr2 = float(np.trace(ai @ xhi @ zz @ xhi.T))
            out.append(0.5 * (-(self.n - self.p) * quad / (r @ hr) + tr1 - tr2))
        return np.array(out)

    def _polish(self, g):
        """Solve grad = 0 for the positive ratios (the criterion is flat at
        the optimum, so minimising it alone stops at ~sqrt(eps))."""
        free = [i for i, v in enumerate(g) if v > 0]
        if not free:
            return g

        def f(u):
            gg = g.copy()
            gg[free] = np.exp(u)
            return self.grad(gg)[free] * np.exp(u)

        u0 = np.log(g[free])
        sol = optimize.root(f, u0, method="hybr", options={"xtol": 1e-14})
        if np.all(np.isfinite(sol.x)) and np.abs(f(sol.x)).max() < np.abs(f(u0)).max():
            gg = g.copy()
            gg[free] = np.exp(sol.x)
            if self.nll(gg) <= self.nll(g) + 1e-10:
                return gg
        return g

    def fit(self) -> dict:
        k = len(self.zs)
        if k == 0:
            g = np.zeros(0)
        else:
            best = None
            for start in (1.0, 0.1, 10.0, 0.01):
                o = optimize.minimize(lambda t: self.nll(t * t), np.full(k, math.sqrt(start)), method="BFGS",
                                      options={"gtol": 1e-12, "maxiter": 2000})
                o2 = optimize.minimize(lambda t: self.nll(t * t), o.x, method="Nelder-Mead",
                                       options={"xatol": 1e-13, "fatol": 1e-15, "maxiter": 20000})
                if best is None or o2.fun < best.fun:
                    best = o2
            g = best.x ** 2
            if k == 1:  # one variance ratio: a precise one-dimensional search in log g
                lo_ = math.log(max(g[0], 1e-12)) - 3
                o1 = optimize.minimize_scalar(lambda u: self.nll(np.array([math.exp(u)])), bounds=(lo_, lo_ + 6),
                                              method="bounded", options={"xatol": 1e-14})
                if o1.fun < self.nll(g):
                    g = np.array([math.exp(o1.x)])
            # polish on the ratios themselves (the surface is flat near the optimum)
            o3 = optimize.minimize(self.nll, g, method="L-BFGS-B", bounds=[(0.0, None)] * k,
                                   options={"ftol": 1e-16, "gtol": 1e-12, "maxiter": 5000, "eps": 1e-9})
            if o3.fun <= best.fun:
                g = o3.x
            g[g < 1e-10] = 0.0
            g = self._polish(g)
        _, _, a, b, s2 = self._parts(g)
        return {"g": g, "s2": s2, "beta": b, "cov": np.linalg.inv(a) * s2, "nll": self.nll(g)}


def _wald(beta, cov, idx) -> float:
    bb = beta[idx]
    return float(bb @ np.linalg.solve(cov[np.ix_(idx, idx)], bb) / len(idx))


def _pairwise_cov(x: np.ndarray, minus: int) -> np.ndarray:
    """Covariance of the columns of x (rows with NaN) from all available
    pairs, centred at each column's mean of all its values."""
    q = x.shape[1]
    mu = np.nanmean(x, axis=0)
    s = np.zeros((q, q))
    for i in range(q):
        for j in range(q):
            ok = ~np.isnan(x[:, i]) & ~np.isnan(x[:, j])
            s[i, j] = ((x[ok, i] - mu[i]) * (x[ok, j] - mu[j])).sum() / (ok.sum() - minus)
    return s


def _pooled_pairwise(groups: list[np.ndarray]) -> np.ndarray:
    """Two-way: cross-products of each group (centred at the group's level
    means) summed over groups, divided by the number of pairs (verified)."""
    q = groups[0].shape[1]
    s, cnt = np.zeros((q, q)), np.zeros((q, q))
    for x in groups:
        mu = np.nanmean(x, axis=0)
        for i in range(q):
            for j in range(q):
                ok = ~np.isnan(x[:, i]) & ~np.isnan(x[:, j])
                s[i, j] += ((x[ok, i] - mu[i]) * (x[ok, j] - mu[j])).sum()
                cnt[i, j] += ok.sum()
    return s / cnt


def _gg_cov(s: np.ndarray, m: np.ndarray) -> float:
    """Geisser-Greenhouse epsilon of orthonormal contrasts m (p x q) for the covariance s."""
    c = m @ s @ m.T
    return float(np.trace(c) ** 2 / (m.shape[0] * np.sum(c * c)))


def _helmert(k: int) -> np.ndarray:
    h = np.zeros((k - 1, k))
    for i in range(1, k):
        h[i - 1, :i] = 1.0
        h[i - 1, i] = -i
        h[i - 1] /= math.sqrt(i * (i + 1))
    return h


# ------------------------------------------------------------------ two-way
def two_way_mixed(cells, design: str, alpha: float = 0.05, assume_sphericity: bool = False,
                  row_titles=None, col_titles=None, remove_nonpositive: bool = True) -> dict:
    """cells[r][c][s]: replicate s of cell (r, c) (None = missing). design:
    REPEATED_MEASURES_BY_ROWS (subject = column x replicate, rows repeated),
    _BY_COLS (subject = row x replicate) or _BY_BOTH_FACTORS (subject = replicate)."""
    nr, nc = len(cells), len(cells[0])
    reps = max(len(cells[r][c]) for r in range(nr) for c in range(nc))
    row_titles = row_titles or [f"Row {r + 1}" for r in range(nr)]
    col_titles = col_titles or [chr(65 + c) for c in range(nc)]
    ys, ri, ci, subj = [], [], [], []
    for r in range(nr):
        for c in range(nc):
            for s in range(reps):
                v = cells[r][c][s] if s < len(cells[r][c]) else None
                if v is None or not math.isfinite(v):
                    continue
                ys.append(float(v))
                ri.append(r)
                ci.append(c)
                subj.append({"REPEATED_MEASURES_BY_ROWS": (c, s), "REPEATED_MEASURES_BY_COLS": (r, s)}.get(design, (s,)))
    y, ri, ci = np.array(ys), np.array(ri), np.array(ci)
    n_obs = len(y)
    missing = nr * nc * reps - n_obs
    one = np.ones((n_obs, 1))
    xr, xc = _effect(ri, nr), _effect(ci, nc)
    x = np.hstack([one, xr, xc, np.einsum("ni,nj->nij", xr, xc).reshape(n_obs, -1)])
    idx = {"row": list(range(1, nr)), "col": list(range(nr, nr + nc - 1)), "int": list(range(nr + nc - 1, x.shape[1]))}

    def zmat(keys):
        levels = sorted(set(keys))
        z = np.zeros((n_obs, len(levels)))
        for i, k in enumerate(keys):
            z[i, levels.index(k)] = 1.0
        return z

    names = ["matchedFactor"]
    keys = [subj]
    if design == "REPEATED_MEASURES_BY_BOTH_FACTORS":
        names += ["matchedFactorVsRowFactor", "matchedFactorVsColFactor"]
        keys += [[(s, r) for s, r in zip(subj, ri, strict=True)], [(s, c) for s, c in zip(subj, ci, strict=True)]]
    zs = [zmat(k) for k in keys]
    n_sub = len(set(subj))
    fit = Reml(y, x, zs).fit()
    kept = [i for i, g in enumerate(fit["g"]) if g > 0] if remove_nonpositive else list(range(len(zs)))
    removed = len(kept) < len(zs)
    if removed:
        fit2 = Reml(y, x, [zs[i] for i in kept]).fit()
        g = np.zeros(len(zs))
        g[kept] = fit2["g"]
        fit = {**fit2, "g": g}
    beta, cov, s2 = fit["beta"], fit["cov"], fit["s2"]

    # legacy error-strata df; the residual stratum loses the missing values
    if design == "REPEATED_MEASURES_BY_ROWS":
        df = {"col": n_sub - nc, "row": (nr - 1) * (n_sub - nc) - missing}
        df["int"] = df["row"]
        within = {"row": nr, "int": nr}
    elif design == "REPEATED_MEASURES_BY_COLS":
        df = {"row": n_sub - nr, "col": (nc - 1) * (n_sub - nr) - missing}
        df["int"] = df["col"]
        within = {"col": nc, "int": nc}
    else:
        df = {"row": (nr - 1) * (n_sub - 1), "col": (nc - 1) * (n_sub - 1),
              "int": (nr - 1) * (nc - 1) * (n_sub - 1) - missing}
        within = {"row": nr, "col": nc, "int": 0}
    if not kept:  # every random effect removed: ordinary residual df
        df = {k: n_obs - nr * nc for k in df}

    # Geisser-Greenhouse epsilon from pairwise covariances
    eps: dict[str, float] = {}
    if design == "REPEATED_MEASURES_BY_BOTH_FACTORS":
        mat = np.full((reps, nr * nc), np.nan)
        for v, r_, c_, s_ in zip(y, ri, ci, subj, strict=True):
            mat[s_[0], r_ * nc + c_] = v
        sc = _pooled_pairwise([mat])
        hr, hc = _helmert(nr), _helmert(nc)
        eps = {"row": _gg_cov(sc, np.kron(hr, np.ones((1, nc)) / math.sqrt(nc))),
               "col": _gg_cov(sc, np.kron(np.ones((1, nr)) / math.sqrt(nr), hc)),
               "int": _gg_cov(sc, np.kron(hr, hc))}
    else:
        by_rows = design == "REPEATED_MEASURES_BY_ROWS"
        ng, q = (nc, nr) if by_rows else (nr, nc)
        groups = [np.full((reps, q), np.nan) for _ in range(ng)]
        for v, r_, c_, sj in zip(y, ri, ci, subj, strict=True):
            gi, lev = (c_, r_) if by_rows else (r_, c_)
            groups[gi][sj[1], lev] = v
        e = _gg_cov(_pooled_pairwise(groups), _helmert(q))
        key = "row" if by_rows else "col"
        eps = {key: e, "int": e}

    term_names = {"row": "rowFactor", "col": "colFactor", "int": "rowFactorVsColFactor"}
    fixed = {}
    for k in ("row", "col", "int"):
        f = _wald(beta, cov, idx[k])
        d1, d2 = float(len(idx[k])), float(df[k])
        entry = {}
        if k in eps and not assume_sphericity and (design == "REPEATED_MEASURES_BY_BOTH_FACTORS" or within.get(k, 0) > 2):
            entry["ggEpsilon"] = eps[k]
            d1, d2 = d1 * eps[k], d2 * eps[k]
        entry["fTest"] = {"status": "VALID", "f": f, "dfNumerator": d1, "dfDenominator": d2,
                          "pValue": _p(stats.f.sf(f, d1, d2), alpha)}
        fixed[term_names[k]] = entry

    random_effects = {nm: {"sd": math.sqrt(g * s2), "variance": float(g * s2)} for nm, g in zip(names, fit["g"], strict=True)}
    random_effects["residual"] = {"sd": math.sqrt(s2), "variance": s2}
    if kept:
        null = Reml(y, x, []).fit()
        chi = 2 * (null["nll"] - fit["nll"])
        matching = {"status": "VALID", "chiSquared": float(chi), "df": float(len(kept)),
                    "pValue": _p(stats.chi2.sf(chi, len(kept)), alpha)}
    else:
        matching = {"status": "INVALID"}

    # least-squares means
    def lsm(r, c):
        lr, lc = _code(r, nr), _code(c, nc)
        return np.concatenate([[1.0], lr, lc, np.outer(lr, lc).ravel()])

    cell_m = np.array([[float(lsm(r, c) @ beta) for c in range(nc)] for r in range(nr)])
    out = {"status": "VALID",
           "fixedEffects": fixed, "randomEffects": random_effects, "matchingTest": matching}

    def diff_block(l1, l2, key):
        d = float((l1 - l2) @ beta)
        se = float(math.sqrt((l1 - l2) @ cov @ (l1 - l2)))
        tc = stats.t.ppf(1 - alpha / 2, df[key])
        return {"mean1": float(l1 @ beta), "mean2": float(l2 @ beta), "difference": d, "differenceSE": se,
                "differenceCI": {"lower": d - tc * se, "upper": d + tc * se, "level": alpha}}

    if nc == 2:
        out["differenceBetweenColMeans"] = diff_block(lsm(None, 0), lsm(None, 1), "col")
    if nr == 2:
        out["differenceBetweenRowMeans"] = diff_block(lsm(0, None), lsm(1, None), "row")
    out["means"] = {
        "total": float(cell_m.mean()),
        "rows": {f"row{r}": {"id": {"row": {"idx": r, "title": row_titles[r]}}, "value": float(cell_m[r].mean())}
                 for r in range(nr)},
        "cols": {f"col{c}": {"id": {"col": {"title": col_titles[c], "idx": c}}, "value": float(cell_m[:, c].mean())}
                 for c in range(nc)},
        "cells": {f"col{c}": {"id": {"col": {"title": col_titles[c], "idx": c}}, "value": {
            f"row{r}": {"id": {"row": {"idx": r, "title": row_titles[r]}}, "value": float(cell_m[r, c])}
            for r in range(nr)}} for c in range(nc)},
    }
    out["dataSummary"] = {"colCount": nc, "rowCount": nr, "matchedCount": n_sub, "missingCount": missing}
    n_removed = len(zs) - len(kept)
    warnings = ["MISSING_VALUES"] + ([] if not n_removed else ["RANDOM_EFFECT_REMOVED"] if n_removed == 1 else ["RANDOM_EFFECTS_REMOVED"])
    out["_fit"] = {"beta": beta, "cov": cov, "df": df, "lsm": lsm, "nr": nr, "nc": nc, "n_obs": n_obs}
    return {"repeatedMeasuresRemlAnovaModel": out, "_warnings": warnings}


# ------------------------------------------------------------------ one-way
def one_way_mixed(columns, alpha: float = 0.05, assume_sphericity: bool = False, remove_nonpositive: bool = True) -> dict:
    """columns[j][s]: treatment j, subject (row) s; None = missing."""
    k = len(columns)
    n_sub = max(len(c) for c in columns)
    ys, ti, si = [], [], []
    for j, col in enumerate(columns):
        for s, v in enumerate(col):
            if v is not None and math.isfinite(v):
                ys.append(float(v))
                ti.append(j)
                si.append(s)
    y, ti, si = np.array(ys), np.array(ti), np.array(si)
    n_obs = len(y)
    missing = k * n_sub - n_obs
    x = np.hstack([np.ones((n_obs, 1)), _effect(ti, k)])
    z = np.zeros((n_obs, n_sub))
    z[np.arange(n_obs), si] = 1.0
    z = z[:, z.sum(axis=0) > 0]
    fit = Reml(y, x, [z]).fit()
    kept = fit["g"][0] > 0 or not remove_nonpositive
    if not kept:
        fit = {**Reml(y, x, []).fit(), "g": np.zeros(1)}
    beta, cov, s2 = fit["beta"], fit["cov"], fit["s2"]
    df_den = (k - 1) * (z.shape[1] - 1) - missing if kept else n_obs - k
    f = _wald(beta, cov, list(range(1, k)))
    d1, d2 = float(k - 1), float(df_den)
    entry = {}
    if not assume_sphericity and k > 2:
        mat = np.full((n_sub, k), np.nan)
        mat[si, ti] = y
        e = _gg_cov(_pairwise_cov(mat, 1), _helmert(k))
        entry["ggEpsilon"] = e
        d1, d2 = d1 * e, d2 * e
    entry["fTest"] = {"status": "VALID", "f": f, "dfNumerator": d1, "dfDenominator": d2,
                      "pValue": _p(stats.f.sf(f, d1, d2), alpha)}
    out = {"status": "VALID", "fixedEffects": {"colFactor": entry},
           "randomEffects": {"matchedFactor": {"sd": math.sqrt(fit["g"][0] * s2), "variance": float(fit["g"][0] * s2)},
                             "residual": {"sd": math.sqrt(s2), "variance": s2}}}
    if kept:
        null = Reml(y, x, []).fit()
        chi = 2 * (null["nll"] - fit["nll"])
        out["matchingTest"] = {"status": "VALID", "chiSquared": float(chi), "df": 1.0, "pValue": _p(stats.chi2.sf(chi, 1), alpha)}
    else:
        out["matchingTest"] = {"status": "INVALID"}
    lmat = np.array([np.concatenate([[1.0], _code(j, k)]) for j in range(k)])
    out["_fit"] = {"beta": beta, "cov": cov, "df": float(df_den), "lsm": lmat @ beta, "lscov": lmat @ cov @ lmat.T, "k": k}
    warnings = ["RANDOM_EFFECT_REMOVED"] if not kept else []
    return {"repeatedMeasuresRemlAnovaModel": out, "_warnings": warnings}
