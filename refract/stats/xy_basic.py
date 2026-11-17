"""Correlation (Prism: CORRELATION) and simple linear regression
(SIMPLE_LINEAR_REGRESSION) for XY tables, with Prism's result keys.
Names and layout from a Prism-made sample (corpus/manual/batch2_samples.prism).
"""

from __future__ import annotations

import itertools
import math

import numpy as np
from scipy import stats

SPEARMAN_CI_MIN_N = 11


def _p(value: float, alpha: float = 0.05) -> dict:
    return {"value": float(value), "level": alpha, "isSignificant": bool(value < alpha), "state": "P_VALUE_EQUAL"}


def _pairs(x, y):
    pr = [(a, b) for a, b in zip(x, y, strict=False)
          if a is not None and b is not None and math.isfinite(a) and math.isfinite(b)]
    return np.array([p[0] for p in pr], float), np.array([p[1] for p in pr], float)


def pearson(x, y, level: float = 95.0, alpha: float = 0.05) -> dict:
    a, b = _pairs(x, y)
    n = len(a)
    r = float(np.corrcoef(a, b)[0, 1])
    t = r * math.sqrt((n - 2) / (1 - r * r))
    p = 2 * stats.t.sf(abs(t), n - 2)
    z = math.atanh(r)
    zc = stats.norm.ppf(1 - (1 - level / 100) / 2) / math.sqrt(n - 3)
    return {"status": "VALID", "n": float(n), "r": r, "r2": r * r,
            "rCI": {"lower": math.tanh(z - zc), "upper": math.tanh(z + zc), "level": level}, "pValue": _p(p, alpha)}


def _snap(v: np.ndarray) -> np.ndarray:
    return np.array([float(f"{t:.12g}") for t in v])


def spearman(x, y, level: float = 95.0, alpha: float = 0.05) -> dict:
    from .two_sample import _spearman_exact_distribution

    a, b = _pairs(x, y)
    n = len(a)
    # Prism ranks values equal to ~12 significant digits as ties (averaged
    # replicates such as 7.3 vs 7.300000000000001; verified)
    ra, rb = stats.rankdata(_snap(a)), stats.rankdata(_snap(b))
    r = float(np.corrcoef(ra, rb)[0, 1])
    t = r * math.sqrt((n - 2) / (1 - r * r)) if abs(r) < 1 else math.inf
    approx = float(2 * stats.t.sf(abs(t), n - 2))
    z = math.atanh(r) if abs(r) < 1 else math.copysign(math.inf, r)
    # Fieller, Hartley & Pearson (1957): Var(atanh r_s) = 1.06 / (n - 3), as Prism
    zc = stats.norm.ppf(1 - (1 - level / 100) / 2) * math.sqrt(1.06 / (n - 3))
    # no interval for small n (Prism: undefined at n <= 10, defined from n = 11; verified)
    ci = ({"lower": math.tanh(z - zc), "upper": math.tanh(z + zc), "level": level} if n >= SPEARMAN_CI_MIN_N else
          {"lower": "undefined", "upper": "undefined", "level": level})
    out = {"status": "VALID", "n": float(n), "r": r, "rCI": ci}
    exact = None
    if n <= 17:  # exact permutation P (two-sided), as the batch-1 pairing test
        dist, scale = _spearman_exact_distribution(ra, rb)
        s_obs = round(float(((ra - rb) ** 2).sum()) * scale)
        # two-sided: |S - E S| at least as large as observed (equals twice the
        # smaller tail without ties; with ties the distribution is skewed; verified)
        sv = np.arange(len(dist))
        mu = float((dist * sv).sum())
        exact = float(min(1.0, dist[np.abs(sv - mu) >= abs(s_obs - mu) - 1e-9].sum()))
    out["pValue"] = _p(exact if exact is not None else approx, alpha)
    out["pValueExact"] = _p(exact, alpha) if exact is not None else {"value": "undefined", "level": alpha,
                                                                    "isSignificant": False, "state": "P_VALUE_EQUAL"}
    out["pValueApproximate"] = _p(approx, alpha)
    return out


