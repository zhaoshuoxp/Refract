"""Formatting Refract's graphs (docs/ui-spec.md §3.4): the overrides, log
axes, hit testing, the Format Graph / Format Axes dialogs, double-click to
format, undo, and the format saved with the graph."""

import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from refract.model import templates as T
from refract.render import build, qt
from refract.render import formatting as F
from refract.render.model import Axis, Graph, Series


@pytest.fixture(scope="module", autouse=True)
def app(tmp_path_factory):
    os.environ["REFRACT_SETTINGS"] = str(tmp_path_factory.mktemp("settings") / "refract.ini")
    return qt.ensure_app()


def test_overrides_apply():
    g = build.from_table(T.make("grouped", "G", sample=True))
    F.apply(g, {"title": "New", "title_size": 18, "font": "Times New Roman", "legend": False, "width": 4, "height": 3,
                "x": {"title": "Genotype", "angle": 0.0}, "y": {"title": "Count", "min": 0, "max": 50, "tick": 10,
                                                               "minor": 2, "label_size": 9},
                "sets": {"1": {"fill": "#ff0000", "color": "#0000ff", "points": False}, "9": {"fill": "#000000"}}})
    assert (g.title, g.title_style.size, g.font, g.legend) == ("New", 18, "Times New Roman", False)
    assert (g.x_length, g.y_length) == (288.0, 216.0)
    assert g.x_axis.title == "Genotype" and g.x_axis.label_angle == 0.0
    assert (g.y_axis.min, g.y_axis.max, g.y_axis.tick, g.y_axis.minor, g.y_axis.label_style.size) == (0, 50, 10, 2, 9)
    assert g.series[1].fill == (255, 0, 0, 255) and g.series[1].color == (0, 0, 255, 255) and g.series[1].points == []
    assert qt.resolve_axes(g)[1] == (0, 50, 10)
    xy = build.from_table(T.make("xy", "X", sample=True))
    F.apply(xy, {"x": {"log": True, "min": -5}, "sets": {"0": {"symbol": "square", "size": 9, "connect": True}}})
    assert xy.x_axis.log and xy.x_axis.min is None  # no negative limits on a log axis
    assert (xy.series[0].symbol, xy.series[0].symbol_size, xy.series[0].connect) == ("square", 9, True)


def test_merged_removes_none_and_empty():
    f = F.merged({}, ["sets", "0"], {"fill": "#112233"})
    assert f == {"sets": {"0": {"fill": "#112233"}}}
    assert F.merged(f, ["sets", "0"], {"fill": None}) == {}
    assert F.merged({"y": {"min": 1}}, ["y"], {"min": None, "log": True}) == {"y": {"log": True}}


def test_log_axes():
    s = qt.Scale(0.1, 1000.0, 10.0, 0.0, 400.0, log=True)
    assert s.ticks() == [0.1, 1.0, 10.0, 100.0, 1000.0] and s(10.0) == pytest.approx(200.0)
    assert len(s.ticks(1.0)) == 4 * 8  # 2..9 in each of the four decades
    assert [qt.fmt_tick(v, 10.0, True) for v in (0.01, 1.0, 1000.0)] == ["0.01", "1", "1000"]
    g = Graph("L", "xy", [Series("A", "points", [1, 10, 100], [0.5, 4.0, 35.0])], x_axis=Axis(log=True),
              y_axis=Axis(log=True))
    assert qt.resolve_axes(g) == ((1.0, 100.0, 10.0), (0.1, 100.0, 10.0))
    qt.to_image(g, 1.0)  # draws


def test_hit_testing():
    g = build.from_table(T.make("grouped", "G", sample=True))
    lay = qt.layout(g)
    left, top, right, bottom = lay.plot
    s1 = g.series[1]
    assert qt.hit(g, lay, lay.title_cx, lay.title_baseline - 3) == ("title", None)
    assert qt.hit(g, lay, left - 20, (top + bottom) / 2) == ("y", None)
    assert qt.hit(g, lay, (left + right) / 2, bottom + 15) == ("x", None)
    assert qt.hit(g, lay, lay.x(s1.xs[2]), lay.y(s1.ys[2] / 2)) == ("set", 1)
    assert qt.hit(g, lay, *lay.legend[0][:2]) == ("set", 0)
    assert qt.hit(g, lay, right - 2, top + 2) == ("graph", None)


def test_format_graph_dialog_records_only_changes():
    from refract.ui.format_graph import FormatGraphDialog

    g = build.from_table(T.make("grouped", "G", sample=True))
    lay = qt.layout(g)
    d = FormatGraphDialog({}, g, lay, set_index=1)
    assert d.sets.currentRow() == 1 and d.fill.isEnabled() and not d.connect_.isEnabled()
    assert d.result_format() == {}  # nothing changed
    d.fill.set_color("#ff0000")
    d.fill.changed.emit("#ff0000")
    d.points.setChecked(False)
    d.title.setText("Renamed")
    f = d.result_format()
    assert f == {"title": "Renamed", "sets": {"1": {"fill": "#ff0000", "points": False}}}
    d.reset.click()
    assert d.result_format() == {"title": "Renamed"} and d.points.isChecked()


def test_format_axes_dialog():
    from refract.ui.format_graph import FormatAxesDialog

    g = build.from_table(T.make("column", "C", sample=True))
    lay = qt.layout(g)
    d = FormatAxesDialog({"y": {"max": 20.0}}, g, lay, "y")
    assert d.tabs.currentIndex() == 1 and d.fields["y"]["max"].text() == "20"
    assert "angle" in d.fields["x"] and "log" not in d.fields["x"]  # a category axis
    assert d.result_format() == {"y": {"max": 20.0}}
    d.set_text("y", "max", "")  # back to automatic
    d.set_text("y", "min", "1")
    d.fields["y"]["log"].setChecked(True)
    d.fields["x"]["angle"].setCurrentIndex(3)
    assert d.result_format() == {"y": {"min": 1.0, "log": True}, "x": {"angle": 90.0}}


