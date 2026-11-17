"""Fidelity tests against real Prism documents.

Corpus files are never committed. Tests look in the user's Documents folder
and the Prism app bundle, and skip when neither is present.
"""

from __future__ import annotations

import base64
import glob
import os
import pathlib
import re
import zlib

import pytest

from refract.formats.pcff import fields
from refract.formats.pcff.walker import MAGIC, parse, serialize
from refract.formats.zipio import ZipArchive, prism_deflate

ROOTS = [
    os.path.expanduser("~/Documents"),
    "/Applications/Prism 11.app/Contents/SharedSupport",
]


def _find(patterns):
    out = []
    for root in ROOTS:
        if os.path.isdir(root):
            for p in patterns:
                out += glob.glob(os.path.join(root, "**", p), recursive=True)
    # Files we generated ourselves (probes, seeds) are not Prism ground truth.
    out = [f for f in out if "/Refract/corpus/" not in f]
    return sorted(set(out))


BUNDLES = [f for f in _find(["*.prism", "*.prismt"]) if pathlib.Path(f).read_bytes()[:4] == b"PK\x03\x04"]
XMLS = _find(["*.pzfx"])


def _blobs():
    for f in BUNDLES:
        z = ZipArchive.open(f)
        for e in z.entries:
            if e.name.endswith("data.bin"):
                b = e.read()
                if b[:8] == MAGIC:
                    yield f"{f}:{e.name}", b
    for f in XMLS:
        m = re.search(r"<Template[^>]*>(.*?)</Template>", pathlib.Path(f).read_text(encoding="utf-8", errors="replace"), re.DOTALL)
        if m:
            yield f, zlib.decompress(base64.b64decode(m.group(1)))


needs_corpus = pytest.mark.skipif(not BUNDLES, reason="no local Prism corpus")


@needs_corpus
@pytest.mark.parametrize("path", BUNDLES, ids=os.path.basename)
def test_zip_roundtrip_byte_identical(path):
    raw = pathlib.Path(path).read_bytes()
    assert ZipArchive.from_bytes(raw).to_bytes() == raw


@needs_corpus
@pytest.mark.parametrize("path", BUNDLES, ids=os.path.basename)
def test_deflate_params_reproduce_prism(path):
    z = ZipArchive.open(path)
    for e in z.entries:
        if e.method == 8:
            assert prism_deflate(e.read()) == e.compressed, e.name


@needs_corpus
def test_pcff_parse_and_reserialise_all_blobs():
    n = 0
    for name, b in _blobs():
        assert serialize(parse(b)) == b, name
        n += 1
    assert n > 0


@needs_corpus
def test_text_container_header_holds_text_length():
    checked = 0
    for _, b in _blobs():
        ch = parse(b)
        for i, t in fields.texts(ch):
            if ch[i - 1].tag == fields.TAG_TEXT_CONTAINER:
                assert int.from_bytes(ch[i - 1].payload[6:8], "little") == len(t.encode("latin-1"))
                checked += 1
    assert checked > 0


def test_replace_entry_updates_crc_and_sizes():
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("a.txt", "hello")
        zf.writestr("b.txt", "world")
    arc = ZipArchive.from_bytes(buf.getvalue())
    arc.entry("a.txt").replace(b"changed contents")
    out = arc.to_bytes()
    with zipfile.ZipFile(io.BytesIO(out)) as zf:
        assert zf.testzip() is None
        assert zf.read("a.txt") == b"changed contents"
        assert zf.read("b.txt") == b"world"


@needs_corpus
def test_property_store_roundtrip():
    from refract.formats.pcff import propstore as P

    n = 0
    for name, b in _blobs():
        for c in parse(b):
            if c.tag == P.TAG and c.payload[:4] == b"Zval":
                v, raw, _tail = P.decode_payload(c.payload)
                assert P._enc(v) == raw, name
                n += 1
    assert n > 0


AUTO = os.path.join(os.path.dirname(__file__), "..", "corpus", "auto")
DUP_CASES = [("dup1", "Data 1"), ("dup_grouped", "Data 1"), ("dup_pie", "Data 1")]


