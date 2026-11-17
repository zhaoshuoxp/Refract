"""Contingency tables (Prism: CONTINGENCY_TABLE): chi-square and Fisher's
exact test, relative risk, difference of proportions / NNT, odds ratio,
sensitivity / specificity / predictive values, with Prism's result keys.

Rows are groups, columns are outcomes; the 2 x 2 measures use the top-left
2 x 2 block (Prism does so for larger tables too).
"""

from __future__ import annotations

import math

import numpy as np
from scipy import optimize, stats


def _p(value: float, alpha: float) -> dict:
    return {"value": float(value), "level": alpha, "isSignificant": bool(value < alpha), "state": "P_VALUE_EQUAL"}


# ---------------------------------------------------------------- intervals
def wilson(x: int, n: int, z: float) -> tuple[float, float]:
    """Wilson score interval (Prism: CI_PROPORTION_METHOD_WILSON_BROWN)."""
    p = x / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return c - h, c + h


def wilson_brown(x: int, n: int, z: float, alpha: float) -> tuple[float, float]:
    """Prism's CI_PROPORTION_METHOD_WILSON_BROWN: the Wilson interval with
    Brown, Cai & DasGupta's (2001) Poisson limits near the ends: for
    1 <= x <= x* the lower limit is chi2(alpha; 2x) / 2n, for 1 <= n - x <= x*
    the upper limit is 1 - chi2(alpha; 2(n - x)) / 2n (one-sided alpha).
    x* = 2 below n = 50 and 3 from n = 50 (verified at n <= 27, 45 and 50, 55)."""
    lo, hi = wilson(x, n, z)
    xs = 3 if n >= 50 else 2
    if 1 <= x <= xs:
        lo = stats.chi2.ppf(alpha, 2 * x) / (2 * n)
    if 1 <= n - x <= xs:
        hi = 1 - stats.chi2.ppf(alpha, 2 * (n - x)) / (2 * n)
    return float(lo), float(hi)


def wilson_cc(x: int, n: int, z: float) -> tuple[float, float]:
    """Wilson interval with continuity correction (Newcombe 1998, method 4),
    without the x = 0 / x = n special cases or clipping to [0, 1], as Prism
    uses it inside the difference interval (verified)."""
    p = x / n
    q = 1 - p
    lo = (2 * n * p + z * z - 1 - z * math.sqrt(max(0.0, z * z - 2 - 1 / n + 4 * p * (n * q + 1)))) / (2 * (n + z * z))
    hi = (2 * n * p + z * z + 1 + z * math.sqrt(max(0.0, z * z + 2 - 1 / n + 4 * p * (n * q - 1)))) / (2 * (n + z * z))
    return lo, hi


def clopper_pearson(x: int, n: int, alpha: float) -> tuple[float, float]:
    """Exact (Clopper-Pearson) interval (Prism: CI_PROPORTION_METHOD_CLOPPER_PEARSON)."""
    lo = 0.0 if x == 0 else stats.beta.ppf(alpha / 2, x, n - x + 1)
    hi = 1.0 if x == n else stats.beta.ppf(1 - alpha / 2, x + 1, n - x)
    return float(lo), float(hi)


def proportion_ci(method: str, x: int, n: int, z: float, alpha: float) -> tuple[float, float]:
    if method == "CI_PROPORTION_METHOD_CLOPPER_PEARSON":
        return clopper_pearson(x, n, alpha)
    if method == "CI_PROPORTION_METHOD_WILSON":
        return wilson(x, n, z)
    return wilson_brown(x, n, z, alpha)


