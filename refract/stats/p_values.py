"""Analyze a stack of P values (MULTIPLE_COMPARISONS): one column of P values
corrected for multiple comparisons - the false discovery rate (two-stage
Benjamini-Krieger-Yekutieli, Benjamini-Hochberg, Benjamini-Yekutieli) or
Holm-Šídák / Bonferroni-Šídák - with Prism's results and result tables
(verified against Prism 11.1, E-stats8; the corrections are refract.stats.
multiple_t.correct, the same as Prism's multiple t tests)."""

from __future__ import annotations

import math

from .multiple_t import correct


def _p(v: float, level: float, significant: bool, rank: int) -> dict:
    return {"value": float(v), "level": level, "isSignificant": bool(significant), "rank": rank,
            "state": "P_VALUE_EQUAL"}


def stack(params: dict, columns: list) -> dict:
    """columns[0]: the P values (one per row; blanks skipped)."""
    col = columns[0] if columns else []
    rows = [(r, float(v)) for r, v in enumerate(col) if v is not None and math.isfinite(v)]
    ps = [v for _, v in rows]
    cor = correct(ps, params.get("multipleComparisons", {}))
    thr = cor["threshold"]
    order = sorted(range(len(ps)), key=lambda i: ps[i])
    rank = {i: k for k, i in enumerate(order)}
    summary = {"pValueCount": len(ps), "correctionMethod": cor["name"]}
    out_rows, flags, second = {}, [], []
    for i, (r, p) in enumerate(rows):
        sig = isinstance(thr, float) and p <= thr
        if cor["fdr"]:
            q = cor["q"][i]
            extra = {"qValue": {"value": float(q), "level": cor["alpha"], "isDiscovery": bool(q <= cor["alpha"])}}
            second.append(float(q))
            flags.append(q <= cor["alpha"])
        elif "adjusted" in cor:
            a = cor["adjusted"][i]
            extra = {"pValueAdjusted": {"value": float(a), "level": cor["alpha"], "isSignificant": bool(a < cor["alpha"]),
                                        "state": "P_VALUE_EQUAL"}}
            second.append(float(a))
            flags.append(a < cor["alpha"])
        else:
            extra = {}
            second.append(None)
            flags.append(p <= cor["alpha"])
        out_rows[f"row{r}"] = {"id": {"row": {"idx": r}}, "value": {"pValue": _p(p, thr if isinstance(thr, float)
                                                                                   else cor["alpha"], sig, rank[i]),
                                                                     **extra}}
    n_found = sum(flags)
    if cor["fdr"]:
        summary["discoveryCount"] = n_found
        if cor["name"].startswith("Two-stage"):
            summary["estimatedTrueNullHypothesisCount"] = _m0(ps, cor["alpha"])
    else:
        summary["significantCount"] = n_found
    summary["threshold"] = thr
    label, flag = ("q value", "Discovery?") if cor["fdr"] else ("Adjusted P Value", "Below threshold?")
    found = sorted((i for i in range(len(ps)) if flags[i]), key=lambda i: ps[i])
    tables = {
        ("q values" if cor["fdr"] else "Adjusted P values"): {
            "columns": [flag, "P value", label], "row_titles": None,
            "rows": [["Yes" if flags[i] else "No", ps[i], second[i]] for i in range(len(ps))]},
        ("Discoveries" if cor["fdr"] else "P small enough?"): {
            "columns": ["P value", label], "row_titles": [f"#{k + 1}" for k in range(len(found))],
            "rows": [[ps[i], second[i]] for i in found]}}
    return {"status": {"error": "VALID", "warning": []}, "summary": summary, "rows": out_rows, "_tables": tables}


def _m0(ps: list[float], q: float) -> int:
    """The two-stage method's estimate of the true null hypotheses: m minus stage one's discoveries."""
    m = len(ps)
    srt = sorted(ps)
    q1 = q / (1 + q)
    r1 = max((i + 1 for i in range(m) if srt[i] <= (i + 1) * q1 / m), default=0)
    return (m - r1) or m
