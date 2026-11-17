"""Graph model, builder and Qt renderer: structure, exports, the point
arrangement, and SSIM against Prism's own renders of its default graphs
(corpus/manual/batch5_samples.prism exported by tools/prism_auto.py to
corpus/auto/b5; skipped when absent)."""

import os

import pytest

from refract.model.document import DataSet, DataTable
from refract.render import build

pytest.importorskip("PySide6")


def _grouped():
    rows = DataSet(None, [["A", "B", "", ""]], role="RT")
    s1 = DataSet("S1", [["1", "2", "", ""], ["2", "3", "", ""], ["3", "4", "", ""]])
    s2 = DataSet("S2", [["4", "1", "", ""], ["5", "2", "", ""], ["6", "3", "", ""]])
    return DataTable("T", "grouped", "y_replicates", [s1, s2], 4, replicates=3, row_titles=rows)


def test_grouped_bars_mean_sd():
    g = build.from_table(_grouped())
    assert g.categories == ["A", "B"]  # empty trailing rows dropped
    s = g.series[1]
    assert s.kind == "bar" and s.ys == [5.0, 2.0]
    assert s.err_hi[0] == pytest.approx(6.0) and s.err_lo[0] == pytest.approx(4.0)
    assert g.extent()[3] == pytest.approx(6.0)


def test_column_scatter_and_xy():
    col = DataTable("C", "column", "y_single", [DataSet("a", [["1", "2", "3"]]), DataSet("b", [["5", "", "7"]])], 3)
    g = build.from_table(col)
    assert g.family == "column" and g.series[1].points == [[5.0, 7.0]] and g.series[1].ys == [6.0]
    xy = DataTable("XY", "xy", "y_single", [DataSet("y", [["1", "4", ""]])], 3, x=DataSet("X", [["0", "1", "2"]], role="X"))
    gx = build.from_table(xy)
    assert gx.series[0].xs == [0.0, 1.0] and gx.series[0].ys == [1.0, 4.0]


def test_axes_follow_prism_autoscale():
    from refract.render.qt import resolve_axes

    (xlo, xhi, _), y = resolve_axes(build.from_table(_grouped()))
    assert (xlo, xhi) == (0.0, 1.0)  # category slots
    assert y == pytest.approx((0.0, 8.0, 2.0))  # extent 1..6: top 6 + 5 % of 5 = 6.25 -> tick 2 -> 0..8


def test_exports(tmp_path):
    from refract.render import qt

    g = build.from_table(_grouped())
    g.y_axis.title = "Y"
    w, h = qt.to_png(g, str(tmp_path / "g.png"), dpi=150)
    pw, ph = qt.to_pdf(g, str(tmp_path / "g.pdf"))
    qt.to_svg(g, str(tmp_path / "g.svg"))
    assert w == pytest.approx(pw * 150 / 72, abs=1) and h == pytest.approx(ph * 150 / 72, abs=1)
    assert (tmp_path / "g.pdf").read_bytes()[:5] == b"%PDF-"
    svg = (tmp_path / "g.svg").read_text()
    flat = svg.replace("\n", "")
    assert "<svg" in flat and ">A<" in flat  # category label as one run (titles / legend: one per character)
    assert os.path.getsize(tmp_path / "g.png") > 1000


def test_spread_matches_prism_column_scatter():
    from refract.render.qt import spread

    # Prism's default column scatter (batch5, "Untreated" 3.4 4.3 3 3.9 4.1 and
    # "Placebo" 2.3 5.2 4.5 3.1 5): page y = -14.366 * value, symbols 4.73 pt
    def slots(vals):
        return spread([-14.366 * v for v in vals], 4.73)

    assert slots([3.4, 4.3, 3.0, 3.9, 4.1]) == [0, -0.5, 0, -0.5, 0.5]
    assert slots([2.3, 5.2, 4.5, 3.1, 5.0]) == [0, -0.5, 0, 0, 0.5]
    # grouped bars: Knock-out B, Treated 65 69 71 at 0.9593 pt per unit, 6.32 pt symbols
    assert spread([-0.9593 * v for v in (65, 69, 71)], 6.32) == [-1, 1, 0]


def test_km_steps():
    xs, ys, marks = build.km_steps([46, 46, 64, 78, 124, 130, 150, 150], [1, 0, 0, 1, 1, 0, 0, 0])
    assert xs[:3] == [0.0, 46.0, 46.0] and ys[:3] == [100.0, 100.0, 87.5]  # drop at 46 (1 of 8)
    assert ys[-1] == pytest.approx(52.5) and xs[-1] == 150.0
    assert marks == [(46.0, 87.5), (64.0, 87.5), (130.0, 52.5), (150.0, 52.5)]


