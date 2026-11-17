"""ROC curves, area under the curve, nested t test / one-way ANOVA: Prism's
own sample (corpus/manual/batch3_samples.prism) and parity runs
(tools/roc_parity.py -> corpus/auto/roc1, tools/nested_parity.py ->
corpus/auto/ns1); skipped when absent."""

import json
import math
import os
import sys

import pytest

from refract.stats import nested as NS
from refract.stats import roc as RC

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "tools"))


def test_roc_area_and_thresholds():
    p = {"data": {"controlID": {"col": {"idx": 0}}, "patientID": {"col": {"idx": 1}}},
         "options": {"reportResultsAs": "PERCENTAGE", "confidenceMethod": "WILSON_BROWN", "confidenceLevel": 95.0}}
    r = RC.roc_curve(p, [[1.0, 2.0, 3.0], [2.5, 4.0, 5.0]])
    assert math.isclose(r["aucTest"]["area"], 8 / 9)
    first, last = r["sensitivitySpecificity"][0], r["sensitivitySpecificity"][-1]
    assert first["sensitivity"]["value"] == 100.0 and first["specificity"]["value"] == 0.0
    assert last["sensitivity"]["value"] == 0.0 and last["specificity"]["value"] == 100.0


def test_auc_trapezoid_single_peak():
    p = {"calc": {"baseline": {"useSpecificValue": True, "value": 0.0},
                  "peak": {"height": {"definePeakByAmplitudePercentage": True, "minimumAmplitudePercentage": 10.0},
                           "width": {"ignoreNarrowPeak": False}, "calcPositivePeaksOnly": True}}}
    r = RC.area_under_curve(p, [0.0, 1.0, 2.0], [[0.0, 2.0, 0.0]])
    s = r["samples"]["col0"]["value"]
    assert s["summary"]["totalArea"] == 2.0 and s["summary"]["peakCount"] == 1


def test_nested_balanced_matches_anova_estimate():
    groups = [[[1.0, 2, 3], [2, 3, 4]], [[4.0, 5, 6], [6, 7, 8]]]
    r = NS.nested_t({"options": {"swapDirection": False, "significanceLevel": 0.05}}, groups)["tTestModel"]
    assert r["differenceOfMeans"]["difference"] == pytest.approx(2.5 - 6.0)
    assert r["fixedEffects"]["colFactor"]["tTest"]["df"] == 2.0


@pytest.mark.parametrize(("tool", "folder", "tol"), [("roc_parity", "roc1", 1e-9), ("nested_parity", "ns1", 1e-6)])
def test_parity_with_prism(tool, folder, tol):
    path = os.path.join(ROOT, "corpus", "auto", folder, "tables.json")
    if not os.path.exists(path):
        pytest.skip("Prism parity results not present")
    mod = __import__(tool)
    with open(path) as f:
        res = json.load(f)
    out = mod.compare_all(mod.gen_roc(), mod.gen_auc(), res) if tool == "roc_parity" else mod.compare_all(mod.gen(), res)
    bad = {k: max(v) for k, v in out[0].items() if max(v) > tol}
    assert not bad, bad
