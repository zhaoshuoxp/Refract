"""Prism's automatic axis range: rules from controlled variants that Prism
re-saved (tools/autoscale_probe.py -> corpus/auto/as_*; skipped when absent)."""

import json
import os

import pytest

from refract.render.autoscale import auto_range, nice_ceil

ROOT = os.path.join(os.path.dirname(__file__), "..")


def test_nice_ceil():
    assert [nice_ceil(v) for v in (0.0094, 29.2, 582, 1000, 1001)] == [0.01, 50, 1000, 1000, 2000]


@pytest.mark.parametrize(("ext", "want"), [
    ((68.603, 146.21), (0, 200, 50)),      # head-room 5 % of the data span crosses 150
    ((2114.6, 2910.1), (0, 3000, 1000)),
    ((79.862, 79.947), (0, 80, 20)),       # tiny span: almost no head-room
    ((-0.24369, 3.986), (-1, 5, 1)),
    ((-363890, -44620), (-400000, 0, 100000)),  # all negative: ends at 0, no head-room
])
def test_bar_examples(ext, want):
    assert auto_range(*ext) == pytest.approx(want)


def test_xy_zero_rule():
    assert auto_range(0.58342, 1.2015, style="xy")[0] == 0.0       # min/max 0.486: from 0
    assert auto_range(21.699, 40.176, style="xy")[:2] == pytest.approx((20, 45))  # 0.540: not
    assert auto_range(3177.7, 7625.3, style="xy") == pytest.approx((0, 10000, 2000))  # margin after 0
    assert auto_range(-1079.5, -353.2, style="xy", axis="x")[1] < 0  # negative X: 0.327, not to 0
    assert auto_range(-295.9, -95.77, style="xy")[1] == 0.0         # negative Y: 0.324, to 0
    assert auto_range(-70.79, 167.08, style="xy") == pytest.approx((-100, 200, 50))  # crossing 0:
    assert auto_range(-9.404, 35.125, style="xy") == pytest.approx((-10, 40, 10))  # 5 % of each end
    assert auto_range(-489.46, 477.08, style="xy") == pytest.approx((-1000, 1000, 500))
    assert auto_range(0, 24, style="xy", axis="x") == pytest.approx((0, 30, 10))  # the sample XY's X


def test_column_scatter():
    """Column scatter (E-colscale): its own margins and zero rule."""
    assert auto_range(3.8, 7.8, style="column") == pytest.approx((0, 10, 2))   # Refract's sample, Prism 0..10
    assert auto_range(2.3, 7.8, style="column") == pytest.approx((0, 10, 2))   # batch5 sample
    assert auto_range(5.189, 5.194, style="column")[0] > 5  # tight data: not from 0
    assert auto_range(3271.9, 6375.0, style="column")[0] == 0.0               # min/max 0.513: from 0
    assert auto_range(67.057, 89.084, style="column") == pytest.approx((65, 95, 5))
    assert auto_range(-7.67, 226.1, style="column") == pytest.approx((-50, 250, 50))  # crosses 0: no bottom margin


def test_column_bars():
    """Column bars (E-pairs): the column margins, always from 0, a bottom margin below 0."""
    assert auto_range(3.8, 7.8, style="colbar") == pytest.approx((0, 10, 2))  # bars "5 %" gives 0..8
    assert auto_range(3.8, 7.8, style="bar") == pytest.approx((0, 8, 2))
    assert auto_range(-38.4, 6.6, style="colbar") == pytest.approx((-50, 10, 10))
    assert auto_range(-300, 6.6, style="colbar") == pytest.approx((-400, 100, 100))
    assert auto_range(90, 100, style="colbar")[0] == 0.0  # bars start at 0


# (folder, style, axes checked, variants Prism does not match: known, findings.md)
@pytest.mark.parametrize(("folder", "style", "axes", "known"), [
    ("as_bars", "bar", ("Y",), set()), ("as_dose", "xy", ("X", "Y"), set()),
    ("as_colscatter", "column", ("Y",), set()), ("as_xyx", "xy", ("X", "Y"), set()),
    ("as_xyx2", "xy", ("X", "Y"), set())])
def test_variants_match_prism(folder, style, axes, known):
    path = os.path.join(ROOT, "corpus", "auto", folder, "rows.json")
    if not os.path.exists(path):
        pytest.skip("Prism probe results not present")
    with open(path) as f:
        rows = [r for r in json.load(f)["rows"]
                if r["axis"] in axes and r["auto"] and not r.get("log") and r["variant"] not in known]
    assert len(rows) >= 29
    for r in rows:
        got = auto_range(r["dmin"], r["dmax"], style=style, axis=r["axis"].lower())
        assert got == pytest.approx((r["lo"], r["hi"], r["tick"]), rel=1e-9, abs=1e-12), r


def test_survival_x_variants_match_prism():
    from refract.render.qt import survival_x_range

    path = os.path.join(ROOT, "corpus", "auto", "as_surv", "rows.json")
    if not os.path.exists(path):
        pytest.skip("Prism probe results not present")
    with open(path) as f:
        rows = [r for r in json.load(f)["rows"] if r["axis"] == "X"]
    assert len(rows) == 30
    for r in rows:
        assert survival_x_range(r["dmax"]) == pytest.approx((r["lo"], r["hi"], r["tick"]), rel=1e-9, abs=1e-12), r


def test_auto_minor_ticks():
    """Prism adds 10 minor intervals once major ticks are over 0.75 inch apart
    (1418 of 1440 corpus axes)."""
    from refract.render.autoscale import auto_minor

    assert auto_minor(0, 30, 10, 4 * 72) == 10   # 1.33 in apart (the 4-inch XY graph)
    assert auto_minor(0, 60, 20, 3 * 72) == 10   # 1.0 in
    assert auto_minor(0, 40, 10, 3 * 72) == 0    # 0.75 in: none
    assert auto_minor(0, 60, 20, 2 * 72) == 0    # Prism's default 2-inch Y axis