def _window_with_graph():
    from refract.ui.main_window import MainWindow

    w = MainWindow()

    w.new_graph_style = "default"  # the type wizard is tested in test_graph_editing
    w.new_project(T.make("grouped", "Data 1", sample=True))
    w.nav.setCurrentItem(next(it for it in w.sheet_items() if it.data(0, 0x0100) == ("ngraphs", 0)))
    return w


def test_double_click_formats_and_undo(tmp_path):
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent

    from refract.formats import open_document

    w = _window_with_graph()
    assert w.a_format_graph.isEnabled() and w.a_format_axes.isEnabled()
    opened = []

    def answer(d):  # stands in for the user: note which page opened, make a change, press OK
        opened.append((type(d).__name__, d.tabs.currentIndex(), getattr(d, "sets", None) and d.sets.currentRow()))
        if type(d).__name__ == "FormatGraphDialog":
            d.fill.set_color("#00aa00")
            d.fill.changed.emit("#00aa00")
        else:
            d.set_text("y", "max", "60")
        return True

    w._exec = answer
    v = w.current_view()
    v.canvas.resize(800, 600)
    v.canvas.grab()  # paints: the page's place on the canvas is known
    lay, s1 = v.canvas.lay, v.graph.series[1]
    ox, oy = v.canvas._origin
    k = v.canvas._k

    def click(px, py):
        pos = QPointF(ox + px * k, oy + py * k)
        v.canvas.mouseDoubleClickEvent(QMouseEvent(QEvent.MouseButtonDblClick, pos, pos, Qt.LeftButton,
                                                   Qt.LeftButton, Qt.NoModifier))

    click(lay.x(s1.xs[0]), lay.y(s1.ys[0] / 2))  # a bar of the second data set
    assert opened[-1] == ("FormatGraphDialog", 0, 1)
    ng = w.doc.project.native_graphs[0]
    assert ng.format == {"sets": {"1": {"fill": "#00aa00"}}}
    assert w.current_view().graph.series[1].fill == (0, 170, 0, 255)  # redrawn
    v = w.current_view()  # the redraw made a new canvas
    v.canvas.resize(800, 600)
    v.canvas.grab()
    ox, oy = v.canvas._origin
    k = v.canvas._k
    click(v.canvas.lay.plot[0] - 12, v.canvas.lay.plot[1] + 3)  # the Y axis (its tick labels; the empty title is a text to type in)
    assert opened[-1][:2] == ("FormatAxesDialog", 1)
    assert ng.format["y"] == {"max": 60.0} and qt.resolve_axes(w.current_view().graph)[1][1] == 60.0
    out = tmp_path / "f.prism"
    w.doc.save(str(out))
    again = open_document(str(out)).native_graphs[0]
    assert again.format == ng.format
    w.doc.undo.undo()
    w.doc.undo.undo()
    assert ng.format == {} and w.current_view().graph.series[1].fill != (0, 170, 0, 255)


def test_prism_graph_formatted_and_patched_in_place(tmp_path):
    """Level A: a graph from the file formatted in Refract; the save patches
    its own blob (from the blob as opened), undo and save restore the bytes."""
    from refract.formats import open_document
    from refract.formats.pcff import fields as PF
    from refract.formats.pcff import walker as W
    from refract.formats.zipio import ZipArchive
    from refract.ui.document import Document
    from refract.ui.main_window import MainWindow
    from refract.ui.views import GraphView

    path = os.path.join(os.path.dirname(__file__), "..", "corpus", "manual", "batch5_samples.prism")
    if not os.path.exists(path):
        pytest.skip("Prism sample not present")
    w = MainWindow(Document.open(path))
    w.nav.setCurrentItem(next(it for it in w.sheet_items() if it.data(0, 0x0100) == ("graphs", 2)))  # grouped
    v = w.current_view()
    assert isinstance(v, GraphView) and w.a_format_graph.isEnabled()

    def answer(d):
        if type(d).__name__ == "FormatAxesDialog":
            d.set_text("y", "max", "60")
        else:
            d.fill.set_color("#00aa00")
            d.fill.changed.emit("#00aa00")
        return True

    w._exec = answer
    assert w.format_object("y") and w.format_object("set", 0)
    g = w.current_view().graph
    assert g.y_axis.max == 60.0 and g.series[0].fill == (0, 170, 0, 255)
    out = tmp_path / "a.prism"
    touched = w.doc.save(str(out))
    uid = w.doc.project.graphs[2].uid
    assert f"graphs/{uid}/data.bin" in touched
    assert [n for n in touched if n.startswith("graphs/")] == [f"graphs/{uid}/data.bin"]  # only that graph
    ch = W.parse(ZipArchive.open(str(out)).read(f"graphs/{uid}/data.bin"))
    assert PF.AxisSettings.read(PF.axis_settings(ch)[3]).max == 60.0
    again = open_document(str(out))
    from refract.render import from_prism

    assert from_prism.graph(again, 2, ZipArchive.open(str(out))).y_axis.max == 60.0  # read back as written
    w.doc.undo.undo()
    w.doc.undo.undo()
    w.doc.save()
    assert ZipArchive.open(str(out)).read(f"graphs/{uid}/data.bin") == ZipArchive.open(path).read(
        f"graphs/{uid}/data.bin")  # back to the original bytes
