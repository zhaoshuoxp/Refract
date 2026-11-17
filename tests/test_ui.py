"""Desktop UI (refract.ui) driven offscreen: data grid model, undo, the main
window over a real document, save and reopen, linked graph updates."""

import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt

from refract.model.document import DataSet, DataTable, Project
from refract.render import qt

ROOT = os.path.join(os.path.dirname(__file__), "..")
SAMPLE = os.path.join(ROOT, "corpus", "manual", "batch5_samples.prism")


@pytest.fixture(scope="module", autouse=True)
def app(tmp_path_factory):
    os.environ["REFRACT_SETTINGS"] = str(tmp_path_factory.mktemp("settings") / "refract.ini")
    return qt.ensure_app()


def _grouped():
    rows = DataSet(None, [["Row A", "Row B"]], role="RT")
    s1 = DataSet("Control", [["1", "2"], ["3", "4"]])
    s2 = DataSet("Treated", [["5", "6"], ["7", ""]])
    s1.cell_attributes[(1, 0)] = {"EXCLUDED"}
    t = DataTable("T", "grouped", "y_replicates", [s1, s2], 2, replicates=2, row_titles=rows)
    return Project("prism", tables=[t]), t


def test_grid_headers_and_excluded_values():
    from refract.ui import look
    from refract.ui.document import Document
    from refract.ui.table_model import TableModel

    project, t = _grouped()
    m = TableModel(Document(project), t)
    assert m.columnCount() == 5 and m.rowCount() > t.n_rows  # row titles + 2 x 2 replicates, spare rows
    from refract.ui.table_model import GROUP_ROLE

    assert [m.headerData(k, Qt.Horizontal) for k in range(5)] == ["Row title", "Y1", "Y2", "Y1", "Y2"]
    groups = [m.headerData(k, Qt.Horizontal, GROUP_ROLE) for k in range(5)]
    assert groups == [(-1, ""), (0, "A: Control"), (0, "A: Control"), (1, "B: Treated"), (1, "B: Treated")]
    assert m.data(m.index(0, 0)) == "Row A" and m.data(m.index(1, 4)) == ""
    assert m.data(m.index(0, 2), Qt.ForegroundRole) == look.color("excluded") and m.data(m.index(0, 2), Qt.FontRole).italic()
    assert m.data(m.index(0, 1), Qt.ForegroundRole) is None


def test_edit_undo_redo():
    from refract.ui.document import Document
    from refract.ui.table_model import TableModel

    project, t = _grouped()
    doc = Document(project)
    m = TableModel(doc, t)
    assert not doc.modified
    assert m.setData(m.index(0, 1), "1.50")
    assert t.datasets[0].subcolumns[0][0] == "1.50" and doc.modified  # stored as typed
    m.setData(m.index(4, 3), "9")  # below the data: the table grows
    assert t.n_rows == 5 and t.datasets[1].subcolumns[0][4] == "9"
    doc.undo.undo()
    assert t.n_rows == 2
    doc.undo.undo()
    assert t.datasets[0].subcolumns[0][0] == "1" and not doc.modified
    doc.undo.redo()
    assert t.datasets[0].subcolumns[0][0] == "1.50"


def _need_sample():
    if not os.path.exists(SAMPLE):
        pytest.skip("Prism sample not present")


def test_main_window_shows_every_sheet(tmp_path):
    _need_sample()
    from refract.ui.document import Document
    from refract.ui.main_window import MainWindow
    from refract.ui.views import GraphView, ResultView, TableSheet

    w = MainWindow(Document.open(SAMPLE))
    sections = [w.nav.topLevelItem(i).text(0) for i in range(w.nav.topLevelItemCount())]
    assert sections == ["Data Tables  (4)", "Info  (1)", "Results  (1)", "Graphs  (4)", "Layouts  (0)"]
    assert w.windowTitle() == "Refract — batch5_samples.prism"
    kinds = []
    for it in w.sheet_items():
        w.nav.setCurrentItem(it)
        kinds.append(type(w.current_view()).__name__)
    assert kinds.count("TableSheet") == 4 and kinds.count("GraphView") == 4 and "ResultView" in kinds
    w.nav.setCurrentItem(w.sheet_items()[-1])  # the survival graph
    v = w.current_view()
    assert isinstance(v, GraphView) and v.graph is not None and w.a_export.isEnabled()
    out = tmp_path / "g.pdf"
    v.export(str(out))
    assert out.stat().st_size > 1000
    w.step(-100)
    assert isinstance(w.current_view(), TableSheet)
    assert not isinstance(w.current_view(), ResultView)


