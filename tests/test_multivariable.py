"""Multiple linear / logistic regression, PCA and multifactor ANOVA with post
tests against Prism's own computations in a Prism-made sample
(corpus/manual/batch3_samples.prism) and the parity run
(tools/multreg_parity.py -> corpus/auto/mr1); skipped when absent."""

import json
import os
import sys
import zipfile

import numpy as np
import pytest

from refract.stats import engine as E
from refract.stats import pca as PC

ROOT = os.path.join(os.path.dirname(__file__), "..")
SAMPLE = os.path.join(ROOT, "corpus", "manual", "batch3_samples.prism")
sys.path.insert(0, os.path.join(ROOT, "tools"))

# known: Prism's random parallel-analysis simulations; the Dunnett critical value of CIs (findings.md)
KNOWN = ("parallelAnalysisValue", "/equation")


def _leaves(o, pre=""):
    if isinstance(o, dict):
        for k, v in o.items():
            yield from _leaves(v, f"{pre}/{k}")
    elif isinstance(o, list):
        for i, v in enumerate(o):
            yield from _leaves(v, f"{pre}/{i}")
    else:
        yield pre, o


def _sample(cls):
    if not os.path.exists(SAMPLE):
        pytest.skip("Prism sample not present")
    from refract.formats.prism_reader import read_prism

    z = zipfile.ZipFile(SAMPLE)
    for n in z.namelist():
        if n.startswith("analyses") and n.endswith("/sheet.json"):
            sheet = json.loads(z.read(n))
            if sheet["analysisClass"] == cls:
                prm = json.loads(z.read(n.replace("sheet.json", "parameters.json")))["content"]
                res = json.loads(z.read(n.replace("sheet.json", "results.json")))["content"]
                table = sheet["title"].split(" of ", 1)[1]
                t = next(t for t in read_prism(SAMPLE).tables if t.title == table)
                return prm, res, [d.subcolumns[0] for d in t.datasets], [d.title for d in t.datasets]
    pytest.skip(f"{cls} not in the sample")


def _check(ours, prism, skip=()):
    o = dict(_leaves(ours))
    checked = 0
    for k, v in _leaves(prism):
        if any(s in k for s in KNOWN + skip):
            continue
        assert k in o, k
        if isinstance(v, float) and not isinstance(v, bool):
            assert o[k] == pytest.approx(v, rel=1e-8, abs=1e-12), k
        else:
            assert o[k] == v, k
        checked += 1
    return checked


@pytest.mark.parametrize("cls", ["MULTIPLE_LINEAR_REGRESSION", "MULTIPLE_LOGISTIC_REGRESSION", "PCA"])
def test_matches_prism_sample(cls):
    prm, res, cols, titles = _sample(cls)
    assert _check(E.compute(cls, prm, cols, titles=titles), res) > 30


def _by_order(r):
    """Prism keys post tests by uuid and identifies groups by column uid: compare
    them in order, by value."""
    r = dict(r)
    mc = dict(r["multipleComparisons"])
    mc["tests"] = [t["value"] for t in mc["tests"].values()]
    for t in mc["tests"]:
        for s in ("sample1", "sample2"):
            t[s] = t[s]["value"]
    r["multipleComparisons"] = mc
    return r


def test_multifactor_post_tests_match_prism_sample():
    prm, res, cols, titles = _sample("MULTI_FACTOR_ANOVA")
    ours = E.compute("MULTI_FACTOR_ANOVA", prm, cols, titles=titles)
    # Dunnett CI limits: Prism's critical value differs in the 4th digit (known, findings.md)
    assert _check(_by_order(ours), _by_order(res), skip=("/lower", "/upper")) > 150


def test_pca_tables_and_orientation():
    rng = np.random.default_rng(3)
    z = rng.standard_normal((40, 4))
    cols = [list(z[:, j] + 0.5 * z[:, 0]) for j in range(4)]
    out = PC.pca({"data": {"variables": [{"col": {"idx": j}} for j in range(4)]},
                  "calc": {"transform": "STANDARDIZE_DATA", "method": "SPECIFIC_NUMBER", "componentCount": 2}},
                 cols, ["a", "b", "c", "d"])
    eig = out["results"]["eigenvalues"]
    assert sum(e["value"] for e in eig.values()) == pytest.approx(4.0)
    assert eig["PC4"]["cumulativeExplainedVariance"] == pytest.approx(100.0)
    load = np.array([s["subs"][0] for s in out["tables"]["Loadings"]["sets"]])
    assert (load ** 2).sum(axis=1) == pytest.approx([eig["PC1"]["value"], eig["PC2"]["value"]])
    assert out["results"]["dataSummary"]["method"] == "Largest 2 eigenvalues"
    assert out["results"]["dataSummary"]["selectedComponentsCount"] == 2


def test_parity_with_prism():
    path = os.path.join(ROOT, "corpus", "auto", "mr1", "tables.json")
    if not os.path.exists(path):
        pytest.skip("Prism parity results not present")
    import multreg_parity as M

    with open(path) as f:
        res = json.load(f)
    acc, _ = M.compare_all(M.gen(), res)
    bad = {k: max(v) for k, v in acc.items() if max(v) > 1e-6}
    assert not bad, bad
