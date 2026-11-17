"""Refract's graphs written as Prism graphs (PLAN §2.4 level B, seed and
patch; verified in Prism: E-seed, E-writeback), the compatibility report,
and the colour conversion back to Prism's Generic RGB."""

import json
import os
import struct

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from refract.formats.pcff import fields as F
from refract.formats.pcff import propstore as P
from refract.formats.pcff import walker as W
from refract.formats.zipio import ZipArchive
from refract.model import templates as T
from refract.render import color, qt

ROOT = os.path.join(os.path.dirname(__file__), "..")
LOCAL_SEEDS = os.path.join(ROOT, "corpus", "manual", "batch5_samples.prism")


@pytest.fixture(scope="module", autouse=True)
def app(tmp_path_factory):
    os.environ["REFRACT_SETTINGS"] = str(tmp_path_factory.mktemp("settings") / "refract.ini")
    return qt.ensure_app()


def test_shipped_seeds_hold_nothing_of_a_sample():
    import re

    from refract.formats import seeds

    assert seeds.path() == seeds.SHIPPED
    lib = seeds.library()
    assert set(lib) == {"column", "grouped", "xy", "survival", "parts_of_whole"}
    for k, s in lib.items():
        assert s.blob[:8] == b"PCFFGRA4" and len(s.y_fens) == (1 if k == "parts_of_whole" else 6)
        text = " ".join(m.group().decode() for m in re.finditer(rb"[ -~]{4,}", s.blob))
        text = text.replace("Probability of Survival", "")  # Prism's own default axis title
        for word in ("Entering replicate", "Hours", "Survival", "Control", "Treated", "Days elapsed"):
            assert word not in text
    # the pie (drawn by Prism on Refract's neutral table) keeps its cached texts: only Refract's own
    from refract.render import from_prism

    pie = W.parse(lib["parts_of_whole"].blob)
    assert {t for t, _ in from_prism.text_objects(pie).values()} <= {"", "Total=100", *(f"Row {i}" for i in range(1, 7))}
    assert [c.payload for c in pie if c.tag == 0x0009] == [b"Seed parts_of_whole [Data Set-A]\x00"]
    assert set(os.listdir(seeds.SHIPPED)) == {"index.json", "column.pcff", "grouped.pcff", "xy.pcff",
                                              "survival.pcff", "parts_of_whole.pcff", "types", "objects.json"}
    # the drawn objects' templates (tools/make_object_templates.py): no text but the placeholder
    with open(os.path.join(seeds.SHIPPED, "objects.json")) as f:
        objects = json.load(f)
    texts = [bytes.fromhex(p) for o in objects.values() for tag, p in o["chunks"] if tag == 0x002C]
    assert set(objects) == {"line", "arrow", "rect", "ellipse", "text"} and texts == [b"Note"]
    # the type seeds (tools/make_type_seeds.py): neutral data, none of the sample tables' texts
    from refract.render import graph_types as GT

    with open(os.path.join(seeds.TYPES, "index.json")) as f:
        index = json.load(f)
    assert set(index) <= GT.SEEDED and len(index) >= 20
    assert set(os.listdir(seeds.TYPES)) == {"index.json", *(e["file"] for e in index.values())}
    for key in index:
        s = seeds.type_seed(key)
        assert s is not None and s.blob[:8] == b"PCFFGRA4" and len(s.y_fens) == 6, key
        text = " ".join(m.group().decode() for m in re.finditer(rb"[ -~]{4,}", s.blob))
        for word in ("Untreated", "Treated", "Wild type", "Mutant", "Vehicle", "Exposed", "disease", "Protein",
                     "Standard", "Control"):
            assert word not in text, (key, word)


def test_seeds_from_a_prism_file(monkeypatch):
    from refract.formats import seeds

    if not os.path.exists(LOCAL_SEEDS):
        pytest.skip("local seed file not present")
    monkeypatch.setenv("REFRACT_SEEDS", LOCAL_SEEDS)
    assert set(seeds.library()) == {"column", "grouped", "xy", "survival"}


def test_colour_back_to_generic_rgb():
    for c in [(124, 160, 212, 255), (40, 82, 145, 255), (160, 160, 164, 128)]:
        assert max(abs(a - b) for a, b in zip(color.from_srgb(color.to_srgb(c)), c, strict=True)) <= 1


def _seed(kind):
    from refract.formats import seeds

    return seeds.library()[kind]


def _slots(ch):
    c = next(c for c in ch if c.tag == 0x0014)
    n = struct.unpack_from("<I", c.payload)[0]
    return list(struct.unpack_from(f"<{n}I", c.payload, 4))


def test_transplant_binds_the_table(tmp_path):
    from refract.formats import graph_transplant as GT
    from refract.ui.document import Document

    doc = Document.new()
    doc.add_table(T.make("column", "A", sample=True), with_graph=False)
    t = doc.add_table(T.make("column", "B", sample=True), with_graph=False)
    doc.add_dataset(t)  # 4 data sets; the seed plots 3
    out = tmp_path / "t.prism"
    doc.save(str(out))
    arc = ZipArchive.open(str(out))
    uid = GT.transplant(arc, _seed("column"), t.sheet_uid, "My graph")
    gs = json.loads(arc.read(f"graphs/{uid}/sheet.json"))
    assert gs["inputDataSets"] == [d.uid for d in t.datasets] and gs["title"] == "My graph"
    sheet_fen = json.loads(arc.read(f"data/sheets/{t.sheet_uid}/sheet.json"))["fenID"]
    ch = W.parse(arc.read(f"graphs/{uid}/data.bin"))
    assert _slots(ch) == [sheet_fen]  # 0x0014: the plotted table, else Prism adds another table's sets
    doc_j = json.loads(arc.read("document.json"))
    assert uid in doc_j["sheets"]["graphs"] and doc_j["sheetAttributesMap"][uid] == {"title": "My graph"}
    second = GT.transplant(arc, _seed("column"), t.sheet_uid, "Again")
    fens = [json.loads(arc.read(f"graphs/{g}/sheet.json"))["fenID"] for g in (uid, second)]
    assert fens[0] != fens[1]
    GT.remove_graph(arc, uid)
    assert not any(n.startswith(f"graphs/{uid}/") for n in arc.names())
    assert uid not in json.loads(arc.read("document.json"))["sheets"]["graphs"]


