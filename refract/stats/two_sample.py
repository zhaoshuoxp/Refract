"""Two-sample tests (Prism: T_TESTS_AND_NONPARAMETRIC), with Prism's result
keys. `a` is column A, `b` column B; with Prism's default swapDirection=true
differences are B - A.

Designs (Prism `experimentalDesign` values, confirmed by the oracle):
UNPAIRED_T_TEST, WELCH_T_TEST, PAIRED_T_TEST, RATIO_PAIRED_T_TEST,
MANN_WHITNEY_TEST, WILCOXON_TEST, KOLMOGOROV_SMIRNOV_TEST.
"""

from __future__ import annotations

import math

import numpy as np
from scipy import stats


def _exact_rank_sum_p(ranks: np.ndarray, n1: int, observed: float) -> float:
    """Exact two-tailed P for the rank sum of a group of n1 among all values,
    conditional on the (possibly tied, mid-)ranks: dynamic programming over
    subsets, on doubled ranks so mid-ranks stay integral. Matches Prism's
    exact Mann-Whitney P with and without ties."""
    r2 = np.rint(np.asarray(ranks) * 2).astype(int)
    total = int(r2.sum())
    dp = np.zeros((n1 + 1, total + 1))
    dp[0, 0] = 1.0
    for v in r2:
        dp[1:, v:] = dp[1:, v:] + dp[:-1, : total + 1 - v]
    dist = dp[n1] / dp[n1].sum()
    w = round(observed * 2)
    lo, hi = dist[: w + 1].sum(), dist[w:].sum()
    return float(min(1.0, 2 * min(lo, hi)))


def _exact_signed_rank_p(abs_ranks: np.ndarray, observed_pos: float) -> float:
    """Exact two-tailed P for the Wilcoxon positive-rank sum over all 2^n sign
    assignments, conditional on tied mid-ranks (doubled to integers)."""
    r2 = np.rint(np.asarray(abs_ranks) * 2).astype(int)
    total = int(r2.sum())
    dist = np.zeros(total + 1)
    dist[0] = 1.0
    for v in r2:
        nxt = dist.copy()
        nxt[v:] += dist[: total + 1 - v]
        dist = nxt
    dist /= dist.sum()
    w = round(observed_pos * 2)
    lo, hi = dist[: w + 1].sum(), dist[w:].sum()
    return float(min(1.0, 2 * min(lo, hi)))


_SPEARMAN_CACHE: dict[tuple, np.ndarray] = {}


def _spearman_exact_distribution(rx: np.ndarray, ry: np.ndarray) -> tuple[np.ndarray, int]:
    """Distribution of S = sum (rx_i - ry_pi(i))^2 over all n! pairings
    (mid-ranks doubled so S*4 is integral). Dynamic programming over the set
    of y-ranks already used. Exact for n <= 17 in about a second, matching
    Prism to machine precision (oracle, n = 9..17)."""
    x2 = np.rint(np.asarray(rx) * 2).astype(int)
    y2 = np.rint(np.asarray(ry) * 2).astype(int)
    key = (tuple(x2), tuple(sorted(y2)))
    if key in _SPEARMAN_CACHE:
        return _SPEARMAN_CACHE[key], 4
    n = len(x2)
    smax = int(sum(max((xi - yj) ** 2 for yj in y2) for xi in x2))
    layer = {0: np.zeros(smax + 1)}
    layer[0][0] = 1.0
    for i in range(n):
        nxt: dict[int, np.ndarray] = {}
        for mask, arr in layer.items():
            for j in range(n):
                if mask >> j & 1:
                    continue
                c = int((x2[i] - y2[j]) ** 2)
                m2 = mask | (1 << j)
                tgt = nxt.get(m2)
                if tgt is None:
                    tgt = nxt[m2] = np.zeros(smax + 1)
                tgt[c:] += arr[: smax + 1 - c]
        layer = nxt
    dist = next(iter(layer.values()))
    dist = dist / dist.sum()
    _SPEARMAN_CACHE[key] = dist
    return dist, 4


