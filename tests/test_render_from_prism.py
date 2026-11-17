"""Graphs rendered from Prism documents' own settings (refract.render.from_prism):
the PCFF decoders, colour conversion, and Prism's default graphs read back
from the batch5 sample (skipped when absent)."""

import os
import struct

import pytest

from refract.render import from_prism
from refract.render.color import to_srgb

ROOT = os.path.join(os.path.dirname(__file__), "..")
SAMPLE = os.path.join(ROOT, "corpus", "manual", "batch5_samples.prism")


def test_generic_rgb_to_srgb():
    # pairs read from Prism's stored colours and its PDF export
    for stored, drawn in [((124, 160, 212), (142, 177, 220)), ((40, 82, 145), (50, 102, 162)),
                          ((160, 160, 164), (176, 176, 179)), ((24, 24, 24), (32, 32, 32)), ((0, 0, 0), (0, 0, 0))]:
        got = to_srgb((*stored, 255))[:3]
        assert all(abs(a - b) <= 1 for a, b in zip(got, drawn, strict=True)), (stored, got, drawn)


def test_text_runs_decode():
    # the default graph title: 14 pt (also 14000), bold, code page 1252
    payload = bytes.fromhex("0100 0400 00000000 0100 0e000000 0900 b0360000 0200 01000000 0a00 e4040000")
    assert from_prism.text_runs(payload) == [(0, {1: 14, 9: 14000, 2: 1, 10: 1252})]
    ts = from_prism._style({1: 12, 2: 2, 4: 0x8C5535})  # italic, colour stored 0x00BBGGRR
    assert ts.size == 12 and ts.italic and not ts.bold
    assert all(abs(a - b) <= 1 for a, b in zip(ts.color[:3], (67, 105, 157), strict=True))


def test_axis_label_style():
    p = bytearray(134)
    struct.pack_into("<H", p, 38, 15)
    p[42] = 2
    p[44:47] = bytes((24, 24, 24))
    ts = from_prism._axis_label_style(bytes(p))
    assert ts.size == 15 and ts.italic and not ts.bold and ts.color[:3] == (32, 32, 32)


@pytest.mark.parametrize("index", [0, 1, 2, 3])
def test_default_graphs_from_file(index):
    if not os.path.exists(SAMPLE):
        pytest.skip("Prism sample not present")
    from refract.formats import open_document
    from refract.formats.zipio import ZipArchive

    p = open_document(SAMPLE)
    g = from_prism.graph(p, index, ZipArchive.open(SAMPLE))
    assert g.family == ["xy", "column", "grouped", "survival"][index]
    assert g.y_length == pytest.approx(144.0)  # 1200 / 600 in
    assert g.x_length == pytest.approx([216.0, 96.0, 144.0, 216.0][index])
    assert g.title_style.size == 14 and g.title_style.bold
    assert g.y_axis.label_style.size == 11 and g.y_axis.label_style.bold
    if index == 0:
        assert g.x_axis.title == "Hours" and g.y_axis.title == ""  # "YTitle" is a hidden placeholder


def test_plot_settings_of_default_graphs():
    if not os.path.exists(SAMPLE):
        pytest.skip("Prism sample not present")
    from refract.formats import open_document
    from refract.formats.pcff import walker

    p = open_document(SAMPLE)
    col = from_prism.plot_settings(walker.parse(p.graphs[1].blob))
    grp = from_prism.plot_settings(walker.parse(p.graphs[2].blob))
    assert len(col) == 3 and len(grp) == 2
    assert all(x["style"] == 3 and x["points"] for x in col + grp)  # column scatter / grouped bars + values
    assert col[0]["symbol_size"] == pytest.approx(4.74) and grp[0]["symbol_size"] == pytest.approx(6.32)
    assert grp[0]["border"] == pytest.approx(2.16)
    assert grp[0]["error"] == "sd" and grp[0]["direction"] == "both"  # Prism's default: mean with SD


def test_title_roles_by_reference():
    if not os.path.exists(SAMPLE):
        pytest.skip("Prism sample not present")
    from refract.formats import open_document
    from refract.formats.zipio import ZipArchive

    g = from_prism.graph(open_document(SAMPLE), 3, ZipArchive.open(SAMPLE))
    assert g.title == "Survival: Two groups"
    assert g.x_axis.title == "Days elapsed" and g.y_axis.title == "Probability of Survival"


def test_error_half_widths():
    from refract.render import build

    sd, n = 2.0, 4
    assert build._half_width(sd, n, "sd") == 2.0
    assert build._half_width(sd, n, "sem") == pytest.approx(1.0)
    assert build._half_width(sd, n, "ci") == pytest.approx(3.182446 * 1.0, rel=1e-5)  # t(0.975, 3)


