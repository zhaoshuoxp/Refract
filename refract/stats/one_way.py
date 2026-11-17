"""One-way ANOVA family (Prism: ONE_WAY_ANOVA), with Prism's result keys.

experimentalDesign: ORDINARY_ANOVA, BROWN_FORSYTHE_ANOVA (Brown-Forsythe and
Welch), KRUSKAL_WALLIS_TEST, REPEATED_MEASURES_ANOVA (GLM, Geisser-Greenhouse),
FRIEDMAN_TEST. Groups are lists of values (None/NaN = missing). Repeated
measures designs take the groups as columns of a subjects x levels table.
"""

from __future__ import annotations

import itertools
import math

import numpy as np
from scipy import stats


def _p(value: float, alpha: float) -> dict:
    return {"value": float(value), "level": alpha, "isSignificant": bool(value < alpha), "state": "P_VALUE_EQUAL"}


def clean_groups(groups) -> list[np.ndarray]:
    return [np.asarray([v for v in g if v is not None and math.isfinite(v)], dtype=float) for g in groups]


def complete_rows(groups) -> np.ndarray:
    """Subjects x levels matrix of the rows with no missing value."""
    n = max(len(g) for g in groups)
    rows = []
    for r in range(n):
        vals = [g[r] if r < len(g) else None for g in groups]
        if all(v is not None and math.isfinite(v) for v in vals):
            rows.append(vals)
    return np.asarray(rows, dtype=float)


# ------------------------------------------------------------------ ordinary
def ordinary(groups, alpha: float = 0.05) -> dict:
    g = clean_groups(groups)
    allv = np.concatenate(g)
    k, n = len(g), len(allv)
    gm = allv.mean()
    ss_b = float(sum(len(x) * (x.mean() - gm) ** 2 for x in g))
    ss_w = float(sum(((x - x.mean()) ** 2).sum() for x in g))
    ss_t = float(((allv - gm) ** 2).sum())
    df_b, df_w = k - 1, n - k
    ms_b, ms_w = ss_b / df_b, ss_w / df_w
    f = ms_b / ms_w
    # Brown-Forsythe (median-centred Levene) and Bartlett tests for equal SDs
    bf = stats.levene(*g, center="median")
    bt = stats.bartlett(*g)
    return {"ordinaryAnovaModel": {
        "status": "VALID",
        "anovaTable": {
            "colFactor": {"ss": ss_b, "df": float(df_b), "ms": ms_b, "r2": ss_b / ss_t,
                          "fTest": {"status": "VALID", "f": f, "dfNumerator": float(df_b), "dfDenominator": float(df_w),
                                    "pValue": _p(stats.f.sf(f, df_b, df_w), alpha)}},
            "residual": {"ss": ss_w, "df": float(df_w), "ms": ms_w},
            "total": {"ss": ss_t, "df": float(n - 1)}},
        "brownForsytheTest": {"status": "VALID", "f": float(bf.statistic), "dfNumerator": float(df_b),
                              "dfDenominator": float(df_w), "pValue": _p(bf.pvalue, alpha)},
        # Prism reports Bartlett only when every group has at least 4 values
        "bartlettTest": ({"status": "VALID", "statistic": float(bt.statistic), "pValue": _p(bt.pvalue, alpha)}
                         if min(len(x) for x in g) >= 4 else {"status": "TOO_FEW_POINTS"}),
        "dataSummary": {"levelCount": k, "pointCount": n}}}


def brown_forsythe_welch(groups, alpha: float = 0.05) -> dict:
    g = clean_groups(groups)
    k = len(g)
    n = np.array([len(x) for x in g], float)
    m = np.array([x.mean() for x in g])
    v = np.array([x.var(ddof=1) for x in g])
    big_n = n.sum()
    gm = (n * m).sum() / big_n
    # Brown-Forsythe F* (Brown & Forsythe 1974)
    num = (n * (m - gm) ** 2).sum()
    den = ((1 - n / big_n) * v).sum()
    f_bf = num / den
    c = (1 - n / big_n) * v / den
    df2_bf = 1 / (c ** 2 / (n - 1)).sum()
    # Welch W
    w = n / v
    mw = (w * m).sum() / w.sum()
    lam = ((1 - w / w.sum()) ** 2 / (n - 1)).sum()
    w_stat = ((w * (m - mw) ** 2).sum() / (k - 1)) / (1 + 2 * (k - 2) / (k * k - 1) * lam)
    df2_w = (k * k - 1) / (3 * lam)
    return {"brownForsytheAnovaModel": {
        "status": "VALID",
        "anovaBrownForsytheTest": {"status": "VALID", "F": float(f_bf), "dfNumerator": float(k - 1), "dfDenominator": float(df2_bf),
                                   "pValue": _p(stats.f.sf(f_bf, k - 1, df2_bf), alpha)},
        "anovaWelchTest": {"status": "VALID", "W": float(w_stat), "dfNumerator": float(k - 1), "dfDenominator": float(df2_w),
                           "pValue": _p(stats.f.sf(w_stat, k - 1, df2_w), alpha)},
        "dataSummary": {"levelCount": k, "pointCount": int(big_n)}}}


