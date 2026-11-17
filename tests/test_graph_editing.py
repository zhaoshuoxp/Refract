"""Graph sheets (docs/ui-spec.md §3.4): the Letter page, text objects that
can be selected, moved, restyled and retyped on the canvas, text boxes,
colour schemes, Magic, the toolbar, and estimation plots."""

import math
import os

import pytest

from refract.model import templates as T
from refract.model.document import DataSet, DataTable
from refract.render import build, formatting, magic, qt, schemes


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ["REFRACT_SETTINGS"] = str(tmp_path_factory.mktemp("settings") / "refract.ini")
    return qt.ensure_app()


def _graph():
    t = T.make("grouped", "Data 1", sample=True)
    g = build.from_table(t)
    g.x_axis.title, g.y_axis.title = "Genotype", "Response"
    g.significance = [{"x1": 0.0, "x2": 1.0, "y": 40.0, "top": 45.0, "label": "**"}]
    return g


def test_text_items_cover_every_text(app):
    g = _graph()
    lay = qt.layout(g)
    items = {t.id: t for t in qt.text_items(g, lay)}
    assert {"title", "x.title", "y.title", "x.labels", "y.labels", "legend.0", "legend.1", "sig.0"} <= set(items)
    t = items["title"]
    cx, cy = (t.rect[0] + t.rect[2]) / 2, (t.rect[1] + t.rect[3]) / 2
    assert qt.text_at(list(items.values()), cx, cy).id == "title"
    y = items["y.title"]
    assert y.rect[3] - y.rect[1] > y.rect[2] - y.rect[0]  # rotated: taller than wide
    assert not items["x.labels"].editable


def test_text_formatting_round_trip(app):
    g = _graph()
    fmt = formatting.with_text({}, "title", {"text": "Renamed", "size": 20, "italic": True})
    fmt = formatting.with_text(fmt, "title", {"move": (5, -3)})
    fmt = formatting.with_text(fmt, "title", {"move": (1, 1)})  # moves add up
    fmt = formatting.with_text(fmt, "legend.1", {"text": "Drug", "bold": True, "color": "#ff0000"})
    fmt = formatting.with_text(fmt, "sig.0", {"text": "p = 0.004", "size": 9})
    fmt = formatting.with_text(fmt, "x.labels", {"size": 8})
    # the title's text and size, and label sizes, stay in their usual (Prism-writable) keys
    assert fmt["title"] == "Renamed" and fmt["title_size"] == 20 and fmt["x"]["label_size"] == 8
    assert fmt["texts"]["title"] == {"italic": True, "dx": 6.0, "dy": -2.0}
    out = formatting.apply(g, fmt)
    assert out.title == "Renamed" and out.title_style.size == 20 and out.title_style.italic
    assert out.offsets["title"] == (6.0, -2.0)
    assert out.series[1].title == "Drug" and out.series[1].legend_style.bold
    assert out.series[1].legend_style.color == (255, 0, 0, 255)
    assert out.significance[0]["label"] == "p = 0.004" and out.significance[0]["style"].size == 9
    lay0, lay1 = qt.layout(_graph()), qt.layout(out)
    t0 = next(t for t in qt.text_items(_graph(), lay0) if t.id == "title")
    t1 = next(t for t in qt.text_items(out, lay1) if t.id == "title")
    c0, c1 = (t0.rect[0] + t0.rect[2]) / 2 - lay0.plot[0], (t1.rect[0] + t1.rect[2]) / 2 - lay1.plot[0]
    assert c1 == pytest.approx(c0 + 6.0, abs=0.01)  # moved 6 pt right of where it was
    img = qt.to_image(out, 1.0)
    assert img.width() > 100
    # removing: a title is emptied, a text box deleted
    fmt2, key = formatting.add_note(fmt, 40, 20, "n = 6")
    assert key == "note.0" and formatting.apply(_graph(), fmt2).annotations[-1]["text"] == "n = 6"
    moved = formatting.with_text(fmt2, key, {"move": (10, 5), "size": 14})
    assert moved["notes"][0] == {"text": "n = 6", "x": 50.0, "y": 25.0, "size": 14}
    assert "notes" not in formatting.remove_text(moved, key)
    assert formatting.remove_text(fmt, "title")["title"] == ""


def test_schemes_and_magic(app):
    g = _graph()
    fmt = schemes.apply({}, g, schemes.BUILT_IN["Colorblind safe (Okabe-Ito)"])
    assert fmt["sets"]["0"] == {"fill": "#e69f00"}  # bars: the fill only
    out = formatting.apply(_graph(), fmt)
    assert out.series[0].fill[:3] == (230, 159, 0)
    style = magic.style_of(out, qt.layout(out))
    target = build.from_table(T.make("grouped", "Other", sample=True))
    m = magic.match({}, target, style, magic.DEFAULT_PARTS)
    assert m["sets"]["0"]["fill"] == "#e69f00" and "title" not in m  # words are not copied by default
    m = magic.match({}, target, style, ["titles"])
    assert m["title"] == "Data 1" and m["y"]["title"] == "Response"
    tpl = magic.template(style)
    assert "title" not in tpl and "range" not in tpl.get("y", {})


def _view_of_native(w):
    from refract.ui.views import NativeGraphView

    for ng in w.doc.project.native_graphs:  # a new table's graph waits for its type: take the default
        if not ng.style:
            w.doc.set_native_options(ng, style="default")
    w.doc.undo.clear()
    for it in w.sheet_items():
        ref = it.data(0, 256)
        if ref and ref[0] == "ngraphs":
            w.nav.setCurrentItem(it)
    v = w.current_view()
    assert isinstance(v, NativeGraphView)
    return v


