"""Survival analysis: unit tests and Prism parity (tools/survival_parity.py,
corpus/auto/sv1; skipped when absent)."""

import json
import math
import os
import sys

import numpy as np
import pytest
from scipy import stats

from refract.stats import survival as SV

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "tools"))
PARAMS = {"data": {"eventCode": 1, "censorCode": 0},
          "calc": {"logrankTest": True, "twoGroupsGehanBreslowWilcoxonTest": True, "logrankTestForTrend": True, "ciLevel": 95.0}}


def test_kaplan_meier_and_median_rules():
    t = np.array([1.0, 2, 3, 4, 5, 6])
    e = np.array([1, 1, 1, 1, 1, 1])
    km = SV.kaplan_meier(t, e)
    assert [round(r[4], 6) for r in km] == [round(1 - i / 6, 6) for i in range(1, 7)]
    med, _, _ = SV.median_survival(km, 1.96)
    assert med == 3.5  # S = 0.5 exactly at t = 3: average with the next event time (Prism)
    km2 = SV.kaplan_meier(np.array([1.0, 2, 3]), np.array([1, 0, 0]))
    assert SV.median_survival(km2, 1.96)[0] == math.inf


def test_logrank_two_groups_against_chi2_formula():
    x = [5, 8, 12, 3, 9, 14, 7, 10]
    g1 = [1, 1, 0, None, None, None, None, None]
    g2 = [None, None, None, 1, 1, 0, 1, 1]
    r = SV.survival(PARAMS, x, [g1, g2], ["A", "B"])
    chi = r["curveComparison"]["logrankMantelCoxTest"]["chiSquared"]
    assert math.isclose(r["curveComparison"]["logrankMantelCoxTest"]["pValue"]["value"], stats.chi2.sf(chi, 1))
    hr = r["ratios"]["ratio"]["value"]["logrankHazardRatio"]
    assert math.isclose(hr * r["ratios"]["ratioReciprocal"]["value"]["logrankHazardRatio"], 1.0)


def test_survival_parity_with_prism():
    path = os.path.join(ROOT, "corpus", "auto", "sv1", "results.json")
    if not os.path.exists(path):
        pytest.skip("Prism parity results not present")
    import survival_parity as P

    with open(path) as f:
        acc, missing = P.compare_all(P.gen(16), json.load(f))
    assert not missing, dict(missing)
    bad = {k: max(v) for k, v in acc.items() if max(v) > 1e-9}
    assert not bad, bad
