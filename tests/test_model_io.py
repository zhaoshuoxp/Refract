"""Reader/writer tests that need no local corpus."""

import json

from refract.formats import open_document, sniff
from refract.formats.bundle_builder import BundleBuilder, DataSet, TableSpec, set_seed
from refract.formats.prism_reader import read_prism
from refract.formats.prism_writer import save_project, table_grid
from refract.formats.zipio import ZipArchive
from refract.model.document import to_number


def _bundle() -> bytes:
    set_seed(7)
    b = BundleBuilder(full_ui=True)
    b.add_info()
    b.add_table(TableSpec("grp", "grouped", "y_replicates",
                          [DataSet("A", [[1.5, 2.0], [3.25, None], [5.0, 6.0]]), DataSet("B", [[7, 8], [9, 10], [11, 12]])],
                          row_titles=["r1", "r2"], replicates=3))
    b.add_table(TableSpec("xy", "xy", "y_sd_n", [DataSet("Y", [[0.1, 0.2], [0.01, 0.02], [3, 4]])], x_title="t", x_values=[1, 2]))
    return b.build().to_bytes()


def test_sniff_and_dispatch():
    raw = _bundle()
    assert sniff(raw) == "prism"
    assert sniff(b"PCFFGRA4....") == "pcff"
    assert sniff(b"\xef\xbb\xbf<?xml version='1.0'?><GraphPadPrismFile/>") == "pzfx"
    assert open_document(raw).tables[0].title == "grp"


def test_builder_roundtrip_through_reader():
    p = read_prism(_bundle())
    g, xy = p.tables
    assert (g.kind, g.data_format, g.replicates, g.n_rows) == ("grouped", "y_replicates", 3, 2)
    assert g.row_titles.subcolumns[0] == ["r1", "r2"]
    assert g.datasets[0].subcolumns == [["1.5", "2"], ["3.25", ""], ["5", "6"]]
    assert xy.x_values() == [1.0, 2.0] and xy.values(0, 2) == [3.0, 4.0]
    assert p.warnings == []


def test_noop_save_is_byte_identical():
    raw = _bundle()
    out, touched = save_project(raw, read_prism(raw))
    assert out == raw and touched == []


def test_edit_cells_and_shape():
    raw = _bundle()
    p = read_prism(raw)
    t = p.tables[0]
    t.datasets[1].subcolumns[0][0] = "70.5"
    t.n_rows += 1
    t.row_titles.subcolumns[0].append("r3")
    for d in t.datasets:
        for k, s in enumerate(d.subcolumns):
            s.append("" if k == 2 else "1")
    out, touched = save_project(raw, p)
    q = read_prism(out)
    assert table_grid(q.tables[0]) == table_grid(t)
    assert table_grid(q.tables[1]) == table_grid(read_prism(raw).tables[1])  # other table untouched
    arc = ZipArchive.from_bytes(out)
    content = json.loads(arc.read(f"data/tables/{t.table_uid}/content.json"))
    assert content["numberOfRows"] == 3
    rr = json.loads(arc.read(f"data/sets/{t.datasets[0].uid}.json"))["replicate ranges"][0]["replicate"]
    assert rr["lastRow"] == 2 and "firstRow" not in rr  # Prism 11 omits firstRow when 0
    untouched = {e.name for e in ZipArchive.from_bytes(raw).entries} - set(touched)
    a, b = ZipArchive.from_bytes(raw), ZipArchive.from_bytes(out)
    assert all(a.read(n) == b.read(n) for n in untouched)


def test_decimal_comma():
    assert to_number("56,92015") == 56.92015
    assert to_number("1,2,3") is None
    assert to_number("(Bad value)") is None