def test_canvas_page_select_move_edit(app):
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent

    from refract.ui.main_window import MainWindow
    from refract.ui.views import LETTER

    w = MainWindow()
    w.new_project(T.make("grouped", "Data 1", sample=True))
    v = _view_of_native(w)
    assert v.canvas.page == LETTER
    v.canvas.resize(700, 900)
    v.canvas.grab()
    k, (ox, oy) = v.canvas._k, v.canvas._origin
    t = next(t for t in v.canvas.items if t.id == "title")
    cx, cy = (t.rect[0] + t.rect[2]) / 2, (t.rect[1] + t.rect[3]) / 2

    def ev(kind, x, y, buttons=Qt.LeftButton):
        pos = QPointF(ox + x * k, oy + y * k)
        return QMouseEvent(kind, pos, pos, Qt.LeftButton, buttons, Qt.NoModifier)

    v.canvas.mousePressEvent(ev(QEvent.MouseButtonPress, cx, cy))
    assert v.canvas.selected == "title" and w.a_bold.isEnabled() and w.a_bold.isChecked()
    v.canvas.mouseMoveEvent(ev(QEvent.MouseMove, cx + 20, cy + 10))
    v.canvas.mouseReleaseEvent(ev(QEvent.MouseButtonRelease, cx + 20, cy + 10, Qt.NoButton))
    v = w.current_view()
    assert v.current_format()["texts"]["title"] == {"dx": 20.0, "dy": 10.0} and v.selected_text() == "title"
    w._text_style(size=22)
    w.a_italic.setChecked(True)
    w._text_style(italic=True)
    v = w.current_view()
    assert v.graph.title_style.size == 22 and v.graph.title_style.italic and w.size_box.currentText() == "22"
    v.canvas.edit("title")
    v.canvas.editor.setText("Wild type vs mutants")
    v.canvas.finish_edit(True)
    v = w.current_view()
    assert v.graph.title == "Wild type vs mutants"
    key = w.add_text()
    v = w.current_view()
    assert key == "note.0" and v.canvas.editor is not None
    v.canvas.editor.setText("n = 3")
    v.canvas.finish_edit(True)
    assert w.current_view().graph.annotations[-1]["text"] == "n = 3"
    for _ in range(6):  # every change was one undo step (move, size, italic, text, box, its text)
        w.doc.undo.undo()
    assert w.current_view().current_format() == {}
    w.doc.undo.setClean()
    w.close()


def test_colour_schemes_new_edit_and_import(app, tmp_path, monkeypatch):
    """Your Schemes: import the colours of a palette picture's caption (six
    hex codes) from a file, edit the scheme (rename, reorder), start one from
    a library palette; each applied to the shown graph."""
    from refract.render import schemes
    from refract.ui import schemes_dialog as SD
    from refract.ui.main_window import MainWindow

    w = MainWindow()
    w.new_project(T.make("column", "Data 1", sample=True))
    _view_of_native(w)
    caption = tmp_path / "mist_blue_apricot.txt"  # as written under the swatches of the user's picture
    caption.write_text("#6F91B8  #A9CBE3  #D7E7EF\n#E8A49A  #F0C6AA  #A4C5B6\n", encoding="utf-8")
    mist = ["#6F91B8", "#A9CBE3", "#D7E7EF", "#E8A49A", "#F0C6AA", "#A4C5B6"]
    seen = []

    def accept(d):
        seen.append(d)
        return True

    monkeypatch.setattr(w, "_exec", accept)
    from PySide6.QtWidgets import QFileDialog

    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(caption), ""))
    assert w.define_scheme(import_file=True) == "mist_blue_apricot"
    assert SD.custom()["mist_blue_apricot"] == mist
    g = w.current_view().graph
    assert [schemes.colors_of(g)[i].upper() for i in range(3)] == mist[:3]
    # edit: renamed and the first colour moved last
    d = SD.DefineSchemeDialog(mist, "mist_blue_apricot", editing="mist_blue_apricot")
    d.name.setText("Mist blue apricot")
    d.list.setCurrentRow(0)
    for _ in range(5):
        d._move(1)
    monkeypatch.setattr(SD, "DefineSchemeDialog", lambda *a, **k: d)
    assert w.edit_scheme("mist_blue_apricot") == "Mist blue apricot"
    assert "mist_blue_apricot" not in SD.custom() and SD.custom()["Mist blue apricot"] == mist[1:] + mist[:1]
    # customize an existing scheme: start from a library palette
    monkeypatch.undo()
    d2 = SD.DefineSchemeDialog([], "")
    d2.start.setCurrentIndex(d2.start.findText("RColorBrewer Dark2"))
    assert d2.scheme() == ("RColorBrewer Dark2 (mine)", schemes.LIBRARY["RColorBrewer"]["Qualitative"]["Dark2"])
    assert schemes.parse_colors('c("#e64b35", 4dbbd5, "#3C5488FF")') == ["#E64B35", "#4DBBD5", "#3C5488"]
    for n in list(SD.custom()):
        SD.delete_custom(n)
    for dlg in (*seen, d, d2):  # destroyed now, not by the garbage collector after the application
        dlg.deleteLater()
    app.processEvents()
    w.doc.undo.setClean()
    w.close()


