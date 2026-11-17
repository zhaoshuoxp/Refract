"""Saving .pzfx documents: table edits written in place (pzfx_writer, every
other byte kept), refusals for what a .pzfx cannot hold, and Save As .prism
(conversion through bundle_builder). The fixture is our own neutral data in
the layout Prism writes (E-pzfxsave, E-pzfxconvert)."""

import base64
import glob
import json
import os
import zlib

import pytest

from refract.formats import open_document
from refract.formats.pzfx_reader import read_pzfx
from refract.formats.pzfx_writer import PzfxUnsupported, save_pzfx
from refract.formats.zipio import ZipArchive
from refract.model.document import DataSet

TEMPLATE = base64.b64encode(zlib.compress(b"not a real graph blob")).decode()

DOC = "\r\n".join([
    '<?xml version="1.0" encoding="UTF-8"?><GraphPadPrismFile PrismXMLVersion="5.00">',
    "<Created>",
    ('<OriginalVersion CreatedByProgram="GraphPad Prism" CreatedByVersion="10.0.0" Login="" '
     'DateTime="2026-01-02T03:04:05-08:00"></OriginalVersion>'),
    "</Created>",
    "<InfoSequence>",
    '<Ref ID="Info0" Selected="1"></Ref>',
    "</InfoSequence>",
    '<Info ID="Info0">',
    "<Title>Project info 1</Title>",
    "<Notes>",
    "</Notes>",
    "<Constant><Name>Experiment Date</Name><Value>2026-01-02</Value></Constant>",
    "<Constant><Name>Experimenter</Name><Value>Someone</Value></Constant>",
    "</Info>",
    "",
    "<TableSequence>",
    "",
    '<Ref ID="Table0" Selected="1"></Ref>',
    '<Ref ID="Table1"></Ref>',
    '<Ref ID="Table2"></Ref>',
    "</TableSequence>",
    '<Table ID="Table0" XFormat="none" TableType="OneWay" EVFormat="AsteriskAfterNumber">',
    '<Title><Font Size="12" Face="Arial">Weights</Font></Title>',
    '<FloatingNote ID="Sticky0" Auto="0" Color="Blue" Left="1" Top="2" Width="3" Height="4">',
    '<Font Size="11" Face="Arial">A note.</Font>',
    "</FloatingNote>",
    '<RowTitlesColumn Width="81">',
    "<Subcolumn>",
    "<d>first\rline</d>",
    "<d>second</d>",
    "</Subcolumn>",
    "</RowTitlesColumn>",
    '<YColumn Width="81" Decimals="3" Subcolumns="1">',
    "<Title>Control</Title>",
    "<Subcolumn>",
    "<d>1.5</d>",
    '<d Excluded="1">2.25</d>',
    "<d>3</d>",
    "</Subcolumn>",
    "</YColumn>",
    '<YColumn Width="81" Decimals="3" Subcolumns="1">',
    "<Title>Treated</Title>",
    "<Subcolumn>",
    "<d>4</d>",
    "<d/>",
    "<d>6</d>",
    "</Subcolumn>",
    "</YColumn>",
    "</Table>",
    "",
    '<Table ID="Table1" XFormat="numbers" YFormat="replicates" Replicates="2" TableType="XY">',
    "<Title>Curve</Title>",
    '<XColumn Width="81" Subcolumns="1" Decimals="1">',
    "<Title>Dose</Title>",
    "<Subcolumn>",
    "<d>0.5</d>",
    "<d>1.5</d>",
    "</Subcolumn>",
    "</XColumn>",
    '<YColumn Width="81" Decimals="2" Subcolumns="2">',
    "<Title>Response</Title>",
    "<Subcolumn>",
    "<d>10</d>",
    "<d>20</d>",
    "</Subcolumn>",
    "<Subcolumn>",
    "<d>11</d>",
    "<d>21</d>",
    "</Subcolumn>",
    "</YColumn>",
    "</Table>",
    "",
    '<Table ID="Table2" TableType="OneWay" ExtTableType="MultipleVariables">',
    "<Title>Variables</Title>",
    '<YColumn Width="81" Decimals="0" Subcolumns="1" MVType="Manual|Categorical" statDecimals="0">',
    "<Title>Group</Title>",
    "<CategoryDictionary>",
    '<d id="0" firstRowUsage="0" numUsage="2" numExcluded="0">1</d>',
    '<d id="1" firstRowUsage="1" numUsage="1" numExcluded="0">0</d>',
    "</CategoryDictionary>",
    "<Subcolumn>",
    '<d CellType="Integer" UserText="1" num="0">1</d>',
    '<d CellType="Integer" UserText="0" num="1">0</d>',
    '<d CellType="Integer" UserText="1" num="0">1</d>',
    "</Subcolumn>",
    "</YColumn>",
    '<YColumn Width="81" Decimals="2" Subcolumns="1" MVType="Continues" statDecimals="2">',
    "<Title>Score</Title>",
    "<Subcolumn>",
    '<d CellType="Decimal" UserText="0.5">0.5</d>',
    '<d CellType="Decimal" UserText="1.25">1.25</d>',
    '<d CellType="Decimal" UserText="2.75">2.75</d>',
    "</Subcolumn>",
    "</YColumn>",
    "</Table>",
    "",
    "<!--Analyses, graphs and layouts as compressed binary. Don&apos;t edit this part of the file.-->",
    "",
    f'<Template dt:dt="bin.base64" xmlns:dt="urn:schemas-microsoft-com:datatypes">{TEMPLATE}</Template>',
    "</GraphPadPrismFile>",
    "",
]).encode("utf-8")