def test_patch_axes_and_colours():
    from refract.formats import graph_patch as GP

    seed = _seed("grouped")
    ch = W.parse(seed.blob)
    notes = GP.apply(ch, {"y": {"min": 0, "max": 50, "tick": 10, "title": "Y"}, "font": "Times New Roman",
                          "sets": {"0": {"fill": "#e07a5f", "symbol": "square"}, "6": {"fill": "#000000"}}},
                     "grouped", len(seed.y_fens), (0, 1, 1), (0.0, 50.0, 10.0))
    m = F.AxisMode.read(F.axis_modes(ch)[1])
    s = F.AxisSettings.read(F.axis_settings(ch)[3])
    assert m.flags & F.AxisMode.MANUAL_RANGE and m.flags & F.AxisMode.MANUAL_TICK
    assert (s.min, s.max, s.major_tick) == (0.0, 50.0, 10.0)
    v, _raw, _tail = P.decode_payload(next(c for c in ch if c.tag == P.TAG).payload)
    plots = [it for it in v.get("SEDObject_Array").items if isinstance(it.get("XYPlot_Map"), P.Dict)]
    fill = plots[0].get("XYPlot_Map").get("PCFF_Plot::fillcolor").raw
    assert tuple(fill) == color.from_srgb((0xE0, 0x7A, 0x5F, 255))
    assert "font" in notes and not any("title" in n or "symbol" in n for n in notes)
    assert any(n.startswith("data set 7: fill colour") for n in notes)  # beyond the seed's plots
    xy = _seed("xy")
    ch = W.parse(xy.blob)
    GP.apply(ch, {"y": {"log": True}, "sets": {"0": {"color": "#d1495b"}}}, "xy", len(xy.y_fens), (0, 30, 5),
             (10.0, 100.0, 10.0))
    s = F.AxisSettings.read(F.axis_settings(ch)[3])
    assert s.log10 == 1 and (s.min, s.max) == (1.0, 2.0)  # log axes store exponents
    v, _raw, _tail = P.decode_payload(next(c for c in ch if c.tag == P.TAG).payload)
    plots = [it for it in v.get("SEDObject_Array").items if isinstance(it.get("XYPlot_Map"), P.Dict)]
    assert tuple(plots[-1].get("XYPlot_Map").get("PCFF_Plot::symbolcolor").raw) == color.from_srgb((0xD1, 0x49, 0x5B, 255))


def test_patch_titles_labels_and_symbols():
    """Titles are written as fixed text (0x802B +8 bit 0x4000 cleared, else
    Prism draws its own), with their size; label size goes to each axis
    setting's 0x00AD and the angle to the 0x0103 copies too; symbol shapes to
    the three shape fields, the size to its code, copy and +289 (E-axes,
    E-pairs)."""
    from refract.formats import graph_patch as GP
    from refract.formats.pcff import texts as TX
    from refract.render import from_prism

    seed = _seed("column")
    ch = W.parse(seed.blob)
    notes = GP.apply(ch, {"title": "Mine", "title_size": 20,
                          "x": {"title": "Groups", "label_size": 9, "angle": 90},
                          "y": {"title": "µg/ml", "title_size": 10, "angle": 45},
                          "sets": {"1": {"symbol": "diamond", "size": 9}, "0": {"points": False}}},
                     "column", len(seed.y_fens), (0, 1, 1), (0.0, 10.0, 2.0))
    texts = from_prism.text_objects(ch)
    gt, xt, yt = TX.graph_title_id(ch), TX.axis_title_id(ch, 0), TX.axis_title_id(ch, 1)
    assert (texts[gt][0], texts[xt][0], texts[yt][0]) == ("Mine", "Groups", "µg/ml")
    assert texts[gt][1].size == 20 and texts[yt][1].size == 10
    for tid in (gt, xt, yt):
        p = ch[TX.index(ch, tid)].payload
        assert not struct.unpack_from("<H", p, 8)[0] & TX.AUTO
    idx = [i for i, c in enumerate(ch) if c.tag == 0x8025 and c.payload and len(c.payload) > 46]
    assert all(ch[i].payload[26] == 0x40 and struct.unpack_from("<H", ch[i].payload, 38)[0] == 9 for i in idx[:3])
    first = ch[idx[0] + 1:idx[1]]
    assert struct.unpack_from("<f", next(c for c in first if c.tag == 0x00AD).payload, 33)[0] == 9.0
    p103 = next(c for c in first if c.tag == 0x0103).payload
    assert [p103[8 + 8 * k] for k in range(struct.unpack_from("<I", p103)[0])] == [0x40, 0x40]
    ad = next(c for c in first if c.tag == 0x00AD).payload  # 90° set: not automatic (E-layoutfix)
    assert not ad[29] & GP.ANGLE_AUTO and ad[GP.ANGLE_SET] == 1
    head, rec = GP.plot_records(ch)[1]
    assert rec.payload[34] == rec.payload[109] == head.payload[60] == 4
    assert rec.payload[81] == head.payload[62] == 6 and struct.unpack_from("<f", rec.payload, 289)[0] == 6.0
    assert set(notes) == {"Y axis label angle 45°", "data set 1: individual values hidden (only over bars)"}


def test_minor_ticks_and_symbol_size_read_back(tmp_path):
    from refract.formats import open_document
    from refract.render import from_prism
    from refract.ui.document import Document

    doc = Document.new()
    doc.add_table(T.make("xy", "XY", sample=True))
    doc.set_native_options(doc.project.native_graphs[0], format={"y": {"minor": 5}, "sets": {"1": {"size": 12.6}}})
    out = tmp_path / "m.prism"
    doc.save(str(out))
    p = open_document(str(out))
    g = from_prism.graph(p, 0, ZipArchive.open(str(out)))
    assert g.y_axis.minor == 5 and g.x_axis.minor == 10  # X: 1 inch between ticks, Prism adds them
    assert abs(g.series[1].symbol_size - 1.58 * 8) < 1e-6


def test_patch_plot_styles_and_error_bars():
    """Bars over the points, SEM, bars without the points: the fields Prism
    wrote in its own graphs of each style (E-pairs)."""
    from refract.formats import graph_patch as GP

    col = _seed("column")
    ch = W.parse(col.blob)
    assert GP.apply(ch, {"sets": {"1": {"points": False}}}, "column", 6, (0, 1, 1), (0.0, 10.0, 2.0),
                    "bars", "sem") == []
    recs = GP.plot_records(ch)
    for i, (h, r) in enumerate(recs):
        assert h.payload[59] == 0 and h.payload[12] == 2
        if i == 1:
            assert all(r.payload[o] == 5 for o in GP.STYLE_COPIES) and r.payload[66] == 0xFF
            assert r.payload[15] == 0 and h.payload[96] == r.payload[85] == 3
        else:
            assert r.payload[15] & GP.BAR and r.payload[133] == GP.SCATTER and r.payload[66] == 0
    ch = W.parse(col.blob)  # the default scatter shows the mean only: no error bars to change
    assert GP.apply(ch, {}, "column", 6, (0, 1, 1), (0.0, 10.0, 2.0), "default", "sem") == []
    assert all(h.payload[59] == GP.NO_ERROR and h.payload[12] == 0 for h, _r in GP.plot_records(ch))
    grp = _seed("grouped")
    ch = W.parse(grp.blob)
    notes = GP.apply(ch, {"sets": {"0": {"points": False}}}, "grouped", 6, (0, 1, 1), (0.0, 10.0, 2.0),
                     "means", "sd")
    assert notes == []  # grouped means are written (E-gmeans); they show no points anyway
    for i, (h, r) in enumerate(GP.plot_records(ch)):
        assert [r.payload[o] for o in GP.STYLE_COPIES] == [1, 1, 7, 1, 7, 1, 7] and h.payload[12] == 1
        assert r.payload[15] == 0 and r.payload[34] == h.payload[60] == GP.MEANS_SHAPES[i]


