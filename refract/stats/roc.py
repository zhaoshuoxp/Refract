"""ROC curve (Prism: ROC_CURVE) and area under the curve (AREA_UNDER_CURVE),
with Prism's result keys (verified: tools/roc_parity.py).
"""

from __future__ import annotations

import itertools
import math

import numpy as np
from scipy import stats

from .contingency import clopper_pearson, wilson, wilson_brown
from .logistic import roc_area_groups


def _p(value: float, alpha: float = 0.05) -> dict:
    return {"value": float(value), "level": alpha, "isSignificant": bool(value < alpha), "state": "P_VALUE_EQUAL"}


def _clean(col):
    return [float(v) for v in col if v is not None and v != "" and math.isfinite(float(v))]


def _prop_ci(method, x, n, z, alpha):
    if method == "CLOPPER_PEARSON":
        return clopper_pearson(x, n, alpha)
    if method == "WILSON":
        return wilson(x, n, z)
    return wilson_brown(x, n, z, alpha)


def roc_curve(params: dict, columns) -> dict:
    """columns[controlID idx] = controls, columns[patientID idx] = patients.
    Thresholds: the smallest value, the midpoints of consecutive distinct
    values, the largest value; sensitivity = patients above the threshold,
    specificity = controls below it (verified)."""
    data, opt = params.get("data", {}), params.get("options", {})
    ci_, pi_ = data.get("controlID", {}).get("col", {}).get("idx", 0), data.get("patientID", {}).get("col", {}).get("idx", 1)
    ctrl, pat = np.array(_clean(columns[ci_])), np.array(_clean(columns[pi_]))
    level = opt.get("confidenceLevel", 95.0)
    alpha = 1 - level / 100
    z = stats.norm.ppf(1 - alpha / 2)
    pct = 100.0 if opt.get("reportResultsAs", "PERCENTAGE") == "PERCENTAGE" else 1.0
    method = opt.get("confidenceMethod", "WILSON_BROWN")
    area, se = roc_area_groups(pat, ctrl)
    swapped = area < 0.5
    if swapped:  # patients lower than controls: Prism reports the swapped area (assumed)
        area = 1 - area
    n1, n0 = len(pat), len(ctrl)
    se0 = math.sqrt((n1 + n0 + 1) / (12 * n1 * n0))  # SE under the null hypothesis (area 0.5)
    auc = {"status": "VALID", "area": area, "se": se,
           "ci": {"lower": max(0.0, area - z * se), "upper": min(1.0, area + z * se), "level": level},
           "isSwapped": bool(swapped), "pValue": _p(2 * stats.norm.sf(abs(area - 0.5) / se0), alpha)}
    u = sorted(set(ctrl.tolist()) | set(pat.tolist()))
    # the first threshold lies just below the smallest value, the last just above the largest (verified)
    last = float(np.nextafter(np.nextafter(u[-1], math.inf), math.inf))
    ths = [u[0]] + [(a + b) / 2 for a, b in itertools.pairwise(u)] + [last]
    rows = []
    for k, th in enumerate(ths):
        th_cmp = float(np.nextafter(th, -math.inf)) if k == 0 else th
        if swapped:
            tp, tn = int((pat < th_cmp).sum()), int((ctrl > th_cmp).sum())
        else:
            tp, tn = int((pat > th_cmp).sum()), int((ctrl < th_cmp).sum())
        sl, sh = _prop_ci(method, tp, n1, z, alpha)
        pl, ph = _prop_ci(method, tn, n0, z, alpha)
        sens, spec = tp / n1, tn / n0
        lr = "undefined" if spec == 1 else sens / (1 - spec)
        rows.append({"threshold": float(th),
                     "sensitivity": {"value": pct * sens, "ci": {"lower": pct * sl, "upper": pct * sh}},
                     "specificity": {"value": pct * spec, "ci": {"lower": pct * pl, "upper": pct * ph}},
                     "likelihoodRatio": lr})

    def missing(col):  # blanks above the last value
        idx = [i for i, v in enumerate(col) if v is not None and v != ""]
        return sum(1 for v in col[: idx[-1] + 1] if v is None or v == "") if idx else 0

    summary = {"controlCount": n0, "patientCount": n1, "controlMissingCount": missing(columns[ci_]),
               "patientMissingCount": missing(columns[pi_])}
    return {"status": {"error": "VALID", "warning": []}, "aucTest": auc, "sensitivitySpecificity": rows,
            "dataSummary": summary}


