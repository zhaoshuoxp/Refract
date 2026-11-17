"""Cox regression: unit tests and Prism parity (tools/cox_parity.py ->
corpus/auto/cx1; skipped when absent)."""

import json
import math
import os
import sys

import numpy as np
import pytest

from refract.stats import cox as CX

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "tools"))


def test_score_vanishes_and_breslow_equals_efron_without_ties():
    rng = np.random.default_rng(1)
    x = rng.normal(size=(40, 2))
    t = rng.exponential(1 / np.exp(x @ [0.5, -0.3]))
    d = (rng.random(40) < 0.7).astype(int)
    b, ll, h = CX.fit(t, d, x)
    _, g, _ = CX.partial_loglik(b, t, d, x, True)
    assert np.abs(g).max() < 1e-9
    # no ties: the Efron term reduces to the plain partial likelihood
    ll_plain = sum(float(x[i] @ b) - math.log(np.exp(x[t >= t[i]] @ b).sum()) for i in range(40) if d[i])
    assert ll == pytest.approx(ll_plain)


def test_harrell_c_counts_ties_as_half():
    t = np.array([1.0, 2.0, 3.0])
    d = np.array([1, 1, 0])
    assert CX.harrell_c(t, d, np.array([3.0, 2.0, 1.0])) == 1.0
    assert CX.harrell_c(t, d, np.array([1.0, 1.0, 1.0])) == 0.5


def test_cox_parity_with_prism():
    path = os.path.join(ROOT, "corpus", "auto", "cx1", "tables.json")
    if not os.path.exists(path):
        pytest.skip("Prism parity results not present")
    import cox_parity as P

    with open(path) as f:
        res = json.load(f)
    acc, missing = P.compare_all(P.gen(), res)
    bad = {k: max(v) for k, v in acc.items() if max(v) > 1e-6}
    assert not bad, bad
    assert not missing and len(acc) > 300
