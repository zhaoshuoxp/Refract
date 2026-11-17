"""Graphs for Prism built without a seed graph (PLAN §2.4 level C).

Prism rebuilds most of a graph's PCFF when it opens one (E-levelc): its
caches, the plot list, the property store and every object it can derive
from the graph sheet's `inputDataSets` - the data-set plots (0x8020 type 9),
legend entries (12) and type 14 objects. What it needs from the file is a
skeleton of about 110 chunks:

  0x8001 graph            header (12 bytes), 0x00A1 page settings
    0x8012 contents       0x0013 graph header (rect, kind +14, title text +32),
                          0x009E, three 0x0017 axes, three 0x00A5 axis modes
                          (refract.formats.pcff.fields), nine 0x8025 axis
                          settings, each with its 0x00AD label format and
                          0x0103 label-angle copies
      0x8018 objects      0x0022 / 0x0023 / 0x0021, the frame (0x8020 type
                          10), the X and Y axes (type 8), the four text
                          objects (type 2: graph title, X, Y and right Y
                          titles; refract.formats.pcff.texts)

A graph whose data sets are formatted (colours, symbols, styles: written by
refract.formats.graph_patch) also carries their plot objects - header
0x8028, record 0x009C, data-set link 0x0027 - with the plot list 0x0015 and
the property store 0x0852 (one entry per object, in order). Without 0x0015
Prism takes the plots for missing and makes its own (E-levelc: formatting
lost). Data sets without a plot object get Prism's default plots.

The payloads are Prism's defaults per graph kind, generated into
skeleton_data.py by tools/make_skeleton.py from the shipped seed graphs.
graph_transplant writes the rest as on a seeded copy: document-unique ids,
the graph's fenID, the data sets bound. Texts keep Prism's automatic flag
(0x802B +8 bit 0x4000): Prism draws the graph's name and its own axis
titles until a title is set.

Kinds: column, grouped, xy (every writeback probe graph drawn as its seeded
copy, E-levelc2), survival (with EXTRA_KEPT; E-levelc3), parts of whole
(a pie keeps its plot and objects) and contingency (on the grouped
skeleton, SEED_KIND).
"""

from __future__ import annotations

import struct

from . import propstore as P
from .walker import MAGIC, Chunk, parse, serialize, subtree_end

KINDS = ("column", "grouped", "xy", "survival", "parts_of_whole")  # the skeletons
# table kinds written on another kind's skeleton: Prism draws a contingency table on the grouped
# one as its grouped graph (rows as groups, columns as data sets; E-compare probe 12). A nested
# table on the column skeleton is drawn wrong (its subcolumns averaged as replicates): not written.
SEED_KIND = {"contingency": "grouped"}
WRITTEN_KINDS = (*KINDS, *SEED_KIND)  # the table kinds whose graphs are written for Prism
# kept per kind beyond PLOT_KEPT (E-levelc3): a survival graph without 0x000A makes
# Prism crash while it opens the file; with plot objects but without the text objects'
# 0x0071, Prism crashed when it re-saved the file (both reproduced twice)
EXTRA_KEPT = {"survival": frozenset({0x000A, 0x0071})}
# a pie keeps its plot (it holds the pie data 0x80D6) and its objects (legend entries per
# slice): without them Prism builds a new pie plot and draws its own "Total=N" beside ours
ALWAYS_PLOTS = frozenset({"parts_of_whole"})
KEEP_OBJECTS = frozenset({"parts_of_whole"})
PLOT = 9  # 0x8020 type: a data set's plot
BUILT_OBJECTS = frozenset({PLOT, 12, 14})  # 0x8020 types Prism creates from inputDataSets
# Rebuilt by Prism on open with the drawing unchanged (E-levelc, 42 of 59 tags of
# a column graph; 0x00AE on grouped graphs). 0x00A5 and 0x0103 are rebuilt too,
# but formatting is written into them (graph_patch), so they stay.
REBUILT = frozenset({
    0x0009, 0x000A, 0x0014, 0x0015, 0x0016, 0x0027, 0x0029, 0x002E, 0x0071, 0x0077, 0x0078,
    0x0081, 0x0082, 0x0083, 0x0084, 0x0085, 0x0086, 0x0087, 0x0088, 0x0091, 0x0099, 0x009D,
    0x00A0, 0x00A3, 0x00A4, 0x00A8, 0x00A9, 0x00AE, 0x00DB, 0x00ED, 0x0852, 0x2015, 0x209D,
    0x8003, 0x8028, 0x8080, 0x80AD, 0x80EC})