def spearman_pairing(a: np.ndarray, b: np.ndarray, alpha: float) -> dict:
    """Spearman r with the one-tailed P Prism reports for "was the pairing
    effective": exact permutation P (direction of the observed sign) for
    n <= 17, otherwise the t approximation's two-tailed P / 2."""
    n = len(a)
    rs, p2 = stats.spearmanr(a, b)
    out = {"status": "VALID", "r": float(rs)}
    if n <= 17:
        rx, ry = stats.rankdata(a), stats.rankdata(b)
        dist, scale = _spearman_exact_distribution(rx, ry)
        s_obs = round(float(((rx - ry) ** 2).sum()) * scale)
        p = float(dist[: s_obs + 1].sum() if rs > 0 else dist[s_obs:].sum())
        out["pValue"] = _p(p, alpha)
        out["pValueExact"] = _p(p, alpha)
    else:
        out["pValue"] = _p(float(p2) / 2, alpha)
        out["pValueApproximate"] = _p(float(p2) / 2, alpha)
    return out


def _ks_exact_conditional(a: np.ndarray, b: np.ndarray, d_obs: float) -> float:
    """Exact P(D >= d) for the two-sample K-S statistic under the permutation
    distribution conditional on ties: lattice paths over the distinct pooled
    values, checked only at the end of each tie group. Matches Prism's exact
    P except where Prism's own floating point drops a lattice point lying
    exactly on D (seen once, 5 vs 7 values; docs/format/findings.md)."""
    n1, n2 = len(a), len(b)
    _, counts = np.unique(np.concatenate([a, b]), return_counts=True)
    eps = 1e-12
    dp = {(0, 0): 1}
    hit = 0
    for g in counts:
        nxt: dict[tuple[int, int], int] = {}
        for (i, j), w in dp.items():
            for k1 in range(g + 1):
                i2, j2 = i + k1, j + g - k1
                if i2 > n1 or j2 > n2:
                    continue
                ww = w * math.comb(int(g), k1)
                if abs(i2 / n1 - j2 / n2) >= d_obs - eps:
                    hit += ww * math.comb(n1 + n2 - i2 - j2, n1 - i2)
                    continue
                nxt[(i2, j2)] = nxt.get((i2, j2), 0) + ww
        dp = nxt
    return hit / math.comb(n1 + n2, n1)


def _normal_cc_p(stat: float, mu: float, sigma: float) -> float:
    """Two-tailed normal approximation with continuity correction, taking
    |z| (Prism does not cap at 1 when |stat - mu| < 0.5)."""
    if sigma <= 0:
        return 1.0
    z = (abs(stat - mu) - 0.5) / sigma
    return float(min(1.0, 2 * stats.norm.sf(abs(z))))


def _p(value: float, alpha: float) -> dict:
    return {"value": value, "level": alpha, "isSignificant": bool(value < alpha), "state": "P_VALUE_EQUAL"}


def _clean(v) -> np.ndarray:
    return np.asarray([x for x in v if x is not None and math.isfinite(x)], dtype=float)


def _pairs(a, b) -> tuple[np.ndarray, np.ndarray]:
    pa, pb = [], []
    for x, y in zip(a, b, strict=False):
        if x is not None and y is not None and math.isfinite(x) and math.isfinite(y):
            pa.append(x)
            pb.append(y)
    return np.asarray(pa), np.asarray(pb)


def _ci(est: float, se: float, df: float, level: float) -> dict:
    t = stats.t.ppf(0.5 + level / 200, df)
    return {"lower": est - t * se, "upper": est + t * se, "level": level}


def _two_tailed_t(t: float, df: float) -> float:
    return float(2 * stats.t.sf(abs(t), df))


def _variance_f(a: np.ndarray, b: np.ndarray, alpha: float) -> dict:
    va, vb = a.var(ddof=1), b.var(ddof=1)
    if va >= vb:
        f, d1, d2 = va / vb, len(a) - 1, len(b) - 1
    else:
        f, d1, d2 = vb / va, len(b) - 1, len(a) - 1
    p = min(1.0, 2 * stats.f.sf(f, d1, d2))
    return {"status": "VALID", "f": float(f), "dfNumerator": float(d1), "dfDenominator": float(d2), "pValue": _p(float(p), alpha)}


def _sign(swap: bool) -> int:
    return 1 if swap else -1