def test_ribbon_groups_and_colors_menu(app):
    from refract.ui.main_window import MainWindow

    w = MainWindow()
    assert list(w.ribbon.groups) == ["File", "Sheet", "Undo", "Clipboard", "Analysis", "Change", "Text", "Draw",
                                     "Export", "Help"]
    w.new_project(T.make("column", "Data 1", sample=True))
    _view_of_native(w)
    w._fill_colors_menu()
    names = [a.text() for a in w.colors_menu.actions()]
    assert "Viridis" in names and {"RColorBrewer", "ggsci", "Your Schemes"} <= set(names)
    sub = {a.text(): a.menu() for a in w.colors_menu.actions() if a.menu() is not None}
    brewer = [a.text() for a in sub["RColorBrewer"].actions()]
    assert brewer == ["Qualitative", "Sequential", "Diverging"]  # one level per kind: no long menus
    assert all(len(a.menu().actions()) <= 30 for m in (sub["RColorBrewer"], sub["ggsci"]) for a in m.actions())
    yours = [a.text() for a in sub["Your Schemes"].actions()]
    assert yours[:3] == ["New Color Scheme…", "Customize an Existing Scheme…", "Import Colors…"]
    assert w.apply_scheme("Viridis")
    from refract.ui import schemes_dialog as SD


    assert SD.recent()[0] == "Viridis"
    assert w.apply_scheme("RColorBrewer Set1") and w.apply_scheme("ggsci npg nrc")
    fills = [w.current_view().graph.series[i].fill[:3] for i in range(3)]
    assert fills == [(0xE6, 0x4B, 0x35), (0x4D, 0xBB, 0xD5), (0x00, 0xA0, 0x87)]  # ggsci's npg, in order
    assert SD.recent()[:2] == ["ggsci npg nrc", "RColorBrewer Set1"]
    SD.save_custom("Lab", ["#123456", "#abcdef"])
    assert SD.all_schemes()["Lab"] == ["#123456", "#abcdef"]
    from refract.ui import look

    look.set_setting(SD.DEFAULT_KEY, "Lab")
    t = w.doc.add_table(T.make("xy", "XY", sample=True))
    ng = next(g for g in w.doc.project.native_graphs if g.table is t)
    assert ng.format["sets"]["0"] == {"fill": "#123456", "color": "#123456"}
    look.set_setting(SD.DEFAULT_KEY, "")
    w.doc.undo.setClean()
    w.close()


def test_estimation_plots(app):
    def view(sets):
        return DataTable("E", "view", "y_single", [DataSet(n, [v]) for n, v in sets], max(len(v) for _, v in sets))

    paired = view([("Before", ["1", "2", "3"]), ("After", ["2", "4", "3.5"]), ("After\r-\rBefore", ["1", "2", "0.5"])])
    g = build.estimation_graph(paired, True, "Estimation")
    e = g.estimation
    assert e["pairs"] == [(1.0, 2.0), (2.0, 4.0), (3.0, 3.5)] and e["mean"] == pytest.approx(7 / 6)
    assert e["lo"] < e["mean"] < e["hi"] and e["right_title"] == "Mean of differences"
    assert g.categories[2] == "After\n-\nBefore"
    lay = qt.layout(g)
    assert lay.right_ticks and lay.right_title_left > lay.plot[2]
    zero = next(y for y, txt in lay.right_ticks if float(txt) == 0)
    assert zero == pytest.approx(lay.y(e["mean_a"]))  # the right axis's zero is group A's mean
    unpaired = view([("A", ["1", "2", "3"]), ("B", ["3", "4", "5"]), ("B\r-\rA", ["0.5", "2", "3.5"])])
    u = build.estimation_graph(unpaired, False)
    assert (u.estimation["lo"], u.estimation["mean"], u.estimation["hi"]) == (0.5, 2.0, 3.5)
    assert qt.to_image(g, 1.0).width() > 100 and qt.to_image(u, 1.0).width() > 100


def test_canvas_only_formatting_is_reported_for_prism():
    from refract.formats import graph_patch as GP

    fmt = {"texts": {"title": {"dx": 3}, "legend.0": {"bold": True}}, "notes": [{"text": "n = 3"}],
           "background": "#eeeeee"}
    notes = GP.apply([], fmt, "column", 0, (0, 1, 1), (0, 1, 1))
    assert {"texts moved on the graph", "text styles changed on the graph", "text boxes added in Refract",
            "background, plotting area or axis colours"} <= set(notes)


def test_estimation_plot_from_a_prism_file(app):
    path = os.path.join(os.path.dirname(__file__), "..", "corpus", "auto", "oracle_tables", "grouped_reference",
                        "input.prism")
    if not os.path.exists(path):
        pytest.skip("local corpus file not present")
    from refract.formats import open_document
    from refract.formats.zipio import ZipArchive
    from refract.render import from_prism

    p = open_document(path)
    i = next(k for k, g in enumerate(p.graphs) if g.title.startswith("Estimation Plot"))
    g = from_prism.graph(p, i, ZipArchive.open(path))
    e = g.estimation
    assert e is not None and e["paired"] and len(e["pairs"]) == 3 and g.categories[:2] == ["Primer#1", "Primer#2"]
    # Prism's own drawing: CI -0.00299 .. 0.00624 of the mean difference 0.00163 (graph_4.pdf)
    assert e["mean"] == pytest.approx(0.0016261, abs=1e-6)
    assert (e["lo"], e["hi"]) == (pytest.approx(-0.00299, abs=2e-5), pytest.approx(0.00624, abs=2e-5))


