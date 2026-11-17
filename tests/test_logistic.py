"""Simple logistic regression: unit tests and Prism parity
(tools/logistic_parity.py -> corpus/auto/lg1; skipped when absent)."""

import json
import math
import os
import sys

import numpy as np
import pytest

from refract.stats import logistic as LG

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "tools"))
PARAMS = {"calc": {"rocCurve": True, "r2CS": True, "r2TJ": True, "deviance": True, "likelihoodRatioTest": True},
          "options": {"confidenceLevel": 95.0}}


def test_ml_fit_score_equations_vanish():
    x = np.array([0.5, 1, 1.5, 2, 2.5, 3, 3.5, 4, 4.5, 5])
    y = np.array([0, 0, 1, 0, 0, 1, 0, 1, 1, 1], float)
    b, ll, _ = LG.fit(x, y)
    p = 1 / (1 + np.exp(-(b[0] + b[1] * x)))
    assert abs((y - p).sum()) < 1e-10 and abs((x * (y - p)).sum()) < 1e-10
    r = LG.simple_logistic(PARAMS, x.tolist(), y.tolist())["models"]["col0"]["value"]
    lo, hi = r["model"]["parameters"]["β1"]["ci"]["lower"], r["model"]["parameters"]["β1"]["ci"]["upper"]
    # profile-likelihood limits: the log-likelihood drops by chi2(0.95, 1) / 2 there
    for v in (lo, hi):
        assert math.isclose(LG.fit(x, y, {1: v}, start=b)[1], ll - 3.841458820694124 / 2, abs_tol=1e-8)


def test_complete_separation_is_not_converged():
    r = LG.simple_logistic(PARAMS, [1, 2, 3, 4], [0, 0, 1, 1])
    assert r["status"]["warning"] == ["NOT_CONVERGED"]
    assert r["models"]["col0"]["value"]["model"]["status"] == "INTERRUPTED"


def test_logistic_parity_with_prism():
    path = os.path.join(ROOT, "corpus", "auto", "lg1", "tables.json")
    if not os.path.exists(path):
        pytest.skip("Prism parity results not present")
    import logistic_parity as P

    with open(path) as f:
        res = json.load(f)
    acc, _ = P.compare_all(P.gen(), res)
    bad = {k: max(v) for k, v in acc.items() if max(v) > 1e-8}
    assert not bad, bad
