"""Structural table edits (data sets added, removed, renamed; tables
renamed) saved into existing bundles (verified in Prism: E-structure), and
Refract's own graphs kept in x-refract/graphs.json."""

import json
import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from refract.formats import open_document
from refract.formats import prism_writer as PW
from refract.formats.zipio import ZipArchive
from refract.model import templates as T
from refract.render import qt

ROOT = os.path.join(os.path.dirname(__file__), "..")
SAMPLE = os.path.join(ROOT, "corpus", "manual", "batch5_samples.prism")


@pytest.fixture(scope="module", autouse=True)
def app(tmp_path_factory):
    os.environ["REFRACT_SETTINGS"] = str(tmp_path_factory.mktemp("settings") / "refract.ini")
    return qt.ensure_app()


def test_add_delete_rename_with_undo():
    from refract.ui.document import Document

    doc = Document.new()
    t = doc.add_table(T.make("column", "Data 1", sample=True))
    first = t.datasets[0]
    ds = doc.add_dataset(t, at=1)
    assert ds.title == "Data Set-D" and t.datasets[1] is ds and len(ds.subcolumns[0]) == t.n_rows
    doc.rename_dataset(t, first, "Control")
    assert doc.delete_datasets(t, [t.datasets[2]])
    assert [d.title for d in t.datasets] == ["Control", "Data Set-D", "High dose"]
    assert not doc.delete_datasets(t, list(t.datasets))  # one must stay
    assert doc.rename_table(t, "Renamed") and not doc.rename_table(t, "")
    for _ in range(4):
        doc.undo.undo()
    assert t.title == "Data 1" and [d.title for d in t.datasets] == ["Vehicle", "Low dose", "High dose"]
    nested = doc.add_table(T.make("nested", "N"))
    assert doc.add_dataset(nested) is None  # not for nested tables yet


def test_analysis_keeps_its_data_sets_when_columns_move():
    from refract.stats import catalog
    from refract.ui.document import Document

    doc = Document.new()
    t = doc.add_table(T.make("column", "Data 1", sample=True))
    a = doc.add_analysis(t, catalog.by_key("t_test"), {}, [1, 2])
    doc.add_dataset(t, at=0)
    assert doc.source_of(a) == (t, [2, 3])
    doc.delete_datasets(t, [t.datasets[0]])
    assert doc.source_of(a) == (t, [1, 2])


def _need_sample():
    if not os.path.exists(SAMPLE):
        pytest.skip("Prism sample not present")


def test_structure_saved_into_an_existing_bundle(tmp_path):
    _need_sample()
    from refract.ui.document import Document

    doc = Document.open(SAMPLE)
    col = doc.project.tables[1]
    gone = col.datasets[1].uid
    doc.delete_datasets(col, [col.datasets[1]])
    ds = doc.add_dataset(col, title="New")
    doc.set_cell(col, ds, 0, 0, "1.50")
    doc.rename_dataset(col, col.datasets[0], "First")
    doc.rename_table(col, "Renamed table")
    out = tmp_path / "s.prism"
    touched = doc.save(str(out))
    assert f"data/sets/{gone}.json" in touched and ds.uid and f"data/sets/{ds.uid}.json" in touched
    again = open_document(str(out))
    t = next(x for x in again.tables if x.title == "Renamed table")
    assert [d.title for d in t.datasets] == ["First", "Treated", "New"] and t.datasets[2].subcolumns[0][0] == "1.50"
    assert PW.table_grid(t) == PW.table_grid(col)
    z = ZipArchive.open(str(out))
    assert not z.has(f"data/sets/{gone}.json")
    assert json.loads(z.read("document.json"))["sheetAttributesMap"][col.sheet_uid]["title"] == "Renamed table"
    # undo everything: the saved file goes back to the original content
    for _ in range(5):
        doc.undo.undo()
    doc.save(str(out))
    back = open_document(str(out)).tables[1]
    orig = open_document(SAMPLE).tables[1]
    assert PW.table_grid(back) == PW.table_grid(orig) and [d.title for d in back.datasets] == \
        [d.title for d in orig.datasets] and back.title == orig.title
    doc.undo.redo()  # the deleted data set deleted again, then the new one re-added after a save removed it
    doc.undo.redo()
    doc.save(str(out))
    assert [d.title for d in open_document(str(out)).tables[1].datasets] == ["Untreated", "Treated", "New"]


def test_refract_graphs_saved_and_reopened(tmp_path):
    from refract.formats import native_graphs as NG
    from refract.ui.document import Document

    doc = Document.new()
    t = doc.add_table(T.make("grouped", "Data 1", sample=True))
    assert [g.title for g in doc.project.native_graphs] == ["Data 1"]  # made with the table
    second = doc.add_native_graph(t)
    assert second.title == "Data 1 (2)"
    doc.set_native_options(second, style="means", error="sem", stars="none")
    out = tmp_path / "g.prism"
    assert NG.ENTRY in doc.save(str(out))
    again = open_document(str(out))
    assert [(g.title, g.style, g.error, g.stars) for g in again.native_graphs] == \
        [("Data 1", "default", "sd", "auto"), ("Data 1 (2)", "means", "sem", "none")]
    assert all(g.table is again.tables[0] for g in again.native_graphs)
    assert doc.save() == []  # nothing changed: the entry is not rewritten
    doc.undo.undo()
    doc.undo.undo()
    doc.undo.undo()  # options, second graph, the table with its graph
    doc.save()
    z = ZipArchive.open(str(out))
    assert not z.has(NG.ENTRY) and open_document(str(out)).native_graphs == []


def test_unknown_graph_table_is_reported():
    from refract.formats import native_graphs as NG
    from refract.formats.bundle_builder import BundleBuilder
    from refract.model.document import Project

    arc = BundleBuilder().build()
    arc.add("x-refract/")
    arc.add(NG.ENTRY, json.dumps({"version": 1, "graphs": [{"title": "G", "table": "missing"}]}).encode())
    p = open_document(arc.to_bytes())
    assert p.native_graphs == [] and any("its table is gone" in w for w in p.warnings)
    assert NG.read(arc, Project("prism")) == []