def test_patch_style_codes_whiskers_and_centres():
    """Styles written by their code alone, box whiskers, connected means and
    the plot's centre and error bars, as Prism drew each in the E-compare
    probes; read back by from_prism.plot_settings."""
    from refract.formats import graph_patch as GP
    from refract.render import from_prism

    col, grp = _seed("column"), _seed("grouped")
    for style, code in (("violin", GP.VIOLIN), ("box", GP.BOX), ("before_after", GP.BEFORE_AFTER)):
        ch = W.parse(col.blob)
        GP.apply(ch, {}, "column", 6, (0, 1, 1), (0.0, 10.0, 2.0), style, "tukey")
        for _h, r in GP.plot_records(ch):
            want = [11, 4, 4, 4, 4, 11, 11] if style == "violin" else [code] * 7  # violins as Prism saves them
            assert [r.payload[o] for o in GP.STYLE_COPIES] == want and r.payload[15] == 0
            assert r.payload[GP.WHISKERS_AT] == (1 if style == "box" else 0)
            assert r.payload[GP.CONNECT] == (style == "before_after")
        ps = from_prism.plot_settings(ch)
        assert ps[0]["style"] == code and ps[0]["whiskers"] == ("tukey" if style == "box" else "min_max")
    ch = W.parse(grp.blob)
    notes = GP.apply(ch, {}, "grouped", 6, (0, 1, 1), (0.0, 10.0, 2.0), "box", "p10_90")
    assert notes == []
    for _h, r in GP.plot_records(ch):  # grouped: the code in three copies and at +67, +15 = 4 (Prism's form)
        assert [r.payload[o] for o in GP.STYLE_COPIES] == [4, 1, 4, 1, 4, 1, 4] and r.payload[125] == 2
        assert r.payload[15] == 4
    ch = W.parse(col.blob)
    GP.apply(ch, {}, "column", 6, (0, 1, 1), (0.0, 10.0, 2.0), "means_line", "mean_sem")
    for h, r in GP.plot_records(ch):
        assert r.payload[133] == GP.MEANS and r.payload[GP.CONNECT] == 1 and (h.payload[59], h.payload[12]) == (0, 2)
    for choice, codes in GP.PLOT_CODES.items():
        ch = W.parse(col.blob)
        GP.apply(ch, {}, "column", 6, (0, 1, 1), (0.0, 10.0, 2.0), "bars_only", choice)
        for h, r in GP.plot_records(ch):
            assert (h.payload[59], h.payload[12]) == codes and r.payload[133] == GP.BARS_ONLY["column"]
        assert from_prism.plot_settings(ch)[0]["plot"] == choice


def test_written_types_read_back_as_drawn(tmp_path):
    """Graph types saved for Prism and read from the file as Prism draws them
    (from_prism): violins, box whiskers, medians with their IQR, the
    horizontal bit."""
    from refract.formats import open_document
    from refract.render import from_prism
    from refract.ui.document import Document

    doc = Document.new()
    col = doc.add_table(T.make("column", "C", sample=True), with_graph=False)
    grp = doc.add_table(T.make("grouped", "G", sample=True), with_graph=False)
    xy = doc.add_table(T.make("xy", "X", sample=True), with_graph=False)
    ct = doc.add_table(T.make("contingency", "K", sample=True), with_graph=False)
    want = [(col, "col_violin", None), (col, "col_box", "tukey"), (col, "col_bar", "median_iqr"),
            (col, "col_bar_h", "mean_sd"), (grp, "grp_violin", None), (grp, "grp_bars", "mean"),
            (col, "col_box_pts", "min_max_points"), (xy, "xy_area", "mean_sd"), (xy, "xy_line", "mean_sd"),
            (ct, "cont_bars", None)]
    for t, style, plot in want:
        ng = doc.add_native_graph(t, title=style, style=style.replace("_pts", ""))
        ng.error = plot
    out = tmp_path / "types.prism"
    doc.save(str(out))
    p, arc = open_document(str(out)), ZipArchive.open(str(out))
    got = {gs.title: from_prism.graph(p, i, arc) for i, gs in enumerate(p.graphs)}
    assert all(s.kind == "violin" and s.box[0]["kde"] for s in got["col_violin"].series)
    b = got["col_box"].series[0].box[0]
    assert b["lo"] == 3.8 and b["hi"] == 5.0  # Tukey whiskers: no value of the sample lies beyond them
    s = got["col_bar"].series[0]  # 3.8 3.9 4.1 4.3 4.6 5.0: median 4.2, Prism's quartiles 3.875 and 4.7
    assert [round(v, 9) for v in (s.ys[0], s.err_lo[0], s.err_hi[0])] == [4.2, 3.875, 4.7]
    assert got["col_bar_h"].horizontal and not got["col_bar"].horizontal
    assert {s.kind for s in got["grp_violin"].series} == {"violin"}
    assert all(lo is None for s in got["grp_bars"].series for lo in s.err_lo)  # the mean only
    assert len(got["col_box_pts"].series[0].points[0]) == 6  # min to max, every value shown
    assert all(s.fill_area and s.connect for s in got["xy_area"].series)
    assert all(s.connect and s.symbol == "none" for s in got["xy_line"].series)
    k = got["cont_bars"]  # a contingency table on the grouped skeleton, bars only
    assert k.family == "grouped" and [s.kind for s in k.series] == ["bar", "bar"]
    assert not any(s.points and any(s.points) for s in k.series)
    assert "cont_bars" not in " ".join(doc.last_report)


def test_broken_axis_scale():
    """A broken Y axis: two segments AXIS_BREAK_GAP apart, values in the gap on
    the lower segment's end, the ticks of both."""
    from refract.render.qt import AXIS_BREAK_GAP, SegmentedScale

    sc = SegmentedScale([(0.0, 40.0, 50.0, 13.0), (50.0, 80.0, 10.0, 130.0)], 0.0, 13.0 + AXIS_BREAK_GAP + 130.0)
    assert sc(0.0) == 0.0 and abs(sc(40.0) - 13.0) < 1e-9 and abs(sc(45.0) - 13.0) < 1e-9
    assert abs(sc(50.0) - (13.0 + AXIS_BREAK_GAP)) < 1e-9 and abs(sc(80.0) - sc.p1) < 1e-9
    assert sc.ticks() == [0.0, 50.0, 60.0, 70.0, 80.0]