def test_plot_rect_and_legend_boxes():
    if not os.path.exists(SAMPLE):
        pytest.skip("Prism sample not present")
    from refract.formats import open_document
    from refract.formats.pcff import walker
    from refract.render import qt

    p = open_document(SAMPLE)
    ch = walker.parse(p.graphs[0].blob)
    assert from_prism.plot_rect(ch) == (1650, 2700, 3450, 3900)  # 3 x 2 in, 1/600 in
    assert len(from_prism.object_boxes(ch, 12)) == 2  # two legend entries
    g = from_prism.graph(p, 0)
    lay = qt.layout(g)
    # placed from the file, the legend lands where Prism's default puts it
    cx, cy, tx = lay.legend[0]
    assert cx == pytest.approx(lay.plot[2] + 40.5, abs=0.2)


class _Chunk:
    def __init__(self, tag, payload):
        self.tag, self.payload = tag, payload


def _plot_chunks(rec_bytes=None, head_bytes=None):
    rec = bytearray(321)
    head = bytearray(120)
    head[10], head[12], head[8] = 1, 1, 2
    for k, v in (rec_bytes or {}).items():
        rec[k] = v
    for k, v in (head_bytes or {}).items():
        head[k] = v
    return [_Chunk(0x8020, b"\x09\x00" + bytes(28)), _Chunk(0x8028, bytes(head)), _Chunk(0x009C, bytes(rec))]


def test_plot_settings_shape_line_and_hidden_errors():
    ps = from_prism.plot_settings(_plot_chunks({34: 7, 8: 1, 145: 10, 81: 4}))[0]
    assert ps["shape"] == 7 and from_prism.SHAPES[7] == "triangle" and 7 in from_prism.BORDERED
    assert ps["connect"] and ps["line_width"] == pytest.approx(2.16)
    assert ps["direction"] == "both"
    hidden = from_prism.plot_settings(_plot_chunks(head_bytes={112: 0x41}))[0]
    assert hidden["direction"] == "none" and not hidden["connect"]
    assert [from_prism.SHAPES[c] for c in (1, 2, 3, 4, 5)] == ["square", "triangle", "triangle_down", "diamond", "circle"]
    assert from_prism.plot_settings(_plot_chunks({313: 7}))[0]["fen"] == 7  # the plotted data set's fen id
    gone = from_prism.plot_settings(_plot_chunks({313: 0xFD, 314: 0xFF, 315: 0xFF, 316: 0xFF}))[0]
    assert gone["fen"] == from_prism.DELETED


def test_bracket_and_free_text_annotations():
    import refract.formats.pcff.fields as F

    rect = (600, 600, 1800, 1400)
    bracket = struct.pack("<H4h", 3, 700, 650, 900, 760) + bytes(20)
    leg = [struct.pack("<I2I", 0, x, y) for x, y in ((700, 740), (900, 740), (800, 686))]  # legs, label anchor
    line = struct.pack("<I", 9) + bytes((255, 0, 0, 0))
    text = struct.pack("<H4h", 2, 1000, 500, 1200, 700) + bytes(20)
    ch = [_Chunk(0x8020, bracket), _Chunk(0x00D9, leg[0]), _Chunk(0x00D9, leg[1]), _Chunk(0x00D9, leg[2]),
          _Chunk(0x0023, line),
          _Chunk(0x8020, text), _Chunk(0x802B, struct.pack("<H", 5) + bytes(16)), _Chunk(F.TAG_TEXT, b"n.s"),
          _Chunk(0x002D, bytes.fromhex("0100 0100 00000000 0100 0c000000"))]
    out = from_prism.annotations(ch, rect, used=set())
    br = next(a for a in out if a["kind"] == "bracket")
    U = 72 / 600
    assert br["points"][0] == pytest.approx(((700 - 600) * U, (740 - 600) * U))
    assert br["points"][1][1] == pytest.approx((650 + from_prism.BRACKET_INSET - 600) * U)
    assert br["width"] == pytest.approx(1.44)
    tx = next(a for a in out if a["kind"] == "text")
    assert tx["text"] == "n.s" and tx["cx"] == pytest.approx((1100 - 600) * U)
    assert tx["top"] == pytest.approx((500 + from_prism.TEXT_PAD - 600) * U)
    assert from_prism.annotations(ch, rect, used={5}) == [br]  # a title is no free text