# ------------------------------------------------------------- area under curve
def _segments(x, d):
    """Split the curve (x, d = y - baseline) at its baseline crossings (linear
    interpolation): [(sign, x_start, x_end, area, [point indices])]."""
    segs = []
    cur = None
    for i in range(len(x)):
        s = 1 if d[i] > 0 else -1 if d[i] < 0 else 0
        if cur is None:
            cur = {"sign": s, "x0": x[i], "area": 0.0, "pts": [i]}
            continue
        j = i - 1
        sj = cur["sign"]
        if s == sj or s == 0 or sj == 0:
            cur["area"] += (x[i] - x[j]) * (d[i] + d[j]) / 2
            cur["pts"].append(i)
            if sj == 0:
                cur["sign"] = s
            continue
        xc = x[j] + (x[i] - x[j]) * d[j] / (d[j] - d[i])  # crossing
        cur["area"] += (xc - x[j]) * d[j] / 2
        cur["x1"] = xc
        segs.append(cur)
        cur = {"sign": s, "x0": xc, "area": (x[i] - xc) * d[i] / 2, "pts": [i]}
    if cur is not None:
        cur["x1"] = x[-1]
        segs.append(cur)
    return segs


def area_under_curve(params: dict, x, sets) -> dict:
    """x: X values (None: row numbers 1, 2, ...); sets: Y columns."""
    calc = params.get("calc", {})
    base, peak = calc.get("baseline", {}), calc.get("peak", {})
    pos_only = peak.get("calcPositivePeaksOnly", True)
    amp = peak.get("height", {}).get("minimumAmplitudePercentage", 10.0) / 100 \
        if peak.get("height", {}).get("definePeakByAmplitudePercentage", True) else 0.0
    min_units = peak.get("height", {}).get("minimumYUnitCount", 0.0)
    narrow = peak.get("width", {}).get("ignoreNarrowPeak", False)
    adj = peak.get("width", {}).get("adjacentPointCount", 2)
    warn = []
    samples = {}
    for si, ys in enumerate(sets):
        pts = [((x[r] if x is not None else r + 1.0), float(v)) for r, v in enumerate(ys)
               if v is not None and math.isfinite(v) and (x is None or (x[r] is not None and math.isfinite(x[r])))]
        xs = np.array([p[0] for p in pts])
        yv = np.array([p[1] for p in pts])
        if base.get("useSpecificValue", True):
            b = float(base.get("value", 0.0))
        else:
            k1, k2 = base.get("firstRowsMeanCount", 1), base.get("lastRowsMeanCount", 0)
            b = float(np.mean(np.concatenate([yv[:k1], yv[len(yv) - k2:] if k2 else yv[:0]])))
        d = yv - b
        segs = _segments(xs, d)
        rng = float(yv.max() - yv.min())
        total = sum(abs(s["area"]) for s in segs)
        peaks = []
        for s in segs:
            if s["sign"] == 0 or (pos_only and s["sign"] < 0):
                continue
            h = max(abs(d[i]) for i in s["pts"])
            if h < amp * rng or h < min_units or (narrow and len(s["pts"]) < adj):
                continue
            ip = max(s["pts"], key=lambda i: abs(d[i]))
            peaks.append({"firstX": float(s["x0"]), "lastX": float(s["x1"]), "peakX": float(xs[ip]), "peakY": float(yv[ip]),
                          "area": abs(s["area"]), "_sign": s["sign"]})
        pos_area = sum(p["area"] for p in peaks if p["_sign"] > 0)
        neg_area = sum(p["area"] for p in peaks if p["_sign"] < 0)
        tpa = pos_area + neg_area
        summary = {"baseline": b, "peakCount": len(peaks)}
        if not pos_only:
            summary.update({"positivePeakArea": pos_area, "negativePeakArea": neg_area})
        summary["totalArea"] = total
        if not pos_only:
            summary["netArea"] = pos_area - neg_area
        summary["totalPeakArea"] = tpa
        for p in peaks:
            p["areaPercentage"] = 100 * p["area"] / tpa if tpa else math.nan
            p.pop("_sign")
        samples[f"col{si}"] = {"id": {"col": {"title": chr(65 + si), "idx": si}},
                               "value": {"status": "VALID", "summary": summary,
                                         "peaks": {f"Peak {k + 1}": p for k, p in enumerate(peaks)}}}
    if x is None:
        warn.append("ROW_NUMBERS_AS_X")
    return {"status": {"error": "VALID", "warning": warn}, "samples": samples}
