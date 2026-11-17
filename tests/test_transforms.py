"""Table-output analyses (Normalize, Transform, Remove baseline, Row
statistics, Transpose): unit tests and Prism parity (tools/table_parity.py ->
corpus/auto/tb1; skipped when absent)."""

import json
import math
import os
import sys

import pytest

from refract.stats import transforms as TR

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "tools"))

TABLE = {"title": "G", "x": None, "rows": ["R1", "R2", "R3"],
         "sets": [{"title": "A", "subs": [[1.0, 2.0, 4.0], [2.0, 3.0, 5.0]]},
                  {"title": "B", "subs": [[10.0, 20.0, 15.0], [12.0, 22.0, 13.0]]}]}


def test_normalize_uses_row_means():
    p = {"calc": {"value_0": {"defineAs": "SMALLEST"}, "value_100": {"defineAs": "LARGEST"}},
         "options": {"reportResultsAs": "PERCENTAGES"}}
    out = TR.normalize(p, TABLE)
    a = out["sets"][0]["subs"]
    # A row means 1.5, 2.5, 4.5 -> 0 % = 1.5, 100 % = 4.5
    assert math.isclose(a[0][0], 100 * (1 - 1.5) / 3)
    assert math.isclose(a[1][2], 100 * (5 - 1.5) / 3)


def test_remove_baseline_ratio_delta_se():
    p = {"data": {"baselineType": "BASELINE_COLUMN", "columnBaseline": {"type": "EVERY_OTHER_COLUMN_2_4_6"},
                  "treatSubcolumnsAs": "MEANS"}, "calc": {"expression": "RATIO"}}
    out = TR.remove_baseline(p, TABLE)
    assert out["format"] == "y_se" and out["sets"][0]["title"] == "A / B"
    ma, mb = 1.5, 11.0
    sa, sb = math.sqrt(0.5) / math.sqrt(2), math.sqrt(2) / math.sqrt(2)
    assert math.isclose(out["sets"][0]["subs"][0][0], ma / mb)
    assert math.isclose(out["sets"][0]["subs"][1][0], ma / mb * math.sqrt((sa / ma) ** 2 + (sb / mb) ** 2))


def test_transform_functions():
    p = {"calc": {"transformType": "STANDARD", "standardFunction": {
        "xTransform": {"enabled": False}, "yTransform": {"enabled": True, "function": "PROBIT(Y)", "kSameForAll": True}}}}
    t = {"title": "XY", "x": [1.0], "rows": None, "sets": [{"title": "A", "subs": [[0.5]]}]}
    assert TR.transform(p, t)["sets"][0]["subs"][0][0] == pytest.approx(5.0)  # probit = z + 5


def test_table_parity_with_prism():
    path = os.path.join(ROOT, "corpus", "auto", "tb1", "tables.json")
    if not os.path.exists(path):
        pytest.skip("Prism parity results not present")
    import table_parity as P

    with open(path) as f:
        res = json.load(f)
    acc, missing = P.compare_all(P.gen(), res)
    bad = {k: max(v) for k, v in acc.items() if max(v) > 1e-9}
    assert not bad, bad
    assert not missing and len(acc) > 350
