"""Correlation, simple linear regression and contingency tables: unit tests
and Prism parity (tools/xy_parity.py -> corpus/auto/xy2,
tools/contingency_parity.py -> corpus/auto/ct2; skipped when absent)."""

import json
import math
import os
import sys

import numpy as np
import pytest
from scipy import stats

from refract.stats import contingency as CT
from refract.stats import engine
from refract.stats import xy_basic as XB

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "tools"))


def _seed(name):
    with open(os.path.join(ROOT, "corpus", "seeds", name)) as f:
        return json.load(f)


def test_pearson_and_spearman_against_scipy():
    rnd = np.random.default_rng(3)
    x = rnd.normal(size=20).tolist()
    y = (np.array(x) * 0.6 + rnd.normal(size=20)).tolist()
    p = XB.pearson(x, y)
    r, pv = stats.pearsonr(x, y)
    assert math.isclose(p["r"], r, rel_tol=1e-12) and math.isclose(p["pValue"]["value"], pv, rel_tol=1e-9)
    s = XB.spearman(x, y)
    assert math.isclose(s["r"], stats.spearmanr(x, y)[0], rel_tol=1e-12)
    assert s["pValueExact"]["value"] == "undefined"  # n > 17: approximate P only
    small = XB.spearman(x[:8], y[:8])
    assert small["rCI"]["lower"] == "undefined"  # no Spearman CI below SPEARMAN_CI_MIN_N


def test_linear_regression_line_and_x_intercept():
    x = [1.0, 2, 3, 4, 5, 6]
    y = [[2.1, 3.9, 6.2, 7.8, 10.1, 12.0]]
    r = engine.compute("SIMPLE_LINEAR_REGRESSION", {"calc": {"xCI": {"enabled": True, "y": 0.0}}}, [y], ["A"], x_values=x)
    m = r["models"]["col0"]["value"]["model"]
    fit = stats.linregress(x, y[0])
    assert math.isclose(m["parameters"]["Slope"]["estimate"], fit.slope, rel_tol=1e-12)
    assert math.isclose(m["parameters"]["Y-intercept"]["estimate"], fit.intercept, rel_tol=1e-12)
    xi = m["parameters"]["X-intercept"]
    assert math.isclose(xi["estimate"], -fit.intercept / fit.slope, rel_tol=1e-12)
    assert xi["ci"]["lower"] < xi["estimate"] < xi["ci"]["upper"]


def test_contingency_2x2_against_scipy():
    params = _seed("contingency_table_params.json")
    for k in ("relativeRisk", "differenceBetweenProportions", "oddsRatio", "proportions"):
        params["calc"][k]["calculate"] = True
    t = [[11, 57], [39, 54]]
    r = CT.contingency(params, t)
    assert math.isclose(r["fisherExactTest"]["pValue"]["value"], stats.fisher_exact(t)[1], rel_tol=1e-12)
    orm = r["oddsRatioModel"]["oddsRatio"]
    assert math.isclose(orm["value"], 11 * 54 / (57 * 39))
    # Prism 11.1 values for this table (corpus/auto/ct_enum1)
    assert math.isclose(orm["ci"]["lower"], 0.12318059919417604, rel_tol=1e-9)
    assert math.isclose(orm["ci"]["upper"], 0.5694492110192668, rel_tol=1e-9)
    ar = r["proportionsDifferenceModel"]["attributableRisk"]["ci"]  # |p1 - p2| = 0.2576
    assert math.isclose(ar["lower"], 0.12735605333084338, rel_tol=1e-9)
    assert math.isclose(ar["upper"], 0.4089502077419197, rel_tol=1e-9)


@pytest.mark.parametrize(("tool", "folder", "label"), [("xy_parity", "xy2", "xy"), ("contingency_parity", "ct2", "ct")])
def test_parity_with_prism(tool, folder, label):
    path = os.path.join(ROOT, "corpus", "auto", folder, "results.json")
    if not os.path.exists(path):
        pytest.skip("Prism parity results not present")
    mod = __import__(tool)
    with open(path) as f:
        res = json.load(f)
    out = mod.compare_all(mod.gen(18 if label == "xy" else 16), res)
    acc = out[0]
    bad = {k: max(v) for k, v in acc.items() if max(v) > 1e-9}
    assert not bad, bad


def test_fisher_freeman_halton_small_table():
    # brute force over all 2 x 3 tables with the margins of [[3, 1, 2], [1, 4, 2]]
    import itertools

    from scipy.special import gammaln

    t = np.array([[3, 1, 2], [1, 4, 2]])
    rows, cols = t.sum(1), t.sum(0)

    def lp(m):
        return gammaln(rows + 1).sum() + gammaln(cols + 1).sum() - gammaln(t.sum() + 1) - gammaln(m + 1).sum()

    obs, p = lp(t), 0.0
    for x0, x1 in itertools.product(range(cols[0] + 1), range(cols[1] + 1)):
        x2 = rows[0] - x0 - x1
        if 0 <= x2 <= cols[2]:
            m = np.array([[x0, x1, x2], [cols[0] - x0, cols[1] - x1, cols[2] - x2]])
            if lp(m) <= obs + 1e-7:
                p += math.exp(lp(m))
    assert math.isclose(CT.fisher_rxc(t), p, rel_tol=1e-12)


def test_wilson_brown_end_corrections():
    z = stats.norm.ppf(0.975)
    lo, hi = CT.wilson_brown(1, 5, z, 0.05)
    assert math.isclose(lo, stats.chi2.ppf(0.05, 2) / 10)
    assert math.isclose(hi, CT.wilson(1, 5, z)[1])
    assert CT.wilson_brown(3, 14, z, 0.05) == CT.wilson(3, 14, z)
