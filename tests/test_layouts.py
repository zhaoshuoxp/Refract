"""Layouts and families (docs/ui-spec.md §1, §3.5): Prism layouts read for
display, Refract's layouts (place, move, resize, arrange, export, save), and
the navigator grouped by family."""

import json
import os
import struct

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from refract.formats.pcff import walker as W
from refract.model import templates as T
from refract.render import page as PG
from refract.render import prism_layout as PL
from refract.render import qt

ROOT = os.path.join(os.path.dirname(__file__), "..")
LAYOUT_SAMPLE = os.path.join(ROOT, "corpus", "auto", "convert_xml", "Combine_graphs_in_layout", "resaved.prism")


@pytest.fixture(scope="module", autouse=True)
def app(tmp_path_factory):
    os.environ["REFRACT_SETTINGS"] = str(tmp_path_factory.mktemp("settings") / "refract.ini")
    return qt.ensure_app()


def _blob(objects):
    """A layout blob: root, then one 0x8020 per (fen, frame in 1/600 in, own size)."""
    ch = [W.Chunk(0, 0x8001, b"\0" * 12, 0)]
    for fen, rect, own in objects:
        ch.append(W.Chunk(0, 0x8020, struct.pack("<H12hHH", 11, *rect, *rect, *rect, 0, 0x4000), 1))
        ch.append(W.Chunk(0, 0x0084, b"\0\0", 2))
        if fen is not None:
            ch.append(W.Chunk(0, 0x002F, struct.pack("<H", fen), 2))
        ch.append(W.Chunk(0, 0x0030, struct.pack("<HH", *own), 2))
        ch.append(W.Chunk(0, 0x4020, None, 1))
    ch.append(W.Chunk(0, 0x4001, None, 0))
    return W.serialize(ch)


def test_placed_objects_of_a_layout_blob():
    blob = _blob([(1, (600, 300, 3000, 1800), (3600, 2250)), (None, (0, 0, 600, 600), (600, 600))])
    objs = PL.placed(blob)
    assert [o.fen for o in objs] == [1, None]
    assert objs[0].frame == (72.0, 36.0, 360.0, 216.0) and objs[0].own == (432.0, 270.0)


def test_grid_fit_and_hit():
    boxes = PG.grid(3, 612, 792, 2)
    assert len(boxes) == 3 and boxes[0][:2] == (36.0, 36.0) and boxes[1][0] > boxes[0][0] + boxes[0][2]
    assert boxes[2][1] > boxes[0][1] and boxes[2][0] == boxes[0][0]
    from refract.render import build

    g = build.from_table(T.make("column", "C", sample=True))
    p = PG.fit(g, 100, 100, 200, 400)
    x0, y0, x1, y1 = p.box
    assert x0 >= 100 - 1e-6 and x1 <= 300 + 1e-6 and abs((x0 + x1) / 2 - 200) < 1e-6  # fitted and centred
    page = PG.Page(612, 792, [p])
    assert PG.item_at(page, (x0 + x1) / 2, (y0 + y1) / 2) == 0 and PG.item_at(page, 10, 10) is None
    assert PG.to_image(page, 0.5).width() == 306


def _doc_with_graphs():
    from refract.ui.document import Document

    doc = Document.new()
    doc.add_table(T.make("column", "Data 1", sample=True))
    doc.add_table(T.make("grouped", "Data 2", sample=True))
    return doc


def test_layout_editing_saved_and_undone(tmp_path):
    from refract.formats import native_graphs as NG
    from refract.formats import open_document
    from refract.formats.zipio import ZipArchive

    doc = _doc_with_graphs()
    refs = [r for r, _t in doc.graph_refs()]
    assert len(refs) == 2 and all(r.startswith("refract:") for r in refs)
    nl = doc.add_layout(refs=refs, cols=2)
    assert nl.title == "Layout 1" and len(nl.items) == 2 and nl.items[1].x > nl.items[0].x
    page = PG.native_page(nl, doc.graph_for)
    assert len(page.items) == 2 and not page.notes
    moved = [type(i)(i.graph, 10, 20, i.w, i.h) for i in nl.items]
    assert doc.set_layout(nl, items=moved)
    assert (nl.items[0].x, nl.items[0].y) == (10, 20)
    assert doc.arrange_layout(nl, 1) and nl.items[1].y > nl.items[0].y + nl.items[0].h
    out = tmp_path / "l.prism"
    touched = doc.save(str(out))
    assert NG.LAYOUTS in touched
    again = open_document(str(out))
    assert [len(x.items) for x in again.native_layouts] == [2] and again.native_layouts[0].uid == nl.uid
    assert {g.uid for g in again.native_graphs} == {r.split(":")[1] for r in refs}  # the references hold
    pdf = tmp_path / "l.pdf"
    PG.export(page, str(pdf))
    assert pdf.read_bytes().startswith(b"%PDF")
    for _ in range(3):
        doc.undo.undo()  # arrange, move, the layout
    assert doc.project.native_layouts == []
    doc.save()
    assert not ZipArchive.open(str(out)).has(NG.LAYOUTS)
    doc.undo.redo()
    assert doc.project.native_layouts[0] is nl and len(nl.items) == 2