# kept with plot objects: their header and record, data-set link, the plot list, the
# store; and always the table link 0x0014 and the text extents 0x002E. Rebuilt on a
# default graph, but without them a re-bound XY graph keeps its cached axis ranges, its
# automatic X title shows "X" and the graph title is laid out small (level C check).
PLOT_KEPT = frozenset({0x8028, 0x0029, 0x0027, 0x0015, 0x0852, 0x0014, 0x002E})


def _type(c: Chunk) -> int | None:
    return struct.unpack_from("<H", c.payload, 0)[0] if c.tag == 0x8020 and c.payload else None


def _objects(ch: list[Chunk]) -> list[int]:
    """Indices of the graph objects (the 0x8020s directly in 0x8018)."""
    d = next((c.depth for c in ch if c.tag == 0x8018), None)
    return [i for i, c in enumerate(ch) if c.tag == 0x8020 and c.payload and c.depth == (d or 0) + 1]


def _drop_objects(ch: list[Chunk], gone: set[int]) -> list[Chunk]:
    """Remove the objects at these indices, with their property-store entries,
    and set the object count (0x8018 +4)."""
    objs = _objects(ch)
    store = next((c for c in ch if c.tag == P.TAG and c.payload), None)
    if store is not None and gone:
        v, _raw, tail = P.decode_payload(store.payload)
        arr = v.get("SEDObject_Array") if isinstance(v, P.Dict) else None
        if arr is not None and len(arr.items) == len(objs):
            drop = {objs.index(i) for i in gone}
            arr.items = [it for k, it in enumerate(arr.items) if k not in drop]
            store.payload = P.encode_payload(v, 6, tail)
    out, i = [], 0
    while i < len(ch):
        if i in gone:
            i = subtree_end(ch, i)
            continue
        out.append(ch[i])
        i += 1
    count = next((c for c in out if c.tag == 0x8018 and c.payload and len(c.payload) >= 8), None)
    if count is not None:
        q = bytearray(count.payload)
        struct.pack_into("<I", q, 4, len(_objects(out)))
        count.payload = bytes(q)
    return out


def reduce(ch: list[Chunk], keep: frozenset[int] = frozenset(), drop_types: frozenset[int] = BUILT_OBJECTS
           ) -> list[Chunk]:
    """A graph without what Prism rebuilds: the REBUILT tags (but `keep`) and
    the objects of `drop_types`."""
    ch = _drop_objects(ch, {i for i in _objects(ch) if _type(ch[i]) in drop_types})
    out, i = [], 0
    while i < len(ch):
        c = ch[i]
        if not c.is_marker and c.tag in REBUILT and c.tag not in keep:
            i = subtree_end(ch, i)
            continue
        out.append(c)
        i += 1
    return out


def available() -> bool:
    try:
        from . import skeleton_data  # noqa: F401
    except ImportError:
        return False
    return True


def _chunks(kind: str) -> list[Chunk]:
    from .skeleton_data import SKELETONS

    if kind not in SKELETONS:
        raise ValueError(f"no skeleton for {kind} graphs")
    out = bytearray(MAGIC)
    for tag, pay in SKELETONS[kind]:
        out += struct.pack("<H", tag)
        if pay is not None:
            out += struct.pack("<I", len(pay)) + pay
    return parse(bytes(out))


def plot_fens(kind: str) -> list[int]:
    """The data-set fenIDs of the skeleton's plots, in data-set order."""
    ch = _chunks(kind)
    fens = [struct.unpack_from("<H", c.payload, 4)[0] for c in ch if c.tag == 0x8028 and c.payload]
    return sorted(fens)


