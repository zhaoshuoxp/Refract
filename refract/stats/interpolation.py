"""Interpolate a standard curve (Prism: INTERPOLATION): fit the model to the
rows that have an X (refract.stats.nonlinear, the same fit as a nonlinear
regression), then read off X for each row that has a Y but no X - the
unknowns (verified against Prism 11.1, E-stats8b).

Results as Prism gives them: the fit per data set, its runs test when asked
(diagnostics.runsTest), each data set's counts in a top-level dataSummary,
and the table of interpolated X values (unknown Y as entered, X read off).
"""

from __future__ import annotations

import math

import numpy as np
from scipy import optimize

from . import nonlinear as NL
from .equation import Model
from .xy_basic import runs_test

EXTEND = 0.5  # Prism reads off X up to half the standards' X range beyond either end (verified)


def limits(known: list[float]) -> tuple[float, float]:
    """The X range Prism reports interpolated values in: the standards' range extended by half of it on
    each side, but not below zero when every standard's X is at least zero (verified, E-stats8b)."""
    lo, hi = min(known), max(known)
    r = hi - lo
    return (max(lo - EXTEND * r, 0.0) if lo >= 0 else lo - EXTEND * r), hi + EXTEND * r


def replicates_test(xs: np.ndarray, ys: np.ndarray, fitted: np.ndarray, k: int, alpha: float = 0.05) -> dict:
    """The replicates (lack-of-fit) test: scatter of the replicates about their means against the
    scatter of those means about the curve (an F test; Prism's names)."""
    from scipy import stats

    groups: dict[float, list[int]] = {}
    for i, x in enumerate(xs.tolist()):
        groups.setdefault(x, []).append(i)
    ss_pure = sum(float(((ys[g] - ys[g].mean()) ** 2).sum()) for g in map(np.array, groups.values()))
    df_pure = len(ys) - len(groups)
    ss_res = float(((ys - fitted) ** 2).sum())
    df_lof = len(groups) - k
    if df_pure <= 0 or df_lof <= 0 or ss_pure <= 0:
        return {"status": "NOT_ENOUGH_DATA"}
    ms_pure, ms_lof = ss_pure / df_pure, (ss_res - ss_pure) / df_lof
    f = ms_lof / ms_pure
    pv = float(stats.f.sf(f, df_lof, df_pure))
    return {"status": "VALID", "sdReplicates": math.sqrt(ms_pure), "sdLackOfFit": math.sqrt(max(ms_lof, 0.0)),
            "f": f, "dfNumerator": float(df_lof), "dfDenominator": float(df_pure),
            "pValue": {"value": pv, "level": alpha, "isSignificant": bool(pv < alpha), "state": "P_VALUE_EQUAL"}}


def _inverse(model: Model, p: np.ndarray, y: float, lo: float, hi: float) -> float | None:
    """The X in [lo, hi] where the curve reaches y."""
    grid = np.linspace(lo, hi, 4001)
    f = np.asarray(model(grid, p), float) - y
    if np.allclose(np.diff(f, 2), 0, atol=1e-12 * max(1.0, float(np.abs(f).max()))):  # a straight line
        slope = (f[-1] - f[0]) / (hi - lo) if hi != lo else 0.0
        v = None if slope == 0 else float(lo - f[0] / slope)
        return v if v is not None and lo <= v <= hi else None
    for i in range(len(grid) - 1):
        if f[i] == 0:
            return float(grid[i])
        if f[i] * f[i + 1] < 0:
            return float(optimize.brentq(lambda v: float(model(np.array([v]), p)[0]) - y, grid[i], grid[i + 1],
                                         xtol=1e-14, rtol=1e-14))
    return None


def interpolate(params: dict, x: list, columns: list, titles: list[str], data_format: str) -> dict:
    """columns: per data set its subcolumns [sub][row]; x: X per row (None: an unknown)."""
    eq = params["model"]["equation"]
    names = list(eq["parameters"])
    model = Model(eq["definition"], names)
    if "confidence" not in params:  # Prism's interpolation reports asymptotic (symmetrical) intervals
        level = (params.get("graph", {}).get("curveBands") or {}).get("level", 95.0)
        params = {**params, "confidence": {"ciMethod": "ASYMPTOTIC", "confidenceLevel": level}}
    runs = bool((params.get("diagnostics") or {}).get("runsTest"))
    models, summary, tables = {}, {}, {}
    each: list = []  # (data set, [(X, Y) of each unknown value])
    means: list = []
    xv = list(x or [])
    for i, subs in enumerate(columns):
        ident = {"col": {"title": titles[i], "idx": i}}
        fit = NL.fit_dataset(params, xv, subs, i, data_format=data_format)
        ds = fit.pop("dataSummary", None)
        if ds is not None:
            summary[f"col{i}"] = {"id": dict(ident), "value": ds}
        p = np.array([fit["parameters"][n]["estimate"] for n in names], float)
        xs, ys, _ = NL._points(xv, subs)
        reps = len(set(xs.tolist())) < len(xs)
        if reps and len(xs):
            fit["replicatesTest"] = replicates_test(xs, ys, np.asarray(model(xs, p), float), len(names))
        elif runs and fit.get("status") == "PERFECT_FIT":
            fit["runsTest"] = {"status": "INVALID", "pointsAboveCount": 0, "pointsBelowCount": 0, "runsCount": 0}
        elif runs and len(xs):
            res = ys - np.asarray(model(xs, p), float)
            res[np.abs(res) <= 1e-9 * max(1.0, float(np.abs(ys).max()))] = 0.0  # on the curve: neither side
            fit["runsTest"] = runs_test(xs, res)
        models[f"col{i}"] = {"id": {**ident, "model": {"name": "Model 1", "title": eq.get("name", "")}},
                             "value": fit}
        # the unknowns: rows with a Y and no X; each value read off, and (replicates) the mean of each row
        known = [v for v in xv if v is not None and math.isfinite(v)]
        lo, hi = limits(known) if known else (0.0, 1.0)
        for r in range(max((len(s) for s in subs), default=0)):
            if r < len(xv) and xv[r] is not None:
                continue
            vals = [float(s[r]) for s in subs if r < len(s) and s[r] is not None and math.isfinite(s[r])]
            if vals:
                each.append((i, [(_inverse(model, p, y, lo, hi), y) for y in vals]))
                mean = float(np.mean(vals))
                means.append((i, [(_inverse(model, p, mean, lo, hi), mean)]))
    cols = ["X", *(f"{t} (Entered)" for t in titles)]

    def stacked(found):  # the data sets one below the other, each Y in its own column (as Prism)
        rows = []
        for i, pts in found:
            for xi, y in pts:
                row = [xi] + [None] * len(titles)
                row[i + 1] = y
                rows.append(row)
        return {"columns": cols, "rows": rows, "row_titles": None}

    if each and data_format == "y_replicates":
        tables["Interpolated X mean values"] = stacked(means)
        tables["Interpolated  X replicates"] = stacked(each)  # Prism's title, with its two spaces
    elif each:
        tables["Interpolated X values"] = stacked(each)
    bands = (params.get("graph") or {}).get("curveBands") or {}
    fits = [m["value"] for m in models.values()]
    tables["Curve"] = NL.curve_table(params, xv, columns, titles, fits,
                                     bands.get("level", 95.0) if bands.get("type") == "CONFIDENCE" else None,
                                     data_format)
    out = {"status": {"error": "VALID", "warning": []}, "models": models}
    if summary:
        out["dataSummary"] = summary
    if tables:
        out["_tables"] = tables
    return out
