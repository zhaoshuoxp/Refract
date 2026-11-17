"""Column statistics (Prism: COLUMN_STATISTICS), with Prism's result keys.

Percentiles use the (n+1)p rule with linear interpolation (Hyndman & Fan
type 6), clipped to the minimum/maximum. This reproduces Prism's quartiles
and percentiles (checked by hand on the Geometric mean sample and by the
oracle tests). Skewness and kurtosis are the bias-adjusted sample statistics.
"""

from __future__ import annotations

import math

import numpy as np
from scipy import stats


def percentile(sorted_x: np.ndarray, p: float) -> float:
    n = len(sorted_x)
    pos = (n + 1) * p
    if pos <= 1:
        return float(sorted_x[0])
    if pos >= n:
        return float(sorted_x[-1])
    lo = math.floor(pos)
    frac = pos - lo
    return float(sorted_x[lo - 1] + frac * (sorted_x[lo] - sorted_x[lo - 1]))


def _t_ci(mean: float, se: float, n: int, level: float) -> dict:
    if n < 2 or not math.isfinite(se):
        return {"lower": math.nan, "upper": math.nan, "level": level}
    t = stats.t.ppf(0.5 + level / 200, n - 1)
    return {"lower": mean - t * se, "upper": mean + t * se, "level": level}


def describe(values, confidence_level: float = 95.0, percentile_level: float = 90.0) -> dict:
    x = np.asarray([v for v in values if v is not None and math.isfinite(v)], dtype=float)
    n = len(x)
    out: dict = {"n": n}
    if n == 0:
        return out
    xs = np.sort(x)
    mean = float(x.mean())
    out["sum"] = float(x.sum())
    out["mean"] = mean
    sd = float(x.std(ddof=1)) if n > 1 else math.nan
    se = sd / math.sqrt(n) if n > 1 else math.nan
    out["sd"] = sd
    out["meanSE"] = se
    out["meanCI"] = _t_ci(mean, se, n, confidence_level)
    out["coeffOfVariation"] = sd / abs(mean) * 100 if n > 1 and mean != 0 else math.nan  # Prism: SD/|mean|
    if n > 2 and sd > 0:
        z = (x - mean) / sd
        out["skewness"] = float(n / ((n - 1) * (n - 2)) * np.sum(z ** 3))
    if n > 3 and sd > 0:
        z = (x - mean) / sd
        out["kurtosis"] = float(n * (n + 1) / ((n - 1) * (n - 2) * (n - 3)) * np.sum(z ** 4)
                                - 3 * (n - 1) ** 2 / ((n - 2) * (n - 3)))
    if n > 1:
        out["qcLines"] = {f"mean{s}{k}SD": mean + (1 if s == "Plus" else -1) * k * sd
                          for s in ("Minus", "Plus") for k in (3, 2, 1)}
    out["minimum"] = float(xs[0])
    out["firstQuartile"] = percentile(xs, 0.25)
    out["median"] = percentile(xs, 0.5)
    out["thirdQuartile"] = percentile(xs, 0.75)
    out["maximum"] = float(xs[-1])
    # Prism's "90% percentiles" are the 10th and 90th percentiles
    out["percentiles"] = {"lower": percentile(xs, 1 - percentile_level / 100), "upper": percentile(xs, percentile_level / 100),
                          "level": percentile_level}
    out["range"] = float(xs[-1] - xs[0])
    if np.all(x > 0):
        lx = np.log(x)
        gm = float(np.exp(lx.mean()))
        out["geometricMean"] = gm
        if n > 1:
            lsd = float(lx.std(ddof=1))
            out["geometricSD"] = float(np.exp(lsd))
            ci = _t_ci(float(lx.mean()), lsd / math.sqrt(n), n, confidence_level)
            out["geometricMeanCI"] = {"lower": math.exp(ci["lower"]), "upper": math.exp(ci["upper"]), "level": confidence_level}
    return out


def extras(values, level: float, calc: dict) -> dict:
    """The optional statistics of Prism's descriptive statistics (verified, E-mv): the median's
    CI (the narrowest pair of order statistics whose exact binomial level is at least `level`,
    reported at that level), the harmonic mean (positive values; CI: the t interval of the
    reciprocals, inverted) and the quadratic mean (CI: the square root of the t interval of
    the squares, its lower end at least 0)."""
    from scipy import stats

    x = np.asarray([v for v in values if v is not None and math.isfinite(v)], dtype=float)
    n = len(x)
    out: dict = {}
    if n < 2:
        return out
    tc = float(stats.t.ppf(1 - (1 - level / 100) / 2, n - 1))
    if calc.get("medianCI"):
        xs = np.sort(x)
        best = None
        for k in range(1, n // 2 + 1):
            lev = 1 - 2 * float(stats.binom.cdf(k - 1, n, 0.5))
            if lev >= level / 100 - 1e-12:
                best = (k, lev)
        if best is not None:
            k, lev = best
            out["medianCI"] = {"lower": float(xs[k - 1]), "upper": float(xs[n - k]), "level": 100 * lev}
    if (calc.get("harmonicMean") or calc.get("harmonicMeanCI")) and (x > 0).all():
        r = 1 / x
        m, se = float(r.mean()), float(r.std(ddof=1)) / math.sqrt(n)
        if calc.get("harmonicMean"):
            out["harmonicMean"] = 1 / m
        if calc.get("harmonicMeanCI") and m - tc * se > 0:
            out["harmonicMeanCI"] = {"lower": 1 / (m + tc * se), "upper": 1 / (m - tc * se), "level": level}
    if calc.get("quadraticMean") or calc.get("quadraticMeanCI"):
        q = x ** 2
        m, se = float(q.mean()), float(q.std(ddof=1)) / math.sqrt(n)
        if calc.get("quadraticMean"):
            out["quadraticMean"] = math.sqrt(m)
        if calc.get("quadraticMeanCI"):
            out["quadraticMeanCI"] = {"lower": math.sqrt(max(0.0, m - tc * se)), "upper": math.sqrt(m + tc * se),
                                      "level": level}
    return out
