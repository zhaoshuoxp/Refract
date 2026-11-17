"""Multiple two-sample tests, one per row (Prism: MULTIPLE_TWO_SAMPLE_TESTS).

Input: a grouped table with two data sets; each row is one test of the row's
replicates in data set A against data set B. Result keys, validity rules,
thresholds and quirks follow Prism 11.1 (verified, tools/multi_t_parity.py;
docs/format/findings.md).
"""

from __future__ import annotations

import math
from fractions import Fraction

import numpy as np
from scipy import stats

from .multiple_comparisons import _bky_qvalues, _holm_sidak

U = "undefined"


def _clean(v) -> np.ndarray:
    return np.asarray([x for x in v if x is not None and math.isfinite(x)], dtype=float)


def _pairs(a, b):
    pr = [(x, y) for x, y in zip(a, b, strict=False)
          if x is not None and y is not None and math.isfinite(x) and math.isfinite(y)]
    return np.array([p[0] for p in pr], float), np.array([p[1] for p in pr], float)


# --------------------------------------------------------------- per-row tests
# Each returns {"key", "test", "status", "p" (None when not computed),
# "fields" (inside the test block, before pValue), "extra" (block after it)}.
def _t_unpaired(a, b, sign: int, welch: bool) -> dict:
    a, b = _clean(a), _clean(b)
    if sign < 0:
        a, b = b, a  # Prism reports the swapped order: mean1 = data set B
    n1, n2 = len(a), len(b)
    key = "unpairedUnequalSDTTestModel" if welch else "unpairedEqualSDTTestModel"
    m1 = float(a.mean()) if n1 else U
    m2 = float(b.mean()) if n2 else U
    diff = float(a.mean() - b.mean()) if n1 and n2 else U
    ok = (n1 >= 2 and n2 >= 2) if welch else (n1 >= 1 and n2 >= 1 and n1 + n2 >= 3)
    if not ok:
        return {"key": key, "test": "unpairedTTest", "status": "TOO_FEW_POINTS", "p": None,
                "fields": {"t": U, "df": U},
                "extra": ("differenceOfMeans", {"n1": n1, "mean1": m1, "n2": n2, "mean2": m2, "difference": diff,
                                                "stdErrorOfDifference": U})}
    if welch:
        va, vb = a.var(ddof=1) / n1, b.var(ddof=1) / n2
        se = math.sqrt(va + vb)
        df = (va + vb) ** 2 / (va ** 2 / (n1 - 1) + vb ** 2 / (n2 - 1))
    else:
        df = n1 + n2 - 2
        se = math.sqrt((((a - a.mean()) ** 2).sum() + ((b - b.mean()) ** 2).sum()) / df * (1 / n1 + 1 / n2))
    t = abs(diff) / se
    return {"key": key, "test": "unpairedTTest", "status": "VALID", "p": float(2 * stats.t.sf(t, df)),
            "fields": {"t": t, "df": float(df)},
            "extra": ("differenceOfMeans", {"n1": n1, "mean1": m1, "n2": n2, "mean2": m2, "difference": diff,
                                            "stdErrorOfDifference": se})}


def unpaired_equal_sd(a, b, sign):
    return _t_unpaired(a, b, sign, welch=False)


def unpaired_unequal_sd(a, b, sign):
    return _t_unpaired(a, b, sign, welch=True)


def paired(a, b, sign: int) -> dict:
    x, y = _pairs(a, b)
    if sign < 0:
        x, y = y, x
    d = x - y
    n = len(d)
    mean1, mean2 = (float(x.mean()), float(y.mean())) if n else (U, U)
    if n < 2:
        return {"key": "pairedTTestModel", "test": "pairedTTest", "status": "TOO_FEW_POINTS", "p": None,
                "fields": {"t": U, "df": float(n - 2)},
                "extra": ("meanOfDifferences", {"mean1": mean1, "mean2": mean2,
                                                "meanOfDifferences": float(d.mean()) if n else U, "stdErrorOfDifferences": U})}
    se = float(d.std(ddof=1) / math.sqrt(n))
    t = abs(d.mean()) / se
    return {"key": "pairedTTestModel", "test": "pairedTTest", "status": "VALID", "p": float(2 * stats.t.sf(t, n - 1)),
            "fields": {"t": t, "df": float(n - 1)},
            "extra": ("meanOfDifferences", {"mean1": mean1, "mean2": mean2, "meanOfDifferences": float(d.mean()),
                                            "stdErrorOfDifferences": se})}