def test_titles_placed_from_file_match_default_layout():
    if not os.path.exists(SAMPLE):
        pytest.skip("Prism sample not present")
    from dataclasses import replace

    from refract.formats import open_document
    from refract.formats.zipio import ZipArchive
    from refract.render import qt

    p = open_document(SAMPLE)
    prism_pages = [(367, 217), (186, 251), (295, 260), (367, 212)]  # Prism's PDF exports, pt
    for i in range(4):
        g = from_prism.graph(p, i, ZipArchive.open(SAMPLE))
        assert g.title_pos is not None and g.x_axis.title_pos is not None and g.y_axis.title_pos is not None
        a = qt.layout(g)
        assert abs(a.width - prism_pages[i][0]) <= 1 and a.height == prism_pages[i][1]
        d = replace(g, title_pos=None, x_axis=replace(g.x_axis, title_pos=None), y_axis=replace(g.y_axis, title_pos=None))
        b = qt.layout(d)  # the default rules put the titles in the same places
        assert a.title_baseline - a.plot[1] == pytest.approx(b.title_baseline - b.plot[1], abs=0.6)
        assert a.x_title_baseline - a.plot[1] == pytest.approx(b.x_title_baseline - b.plot[1], abs=0.6)
        assert a.y_title_baseline_x - a.plot[0] == pytest.approx(b.y_title_baseline_x - b.plot[0], abs=0.6)


def test_xy_plots_stored_last_data_set_first():
    if not os.path.exists(SAMPLE):
        pytest.skip("Prism sample not present")
    from refract.formats import open_document
    from refract.formats.zipio import ZipArchive

    g = from_prism.graph(open_document(SAMPLE), 0, ZipArchive.open(SAMPLE))
    # Prism's default XY graph: Control circles, Treated squares (its PDF legend)
    assert [(s.title, s.symbol) for s in g.series] == [("Control", "circle"), ("Treated", "square")]


def test_multiple_variables_graph_from_its_json(tmp_path):
    """A Prism MV graph is JSON in its sheet (refract.render.mv_prism): its
    variables by data-set uid, a gradient colour by a number, sizes by a
    category; drawn as points with a colour bar and a sizes legend."""
    import json as _json

    from refract.formats import open_document
    from refract.formats.zipio import ZipArchive
    from refract.model import templates as T
    from refract.render import from_prism
    from refract.ui.document import Document

    d = Document.new()
    d.add_table(T.make("multivariable", "MV", sample=True), with_graph=False)
    path = tmp_path / "mv.prism"
    d.save(str(path))
    arc = ZipArchive.open(str(path))
    t = open_document(str(path)).tables[0]
    by = {ds.title: ds.uid for ds in t.datasets}
    doc = _json.loads(arc.read("document.json"))
    uid = "0E3C8D6B-1111-4AAA-8BBB-000000000001"
    graph = {"@class": "MVGraph", "width": 216.0, "height": 144.0, "title": {"text": {"string": "Bubbles"}},
             "axisX": {"title": {"text": {"string": "Age"}}, "segments": [{"lowerLimit": 0.0, "upperLimit": 80.0,
                                                                           "interval": 20.0}]},
             "axisY": {"title": {"text": {"string": "Dose"}}, "segments": [{"lowerLimit": 0.0, "upperLimit": 40.0,
                                                                           "interval": 10.0}]},
             "xVariables": [by["Age"]], "yVariables": [by["Dose"]], "dataSheet": t.sheet_uid,
             "gdoTypes": {"defaults": ["symbols"]},
             "gdoSettings": {"symbols": {"colorVariable": by["Response"], "sizeVariable": by["Sex"],
                                         "colormap": {"@class": "GradientColormap", "colorScheme": "Viridis",
                                                      "colorsTransparencyPercent": 50},
                                         "sizeEvaluator": {"@class": "CategoricalSizeEvaluator", "symbolSize": 6.0,
                                                           "sizesDictionary": {"f": 6.0, "m": 7.0}}}}}
    arc.put(f"graphs/{uid}/sheet.json", _json.dumps({"@class": "GraphSheet", "uid": uid, "fenID": 99,
                                                      "title": "Bubbles", "graph": graph}).encode())
    doc["sheets"].setdefault("graphs", []).append(uid)
    arc.put("document.json", _json.dumps(doc).encode())
    path.write_bytes(arc.to_bytes())
    p, arc = open_document(str(path)), ZipArchive.open(str(path))
    g = from_prism.graph(p, len(p.graphs) - 1, arc)
    assert g.family == "xy" and (g.x_axis.min, g.x_axis.max, g.y_axis.max) == (0.0, 80.0, 40.0)
    assert g.color_bar["cmap"] == "viridis" and g.color_bar["title"] == "Response"
    sizes = sorted({sz for s in g.series for sz in (s.sizes or [])})
    assert sizes == [6.0, 7.0] and {s.title for s in g.series if s.in_legend and s.title} >= {"F", "M"}
    assert sum(len(s.xs) for s in g.series) == len([v for v in t.values(0, 0) if v is not None])