def _excluded(d: DataSet) -> list:
    return sorted(k for k, v in d.cell_attributes.items() if "EXCLUDED" in v)


def _cells(t) -> list:
    n = t.n_rows
    return [[c + [""] * (n - len(c)) for c in d.subcolumns] for d in t.datasets]


def test_reader_keeps_line_breaks_decimals_and_variable_types():
    p = read_pzfx(DOC)
    w, xy, mv = p.tables
    assert w.title == "Weights" and w.row_titles.subcolumns[0][:2] == ["first\rline", "second"]  # lone CR kept
    assert [d.decimals for d in w.datasets] == [3, 3] and xy.x.decimals == 1
    assert mv.datasets[0].variable == {"type": "categorical", "manual": True, "categories": [(0, "1"), (1, "0")]}
    assert mv.datasets[1].variable == {"type": "continuous", "manual": False} and mv.datasets[1].decimals == 2


def test_unchanged_document_is_byte_identical():
    out, touched = save_pzfx(DOC, read_pzfx(DOC))
    assert out == DOC and touched == []


def test_table_edits_are_written_in_place():
    p = read_pzfx(DOC)
    w, xy, _ = p.tables
    c = w.datasets[0]
    c.subcolumns[0][0] = "9.75"  # value
    c.cell_attributes.pop((0, 1))  # no longer excluded
    w.datasets[1].cell_attributes[(0, 2)] = {"EXCLUDED"}
    w.datasets[1].title = "Treated & <dosed>"  # escaped
    w.datasets.append(DataSet("Added", [["7", "", "8"]], "Y", "y_single"))
    xy.datasets[0].subcolumns[1][1] = "22"
    out, touched = save_pzfx(DOC, p)
    assert touched == ["Table0", "Table1"]
    q = read_pzfx(out)
    for a, b in zip(p.tables, q.tables, strict=True):
        assert a.title == b.title and [d.title for d in a.datasets] == [d.title for d in b.datasets]
        assert _cells(a) == _cells(b) and [_excluded(d) for d in a.datasets] == [_excluded(d) for d in b.datasets]
    assert q.tables[0].row_titles.subcolumns[0][0] == "first\rline"
    # everything else as it was: the Template, the info sheet, the untouched table, the
    # table's title markup and note, the columns' start tags and the cells not edited
    for part in (DOC[DOC.index(b"<!--Analyses"):], DOC[:DOC.index(b"<Table ")],
                 DOC[DOC.index(b'<Table ID="Table2"'):DOC.index(b"<!--Analyses")].strip()):
        assert part in out
    for part in (b'<Title><Font Size="12" Face="Arial">Weights</Font></Title>', b"A note.",
                 b'<YColumn Width="81" Decimals="3" Subcolumns="1">\r\n<Title>Control</Title>',
                 b"<d>first\rline</d>", b'<d Excluded="1">6</d>', b"Treated &amp; &lt;dosed&gt;",
                 b"<Title>Added</Title>\r\n<Subcolumn>\r\n<d>7</d>\r\n<d/>\r\n<d>8</d>\r\n</Subcolumn>"):
        assert part in out, part
    assert b"\n" not in out.replace(b"\r\n", b"")  # the file's CRLF throughout
    assert q.graphs[0].blob == read_pzfx(DOC).graphs[0].blob


def test_what_a_pzfx_cannot_hold_is_refused():
    p = read_pzfx(DOC)
    p.tables[2].datasets[0].subcolumns[0][0] = "0"  # typed Multiple variables cell
    with pytest.raises(PzfxUnsupported, match="Multiple variables"):
        save_pzfx(DOC, p)
    p = read_pzfx(DOC)
    t = p.tables[0]
    p.tables.append(type(t)("New", "column", "y_single", [DataSet("A", [["1"]], "Y")], 1))
    with pytest.raises(PzfxUnsupported, match="made in Refract"):
        save_pzfx(DOC, p)
    p = read_pzfx(DOC)
    del p.tables[1]
    with pytest.raises(PzfxUnsupported, match="removed"):
        save_pzfx(DOC, p)


