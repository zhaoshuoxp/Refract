"""New data tables (docs/ui-spec.md §6): the kinds and sample data, inserting
them into a bundle (verified in Prism: E-new-tables), new projects, the
dialog, and undo across saves."""

import json
import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from refract.formats import bundle_builder as BB
from refract.formats import open_document
from refract.formats import prism_writer as PW
from refract.formats.zipio import ZipArchive
from refract.model import templates as T
from refract.model.document import subcolumns_for
from refract.render import qt


@pytest.fixture(scope="module", autouse=True)
def app(tmp_path_factory):
    os.environ["REFRACT_SETTINGS"] = str(tmp_path_factory.mktemp("settings") / "refract.ini")
    return qt.ensure_app()


def test_every_kind_and_format():
    for k in T.KINDS:
        for fmt in k.formats:
            for sample in (False, True):
                t = T.make(k.key, "T", fmt, 3, sample=sample)
                assert t.kind == k.key and t.data_format == fmt
                assert all(len(d.subcolumns) == subcolumns_for(fmt, t.replicates) for d in t.datasets)
                assert (t.x is not None) == k.x and (t.row_titles is not None) == k.row_titles
                assert (t.n_rows > 0) == sample
                if not sample:
                    assert len(t.datasets) == k.sets
    with pytest.raises(ValueError):
        T.make("column", "T", "y_replicates")
    surv = T.make("survival", "S", sample=True)
    assert all(sum(1 for d in surv.datasets if d.subcolumns[0][r]) == 1 for r in range(surv.n_rows))  # one group per row


def _bundle_with_result_sheet() -> ZipArchive:
    b = BB.BundleBuilder()
    b.add_info()
    b.add_table(BB.TableSpec("Old", "column", "y_single", [BB.DataSet("A", [[1, 2, 3]])], row_titles=["", "", ""]))
    arc = b.build()
    # a result table: a data sheet not listed in document.json, with its own fenID
    arc.add("data/sheets/R/sheet.json", json.dumps({"@class": "DataSheet", "uid": "R", "fenID": 7}).encode())
    return arc


def test_insert_keeps_typed_text_and_free_fen_ids():
    arc = _bundle_with_result_sheet()
    t = T.make("grouped", "New", "y_replicates", 2)
    t.n_rows = 2
    t.row_titles.subcolumns[0][:] = ["Row one", "Row, two"]
    t.datasets[0].subcolumns[0][:] = ["1.50", "2"]
    t.datasets[0].subcolumns[1][:] = ["", "3e2"]
    t.datasets[1].subcolumns[0][:] = ["x", ""]
    t.datasets[1].subcolumns[1][:] = ["", ""]
    uid = PW.insert_new_table(arc, t)
    assert t.sheet_uid == uid and all(d.uid for d in t.datasets)
    sheet = json.loads(arc.read(f"data/sheets/{uid}/sheet.json"))
    assert sheet["fenID"] == 8  # after the result sheet's 7
    fens = [json.loads(arc.read(n))["fenID"] for n in arc.names() if n.startswith("data/sets/") and n.endswith(".json")]
    assert len(fens) == len(set(fens))
    again = open_document(arc.to_bytes()).table("New")
    assert PW.table_grid(again) == PW.table_grid(t)  # "1.50" stays "1.50", the comma survives
    doc = json.loads(arc.read("document.json"))
    assert doc["sheets"]["data"][-1] == uid and doc["sheetAttributesMap"][uid] == {"title": "New"}
    BB.remove_table(arc, uid)
    assert not any(uid in n or (t.table_uid and t.table_uid in n) for n in arc.names())
    assert uid not in json.loads(arc.read("document.json"))["sheets"]["data"]
    assert open_document(arc.to_bytes()).tables[0].title == "Old"


def test_new_project_add_edit_undo_across_saves(tmp_path):
    from refract.stats import catalog
    from refract.ui.document import Document

    doc = Document.new()
    assert doc.name == "Untitled" and doc.can_save() and doc.project.infos
    with pytest.raises(ValueError):
        doc.save()  # no file name yet
    t = doc.add_table(T.make("column", "Data 1", sample=True))
    assert doc.next_table_title() == "Data 2"
    a = doc.add_analysis(t, catalog.by_key("one_way"), {})
    out = tmp_path / "n.prism"
    doc.save(str(out))
    p = open_document(str(out))
    assert [x.title for x in p.tables] == ["Data 1"] and [x.title for x in p.analyses] == [a.title]
    doc.set_cell(t, t.datasets[0], 0, 0, "4.25")
    touched = doc.save()
    assert any(n.endswith("data.csv") for n in touched)  # an ordinary table edit now
    assert open_document(str(out)).tables[0].datasets[0].subcolumns[0][0] == "4.25"
    doc.undo.undo()
    doc.undo.undo()
    doc.undo.undo()  # edit, analysis, table
    doc.save()
    p = open_document(str(out))
    assert p.tables == [] and p.analyses == [] and t.sheet_uid is None
    doc.undo.redo()  # the table again: inserted afresh
    doc.save()
    assert [x.title for x in open_document(str(out)).tables] == ["Data 1"]
    b = doc.add_table(T.make("xy", "Data 1"))
    assert b.title == "Data 1 (2)"


def test_dialog():
    from refract.ui.new_table import NewTableDialog

    d = NewTableDialog("Data 3")
    assert d.kind().key == "xy" and d.title.text() == "Data 3" and not d.picture.pixmap().isNull()
    assert d.data_format() == "y_single" and not d.replicates.isEnabled()
    d.set_format("y_replicates")
    assert d.replicates.isEnabled() and d.data_format() == "y_replicates"
    d.set_format("y_sd_n")
    assert not d.replicates.isEnabled() and d.errors.isEnabled() and d.data_format() == "y_sd_n"
    d.errors.setCurrentIndex(d.errors.findData("y_se"))
    assert d.table().data_format == "y_se"
    d.select("column")
    assert d.y_stacked.isChecked() and d.data_format() == "y_single" and d.y_paired.isVisibleTo(d)
    d.select("contingency")
    assert d.data_format() == "y_single" and d.only_empty.isVisibleTo(d) and not d.y_errors.isVisibleTo(d)
    assert d.sets_label.text() == "Outcomes (columns)"
    d.sets.setValue(4)
    t = d.table()
    assert t.kind == "contingency" and len(t.datasets) == 4 and t.n_rows == 0
    d.select("nested")
    assert d.replicates.isEnabled()
    d.sample.setChecked(True)
    assert not d.sets.isEnabled()
    t = d.table()
    assert t.kind == "nested" and t.n_rows > 0


def test_window_new_project_and_table():
    from refract.ui.grid import TableSheet
    from refract.ui.main_window import MainWindow

    w = MainWindow()
    assert w.a_new_table.isEnabled()  # also with no project: it starts one
    w.new_table(T.make("grouped", "Data 1", sample=True))
    assert w.windowTitle() == "Refract — Untitled*"
    v = w.current_view()
    assert isinstance(v, TableSheet) and v.table.title == "Data 1"
    w.new_table(T.make("column", w.doc.next_table_title()))
    assert w.current_view().table.title == "Data 2"
    assert w.nav.topLevelItem(0).text(0) == "Data Tables  (2)"
    w.doc.undo.undo()
    assert w.nav.topLevelItem(0).text(0) == "Data Tables  (1)" and w.current_view().table.title == "Data 1"