def unpaired_t(a, b, swap=True, alpha=0.05, level=95.0, welch=False) -> dict:
    a, b = _clean(a), _clean(b)
    n1, n2 = len(a), len(b)
    m1, m2 = float(a.mean()), float(b.mean())
    diff = (m2 - m1) * _sign(swap)
    v1, v2 = a.var(ddof=1), b.var(ddof=1)
    if welch:
        se = math.sqrt(v1 / n1 + v2 / n2)
        df = (v1 / n1 + v2 / n2) ** 2 / ((v1 / n1) ** 2 / (n1 - 1) + (v2 / n2) ** 2 / (n2 - 1))
    else:
        df = n1 + n2 - 2
        sp2 = ((n1 - 1) * v1 + (n2 - 1) * v2) / df
        se = math.sqrt(sp2 * (1 / n1 + 1 / n2))
    t = diff / se
    test = {"status": "VALID", "t": abs(t), "df": float(df), "pValue": _p(_two_tailed_t(t, df), alpha)}
    key = "welchTTest" if welch else "unpairedTTest"
    return {key + "Model": {
        "status": "VALID", key: test,
        "differenceOfMeans": {"n1": n1, "mean1": m1, "n2": n2, "mean2": m2, "difference": diff,
                              "stdErrorOfDifference": se, "confidenceIntervalOfDifference": _ci(diff, se, df, level),
                              "rSquared": t * t / (t * t + df)},
        "varianceTest": _variance_f(a, b, alpha)}}


def paired_t(a, b, swap=True, alpha=0.05, level=95.0) -> dict:
    a, b = _pairs(a, b)
    d = (b - a) * _sign(swap)
    n = len(d)
    mean, sd = float(d.mean()), float(d.std(ddof=1))
    se = sd / math.sqrt(n)
    df = n - 1
    t = mean / se
    r, pr = stats.pearsonr(a, b)
    return {"pairedTTestModel": {
        "status": "VALID",
        "pairedTTest": {"status": "VALID", "t": abs(t), "df": float(df), "pValue": _p(_two_tailed_t(t, df), alpha)},
        "meanOfDifferences": {"mean": mean, "stdDeviationOfDifferences": sd, "stdErrorOfDifferences": se,
                              "confidenceIntervalOfDifferences": _ci(mean, se, df, level), "rSquared": t * t / (t * t + df)},
        "pearsonTest": {"status": "VALID", "r": float(r), "pValue": _p(float(pr) / 2, alpha),
                        "pValueOneTailed": _p(float(pr) / 2, alpha)}}}


def ratio_paired_t(a, b, swap=True, alpha=0.05, level=95.0) -> dict:
    a, b = _pairs(a, b)
    lr = np.log10(b / a) * _sign(swap)
    n = len(lr)
    mean, sd = float(lr.mean()), float(lr.std(ddof=1))
    se = sd / math.sqrt(n)
    df = n - 1
    t = mean / se
    ci = _ci(mean, se, df, level)
    r, pr = stats.pearsonr(np.log10(a), np.log10(b))
    return {"ratioPairedTTestModel": {
        "status": "VALID",
        "ratioPairedTTest": {"status": "VALID", "t": abs(t), "df": float(df), "pValue": _p(_two_tailed_t(t, df), alpha)},
        "ratioOfPairs": {"geometricMeanOfRatios": 10 ** mean, "stdDeviationOfLogRatios": sd, "stdErrorOfLogRatios": se,
                         "confidenceIntervalOfGeometricMean": {"lower": 10 ** ci["lower"], "upper": 10 ** ci["upper"], "level": level},
                         "rSquared": t * t / (t * t + df)},
        "pearsonTest": {"status": "VALID", "r": float(r), "pValue": _p(float(pr) / 2, alpha),
                        "pValueOneTailed": _p(float(pr) / 2, alpha)}}}


def mann_whitney(a, b, swap=True, alpha=0.05) -> dict:
    a, b = _clean(a), _clean(b)
    g1, g2 = (b, a) if swap else (a, b)
    n1, n2 = len(g1), len(g2)
    ranks = stats.rankdata(np.concatenate([g1, g2]))
    r1, r2 = float(ranks[:n1].sum()), float(ranks[n1:].sum())
    u1 = r1 - n1 * (n1 + 1) / 2
    u2 = r2 - n2 * (n2 + 1) / 2
    ties = len(np.unique(np.concatenate([g1, g2]))) < n1 + n2
    exact = _exact_rank_sum_p(ranks, n1, r1)
    _, tc = np.unique(np.concatenate([g1, g2]), return_counts=True)
    big_n = n1 + n2
    sigma = math.sqrt(n1 * n2 / 12 * ((big_n + 1) - float((tc ** 3 - tc).sum()) / (big_n * (big_n - 1))))
    approx = _normal_cc_p(u1, n1 * n2 / 2, sigma)
    p = exact
    hl = float(np.median(np.subtract.outer(g1, g2)))
    return {"mannWhitneyTestModel": {
        "status": "VALID",
        "mannWhitneyTest": {"status": "VALID", "tiesStatus": "WITH_TIES" if ties else "NO_TIES", "U": float(min(u1, u2)),
                            "sumRanks1": r1, "sumRanks2": r2, "meanRanks1": r1 / n1, "meanRanks2": r2 / n2,
                            "differenceOfRankMeans": r1 / n1 - r2 / n2, "pValue": _p(float(p), alpha),
                            "pValueExact": _p(float(exact), alpha), "pValueApproximate": _p(float(approx), alpha)},
        "differenceOfMedians": {"n1": n1, "median1": float(np.median(g1)), "n2": n2, "median2": float(np.median(g2)),
                                "actualDifference": float(np.median(g1) - np.median(g2)), "hodgesLehmannDifference": hl}}}


