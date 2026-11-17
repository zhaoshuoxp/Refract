"""One-way ANOVA and multiple-comparison tests.

Unit tests use identities, brute-force enumeration and SciPy cross-checks.
Parity tests compare with full-precision results Prism computed locally
(tools/anova_parity.py and tools/anova_exact_probe.py write them under
corpus/auto/); they skip when those results are absent.
"""

import itertools
import json
import math
import os
import sys

import numpy as np
import pytest
from scipy import stats

from refract.stats import distributions as D
from refract.stats import multiple_comparisons as MC
from refract.stats import one_way as OW
from refract.stats.engine import compute

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "tools"))

G3 = [[12.1, 14.3, 9.8, 11.0, 15.6], [15.2, 16.1, 12.4, 14.9, 18.3], [10.2, 9.9, 11.8, 8.7, 10.5]]


# ---------------------------------------------------------------- distributions
def test_ptukey_against_scipy_and_tables():
    # the Gauss-Legendre algorithm (as Prism) loses accuracy at very small df
    for q, k, df, tol in ((3.5, 3, 10, 1e-9), (2.0, 5, 20, 1e-9), (4.2, 6, 42, 1e-9), (5.0, 4, 2.5, 1e-6)):
        assert math.isclose(D.ptukey(q, k, df), stats.studentized_range.cdf(q, k, df), rel_tol=tol)
    assert round(D.qtukey(0.95, 3, 10), 3) == 3.877  # standard table value
    # k = 2: the studentized range is sqrt(2) |t|
    assert math.isclose(D.qtukey(0.95, 2, 21) / math.sqrt(2), stats.t.ppf(0.975, 21), rel_tol=1e-9)


def test_dunnett_and_smm_reduce_to_t_for_one_comparison():
    for c, df in ((1.3, 7), (2.9, 30)):
        two_sided = 2 * stats.t.sf(c, df)
        assert math.isclose(D.dunnett_sf(c, [math.sqrt(0.5)], df), two_sided, rel_tol=1e-9)
        assert math.isclose(D.smm_sf(c, 1, df), two_sided, rel_tol=1e-9)


def test_dunnett_independent_limit_is_smm():
    # lam -> 0 makes the comparisons independent: Dunnett == studentized maximum modulus
    assert math.isclose(D.dunnett_sf(2.5, [1e-9] * 3, 12), D.smm_sf(2.5, 3, 12), rel_tol=1e-8)


# ------------------------------------------------------------ one-way models
def test_ordinary_anova_against_scipy():
    m = OW.ordinary(G3)["ordinaryAnovaModel"]
    f = stats.f_oneway(*G3)
    assert math.isclose(m["anovaTable"]["colFactor"]["fTest"]["f"], f.statistic, rel_tol=1e-12)
    assert math.isclose(m["anovaTable"]["colFactor"]["fTest"]["pValue"]["value"], f.pvalue, rel_tol=1e-10)
    assert m["bartlettTest"]["status"] == "VALID"
    assert OW.ordinary([g[:3] for g in G3])["ordinaryAnovaModel"]["bartlettTest"] == {"status": "TOO_FEW_POINTS"}


def _brute_kw(groups):
    allv = np.concatenate(groups)
    r = stats.rankdata(allv)
    ns = [len(g) for g in groups]

    def stat(assign):
        return sum(r[list(ix)].sum() ** 2 / len(ix) for ix in assign)

    off = np.cumsum([0] + ns)
    obs = stat([range(off[i], off[i + 1]) for i in range(len(ns))])
    hit = tot = 0
    idx = list(range(len(allv)))

    def rec(rest, k, acc):
        nonlocal hit, tot
        if k == len(ns) - 1:
            tot += 1
            hit += stat(acc + [rest]) >= obs - 1e-9
            return
        for c in itertools.combinations(rest, ns[k]):
            rec([x for x in rest if x not in c], k + 1, acc + [list(c)])

    rec(idx, 0, [])
    return hit / tot


def test_kruskal_wallis_exact_matches_enumeration_with_ties():
    g = [np.array([1.0, 2, 2, 5]), np.array([3.0, 3, 7]), np.array([4.0, 6, 6]), np.array([2.0, 8])]
    assert math.isclose(OW.kw_exact_p(g), _brute_kw(g), rel_tol=1e-12)
    g = [np.array([1.0, 4, 9]), np.array([2.0, 5, 8]), np.array([3.0, 6, 7])]  # equal sizes: orbit counting
    assert math.isclose(OW.kw_exact_p(g), _brute_kw(g), rel_tol=1e-12)


def test_friedman_exact_matches_enumeration_with_ties():
    x = np.array([[1.0, 2, 3, 4], [2.0, 2, 1, 5], [3.0, 1, 2, 2], [4.0, 3, 1, 2]])
    r2 = np.apply_along_axis(stats.rankdata, 1, x)
    obs = (r2.sum(axis=0) ** 2).sum()
    arrs = [sorted(set(itertools.permutations(row))) for row in r2.tolist()]
    hit = tot = 0
    for combo in itertools.product(*arrs):
        tot += 1
        hit += (np.sum(combo, axis=0) ** 2).sum() >= obs - 1e-9
    assert math.isclose(OW.friedman_exact_p(x), hit / tot, rel_tol=1e-12)