def newcombe_cc(x1, n1, x2, n2, z, cc: bool = True):
    """Prism's CI_PROPORTIONS_DIFFERENCE_METHOD_NEWCOMBE_WILSON_CC (cc=True)
    and _NEWCOMBE_WILSON (cc=False), verified: the Newcombe (1998, methods
    11 / 10) half-widths of p1 - p2, A below and B above, placed around
    |p1 - p2| without reorienting them when p1 < p2.
    Returns (|p1 - p2|, lower, upper); the upper limit may exceed 1."""
    p1, p2 = x1 / n1, x2 / n2
    f = wilson_cc if cc else wilson
    l1, u1 = f(x1, n1, z)
    l2, u2 = f(x2, n2, z)
    d = abs(p1 - p2)
    a = math.sqrt((p1 - l1) ** 2 + (u2 - p2) ** 2)
    b = math.sqrt((u1 - p1) ** 2 + (p2 - l2) ** 2)
    return d, d - a, d + b


def koopman(x1, n1, x2, n2, z):
    """Score interval for the ratio of proportions (Koopman 1984)."""
    crit = z * z
    rr = (x1 / n1) / (x2 / n2) if x2 else math.inf

    def chi(theta):
        a = theta * (n1 + n2)
        b = -(theta * (n1 + x2) + x1 + n2)
        c = x1 + x2
        disc = max(0.0, b * b - 4 * a * c)
        p2 = (-b - math.sqrt(disc)) / (2 * a)
        p1 = theta * p2
        s = 0.0
        for x, n, p in ((x1, n1, p1), (x2, n2, p2)):
            if 0 < p < 1:
                s += (x - n * p) ** 2 / (n * p * (1 - p))
        return s - crit

    def root(t0, t1):
        return math.exp(optimize.brentq(lambda t: chi(math.exp(t)), t0, t1, xtol=1e-15, rtol=1e-15, maxiter=500))

    mid = math.log(rr) if 0 < rr < math.inf else math.log((x1 + 0.5) / (n1 + 0.5) / ((x2 + 0.5) / (n2 + 0.5)))
    lo = root(mid - 30, mid) if x1 > 0 else 0.0
    hi = root(mid, mid + 30) if x2 > 0 else math.inf
    return lo, hi


def katz_log(x1, n1, x2, n2, z):
    """Katz log interval of the relative risk (Prism: CI_RELATIVE_RISK_METHOD_KATZ_LOG).
    A zero count is replaced by 0.5 (totals unchanged) in the ratio and its
    standard error, and that side of the interval becomes 0 / +inf
    (verified for x1 = 0). Returns (rr, lower, upper)."""
    y1, y2 = (x1 or 0.5), (x2 or 0.5)
    rr = (y1 / n1) / (y2 / n2)
    se = math.sqrt(1 / y1 - 1 / n1 + 1 / y2 - 1 / n2)
    lo, hi = rr * math.exp(-z * se), rr * math.exp(z * se)
    return rr, (0.0 if x1 == 0 else lo), (math.inf if x2 == 0 else hi)


def woolf_logit(a, b, c, d, z):
    """Woolf logit interval of the odds ratio (Prism: CI_ODDS_RATIO_METHOD_WOOLF_LOGIT).
    With a zero cell Prism switches to Gart's adjusted logit (0.5 added to
    every cell, ratio included) and names it GART_ADJUSTED_LOGIT (verified).
    Returns (method suffix, or, lower, upper)."""
    name = "WOOLF_LOGIT"
    if 0 in (a, b, c, d):
        a, b, c, d = a + 0.5, b + 0.5, c + 0.5, d + 0.5
        name = "GART_ADJUSTED_LOGIT"
    o = a * d / (b * c)
    se = math.sqrt(1 / a + 1 / b + 1 / c + 1 / d)
    return name, o, o * math.exp(-z * se), o * math.exp(z * se)


def asymptotic_difference(x1, n1, x2, n2, z):
    """Prism's CI_PROPORTIONS_DIFFERENCE_METHOD_ASYMPTOTIC: |p1 - p2| +- z
    times the pooled standard error sqrt(p(1 - p)(1/n1 + 1/n2)) (verified)."""
    d = abs(x1 / n1 - x2 / n2)
    p = (x1 + x2) / (n1 + n2)
    h = z * math.sqrt(p * (1 - p) * (1 / n1 + 1 / n2))
    return d, d - h, d + h