def test_edit_save_reopen(tmp_path):
    _need_sample()
    from refract.formats import open_document
    from refract.formats.zipio import ZipArchive
    from refract.ui.document import Document

    doc = Document.open(SAMPLE)
    t = doc.project.tables[1]  # the column table
    ds = t.datasets[0]
    doc.set_cell(t, ds, 0, 0, "123.5")
    out = tmp_path / "edited.prism"
    touched = doc.save(str(out))
    assert not doc.modified and doc.path == str(out)
    assert any(n.endswith("data.csv") for n in touched)
    again = open_document(str(out))
    assert again.tables[1].datasets[0].subcolumns[0][0] == "123.5"
    a, b = ZipArchive.open(SAMPLE), ZipArchive.open(str(out))
    same = [n for n in a.names() if n not in touched and a.read(n) == b.read(n)]
    assert len(same) == len([n for n in a.names() if n not in touched])  # the rest byte-identical


def test_graph_follows_table_edits():
    _need_sample()
    from refract.ui.document import Document
    from refract.ui.main_window import MainWindow

    w = MainWindow(Document.open(SAMPLE))
    graph_item = next(it for it in w.sheet_items() if it.data(0, Qt.UserRole) == ("graphs", 1))
    w.nav.setCurrentItem(graph_item)
    before = max(v for v in w.current_view().graph.series[0].points[0])
    t = w.doc.project.tables[1]
    w.doc.set_cell(t, t.datasets[0], 0, 0, "500")  # the graph is shown: rebuilt at once
    g = w.current_view().graph
    assert max(g.series[0].points[0]) == 500 and before != 500
    assert g.y_axis.max is None or g.y_axis.max >= 500  # autoscaled, not the cached range
    w.doc.undo.undo()
    assert max(w.current_view().graph.series[0].points[0]) == before


def _grid(project=None, t=None):
    from refract.ui.document import Document
    from refract.ui.grid import TableSheet

    if project is None:
        project, t = _grouped()
    doc = Document(project)
    return doc, t, TableSheet(doc, t)


def test_paste_block_clear_and_copy():
    from PySide6.QtWidgets import QApplication

    doc, t, g = _grid()
    g.setCurrentIndex(g.model_.index(1, 1))
    assert g.paste("10\t11\t12\n13\t14\t15\t16\t17\n")  # 2 rows; the 5th column onwards does not exist
    assert t.n_rows == 3
    assert t.datasets[0].subcolumns[0][1:3] == ["10", "13"] and t.datasets[1].subcolumns[0][1:3] == ["12", "15"]
    assert doc.undo.count() == 1  # one step
    from PySide6.QtCore import QItemSelection, QItemSelectionModel

    g.selectionModel().select(QItemSelection(g.model_.index(1, 1), g.model_.index(2, 2)),
                              QItemSelectionModel.SelectionFlag.ClearAndSelect)
    g.copy()
    assert QApplication.clipboard().text() == "10\t11\n13\t14\n"
    g.clear()
    assert t.datasets[0].subcolumns[0][1:3] == ["", ""] and t.datasets[0].subcolumns[1][1:3] == ["", ""]
    doc.undo.undo()
    doc.undo.undo()
    assert t.datasets[0].subcolumns[0] == ["1", "2"] and t.n_rows == 2


def test_rows_move_with_their_marks():
    doc, t, _g = _grid()
    s1 = t.datasets[0]
    assert s1.is_excluded(1, 0)
    doc.insert_rows(t, 0, 2)
    assert t.n_rows == 4 and s1.subcolumns[0] == ["", "", "1", "2"] and t.row_titles.subcolumns[0][2] == "Row A"
    assert s1.is_excluded(1, 2) and not s1.is_excluded(1, 0)
    doc.delete_rows(t, {0, 1, 3})
    assert t.n_rows == 1 and s1.subcolumns[0] == ["1"] and s1.is_excluded(1, 0)
    doc.undo.undo()
    doc.undo.undo()
    assert t.n_rows == 2 and s1.subcolumns[0] == ["1", "2"] and s1.is_excluded(1, 0)


def test_exclude_include():
    doc, t, g = _grid()
    g.setCurrentIndex(g.model_.index(1, 3))  # B: Treated Y1, row 2
    g.exclude(True)
    assert t.datasets[1].is_excluded(0, 1) and t.values(1, 0) == [5.0, None]
    g.setCurrentIndex(g.model_.index(0, 0))  # row titles cannot be excluded
    g.exclude(True)
    assert t.row_titles.cell_attributes == {}
    g.setCurrentIndex(g.model_.index(0, 2))
    g.exclude(False)
    assert not t.datasets[0].is_excluded(1, 0)
    doc.undo.undo()
    assert t.datasets[0].is_excluded(1, 0)