def ratio_paired(a, b, sign: int) -> dict:
    x, y = _pairs(a, b)
    keep = (x > 0) & (y > 0)
    x, y = x[keep], y[keep]
    if sign < 0:
        x, y = y, x
    lx, ly = np.log10(x), np.log10(y)
    d = lx - ly
    n = len(d)
    base = {"meanOfLog1": float(lx.mean()) if n else U, "meanOfLog2": float(ly.mean()) if n else U,
            "geometricMeanOfRatios": float(10 ** d.mean()) if n else U}
    if n < 2:
        return {"key": "ratioPairedTTestModel", "test": "ratioPairedTTest", "status": "TOO_FEW_POINTS", "p": None,
                "fields": {"t": U, "df": float(n - 2)}, "extra": ("ratioOfPairs", {**base, "stdErrorOfLogRatios": U})}
    se = float(d.std(ddof=1) / math.sqrt(n))
    t = abs(d.mean()) / se
    return {"key": "ratioPairedTTestModel", "test": "ratioPairedTTest", "status": "VALID",
            "p": float(2 * stats.t.sf(t, n - 1)), "fields": {"t": t, "df": float(n - 1)},
            "extra": ("ratioOfPairs", {**base, "stdErrorOfLogRatios": se})}


def mann_whitney(a, b, sign: int) -> dict:
    from . import two_sample as T2

    a, b = _clean(a), _clean(b)
    g1, g2 = (b, a) if sign < 0 else (a, b)
    n1, n2 = len(g1), len(g2)
    r = stats.rankdata(np.concatenate([g1, g2]))
    s1, s2 = float(r[:n1].sum()), float(r[n1:].sum())
    m1 = s1 / n1 if n1 else U
    m2 = s2 / n2 if n2 else U
    ranks = {"sumRanks1": s1, "sumRanks2": s2, "meanRanks1": m1, "meanRanks2": m2,
             "differenceOfRankMeans": float(m1 - m2) if n1 and n2 else U}
    if n1 < 2 or n2 < 2:
        return {"key": "mannWhitneyTestModel", "test": "mannWhitneyTest", "status": "TOO_FEW_POINTS", "p": None,
                "fields": {"U": U, **ranks}}
    m = T2.mann_whitney(list(g1), list(g2), swap=False)["mannWhitneyTestModel"]["mannWhitneyTest"]
    equal = len(np.unique(g1)) == 1 or len(np.unique(g2)) == 1
    # the exact P is a count over C(n1+n2, n1) assignments: snap it to that
    # fraction so equal P values are bit-identical (Prism ranks by exact value)
    total = math.comb(n1 + n2, n1)
    p = float(Fraction(m["pValue"]["value"]).limit_denominator(total))
    return {"key": "mannWhitneyTestModel", "test": "mannWhitneyTest", "status": "EQUAL_VALUES" if equal else "VALID",
            "p": p, "fields": {"U": m["U"], **ranks}}


def wilcoxon(a, b, sign: int) -> dict:
    from . import two_sample as T2

    x, y = _pairs(a, b)
    d = (y - x) if sign < 0 else (x - y)
    if len(d) < 3:
        return {"key": "wilcoxonTestModel", "test": "wilcoxonTest", "status": "TOO_FEW_POINTS", "p": None,
                "fields": {"signedRanksSum": U, "positiveRanksSum": U, "negativeRanksSum": U, "n": len(d),
                           "tieCount": 0}}  # Prism reports 0 here
    m = T2.wilcoxon(list(x), list(y), swap=sign < 0)["wilcoxonTestModel"]["wilcoxonTest"]
    p = float(Fraction(m["pValue"]["value"]).limit_denominator(2 ** int((d != 0).sum())))  # exact: count / 2^n
    return {"key": "wilcoxonTestModel", "test": "wilcoxonTest", "status": "VALID", "p": p,
            "fields": {k: m[k] for k in ("signedRanksSum", "positiveRanksSum", "negativeRanksSum", "n", "tieCount")}}


