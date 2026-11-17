"""Frequency distribution: unit tests and Prism parity (tools/freq_parity.py,
corpus/auto/fd1; skipped when absent)."""

import json
import os
import sys

import numpy as np
import pytest

from refract.stats import frequency as FD

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "tools"))
PARAMS = {"calc": {"distributionType": "FREQUENCY", "binWidth": {"type": "AUTO_BINS"},
                   "binCenterFirst": {"isAuto": True}, "binCenterLast": {"isAuto": True}}}


def test_auto_bins_single_set_examples():
    # Prism 11.1 values (fd09, fd13, fd07 of the parity set)
    rnd = np.random.default_rng(0)
    x = np.concatenate([[508.1, 1428.2], rnd.uniform(509, 1428, 10)])
    assert FD.auto_bins([x])[0] == 100.0  # 920.1 / (floor(log2 12) + 2) = 184 -> 100
    ints = np.array([0.0, 11.0, *range(1, 11), 5, 6, 7, 3, 2, 8, 9, 4])
    assert FD.auto_bins([ints])[0] == 1.0  # integer data: whole-number width


def test_counts_cumulative_and_no_bins():
    cols = [[1.0, 1.2, 2.6, 3.0], [2.0, 2.2]]
    p = json.loads(json.dumps(PARAMS))
    p["calc"]["binWidth"] = {"type": "AUTO_BINS", "value": 1.0}
    r = FD.frequency(p, cols, ["A", "B"])
    assert sum(r["table"]["sets"][0]) == 4 and r["results"]["samples"]["col1"]["value"]["binsSummary"]["binnedValuesCount"] == 2
    p["calc"]["distributionType"] = "CUMULATIVE_FREQUENCY"
    assert FD.frequency(p, cols, ["A", "B"])["table"]["sets"][0][-1] == 4
    p["calc"]["distributionType"] = "FREQUENCY"
    p["calc"]["binWidth"] = {"type": "NO_BINS"}
    nb = FD.frequency(p, cols, ["A", "B"])["table"]
    assert nb["x"] == [1.0, 1.2, 2.6, 3.0, 2.0, 2.2] and nb["sets"][1][:4] == [None] * 4


def test_frequency_parity_with_prism():
    path = os.path.join(ROOT, "corpus", "auto", "fd1", "collected.json")
    if not os.path.exists(path):
        pytest.skip("Prism parity results not present")
    import freq_parity as P

    with open(path) as f:
        acc, missing = P.compare_all(P.gen(40), json.load(f))
    assert not [k for k in missing if not k.startswith("known:")], missing
    bad = {k: max(v) for k, v in acc.items() if max(v) > 1e-9}
    assert not bad, bad