def _row_means(subs):
    """Replicates are averaged per row before correlating (verified)."""
    if not subs or not isinstance(subs[0], (list, tuple)):
        return subs
    out = []
    for r in range(max(len(s) for s in subs)):
        v = [s[r] for s in subs if r < len(s) and s[r] is not None and math.isfinite(s[r])]
        out.append(float(np.mean(v)) if v else None)
    return out


def correlation(params: dict, x, ys: list, titles: list[str]) -> dict:
    """ys: per Y data set either a list of values or [subcolumn][row]."""
    ys = [_row_means(y) for y in ys]
    design = params.get("experimentalDesign", "PARAMETRIC")
    opt = params.get("options", {})
    level = opt.get("confidenceLevel", 95.0)
    alpha = 1 - level / 100
    fn = pearson if design == "PARAMETRIC" else spearman
    key = "pearsonTestModel" if design == "PARAMETRIC" else "spearmanTestModel"
    inner = {f"col{i}": {"id": {"col": {"title": titles[i], "idx": i}}, "value": fn(x, y, level, alpha)} for i, y in enumerate(ys)}
    return {"status": {"error": "VALID", "warning": []},
            key: {"x": {"id": {"col": {"idx": -1}}, "value": inner}}}


def _inverse(yv, icpt, slope, tc, syx, sxx, n, m, c0, level):
    """X where the line equals yv, with the Fieller (inverse prediction) set
    {x: (yv - a - b x)^2 <= t^2 s^2 (c0 + (x - m)^2 / Sxx)}: c0 = 1/n, m = mean X
    for an ordinary fit, c0 = 0, m = x0 for a line through a fixed point.
    When the slope is not significant the set is two half-lines; Prism
    reports the one holding the estimate (e.g. [13.9, +inf))."""
    xv = (yv - icpt) / slope
    u, k = yv - icpt, (tc * syx) ** 2
    qa = slope * slope - k / sxx
    qb = -2 * slope * u + 2 * k * m / sxx
    qc = u * u - k * (c0 + m * m / sxx)
    d = qb * qb - 4 * qa * qc
    if d < 0:
        return xv, {"lower": "-inf", "upper": "+inf", "level": level}
    r1, r2 = sorted(((-qb - math.sqrt(d)) / (2 * qa), (-qb + math.sqrt(d)) / (2 * qa)))
    if qa > 0:
        return xv, {"lower": r1, "upper": r2, "level": level}
    if xv >= r2:
        return xv, {"lower": r2, "upper": "+inf", "level": level}
    return xv, {"lower": "-inf", "upper": r1, "level": level}


def runs_count_cdf(runs: int, n1: int, n2: int) -> float:
    """P(R <= runs) for the Wald-Wolfowitz number of runs of n1 + n2 signs."""
    from math import comb

    def ways(r):
        k = r // 2
        if r % 2 == 0:
            return 2 * comb(n1 - 1, k - 1) * comb(n2 - 1, k - 1)
        return comb(n1 - 1, k - 1) * comb(n2 - 1, k) + comb(n1 - 1, k) * comb(n2 - 1, k - 1)

    return sum(ways(r) for r in range(2, runs + 1)) / comb(n1 + n2, n1)


