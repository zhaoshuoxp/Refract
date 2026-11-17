"""Nonlinear model comparison and global (shared-parameter) fits: Prism's own
sample (corpus/manual/batch4_samples.prism) and the parity run
(tools/nl_compare_parity.py -> corpus/auto/nlc1); skipped when absent."""

import json
import math
import os
import sys

import pytest
from scipy import stats

from refract.stats import nonlinear_global as NG

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "tools"))


def _params(eq, cons=None, mc=None):
    with open(os.path.join(ROOT, "corpus", "seeds", "nonlinear_params.json")) as f:
        p = json.load(f)
    with open(os.path.join(ROOT, "corpus", "seeds", "nonlinear_equations.json")) as f:
        eqs = json.load(f)
    p["model"] = {"equation": eqs[eq]["equation"], "constraints": cons or {}, "initialValues": {}}
    p["confidence"]["ciMethod"] = "WALD"
    if mc:
        mc["modelToCompare"] = {"equation": eqs[mc.pop("eq", eq)]["equation"], "constraints": mc.pop("cons", {}),
                                "initialValues": {}}
        p["modelComparison"] = {**p["modelComparison"], **mc}
    return p


X = [0.0, 1, 2, 3, 4, 5, 6, 7]
A = [[1.0, 1.6, 2.4, 2.9, 3.6, 4.4, 5.1, 5.5]]
B = [[2.0, 2.4, 3.3, 3.6, 4.5, 4.9, 5.8, 6.1]]


def test_shared_slope_f_test_by_hand():
    import numpy as np

    p = _params("Straight line", mc={"type": "SHARED_PARAMETERS", "method": "STAT_TEST",
                                     "options": {"sharedParameters": ["Slope"]},
                                     "cons": {"Slope": {"type": "SHARE", "value": "undefined"}}})
    out = NG.analysis(p, X, [A, B], ["A", "B"], "y_single")
    f = out["modelComparison"]["global"]["value"]["fTest"]
    ss_sep = sum(float(((np.polyval(np.polyfit(X, y[0], 1), X) - y[0]) ** 2).sum()) for y in (A, B))
    # common slope, separate intercepts: ordinary least squares with dummies
    xx = np.array(X * 2)
    d = np.r_[np.zeros(8), np.ones(8)]
    m = np.c_[xx, 1 - d, d]
    yy = np.r_[A[0], B[0]]
    beta = np.linalg.lstsq(m, yy, rcond=None)[0]
    ss_sh = float(((m @ beta - yy) ** 2).sum())
    assert f["simpleModel"]["ss"] == pytest.approx(ss_sh) and f["complexModel"]["ss"] == pytest.approx(ss_sep)
    fv = (ss_sh - ss_sep) / (ss_sep / 12)
    assert f["summary"]["f"] == pytest.approx(fv)
    assert f["summary"]["pValue"]["value"] == pytest.approx(stats.f.sf(fv, 1, 12))
    g = out["models"]["Model 2|global"]["value"]
    assert g["parameters"]["Slope"]["shared"]["estimate"] == pytest.approx(beta[0])
    assert g["parameters"]["Slope"]["shared"]["dsList"] == [0, 1]
    assert g["modelDescription"] == "Slope same for all data sets"


def test_equal_df_gives_no_test():
    p = _params("Straight line", mc={"type": "TWO_MODLES", "method": "STAT_TEST"})
    f = NG.analysis(p, X, [A], ["A"], "y_single")["modelComparison"]["col0"]["value"]["fTest"]
    assert f["status"] == "MODELS_EQUAL_DF" and f["summary"]["f"] == "undefined"
    assert f["preferredModelName"] == "Equation 1"


def test_aic_probabilities():
    p = _params("Straight line", mc={"type": "CONSTRAINED_PARAMETER", "method": "AIC_TEST",
                                     "options": {"parameterName": "Slope", "hypoteticalValue": 0.6},
                                     "cons": {"Slope": {"type": "CONST", "value": 0.6}}})
    a = NG.analysis(p, X, [A], ["A"], "y_single")["modelComparison"]["col0"]["value"]["aicTest"]
    assert a["simpleModel"]["name"] == "Slope = 0.6" and a["complexModel"]["name"] == "Slope unconstrained"
    assert a["simpleModel"]["probability"] + a["complexModel"]["probability"] == pytest.approx(1.0)
    assert a["simpleModel"]["probability"] == pytest.approx(1 / (1 + math.exp(a["summary"]["aicDifference"] / 2)))


def test_matches_prism_sample():
    import nl_compare_parity as P

    if not os.path.exists(P.SAMPLE):
        pytest.skip("Prism sample not present")
    acc, missing = P.sample_check()
    assert len(acc) > 900 and not missing
    comp = {k: max(v) for k, v in acc.items() if "/modelComparison/" in k}
    assert comp and max(comp.values()) <= 1e-6
    # the rest: Prism's convergence on 4-parameter and weakly determined global fits
    assert max(max(v) for v in acc.values()) <= P.CONVERGENCE_TOL * 2


def test_parity_with_prism():
    path = os.path.join(ROOT, "corpus", "auto", "nlc1", "results.json")
    if not os.path.exists(path):
        pytest.skip("Prism parity results not present")
    import nl_compare_parity as P

    with open(path) as f:
        res = json.load(f)
    acc, _ = P.compare_all(P.gen(), res)
    bad = {k: max(v) for k, v in acc.items() if max(v) > P.CONVERGENCE_TOL}
    assert not bad, bad
