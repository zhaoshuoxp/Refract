"""Multiple two-sample tests (MULTIPLE_TWO_SAMPLE_TESTS).

Unit tests use SciPy cross-checks; parity tests compare with full-precision
results Prism computed locally (tools/multi_t_parity.py, corpus/auto/mt1, mt2);
they skip when those results are absent.
"""

import json
import math
import os
import sys

import pytest
from scipy import stats

from refract.stats import multiple_t as MT
from refract.stats.engine import compute

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "tools"))

A = [[10.1, 12.0, 9.5], [11.2, 12.5, 9.9], [10.8, 11.7, 10.2]]  # [subcolumn][row]
B = [[12.3, 12.1, 13.0], [13.1, 12.9, 12.2], [12.8, 13.4, 12.6]]


def _params(test, **mc):
    """Minimal parameters (the corpus seed is git-ignored)."""
    base = {"test": test, "options": {"swapDirection": False},
            "multipleComparisons": {"type": "NO_CORRECTION", "noCorrection": {"options": {"significanceLevel": 0.05}}}}
    base["multipleComparisons"].update(mc)
    return base


def test_equal_and_unequal_sd_match_scipy():
    for test, eq in (("MULTIPLE_UNPAIRED_TWO_SAMPLE_EQUAL_SD_TESTS", True), ("MULTIPLE_UNPAIRED_TWO_SAMPLE_UNEQUAL_SD_TESTS", False)):
        r = MT.multiple_t(_params(test), A, B, ["r1", "r2", "r3"])
        for i in range(3):
            row = next(iter(r["rows"][f"row{i}"]["value"].values()))
            ref = stats.ttest_ind([s[i] for s in A], [s[i] for s in B], equal_var=eq)
            assert math.isclose(row["unpairedTTest"]["pValue"]["value"], ref.pvalue, rel_tol=1e-10)


def test_validity_rules_and_ranks():
    a = [[1.0, 5.0], [None, 6.0]]  # row 0: one value in A
    b = [[2.0, 7.0], [3.0, 8.0]]
    eq = MT.multiple_t(_params("MULTIPLE_UNPAIRED_TWO_SAMPLE_EQUAL_SD_TESTS"), a, b, ["r1", "r2"])
    assert eq["summary"]["validTestCount"] == 2  # n1 + n2 >= 3 suffices for the pooled test
    welch = MT.multiple_t(_params("MULTIPLE_UNPAIRED_TWO_SAMPLE_UNEQUAL_SD_TESTS"), a, b, ["r1", "r2"])
    blk = welch["rows"]["row0"]["value"]["unpairedUnequalSDTTestModel"]["unpairedTTest"]
    assert blk["status"] == "TOO_FEW_POINTS" and blk["t"] == "undefined"
    ranks = sorted(next(iter(v["value"].values()))["unpairedTTest"]["pValue"]["rank"] for v in eq["rows"].values())
    assert ranks == [0, 1]


def test_corrections_thresholds():
    ps = [0.001, 0.02, 0.04, 0.3]
    bonf = MT.correct(ps, {"type": "STATISTICAL", "statistical": {"test": "BONFERRONI_DUNN", "options": {"significanceLevel": 0.05}}})
    assert bonf["threshold"] == 0.05 / 4 and bonf["adjusted"][0] == 0.004
    bh = MT.correct(ps, {"type": "FDR", "fdr": {"test": "BENJAMINI_HOCHBERG", "options": {"discoveryLevel": 5.0}}})
    assert bh["name"].startswith("Original FDR") and math.isclose(bh["threshold"], 0.05 * 2 / 4)  # 2 discoveries
    none = MT.correct([0.5], {"type": "FDR", "fdr": {"test": "BENJAMINI_HOCHBERG", "options": {"discoveryLevel": 5.0}}})
    assert none["threshold"] == "undefined"


def test_engine_entry():
    cols = [A, B]
    r = compute("MULTIPLE_TWO_SAMPLE_TESTS", _params("MULTIPLE_PAIRED_TWO_SAMPLE_TESTS"), cols, ["A", "B"], ["r1", "r2", "r3"])
    assert r["summary"]["validTestCount"] == 3


@pytest.mark.parametrize("folder,n", [("mt1", 10), ("mt2", 12)])
def test_multiple_t_parity_with_prism(folder, n):
    path = os.path.join(ROOT, "corpus", "auto", folder, "results.json")
    if not os.path.exists(path):
        pytest.skip("Prism parity results not present")
    import multi_t_parity as P

    with open(path) as f:
        acc, missing = P.compare_all(P.gen(n), json.load(f))
    assert not [k for k in missing if not k.startswith("known:")], missing
    bad = {k: max(v) for k, v in acc.items() if max(v) > 2e-9}
    assert not bad, bad