def runs_test(xa, res, alpha=0.05) -> dict:
    """Prism's departure-from-linearity runs test: signs of the residuals in
    X order; one-sided exact P of so few runs. Needs distinct X values
    (otherwise status SAMPLE_HAS_REPLICATES, verified)."""
    if len(set(xa.tolist())) < len(xa):
        return {"status": "SAMPLE_HAS_REPLICATES", "pointsAboveCount": 0, "pointsBelowCount": 0, "runsCount": 0}
    signs = [r > 0 for _, r in sorted(zip(xa.tolist(), res.tolist(), strict=True)) if r != 0]
    above = sum(signs)
    below = len(signs) - above
    runs = 1 + sum(a != b for a, b in itertools.pairwise(signs)) if signs else 0
    p = runs_count_cdf(runs, above, below) if above and below else 1.0
    return {"status": "VALID", "pointsAboveCount": above, "pointsBelowCount": below, "runsCount": runs,
            "pValue": _p(p, alpha), "pValueExact": _p(p, alpha)}


def _points(x, subs, avg):
    xs, ys, skipped = [], [], 0
    for r, xv in enumerate(x):
        vals = [s[r] for s in subs if r < len(s) and s[r] is not None and math.isfinite(s[r])]
        if xv is None:
            continue
        if not avg:
            skipped += len(subs) - len(vals)
        if not vals:
            skipped += 1 if avg else 0
            continue
        if avg:
            xs.append(float(xv))
            ys.append(float(np.mean(vals)))
        else:
            xs.extend([float(xv)] * len(vals))
            ys.extend(vals)
    return np.array(xs), np.array(ys), skipped


def compare_lines(pts: list, alpha: float = 0.05) -> dict:
    """Prism's modelComparisonTests (ANCOVA): equal slopes; when the slopes
    do not differ (P >= alpha), equal intercepts given a common slope."""
    k = len(pts)
    big_n = sum(len(xa) for xa, _ in pts)
    sxx = [float(((xa - xa.mean()) ** 2).sum()) for xa, _ in pts]
    sxy = [float(((xa - xa.mean()) * (ya - ya.mean())).sum()) for xa, ya in pts]
    syy = [float(((ya - ya.mean()) ** 2).sum()) for _, ya in pts]
    ss_sep = sum(yy - xy * xy / xx for xx, xy, yy in zip(sxx, sxy, syy, strict=True))
    df_sep = big_n - 2 * k
    b_c = sum(sxy) / sum(sxx)
    ss_c = sum(syy) - sum(sxy) ** 2 / sum(sxx)
    df_c = big_n - k - 1
    f = ((ss_c - ss_sep) / (k - 1)) / (ss_sep / df_sep)
    p = float(stats.f.sf(f, k - 1, df_sep))
    out = {"slopeTest": {"pooledSlope": b_c, "f": f, "dfNumerator": float(k - 1), "dfDenominator": float(df_sep),
                         "pValue": _p(p, alpha)}}
    if p >= alpha:
        xa = np.concatenate([q[0] for q in pts])
        ya = np.concatenate([q[1] for q in pts])
        b1 = float(((xa - xa.mean()) * (ya - ya.mean())).sum() / ((xa - xa.mean()) ** 2).sum())
        a1 = float(ya.mean() - b1 * xa.mean())
        ss_1 = float(((ya - a1 - b1 * xa) ** 2).sum())
        f2 = ((ss_1 - ss_c) / (k - 1)) / (ss_c / df_c)
        out["interceptTest"] = {"pooledIntercept": a1, "f": f2, "dfNumerator": float(k - 1), "dfDenominator": float(df_c),
                                "pValue": _p(float(stats.f.sf(f2, k - 1, df_c)), alpha)}
    return out