def test_patch_minor_ticks_and_the_legend():
    """Minor ticks: the main axis setting's +52 and its 0x00AD no longer
    automatic, category X axes reported; the legend hidden as Prism hides
    it (E-pairs)."""
    from refract.formats import graph_patch as GP

    seed = _seed("xy")
    ch = W.parse(seed.blob)
    notes = GP.apply(ch, {"legend": False, "x": {"minor": 2}, "y": {"minor": 5}, "sets": {"0": {"size": 12.6}}},
                     "xy", len(seed.y_fens), (0.0, 30.0, 10.0), (0.0, 60.0, 20.0))
    idx = [i for i, c in enumerate(ch) if c.tag == 0x8025 and c.payload and len(c.payload) > 52]
    for which, n in ((0, 2), (1, 5)):
        i = idx[3 * which]
        assert ch[i].payload[52] == n
        ad = next(c for c in ch[i + 1:idx[3 * which + 1]] if c.tag == 0x00AD)
        assert not ad.payload[29] & GP.MINOR_AUTO
    assert notes == []
    objects = [c for c in ch if c.tag == 0x8020 and c.payload]
    assert not any(c.payload[:2] == b"\x0c\x00" for c in objects)
    count = next(c for c in ch if c.tag == 0x8018)
    assert struct.unpack_from("<I", count.payload, 4)[0] == len(objects)
    store = next(c for c in ch if c.tag == P.TAG and c.payload)
    assert len(P.decode_payload(store.payload)[0].get("SEDObject_Array").items) == len(objects)
    for h, r in GP.plot_records(ch):
        assert not h.payload[58] & GP.IN_LEGEND and h.payload[113] & GP.NOT_IN_LEGEND and r.payload[113] & 8
    assert W.serialize(ch)[:8] == b"PCFFGRA4"
    head, rec = GP.plot_records(ch)[-1]  # XY plots are stored last data set first
    assert rec.payload[81] == head.payload[62] == 8
    col = _seed("column")
    ch = W.parse(col.blob)
    assert GP.apply(ch, {"x": {"minor": 3}}, "column", len(col.y_fens), (0, 1, 1), (0.0, 10.0, 2.0)) == \
        ["X axis minor ticks (a category axis)"]


def test_patch_axis_lengths_means_and_font(tmp_path):
    """Axis lengths, the column mean-symbol style and the font (E-pairs)."""
    from refract.formats import graph_patch as GP
    from refract.formats.pcff import fonts as FT
    from refract.formats.pcff import texts as TX
    from refract.render import from_prism
    from refract.ui.document import Document

    col = _seed("column")
    ch = W.parse(col.blob)
    Document.new().save(str(tmp_path / "e.prism"))  # a bundle Refract made: no font table yet
    arc = ZipArchive.open(str(tmp_path / "e.prism"))
    assert not arc.has(FT.NAME)
    touched: list[str] = []
    notes = GP.apply(ch, {"width": 3.0, "height": 1.5, "font": "Times New Roman"}, "column", 6,
                     (0, 1, 1), (0.0, 10.0, 2.0), "means", "sem", fonts=lambda n, b: FT.index(arc, n, b, touched))
    assert notes == [] and touched == [FT.NAME]
    table = FT.parse(arc.read(FT.NAME))
    assert [(n, w) for n, w, _r in table[:2]] == [("Arial", 400), ("Arial", 700)]  # Prism's defaults first
    names = {(n, w): k for k, (n, w, _r) in enumerate(table)}
    sets = [c for c in ch if c.tag == 0x8025 and c.payload and len(c.payload) > 46]
    assert struct.unpack_from("<I", sets[0].payload, 30)[0] == 1800 and struct.unpack_from("<I", sets[3].payload, 30)[0] == 900
    x0, y0, x1, y1 = struct.unpack_from("<4h", next(c for c in ch if c.tag == 0x0013).payload, 0)
    assert (x1 - x0, y1 - y0) == (1800, 900)
    assert all(c.payload[94] == 0 for c in ch if c.tag == 0x009E and len(c.payload) > 95)
    for h, r in GP.plot_records(ch):
        assert all(r.payload[o] == GP.MEANS for o in GP.STYLE_COPIES) and h.payload[59] == 0 and h.payload[12] == 2
    runs = [from_prism.text_runs(c.payload) for c in ch if c.tag == 0x002D and c.payload]
    for rs in runs:
        for _start, attrs in rs:
            if TX.FONT in attrs:
                want = names[("Times New Roman", 700 if attrs.get(TX.BOLD) == 1 else 400)]
                assert attrs[TX.FONT] == want
    times = {k for (n, _w), k in names.items() if n == "Times New Roman"}
    assert times and all(struct.unpack_from("<H", c.payload, GP.LABEL_FONT)[0] in times for c in sets)
    assert FT.build(table) == arc.read(FT.NAME)  # the table round-trips
    k = min(times)
    assert FT.index(arc, "Times New Roman", table[k][1] == FT.BOLD) == k  # found, not added


def test_save_writes_prism_graphs_and_keeps_them_in_step(tmp_path):
    from refract.formats import open_document
    from refract.stats import catalog
    from refract.ui.document import Document

    doc = Document.new()
    col = doc.add_table(T.make("column", "C", sample=True))
    doc.add_table(T.make("parts_of_whole", "P", sample=True))
    ng = doc.project.native_graphs[0]
    out = tmp_path / "w.prism"
    touched = doc.save(str(out))
    pie = doc.project.native_graphs[1]
    assert ng.prism_uid and f"graphs/{ng.prism_uid}/" in touched and doc.last_report == []
    p = open_document(str(out))
    assert [g.uid for g in p.graphs] == [ng.prism_uid, pie.prism_uid] and p.native_graphs[0].prism_uid == ng.prism_uid
    assert doc.save() == []  # nothing changed: nothing rewritten
    first = ng.prism_uid
    doc.set_cell(col, col.datasets[0], 0, 0, "9")
    assert not any(n.startswith("graphs/") for n in doc.save())  # Prism redraws data edits itself
    doc.add_analysis(col, catalog.by_key("one_way"), {"compare": "ALL_VS_ALL", "test": "TUKEY"})
    doc.set_native_options(ng, style="means")
    doc.save()
    assert ng.prism_uid != first and not ZipArchive.open(str(out)).has(f"graphs/{first}/sheet.json")
    rep = " ".join(doc.last_report)
    assert "significance stars" in rep and "replaced" in rep and "default style" not in rep  # means: written
    # reopened: the Prism copy is not listed beside its Refract graph
    from refract.ui.main_window import MainWindow

    w = MainWindow(Document.open(str(out)))
    graphs = [it.text(0) for it in w.sheet_items() if it.data(0, 0x0100)[0] in ("graphs", "ngraphs")]
    assert graphs == ["C", "P"] and w.doc.graph_refs() == [(f"refract:{g.uid}", g.title)
                                                          for g in w.doc.project.native_graphs]
    assert "Prism will show differently" in w.report_text() or "Everything" in w.report_text()
    # the Refract graph removed: its Prism copy goes too
    doc.undo.undo()  # style
    doc.undo.undo()  # analysis
    doc.undo.undo()  # cell
    doc.undo.undo()  # parts-of-whole table and its graph
    doc.undo.undo()  # column table and its graph
    doc.save()
    assert open_document(str(out)).graphs == []


