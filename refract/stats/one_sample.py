"""One-sample tests per column (Prism: ONE_SAMPLE_TESTS).

experimentalDesign: ONE_SAMPLE_T_TEST, WILCOXON_SIGNED_RANK_TEST (verified
names). Result keys follow Prism's results.json (samples keyed by column).
"""

from __future__ import annotations

import math

import numpy as np
from scipy import stats

from .descriptive import describe


def _p(value: float, alpha: float) -> dict:
    return {"value": float(value), "level": alpha, "isSignificant": bool(value < alpha), "state": "P_VALUE_EQUAL"}


def _clean(v) -> np.ndarray:
    return np.asarray([x for x in v if x is not None and math.isfinite(x)], dtype=float)


def t_test(x, mu: float, alpha: float = 0.05, level: float = 95.0) -> dict:
    x = _clean(x)
    n = len(x)
    d = describe(list(x), level)
    desc = {k: d[k] for k in ("n", "mean", "sd", "meanSE", "meanCI") if k in d}
    if n < 2:
        return {"tTestModel": {"status": "TOO_FEW_POINTS"}, "descriptiveStatistics": desc}
    sd = float(x.std(ddof=1))
    se = sd / math.sqrt(n)
    disc = float(x.mean() - mu)
    t = abs(disc) / se
    df = n - 1
    tc = stats.t.ppf(1 - (1 - level / 100) / 2, df)
    return {"tTestModel": {
        "status": "VALID",
        "tTest": {"status": "VALID", "t": t, "df": float(df), "pValue": _p(2 * stats.t.sf(t, df), alpha)},
        "discrepancy": {"discrepancy": disc, "stdDeviationDiscrepancy": sd, "stdErrorOfDiscrepancy": se,
                        "confidenceIntervalDiscrepancy": {"lower": disc - tc * se, "upper": disc + tc * se, "level": level},
                        "rSquared": t * t / (t * t + df)}},
        "descriptiveStatistics": desc}


def _signed_rank_exact(ranks2: np.ndarray, observed2: int) -> float:
    total = int(ranks2.sum())
    dist = np.zeros(total + 1)
    dist[0] = 1.0
    for r in ranks2.astype(int):
        nd = dist.copy()
        nd[r:] += dist[: total + 1 - r]
        dist = nd
    dist /= dist.sum()
    e = total / 2
    dev = abs(observed2 - e)
    w = np.arange(total + 1)
    return float(min(1.0, dist[np.abs(w - e) >= dev - 1e-9].sum()))


def wilcoxon_signed_rank(x, mu: float, alpha: float = 0.05, pratt: bool = True) -> dict:
    """Pratt's method (default in Prism): rank |x - mu| including zeros, then
    drop the zero ranks; otherwise Wilcoxon's method (drop zeros first)."""
    x = _clean(x)
    n = len(x)
    d = x - mu
    zeros = int((d == 0).sum())
    desc_all = describe(list(x))
    desc = {k: desc_all[k] for k in ("n", "minimum", "firstQuartile", "median", "thirdQuartile", "maximum") if k in desc_all}
    if n < 3:
        return {"wilcoxonTestModel": {"status": "VALID", "wilcoxonTest": {"status": "TOO_FEW_POINTS"}},
                "descriptiveStatistics": desc}
    if pratt:
        r = stats.rankdata(np.abs(d))
        keep = d != 0
        rk, sk = r[keep], np.sign(d[keep])
    else:
        nz = d[d != 0]
        rk, sk = stats.rankdata(np.abs(nz)), np.sign(nz)
    pos = float(rk[sk > 0].sum())
    neg = -float(rk[sk < 0].sum())
    r2 = np.rint(2 * rk).astype(int)
    exact = _signed_rank_exact(r2, round(2 * pos)) if len(rk) else 1.0
    m = len(rk)
    var = (rk ** 2).sum() / 4  # variance of W+ given the (mid)ranks
    # normal approximation with continuity correction (as Prism)
    # normal approximation with continuity correction, |(|W - E|) - 0.5| as Prism
    approx = float(2 * stats.norm.sf(abs(abs(pos - rk.sum() / 2) - 0.5) / math.sqrt(var))) if m and var > 0 else 1.0
    # CI of the median from order statistics (sign-test interval), coverage >= 95%
    # (x_(k), x_(n+1-k)) covers the median with probability 1 - 2 P(B <= k-1);
    # take the narrowest with coverage >= 95%, at least min..max (n <= 5 falls short)
    xs = np.sort(x)
    k = 1
    while k + 1 <= n / 2 and 1 - 2 * stats.binom.cdf(k, n, 0.5) >= 0.95:
        k += 1
    cover = 1 - 2 * stats.binom.cdf(k - 1, n, 0.5)
    lo, hi = float(xs[k - 1]), float(xs[n - k])
    med = float(np.median(x))
    return {"wilcoxonTestModel": {
        "status": "VALID",
        "wilcoxonTest": {"status": "VALID", "zeroesStatus": "WITH_ZEROES" if zeros else "NO_ZEROES",
                         "signedRanksSum": pos + neg, "positiveRanksSum": pos, "negativeRanksSum": neg, "n": n,
                         "tieCount": zeros, "pValue": _p(exact, alpha), "pValueExact": _p(exact, alpha),
                         "pValueApproximate": _p(approx, alpha)},
        "discrepancy": {"discrepancy": med - mu, "confidenceIntervalDiscrepancy": {
            "lower": lo - mu, "upper": hi - mu, "level": 100 * cover}}},
        "descriptiveStatistics": desc}


def one_sample(params: dict, columns: list, titles: list[str]) -> dict:
    design = params.get("experimentalDesign", "ONE_SAMPLE_T_TEST")
    mu = params.get("calc", {}).get("hypotheticalValue", 0.0)
    alpha = params.get("options", {}).get("significanceLevel", 0.05)
    samples = {}
    for i, col in enumerate(columns):
        if design == "ONE_SAMPLE_T_TEST":
            v = t_test(col, mu, alpha, 100 * (1 - alpha))
        elif design == "WILCOXON_SIGNED_RANK_TEST":
            v = wilcoxon_signed_rank(col, mu, alpha, params.get("calc", {}).get("usePrattMethod", True))
        else:
            raise NotImplementedError(f"one-sample design {design}")
        samples[f"col{i}"] = {"id": {"col": {"title": titles[i], "idx": i}}, "value": v}
    return {"status": {"error": "VALID", "warning": []}, "samples": samples}