def test_local_corpus_round_trip():
    files = [f for f in glob.glob(os.path.join(os.path.dirname(__file__), "..", "corpus", "**", "*.pzfx"),
                                  recursive=True)]
    if not files:
        pytest.skip("no local .pzfx corpus")
    for f in files:
        with open(f, "rb") as fh:
            src = fh.read()
        p = read_pzfx(src)
        assert save_pzfx(src, p)[0] == src, f
        for t in p.tables:
            if t.kind != "multivariable" and t.datasets and t.n_rows:
                t.datasets[0].subcolumns[0][0] = "12.5"
                t.datasets[0].cell_attributes[(0, 0)] = {"EXCLUDED"}
        q = read_pzfx(save_pzfx(src, p)[0])
        for a, b in zip(p.tables, q.tables, strict=True):
            assert _cells(a) == _cells(b) and [_excluded(d) for d in a.datasets] == [_excluded(d) for d in b.datasets], f


# ------------------------------------------------------------- the document
@pytest.fixture(scope="module")
def app(tmp_path_factory):
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ["REFRACT_SETTINGS"] = str(tmp_path_factory.mktemp("settings") / "refract.ini")
    from refract.render import qt

    return qt.ensure_app()


def _doc(tmp_path):
    from refract.ui.document import Document

    path = tmp_path / "doc.pzfx"
    path.write_bytes(DOC)
    return Document.open(str(path)), path


def test_document_saves_table_edits_to_the_pzfx(app, tmp_path):
    from refract.model import templates as T

    doc, path = _doc(tmp_path)
    assert doc.can_save() and doc.is_pzfx and doc.pzfx_blockers() == []
    w = doc.project.tables[0]
    doc.set_cell(w, w.datasets[1], 0, 1, "5")
    doc.rename_table(w, "Weights 2")
    assert doc.modified
    assert doc.save() == ["Table0"] and not doc.modified
    q = read_pzfx(path.read_bytes())
    assert q.tables[0].title == "Weights 2" and q.tables[0].datasets[1].subcolumns[0][1] == "5"
    doc.add_table(T.make("column", "Extra", sample=True))
    assert doc.pzfx_blockers() == ["data tables made in Refract", "graphs made in Refract"]
    before = path.read_bytes()
    with pytest.raises(PzfxUnsupported, match="Save As .prism"):
        doc.save()
    assert path.read_bytes() == before


def test_save_as_prism_converts(app, tmp_path):
    doc, path = _doc(tmp_path)
    w = doc.project.tables[0]
    doc.set_excluded(w, [(w.datasets[0], 0, 0)], True)
    assert any("binary part" in x for x in doc.convert_loss())
    out = str(tmp_path / "doc.prism")
    doc.save(out)
    assert path.read_bytes() == DOC  # the .pzfx is not changed
    assert not doc.is_pzfx and doc.path == out and doc.project.graphs == []
    p = open_document(out)
    src = read_pzfx(DOC)
    src.tables[0].datasets[0].cell_attributes[(0, 0)] = {"EXCLUDED"}
    got = [t for t in p.tables if not t.is_result]
    assert [t.title for t in got] == [t.title for t in src.tables]
    for a, b in zip(src.tables, got, strict=True):
        assert (a.kind, a.data_format) == (b.kind, b.data_format)
        assert _cells(a) == _cells(b) and [_excluded(d) for d in a.datasets] == [_excluded(d) for d in b.datasets]
    assert got[0].row_titles.subcolumns[0][0] == "first\rline"
    assert p.infos[0].constants[:2] == [("Experiment Date", "2026-01-02"), ("Experimenter", "Someone")]
    arc = ZipArchive.open(out)
    sets = [json.loads(arc.read(n)) for n in arc.names() if n.startswith("data/sets/") and n.endswith(".json")]
    by = {s.get("title"): s for s in sets}
    assert by["Control"]["replicates"][0]["decimalsLength"] == 3  # the column's display decimals
    g = by["Group"]  # a categorical variable of numbers, set by hand: kept as such
    assert (g["currentType"], g["isManual"], g["integersCount"], g["textsCount"]) == ("categorical", True, 3, 0)
    assert [(c["id"], c["name"], c["usageCount"]) for c in g["categories"]] == [(1, "0", 1), (0, "1", 2)]
    assert by["Score"]["currentType"] == "continuous" and by["Score"]["replicates"][0]["decimalsLength"] == 2
    # the converted document goes on saving as a .prism
    xy = doc.project.tables[1]
    doc.set_cell(xy, xy.datasets[0], 0, 0, "15")
    doc.save()
    assert open_document(out).tables[1].datasets[0].subcolumns[0][0] == "15"


def test_window_offers_prism_for_what_a_pzfx_cannot_hold(app, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from refract.model import templates as T
    from refract.ui.main_window import MainWindow

    _, path = _doc(tmp_path)
    w = MainWindow()
    w.open_recent(str(path))
    w.doc.add_table(T.make("column", "Extra", sample=True))
    asked = []
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: asked.append(a[2]) or QMessageBox.StandardButton.Cancel)
    assert w.save() is False
    assert "Save a .prism copy instead?" in asked[0] and "data tables made in Refract" in asked[0]
    assert path.read_bytes() == DOC
    asked.clear()
    assert w.confirm_convert() is False and "not changed" in asked[0] and "binary part" in asked[0]
    w.doc.undo.setClean()
    w.close()