def test_pie_graphs(tmp_path):
    """A pie plots the first data set of its table (E-pie); each copy gets its
    own pie plot data (0x80d6: document-unique id, its graph fenID, its plot),
    without which Prism drew the first pie blank. Refract draws Prism's default
    pie: slices by row, no slice or legend entry for blank and zero rows."""
    from refract.render import native
    from refract.ui.document import Document

    doc = Document.new()
    a = doc.add_table(T.make("parts_of_whole", "A", sample=True))
    b = doc.add_table(T.make("parts_of_whole", "B"))
    doc.add_dataset(b, title="Second")
    doc.set_cells(b, [(b.datasets[0], 0, r, v) for r, v in enumerate(["6", "", "0", "3"])]
                  + [(b.datasets[1], 0, r, "1") for r in range(4)] + [(b.row_titles, 0, 0, "One")])
    out = tmp_path / "p.prism"
    doc.save(str(out))
    assert doc.last_report == []
    arc = ZipArchive.open(str(out))
    seen = []
    for ng, t in zip(doc.project.native_graphs, (a, b), strict=True):
        gs = json.loads(arc.read(f"graphs/{ng.prism_uid}/sheet.json"))
        assert gs["inputDataSets"] == [t.datasets[0].uid]
        ch = W.parse(arc.read(f"graphs/{ng.prism_uid}/data.bin"))
        d6 = [c.payload for c in ch if c.tag == 0x80D6]
        plots = {struct.unpack_from("<H", c.payload, 0)[0] for c in ch if c.tag == 0x8028 and c.payload}
        assert len(d6) == 1
        pid, gfen, plot = (struct.unpack_from("<H", d6[0], o)[0] for o in (4, 8, 12))
        assert gfen == gs["fenID"] and plot in plots
        seen.append(pid)
    assert len(set(seen)) == 2
    g = native.graph(doc.project, doc.project.native_graphs[1])
    assert g.title == "" and g.legend_texts == ["One", "Legend"]
    assert g.annotations[0]["text"] == "Total=9" and len(g.legend_pos) == 2
    assert g.legend_fills == [g.series[0].slice_fills[0], g.series[0].slice_fills[3]]


def test_kind_without_a_seed_is_reported(tmp_path, monkeypatch):
    from refract.formats import seeds
    from refract.ui.document import Document

    lib = {k: v for k, v in seeds.library().items() if k != "parts_of_whole"}
    monkeypatch.setattr(seeds, "library", lambda: lib)
    monkeypatch.setenv("REFRACT_GRAPHS", "seed")  # seeds only (the skeleton covers parts of whole)
    doc = Document.new()
    doc.add_table(T.make("parts_of_whole", "P", sample=True))
    doc.save(str(tmp_path / "k.prism"))
    assert doc.project.native_graphs[0].prism_uid is None
    assert doc.last_report == [("P: not written as a Prism graph (Refract cannot write graphs of parts_of_whole "
                                "tables for Prism yet); Refract keeps it")]


def test_survival_graph_with_its_analysis(tmp_path):
    """A survival graph is written with a survival analysis whose Survival
    proportions table it plots (E-survival); the analysis is not listed in
    Refract and goes with the graph."""
    from refract.formats import open_document
    from refract.ui.document import Document
    from refract.ui.main_window import MainWindow

    doc = Document.new()
    t = doc.add_table(T.make("survival", "S", sample=True))
    ng = doc.project.native_graphs[0]
    out = tmp_path / "s.prism"
    doc.save(str(out))
    assert ng.prism_uid and ng.prism_analysis and doc.last_report == []
    arc = ZipArchive.open(str(out))
    a = json.loads(arc.read(f"analyses/{ng.prism_analysis}/sheet.json"))
    assert a["analysisClass"] == "SURVIVAL" and a["title"] == "Survival of S"
    assert a["inputSheets"][0]["uid"] == t.sheet_uid and [r["title"] for r in a["resultSheets"]] == \
        ["Survival proportions"]
    view = json.loads(arc.read(f"analyses/{ng.prism_analysis}/result_sheets/{a['resultSheets'][0]['uid']}.json"))
    sheet = json.loads(arc.read(f"data/sheets/{view['dataSheet']}/sheet.json"))
    gs = json.loads(arc.read(f"graphs/{ng.prism_uid}/sheet.json"))
    assert gs["inputDataSets"] == sheet["table"]["dataSets"] and "ANALYSIS_VIEW" in sheet["flags"]
    assert view["dataSheet"] not in json.loads(arc.read("document.json"))["sheets"]["data"]
    csv = arc.read(f"data/tables/{sheet['table']['uid']}/data.csv").decode().splitlines()
    assert csv[0] == "0,100,100" and csv[1] == "14,87.5,"  # Kaplan-Meier, in percent
    first_set = json.loads(arc.read(f"data/sets/{sheet['table']['dataSets'][0]}.json"))
    assert {"rows": "4", "attributes": ["CENSORED"]} in first_set["replicates"][0]["cellAttributes"]
    ch = W.parse(arc.read(f"graphs/{ng.prism_uid}/data.bin"))
    assert _slots(ch) == [sheet["fenID"]]  # 0x0014: the result table
    # reopened: neither the copy nor its analysis is listed
    w = MainWindow(Document.open(str(out)))
    kinds = [it.data(0, 0x0100)[0] for it in w.sheet_items()]
    assert "results" not in kinds and kinds.count("ngraphs") == 1 and "graphs" not in kinds
    assert w.doc.prism_companion_uids() == {ng.prism_analysis}
    # options changed: graph and analysis rewritten; the old ones are gone
    old_g, old_a = ng.prism_uid, ng.prism_analysis
    doc.set_native_options(ng, format={"y": {"min": 0.0, "max": 100.0, "tick": 25.0}})
    doc.save()
    arc = ZipArchive.open(str(out))
    assert ng.prism_analysis != old_a and not arc.has(f"analyses/{old_a}/sheet.json")
    assert not arc.has(f"graphs/{old_g}/sheet.json") and not arc.has(f"data/sheets/{view['dataSheet']}/sheet.json")
    # table removed: graph, analysis and result tables go
    doc.undo.undo()
    doc.undo.undo()
    doc.save()
    p = open_document(str(out))
    arc = ZipArchive.open(str(out))
    assert p.graphs == [] and p.analyses == [] and not any(n.startswith("data/sets/") and n.endswith(".json") for n in arc.names())


def test_survival_graph_reuses_the_tables_analysis(tmp_path):
    """With a survival analysis on the table, the survival graph plots its
    Survival proportions table (added when it has none) and no companion is
    written; once the analysis is removed, a companion takes its place."""
    from refract.stats import catalog
    from refract.ui.document import Document

    doc = Document.new()
    t = doc.add_table(T.make("survival", "S", sample=True))
    doc.add_analysis(t, catalog.by_key("survival"), {})
    ng = doc.project.native_graphs[0]
    out = tmp_path / "r.prism"
    doc.save(str(out))
    arc = ZipArchive.open(str(out))
    [uid] = json.loads(arc.read("document.json"))["sheets"]["analyses"]
    assert ng.prism_analysis is None and uid == doc.project.analyses[0].uid
    a = json.loads(arc.read(f"analyses/{uid}/sheet.json"))
    view = json.loads(arc.read(f"analyses/{uid}/result_sheets/{a['resultSheets'][0]['uid']}.json"))
    sheet = json.loads(arc.read(f"data/sheets/{view['dataSheet']}/sheet.json"))
    gs = json.loads(arc.read(f"graphs/{ng.prism_uid}/sheet.json"))
    assert view["name"] == "Survival proportions" and gs["inputDataSets"] == sheet["table"]["dataSets"]
    assert doc.save() == []  # nothing changed
    doc.undo.undo()  # the analysis removed: the graph gets a companion
    doc.save()
    arc = ZipArchive.open(str(out))
    assert ng.prism_analysis and json.loads(arc.read("document.json"))["sheets"]["analyses"] == [ng.prism_analysis]
    assert doc.prism_companion_uids() == {ng.prism_analysis}


