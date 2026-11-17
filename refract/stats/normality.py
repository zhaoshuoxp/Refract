"""Normality and lognormality tests per column (Prism: NORMALITY_TESTS).

Tests: D'Agostino-Pearson omnibus K2, Anderson-Darling A2, Shapiro-Wilk W,
Kolmogorov-Smirnov (Lilliefors distance, Dallal-Wilkinson P, "> 0.10" above
0.1), plus the relative likelihood of a normal vs a lognormal fit. Result keys
follow Prism's results.json.
"""

from __future__ import annotations

import math

import numpy as np
from scipy import stats

from .descriptive import describe


def _p(value: float, alpha: float, state: str = "P_VALUE_EQUAL") -> dict:
    return {"value": float(value), "level": alpha, "isSignificant": bool(value < alpha), "state": state}


def dagostino_pearson(x: np.ndarray, alpha: float) -> dict:
    k2, p = stats.normaltest(x)
    return {"status": "VALID", "K2": float(k2), "pValue": _p(p, alpha)}


def anderson_darling(x: np.ndarray, alpha: float) -> dict:
    n = len(x)
    z = np.sort((x - x.mean()) / x.std(ddof=1))
    cdf = stats.norm.cdf(z)
    i = np.arange(1, n + 1)
    a2 = float(-n - np.sum((2 * i - 1) * (np.log(cdf) + np.log1p(-cdf[::-1]))) / n)
    a = a2 * (1 + 0.75 / n + 2.25 / n ** 2)  # D'Agostino & Stephens (1986) correction
    if a >= 0.6:
        p = math.exp(1.2937 - 5.709 * a + 0.0186 * a * a)
    elif a >= 0.34:
        p = math.exp(0.9177 - 4.279 * a - 1.38 * a * a)
    elif a >= 0.2:
        p = 1 - math.exp(-8.318 + 42.796 * a - 59.938 * a * a)
    else:
        p = 1 - math.exp(-13.436 + 101.14 * a - 223.73 * a * a)
    return {"status": "VALID", "A2": a2, "pValue": _p(min(1.0, max(0.0, p)), alpha)}


def shapiro_wilk(x: np.ndarray, alpha: float) -> dict:
    w, p = stats.shapiro(x)
    if len(x) == 3:  # exact n = 3 formula with Prism's 7-digit constants for 6/pi and pi/3 (verified)
        p = min(1.0, max(0.0, 1.909859 * (math.asin(math.sqrt(w)) - 1.047198)))
    return {"status": "VALID", "W": float(w), "pValue": _p(p, alpha)}


def kolmogorov_smirnov(x: np.ndarray, alpha: float) -> dict:
    n = len(x)
    z = np.sort((x - x.mean()) / x.std(ddof=1))
    cdf = stats.norm.cdf(z)
    i = np.arange(1, n + 1)
    d = float(max((i / n - cdf).max(), (cdf - (i - 1) / n).max()))
    nn, dd = (n, d) if n <= 100 else (100, d * (n / 100) ** 0.49)
    p = math.exp(-7.01256 * dd * dd * (nn + 2.78019) + 2.99587 * dd * math.sqrt(nn + 2.78019) - 0.122119
                 + 0.974598 / math.sqrt(nn) + 1.67997 / nn)  # Dallal & Wilkinson (1986)
    if p > 0.1:
        return {"status": "VALID", "distance": d, "pValue": _p(0.1, alpha, "P_VALUE_GREATER")}
    return {"status": "VALID", "distance": d, "pValue": _p(p, alpha)}


TESTS = (("dAgostinoPearson", "dAgostinoPearsonTest", dagostino_pearson, 8),
         ("andersonDarling", "andersonDarlingTest", anderson_darling, 8),
         ("shaproWilks", "shapiroWilkTest", shapiro_wilk, 3),  # sic: Prism's parameter key
         ("kolmogorovSmirnov", "kolmogorovSmirnovTest", kolmogorov_smirnov, 5))


def _model(x: np.ndarray, which: dict, alpha: float, run: bool) -> dict:
    out = {"status": "VALID"}
    passed = True
    if run:
        for key, name, fn, nmin in TESTS:
            if not which.get(key, True):
                continue
            if len(x) < nmin:
                out[name] = {"status": "TOO_FEW_POINTS"}
                continue
            t = fn(x, alpha)
            out[name] = t
            passed = passed and t["pValue"]["value"] >= alpha
    out["allTestsPassed"] = passed
    return out


def relative_likelihood(x: np.ndarray) -> dict:
    """Likelihoods of a normal and a lognormal fit, as Prism computes them:
    (2 pi s^2)^(-n/2) exp(-n/2) with the n-1 SD (lognormal: of ln x, times the
    Jacobian prod 1/x). The ratio is the same as with MLE SDs."""
    n = len(x)
    s2 = x.var(ddof=1)
    ln = np.log(x)
    sl2 = ln.var(ddof=1)
    l_norm = float(math.exp(-n / 2 * math.log(2 * math.pi * s2) - n / 2))
    l_log = float(math.exp(-n / 2 * math.log(2 * math.pi * sl2) - n / 2 - ln.sum()))
    tot = l_norm + l_log
    return {"status": "VALID", "likelihoodRatio": l_norm / l_log, "likelihoodRatioInverse": l_log / l_norm,
            "likelihoodNormal": l_norm, "likelihoodLognormal": l_log, "probabilityNormal": l_norm / tot,
            "probabilityLognormal": l_log / tot,
            "preferredDistribution": "PREFERRED_DISTRIBUTION_NORMAL" if l_norm >= l_log else "PREFERRED_DISTRIBUTION_LOGNORMAL"}


def normality(params: dict, columns: list, titles: list[str]) -> dict:
    calc = params.get("calc", {})
    which = calc.get("tests", {})
    alpha = params.get("options", {}).get("significanceLevel", 0.05)
    samples = {}
    for i, col in enumerate(columns):
        x = np.asarray([v for v in col if v is not None and math.isfinite(v)], float)
        d = describe(list(x))
        normal = _model(x, which, alpha, calc.get("testforNormality", True))
        normal["descriptiveStatistics"] = {k: d[k] for k in ("n", "mean", "sd") if k in d}
        positive = bool((x > 0).all())
        want_log = calc.get("testforLognormality", False)
        want_rl = calc.get("testRelativeLikelihood", False)
        if positive:
            logm = _model(np.log(x), which, alpha, want_log)
            if len(x):
                logm["descriptiveStatistics"] = {"n": len(x), **{k: d[k] for k in ("geometricMean", "geometricSD") if k in d}}
        else:
            logm = {"status": "NON_POSITIVE_VALUES", "allTestsPassed": True}
        v = {"normalityModel": normal, "lognormalityModel": logm}
        if want_rl:
            v["relativeLikelihoodTest"] = (relative_likelihood(x) if positive else
                                           {"status": "UNDEFINED_LOGNORMAL_MODEL",
                                            "preferredDistribution": "PREFERRED_DISTRIBUTION_NORMAL"})
        v["dataSummary"] = {"valueCount": len(x)}
        if want_log or want_rl:
            v["dataSummary"]["impossibleValues"] = {"zeroCount": int((x == 0).sum()), "negativeCount": int((x < 0).sum())}
        samples[f"col{i}"] = {"id": {"col": {"title": titles[i], "idx": i}}, "value": v}
    return {"status": {"error": "VALID", "warning": []}, "samples": samples}
