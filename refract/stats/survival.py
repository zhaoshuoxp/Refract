"""Survival analysis (Prism: SURVIVAL): Kaplan-Meier per group, curve
comparison (log-rank / Mantel-Cox, Gehan-Breslow-Wilcoxon, log-rank test for
trend), hazard ratios and median survival ratios, data summary.

Input: one survival table: x[r] = time of subject r, groups[g][r] = event
code (1 event, 0 censored, None blank) of subject r in group g.
"""

from __future__ import annotations

import math

import numpy as np
from scipy import stats


def _p(value: float, alpha: float) -> dict:
    return {"value": float(value), "level": alpha, "isSignificant": bool(value < alpha), "state": "P_VALUE_EQUAL"}


def _subjects(x, codes, event=1, censor=0):
    t, e = [], []
    for xi, ci in zip(x, codes, strict=False):
        if ci is None or xi is None:
            continue
        if ci == event:
            t.append(float(xi)); e.append(1)
        elif ci == censor:
            t.append(float(xi)); e.append(0)
    return np.array(t), np.array(e, int)


def kaplan_meier(t: np.ndarray, e: np.ndarray, level: float = 95.0):
    """[(time, at risk, events, censored, S, Greenwood var of log S)] at each distinct time."""
    rows = []
    s, gw = 1.0, 0.0
    for u in np.unique(t):
        n = int((t >= u).sum())
        d = int(((t == u) & (e == 1)).sum())
        c = int(((t == u) & (e == 0)).sum())
        if d:
            s *= 1 - d / n
            gw += d / (n * (n - d)) if n > d else math.inf
        rows.append((float(u), n, d, c, s, gw))
    return rows


def _ci_loglog(s: float, gw: float, z: float) -> tuple[float, float]:
    """Asymmetrical CI of S (log(-log) transform, Kalbfleisch-Prentice)."""
    if s <= 0 or s >= 1 or not math.isfinite(gw):
        return (s, s) if s <= 0 else (1.0, 1.0)
    se = math.sqrt(gw) / abs(math.log(s))
    return s ** math.exp(z * se), s ** math.exp(-z * se)


def median_survival(km, z: float):
    """Median and its CI, as Prism:
    - median = first time with S <= 0.5; when S is exactly 0.5 there, the
      average of that time and the next event time; "undefined" (inf) when S
      stays above 0.5;
    - CI (Brookmeyer & Crowley): first times at which the lower / upper limit
      of the log-log band reaches 0.5; points with S = 0 (no band) are skipped,
      so an upper limit that never reaches 0.5 is +inf."""
    med = math.inf
    for i, r in enumerate(km):
        if r[4] <= 0.5:
            med = r[0]
            if r[4] == 0.5:
                nxt = next((q[0] for q in km[i + 1:] if q[2] > 0), None)
                if nxt is not None:
                    med = (r[0] + nxt) / 2
            break
    band = [(r[0], *_ci_loglog(r[4], r[5], z)) for r in km if r[4] > 0]
    lo = next((t for t, lower, _ in band if lower <= 0.5), math.inf)
    hi = next((t for t, _, upper in band if upper <= 0.5), math.inf)
    return med, lo, hi


def _logrank_parts(groups, weight: str = "logrank"):
    """O - E vector and covariance for k groups (weights: 1 = log-rank,
    n at risk = Gehan-Breslow-Wilcoxon)."""
    k = len(groups)
    allt = np.unique(np.concatenate([g[0][g[1] == 1] for g in groups if len(g[0])]))
    oe = np.zeros(k)
    v = np.zeros((k, k))
    o = np.zeros(k)
    ex = np.zeros(k)
    for u in allt:
        n = np.array([(g[0] >= u).sum() for g in groups], float)
        d = np.array([((g[0] == u) & (g[1] == 1)).sum() for g in groups], float)
        nt, dt = n.sum(), d.sum()
        if nt == 0:
            continue
        w = 1.0 if weight == "logrank" else nt
        e = n * dt / nt
        oe += w * (d - e)
        o += d
        ex += e
        if nt > 1:
            f = dt * (nt - dt) / (nt - 1)
            v += w * w * f * (np.diag(n / nt) - np.outer(n, n) / nt ** 2)
    return oe, v, o, ex


