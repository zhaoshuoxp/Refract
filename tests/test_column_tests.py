"""One-sample tests and normality tests.

Unit tests use SciPy cross-checks; the parity test compares with full-precision
results Prism computed locally (tools/column_tests_parity.py, corpus/auto/ct1);
it skips when those results are absent.
"""

import json
import math
import os
import sys

import numpy as np
import pytest
from scipy import stats

from refract.stats import normality as NT
from refract.stats import one_sample as OS

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "tools"))
X = [9.1, 10.4, 11.8, 8.7, 12.2, 10.9, 9.6, 11.1]


def test_one_sample_t_matches_scipy():
    r = OS.t_test(X, 10.0)["tTestModel"]
    ref = stats.ttest_1samp(X, 10.0)
    assert math.isclose(r["tTest"]["pValue"]["value"], ref.pvalue, rel_tol=1e-12)
    t = r["tTest"]["t"]
    assert math.isclose(r["discrepancy"]["rSquared"], t * t / (t * t + 7))


def test_wilcoxon_exact_and_ci():
    y = [9.1, 10.4, 11.8, 8.6, 12.2, 10.7, 9.5, 11.15]  # no tied |y - 10| (SciPy's exact P is not tie-conditional)
    r = OS.wilcoxon_signed_rank(y, 10.0)["wilcoxonTestModel"]
    ref = stats.wilcoxon(np.array(y) - 10.0, method="exact")
    assert math.isclose(r["wilcoxonTest"]["pValue"]["value"], ref.pvalue, rel_tol=1e-12)
    small = OS.wilcoxon_signed_rank([1.0, 2.0, 3.5], 0.0)["wilcoxonTestModel"]["discrepancy"]["confidenceIntervalDiscrepancy"]
    assert math.isclose(small["level"], 75.0) and (small["lower"], small["upper"]) == (1.0, 3.5)  # min..max, 1 - 2/8
    assert OS.wilcoxon_signed_rank([1.0, 2.0], 0.0)["wilcoxonTestModel"]["wilcoxonTest"]["status"] == "TOO_FEW_POINTS"


def test_normality_tests_against_scipy_and_rules():
    x = np.array(X)
    assert math.isclose(NT.shapiro_wilk(x, 0.05)["pValue"]["value"], stats.shapiro(x).pvalue, rel_tol=1e-12)
    assert math.isclose(NT.dagostino_pearson(x, 0.05)["K2"], stats.normaltest(x).statistic, rel_tol=1e-12)
    ks = NT.kolmogorov_smirnov(x, 0.05)
    assert ks["pValue"]["state"] in ("P_VALUE_GREATER", "P_VALUE_EQUAL") and 0 < ks["distance"] < 1
    params = {"calc": {"testforNormality": True, "testforLognormality": True, "testRelativeLikelihood": True, "tests": {}},
              "options": {"significanceLevel": 0.05}}
    v = NT.normality(params, [[-1.0, *X]], ["A"])["samples"]["col0"]["value"]
    assert v["lognormalityModel"]["status"] == "NON_POSITIVE_VALUES"
    assert v["relativeLikelihoodTest"]["status"] == "UNDEFINED_LOGNORMAL_MODEL"
    assert v["dataSummary"]["impossibleValues"]["negativeCount"] == 1


def test_relative_likelihood_ratio_is_mle_ratio():
    x = np.array(X)
    rl = NT.relative_likelihood(x)
    mle = math.exp(stats.norm.logpdf(x, x.mean(), x.std()).sum() -
                   (stats.norm.logpdf(np.log(x), np.log(x).mean(), np.log(x).std()) - np.log(x)).sum())
    assert math.isclose(rl["likelihoodRatio"], mle, rel_tol=1e-10)


def test_column_tests_parity_with_prism():
    path = os.path.join(ROOT, "corpus", "auto", "ct1", "results.json")
    if not os.path.exists(path):
        pytest.skip("Prism parity results not present")
    import column_tests_parity as P

    with open(path) as f:
        acc, missing = P.compare_all(P.gen(6), json.load(f))
    assert not missing, dict(missing)
    bad = {k: max(v) for k, v in acc.items() if max(v) > 2e-9}
    assert not bad, bad