def test_without_seeds_the_save_reports(tmp_path, monkeypatch):
    """Graphs are built from Refract's skeleton (level C) without seed files;
    a kind with neither is reported."""
    from refract.formats import seeds
    from refract.ui.document import Document

    monkeypatch.setattr(seeds, "CANDIDATES", [])
    monkeypatch.delenv("REFRACT_SEEDS", raising=False)
    doc = Document.new()
    doc.add_table(T.make("grouped", "G", sample=True))
    doc.add_table(T.make("survival", "S", sample=True))
    doc.save(str(tmp_path / "n.prism"))
    assert all(g.prism_uid for g in doc.project.native_graphs) and doc.last_report == []
    monkeypatch.setenv("REFRACT_GRAPHS", "seed")  # seeds only, and none found
    doc = Document.new()
    doc.add_table(T.make("grouped", "G", sample=True))
    doc.save(str(tmp_path / "m.prism"))
    assert doc.project.native_graphs[0].prism_uid is None
    assert doc.last_report and "no seed graph file found" in doc.last_report[0]


def test_donut(tmp_path):
    """A donut: 0x80D6 +20 = 2 (1 = pie), a hole of half the radius (E-donut);
    read back from the Prism copy; offered only for parts-of-whole tables."""
    from refract.formats import open_document
    from refract.render import from_prism, native
    from refract.ui.document import Document

    assert native.styles_for("parts_of_whole") == ["default", "donut"] and "donut" not in native.styles_for("column")
    doc = Document.new()
    doc.add_table(T.make("parts_of_whole", "D", sample=True))
    ng = doc.project.native_graphs[0]
    doc.set_native_options(ng, style="donut")
    assert native.graph(doc.project, ng).series[0].hole == native.DONUT_HOLE
    out = tmp_path / "d.prism"
    doc.save(str(out))
    ch = W.parse(ZipArchive.open(str(out)).read(f"graphs/{ng.prism_uid}/data.bin"))
    assert [struct.unpack_from("<I", c.payload, 20)[0] for c in ch if c.tag == 0x80D6] == [2]
    p = open_document(str(out))
    assert from_prism.graph(p, 0, ZipArchive.open(str(out))).series[0].hole == native.DONUT_HOLE
    doc.set_native_options(ng, style="default")
    doc.save()
    ch = W.parse(ZipArchive.open(str(out)).read(f"graphs/{ng.prism_uid}/data.bin"))
    assert [struct.unpack_from("<I", c.payload, 20)[0] for c in ch if c.tag == 0x80D6] == [1]



def test_refract_and_prism_graphs_stay_one_graph(tmp_path):
    """A graph changed in Prism (here: its title and colours, as Prism writes
    them) is taken into the Refract graph on opening; one deleted in Prism is
    deleted; one only re-saved stays as it was (refract.render.prism_sync)."""
    from refract.formats import graph_transplant as GTR
    from refract.formats.pcff import texts as TX
    from refract.ui.document import Document

    doc = Document.new()
    col = doc.add_table(T.make("column", "C", sample=True), with_graph=False)
    keep = doc.add_native_graph(col, title="kept", style="col_box")
    edit = doc.add_native_graph(col, title="edited", style="col_bar")
    gone = doc.add_native_graph(col, title="gone", style="col_violin")
    out = tmp_path / "one.prism"
    doc.save(str(out))
    assert all(g.prism_base for g in (keep, edit, gone))
    arc = ZipArchive.open(str(out))
    name = f"graphs/{edit.prism_uid}/data.bin"
    ch = W.parse(arc.read(name))
    assert TX.set_text(ch, TX.graph_title_id(ch), "Edited in Prism")
    from refract.formats import graph_patch as GP

    GP._colors(ch, {"0": {"fill": "#c81e1e"}}, 3, False, [])  # the first data set's bars recoloured
    arc.put(name, W.serialize(ch))
    GTR.remove_graph(arc, gone.prism_uid)
    doc_json = json.loads(arc.read("document.json"))
    doc_json["sheets"]["graphs"] = [u for u in doc_json["sheets"]["graphs"] if u != gone.prism_uid]
    arc.put("document.json", json.dumps(doc_json).encode())
    out.write_bytes(arc.to_bytes())
    back = Document.open(str(out))
    titles = [g.title for g in back.project.native_graphs]
    assert titles == ["kept", "edited"]
    e = back.project.native_graphs[1]
    fill = e.format["sets"]["0"]["fill"]
    assert e.format["title"] == "Edited in Prism" and abs(int(fill[1:3], 16) - 0xC8) <= 2 and int(fill[3:5], 16) < 0x30
    rep = " ".join(back.sync_report)
    assert "gone: deleted in Prism" in rep and "edited: changed in Prism" in rep and "kept" not in rep
    assert back.project.native_graphs[0].format == {}


def test_seeded_types_written_and_read_back(tmp_path):
    """The types written from Prism's own graphs of them (type seeds, E-types)
    are written as Prism graphs and read back as the same type."""
    from refract.formats import open_document
    from refract.formats.pcff import walker as PW
    from refract.render import from_prism
    from refract.ui.document import Document

    doc = Document.new()
    col = doc.add_table(T.make("column", "C", sample=True), with_graph=False)
    grp = doc.add_table(T.make("grouped", "G", sample=True), with_graph=False)
    xy = doc.add_table(T.make("xy", "X", data_format="y_replicates", replicates=3, sample=True), with_graph=False)
    pw = doc.add_table(T.make("parts_of_whole", "P", sample=True), with_graph=False)
    want = [(col, "col_floating"), (grp, "grp_stacked"), (grp, "grp_bars_sep"), (grp, "grp_scatter_sep"),
            (xy, "xy_replicates"), (xy, "xy_rep_lines"), (xy, "xy_bars"), (pw, "pow_stacked")]
    for t, style in want:
        doc.add_native_graph(t, title=style, style=style)
    out = tmp_path / "seeded.prism"
    doc.save(str(out))
    assert not [r for r in doc.last_report if "default graph" in r or "not written" in r], doc.last_report
    p, arc = open_document(str(out)), ZipArchive.open(str(out))
    by_ds = {ds.uid: t for t in p.tables for ds in t.datasets if ds.uid}
    for i, gs in enumerate(p.graphs):
        t = next(by_ds[u] for u in gs.input_datasets if u in by_ds)
        ch = PW.parse(gs.blob)
        head = next(c.payload for c in ch if c.tag == 0x0013 and c.payload)
        if gs.title == "pow_stacked":
            assert from_prism.graph(p, i, arc).series[0].stacked_bar
            continue
        assert from_prism.type_of(t, from_prism.plot_settings(ch), head) == gs.title, gs.title