def _chi2(oe, v):
    k = len(oe)
    a, b = oe[: k - 1], v[: k - 1, : k - 1]
    chi = float(a @ np.linalg.solve(b, a)) if k > 2 else float(a[0] ** 2 / b[0, 0])
    return chi, k - 1


def survival(params: dict, x, groups, titles: list[str]) -> dict:
    d = params.get("data", {})
    calc = params.get("calc", {})
    ev, ce = d.get("eventCode", 1), d.get("censorCode", 0)
    level = calc.get("ciLevel", 95.0)
    z = stats.norm.ppf(1 - (1 - level / 100) / 2)
    alpha = 1 - level / 100  # Prism ties the P-value level to the CI level
    subj = [_subjects(x, g, ev, ce) for g in groups]
    out: dict = {"status": {"error": "VALID", "warning": []}}
    k = len(groups)
    cc = {}
    if k >= 2 and calc.get("logrankTest", True):
        oe, v, o, ex = _logrank_parts(subj)
        chi, df = _chi2(oe, v)
        cc["logrankMantelCoxTest"] = {"status": "VALID", "chiSquared": chi, "df": float(df), "pValue": _p(stats.chi2.sf(chi, df), alpha)}
    if k >= 2 and (calc.get("twoGroupsGehanBreslowWilcoxonTest", True) if k == 2 else calc.get("gehanBreslowWilcoxonTest", False)):
        oe_w, v_w, _, _ = _logrank_parts(subj, "gehan")
        chi, df = _chi2(oe_w, v_w)
        cc["gehanBreslowWilcoxonTest"] = {"status": "VALID", "chiSquared": chi, "df": float(df), "pValue": _p(stats.chi2.sf(chi, df), alpha)}
    if k >= 3 and calc.get("logrankTestForTrend", True):
        sc = np.arange(1, k + 1, dtype=float)
        oe, v, _, _ = _logrank_parts(subj)
        num = float(sc @ oe)
        chi = num * num / float(sc @ v @ sc)
        cc["logrankTestForTrend"] = {"status": "VALID", "chiSquared": chi, "df": 1.0, "pValue": _p(stats.chi2.sf(chi, 1), alpha)}
    if cc:
        out["curveComparison"] = cc
    kms = [kaplan_meier(t, e, level) for t, e in subj]
    meds = [median_survival(km, z) for km in kms]
    if k == 2:
        oe, v, o, ex = _logrank_parts(subj)
        zr = 1.96  # Prism's ratio intervals are always 95% with z = 1.96 (labelled with ciLevel)
        events = [int(e.sum()) for _, e in subj]

        def ratio(a, b, sign):
            r = {}
            ma, mb = meds[a][0], meds[b][0]
            if math.isfinite(ma) and math.isfinite(mb) and events[a] and events[b]:
                mr = ma / mb
                f = math.exp(zr * math.sqrt(1 / events[a] + 1 / events[b]))
                r["medianSurvivalRatio"] = mr
                r["medianSurvivalRatioConfidenceInterval"] = {"lower": mr / f, "upper": mr * f, "level": level}
            # Mantel-Haenszel: exp((O-E)/V), CI exp(... +- z / sqrt(V)) for group a vs b
            va = v[0, 0]
            lmh = sign * oe[0] / va
            r["mantelHaenszelHazardRatio"] = math.exp(lmh)
            r["mantelHaenszelHazardRatioConfidenceInterval"] = {"lower": math.exp(lmh - zr / math.sqrt(va)),
                                                                "upper": math.exp(lmh + zr / math.sqrt(va)), "level": level}
            hr = (o[a] / ex[a]) / (o[b] / ex[b])
            se = math.sqrt(1 / ex[a] + 1 / ex[b])
            r["logrankHazardRatio"] = hr
            r["logrankHazardRatioConfidenceInterval"] = {"lower": hr * math.exp(-zr * se), "upper": hr * math.exp(zr * se),
                                                         "level": level}
            return r

        ids = [{"col": {"title": titles[i], "idx": i}} for i in range(2)]
        out["ratios"] = {"ratio": {"id": [ids[0], ids[1]], "value": ratio(0, 1, 1)},
                         "ratioReciprocal": {"id": [ids[1], ids[0]], "value": ratio(1, 0, -1)}}
    nrows = len(x)
    summ = {}
    for i, g in enumerate(groups):
        t, e = subj[i]
        blank = sum(1 for c in g if c is None) + max(0, nrows - len(g))
        med, lo, hi = meds[i]

        def f(v):
            return float(v) if math.isfinite(v) else "+inf"

        v = {"rowCount": float(nrows), "blankRowCount": float(blank),
             "impossibleDataRowCount": float(len(g) - blank - len(t) + max(0, nrows - len(g))),
             "censoredCount": float((e == 0).sum()), "eventCount": float((e == 1).sum())}
        if math.isfinite(med):
            # computed at ciLevel, but Prism 11.1 labels it 95 whatever the level (reproduced)
            v["medianSurvival"] = float(med)
            v["medianSurvivalCI"] = {"lower": f(lo), "upper": f(hi), "level": 95.0}
        else:
            v["medianSurvival"] = "undefined"
        summ[f"col{i}"] = {"id": {"col": {"title": titles[i], "idx": i}}, "value": v}
    out["dataSummary"] = summ
    pt = params.get("postTests") or {}
    if pt.get("type") == "PAIRWISE_TESTS" and k >= 3 and params.get("_mv"):  # Prism: Multiple-variables tables only
        out["multipleComparisons"] = _pairwise(pt.get("pairwiseTests") or {}, subj, meds, titles)
    return out