def _nchg_pmf(a_vals, m1, n1, m2, psi):
    """Fisher's noncentral hypergeometric pmf over the support a_vals."""
    from scipy.special import gammaln

    logc = (gammaln(m1 + 1) - gammaln(a_vals + 1) - gammaln(m1 - a_vals + 1)
            + gammaln(m2 + 1) - gammaln(n1 - a_vals + 1) - gammaln(m2 - n1 + a_vals + 1))
    lw = logc + a_vals * math.log(psi)
    lw -= lw.max()
    w = np.exp(lw)
    return w / w.sum()


def odds_ratio_exact(a, b, c, d, level):
    """Exact conditional CI of the odds ratio (Prism: Baptista & Pike 1977,
    acceptance by probability order)."""
    alpha = 1 - level / 100
    m1, m2, n1 = a + c, b + d, a + b  # column totals, first row total
    lo_a, hi_a = max(0, n1 - m2), min(n1, m1)
    av = np.arange(lo_a, hi_a + 1)

    def bp(psi):
        """Prism's Baptista-Pike acceptability: outcomes strictly less probable
        than the observed one, plus half the observed probability (verified)."""
        pmf = _nchg_pmf(av, m1, n1, m2, psi)
        pa = pmf[av == a][0]
        return pmf[pmf < pa * (1 - 1e-9)].sum() + 0.5 * pa

    # bp() is a sawtooth in psi (it jumps where the probability order
    # changes), so the acceptance set need not be an interval. Prism reports
    # the edges of the piece holding the estimate (verified): march out from
    # the estimate in small log(psi) steps to the first rejected point, then
    # bisect the crossing.
    mid = math.log((a + 0.5) * (d + 0.5) / ((b + 0.5) * (c + 0.5)))

    def edge(sign):
        step, t = 0.002, mid
        for _ in range(int(40 / step)):
            u = t + sign * step
            if bp(math.exp(u)) < alpha:
                return math.exp(optimize.brentq(lambda v: bp(math.exp(v)) - alpha, min(t, u), max(t, u),
                                                xtol=1e-15, rtol=1e-15, maxiter=2000))
            t = u
        return math.exp(t)

    lo = edge(-1) if a > lo_a else 0.0
    hi = edge(1) if a < hi_a else math.inf
    return lo, hi