def test_exclusion_saved_as_prism_stores_it(tmp_path):
    _need_sample()
    import json

    from refract.formats import open_document
    from refract.formats.zipio import ZipArchive
    from refract.ui.document import Document

    doc = Document.open(SAMPLE)
    t = doc.project.tables[1]
    ds = t.datasets[0]
    doc.set_excluded(t, [(ds, 0, 1)], True)
    doc.insert_rows(t, 0)  # the mark moves to row 2
    out = tmp_path / "x.prism"
    doc.save(str(out))
    again = open_document(str(out)).tables[1].datasets[0]
    assert again.cell_attributes == {(0, 2): {"EXCLUDED"}}
    rep = json.loads(ZipArchive.open(str(out)).read(f"data/sets/{ds.uid}.json"))["replicates"][0]
    assert rep["cellAttributes"] == [{"rows": "2", "attributes": ["EXCLUDED"]}]
    assert list(rep).index("cellAttributes") < list(rep).index("lastRow")  # where Prism puts it
    doc.undo.undo()
    doc.undo.undo()
    doc.save(str(tmp_path / "back.prism"))  # back to the original content
    assert open_document(str(tmp_path / "back.prism")).tables[1].datasets[0].cell_attributes == {}


def test_start_page_and_recent_files(tmp_path):
    _need_sample()
    from refract.ui import look
    from refract.ui.document import Document
    from refract.ui.main_window import MainWindow

    w = MainWindow()
    assert isinstance(w.current_view(), look.StartPage) and not w.nav.isVisible() and not w.a_save.isEnabled()
    w.open_path(SAMPLE)
    assert look.recent_files()[0] == os.path.abspath(SAMPLE)
    w.nav.setCurrentItem(w.sheet_items()[0])
    assert [a.text() for a in w.table_menu.actions() if a.text()][:3] == ["Cut", "Copy", "Paste"]
    w.close_document()
    start = w.current_view()
    assert isinstance(start, look.StartPage) and start.recent.count() == 1
    assert Document  # imported for the window above


def _contrast(a: str, b: str) -> float:
    from PySide6.QtGui import QColor

    def lum(c):
        q = QColor(c)
        ch = [v / 255 for v in (q.red(), q.green(), q.blue())]
        ch = [v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4 for v in ch]
        return 0.2126 * ch[0] + 0.7152 * ch[1] + 0.0722 * ch[2]

    hi, lo = sorted((lum(a), lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_theme_text_is_readable(theme, monkeypatch):
    """Every background the window sets is paired with text of the same palette
    (WCAG contrast: 4.5 for text, 3 for secondary text)."""
    from refract.ui import look
    from refract.ui.main_window import MainWindow

    monkeypatch.setenv("REFRACT_THEME", theme)
    c = look.colors()
    assert c is (look.DARK if theme == "dark" else look.LIGHT)
    for bg in ("window", "panel", "bar", "card", "base"):
        assert _contrast(c["text"], bg if bg.startswith("#") else c[bg]) >= 4.5, bg
        assert _contrast(c["muted"], c[bg]) >= 3, bg
    assert _contrast(c["selected_text"], c["selected"]) >= 4.5
    assert _contrast(c["excluded"], c["base"]) >= 3 and _contrast(c["text"], c["row_title"]) >= 4.5
    assert _contrast(c["bad"], c["base"]) >= 4.5
    w = MainWindow()
    assert c["panel"] in w.styleSheet() and c["text"] in w.styleSheet()
    other = "light" if theme == "dark" else "dark"
    monkeypatch.setenv("REFRACT_THEME", other)
    w.apply_theme()  # what a system colour-scheme change triggers
    assert look.colors()["panel"] in w.styleSheet() and c["panel"] not in w.styleSheet()


def test_actions_take_no_checked_argument():
    """Triggered actions pass `checked`; Paste through its action and shortcut
    must still read the clipboard (it once got False as the text)."""
    from PySide6.QtWidgets import QApplication

    doc, t, g = _grid()
    g.setCurrentIndex(g.model_.index(0, 1))
    QApplication.clipboard().setText("42\t43\n")
    g.actions_["paste"].trigger()
    assert t.datasets[0].subcolumns[0][0] == "42" and t.datasets[0].subcolumns[1][0] == "43"
    for key in ("copy", "row_above", "row_below", "exclude", "include", "delete_rows", "clear", "cut"):
        g.setCurrentIndex(g.model_.index(0, 1))  # an edit resets the model and its current cell
        g.actions_[key].trigger()  # none raises
    assert doc.undo.count() >= 4  # paste, two inserts, exclude (include of a kept value is no step)