def linear_regression(params: dict, x, y_sets: list, titles: list[str], level: float = 95.0) -> dict:
    """y_sets: per data set, [replicate subcolumn][row] values."""
    calc = params.get("calc", {})
    model_p = params.get("model", {})
    fixed = model_p.get("constrainLineToFixedPoint", False)
    x0 = float(model_p.get("fixedPoint", {}).get("x", 0.0))
    y0f = float(model_p.get("fixedPoint", {}).get("y", 0.0))
    avg = params.get("data", {}).get("handleReplicatesAs", "AVERAGE") == "AVERAGE"
    models, pts = {}, []
    for i, subs in enumerate(y_sets):
        xa, ya, skipped = _points(x, subs, avg)
        pts.append((xa, ya))
        n = len(xa)
        xb, yb = xa.mean(), ya.mean()
        if fixed:  # line through (x0, y0): one free parameter
            sxx = float(((xa - x0) ** 2).sum())
            slope = float(((xa - x0) * (ya - y0f)).sum() / sxx)
            icpt = y0f - slope * x0
            df = n - 1
            m, c0 = x0, 0.0
        else:
            sxx = float(((xa - xb) ** 2).sum())
            slope = float(((xa - xb) * (ya - yb)).sum() / sxx)
            icpt = float(yb - slope * xb)
            df = n - 2
            m, c0 = xb, 1 / n
        res = ya - (icpt + slope * xa)
        ss = float(res @ res)
        syx = math.sqrt(ss / df)
        se_s = syx / math.sqrt(sxx)
        se_i = syx * math.sqrt(c0 + m * m / sxx)
        tc = stats.t.ppf(1 - (1 - level / 100) / 2, df)
        f = (slope / se_s) ** 2
        sst = float(((ya - yb) ** 2).sum())

        xi, xci = _inverse(0.0, icpt, slope, tc, syx, sxx, n, m, c0, level)
        parameters = {
            "Slope": {"estimate": slope, "se": se_s, "ci": {"lower": slope - tc * se_s, "upper": slope + tc * se_s, "level": level},
                      "significanceTest": {"status": "VALID", "f": f, "dfNumerator": 1.0, "dfDenominator": float(df),
                                           "pValue": _p(stats.f.sf(f, 1, df))}},
            "Y-intercept": {"estimate": icpt, "se": se_i, "ci": {"lower": icpt - tc * se_i, "upper": icpt + tc * se_i, "level": level}},
            "X-intercept": {"estimate": xi, "se": "undefined", "ci": xci},
        }
        y0 = calc.get("xCI", {}).get("y", 0.0)
        if calc.get("xCI", {}).get("enabled", True) and y0 != 0:
            xv, xvci = _inverse(y0, icpt, slope, tc, syx, sxx, n, m, c0, level)
            parameters["X value when Y"] = {"name": f"X when Y={y0:g}", "estimate": xv, "se": "undefined", "ci": xvci}
        xq = calc.get("yCI", {}).get("x", 0.0)
        if calc.get("yCI", {}).get("enabled", True) and xq != 0:
            yv = icpt + slope * xq
            se_y = syx * math.sqrt(c0 + (xq - m) ** 2 / sxx)
            parameters["Y value when X"] = {"name": f"Y when X={xq:g}", "estimate": yv, "se": se_y,
                                            "ci": {"lower": yv - tc * se_y, "upper": yv + tc * se_y, "level": level}}
        value = {
            "model": {"status": "COMPLETED", "equation": f"Y = {slope:.4g}*X {'-' if icpt < 0 else '+'} {abs(icpt):.4g}",
                      "parameters": parameters,
                      "goodnessOfFit": {"df": float(df), "lfv": ss, "r2": "undefined" if fixed else 1 - ss / sst, "syx": syx}}}
        if calc.get("departureFromLinearityTest"):
            value["runsTest"] = runs_test(xa, res)
        value["dataSummary"] = {"xValues": float(n + skipped), "yReplicates": 1.0 if avg else float(len(subs)),
                                "pointsAnalyzed": float(n), "pointsSkipped": float(skipped)}
        models[f"col{i}"] = {"id": {"col": {"title": titles[i], "idx": i}}, "value": value}
    out = {"status": {"error": "VALID", "warning": []}, "models": models}
    if calc.get("modelComparisonTest") and len(pts) > 1 and not fixed:
        out["modelComparisonTests"] = compare_lines(pts)
    return out