def kolmogorov_smirnov(a, b, sign: int) -> dict:
    from .two_sample import kolmogorov_smirnov as ks

    a, b = _clean(a), _clean(b)
    if len(a) < 2 or len(b) < 2:
        return {"key": "kolmogorovSmirnovTestModel", "test": "kolmogorovSmirnovTest", "status": "TOO_FEW_POINTS",
                "p": None, "fields": {"D": U}}
    m = ks(a, b)["kolmogorovSmirnovTestModel"]["kolmogorovSmirnovTest"]
    return {"key": "kolmogorovSmirnovTestModel", "test": "kolmogorovSmirnovTest", "status": "VALID",
            "p": float(m["pValue"]["value"]), "fields": {"D": float(m["D"])}}


TESTS = {
    "MULTIPLE_UNPAIRED_TWO_SAMPLE_EQUAL_SD_TESTS": unpaired_equal_sd,
    "MULTIPLE_UNPAIRED_TWO_SAMPLE_UNEQUAL_SD_TESTS": unpaired_unequal_sd,
    "MULTIPLE_PAIRED_TWO_SAMPLE_TESTS": paired,
    "MULTIPLE_RATIO_PAIRED_TWO_SAMPLE_TESTS": ratio_paired,
    "MULTIPLE_MANN_WHITNEY_TESTS": mann_whitney,
    "MULTIPLE_WILCOXON_TESTS": wilcoxon,
    "MULTIPLE_KOLMOGOROV_SMIRNOV_TESTS": kolmogorov_smirnov,
}


# ----------------------------------------------------------------- corrections
def _bh(ps: list[float], c: float = 1.0) -> list[float]:
    m = len(ps)
    order = sorted(range(m), key=lambda i: ps[i])
    qs = [0.0] * m
    running = 1.0
    for k in range(m - 1, -1, -1):
        i = order[k]
        running = min(running, ps[i] * m * c / (k + 1))
        qs[i] = running
    return qs


def correct(ps: list[float], mc: dict) -> dict:
    """-> {name, adjusted | q, alpha (level of adjusted/q), threshold (raw-P
    cutoff or "undefined"), fdr (bool)} with Prism's names and thresholds."""
    m = len(ps)
    srt = sorted(ps)
    mtype = mc.get("type", "NO_CORRECTION")
    if mtype == "NO_CORRECTION":
        a = mc.get("noCorrection", {}).get("options", {}).get("significanceLevel", 0.05)
        return {"name": "No correction", "alpha": a, "threshold": a if m else U, "fdr": False}
    if mtype == "STATISTICAL":
        st = mc.get("statistical", {})
        a = st.get("options", {}).get("significanceLevel", 0.05)
        test = st.get("test", "HOLM_SIDAK")
        if test == "BONFERRONI_DUNN":
            return {"name": "Bonferroni-Dunn", "adjusted": [min(1.0, p * m) for p in ps], "alpha": a,
                    "threshold": a / m if m else U, "fdr": False}
        if test == "BONFERRONI_SIDAK":
            return {"name": "Bonferroni-Šídák", "adjusted": [min(1.0, 1 - (1 - p) ** m) for p in ps], "alpha": a,
                    "threshold": 1 - (1 - a) ** (1 / m) if m else U, "fdr": False}
        if test == "HOLM_SIDAK":
            adj = _holm_sidak(ps)
            k = sum(1 for v in adj if v < a)
            thr = 1 - (1 - a) ** (1 / (m - k + 1)) if k else U  # critical value of the last rejected step
            return {"name": "Holm-Šídák", "adjusted": adj, "alpha": a, "threshold": thr, "fdr": False}
        raise NotImplementedError(f"multiple t tests correction {test}")
    if mtype == "FDR":
        f = mc.get("fdr", {})
        q = f.get("options", {}).get("discoveryLevel", 1.0) / 100  # stored in percent
        test = f.get("test", "BENJAMINI_KRIEGER_YEKUTIELI")
        if test == "BENJAMINI_KRIEGER_YEKUTIELI":
            qs = _bky_qvalues(ps, q)
            k = sum(1 for v in qs if v <= q)
            q1 = q / (1 + q)
            r1 = max((i + 1 for i in range(m) if srt[i] <= (i + 1) * q1 / m), default=0)
            m0 = (m - r1) or m
            thr = k * q1 / m0 if k else U
            name = "Two-stage step-up FDR method (Benjamini, Krieger, and Yekutieli)"
        elif test == "BENJAMINI_HOCHBERG":
            qs = _bh(ps)
            k = sum(1 for v in qs if v <= q)
            thr = k * q / m if k else U
            name = "Original FDR method (Benjamini and Hochberg)"
        elif test == "BENJAMINI_YEKUTIELI":
            c = sum(1 / i for i in range(1, m + 1))
            qs = _bh(ps, c)
            k = sum(1 for v in qs if v <= q)
            thr = k * q / (m * c) if k else U
            name = "Corrected FRD method (Benjamini and Yekutieli)"  # sic, as Prism 11.1
        else:
            raise NotImplementedError(f"multiple t tests FDR {test}")
        return {"name": name, "q": qs, "alpha": q, "threshold": thr, "fdr": True}
    raise NotImplementedError(mtype)