def test_graph_types_draw_on_every_kind(app):
    from refract.render import graph_types as GT

    for gt in GT.TYPES:  # each type, on our sample table of its family and of the other kinds it allows
        for kind, fams in GT.FAMILIES.items():
            if gt.family not in fams:
                continue
            t = T.make(kind, kind, sample=True)
            opts = {"color": "Sex", "size": "Dose"} if gt.family == "multivariable" else {}
            for plot in [k for k, _ in gt.plots] or [None]:
                g = GT.make(t, gt, plot, gt.label, opts)
                assert qt.to_image(g, 0.5).width() > 10, (gt.key, kind, plot)
    box, out = GT.box_stats([1, 2, 3, 4, 5, 6, 7, 8, 100], "tukey")  # Prism's quartiles: rank (n+1)p
    assert (box["q1"], box["med"], box["q3"], box["hi"], out) == (2.5, 5, 7.5, 8, [100])
    box, _ = GT.box_stats([2, 4, 4.5, 5, 6, 12], "min_max")  # E-compare: Prism's IQR of these, 3.5..7.5
    assert (box["q1"], box["q3"], box["lo"], box["hi"]) == (3.5, 7.5, 2, 12)
    k = GT.kde([3.8, 3.9, 4.1, 4.3, 4.6, 5.0])  # violins end two bandwidths past the extremes (Prism)
    assert k[0][0] < 3.2 and k[-1][0] > 5.6
    assert GT.summary([1, 2, 3], "median_range") == (2, 1, 3)
    assert GT.resolve("column", "bars").key == "col_scatter_bar" and GT.resolve("xy", "") is None


def test_new_table_graph_waits_for_its_type(app):
    from refract.render import native
    from refract.ui.graph_wizard import GraphTypeDialog
    from refract.ui.main_window import MainWindow

    w = MainWindow()
    w.new_project(T.make("xy", "XY", sample=True))
    ng = w.doc.project.native_graphs[0]
    assert ng.style == ""  # the graph sheet exists, its type is not chosen yet
    with pytest.raises(native.NoGraphType):
        native.graph(w.doc.project, ng)
    answers = []

    def answer(d):  # stands in for the user: XY data shown as columns, box and whiskers
        assert isinstance(d, GraphTypeDialog) and d.chosen().key == "xy_points"
        d.family.setCurrentIndex(d.family.findData("column"))
        d.tabs.setCurrentIndex(1)
        d.types.setCurrentRow(1)
        d.plot.setCurrentIndex(d.plot.findData("min_max"))
        assert not d.preview.pixmap().isNull()
        answers.append(d.choice())
        return True

    w._exec = answer
    _view_of_native_unset(w)
    assert w.graph_type_dialog()
    assert answers == [("col_box", "min_max", {})] and (ng.style, ng.error) == ("col_box", "min_max")
    # the graph's commands work at once, without showing another sheet first
    assert w.a_colors.isEnabled() and w.a_format_graph.isEnabled() and w.a_export.isEnabled()
    g = w.current_view().graph
    assert g.family == "column" and g.series[0].kind == "box" and g.categories == ["Control", "Treated"]
    w.doc.undo.undo()
    assert ng.style == ""
    w.doc.undo.setClean()
    w.close()


def _view_of_native_unset(w):
    for it in w.sheet_items():
        ref = it.data(0, 256)
        if ref and ref[0] == "ngraphs":
            w.nav.setCurrentItem(it)


def test_every_type_has_a_fixed_icon_and_horizontal_ones_draw(app):
    from refract.render import graph_types as GT
    from refract.ui import type_icons

    keys = [t.key for t in GT.TYPES]
    assert len(keys) == len(set(keys)) >= 95
    for k in keys:
        assert not type_icons.icon(k).isNull()
    g = GT.make(T.make("column", "C", sample=True), GT.BY_KEY["col_box_h"], "tukey", "C")
    lay = qt.layout(g)
    up = qt.layout(GT.make(T.make("column", "C", sample=True), GT.BY_KEY["col_box"], "tukey", "C"))
    # Prism keeps the plot's shape on its side: the values take the bottom length, the categories the left (E-compare)
    assert g.horizontal and lay.horizontal
    assert abs((lay.plot[2] - lay.plot[0]) - (up.plot[2] - up.plot[0])) < 1
    assert abs((lay.plot[3] - lay.plot[1]) - (up.plot[3] - up.plot[1])) < 1
    w = GT.make(T.make("parts_of_whole", "P", sample=True), GT.BY_KEY["waffle"], None, "P")
    assert sum(1 for _ in w.waffle["parts"]) == 4 and qt.to_image(w, 1.0).width() > 100


def test_more_types_survival_errors_and_placeholders(app):
    from refract.render import graph_types as GT

    t = T.make("survival", "S", sample=True)
    g = GT.make(t, GT.BY_KEY["surv_ticks"], None, "S", {"error": "ci"})
    bands = [s for s in g.series if s.dash]
    assert len(bands) == 4 and not any(s.in_legend for s in bands)  # a low and a high bound per curve
    p = GT.make(t, GT.BY_KEY["surv_points"], None, "S", {"error": "se"})
    assert any(e is not None for e in p.series[0].err_lo)
    lay = qt.layout(g)
    assert sum(1 for e in lay.legend if e is not None) == 2  # the bounds are not listed
    three = T.make("grouped", "G", sample=True)
    three.datasets[1].title = "Untreated B"
    three.datasets[0].title = "Untreated A"
    g3 = GT.make(three, GT.BY_KEY["grp3_bars"], "mean_sd", "3")
    assert g3.panel_labels and g3.dividers
    mv = T.make("multivariable", "M", sample=True)
    ba = GT.make(mv, GT.BY_KEY["mv_before_after"], "mean", "M", {"x": "Sex", "y": "Response", "lines": "Dose"})
    assert ba.categories == ["F", "M"] and all(s.connect for s in ba.series) and ba.legend
    # an empty axis title: a place to type one, shown only on screen
    gg = build.from_table(T.make("column", "C", sample=True))
    items = {it.id: it for it in qt.text_items(gg, qt.layout(gg))}
    assert items["y.title"].text == "" and items["y.title"].placeholder == "Y title"
    h = GT.make(T.make("column", "C", sample=True), GT.BY_KEY["col_bar_h"], "mean_sd", "C")
    assert {it.id for it in qt.text_items(h, qt.layout(h))} >= {"title", "y.title"}


