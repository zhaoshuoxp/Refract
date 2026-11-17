"""Outlier identification (Prism: IDENTIFY_OUTLIERS - Grubbs, iterative
Grubbs, ROUT) and Bland-Altman agreement (BLAND_ALTMAN), with Prism's result
keys and result tables (verified: tools/outlier_parity.py).

Input: columns = one list of values per data set (None = blank).
Output: {"results": results.json content, "tables": {result sheet title:
{"sets": [{"title", "subs"}], "x": [...]?}}}.
"""

from __future__ import annotations

import math

import numpy as np
from scipy import optimize, stats


def _clean(col):
    return [v for v in col if v is not None and math.isfinite(v)]


# ------------------------------------------------------------------ Grubbs
def grubbs_critical(n: int, alpha: float) -> float:
    t = stats.t.isf(alpha / (2 * n), n - 2)
    return (n - 1) / math.sqrt(n) * math.sqrt(t * t / (n - 2 + t * t))


def grubbs_g(vals) -> tuple[float, int]:
    a = np.asarray(vals, float)
    dev = np.abs(a - a.mean())
    i = int(np.argmax(dev))
    return float(dev[i] / a.std(ddof=1)), i


def _grubbs(vals, alpha, iterative):
    """-> (outlier indices into vals, G of the first test)."""
    idx = list(range(len(vals)))
    out, g_first = [], None
    while len(idx) >= 3:
        sub = [vals[i] for i in idx]
        if np.std(sub, ddof=1) == 0:
            break
        g, j = grubbs_g(sub)
        if g_first is None:
            g_first = g
        if g <= grubbs_critical(len(idx), alpha):
            break
        out.append(idx.pop(j))
        if not iterative:
            break
    return out, g_first


# -------------------------------------------------------------------- ROUT
def rout(vals, q: float) -> list[int]:
    """ROUT (Motulsky & Brown 2006) for a column (model Y = constant), as
    Prism 11.1 computes it (verified, 160 of 160 parity columns):
    RSDR = 68.27th percentile of |residual| * n / (n - 1); the centre is the
    Lorentzian (robust) fit with the scale fixed at the RSDR around the
    median; then each residual's two-sided t P value (df n - 1, t =
    |residual| / RSDR at the fit) and Benjamini-Hochberg at Q %: the k
    largest residuals are outliers, k the largest rank with P(k) <= k Q / n."""
    a = np.asarray(vals, float)
    n = len(a)
    if n < 3:
        return []

    def rsdr(c):
        return float(np.percentile(np.abs(a - c), 68.27, method="linear") * n / (n - 1))

    s0 = rsdr(float(np.median(a)))
    if s0 == 0:
        return []
    c = float(optimize.minimize_scalar(lambda c: float(np.log1p(((a - c) / s0) ** 2).sum()),
                                       bounds=(float(a.min()), float(a.max())), method="bounded",
                                       options={"xatol": 1e-12}).x)
    s = rsdr(c)
    if s == 0:
        return []
    r = np.abs(a - c)
    order = np.argsort(-r)
    ps = 2 * stats.t.sf(r / s, n - 1)
    asc = np.sort(ps)
    k = 0
    for i, p in enumerate(asc, 1):
        if p <= i * (q / 100) / n:
            k = i
    return [int(i) for i in order[:k]]


def identify_outliers(params: dict, columns) -> dict:
    calc = params.get("calc", {})
    method = calc.get("method", "GRUBBS_SINGLE")
    alpha, q = calc.get("alpha", 0.05), calc.get("q", 1.0)
    titles = [chr(65 + i) for i in range(len(columns))]
    samples, cleaned, outl = {}, [], []
    total = 0
    for c, col in enumerate(columns):
        pos = [r for r, v in enumerate(col) if v is not None and math.isfinite(v)]
        vals = [col[r] for r in pos]
        g = None
        if method in ("GRUBBS_SINGLE", "GRUBBS_MULTIPLE"):
            found, g = _grubbs(vals, alpha, method == "GRUBBS_MULTIPLE")
        elif method == "ROUT":
            found = rout(vals, q)
        else:
            raise NotImplementedError(f"outlier method {method}")
        bad = {pos[i] for i in found}
        total += len(bad)
        value = {}
        if method == "GRUBBS_SINGLE" and g is not None:
            value["grubbsG"] = g
        value.update({"pointCount": len(vals), "outlierCount": len(bad)})
        samples[f"col{c}"] = {"id": {"col": {"title": titles[c], "idx": c}}, "value": value}
        cleaned.append({"title": titles[c], "subs": [[None if r in bad else v for r, v in enumerate(col)]]})
        outl.append(sorted(bad))
    # Outliers table: one row per outlier ("#row", 1-based), its value in its own column (verified)
    out_rows = [(c, r) for c, rows in enumerate(outl) for r in rows]
    outl = [{"title": titles[c], "subs": [[columns[c][r] if cc == c else None for cc, r in out_rows]]}
            for c in range(len(columns))]
    out_titles = [f"#{r + 1}" for _, r in out_rows]
    name = {"GRUBBS_SINGLE": "Grubbs", "GRUBBS_MULTIPLE": "Iterative Grubbs", "ROUT": "ROUT"}[method]
    summary = {"method": name, **({"q": q} if method == "ROUT" else {"alpha": alpha}), "totalOutlierCount": total}
    return {"results": {"status": {"error": "VALID", "warning": []}, "summary": summary, "samples": samples},
            "tables": {"Cleaned data": {"sets": cleaned}, "Outliers": {"sets": outl, "rows": out_titles}}}


# ------------------------------------------------------------ Bland-Altman
def bland_altman(params: dict, columns) -> dict:
    data = params.get("data", {})
    ia = data.get("methodAID", {}).get("col", {}).get("idx", 0)
    ib = data.get("methodBID", {}).get("col", {}).get("idx", 1)
    kind = params.get("calc", {}).get("type", "A_MINUS_B")
    a_col, b_col = columns[ia], columns[ib]
    diffs, avgs, t_d, t_x = [], [], [], []
    for a, b in zip(a_col, b_col, strict=False):
        if a is None or b is None or not (math.isfinite(a) and math.isfinite(b)):
            t_d.append(None)
            t_x.append(None)
            continue
        if kind == "A_MINUS_B":
            d = a - b
        elif kind == "B_MINUS_A":
            d = b - a
        elif kind == "A_DIV_B":  # ratio (verified); a zero divisor drops the pair
            if b == 0:
                t_d.append(None)
                t_x.append(None)
                continue
            d = a / b
        elif kind == "B_DIV_A":
            if a == 0:
                t_d.append(None)
                t_x.append(None)
                continue
            d = b / a
        else:
            raise NotImplementedError(f"Bland-Altman {kind}")
        diffs.append(d)
        avgs.append((a + b) / 2)
        t_d.append(d)
        t_x.append((a + b) / 2)
    d = np.asarray(diffs)
    bias, sd = float(d.mean()), float(d.std(ddof=1))
    z = 1.96  # Prism uses 1.96 exactly (verified)
    res = {"status": {"error": "VALID", "warning": []}, "bias": bias, "sd": sd,
           "ci": {"lower": bias - z * sd, "upper": bias + z * sd, "level": 95.0}}
    what = "Ratio" if kind in ("A_DIV_B", "B_DIV_A") else "Difference"
    return {"results": res, "tables": {f"{what} vs. average": {"x": t_x, "sets": [{"title": what, "subs": [t_d]}]}}}