def multiple_t(params: dict, set_a: list[list], set_b: list[list], row_titles: list[str]) -> dict:
    """set_a / set_b: the two data sets as [subcolumn][row] values."""
    test = params.get("test", "MULTIPLE_UNPAIRED_TWO_SAMPLE_EQUAL_SD_TESTS")
    if test not in TESTS:
        raise NotImplementedError(f"multiple two-sample test {test}")
    sign = -1 if params.get("options", {}).get("swapDirection", False) else 1
    nrows = max([len(s) for s in set_a + set_b] or [0])

    def row(sets, r):
        return [s[r] if r < len(s) else None for s in sets]

    per_row = {}
    for r in range(nrows):
        a, b = row(set_a, r), row(set_b, r)
        if not any(v is not None for v in a + b):
            continue  # empty rows are not reported
        per_row[r] = TESTS[test](a, b, sign)
    valid = [r for r, v in per_row.items() if v["p"] is not None]
    ps = [per_row[r]["p"] for r in valid]
    cor = correct(ps, params.get("multipleComparisons", {}))
    thr = cor["threshold"]
    # 0 = smallest P (exact float comparison, as Prism); equal P keep table order
    order = sorted(range(len(ps)), key=lambda i: ps[i])
    rank = {valid[i]: k for k, i in enumerate(order)}
    pos = {r: i for i, r in enumerate(valid)}
    rows, sig = {}, 0
    for r, v in per_row.items():
        block = {"status": v["status"], **v["fields"]}
        model = {"status": "VALID", v["test"]: block}
        side = {}  # adjusted P / q value sit beside the model, in the row value
        if v["p"] is not None:
            i = pos[r]
            p_sig = isinstance(thr, float) and v["p"] <= thr
            block["pValue"] = {"value": float(v["p"]), "level": thr, "isSignificant": bool(p_sig), "rank": rank[r],
                               "state": "P_VALUE_EQUAL"}
            if "adjusted" in cor:
                a = cor["adjusted"][i]
                side["pValueAdjusted"] = {"value": float(a), "level": cor["alpha"], "isSignificant": bool(a < cor["alpha"]),
                                           "state": "P_VALUE_EQUAL"}
                sig += a < cor["alpha"]
            elif "q" in cor:
                q = cor["q"][i]
                side["qValue"] = {"value": float(q), "level": cor["alpha"], "isDiscovery": bool(q <= cor["alpha"])}
                sig += q <= cor["alpha"]
            else:
                sig += bool(p_sig)
        if "extra" in v:
            model[v["extra"][0]] = v["extra"][1]
        rows[f"row{r}"] = {"id": {"row": {"idx": r, "title": row_titles[r] if r < len(row_titles) else ""}},
                           "value": {v["key"]: model, **side}}
    count_key = "discoveryCount" if cor["fdr"] else "significantCount"
    return {"status": {"error": "VALID", "warning": []},
            "summary": {"correctionMethod": cor["name"], "validTestCount": len(valid), count_key: int(sig),
                        "threshold": thr},
            "rows": rows}
