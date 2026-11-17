"""PLAN §4 phase 4 acceptance scenario, driven through the window:
new Grouped table -> paste data -> two-way ANOVA with Tukey -> the graph
shows significance stars -> export PDF -> save .prism -> reopen: the same
tables, analysis and graph. (Prism opens the saved file and computes the
analysis: experiment E-acceptance.)"""

import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from refract.model import templates as T
from refract.render import qt

DATA = ("Wild type\t12\t14\t11\t30\t33\t28\n"
        "Mutant A\t18\t17\t20\t22\t21\t24\n"
        "Mutant B\t25\t23\t27\t26\t29\t24\n")


@pytest.fixture(scope="module", autouse=True)
def app(tmp_path_factory):
    os.environ["REFRACT_SETTINGS"] = str(tmp_path_factory.mktemp("settings") / "refract.ini")
    return qt.ensure_app()


def scenario(tmp_path):
    from refract.formats import prism_writer as PW
    from refract.ui.main_window import MainWindow
    from refract.ui.views import NativeGraphView, ResultView, TableSheet

    w = MainWindow()

    w.new_graph_style = "default"  # the type wizard is tested in test_graph_editing
    # 1. a new project with an empty Grouped table (2 data sets, 3 replicates)
    w.new_project(T.make("grouped", "Data 1", "y_replicates", 3))
    grid = w.current_view()
    assert isinstance(grid, TableSheet) and grid.table.n_rows == 0
    t = grid.table
    doc = w.doc
    doc.rename_dataset(t, t.datasets[0], "Untreated")
    doc.rename_dataset(t, t.datasets[1], "Treated")
    # 2. paste the data from the first cell (row titles, then 2 x 3 replicates)
    grid.setCurrentIndex(grid.model_.index(0, 0))
    assert grid.paste(DATA)
    assert t.n_rows == 3 and t.row_titles.subcolumns[0] == ["Wild type", "Mutant A", "Mutant B"]
    assert [sc[0] for sc in t.datasets[1].subcolumns] == ["30", "33", "28"]
    # 3. two-way ANOVA, Tukey, columns compared within each row
    a = w.analyze(t, "two_way", {"compare": "COMPARE_CELLS_BY_COLUMNS_WITHIN_ROWS_SINGLE_FAMILY", "test": "TUKEY"})
    rv = w.current_view()
    assert isinstance(rv, ResultView) and "ANOVA table" in rv.tab_names() and "Multiple comparisons" in rv.tab_names()
    # 4. the table's graph (made with the table) shows the comparisons as stars
    item = next(it for it in w.sheet_items() if it.data(0, 0x0100) == ("ngraphs", 0))
    w.nav.setCurrentItem(item)
    gv = w.current_view()
    assert isinstance(gv, NativeGraphView) and gv.graph.family == "grouped"
    assert w.a_analyze.isEnabled() and w._analyzed_table() is t
    labels = [b["label"] for b in gv.graph.significance]
    assert labels and all(lab.startswith("*") for lab in labels)
    # 5. export PDF
    pdf = tmp_path / "graph.pdf"
    gv.export(str(pdf))
    assert pdf.read_bytes().startswith(b"%PDF") and pdf.stat().st_size > 2000
    # 6. save .prism
    out = tmp_path / "scenario.prism"
    doc.save(str(out))
    return w, a, t, labels, str(out), PW.table_grid(t)


def test_acceptance_scenario(tmp_path):
    from refract.formats import prism_writer as PW
    from refract.ui.document import Document
    from refract.ui.main_window import MainWindow
    from refract.ui.views import NativeGraphView, ResultView

    _w, a, _t, labels, path, grid = scenario(tmp_path)
    # 7. reopen: same table, the analysis (computed by Refract until Prism has
    # saved it), the graph with the same stars
    w2 = MainWindow(Document.open(path))
    p = w2.doc.project
    assert [x.title for x in p.tables] == ["Data 1"] and PW.table_grid(p.tables[0]) == grid
    assert [d.title for d in p.tables[0].datasets] == ["Untreated", "Treated"]
    assert [x.title for x in p.analyses] == [a.title]
    assert [g.title for g in p.native_graphs] == ["Data 1"] and p.native_graphs[0].table is p.tables[0]
    item = next(it for it in w2.sheet_items() if it.data(0, 0x0100) == ("results", 0))
    w2.nav.setCurrentItem(item)
    assert isinstance(w2.current_view(), ResultView) and "Multiple comparisons" in w2.current_view().tab_names()
    item = next(it for it in w2.sheet_items() if it.data(0, 0x0100) == ("ngraphs", 0))
    w2.nav.setCurrentItem(item)
    gv = w2.current_view()
    assert isinstance(gv, NativeGraphView) and [b["label"] for b in gv.graph.significance] == labels


def test_graph_follows_data_and_options(tmp_path):
    w, _a, t, labels, _path, _grid = scenario(tmp_path)
    gv = w.current_view()
    doc = w.doc
    doc.set_cells(t, [(t.datasets[1], k, 0, v) for k, v in enumerate(["13", "12", "14"])], "Edit")
    w.nav.setCurrentItem(next(it for it in w.sheet_items() if it.data(0, 0x0100) == ("ngraphs", 0)))
    gv = w.current_view()
    assert all(b["x1"] > 0.5 for b in gv.graph.significance)  # no bracket over the wild-type row any more
    doc.undo.undo()
    assert [b["label"] for b in w.current_view().graph.significance] == labels
    gv = w.current_view()
    gv.stars.setCurrentIndex(gv.stars.findData("none"))
    assert w.current_view().graph.significance == []
    doc.set_native_options(gv.ng, style="means")  # Change Graph Type: symbols with error bars
    assert all(s.kind == "points" for s in w.current_view().graph.series)
    doc.undo.undo()
    doc.undo.undo()  # both option changes undone
    ng = w.doc.project.native_graphs[0]
    assert (ng.style, ng.stars) == ("default", "auto") and [b["label"] for b in w.current_view().graph.significance] == labels