def test_estimation_plot_follows_edits(app, tmp_path):
    path = os.path.join(os.path.dirname(__file__), "..", "corpus", "auto", "oracle_tables", "grouped_reference",
                        "input.prism")
    if not os.path.exists(path):
        pytest.skip("local corpus file not present")
    from refract.ui.document import Document

    d = Document.open(path)
    i = next(k for k, g in enumerate(d.project.graphs) if g.title.startswith("Estimation Plot"))
    before = d.prism_graph(i).estimation
    t = next(t for t in d.project.tables if t.title == "AHR")
    d.set_cell(t, t.datasets[1], 0, 0, "0.009")
    after = d.prism_graph(i).estimation
    assert after["pairs"][0][1] != before["pairs"][0][1] and after["mean"] > before["mean"]


def test_objects_selected_formatted_drawn_moved(app):
    """Every graph object can be formatted on its own, as in a slide editor:
    a click on a bar selects its data set and the Format panel sets its fill,
    hatch, border and error bars; the Draw tools draw lines, arrows, boxes and
    ellipses, which are moved, resized by their ends and deleted; a
    significance bracket is moved with its label and given its own line."""
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent

    from refract.ui.main_window import MainWindow

    w = MainWindow()
    w.new_project(T.make("column", "Data 1", sample=True))
    v = _view_of_native(w)
    w.doc.set_native_options(v.ng, style="col_bar")
    v = w.current_view()

    def canvas():
        c = w.current_view().canvas
        c.resize(700, 900)
        c.grab()
        return c

    def ev(c, kind, x, y, buttons=Qt.LeftButton, mods=Qt.NoModifier):
        k, (ox, oy) = c._k, c._origin
        pos = QPointF(ox + x * k, oy + y * k)
        return QMouseEvent(kind, pos, pos, Qt.LeftButton, buttons, mods)

    def drag(a, b):
        c = canvas()
        c.mousePressEvent(ev(c, QEvent.MouseButtonPress, *a))
        c.mouseMoveEvent(ev(c, QEvent.MouseMove, *b))
        c.mouseReleaseEvent(ev(c, QEvent.MouseButtonRelease, *b, Qt.NoButton))

    c = canvas()
    box = qt.object_box(c.graph, c.lay, "set.1")
    cx, cy = (box[0] + box[2]) / 2, box[3] - 8  # inside the second bar
    c.mousePressEvent(ev(c, QEvent.MouseButtonPress, cx, cy))
    c.mouseReleaseEvent(ev(c, QEvent.MouseButtonRelease, cx, cy, Qt.NoButton))
    assert c.selected == "set.1" and v.panel.heading.text().startswith("Data set 2")
    from PySide6.QtWidgets import QComboBox, QDoubleSpinBox

    pattern = v.panel.findChild(QComboBox, "panel_pattern")
    pattern.setCurrentIndex(pattern.findData("/"))
    v = w.current_view()
    v.panel.findChild(QDoubleSpinBox, "panel_border_width").setValue(1.0)
    v = w.current_view()
    assert v.current_format()["sets"]["1"] == {"pattern": "/", "border_width": 1.0}
    s = v.graph.series[1]
    assert s.pattern == "/" and s.border_width == 1.0 and v.canvas.selected == "set.1"
    # draw an arrow, then move it and one of its ends
    w._choose_tool("arrow")
    assert w.a_tools["arrow"].isChecked() and w.current_view().canvas.tool == "arrow"
    left, top = w.current_view().canvas.lay.plot[:2]
    drag((left + 10, top + 10), (left + 60, top + 40))
    v = w.current_view()
    assert v.current_format()["shapes"] == [{"kind": "arrow", "x1": 10.0, "y1": 10.0, "x2": 60.0, "y2": 40.0,
                                             "color": "#000000", "width": 1.0}]
    assert v.canvas.selected == "shape.0" and v.tool is None and not w.a_tools["arrow"].isChecked()
    drag((left + 35, top + 25), (left + 45, top + 30))  # the line's middle: the whole arrow
    drag((left + 70, top + 45), (left + 80, top + 60))  # its head's handle: that end only
    sh = w.current_view().current_format()["shapes"][0]
    assert (sh["x1"], sh["y1"], sh["x2"], sh["y2"]) == (20.0, 15.0, 80.0, 60.0)
    v = w.current_view()
    v.change_object("shape.0", {"color": "#c00000", "width": 2.0, "dash": True})
    assert w.current_view().graph.shapes[0]["color"][:3] == (0xC0, 0, 0)
    # a filled ellipse, then deleted with the Delete key
    w._choose_tool("ellipse")
    drag((left + 100, top + 5), (left + 140, top + 30))
    v = w.current_view()
    v.change_object("shape.1", {"fill": "#ffff00"})
    from PySide6.QtGui import QKeyEvent

    c = canvas()
    assert c.selected == "shape.1"
    c.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Delete, Qt.NoModifier))
    assert [bool(x) for x in w.current_view().current_format()["shapes"]] == [True, False]
    # every change was one undo step
    steps = w.doc.undo.count()
    assert steps >= 8
    w.doc.undo.setClean()
    w.close()