def test_layout_view_and_canvas_drag():
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent

    from refract.ui.main_window import MainWindow

    w = MainWindow()

    w.new_graph_style = "default"  # the type wizard is tested in test_graph_editing
    w.new_project(T.make("column", "Data 1", sample=True))
    w.nav.setCurrentItem(next(it for it in w.sheet_items() if it.data(0, 0x0100) == ("ngraphs", 0)))
    w.new_layout()  # with the shown graph
    v = w.current_view()
    assert type(v).__name__ == "NativeLayoutView" and len(v.nl.items) == 1 and w.a_export.isEnabled()
    v.add_graph(v.nl.items[0].graph)
    assert len(v.nl.items) == 2
    v.page_size.setCurrentIndex(v.page_size.findText("A4, landscape"))
    assert round(v.nl.width) == 842
    c = v.canvas
    c.resize(900, 700)
    bx, by, bw, bh = c.boxes[0]
    sx, sy = c.to_widget(bx + bw / 2, by + bh / 2)

    def ev(kind, x, y, buttons=Qt.LeftButton):
        p = QPointF(x, y)
        return QMouseEvent(kind, p, p, Qt.LeftButton, buttons, Qt.NoModifier)

    c.mousePressEvent(ev(QEvent.MouseButtonPress, sx, sy))
    c.mouseMoveEvent(ev(QEvent.MouseMove, sx + 50, sy + 30))
    c.mouseReleaseEvent(ev(QEvent.MouseButtonRelease, sx + 50, sy + 30, Qt.NoButton))
    k = c.scale()
    assert v.nl.items[0].x == pytest.approx(bx + 50 / k) and v.nl.items[0].y == pytest.approx(by + 30 / k)
    v.canvas.selected = 1
    v.remove_selected()
    assert len(v.nl.items) == 1
    w.doc.undo.undo()
    assert len(v.nl.items) == 2


def test_families():
    from refract.ui import look
    from refract.ui.main_window import MainWindow

    w = MainWindow()

    w.new_graph_style = "default"  # the type wizard is tested in test_graph_editing
    w.new_project(T.make("column", "Data 1", sample=True))
    w.analyze(w.doc.project.tables[0], "one_way", {})
    w.new_table(T.make("grouped", "Data 2", sample=True))
    w.toggle_families(True)
    secs = {w.nav.topLevelItem(i).text(0): w.nav.topLevelItem(i) for i in range(w.nav.topLevelItemCount())}
    assert list(secs) == ["Info  (1)", "Data 1  (3)", "Data 2  (2)", "Layouts  (0)"]
    kinds = [secs["Data 1  (3)"].child(k).data(0, 0x0100)[0] for k in range(3)]
    assert kinds == ["tables", "results", "ngraphs"]
    assert look.setting("navigator/families", False) is True
    w.toggle_families(False)
    assert w.nav.topLevelItem(0).text(0).startswith("Data Tables")


def test_prism_layout_preview_and_copy():
    if not os.path.exists(LAYOUT_SAMPLE):
        pytest.skip("layout sample not present")
    from refract.ui.document import Document
    from refract.ui.main_window import MainWindow

    w = MainWindow(Document.open(LAYOUT_SAMPLE))
    w.nav.setCurrentItem(next(it for it in w.sheet_items() if it.data(0, 0x0100) == ("layouts", 0)))
    v = w.current_view()
    assert type(v).__name__ == "PrismLayoutView" and len(v.page.items) == 2 and w.a_export.isEnabled()
    inset = v.page.items[1].box
    main = v.page.items[0].box
    assert main[0] < inset[0] < inset[2] < main[2]  # the inset graph sits inside the main one
    w.copy_prism_layout(0)
    nl = w.doc.project.native_layouts[0]
    assert type(w.current_view()).__name__ == "NativeLayoutView" and [i.graph.split(":")[0] for i in nl.items] == \
        ["prism", "prism"]
    assert json.loads(json.dumps([i.__dict__ for i in nl.items]))  # plain values
