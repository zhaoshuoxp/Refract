"""Level C: graphs built from Refract's skeleton (refract.formats.pcff.skeleton, E-levelc)."""

import os
import struct

import pytest

from refract.formats.pcff import propstore as P
from refract.formats.pcff import skeleton as S
from refract.formats.pcff import walker as W
from refract.formats.zipio import ZipArchive
from refract.model import templates as T


def _objects(ch):
    return [ch[i] for i in S._objects(ch)]


@pytest.mark.parametrize("kind", S.KINDS)
@pytest.mark.parametrize("plots", [0, 2, 6])
def test_skeleton_is_consistent(kind, plots):
    blob, fens = S.build(kind, "Mine", plots)
    ch = W.parse(blob)
    objs = _objects(ch)
    assert struct.unpack_from("<I", next(c for c in ch if c.tag == 0x8018).payload, 4)[0] == len(objs)
    store = next(c for c in ch if c.tag == P.TAG)
    assert len(P.decode_payload(store.payload)[0].get("SEDObject_Array").items) == len(objs)
    heads = [c for c in ch if c.tag == 0x8028]
    n = min(plots, len(S.plot_fens(kind)))  # a pie has one plot
    assert len(heads) == len(fens) == n and fens == S.plot_fens(kind)[:n]
    lists = [c for c in ch if c.tag == 0x0015]
    if plots:  # the plot list names exactly the plots kept (else Prism replaces them)
        n = struct.unpack_from("<I", lists[0].payload, 0)[0]
        assert sorted(struct.unpack_from(f"<{n}I", lists[0].payload, 4)) == \
            sorted(struct.unpack_from("<H", h.payload, 0)[0] for h in heads)
    else:
        assert not lists
    kept_types = {10, 8, 2} | ({S.PLOT} if plots else set()) | ({12} if kind in S.KEEP_OBJECTS else set()) \
        | ({19} if kind == "survival" else set())  # 19: a survival graph's own object
    assert {S._type(o) for o in objs} == kept_types
    assert not any(c.tag in S.REBUILT - S.PLOT_KEPT - S.EXTRA_KEPT.get(kind, frozenset()) for c in ch)
    texts = [c.payload for c in ch if c.tag == 0x002C]
    assert b"Mine" in texts and not any(t.startswith(b"Seed") for t in texts)  # nothing of the seed's table


@pytest.mark.parametrize("kind", S.KINDS)
def test_skeleton_data_matches_the_shipped_seeds(kind):
    """skeleton_data.py is tools/make_skeleton.py's output for the shipped seeds."""
    from refract.formats import seeds
    from refract.formats.pcff.skeleton_data import SKELETONS

    seed = seeds.library().get(kind)
    if seed is None:
        pytest.skip("no shipped seeds")
    drop = frozenset() if kind in S.KEEP_OBJECTS else S.BUILT_OBJECTS - {S.PLOT}
    ch = S.reduce(W.parse(seed.blob), S.PLOT_KEPT | S.EXTRA_KEPT.get(kind, frozenset()), drop_types=drop)
    assert [(c.tag, c.payload) for c in ch] == SKELETONS[kind]


def test_survival_and_pie_skeletons():
    """A survival skeleton keeps 0x000A and the texts' 0x0071 (without them Prism
    crashed); a pie always keeps its plot, which holds the pie data (E-levelc3)."""
    surv = W.parse(S.build("survival")[0])
    assert any(c.tag == 0x000A for c in surv) and sum(1 for c in surv if c.tag == 0x0071) == 4
    pie = S.seed("parts_of_whole", "P", 5, plots=False)
    ch = W.parse(pie.blob)
    assert pie.y_fens == [1] and any(c.tag == 0x80D6 for c in ch)
    assert not any(c.tag == 0x000A for c in W.parse(S.build("column")[0]))