MC_LABEL = {"HOLM_SIDAK": "Holm-Šídák"}


def _pairwise(pw: dict, subj, meds, titles: list[str]) -> dict:
    """Post tests: a log-rank test of each pair of curves (the control against each other group,
    or every pair), its P value corrected for the family (Holm-Šídák, Bonferroni, Šídák or none).
    Verified against Prism's own sample (control vs. all, Holm-Šídák)."""
    from .multiple_comparisons import _holm_sidak, pairs

    design = (pw.get("pairwiseDesign") or {})
    ctl = (((design.get("controlID") or {}).get("col")) or {}).get("idx", 0)
    sel = [((a.get("col") or {}).get("idx"), (b.get("col") or {}).get("idx"))
           for a, b in (design.get("selectedPairIDList") or []) if isinstance(a, dict) and isinstance(b, dict)]
    todo = pairs(len(subj), design.get("type", "ALL_VS_ALL"), int(ctl or 0), sel)
    mc = pw.get("multipleComparisons") or {}
    kind = mc.get("type", "STATISTICAL")
    test = (mc.get("statistical") or {}).get("test", "HOLM_SIDAK")
    alpha = float(((mc.get("statistical") or {}).get("options") or {}).get("significanceLevel", 0.05)) \
        if kind != "NO_CORRECTION" else float(((mc.get("noCorrection") or {}).get("options") or {}).get(
            "significanceLevel", 0.05))
    stat, raw = [], []
    for a, b in todo:
        oe, v, _, _ = _logrank_parts([subj[a], subj[b]])
        chi, df = _chi2(oe, v)
        stat.append(chi)
        raw.append(float(stats.chi2.sf(chi, df)))
    m = len(raw)
    if kind == "NO_CORRECTION":
        adj = raw
    elif test == "HOLM_SIDAK":  # (BONFERRONI and SIDAK are not Prism's names here: it stores UNKNOWN)
        adj = _holm_sidak(raw)
    else:
        raise NotImplementedError(f"survival post tests corrected by {kind} {test}")
    tests: dict = {}
    for (a, b), chi, p in zip(todo, stat, adj, strict=True):
        ida, idb = ({"col": {"title": titles[i], "idx": i}} for i in (a, b))

        def sample(i):
            med = meds[i][0]
            return {"id": {"col": {"title": titles[i], "idx": i}},
                    "value": {"median": float(med) if math.isfinite(med) else "undefined", "n": int(subj[i][1].sum())}}  # n: the group's events (Prism)
        entry = tests.setdefault(f"col{a}", {"id": ida, "value": {}})
        entry["value"][f"col{b}"] = {"id": idb, "value": {
            "status": "VALID", "statistic": chi, "df": 1.0, "pValueAdjusted": _p(p, alpha),
            "sample1": sample(a), "sample2": sample(b)}}
    label = "No correction" if kind == "NO_CORRECTION" else MC_LABEL.get(test, test.replace("_", " ").title())
    return {"status": "VALID", "method": label, "comparisonCount": m,
            "significantCount": sum(1 for p in adj if p < alpha), "tests": tests}
