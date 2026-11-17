"""Two-way ANOVA tests.

Unit tests use classical balanced-design identities. Parity tests compare with
full-precision results Prism computed locally (tools/twoway_parity.py writes
corpus/auto/tw1 and tw2/results.json); they skip when those results are absent.
"""

import json
import math
import os
import sys

import numpy as np
import pytest

from refract.stats import two_way as TW
from refract.stats.engine import compute

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "tools"))

RNG = np.random.default_rng(4)
CELLS = [[list(np.round(RNG.normal(10 + r + 2 * c, 1.0, 4), 3)) for c in range(3)] for r in range(2)]


def test_balanced_ordinary_matches_classical_formulas():
    y = np.array(CELLS)  # rows x cols x reps
    gm = y.mean()
    ss_r = y.shape[1] * y.shape[2] * ((y.mean(axis=(1, 2)) - gm) ** 2).sum()
    ss_c = y.shape[0] * y.shape[2] * ((y.mean(axis=(0, 2)) - gm) ** 2).sum()
    ss_e = ((y - y.mean(axis=2, keepdims=True)) ** 2).sum()
    t = TW.ordinary(CELLS)["ordinaryAnovaModel"]["anovaTable"]
    assert math.isclose(t["rowFactor"]["ss"], ss_r, rel_tol=1e-10)
    assert math.isclose(t["colFactor"]["ss"], ss_c, rel_tol=1e-10)
    assert math.isclose(t["residual"]["ss"], ss_e, rel_tol=1e-10)
    total = sum(t[k]["ss"] for k in ("rowFactor", "colFactor", "rowFactorVsColFactor", "residual"))
    assert math.isclose(total, t["total"]["ss"], rel_tol=1e-10)


def test_empty_cell_drops_interaction():
    cells = [row[:] for row in CELLS]
    cells[0] = [cells[0][0], [], cells[0][2]]
    t = TW.ordinary(cells)["ordinaryAnovaModel"]["anovaTable"]
    assert "rowFactorVsColFactor" not in t


def test_rm_designs_partition_total_ss():
    for fn in (TW.rm_by_rows, TW.rm_by_cols):
        m = fn(CELLS)["repeatedMeasuresGlmAnovaModel"]
        assert 0 < m["anovaTable"]["rowFactor"]["fTest"]["pValue"]["value"] <= 1
    both = TW.rm_by_both(CELLS)["repeatedMeasuresGlmAnovaModel"]["anovaTable"]
    y = np.array(CELLS)
    ss_t = ((y - y.mean()) ** 2).sum()
    ss_subj = 6 * ((y.mean(axis=(0, 1)) - y.mean()) ** 2).sum()
    parts = sum(v["ss"] for v in both.values()) + ss_subj
    assert math.isclose(parts, ss_t, rel_tol=1e-10)
    for k, p in (("rowFactor", 1), ("colFactor", 2), ("rowFactorVsColFactor", 2)):
        assert 1 / p - 1e-12 <= both[k]["ggEpsilon"] <= 1 + 1e-12  # GG lower bound 1/(levels-1)


def test_lsmeans_equal_mean_of_cell_means():
    cells = [row[:] for row in CELLS]
    cells[1][2] = cells[1][2][:2]  # unbalanced
    items = [({}, (None, c)) for c in range(3)]
    est, cov = TW.lsmeans(cells, items, True)
    cm = np.array([[np.mean(cells[r][c]) for c in range(3)] for r in range(2)])
    assert np.allclose(est, cm.mean(axis=0))
    assert math.isclose(cov[2, 2], (1 / 4 + 1 / 2) / 4, rel_tol=1e-10)


def test_engine_column_layout():
    import twoway_parity as T

    cols = [[[CELLS[r][c][s] for r in range(2)] for s in range(4)] for c in range(3)]
    r = compute("TWO_WAY_ANOVA", T.params(T.ORD, "COMPARE_COLUMNS", "ALL_VS_ALL", "STATISTICAL", "TUKEY"), cols)
    mc = r["ordinaryAnovaModel"]["multipleComparisons"]
    assert mc["comparisonPerFamilyCount"] == 3 and mc["method"] == "Tukey"


@pytest.mark.parametrize("folder", ["tw1", "tw2"])  # tw2: simple effects
def test_two_way_parity_with_prism(folder):
    path = os.path.join(ROOT, "corpus", "auto", folder, "results.json")
    if not os.path.exists(path):
        pytest.skip("Prism parity results not present")
    import twoway_parity as T

    with open(path) as f:
        acc, missing = T.compare_all(T.gen(12), json.load(f))
    assert not [k for k in missing if not k.startswith("known:")], missing
    bad = {}
    for k, v in acc.items():
        tol = 1e-8 if "meansDifferenceCI" in k else 2e-9
        if "dunnett" in k and "meansDifferenceCI" in k:
            tol = 1e-3  # Prism's Dunnett critical value (see one-way findings)
        if max(v) > tol:
            bad[k] = max(v)
    assert not bad, bad