def test_category_labels_are_left_to_prism():
    """Column and grouped skeletons leave the label angle automatic (0x80), as
    Prism's own default graphs are after a re-save (E-layoutfix)."""
    for kind in ("column", "grouped"):
        ch = W.parse(S.build(kind)[0])
        x = next(c for c in ch if c.tag == 0x8025)
        assert x.payload[26] == S.AUTO_ANGLE


def test_one_length_set_keeps_the_other_at_prisms_default(tmp_path):
    from refract.formats.pcff import fields as F
    from refract.ui.document import Document

    doc = Document.new()
    doc.add_table(T.make("grouped", "G", sample=True))
    ng = doc.project.native_graphs[0]
    doc.set_native_options(ng, format={"height": 2.5})
    doc.save(str(tmp_path / "l.prism"))
    ch = W.parse(ZipArchive.open(str(tmp_path / "l.prism")).read(f"graphs/{ng.prism_uid}/data.bin"))
    sets = F.axis_settings(ch)
    assert F.AxisSettings.read(sets[3]).length == 1500 and F.AxisSettings.read(sets[0]).length == 1200  # 2 in


def test_needs_plots():
    assert not S.needs_plots("default", "sd", {"y": {"min": 0}, "title": "T"})
    assert not S.needs_plots("default", None, {"sets": {"0": {}}})
    assert S.needs_plots("bars", "sd", {}) and S.needs_plots("default", "sem", {})
    assert S.needs_plots("default", "sd", {"sets": {"1": {"fill": "#ff0000"}}})
    assert S.needs_plots("default", "sd", {"legend": False})


def test_save_builds_graphs_from_the_skeleton(tmp_path, monkeypatch):
    from refract.formats import open_document
    from refract.render import from_prism
    from refract.ui.document import Document

    doc = Document.new()
    for kind in ("column", "grouped", "xy"):
        doc.add_table(T.make(kind, kind.title(), sample=True))
    col, grp, xy = doc.project.native_graphs
    doc.set_native_options(grp, format={"sets": {"0": {"fill": "#e07a5f"}}})
    out = tmp_path / "c.prism"
    doc.save(str(out))
    z = ZipArchive.open(str(out))
    blobs = {ng.table.kind: W.parse(z.read(f"graphs/{ng.prism_uid}/data.bin")) for ng in (col, grp, xy)}
    for kind, ch in blobs.items():
        assert not any(c.tag == 0x00DB for c in ch)  # caches left for Prism to rebuild
    assert not any(c.tag == 0x8028 for c in blobs["column"])  # unformatted: Prism makes the plots
    assert sum(1 for c in blobs["grouped"] if c.tag == 0x8028) == len(grp.table.datasets)
    # the cached range is the one Prism will draw: Refract's autoscale (written, not manual)
    from refract.formats.pcff import fields as F
    from refract.render import native, qt

    ys = F.AxisSettings.read(F.axis_settings(blobs["xy"])[3])
    want = qt.resolve_axes(native.graph(doc.project, xy))[1]
    assert (ys.min, ys.max, ys.major_tick) == pytest.approx(want)
    assert not F.AxisMode.read(F.axis_modes(blobs["xy"])[1]).flags & F.AxisMode.MANUAL_RANGE
    p = open_document(str(out))  # Refract reads its own Prism copies back
    for i in range(len(p.graphs)):
        from_prism.graph(p, i, z)
    monkeypatch.setenv("REFRACT_GRAPHS", "seed")  # the seeded copies stay available
    doc2 = Document.new()
    doc2.add_table(T.make("column", "C", sample=True))
    doc2.save(str(tmp_path / "s.prism"))
    ch = W.parse(ZipArchive.open(str(tmp_path / "s.prism")).read(
        f"graphs/{doc2.project.native_graphs[0].prism_uid}/data.bin"))
    assert any(c.tag == 0x00DB for c in ch)
    assert os.environ["REFRACT_GRAPHS"] == "seed"