def test_bracket_moves_with_its_label_and_has_its_own_line(app):
    g = _graph()
    fmt = formatting.with_object({}, "bracket.0", {"move": (5.0, -10.0)})
    fmt = formatting.with_object(fmt, "bracket.0", {"color": "#ff0000", "width": 2.0})
    lay0 = qt.layout(_graph())
    formatting.apply(g, fmt)
    lay = qt.layout(g)
    b0, b1 = qt.object_box(_graph(), lay0, "bracket.0"), qt.object_box(g, lay, "bracket.0")
    assert round(b1[0] - b0[0], 1) == 5.0 and round(b1[1] - b0[1], 1) == -10.0
    lab0 = next(t for t in qt.text_items(_graph(), lay0) if t.id == "sig.0")
    lab1 = next(t for t in qt.text_items(g, lay) if t.id == "sig.0")
    assert round(lab1.rect[1] - lab0.rect[1], 1) == -10.0  # the label went with it
    assert g.significance[0]["color"][:3] == (255, 0, 0) and g.significance[0]["width"] == 2.0
    assert qt.object_at(g, lay, (b1[0] + b1[2]) / 2, b1[1]) == "bracket.0"


def test_misty_blue_and_peach_is_built_in():
    """The scheme taken from the user's colour picture ships with the app, in the picture's order."""
    from refract.render import schemes

    assert schemes.BUILT_IN["Misty Blue and Peach"] == ["#6f91b8", "#a9cbe3", "#d7e7ef", "#e8a49a", "#f0c6aa",
                                                        "#a4c5b6"]


def test_every_drawn_kind_renders_hits_and_is_written_as_primitives(app):
    """Draw menu kinds (refract.render.shape_kinds): each is drawn, selected by a click on its marks,
    and written for Prism as lines, arrows, boxes and ellipses, a line with text with a text box."""
    from refract.render import shape_kinds as SK

    g = _graph()
    lay = qt.layout(g)
    for kind in SK.KINDS:
        sh = {"kind": kind, "x1": 20.0, "y1": 20.0, "x2": 90.0, "y2": 50.0, "color": (0, 0, 0, 255), "width": 1.0}
        if kind in SK.LABELLED:
            sh["label"] = "**"
        g.shapes = [sh]
        qt.to_image(g, 1.0, lay=lay)  # draws
        prims = SK.primitives(sh)
        assert prims and all(p["kind"] in SK.PRIMITIVE for p in prims), kind
        p0 = prims[0]
        mx, my = (p0["x1"] + p0["x2"]) / 2, (p0["y1"] + p0["y2"]) / 2
        if p0["kind"] in ("rect", "ellipse"):
            mx, my = p0["x1"], (p0["y1"] + p0["y2"]) / 2  # on its outline
        if p0["kind"] == "ellipse":
            mx = min(p0["x1"], p0["x2"])
        assert qt.object_at(g, lay, lay.plot[0] + mx, lay.plot[1] + my) == "shape.0", kind
    prims, notes = SK.for_prism([{"kind": "bracket", "x1": 10, "y1": 30, "x2": 60, "y2": 30, "label": "***",
                                  "color": "#000000", "width": 1.0}])
    assert [p["kind"] for p in prims] == ["line", "line", "line"] and notes[0]["text"] == "***"
    assert prims[0]["y2"] - prims[0]["y1"] == -SK.LEG  # a flat drag: legs of a significance bracket
    assert notes[0]["x"] == 35.0 and notes[0]["y"] < 30


