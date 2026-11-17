"""Compare an observed distribution with the expected one (Prism: CHI2),
verified against Prism 11.1 (E-stats8e).

One column of counts (data.datasetID), one outcome per row. The expected
values are calc.outcomes' expectedCount (data.expectedValuesType COUNTS) or
expectedPercentage of the observed total (PERCENTAGES); when they do not add
up to the total (or 100 %), Prism still computes, with the status
INVALID_PARAMETER_EXPECTED_COUNTS / _PERCENTAGES.

  * CHI_SQUARE_TEST: sum (O - E)^2 / E, df = outcomes - 1.
  * BINOMIAL_TEST (two outcomes): the exact binomial test of the first
    outcome's count, one-tailed in the direction observed, two-tailed by
    adding the outcomes no more likely than the one observed; each observed
    percentage with its interval (calc.ciMethod Wilson/Brown or
    Clopper-Pearson, 95 %).
"""

from __future__ import annotations

import math

from scipy import stats

from .roc import _prop_ci


def _p(v: float, alpha: float = 0.05) -> dict:
    return {"value": float(v), "level": alpha, "isSignificant": bool(v < alpha), "state": "P_VALUE_EQUAL"}


def observed_expected(params: dict, columns: list) -> dict:
    data, calc = params.get("data", {}), params.get("calc", {})
    i = (data.get("datasetID") or {}).get("col", {}).get("idx", 0)
    col = columns[i] if 0 <= i < len(columns) else (columns[0] if columns else [])
    obs = [float(v) for v in col if v is not None and math.isfinite(v)]
    outs = calc.get("outcomes") or []
    n = sum(obs)
    pct = data.get("expectedValuesType", "COUNTS") == "PERCENTAGES"
    exp = []
    for k in range(len(obs)):
        o = outs[k] if k < len(outs) else {}
        if pct:
            exp.append(n * float(o.get("expectedPercentage") or 0.0) / 100)
        else:
            exp.append(float(o.get("expectedCount") or 0.0))
    status = "VALID"
    if pct and not math.isclose(sum(float((outs[k] if k < len(outs) else {}).get("expectedPercentage") or 0)
                                    for k in range(len(obs))), 100.0, abs_tol=1e-6):
        status = "INVALID_PARAMETER_EXPECTED_PERCENTAGES"
    if not pct and not math.isclose(sum(exp), n, abs_tol=1e-6):
        status = "INVALID_PARAMETER_EXPECTED_COUNTS"
    test = calc.get("test", "CHI_SQUARE_TEST")
    out: dict = {"status": {"error": status, "warning": []}}
    rows = {}
    for k, (o, e) in enumerate(zip(obs, exp, strict=True)):
        rows[f"row{k}"] = {"id": {"row": {"idx": k}},
                           "value": {"observedCount": o, "expectedCount": e, "observedPercentage": 100 * o / n,
                                     "expectedPercentage": 100 * e / n}}
    if test == "CHI_SQUARE_TEST":
        chi = sum((o - e) ** 2 / e for o, e in zip(obs, exp, strict=True) if e)
        df = len(obs) - 1
        out["chiSquareTest"] = {"status": "VALID", "chiSquared": chi, "df": float(df),
                                "pValueTwoTailed": _p(stats.chi2.sf(chi, df))}
    elif test == "BINOMIAL_TEST":
        if len(obs) != 2:
            raise NotImplementedError("a binomial test of more than two outcomes")
        x, m = round(obs[0]), round(obs[0] + obs[1])
        p0 = exp[0] / (exp[0] + exp[1])
        side = "less" if x < m * p0 else "greater"
        out["binomialTest"] = {"status": "VALID",
                               "pValueOneTailed": _p(stats.binomtest(x, m, p0, alternative=side).pvalue),
                               "pValueTwoTailed": _p(stats.binomtest(x, m, p0).pvalue)}
        method = "CLOPPER_PEARSON" if "CLOPPER" in calc.get("ciMethod", "") else "WILSON_BROWN"
        z = stats.norm.ppf(0.975)
        for k, o in enumerate(obs):
            lo, hi = _prop_ci(method, round(o), m, z, 0.05)
            rows[f"row{k}"]["value"]["ciOfObserved"] = {"lower": 100 * lo, "upper": 100 * hi, "level": 0.05}
    else:
        raise NotImplementedError(f"test {test}")
    out["outcomes"] = rows
    out["total"] = {"observedCount": n, "expectedCount": sum(exp), "observedPercentage": 100.0,
                    "expectedPercentage": 100.0}
    return out
