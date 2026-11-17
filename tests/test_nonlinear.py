"""Nonlinear regression: equation parser, fits, and Prism parity
(tools/nonlinear_parity.py -> corpus/auto/nl2; skipped when absent)."""

import json
import math
import os
import sys

import numpy as np
import pytest

from refract.stats import engine
from refract.stats.equation import EquationError, Model, expression

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "tools"))


def test_equation_language():
    m = Model("Y=Bottom + (Top-Bottom)/(1+10^((LogEC50-X)*HillSlope))", ["Bottom", "Top", "LogEC50", "HillSlope"])
    assert math.isclose(float(m(np.array([-6.0]), [0, 100, -6, 1])[0]), 50.0)
    assert float(Model("Y=-X^2", [])(np.array([3.0]), [])[0]) == -9.0  # ^ binds tighter than unary minus
    m2 = Model("k = ln(2)/Half\nY = A*exp(-k*X)", ["A", "Half"])  # intermediate variable
    assert math.isclose(float(m2(np.array([2.0]), [8, 2])[0]), 4.0)
    assert math.isclose(float(Model("Y = IF(X<0, 0, X)", [])(np.array([-1.0, 2.0]), [])[1]), 2.0)
    assert math.isclose(float(expression("10^logEC50", ["LogEC50"])(np.array([-6.0]))), 1e-6)
    with pytest.raises(EquationError):
        Model("Y = __import__('os')", [])


def test_straight_line_fit_matches_least_squares():
    with open(os.path.join(ROOT, "corpus", "seeds", "nonlinear_params.json")) as f:
        params = json.load(f)
    with open(os.path.join(ROOT, "corpus", "seeds", "nonlinear_equations.json")) as f:
        params["model"]["equation"] = json.load(f)["Straight line"]["equation"]
    params["model"]["initialValues"] = {}
    params["confidence"]["ciMethod"] = "WALD"
    x = [0.0, 1, 2, 3, 4, 5]
    y = [[1.1, 2.9, 5.2, 6.8, 9.1, 11.0]]
    r = engine.compute("NONLINEAR_REGRESSION", params, [y], ["A"], x_values=x)
    pars = r["models"]["col0"]["value"]["parameters"]
    slope, icpt = np.polyfit(x, y[0], 1)
    assert math.isclose(pars["Slope"]["estimate"], slope, rel_tol=1e-9)
    assert math.isclose(pars["YIntercept"]["estimate"], icpt, rel_tol=1e-9)


def test_nonlinear_parity_with_prism():
    path = os.path.join(ROOT, "corpus", "auto", "nl2", "results.json")
    if not os.path.exists(path):
        pytest.skip("Prism parity results not present")
    import nonlinear_parity as P

    with open(path) as f:
        res = json.load(f)
    cfgs = [*P.CONFIGS, ("wald", {**P.DIAG_ALL, "confidence/ciMethod": "WALD"})]
    acc, _ = P.compare_all(P.gen(14), res, cfgs)
    bad = {k: max(v) for k, v in acc.items() if max(v) > P.CONVERGENCE_TOL}
    assert len(acc) > 700
    assert not bad, bad


def test_rout_eliminates_a_planted_outlier():
    with open(os.path.join(ROOT, "corpus", "seeds", "nonlinear_params.json")) as f:
        params = json.load(f)
    with open(os.path.join(ROOT, "corpus", "seeds", "nonlinear_equations.json")) as f:
        params["model"]["equation"] = json.load(f)["Straight line"]["equation"]
    params["model"]["initialValues"] = {}
    params["method"]["outliers"] = {"method": "ELIMINATE", "q": 1.0}
    rnd = np.random.default_rng(4)
    x = [float(i) for i in range(12)]
    y = [2 + 0.5 * v + float(rnd.normal(0, 0.2)) for v in x]
    y[5] += 8.0
    r = engine.compute("NONLINEAR_REGRESSION", params, [[y]], ["A"], x_values=x)
    o = r["outliers"]["col0"]["value"]
    assert o["outliersCount"] == 1 and o["outliersList"][0]["id"] == [0, 5, 0]
    fit = r["models"]["col0"]["value"]
    assert fit["dataSummary"]["yValuesAnalyzed"] == 12 and fit["dataSummary"]["outliersCount"] == 1
    clean = [v for i, v in enumerate(y) if i != 5]
    slope, _ = np.polyfit([v for i, v in enumerate(x) if i != 5], clean, 1)
    assert math.isclose(fit["parameters"]["Slope"]["estimate"], slope, rel_tol=1e-9)


def test_rout_and_robust_parity_with_prism():
    path = os.path.join(ROOT, "corpus", "auto", "nlo1", "results.json")
    if not os.path.exists(path):
        pytest.skip("Prism parity results not present")
    import nl_outlier_parity as P

    with open(path) as f:
        res = json.load(f)
    acc, _ = P.compare_all(P.gen(), res)
    assert len(acc) > 500
    outl = {k: max(v) for k, v in acc.items() if "/outliers/" in k}
    assert outl and max(outl.values()) == 0.0  # ROUT decisions: exact
    bad = {k: max(v) for k, v in acc.items() if max(v) > P.CONVERGENCE_TOL}
    assert not bad, bad