# ------------------------------------------------------------- nonparametric
# Prism reports an exact P (and uses it as pValue) when the number of
# equally likely rank arrangements is small enough (ties allowed: the exact
# distribution is conditional on the observed midranks). Probed in Prism 11
# (docs/experiments.md): Kruskal-Wallis exact at 1.63e9 partitions, not at
# 2.02e9; Friedman exact at (k!)^n = 3.7e8, not at 1.63e9.
KW_EXACT_LIMIT = 2e9
FRIEDMAN_EXACT_LIMIT = 1e9


def _kw_partitions(ns) -> int:
    return math.factorial(sum(ns)) // math.prod(math.factorial(n) for n in ns)


def kw_exact_p(g: list[np.ndarray]) -> float:
    """Exact permutation P of the Kruskal-Wallis statistic: P(sum R_i^2/n_i >=
    observed) over all partitions of the pooled (mid)ranks into groups of the
    observed sizes.

    Vectorised DP over the ranks. A state holds (count, doubled rank sum) for
    every group but the largest, whose values are implied; states are packed
    into one int64 (mixed radix). Groups of equal size are exchangeable, so
    their digits are kept sorted and a state carries the count of its orbit."""
    allv = np.concatenate(g)
    r2 = np.rint(2 * stats.rankdata(allv)).astype(np.int64)  # doubled midranks
    ns = [len(x) for x in g]
    lcm = math.lcm(*ns)
    off = np.cumsum([0] + ns)
    observed = sum(int(r2[off[i]:off[i + 1]].sum()) ** 2 * (lcm // ns[i]) for i in range(len(ns)))
    sizes = sorted(ns)
    n_last, ex = sizes[-1], sizes[:-1]
    m = len(ex)
    desc = np.sort(r2)[::-1]
    rs = [int(desc[:n].sum()) + 1 for n in ex]                # sum radix per group
    rad = [(n + 1) * q for n, q in zip(ex, rs, strict=True)]  # digit radix
    place = [1]
    for q in rad[:-1]:
        place.append(place[-1] * q)
    if place[-1] * rad[-1] >= 2 ** 62:
        raise OverflowError("state space too large to pack")
    place_a, rad_a = np.array(place, dtype=np.int64), np.array(rad, dtype=np.int64)
    blocks = []
    i = 0
    while i < m:
        j = i
        while j < m and ex[j] == ex[i]:
            j += 1
        if j - i > 1:
            blocks.append((i, j))
        i = j
    codes = np.zeros(1, np.int64)
    cnt = np.ones(1)
    for step, r in enumerate(np.sort(r2).tolist()):
        digits = (codes[:, None] // place_a) % rad_a
        c = digits // np.array(rs, dtype=np.int64)
        parts_c, parts_n = [], []
        keep = (step - c.sum(axis=1)) < n_last  # rank goes to the implied group
        parts_c.append(codes[keep])
        parts_n.append(cnt[keep])
        for i in range(m):
            ok = c[:, i] < ex[i]
            parts_c.append(codes[ok] + (rs[i] + r) * place[i])
            parts_n.append(cnt[ok])
        codes = np.concatenate(parts_c)
        cnt = np.concatenate(parts_n)
        if blocks:
            d = (codes[:, None] // place_a) % rad_a
            for a, b in blocks:
                d[:, a:b] = np.sort(d[:, a:b], axis=1)
            codes = d @ place_a
        codes, inv = np.unique(codes, return_inverse=True)
        cnt = np.bincount(inv, weights=cnt)
    digits = (codes[:, None] // place_a) % rad_a
    sums = digits % np.array(rs, dtype=np.int64)
    last = int(r2.sum()) - sums.sum(axis=1)
    stat = (sums ** 2 * np.array([lcm // n for n in ex], dtype=np.int64)).sum(axis=1) + last ** 2 * (lcm // n_last)
    return float(cnt[stat >= observed].sum() / cnt.sum())


def kruskal_wallis(groups, alpha: float = 0.05) -> dict:
    g = clean_groups(groups)
    h, p = stats.kruskal(*g)
    t = {"status": "VALID", "statistic": float(h), "levelCount": len(g), "pValue": _p(p, alpha)}
    if _kw_partitions([len(x) for x in g]) <= KW_EXACT_LIMIT:
        exact = kw_exact_p(g)
        t["pValue"] = _p(exact, alpha)
        t["pValueExact"] = _p(exact, alpha)
    else:
        t["pValueExact"] = {"value": "undefined", "level": alpha, "isSignificant": False, "state": "P_VALUE_EQUAL"}
    t["pValueApproximate"] = _p(p, alpha)
    return {"kruskalWallisTestModel": {
        "status": "VALID", "kruskalWallisTest": t,
        "dataSummary": {"levelCount": len(g), "pointCount": int(sum(len(x) for x in g))}}}


def friedman_exact_p(x: np.ndarray) -> float:
    """Exact P(sum_j R_j^2 >= observed) when each row's (mid)ranks are
    arranged uniformly over their distinct orderings. Columns are
    exchangeable, so rank-sum vectors are kept sorted (orbit totals)."""
    r2 = np.rint(2 * np.apply_along_axis(stats.rankdata, 1, x)).astype(np.int64)
    observed = int((r2.sum(axis=0) ** 2).sum())
    k = x.shape[1]
    dist: dict[tuple, int] = {tuple([0] * k): 1}
    total = 1
    for row in r2.tolist():
        arrs = set(itertools.permutations(row))
        total *= len(arrs)
        nxt: dict[tuple, int] = {}
        for st, c in dist.items():
            for a in arrs:
                key = tuple(sorted(u + v for u, v in zip(st, a, strict=True)))
                nxt[key] = nxt.get(key, 0) + c
        dist = nxt
    hit = sum(c for st, c in dist.items() if sum(v * v for v in st) >= observed)
    return hit / total


def friedman(groups, alpha: float = 0.05) -> dict:
    x = complete_rows(groups)
    n, k = x.shape
    q, p = stats.friedmanchisquare(*x.T)
    model = {"status": "VALID", "statistic": float(q), "levelCount": k, "pValue": _p(p, alpha)}
    if math.factorial(k) ** n <= FRIEDMAN_EXACT_LIMIT:
        exact = friedman_exact_p(x)
        model["pValue"] = _p(exact, alpha)
        model["pValueExact"] = _p(exact, alpha)
    else:
        model["pValueExact"] = {"value": "undefined", "level": alpha, "isSignificant": False, "state": "P_VALUE_EQUAL"}
    model["pValueApproximate"] = _p(p, alpha)
    return {"friedmanTestModel": {"status": "VALID", "friedmanTest": model,
                                  "dataSummary": {"levelCount": k, "matchedCount": n}}}


# ---------------------------------------------------------- repeated measures
def gg_epsilon(x: np.ndarray) -> float:
    """Greenhouse-Geisser epsilon from the double-centred covariance matrix."""
    k = x.shape[1]
    s = np.cov(x, rowvar=False)
    c = np.eye(k) - np.ones((k, k)) / k
    sc = c @ s @ c
    return float(np.trace(sc) ** 2 / ((k - 1) * np.sum(sc * sc)))


def repeated_measures(groups, alpha: float = 0.05, assume_sphericity: bool = False) -> dict:
    x = complete_rows(groups)
    n, k = x.shape
    gm = x.mean()
    ss_t = float(((x - gm) ** 2).sum())
    ss_c = float(n * ((x.mean(axis=0) - gm) ** 2).sum())
    ss_s = float(k * ((x.mean(axis=1) - gm) ** 2).sum())
    ss_e = ss_t - ss_c - ss_s
    df_c, df_s, df_e = k - 1, n - 1, (k - 1) * (n - 1)
    ms_c, ms_s, ms_e = ss_c / df_c, ss_s / df_s, ss_e / df_e
    f = ms_c / ms_e
    eps = gg_epsilon(x)
    d1, d2 = (df_c, df_e) if assume_sphericity else (eps * df_c, eps * df_e)
    f_s = ms_s / ms_e
    matching = {"status": "VALID", "f": f_s, "dfNumerator": float(df_s), "dfDenominator": float(df_e),
                "pValue": _p(stats.f.sf(f_s, df_s, df_e), alpha)}
    col = {"ss": ss_c, "df": float(df_c), "ms": ms_c, "r2": ss_c / (ss_c + ss_e),
           "fTest": {"status": "VALID", "f": f, "dfNumerator": float(d1), "dfDenominator": float(d2),
                     "pValue": _p(stats.f.sf(f, d1, d2), alpha)}}
    if not assume_sphericity:
        col["ggEpsilon"] = eps
    return {"repeatedMeasuresGlmAnovaModel": {
        "status": "VALID",
        "anovaTable": {"colFactor": col,
                       "matchedFactor": {"ss": ss_s, "df": float(df_s), "ms": ms_s, "r2": ss_s / ss_t, "fTest": matching},
                       "residual": {"ss": ss_e, "df": float(df_e), "ms": ms_e},
                       "total": {"ss": ss_t, "df": float(n * k - 1)}},
        "matchingTest": matching,
        "dataSummary": {"levelCount": k, "matchedCount": n, "missingCount": int(max(len(g) for g in groups) - n)}}}
