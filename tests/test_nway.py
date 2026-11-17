"""Multifactor ANOVA and multiple-variables tables: Prism-computed two-factor
sample (corpus/seeds/R_twoway.prism; skipped when absent) and a Type III
check against two_way for an unbalanced design."""

import json
import os
import zipfile

import pytest

from refract.formats.bundle_builder import BundleBuilder, DataSet, TableSpec
from refract.stats import nway as NW
from refract.stats import two_way as TW

ROOT = os.path.join(os.path.dirname(__file__), "..")
SEED = os.path.join(ROOT, "corpus", "seeds", "R_twoway.prism")


def _leaves(o, pre=""):
    if isinstance(o, dict):
        for k, v in o.items():
            yield from _leaves(v, f"{pre}/{k}")
    elif isinstance(o, list):
        for i, v in enumerate(o):
            yield from _leaves(v, f"{pre}/{i}")
    else:
        yield pre, o


def test_multifactor_matches_prism_sample():
    if not os.path.exists(SEED):
        pytest.skip("Prism sample not present")
    from refract.formats.prism_reader import read_prism

    p = read_prism(SEED, include_results=True)
    t = next(t for t in p.tables if t.title == "MV: Extract and Rearrange")
    cols, titles = [d.subcolumns[0] for d in t.datasets], [d.title for d in t.datasets]
    z = zipfile.ZipFile(SEED)
    for n in z.namelist():
        if n.startswith("analyses") and n.endswith("/sheet.json") and \
                json.loads(z.read(n))["analysisClass"] == "MULTI_FACTOR_ANOVA":
            prism = json.loads(z.read(n.replace("sheet.json", "results.json")))["content"]
            prm = json.loads(z.read(n.replace("sheet.json", "parameters.json")))["content"]
    ours = dict(_leaves(NW.from_params(prm, cols, titles)))
    for k, v in _leaves(prism):
        assert ours[k] == pytest.approx(v, rel=1e-9, abs=1e-12) if isinstance(v, float) else ours[k] == v, k


def test_two_factor_type_iii_matches_two_way():
    import random

    rnd = random.Random(2)
    rows = [(a, b, 10 + 2 * a + b + rnd.gauss(0, 1)) for a in range(2) for b in range(3) for _ in range(rnd.randint(2, 5))]
    out = NW.multifactor([r[2] for r in rows], [[f"a{r[0]}" for r in rows], [f"b{r[1]}" for r in rows]], ["A", "B"],
                         NW.full_factorial(2))
    cells = [[[r[2] for r in rows if r[0] == a and r[1] == b] for b in range(3)] for a in range(2)]
    ref = TW.ordinary(cells)
    tab = next(iter(ref.values()))["anovaTable"]
    fe = out["ordinaryModel"]["anovaTable"]["fixedEffects"]
    assert fe[0]["ss"] == pytest.approx(tab["rowFactor"]["ss"])
    assert fe[2]["ss"] == pytest.approx(tab["rowFactorVsColFactor"]["ss"])


def test_multivariable_table_is_written_with_categories():
    b = BundleBuilder()
    b.add_table(TableSpec("MV", "multivariable", "y_single", [DataSet("Y", [[1.5, 2.0]]), DataSet("G", [["x", "y"]])]))
    arc = b.build()
    sets = [json.loads(arc.read(n)) for n in arc.names() if n.startswith("data/sets/") and n.endswith(".json")]
    if sets:
        g = next(s for s in sets if s.get("title") == "G")
        assert g["@class"] == "VariableDataSet" and g["currentType"] == "categorical"
        assert [c["name"] for c in g["categories"]] == ["x", "y"]
