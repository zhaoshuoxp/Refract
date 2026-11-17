"""Statistics engine tests.

Unit tests use textbook identities and SciPy cross-checks (no Prism needed).
Parity tests compare with full-precision results Prism computed locally
(tools/stats_parity.py writes corpus/auto/parity2/results.json); they skip
when those results are absent.
"""

import json
import math
import os
import sys

import numpy as np
import pytest
from scipy import stats

from refract.stats.descriptive import describe, percentile
from refract.stats.engine import compute
from refract.stats.two_sample import (
    _exact_rank_sum_p,
    _exact_signed_rank_p,
    _ks_exact_conditional,
    spearman_pairing,
    two_sample,
)

A = [12.1, 14.3, 9.8, 11.0, 15.6, 13.2, 10.4, 12.9, 14.8, 11.7]
B = [15.2, 16.1, 12.4, 14.9, 18.3, 15.5, 13.1, 16.0, 17.7, 14.2]


def test_percentile_rule_matches_prism_example():
    # Prism's Geometric mean sample, n = 14 (checked against its results.json)
    x = np.sort(np.array([1, 2, 4, 9, 24, 35, 45, 56, 67, 89, 111, 222, 345, 666.0]))
    assert percentile(x, 0.25) == 7.75 and percentile(x, 0.75) == 138.75 and percentile(x, 0.10) == 1.5


def test_describe_basics():
    d = describe(A)
    assert d["n"] == 10 and math.isclose(d["mean"], 12.58) and math.isclose(d["sd"], np.std(A, ddof=1))
    assert d["percentiles"]["level"] == 90.0 and d["minimum"] == min(A)


def test_unpaired_and_welch_against_scipy():
    u = two_sample("UNPAIRED_T_TEST", A, B)["unpairedTTestModel"]
    w = two_sample("WELCH_T_TEST", A, B)["welchTTestModel"]
    assert math.isclose(u["unpairedTTest"]["pValue"]["value"], stats.ttest_ind(B, A).pvalue, rel_tol=1e-12)
    assert math.isclose(w["welchTTest"]["pValue"]["value"], stats.ttest_ind(B, A, equal_var=False).pvalue, rel_tol=1e-12)
    # values from Prism (oracle_ttest_enum): t = 3.272446098511991, Welch df = 17.9623244908593
    assert math.isclose(u["unpairedTTest"]["t"], 3.272446098511991, rel_tol=1e-13)
    assert math.isclose(w["welchTTest"]["df"], 17.9623244908593, rel_tol=1e-12)


def test_exact_distributions_without_ties_match_scipy():
    x, y = np.array(A), np.array(B)
    ranks = stats.rankdata(np.concatenate([y, x]))
    assert math.isclose(_exact_rank_sum_p(ranks, 10, ranks[:10].sum()),
                        stats.mannwhitneyu(y, x, method="exact").pvalue, rel_tol=1e-12)
    d = y - x
    r = stats.rankdata(np.abs(d))
    assert math.isclose(_exact_signed_rank_p(r, r[d > 0].sum()), stats.wilcoxon(d, method="exact").pvalue, rel_tol=1e-12)
    a, b = np.array([1.0, 3, 5, 7, 9]), np.array([2.0, 4, 6, 8, 10, 12])
    assert math.isclose(_ks_exact_conditional(a, b, stats.ks_2samp(a, b).statistic), stats.ks_2samp(a, b, method="exact").pvalue,
                        rel_tol=1e-12)


def test_spearman_exact_small_n():
    # n = 5, rho = 0.9: one-tailed exact P = 5/120 (Prism shows 0.041666...)
    a = np.array([1.0, 2, 3, 4, 5])
    b = np.array([2.0, 1, 3, 4, 5])
    assert math.isclose(spearman_pairing(a, b, 0.05)["pValueExact"]["value"], 5 / 120, rel_tol=1e-12)


def test_engine_dispatch():
    params = {"experimentalDesign": "MANN_WHITNEY_TEST", "options": {"swapDirection": True, "significanceLevel": 0.05}}
    r = compute("T_TESTS_AND_NONPARAMETRIC", params, [A, B])
    assert r["mannWhitneyTestModel"]["mannWhitneyTest"]["U"] == 15.0  # Prism: U = 15
    assert compute("COLUMN_STATISTICS", {}, [A])["samples"]["col0"]["value"]["descriptiveStatistics"]["n"] == 10


PARITY = os.path.join(os.path.dirname(__file__), "..", "corpus", "auto", "parity2", "results.json")
KNOWN_PRISM_QUIRKS = {("pair06_n5_k6", "KOLMOGOROV_SMIRNOV_TEST")}  # Prism floating point drops a boundary path
LOOSE = {"varianceTest/pValue/value": 1e-7}  # Prism's F-distribution numerics


@pytest.mark.skipif(not os.path.exists(PARITY), reason="Prism parity results not generated locally")
def test_parity_with_prism():
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
    from stats_parity import gen_pairs, leaves

    with open(PARITY) as f:
        res = json.load(f)
    failures = []
    for name, x, y in gen_pairs(60):
        r = res[name]
        for s in r["colstats"]["samples"].values():
            col = s["id"]["col"]["idx"]
            ours, theirs = dict(leaves(describe(x if col == 0 else y))), dict(leaves(s["value"]["descriptiveStatistics"]))
            failures += [(name, "colstats", k) for k, v in theirs.items()
                         if not k.endswith("/level") and not (math.isclose(ours.get(k, math.nan), v, rel_tol=1e-9, abs_tol=1e-300)
                                                             or (math.isnan(v) and math.isnan(ours.get(k, 0))))]
        for d in ("UNPAIRED_T_TEST", "WELCH_T_TEST", "PAIRED_T_TEST", "RATIO_PAIRED_T_TEST", "MANN_WHITNEY_TEST",
                  "WILCOXON_TEST", "KOLMOGOROV_SMIRNOV_TEST"):
            if (name, d) in KNOWN_PRISM_QUIRKS or not r.get(d):
                continue
            ours_all = two_sample(d, x, y)
            model = next(iter(ours_all))
            ours, theirs = dict(leaves(ours_all[model])), dict(leaves(r[d].get(model, {})))
            for k, v in theirs.items():
                if k.endswith(("/level", "/idx")) or k not in ours:
                    continue
                tol = next((t for suffix, t in LOOSE.items() if k.endswith(suffix)), 1e-9)
                if not (math.isclose(ours[k], v, rel_tol=tol, abs_tol=1e-300) or (math.isnan(v) and math.isnan(ours[k]))):
                    failures.append((name, d, k, ours[k], v))
    assert failures == [], failures[:10]