def build(kind: str, title: str = "", plots: int = 0) -> tuple[bytes, list[int]]:
    """A default graph of this kind with plot objects for its first `plots`
    data sets (at most the skeleton's six). Returns the blob and the
    data-set fenIDs those plots name (to be bound to the target's data sets:
    graph_transplant.Seed.y_fens)."""
    ch = _chunks(kind)
    fens = plot_fens(kind)[:max(0, plots)]
    objs = _objects(ch)
    gone = set()
    for i in objs:
        if _type(ch[i]) != PLOT:
            continue
        head = next((c for c in ch[i:subtree_end(ch, i)] if c.tag == 0x8028), None)
        if head is None or struct.unpack_from("<H", head.payload, 4)[0] not in fens:
            gone.add(i)
    ch = _drop_objects(ch, gone)
    kept = {struct.unpack_from("<H", c.payload, 0)[0] for c in ch if c.tag == 0x8028 and c.payload}
    out = []
    for c in ch:
        if c.tag == 0x0015 and c.payload:  # the plot list: u32 count, u32 plot id per plot
            if not kept:
                continue  # no plots: Prism makes them all
            n = struct.unpack_from("<I", c.payload, 0)[0]
            ids = [v for v in struct.unpack_from(f"<{n}I", c.payload, 4) if v in kept]
            c.payload = struct.pack(f"<I{len(ids)}I", len(ids), *ids) + c.payload[4 + 4 * n:]
        out.append(c)
    _set_title(out, title)
    if kind in CATEGORY_X:
        _auto_label_angle(out)
    return serialize(out), fens


CATEGORY_X = frozenset({"column", "grouped"})
AUTO_ANGLE = 0x80  # 0x8025 +26 and its 0x0103 copies: Prism chooses the label angle


def _auto_label_angle(ch: list[Chunk]) -> None:
    """The category labels' angle left to Prism, as in its own default graphs
    after a re-save (the grouped seed stored 0, horizontal, which Prism keeps
    once an axis length is set: level C check, E-layoutfix)."""
    idx = [i for i, c in enumerate(ch) if c.tag == 0x8025 and c.payload and len(c.payload) > 26]
    for n, i in enumerate(idx[:3]):  # the X axis's three settings
        p = bytearray(ch[i].payload)
        p[26] = AUTO_ANGLE
        ch[i].payload = bytes(p)
        end = idx[n + 1] if n + 1 < len(idx) else len(ch)
        for c in (c for c in ch[i + 1:end] if c.tag == 0x0103 and c.payload and len(c.payload) >= 4):
            q = bytearray(c.payload)
            for k in range(struct.unpack_from("<I", q, 0)[0]):
                if 8 + 8 * k < len(q):
                    q[8 + 8 * k] = AUTO_ANGLE
            c.payload = bytes(q)


def needs_plots(style: str, error: str | None, fmt: dict | None) -> bool:
    """Whether a graph's formatting is written into its plots (graph_patch):
    a style or error bars other than the default, any data-set format, or a
    hidden legend."""
    fmt = fmt or {}
    return style != "default" or error not in (None, "sd", "mean_sd") or any(fmt.get("sets", {}).values()) \
        or fmt.get("legend") is False  # hidden: each plot is marked out of the legend


def seed(kind: str, title: str, n_sets: int, plots: bool):
    """The skeleton as a graph_transplant.Seed: plot objects for the first
    data sets (up to six) when `plots`, else none."""
    from ..graph_transplant import Seed
    from .skeleton_data import ROLES

    kind = SEED_KIND.get(kind, kind)
    blob, fens = build(kind, title, min(n_sets, 6) if plots or kind in ALWAYS_PLOTS else 0)
    row, x = ROLES[kind]
    return Seed(blob, {"@class": "FENGraphSheet", "$id": "sheets/graph_sheet.schema.json"}, fens, row, x, kind)


def _set_title(ch: list[Chunk], title: str) -> None:
    """The graph title's stored text (it stays automatic: Prism draws the
    graph sheet's name)."""
    head = next(c for c in ch if c.tag == 0x0013)
    tid = struct.unpack_from("<H", head.payload, 32)[0]
    for i, c in enumerate(ch[:-1]):
        if c.tag == 0x802B and struct.unpack_from("<H", c.payload, 0)[0] == tid and ch[i + 1].tag == 0x002C:
            raw = title.encode("cp1252", errors="replace")
            p = bytearray(c.payload)
            struct.pack_into("<H", p, 6, len(raw))
            c.payload = bytes(p)
            ch[i + 1].payload = raw
            return