def fisher_rxc(table) -> float:
    """Two-sided Fisher-Freeman-Halton exact P of an R x C table: the total
    probability of tables with the same margins that are no more probable
    than the observed one (relative tolerance 1e-7, as R's fisher.test).
    Network-style enumeration column by column; prefixes with the same
    remaining row totals and probability are merged, and a node is closed
    when bounds show that all, or none, of its completions count."""
    from scipy.special import gammaln

    t = np.asarray(table, dtype=np.int64)
    if t.shape[0] > t.shape[1]:
        t = t.T
    t = t[:, np.argsort(-t.sum(axis=0), kind="stable")]
    rows = tuple(int(v) for v in t.sum(axis=1))
    cols = [int(v) for v in t.sum(axis=0)]
    big_n = sum(cols)
    lf = gammaln(np.arange(big_n + 2) + 1.0)
    const = lf[list(rows)].sum() + lf[cols].sum() - lf[big_n]
    thr = const - lf[t.ravel()].sum() + math.log1p(1e-7)

    def vectors(caps, total):
        if len(caps) == 1:
            if total <= caps[0]:
                yield (total,)
            return
        rest = sum(caps[1:])
        for v in range(max(0, total - rest), min(caps[0], total) + 1):
            for tail in vectors(caps[1:], total - v):
                yield (v, *tail)

    def even(caps, total):  # max of -sum log x! with sum = total, x <= caps
        x = [0] * len(caps)
        order = sorted(range(len(caps)), key=lambda i: caps[i])
        left = total
        for k, i in enumerate(order):
            share = min(caps[i], left // (len(caps) - k) + (1 if left % (len(caps) - k) else 0))
            share = min(share, left)
            x[i] = share
            left -= share
        return -lf[x].sum()

    def lumped(caps, total):  # min of -sum log x!: fill the largest caps first
        x, left = [], total
        for cap in sorted(caps, reverse=True):
            v = min(cap, left)
            x.append(v)
            left -= v
        return -lf[x].sum()

    p = 0.0
    # remaining row totals -> {rounded sum of -log x!: [exact sum, number of prefixes]}
    stage = {rows: {0.0: [0.0, 1.0]}}
    for j in range(len(cols)):
        nxt: dict = {}
        later = cols[j:]
        for rem, accs in stage.items():
            n_left = sum(rem)
            mass = lf[n_left] - lf[list(rem)].sum() - lf[later].sum()  # log sum over completions
            ub = sum(even(rem, c) for c in later)
            lb = sum(lumped(rem, c) for c in later)
            open_accs = []
            for acc, mult in accs.values():
                if const + acc + ub <= thr:
                    p += mult * math.exp(const + acc + mass)
                elif const + acc + lb <= thr:
                    open_accs.append((acc, mult))
            if not open_accs:
                continue
            for x in vectors(rem, cols[j]):
                w = -lf[list(x)].sum()
                key = tuple(r - v for r, v in zip(rem, x, strict=True))
                bucket = nxt.setdefault(key, {})
                for acc, mult in open_accs:
                    k2 = round(acc + w, 9)
                    if k2 in bucket:
                        bucket[k2][1] += mult
                    else:
                        bucket[k2] = [acc + w, mult]
        stage = nxt
    for accs in stage.values():  # complete tables reached by enumeration
        for acc, mult in accs.values():
            if const + acc <= thr:
                p += mult * math.exp(const + acc)
    return min(1.0, p)


# --------------------------------------------------------------------- main
def _num(v: float):
    """Prism writes infinities as "+inf" / "-inf" and NaN as "undefined"."""
    v = float(v)
    if math.isnan(v):
        return "undefined"
    if math.isinf(v):
        return "+inf" if v > 0 else "-inf"
    return v


def _ci(lo, hi, level):
    return {"lower": _num(lo), "upper": _num(hi), "level": level}


def _div(x: float, y: float) -> float:
    if y == 0:
        return math.nan if x == 0 else math.copysign(math.inf, x)
    return x / y


def chi_square_warning(m: np.ndarray) -> bool:
    """Prism flags R x C chi-square (CHI_WARNING) when at least 20 % of the
    expected counts are below 5 or any is below 1 (verified; 2 x 2: never)."""
    if m.shape == (2, 2):
        return False
    e = stats.contingency.expected_freq(m)
    return bool((e < 5).mean() >= 0.2 or (e < 1).any())


def contingency(params: dict, table: list[list[float]]) -> dict:
    """table[r][c]: counts, rows = groups, columns = outcomes."""
    calc = params.get("calc", {})
    opt = params.get("options", {})
    alpha = opt.get("significanceLevel", 0.05)
    one_tailed = opt.get("pValueTailType", "P_VALUE_TWO_TAILED") == "P_VALUE_ONE_TAILED"
    level = 100 * (1 - alpha)
    z = stats.norm.ppf(1 - alpha / 2)
    m = np.array(table, float)
    nr, nc = m.shape
    out: dict = {"status": {"error": "VALID", "warning": []}}
    method = calc.get("method", "FISHER_EXACT_TEST")
    if method == "FISHER_EXACT_TEST":
        if m.shape == (2, 2):
            # one-tailed: the smaller one-sided P (verified)
            p = (min(stats.fisher_exact(m, "less")[1], stats.fisher_exact(m, "greater")[1]) if one_tailed
                 else stats.fisher_exact(m)[1])
        else:
            p = fisher_rxc(m)  # R x C: two-sided regardless of the tail option (verified)
        out["fisherExactTest"] = {"status": "VALID", "pValue": _p(p, alpha)}
    else:
        chi, p, df, _ = stats.chi2_contingency(m, correction=False)
        t = {"status": "CHI_WARNING" if chi_square_warning(m) else "VALID", "chiSquared": float(chi), "df": float(df)}
        if m.shape == (2, 2):
            t["z"] = math.sqrt(chi)
            if one_tailed:
                p = p / 2
        t["pValue"] = _p(p, alpha)
        out["chiSquareTest"] = t
    a, b, c, d = (int(v) for v in (m[0, 0], m[0, 1], m[1, 0], m[1, 1]))
    n1, n2 = a + b, c + d
    if calc.get("relativeRisk", {}).get("calculate"):
        rr = _div(a / n1, c / n2)
        rm = calc["relativeRisk"].get("ciMethod", "CI_RELATIVE_RISK_METHOD_KOOPMAN")
        if rm == "CI_RELATIVE_RISK_METHOD_KATZ_LOG":
            rr, lo, hi = katz_log(a, n1, c, n2, z)
        else:
            lo, hi = koopman(a, n1, c, n2, z)
        out["relativeRiskModel"] = {"ciMethod": rm,
                                    "relativeRisk": {"value": _num(rr), "ci": _ci(lo, hi, level)},
                                    "relativeRiskReciprocal": {"value": _num(_div(1, rr)),
                                                               "ci": _ci(_div(1, hi), _div(1, lo), level)}}
    if calc.get("differenceBetweenProportions", {}).get("calculate"):
        dm = calc["differenceBetweenProportions"].get("ciMethod", "CI_PROPORTIONS_DIFFERENCE_METHOD_NEWCOMBE_WILSON_CC")
        if dm == "CI_PROPORTIONS_DIFFERENCE_METHOD_ASYMPTOTIC":
            ar, lo, hi = asymptotic_difference(a, n1, c, n2, z)
        else:
            ar, lo, hi = newcombe_cc(a, n1, c, n2, z, cc=dm != "CI_PROPORTIONS_DIFFERENCE_METHOD_NEWCOMBE_WILSON")
        nnt = _ci(1 / hi, 1 / lo, level) if lo > 0 else {"lower": "undefined", "upper": "undefined", "level": level}
        out["proportionsDifferenceModel"] = {
            "ciMethod": dm,
            "attributableRisk": {"value": ar, "ci": _ci(lo, hi, level)},
            "nnt": {"value": _num(_div(1, ar)), "ci": nnt}}
    if calc.get("oddsRatio", {}).get("calculate"):
        orv = _div(a * d, b * c)
        # results name the method CI_PROPORTIONS_RATIO_METHOD_* (verified)
        if calc["oddsRatio"].get("ciMethod") == "CI_ODDS_RATIO_METHOD_WOOLF_LOGIT":
            suffix, orv, lo, hi = woolf_logit(a, b, c, d, z)
        else:
            suffix = "BAPTISTA_PIKE"
            lo, hi = odds_ratio_exact(a, b, c, d, level)
        out["oddsRatioModel"] = {"ciMethod": "CI_PROPORTIONS_RATIO_METHOD_" + suffix,
                                 "oddsRatio": {"value": _num(orv), "ci": _ci(lo, hi, level)},
                                 "oddsRatioReciprocal": {"value": _num(_div(1, orv)), "ci": _ci(_div(1, hi), _div(1, lo), level)}}
    if calc.get("proportions", {}).get("calculate"):
        pm = calc["proportions"].get("ciMethod", "CI_PROPORTION_METHOD_WILSON_BROWN")

        def prop(x, n):
            lo, hi = proportion_ci(pm, x, n, z, alpha)
            return {"value": x / n, "ci": _ci(lo, hi, level)}

        sens, spec = prop(a, a + c), prop(d, b + d)
        out["proportionsModel"] = {"ciMethod": pm,
                                   "sensitivity": sens, "specificity": spec,
                                   "positivePredictiveValue": prop(a, a + b), "negativePredictiveValue": prop(d, c + d),
                                   "likelihoodRatio": "undefined" if spec["value"] == 1 else sens["value"] / (1 - spec["value"])}
    out["dataSummary"] = {"rowCount": float(nr), "colCount": float(nc)}
    return out