def _ci_text(ci: dict) -> str:
    lo, hi = ci.get("lower"), ci.get("upper")
    if not isinstance(lo, float) or not isinstance(hi, float):
        return ""
    return f"{lo:#.4g} to {hi:#.4g}"  # four significant digits, trailing zeros kept (as Prism)


def correlation_matrix(params: dict, ys: list, titles: list[str]) -> dict:
    """Correlation of every pair of data sets (Prism: CORRELATION of a column
    or Multiple-variables table): results nested per pair (i <= j), and the
    matrices of r, P values, sample size and confidence intervals."""
    ys = [_row_means(y) for y in ys]
    design = params.get("experimentalDesign", "PARAMETRIC")
    opt = params.get("options", {})
    level = opt.get("confidenceLevel", 95.0)
    alpha = 1 - level / 100
    one_tail = opt.get("pValueTailType") == "P_VALUE_ONE_TAILED"
    spear = design != "PARAMETRIC"
    fn = spearman if spear else pearson

    def ok(v):
        return isinstance(v, (int, float)) and math.isfinite(v)

    # a variable without numbers (a categorical one) is left out; the others keep their indices
    idx = [i for i, y in enumerate(ys) if any(ok(v) for v in y)]
    ys, names = [ys[i] for i in idx], [titles[i] for i in idx]
    k = len(ys)
    rows = max((len(y) for y in ys), default=0)
    ys = [(list(y) + [None] * rows)[:rows] for y in ys]

    if opt.get("excludeIncompleteRows"):  # only the rows where every variable has a value
        keep = [all(ok(y[r]) for y in ys) for r in range(rows)]
        ys = [[v if keep[r] else None for r, v in enumerate(y)] for y in ys]
    res = [[None] * k for _ in range(k)]
    for i in range(k):
        for j in range(i, k):
            if i == j:
                n = float(sum(1 for v in ys[i] if ok(v)))
                p0 = _p(0.0, alpha)
                v = {"status": "PERFECT_LINE", "n": n, "r": 1.0}
                if not spear:
                    v["r2"] = 1.0
                v["rCI"] = {"lower": 1.0, "upper": 1.0, "level": level}
                v["pValue"] = p0
                if spear:
                    v["pValueExact"], v["pValueApproximate"] = dict(p0), dict(p0)
            else:
                v = fn(ys[i], ys[j], level, alpha)
                if one_tail:
                    for key in ("pValue", "pValueExact", "pValueApproximate"):
                        if isinstance(v.get(key, {}).get("value"), float):
                            v[key] = _p(v[key]["value"] / 2, alpha)
            res[i][j] = res[j][i] = v
    key = "spearmanTestModel" if spear else "pearsonTestModel"

    def ident(i):
        return {"col": {"title": names[i], "idx": idx[i]}}

    out = {key: {f"col{idx[i]}": {"id": ident(i), "value": {f"col{idx[j]}": {"id": ident(j), "value": res[i][j]}
                                                       for j in range(i, k)}} for i in range(k)}}

    def matrix(cell):
        return {"columns": list(names), "row_titles": list(names),
                "rows": [[cell(i, j) for j in range(k)] for i in range(k)]}

    tables = {"Spearman r" if spear else "Pearson r": matrix(lambda i, j: res[i][j]["r"]),
              "P values": matrix(lambda i, j: None if i == j else res[i][j]["pValue"]["value"])}
    if spear:
        tables["P value type"] = matrix(lambda i, j: "" if i == j else (
            "Exact" if isinstance(res[i][j].get("pValueExact", {}).get("value"), float) else "Approximate"))
    tables["Sample size"] = matrix(lambda i, j: res[i][j]["n"])
    tables["Confidence interval of rs" if spear else "Confidence interval of r"] = \
        matrix(lambda i, j: "" if i == j else _ci_text(res[i][j]["rCI"]))
    return {"status": {"error": "VALID", "warning": []}, **out, "_tables": tables}