def wilcoxon(a, b, swap=True, alpha=0.05) -> dict:
    a, b = _pairs(a, b)
    d = (b - a) * _sign(swap)
    nz = d[d != 0]
    ranks = stats.rankdata(np.abs(nz))
    pos, neg = float(ranks[nz > 0].sum()), float(-ranks[nz < 0].sum())
    exact = _exact_signed_rank_p(ranks, pos)
    m = len(nz)
    _, tc = np.unique(np.abs(nz), return_counts=True)
    sigma = math.sqrt(m * (m + 1) * (2 * m + 1) / 24 - float((tc ** 3 - tc).sum()) / 48)
    approx = _normal_cc_p(pos, m * (m + 1) / 4, sigma)  # zeros dropped (Wilcoxon's method)
    return {"wilcoxonTestModel": {
        "status": "VALID",
        "wilcoxonTest": {"status": "VALID", "zeroesStatus": "WITH_ZEROES" if len(nz) < len(d) else "NO_ZEROES",
                         "signedRanksSum": pos + neg, "positiveRanksSum": pos, "negativeRanksSum": neg, "n": len(d),
                         "tieCount": int(len(d) - len(nz)),  # Prism: number of zero differences
                         "pValue": _p(float(exact), alpha),
                         "pValueExact": _p(float(exact), alpha), "pValueApproximate": _p(float(approx), alpha)},
        "medianOfDifferences": {"median": float(np.median(d))},
        "spearmanTest": spearman_pairing(a, b, alpha)}}


# Prism computes the exact K-S P when the number of group assignments
# C(n1+n2, n1) is at most 60,000 (oracle: exact at 59,640, approximate at 62,196).
KS_EXACT_MAX_COMBINATIONS = 60000


def kolmogorov_smirnov(a, b, alpha=0.05) -> dict:
    a, b = _clean(a), _clean(b)
    d = float(stats.ks_2samp(a, b).statistic)
    ne = len(a) * len(b) / (len(a) + len(b))
    approx = float(stats.kstwobign.sf(math.sqrt(ne) * d))  # Kolmogorov limit, no small-sample correction
    model = {"status": "VALID", "D": d, "pValueApproximate": _p(approx, alpha)}
    if math.comb(len(a) + len(b), len(a)) <= KS_EXACT_MAX_COMBINATIONS:
        exact = _ks_exact_conditional(a, b, d)
        model["pValueExact"] = _p(exact, alpha)
        model["pValue"] = _p(exact, alpha)
    else:
        model["pValue"] = _p(approx, alpha)
    return {"kolmogorovSmirnovTestModel": {"status": "VALID", "kolmogorovSmirnovTest": model}}


DESIGNS = {
    "UNPAIRED_T_TEST": lambda a, b, o: unpaired_t(a, b, o["swap"], o["alpha"], o["level"]),
    "WELCH_T_TEST": lambda a, b, o: unpaired_t(a, b, o["swap"], o["alpha"], o["level"], welch=True),
    "PAIRED_T_TEST": lambda a, b, o: paired_t(a, b, o["swap"], o["alpha"], o["level"]),
    "RATIO_PAIRED_T_TEST": lambda a, b, o: ratio_paired_t(a, b, o["swap"], o["alpha"], o["level"]),
    "MANN_WHITNEY_TEST": lambda a, b, o: mann_whitney(a, b, o["swap"], o["alpha"]),
    "WILCOXON_TEST": lambda a, b, o: wilcoxon(a, b, o["swap"], o["alpha"]),
    "KOLMOGOROV_SMIRNOV_TEST": lambda a, b, o: kolmogorov_smirnov(a, b, o["alpha"]),
}


def two_sample(design: str, a, b, swap=True, alpha=0.05, level=95.0) -> dict:
    return DESIGNS[design](a, b, {"swap": swap, "alpha": alpha, "level": level})