def test_each_bar_and_brackets_formatted_on_their_own(app):
    g = _graph()
    lay = qt.layout(g)
    fmt = formatting.with_object({}, "set.0", {"bar": 1, "fill": "#ff0000", "pattern": "x"})
    assert fmt["sets"]["0"]["bars"]["1"] == {"fill": "#ff0000", "pattern": "x"}
    formatting.apply(g, fmt)
    assert g.series[0].bar_styles == {1: {"fill": (255, 0, 0, 255), "pattern": "x"}}
    plain = _graph()
    formatting.apply(plain, formatting.with_object({}, "set.0", {"bar": 1, "fill": "#ff0000"}))
    img = qt.to_image(plain, 1.0, lay=lay)
    s = plain.series[0]
    unit = abs(lay.x(1.0) - lay.x(0.0))
    y = int(lay.y(s.ys[1] / 2))
    c = img.pixelColor(int(lay.x(s.xs[1]) - s.width * unit / 4), y)
    d = img.pixelColor(int(lay.x(s.xs[0]) - s.width * unit / 4), int(lay.y(s.ys[0] / 2)))
    assert (c.red(), c.green(), c.blue()) == (255, 0, 0) and (d.red(), d.green(), d.blue()) != (255, 0, 0)
    # a significance bracket's ends stretched by their handles
    g2, lay0 = _graph(), qt.layout(_graph())
    b0 = qt.object_box(_graph(), lay0, "bracket.0")
    fmt = formatting.with_object({}, "bracket.0", {"end": (1, -6.0, 0.0)})
    fmt = formatting.with_object(fmt, "bracket.0", {"end": (2, 10.0, 0.0)})
    formatting.apply(g2, fmt)
    b1 = qt.object_box(g2, qt.layout(g2), "bracket.0")
    assert round(b1[0] - b0[0], 1) == -6.0 and round(b1[2] - b0[2], 1) == 10.0
    lab = next(t for t in qt.text_items(g2, qt.layout(g2)) if t.id == "sig.0")
    assert abs((lab.rect[0] + lab.rect[2]) / 2 - (b1[0] + b1[2]) / 2) < 0.6  # its label stays centred
    # a bracket placed in Prism (an annotation): selected, moved, stretched, hidden
    g3 = _graph()
    g3.significance = []
    g3.annotations = [{"kind": "bracket", "points": [(40.0, 60.0), (40.0, 50.0), (120.0, 50.0), (120.0, 60.0)],
                       "color": (0, 0, 0, 255), "width": 1.0}]
    lay3 = qt.layout(g3)
    assert qt.object_at(g3, lay3, lay3.plot[0] + 80, lay3.plot[1] + 50) == "abr.0"
    fmt = formatting.with_object({}, "abr.0", {"move": (5.0, -4.0)})
    fmt = formatting.with_object(fmt, "abr.0", {"end": (2, 20.0, 0.0)})
    formatting.apply(g3, fmt)
    assert g3.annotations[0]["points"] == [(45.0, 56.0), (45.0, 46.0), (145.0, 46.0), (145.0, 56.0)]
    formatting.apply(g3, formatting.with_object(fmt, "abr.0", {"hidden": True}))
    assert g3.annotations[0]["points"] == []


def test_right_click_menus_patterns_and_scheme_colours(app):
    """Right-click a bar: Format This Bar / Entire Data Set / All Data Sets, with pattern swatches and the
    colours of the graph's scheme first; the Draw menu and palette hold every kind."""
    from PySide6.QtWidgets import QMenu, QToolButton

    from refract.ui import color_menu, context_menu
    from refract.ui.main_window import MainWindow

    w = MainWindow()
    w.new_project(T.make("column", "Data 1", sample=True))
    v = _view_of_native(w)
    w.doc.set_native_options(v.ng, style="col_bar")
    w.apply_scheme("Misty Blue and Peach")
    v = w.current_view()
    assert v.current_format()["scheme"] == "Misty Blue and Peach"
    assert color_menu.scheme() == ("Misty Blue and Peach", schemes.BUILT_IN["Misty Blue and Peach"])
    v.canvas.resize(700, 900)
    v.canvas.grab()
    m = QMenu()
    menus = context_menu._Menus(v)
    s = v.graph.series[0]
    menus.data_set(m, 0, v.canvas.lay.x(s.xs[0]))  # a column graph: one bar per data set
    titles = [a.text() for a in m.actions()]
    assert titles[:3] == ["Format This Bar", "Format Entire Data Set", "Format All Data Sets"]
    this = m.actions()[0].menu()
    pat = next(a.menu() for a in this.actions() if a.text() == "Fill Pattern")
    buttons = [a.defaultWidget() for a in pat.actions()]
    assert len(buttons) == len(formatting.PATTERNS) and isinstance(buttons[0], QToolButton)
    assert buttons[0].iconSize().width() == 56  # swatches, not words alone
    next(b for b in buttons if b.objectName() == "pattern_/").click()
    v = w.current_view()
    assert v.current_format()["sets"]["0"]["bars"]["0"] == {"pattern": "/"}
    # a colour menu: the scheme's colours first
    cm = QMenu()
    picked = []
    color_menu.build(cm, None, picked.append)
    grid = cm.actions()[1].defaultWidget()
    swatches = grid.findChildren(QToolButton)
    assert [b.toolTip() for b in swatches] == schemes.BUILT_IN["Misty Blue and Peach"]
    swatches[3].click()
    assert picked == ["#e8a49a"]
    assert [a.text() for a in cm.actions() if a.text()][-2:] == ["Other Color Schemes", "Custom Color…"]
    # the Draw menu and the toolbar palette
    kinds = [a.text() for a in w.draw_menu.actions()]
    assert "Add Significance Bracket (Bracket with Text)" in kinds and "Rounded rectangle" in kinds
    assert w.ribbon.findChild(QToolButton) is not None
    w._choose_tool("bracket:text")
    c = w.current_view().canvas
    assert c.tool == "bracket" and c.tool_label == "*"
    w.doc.undo.setClean()
    w.close()