def test_second_batch_types_written_and_read_back(tmp_path):
    """The types of the second reference batch (E-types round 2): horizontal
    stacked and separated bars, survival staircases with symbols and deaths
    with ticks, nested box / floating / violin from Prism's own graphs; the
    horizontal grouped means, violins and floating bars on Prism's own
    horizontal seeds; the parts' bar on its side as its chart kind."""
    from refract.formats import open_document
    from refract.formats.pcff import walker as PW
    from refract.render import from_prism
    from refract.ui.document import Document

    doc = Document.new()
    grp = doc.add_table(T.make("grouped", "G", sample=True), with_graph=False)
    nest = doc.add_table(T.make("nested", "N", sample=True), with_graph=False)
    surv = doc.add_table(T.make("survival", "S", sample=True), with_graph=False)
    pw = doc.add_table(T.make("parts_of_whole", "P", sample=True), with_graph=False)
    want = [(grp, "grp_stacked_h"), (grp, "grp_bars_sep_h"), (grp, "grp_means_h"), (grp, "grp_violin_h"),
            (grp, "grp_floating_h"), (nest, "nest_box"), (nest, "nest_floating"), (nest, "nest_violin"),
            (surv, "surv_steps_symbols"), (surv, "surv_inverted_ticks"), (pw, "pow_stacked_h")]
    for t, style in want:
        doc.add_native_graph(t, title=style, style=style)
    out = tmp_path / "second.prism"
    doc.save(str(out))
    assert not [r for r in doc.last_report if "default graph" in r or "upright" in r or "not written" in r], \
        doc.last_report
    p, arc = open_document(str(out)), ZipArchive.open(str(out))
    tables = {"grp": next(t for t in p.tables if t.kind == "grouped"), "nest": next(t for t in p.tables if t.kind == "nested"),
              "surv": next(t for t in p.tables if t.kind == "survival")}
    for i, gs in enumerate(p.graphs):
        ch = PW.parse(gs.blob)
        head = next(c.payload for c in ch if c.tag == 0x0013 and c.payload)
        ps = from_prism.plot_settings(ch)
        g = from_prism.graph(p, i, arc)
        key = gs.title
        if key == "pow_stacked_h":
            assert g.series[0].stacked_bar and g.horizontal
            continue
        t = tables[key.split("_")[0]]
        if key.endswith("_h"):
            assert g.horizontal, key
        if key in ("grp_stacked_h", "grp_bars_sep_h"):
            assert from_prism.type_of(t, ps, head) == key[:-2]
        elif key == "grp_means_h":
            assert ps[0]["style"] == 7
        elif key == "grp_violin_h":
            assert ps[0]["style"] == from_prism.VIOLIN
        elif key == "grp_floating_h":
            assert ps[0]["floating"]
        else:
            assert from_prism.type_of(t, ps, head) == key, key


def test_wizard_says_what_prism_shows():
    """The graph wizard says, per type, whether Prism shows the same graph:
    staircases without ticks and contingency bars stacked to 100 % have no
    Prism graph (Prism's Create New Graph window, the user, 2026-11-16)."""
    from refract.render import graph_types as GT

    assert GT.in_prism(GT.BY_KEY["surv_plain"]).endswith("(Prism has no such graph)")
    assert GT.in_prism(GT.BY_KEY["cont_percent"]).endswith("(Prism has no such graph)")
    for k in ("grp_violin_h", "nest_violin", "pow_stacked_h", "grp_stacked_h", "col_box_h"):
        assert GT.in_prism(GT.BY_KEY[k]) == "In Prism: the same graph", k
    assert GT.prism_style(GT.BY_KEY["surv_plain"])[1].startswith("graph type")


def test_bubble_graph_by_a_number_as_prism_draws_it(tmp_path):
    """A bubble graph coloured and sized by a numeric variable: a viridis
    gradient 50 % clear with its colour bar, and Prism's sizes legend (the
    smallest, the geometric middle, the largest value: E-mv), drawn by
    Refract from the settings it writes to Prism, and read back the same."""
    from refract.formats import open_document
    from refract.render import from_prism
    from refract.render import graph_types as GT
    from refract.ui.document import Document

    doc = Document.new()
    mv = doc.add_table(T.make("multivariable", "MV", sample=True), with_graph=False)
    b = doc.add_native_graph(mv, title="bubbles", style="mv_bubble")
    b.options = {"x": "Age", "y": "Dose", "color": "Response", "size": "Response"}
    g = GT.make(mv, GT.BY_KEY["mv_bubble"], None, "bubbles", b.options)
    assert g.color_bar["cmap"] == "viridis" and g.color_bar["alpha"] == 128
    assert [e[0] for e in g.size_legend["entries"]] == ["1.80", "3.26", "5.90"]
    out = tmp_path / "bubbles.prism"
    doc.save(str(out))
    arc = ZipArchive.open(str(out))
    fig = json.loads(arc.read(f"graphs/{b.prism_uid}/sheet.json"))["graph"]["gdoSettings"]["symbols"]
    assert fig["colormap"]["@class"] == "GradientColormap" and fig["colormap"]["colorScheme"] == "Viridis"
    p = open_document(str(out))
    i = next(k for k, gs in enumerate(p.graphs) if gs.uid == b.prism_uid)
    back = from_prism.graph(p, i, arc)
    assert back.color_bar == {**g.color_bar, "title": back.color_bar["title"]}
    assert back.size_legend == g.size_legend
    assert sorted(v for s in back.series for v in s.sizes) == sorted(v for s in g.series for v in s.sizes)
    qt.to_png(g, str(tmp_path / "b.png"), dpi=72)  # draws


def test_multiple_variables_graphs_written_as_prism_mv_graphs(tmp_path):
    """Bubble and scatter graphs of a Multiple-variables table are written as
    Prism's MV graphs (JSON in the sheet: refract.formats.mv_writer) with the
    variables, the colours by category and the sizes, and read back."""
    from refract.formats import open_document
    from refract.render import from_prism
    from refract.ui.document import Document

    doc = Document.new()
    mv = doc.add_table(T.make("multivariable", "MV", sample=True), with_graph=False)
    b = doc.add_native_graph(mv, title="bubbles", style="mv_bubble")
    b.options = {"x": "Age", "y": "Response", "color": "Sex", "size": "Dose"}
    s = doc.add_native_graph(mv, title="scatter", style="mv_scatter")
    s.options = {"x": "Age", "y": "Dose"}
    out = tmp_path / "mv.prism"
    doc.save(str(out))
    assert not [r for r in doc.last_report if "bubbles" in r or "scatter" in r], doc.last_report
    arc = ZipArchive.open(str(out))
    by = {ds.title: ds.uid for ds in mv.datasets}
    g = json.loads(arc.read(f"graphs/{b.prism_uid}/sheet.json"))["graph"]
    fig = g["gdoSettings"]["symbols"]
    assert g["@class"] == "MVGraph" and g["xVariables"] == [by["Age"]] and g["yVariables"] == [by["Response"]]
    assert fig["colorVariable"] == by["Sex"] and set(fig["colormap"]["colorsDictionary"]) == {"f", "m"}
    assert fig["sizeVariable"] == by["Dose"] and fig["sizeEvaluator"]["customMinimalValue"] == 10.0
    p = open_document(str(out))
    i = next(k for k, gs in enumerate(p.graphs) if gs.uid == b.prism_uid)
    back = from_prism.graph(p, i, ZipArchive.open(str(out)))
    sizes = sorted({round(v, 2) for s_ in back.series for v in (s_.sizes or [])})
    assert sizes == [4.0, 5.66, 6.93]  # Prism's areas in proportion to the value (E-mv)
    assert json.loads(arc.read(f"graphs/{s.prism_uid}/sheet.json"))["graph"]["gdoSettings"]["symbols"][
        "colormap"]["@class"] == "SingleColormap"


