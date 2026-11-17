"""Mixed-effects (REML) fits for repeated measures with missing values:
unit tests and Prism parity (tools/mixed_parity.py -> corpus/auto/mx1;
skipped when absent)."""

import json
import math
import os
import sys

import numpy as np
import pytest

from refract.stats import engine
from refract.stats import mixed as MX

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "tools"))


def test_reml_random_intercept_balanced_matches_anova():
    # balanced complete data: REML variance components equal the ANOVA (method of moments) estimates
    rng = np.random.default_rng(2)
    k, n = 3, 8
    subj = rng.normal(0, 2, n)
    cols = [[float(10 + j + subj[s] + rng.normal()) for s in range(n)] for j in range(k)]
    x = np.array(cols).T
    ms_e = float(((x - x.mean(1, keepdims=True) - x.mean(0) + x.mean()) ** 2).sum() / ((n - 1) * (k - 1)))
    ms_s = float(k * ((x.mean(1) - x.mean()) ** 2).sum() / (n - 1))
    r = MX.one_way_mixed([c for c in np.array(x).T.tolist()])
    re = r["repeatedMeasuresRemlAnovaModel"]["randomEffects"]
    assert math.isclose(re["residual"]["variance"], ms_e, rel_tol=1e-6)
    assert math.isclose(re["matchedFactor"]["variance"], (ms_s - ms_e) / k, rel_tol=1e-6)


def test_engine_uses_mixed_model_when_values_are_missing():
    with open(os.path.join(ROOT, "corpus", "seeds", "twoway_params.json")) as f:
        params = json.load(f)
    params["experimentalDesign"] = "REPEATED_MEASURES_BY_ROWS"
    params["postTests"]["type"] = "NO_TESTS"
    rng = np.random.default_rng(4)
    subj = rng.normal(0, 3, (2, 4))
    cols = [[[float(10 + r + c + subj[c, s] + rng.normal()) for r in range(3)] for s in range(4)] for c in range(2)]
    cols[0][1][2] = None
    out = engine.compute("TWO_WAY_ANOVA", params, cols, ["A", "B"], ["R1", "R2", "R3"])
    m = out["repeatedMeasuresRemlAnovaModel"]
    assert "MISSING_VALUES" in out["status"]["warning"]
    # legacy df: within-subject stratum (3 - 1) * (8 - 2) loses the missing value
    assert m["fixedEffects"]["rowFactor"]["fTest"]["dfDenominator"] == pytest.approx(
        11 * m["fixedEffects"]["rowFactor"]["ggEpsilon"])
    assert m["dataSummary"]["missingCount"] == 1


def test_mixed_parity_with_prism():
    path = os.path.join(ROOT, "corpus", "auto", "mx1", "results.json")
    if not os.path.exists(path):
        pytest.skip("Prism parity results not present")
    import mixed_parity as P

    with open(path) as f:
        res = json.load(f)
    acc, _ = P.compare_all(P.gen_ow(10), P.gen_tw(10), res)
    bad = {k: max(v) for k, v in acc.items()
           if max(v) > 1e-5 and not (k.split("/")[0] in P.KNOWN_CONFIGS and "multipleComparisons/tests" in k)}
    assert not bad, bad
    assert len(acc) > 1300