def test_exact_p_thresholds():
    assert "value" in OW.kruskal_wallis(G3)["kruskalWallisTestModel"]["kruskalWallisTest"]["pValueExact"]
    big = [list(range(i, 60, 3)) for i in range(3)]  # 20 per group: approximate only
    t = OW.kruskal_wallis(big)["kruskalWallisTestModel"]["kruskalWallisTest"]
    assert t["pValueExact"]["value"] == "undefined" and t["pValue"] == t["pValueApproximate"]


# -------------------------------------------------------- multiple comparisons
def test_bky_qvalues_prism_example():
    # Prism 11, ordinary ANOVA k = 3, Q = 0.05 (two stage-1 rejections -> m0 = 1)
    q = MC._bky_qvalues([0.000490802, 0.000803428, 0.838558089003402])
    assert math.isclose(q[2], 0.2934953311511908, rel_tol=1e-12)
    assert math.isclose(q[0], q[1])


def test_tukey_and_holm_structure():
    tk = MC.compare(G3, "TUKEY")
    assert tk["method"] == "Tukey" and tk["comparisonCount"] == 3
    t01 = tk["tests"][(0, 1)]
    assert t01["meansDifference"] == pytest.approx(np.mean(G3[0]) - np.mean(G3[1]))
    hs = MC.compare(G3, "HOLM_SIDAK")["tests"]
    raw = MC.compare(G3, "TUKEY", mc_type="NO_CORRECTION")["tests"]
    largest = max(raw, key=lambda k: raw[k]["pValueIndividual"]["value"])
    assert hs[largest]["pValueAdjusted"]["value"] == pytest.approx(raw[largest]["pValueIndividual"]["value"])


def test_newman_keuls_step_down():
    g = [[10.0, 10.2, 9.9, 10.1], [10.1, 10.3, 10.0, 10.2], [20.0, 20.4, 19.8, 20.1]]
    t = MC.compare(g, "NEWMAN_KEULS")["tests"]
    assert t[(0, 2)]["pValueAdjusted"]["isSignificant"]
    assert t[(0, 1)]["statistic"] != "undefined"  # parent ranges significant -> tested


def test_engine_swap_direction():
    from anova_parity import params

    p = params("ORDINARY_ANOVA", "ALL_VS_ALL", "STATISTICAL", "TUKEY", {"postTests/pairwiseTests/options/swapDirection": True})
    r = compute("ONE_WAY_ANOVA", p, G3)
    t = r["ordinaryAnovaModel"]["multipleComparisons"]["tests"]["col1"]["value"]["col0"]["value"]
    assert t["meansDifference"] == pytest.approx(np.mean(G3[1]) - np.mean(G3[0]))


# ------------------------------------------------------------- Prism parity
KNOWN = {  # documented deviations (docs/format/findings.md, one-way ANOVA)
    "ord_dunnett": ("meansDifferenceCI", 5e-3),  # Prism's Dunnett critical value is ~1e-4 off the exact root
    "bf_t3": ("", 0.1),  # Prism's T3 tail P differs by <= 1.3e-10 absolute near 1e-9
}


@pytest.mark.parametrize("folder,n", [("anova1", 20), ("anova_nk", 20), ("anova_opts", 12)])
def test_one_way_parity_with_prism(folder, n):
    path = os.path.join(ROOT, "corpus", "auto", folder, "results.json")
    if not os.path.exists(path):
        pytest.skip("Prism parity results not present")
    import anova_parity as AP

    with open(path) as f:
        acc, missing = AP.compare_all(AP.gen(n), json.load(f))
    assert not missing, missing
    bad = {}
    for k, v in acc.items():
        tol = 1e-8 if "meansDifferenceCI" in k else 2e-9  # Prism inverts ptukey to ~1e-10
        cfg = k.split("/")[0]
        if cfg in KNOWN and KNOWN[cfg][0] in k:
            tol = KNOWN[cfg][1]
        if max(v) > tol:
            bad[k] = max(v)
    assert not bad, bad


@pytest.mark.parametrize("folder,rnd", [("anova_exact", 1), ("anova_exact2", 2)])
def test_exact_p_parity_with_prism(folder, rnd):
    path = os.path.join(ROOT, "corpus", "auto", folder, "results.json")
    if not os.path.exists(path):
        pytest.skip("Prism exact-P probe results not present")
    import anova_exact_probe as EP

    with open(path) as f:
        res = json.load(f)
    for name, design, groups in EP.gen(rnd_no=rnd):
        r = res.get(name, {}).get("a", {})
        model = next((v for k, v in r.items() if k.endswith("Model")), None)
        if model is None:
            continue
        t = model.get("kruskalWallisTest") or model.get("friedmanTest")
        ours = OW.kruskal_wallis(groups) if design.startswith("KRUSKAL") else OW.friedman(groups)
        o = next(iter(ours.values()))
        o = o.get("kruskalWallisTest") or o.get("friedmanTest")
        assert o["pValueExact"]["value"] == t["pValueExact"]["value"] or math.isclose(
            o["pValueExact"]["value"], t["pValueExact"]["value"], rel_tol=1e-12), name
        assert math.isclose(o["pValue"]["value"], t["pValue"]["value"], rel_tol=1e-9), name
