"""Outliers (Grubbs, iterative Grubbs, ROUT) and Bland-Altman: unit tests and
Prism parity (tools/outlier_parity.py -> corpus/auto/ol2; skipped when absent)."""

import json
import math
import os
import sys

import pytest

from refract.stats import outliers as OL

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "tools"))


def test_grubbs_flags_planted_outlier():
    vals = [10.1, 9.8, 10.3, 9.9, 10.0, 10.2, 9.7, 25.0]
    p = {"calc": {"method": "GRUBBS_SINGLE", "alpha": 0.05}}
    r = OL.identify_outliers(p, [vals])
    assert r["results"]["samples"]["col0"]["value"]["outlierCount"] == 1
    assert r["tables"]["Outliers"]["rows"] == ["#8"]
    assert r["tables"]["Cleaned data"]["sets"][0]["subs"][0][7] is None


def test_bland_altman_limits_use_1_96():
    p = {"data": {"methodAID": {"col": {"idx": 0}}, "methodBID": {"col": {"idx": 1}}}, "calc": {"type": "A_MINUS_B"}}
    r = OL.bland_altman(p, [[1.0, 2.0, 3.0, 5.0], [1.5, 1.5, 3.5, 4.0]])["results"]
    assert math.isclose(r["ci"]["upper"] - r["bias"], 1.96 * r["sd"])


def test_outlier_parity_with_prism():
    path = os.path.join(ROOT, "corpus", "auto", "ol2", "tables.json")
    if not os.path.exists(path):
        pytest.skip("Prism parity results not present")
    import outlier_parity as P

    with open(path) as f:
        res = json.load(f)
    acc, _ = P.compare_all(P.gen(), res)
    bad = {k: max(v) for k, v in acc.items() if max(v) > 1e-9}
    assert not bad, bad
    assert len(acc) > 120