@pytest.mark.parametrize("case,title", DUP_CASES)
def test_duplicate_family_matches_prism(case, title):
    """Our duplicate_family reproduces Prism's own DuplicateFamily graph blob
    (bar, column and pie graphs) and its fenID choices."""
    import json

    from refract.formats.bundle_builder import set_seed
    from refract.formats.graph_copy import duplicate_family

    ctrl = os.path.join(AUTO, case, "control", "variant.prism")
    dup = os.path.join(AUTO, case, "dupfamily", "variant.prism")
    if not (os.path.exists(ctrl) and os.path.exists(dup)):
        pytest.skip("Prism DuplicateFamily samples not generated locally")
    set_seed(1)
    arc = ZipArchive.open(ctrl)
    doc = json.loads(arc.read("document.json"))
    src = next(u for u in doc["sheets"]["data"] if json.loads(arc.read(f"data/sheets/{u}/sheet.json"))["title"] == title)
    _, graphs = duplicate_family(arc, src)
    zb = ZipArchive.open(dup)
    pg = next(u for u in json.loads(zb.read("document.json"))["sheets"]["graphs"] if u not in doc["sheets"]["graphs"])
    ours, theirs = parse(arc.read(f"graphs/{graphs[0]}/data.bin")), parse(zb.read(f"graphs/{pg}/data.bin"))
    assert [c.tag for c in ours] == [c.tag for c in theirs]
    assert [i for i, (x, y) in enumerate(zip(ours, theirs)) if x.payload != y.payload and x.tag != 0x2015] == []
    assert json.loads(arc.read(f"graphs/{graphs[0]}/sheet.json"))["fenID"] == json.loads(zb.read(f"graphs/{pg}/sheet.json"))["fenID"]


DUP1 = os.path.join(os.path.dirname(__file__), "..", "corpus", "auto", "dup1")


@pytest.mark.skipif(not os.path.exists(os.path.join(DUP1, "dupfamily", "variant.prism")),
                    reason="Prism DuplicateFamily sample not generated locally")
def test_dupfamily_emulation_is_byte_exact_on_single_graph_doc(capsys):
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "emulate_dupfamily", os.path.join(os.path.dirname(__file__), "..", "tools", "emulate_dupfamily.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.main(os.path.join(DUP1, "control", "variant.prism"), os.path.join(DUP1, "dupfamily", "variant.prism"))
    assert "0 chunks differ" in capsys.readouterr().out


@needs_corpus
@pytest.mark.parametrize("path", BUNDLES, ids=os.path.basename)
def test_reader_csv_rebuild_and_noop_save(path):
    from refract.formats.prism_reader import read_prism
    from refract.formats.prism_writer import save_project, table_grid, write_csv

    raw = pathlib.Path(path).read_bytes()
    arc = ZipArchive.from_bytes(raw)
    p = read_prism(raw, include_results=True)
    assert p.warnings == []
    for t in p.tables:
        assert write_csv(table_grid(t)) == arc.read(f"data/tables/{t.table_uid}/data.csv"), t.title
    assert save_project(raw, read_prism(raw))[0] == raw


@pytest.mark.skipif(not XMLS, reason="no local .pzfx corpus")
def test_pzfx_reader_reads_every_document():
    from refract.formats.pzfx_reader import read_pzfx

    for f in XMLS:
        read_pzfx(f)


@pytest.mark.parametrize("run", ["oracle_tables", "oracle_bundled", "p1"])
def test_tables_match_prism_export(run, capsys):
    """Every table we read equals Prism's own ExportTable (generated locally by
    tools/prism_auto.py --tables-only; skipped when absent)."""
    out = os.path.join(AUTO, run)
    if not os.path.exists(os.path.join(out, "summary.json")):
        pytest.skip(f"{run} not generated locally")
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "check_tables_vs_prism", os.path.join(os.path.dirname(__file__), "..", "tools", "check_tables_vs_prism.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.main(out)
    assert "mismatching: 0" in capsys.readouterr().out