def test_widths_patterns_and_drawn_objects_written_for_prism(tmp_path):
    """Border, line and error-bar widths, hatch patterns, and lines, arrows,
    rectangles, ellipses and text boxes drawn in Refract are written as
    Prism stores them (E-elements: checked in Prism's own drawing) and read
    back from the file."""
    from refract.formats import graph_patch as GP
    from refract.formats import open_document
    from refract.formats.pcff import walker as PW
    from refract.render import from_prism
    from refract.ui.document import Document

    doc = Document.new()
    c = doc.add_table(T.make("column", "C", sample=True), with_graph=False)
    g = doc.add_native_graph(c, title="parts", style="col_bar")
    g.format = {"sets": {"0": {"border_width": 0.72, "pattern": "/", "fill": "#ffffff"},
                         "1": {"border_width": 0, "error_width": 2.88, "pattern": "x bold", "pattern_color": "#0000ff"},
                         "2": {"border_width": 3.6, "pattern": "bricks"}},
                "shapes": [{"kind": "line", "x1": 10, "y1": 10, "x2": 80, "y2": 10, "color": "#c00000", "width": 2.16},
                           {"kind": "arrow", "x1": 100, "y1": 20, "x2": 60, "y2": 50, "width": 1.44},
                           {"kind": "rect", "x1": 5, "y1": 60, "x2": 40, "y2": 85, "fill": "#ffff00", "width": 0.72},
                           {"kind": "ellipse", "x1": 70, "y1": 70, "x2": 120, "y2": 95}],
                "notes": [{"text": "n = 3 mice", "x": 60, "y": 110}]}
    out = tmp_path / "parts.prism"
    doc.save(str(out))
    assert not [r for r in doc.last_report if r.startswith("parts")], doc.last_report
    p, arc = open_document(str(out)), ZipArchive.open(str(out))
    ch = PW.parse(p.graphs[0].blob)
    recs = GP.plot_records(ch)
    h, r = recs[0][0].payload, recs[0][1].payload
    assert h[94] == r[149] == 8 and struct.unpack_from("<f", r, 265)[0] == 6.0  # 0.72 pt in its three copies
    assert h[96] == r[85] == GP.PATTERN_CODES["/"] and r[224] == 0xFF
    assert recs[1][0].payload[122] == recs[1][1].payload[153] == 11  # 2.88 pt error bars
    ps = from_prism.plot_settings(ch)
    assert [x["pattern"] for x in ps] == ["/", "x bold", "bricks"] and ps[1]["error_width"] == pytest.approx(2.88)
    back = from_prism.graph(p, 0, arc)
    assert [s.pattern for s in back.series] == ["/", "x bold", "bricks"]
    assert [round(s.border_width, 2) for s in back.series] == [0.72, 0.0, 3.6]
    kinds = [a["kind"] for a in back.annotations]
    assert kinds.count("bracket") == 2 and kinds.count("shape") == 2 and "text" in kinds
    line = next(a for a in back.annotations if a["kind"] == "bracket" and not a["arrow"])
    assert line["points"][0] == pytest.approx((10.0, 10.0), abs=0.2) and line["color"][:3][0] > 180
    assert next(a for a in back.annotations if a["kind"] == "bracket" and a["arrow"])["points"][1] == \
        pytest.approx((60.0, 50.0), abs=0.2)
    rect = next(a["shape"] for a in back.annotations if a["kind"] == "shape" and a["shape"]["kind"] == "rect")
    assert (rect["x1"], rect["y2"]) == (pytest.approx(5.0, abs=0.2), pytest.approx(85.0, abs=0.2))
    assert rect["fill"][:3] == pytest.approx((255, 255, 0), abs=15) and rect["width"] == pytest.approx(0.72)  # colour round trip
    assert next(a for a in back.annotations if a["kind"] == "text")["text"] == "n = 3 mice"


def test_heat_maps_written_for_prism(tmp_path):
    """Heat maps are written from Prism's own (E-heat): the copy names its
    own graph (fenID), its chart ids count with pies', the cell caches are
    sized for the table (Prism fills in the values); read back as heat maps."""
    from refract.formats import graph_patch as GP
    from refract.formats import open_document
    from refract.formats.pcff import walker as PW
    from refract.render import from_prism
    from refract.render import graph_types as GT
    from refract.ui.document import Document

    doc = Document.new()
    t = doc.add_table(T.make("grouped", "G", n_sets=4, sample=False), with_graph=False)
    doc.set_cells(t, [(ds, s, r, str(10 * j + r + s)) for j, ds in enumerate(t.datasets)
                      for s in range(len(ds.subcolumns)) for r in range(5)])
    doc.add_native_graph(t, title="heat", style="grp_heat_viridis")
    doc.add_native_graph(t, title="magma", style="grp_heat_magma")
    out = tmp_path / "heat.prism"
    doc.save(str(out))
    assert any("Prism draws viridis" in r for r in doc.last_report if r.startswith("magma"))
    assert not [r for r in doc.last_report if r.startswith("heat")]
    p, arc = open_document(str(out)), ZipArchive.open(str(out))
    for i, gs in enumerate(p.graphs):
        ch = PW.parse(gs.blob)
        cache = next(c.payload for c in ch if c.tag == 0x80F4)
        assert struct.unpack_from("<2I", cache, GP.HEAT_DIMS) == (5, 4)
        assert struct.unpack_from("<H", cache, 8)[0] == gs.fen  # the heat map names its own graph
        cols = [c.payload for c in ch if c.tag == 0x80F6]
        assert cols and all(len(c) == GP.HEAT_RECORDS + 5 * GP.HEAT_RECORD for c in cols)
        g = from_prism.graph(p, i, arc)
        assert g.heatmap is not None and g.heatmap["rows"] == ["1", "2", "3", "4", "5"]
        assert g.heatmap["cols"] == ["A", "B", "C", "D"] and g.title == ""
    assert GT.in_prism(GT.BY_KEY["grp_heat_viridis"]) == "In Prism: the same graph"
