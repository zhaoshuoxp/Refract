"""Deming (model II) linear regression (DEMING_REGRESSION), as Prism 11.1
reports it (E-stats8, Prism's own results): per data set the Deming slope
and intercept for the ratio of the Y and X error SDs (EQUAL_SD: 1), their
SEs by the jackknife (leaving out each point), t-based CIs on n - 2 df, the
X-intercept, and - as Prism - the test of a non-zero slope and the goodness
of fit from ordinary least squares (F of the correlation, residual SS and
Sy.x)."""

from __future__ import annotations

import math

import numpy as np
from scipy import stats

U = "undefined"


def _fit(x: np.ndarray, y: np.ndarray, lam: float) -> tuple[float, float]:
    mx, my = x.mean(), y.mean()
    sxx, syy, sxy = ((x - mx) ** 2).sum(), ((y - my) ** 2).sum(), ((x - mx) * (y - my)).sum()
    b = (syy - lam * sxx + math.sqrt((syy - lam * sxx) ** 2 + 4 * lam * sxy * sxy)) / (2 * sxy)
    return float(b), float(my - b * mx)


def _p(v: float, alpha: float = 0.05) -> dict:
    return {"value": float(v), "level": alpha, "isSignificant": bool(v < alpha), "state": "P_VALUE_EQUAL"}


def _fmt(v: float) -> str:
    return f"{v:.4g}"


def deming(params: dict, x: list, columns: list, titles: list[str]) -> dict:
    model = params.get("model", {})
    lam = 1.0 if model.get("sdType", "EQUAL_SD") == "EQUAL_SD" else \
        (float(model.get("ySD", 1.0)) / float(model.get("xSD", 1.0))) ** 2
    level = 95.0
    models, lines, warn = {}, {}, []
    individual = (params.get("data") or {}).get("handleReplicatesAs", "INDIVIDUAL") == "INDIVIDUAL"
    replicated = any(c and isinstance(c[0], (list, tuple)) and len(c) > 1 for c in columns)
    for j, col in enumerate(columns):
        subs = col if col and isinstance(col[0], (list, tuple)) else [col]  # [subcolumn][row] or one column
        if individual or len(subs) == 1:  # every replicate is a point
            pts = [(float(a), float(b)) for sub in subs for a, b in zip(x or [], sub, strict=False)
                   if a is not None and b is not None and math.isfinite(a) and math.isfinite(b)]
            pts.sort(key=lambda p: p[0])
        else:  # the mean of each row
            pts = []
            for r, a in enumerate(x or []):
                vals = [s[r] for s in subs if r < len(s) and s[r] is not None and math.isfinite(s[r])]
                if a is not None and math.isfinite(a) and vals:
                    pts.append((float(a), float(np.mean(vals))))
        xs, ys = np.array([p[0] for p in pts]), np.array([p[1] for p in pts])
        n = len(xs)
        # Prism counts the table's rows up to this data set's last value
        last = max((i for sub in subs for i, v in enumerate(sub) if v is not None), default=-1)
        rows = sum(1 for v in (x or [])[:last + 1] if v is not None)
        slots = rows * (len(subs) if individual else 1)  # Prism: X values = the point slots
        b, a = _fit(xs, ys, lam)
        jk = [_fit(np.delete(xs, i), np.delete(ys, i), lam) for i in range(n)]
        se = [math.sqrt((n - 1) / n * sum((v[k] - np.mean([w[k] for w in jk])) ** 2 for v in jk)) for k in (0, 1)]
        df = n - 2
        tc = stats.t.ppf(1 - (1 - level / 100) / 2, df)
        r = float(np.corrcoef(xs, ys)[0, 1])
        f = r * r / (1 - r * r) * df
        bo, ao = np.polyfit(xs, ys, 1)
        ss = float(((ys - ao - bo * xs) ** 2).sum())
        sign = "+" if a >= 0 else "-"
        models[f"col{j}"] = {"id": {"col": {"idx": j, "title": titles[j]}}, "value": {
            "model": {"status": "COMPLETED", "equation": f"Y = {_fmt(b)}*X {sign} {_fmt(abs(a))}",
                      "parameters": {
                          "Slope": {"estimate": b, "se": se[0], "ci": {"lower": b - tc * se[0], "upper": b + tc * se[0],
                                                                       "level": level},
                                    "significanceTest": {"status": "VALID", "f": float(f), "dfNumerator": 1.0,
                                                         "dfDenominator": float(df),
                                                         "pValue": _p(stats.f.sf(f, 1, df))}},
                          "Y-intercept": {"estimate": a, "se": se[1],
                                          "ci": {"lower": a - tc * se[1], "upper": a + tc * se[1], "level": level}},
                          "X-intercept": {"estimate": -a / b, "se": U, "ci": {"lower": U, "upper": U, "level": level}}},
                      "goodnessOfFit": {"df": float(df), "lfv": ss, "r2": r * r, "syx": math.sqrt(ss / df)}},
            "dataSummary": {"xValues": slots, "yReplicates": len(subs) if individual else 1, "pointsAnalyzed": n,
                            "pointsSkipped": slots - n}}}
        lo, hi = float(xs.min()), float(xs.max())
        lines[titles[j]] = (lo, hi, b, a)
    # Prism's line: one X series across all the data (200 segments for more than one data set of single
    # Y values, else 100); each line is blank outside its own X range
    seg = 200 if len(lines) > 1 and not replicated else 100
    rows = []
    if lines:
        x0 = min(v[0] for v in lines.values())
        x1 = max(v[1] for v in lines.values())
        step = (x1 - x0) / seg
        eps = abs(step) * 1e-9
        for k in range(seg + 1):
            xv = x0 + k * step
            rows.append([xv, *((a + b * xv) if lo - eps <= xv <= hi + eps else None
                                for lo, hi, b, a in lines.values())])
    return {"status": {"error": "VALID", "warning": warn}, "models": models,
            "_tables": {"Line": {"columns": ["X", *titles], "rows": rows, "row_titles": None}}}
