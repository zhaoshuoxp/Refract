"""Tests from entered summary data, and compact letter displays (E-stats8):
the numbers are Prism's own, computed by Prism 11.1 on the same tables."""

import pytest

from refract.model.document import DataSet, DataTable
from refract.stats import catalog
from refract.stats import inputs as INP
from refract.stats.multiple_comparisons import compact_letters


def _summary(rows, fmt="y_sd_n"):
    sets = [DataSet(chr(65 + i), [[str(m)], [str(s)], [str(n)]], uid=f"u{i}") for i, (m, s, n) in enumerate(rows)]
    return DataTable("S", "column", fmt, sets, 1, sheet_uid="s")


def test_t_tests_from_mean_sd_n():
    t = _summary([(12.3, 2.1, 8), (15.6, 3.4, 10)])
    p = catalog.build(catalog.by_key("t_test"), {"design": "UNPAIRED_T_TEST"})
    r = INP.run("T_TESTS_AND_NONPARAMETRIC", p, t)
    m = r["unpairedTTestModel"]
    assert m["unpairedTTest"]["t"] == pytest.approx(2.3958553889984584, rel=1e-9)
    assert m["unpairedTTest"]["df"] == 16.0
    assert m["unpairedTTest"]["pValue"]["value"] == pytest.approx(0.0291587585573053, rel=1e-9)
    assert m["differenceOfMeans"]["stdErrorOfDifference"] == pytest.approx(1.3773786244166852, rel=1e-9)
    d = r["descriptiveStatistics"]["col1"]["value"]
    assert (d["n"], d["mean"], d["sd"]) == (10, pytest.approx(15.6), pytest.approx(3.4))
    assert d["meanCI"]["lower"] == pytest.approx(13.167786519699739, rel=1e-9)
    assert sorted(v["value"] for v in r["compactLetterDisplay"]["samples"].values()) == ["A", "B"]
    w = INP.run("T_TESTS_AND_NONPARAMETRIC", catalog.build(catalog.by_key("t_test"), {"design": "WELCH_T_TEST"}), t)
    assert w["welchTTestModel"]["welchTTest"]["df"] == pytest.approx(15.189229868787722, rel=1e-9)


def test_one_way_anova_from_mean_sd_n():
    t = _summary([(100.0, 15.0, 20), (92.5, 12.0, 25), (110.0, 20.0, 15)])
    r = INP.run("ONE_WAY_ANOVA", catalog.build(catalog.by_key("one_way"), {}), t)
    m = r["ordinaryAnovaModel"]
    assert m["anovaTable"]["colFactor"]["fTest"]["f"] == pytest.approx(6.16309025954542, rel=1e-9)
    assert m["anovaTable"]["residual"]["ss"] == pytest.approx(13331.0, rel=1e-9)
    assert "bartlettTest" not in m and "brownForsytheTest" not in m  # Prism leaves them out of summary data
    letters = {e["id"]["col"]["idx"]: e["value"] for e in m["compactLetterDisplay"]["samples"].values()}
    assert letters == {0: "A B", 1: "B", 2: "A"}  # Prism's letters for these
    assert "median" not in r["descriptiveStatistics"]["col0"]["value"]


def test_compact_letters():
    assert compact_letters([1.0, 2.0, 3.0], set()) == ["A", "A", "A"]
    assert compact_letters([3.0, 1.0], {(0, 1)}) == ["A", "B"]
    assert compact_letters([100.0, 92.5, 110.0], {(1, 2)}) == ["A B", "B", "A"]