def test_survival_axes():
    from refract.render.qt import resolve_axes

    g = build.survival_graph(DataTable("S", "survival", "y_single", [DataSet("a", [["1", "0", "1"]])], 3,
                                       x=DataSet("t", [["10", "40", "150"]], role="X")))
    assert resolve_axes(g) == ((-23.75, 223.75, 50.0), (0.0, 110.0, 50.0))


@pytest.mark.parametrize(("index", "minimum"), [(0, 0.97), (1, 0.92), (2, 0.96), (3, 0.93)])
def test_default_graphs_match_prism(index, minimum, tmp_path):
    root = os.path.join(os.path.dirname(__file__), "..")
    sample = os.path.join(root, "corpus", "manual", "batch5_samples.prism")
    ref = os.path.join(root, "corpus", "auto", "b5", "batch5_samples", f"graph_{index + 1}.pdf")
    if not (os.path.exists(sample) and os.path.exists(ref)):
        pytest.skip("Prism sample or its exports not present")
    import sys

    sys.path.insert(0, os.path.join(root, "tools"))
    import image_compare as IC

    from refract.formats import open_document
    from refract.render import qt

    g = build.from_table(open_document(sample).tables[index])
    g.x_axis.title = "Hours" if index == 0 else ""
    out = str(tmp_path / "g.pdf")
    qt.to_pdf(g, out)
    assert IC.ssim_aligned(IC.pdf_grey(ref), IC.pdf_grey(out)) >= minimum


def test_title_snap_and_annotation_extent():
    from refract.render import qt
    from refract.render.model import Axis, Graph, Series

    g = Graph(title="T", family="xy", series=[Series("a", "points", [0.0, 1.0], [0.0, 1.0])],
              x_axis=Axis(min=0, max=1, tick=0.5), y_axis=Axis(min=0, max=1, tick=0.5))
    rule = qt.layout(g)
    top = rule.title_baseline - rule.plot[1]
    g.title_pos, g.title_snap = (None, -60.0), 1.5  # stale height: the rule wins
    assert qt.layout(g).title_baseline - qt.layout(g).plot[1] == pytest.approx(top)
    g.title_snap = None  # trusted: the page grows to hold it
    lay = qt.layout(g)
    assert lay.height > rule.height + 20
    g.title_pos = None
    g.annotations = [{"kind": "text", "cx": 50.0, "top": -80.0, "text": "*", "style": g.legend_style}]
    assert qt.layout(g).plot[1] > rule.plot[1] + 40  # everything moves down under it


def test_tick_labels_keep_decimals_on_zero():
    from refract.render import qt

    assert qt.fmt_tick(0.0, 0.01) == "0.00" and qt.fmt_tick(-0.0, 0.5) == "0.0"
    assert qt.fmt_tick(0.0, 50) == "0" and qt.fmt_tick(0.03, 0.01) == "0.03"


def test_pie_from_parts_of_whole(tmp_path):
    from refract.render import qt

    rows = DataSet(None, [["A", "B", "C", ""]], role="RT")
    ds = DataSet("Votes", [["50", "30", "20", ""]])
    t = DataTable("T", "parts_of_whole", "y_single", [ds], 4, row_titles=rows)
    g = build.pie_graph(t)
    assert g.family == "pie" and g.categories == ["A", "B", "C", ""] and g.series[0].ys[:3] == [50.0, 30.0, 20.0]
    g.x_length = g.y_length = 144.0
    g.legend_pos = [(10.0, 0.0), (10.0, 20.0)]
    g.legend_texts, g.legend_fills = ["50% A", "30% B"], [(0, 0, 0, 255), None]
    lay = qt.layout(g)
    left, top, right, bottom = lay.plot
    assert right - left == pytest.approx(144.0 * qt.DRAWN) and bottom - top == pytest.approx(right - left)
    # a label without a swatch starts at the entry box's padding
    assert lay.legend[1][2] - right == pytest.approx(10.0 + qt.LEGEND_BOX_PAD)
    g.series[0].hole = 0.5
    w, h = qt.to_png(g, str(tmp_path / "pie.png"), dpi=72)
    assert (w, h) == (lay.width, lay.height)


def test_free_text_lines():
    from refract.render import qt

    qt.ensure_app()
    m = qt._metrics(qt._font("Arial", 12.0))
    lines, w, h = qt._text_lines(m, "1023\nRejected")
    assert lines == ["1023", "Rejected"] and w == pytest.approx(qt.text_width(m, "Rejected", qt.TRACK_TEXT))
    assert h == pytest.approx(m.lineSpacing() + m.ascent() + m.descent())