def test_objects_beyond_the_graph_box_are_drawn_and_exported(app, tmp_path):
    """A text beyond the graph's box (a drawn bracket's star above the title; texts placed in Prism, a wide
    title) is drawn on the canvas and in the exports, as Prism draws it; the graph stays in place."""
    from refract.ui.views import GraphCanvas

    g = _graph()
    lay0 = qt.layout(g)
    assert qt.overflow(g, lay0) == (0.0, 0.0, 0.0, 0.0)  # nothing outside: as before
    top = lay0.plot[1]
    g.shapes = [{"kind": "bracket", "x1": 10.0, "y1": -top - 30, "x2": 60.0, "y2": -top - 30, "label": "*",
                 "color": (0, 0, 0, 255), "width": 1.0}]  # (layout makes room for the bracket, not its text)
    lay = qt.layout(g)
    ml, mt, mr, mb = qt.overflow(g, lay)
    assert mt > 0 and (ml, mr, mb) == (0.0, 0.0, 0.0)
    img = qt.to_image(g, 1.0, lay=lay, margins=(ml, mt, mr, mb))
    assert (img.width(), img.height()) == (math.ceil(lay.width), math.ceil(lay.height + mt))
    gl, gt_ = lay.plot[0] + ml, lay.plot[1] + mt  # the plot's corner in the image
    bar_y = gt_ - top - 30
    star = [(x, y) for x in range(int(gl + 25), int(gl + 46)) for y in range(max(0, int(bar_y - 14)), int(bar_y - 2))
            if img.pixelColor(x, y).lightness() < 128]
    assert star  # the star above the bracket is drawn (it was cut off before)
    plain = qt.to_image(g, 1.0, lay=lay)
    assert plain.height() == math.ceil(lay.height)  # without margins: the graph's box alone
    w, h = qt.to_pdf(g, str(tmp_path / "g.pdf"))
    assert (w, h) == (lay.width + ml + mr, lay.height + mt + mb)
    c = GraphCanvas(g)
    c.resize(800, 1000)
    c.grab()
    assert c.margins == (ml, mt, mr, mb) and c.graph_rect().width() == pytest.approx(lay.width * c._k)


def test_several_data_sets_chosen_and_bracket_legs_dragged(app):
    """Shift / Cmd-click chooses several data sets: the Format panel's changes go to each, in one undo
    step, and they stay chosen; a bracket's legs are lengthened by dragging their tips."""
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QMenu

    from refract.render import shape_kinds as SK
    from refract.ui import context_menu
    from refract.ui.main_window import MainWindow

    w = MainWindow()
    w.new_project(T.make("column", "Data 1", sample=True))
    v = _view_of_native(w)
    w.doc.set_native_options(v.ng, style="col_bar")

    def canvas():
        c = w.current_view().canvas
        c.resize(700, 900)
        c.grab()
        return c

    def click(c, key, mods=Qt.NoModifier):
        b = qt.object_box(c.graph, c.lay, key)
        k, (ox, oy) = c._k, c._origin
        pos = QPointF(ox + (b[0] + b[2]) / 2 * k, oy + (b[3] - 6) * k)
        c.mousePressEvent(QMouseEvent(QEvent.MouseButtonPress, pos, pos, Qt.LeftButton, Qt.LeftButton, mods))
        c.mouseReleaseEvent(QMouseEvent(QEvent.MouseButtonRelease, pos, pos, Qt.LeftButton, Qt.NoButton, mods))

    c = canvas()
    click(c, "set.0")
    click(c, "set.2", Qt.ShiftModifier)
    assert c.group == ["set.0", "set.2"]
    v = w.current_view()
    assert v.chosen_sets() == ["set.0", "set.2"] and v.panel.heading.text().startswith("2 data sets")
    before = w.doc.undo.count()
    v.change_object("set.0", {"fill": "#123456"})
    v = w.current_view()
    assert w.doc.undo.count() == before + 1
    sets = v.current_format()["sets"]
    assert sets["0"]["fill"] == sets["2"]["fill"] == "#123456" and "fill" not in sets.get("1", {})
    assert v.canvas.group == ["set.0", "set.2"]  # still chosen after the redraw
    m = QMenu()
    context_menu._Menus(v).data_set(m, 2, 0.0)
    assert m.actions()[0].text() == "Format Selected Data Sets (2)"
    click(canvas(), "set.2", Qt.ShiftModifier)  # Shift-click again: out of the choice
    assert w.current_view().canvas.group == ["set.0"]
    # a drawn bracket's right leg dragged down by its tip: that leg alone longer
    v = w.current_view()
    v.add_shape("bracket", 20.0, 30.0, 90.0, 30.0)
    v = w.current_view()
    sh = v.graph.shapes[0]
    tips = SK.leg_tips(sh)
    assert [t[0] for t in tips] == [3, 4] and tips[0][2] == tips[1][2] == 30.0 + SK.LEG
    v.change_object("shape.0", {"end": (4, 0.0, 12.0)})
    sh = w.current_view().current_format()["shapes"][0]
    assert sh["leg2"] == SK.LEG + 12.0 and "leg1" not in sh
    w.doc.undo.setClean()
    w.close()


def test_bracket_legs_of_significance_and_prism_brackets(app):
    g = _graph()
    lay = qt.layout(g)
    h0 = {k: (x, y) for k, x, y in qt.bracket_handles(g, lay, "bracket.0")}
    assert set(h0) == {1, 2, 3, 4} and h0[3][1] - h0[1][1] == qt.BRACKET_LEG
    fmt = formatting.with_object({}, "bracket.0", {"end": (3, 0.0, 10.0)})
    formatting.apply(g, fmt)
    h1 = {k: (x, y) for k, x, y in qt.bracket_handles(g, qt.layout(g), "bracket.0")}
    assert round(h1[3][1] - h1[1][1], 6) == qt.BRACKET_LEG + 10 and round(h1[4][1] - h1[2][1], 6) == qt.BRACKET_LEG
    g3 = _graph()
    g3.annotations = [{"kind": "bracket", "points": [(40.0, 60.0), (40.0, 50.0), (120.0, 50.0), (120.0, 60.0)],
                       "color": (0, 0, 0, 255), "width": 1.0}]
    formatting.apply(g3, formatting.with_object({}, "abr.0", {"end": (4, 0.0, -6.0)}))
    assert g3.annotations[0]["points"][-1] == (120.0, 54.0)  # the right leg shorter, the rest as it was
    assert g3.annotations[0]["points"][0] == (40.0, 60.0)
