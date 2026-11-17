"""Object-ID fields inside a PCFF graph blob, and graph duplication.

Learned from Prism's own DuplicateFamily (corpus/auto/dup1): duplicating a
graph renumbers several ID namespaces, each unique across the document. A
copy that keeps the original's IDs is either rejected (graph fenID, E6) or
resolved to the original's objects (text IDs: E6b showed the original's
title).

Every field is a u16 at a byte offset of the chunk payload.
"""

from __future__ import annotations

import struct
import uuid
from collections import defaultdict

from .walker import Chunk

# (tag, offset) -> namespace. "dataset" fields hold data-set fenIDs (the data
# a plot draws, and the row-title set); they follow the data-set fenID map, not
# a counter (grouped and parts-of-whole DuplicateFamily diffs).
# (tag, offset) -> namespace. Three namespaces, merged after the DuplicateFamily
# diff showed which fields shift together (plot/axsub +4, text/axis +8,
# axset/obj2a +10):
#   "plot":  plot ids, equal to the plotted data set's fenID (copy of a table
#            -> plot ids follow the new fenIDs); 0x0027 and plot slots refer to them
#   "text":  text objects; 0x0017 +48 (axis -> its title text) refers to them
#   "axset": axis-settings objects; 0x002a refers to them
ID_FIELDS: dict[tuple[int, int], str] = {
    (0x8025, 0): "axset", (0x0017, 54): "axset", (0x0017, 56): "axset", (0x0017, 58): "axset",
    (0x0017, 48): "axis",
    (0x0027, 4): "dataset",
    (0x8028, 0): "plot", (0x8028, 4): "dataset", (0x009C, 313): "dataset",
    (0x002F, 0): "plot", (0x002F, 2): "plot", (0x0030, 0): "dataset",
    (0x802B, 0): "text",
    (0x002A, 0): "obj2a",
    # learned from Prism duplicates of pie and XY-fit (dose-response) graphs:
    # each field shifted together with the namespace named here
    (0x009C, 141): "slice", (0x80F6, 8): "slice", (0x80F6, 16): "plot", (0x00A9, 16): "plot",
    (0x009C, 20): "dataset", (0x80F6, 20): "dataset", (0x00A9, 20): "dataset",
    (0x000A, 20): "obj2a",
    # pie-chart objects (parts-of-whole DuplicateFamily diff)
    (0x00F8, 4): "pie", (0x00F8, 8): "pie2", (0x00DB, 4): "pie", (0x009E, 64): "pie",
    (0x0013, 32): "text",
    # the pie's plot data (one 0x80d6 per pie graph, E-pie): +4 an id unique in the
    # document, +12 the pie's plot, +24 a text; +8 is the graph fenID. Left as in the
    # seed, every copy claims the same id and the seed's graph: Prism leaves the
    # first such pie blank and draws another graph with the copy's settings
    (0x80D6, 4): "pdata", (0x80D6, 12): "plot", (0x80D6, 24): "text",
}
# Fields holding the graph's own fenID (same as the 0x8012 header).
GRAPH_FEN_FIELDS = [(0x8012, 0), (0x0013, 8), (0x8018, 0), (0x009C, 113), (0x80F6, 12),
                    # survival graphs (Prism 10.5+ chunks; survival DuplicateFamily diff, E-survival)
                    (0x2018, 4), (0x2019, 20), (0x201A, 8),
                    (0x80D6, 8)]  # pie plot data (E-pie)
SURVIVAL_TAGS = (0x2019, 0x201A)
# 0x00db frames an object. Its +158 field takes the ID of the framed object
# in the same 0x8020 container, by this priority.
FRAME = (0x00DB, 158)
FRAMED_PRIORITY = [(0x802B, "text"), (0x8028, "plot"), (0x002A, "obj2a")]


def _u16(p: bytes, o: int) -> int:
    return struct.unpack_from("<H", p, o)[0]


def _set_u16(c: Chunk, o: int, v: int) -> None:
    p = bytearray(c.payload)
    struct.pack_into("<H", p, o, v)
    c.payload = bytes(p)


def containers(chunks: list[Chunk], tag: int) -> list[tuple[int, int]]:
    """(open index, close index) of every container with this tag."""
    out, stack = [], []
    for i, c in enumerate(chunks):
        if c.is_container:
            stack.append((c.tag, i))
        elif c.is_marker:
            opener = (c.tag & 0x3FFF) | 0x8000
            while stack and stack[-1][0] != opener:
                stack.pop()
            if stack:
                t, s = stack.pop()
                if t == tag:
                    out.append((s, i))
    return out


def _slot_offsets(c: Chunk) -> list[int]:
    """Plot-slot id offsets in 0x0016 (u16 count + 12-byte slots) and 0x00a0
    (u32, u32 count + 32-byte slots). In GraphPad's samples these ids differ
    from the data-set fenIDs in 0x0015, so they are plot ids."""
    p = c.payload
    if c.tag == 0x0016 and p and len(p) >= 2:
        n = _u16(p, 0)
        return [2 + 12 * k for k in range(n) if 2 + 12 * k + 2 <= len(p)]
    if c.tag == 0x00A0 and p and len(p) >= 8:
        n = struct.unpack_from("<I", p, 4)[0]
        return [8 + 32 * k for k in range(n) if 8 + 32 * k + 2 <= len(p)]
    return []


# Fields valid only under a given parent: parent tag, or (0x8020, object type)
# where the 0x8020 header u16 is the object type (9 plot, 2 text, 12 legend entry).
PARENT_ONLY: dict[tuple[int, int], tuple[int, int | None]] = {
    (0x00DB, 4): (0x80FA, None),
    (0x009C, 313): (0x8028, None), (0x009C, 141): (0x8028, None), (0x009C, 20): (0x8028, None),
    (0x80F6, 8): (0x8028, None), (0x80F6, 16): (0x8028, None), (0x80F6, 20): (0x8028, None),
    (0x00A9, 16): (0x8020, 9), (0x00A9, 20): (0x8020, 9),
    (0x002F, 0): (0x8020, 12), (0x002F, 2): (0x8020, 12), (0x0030, 0): (0x8020, 12),
}
OBJ_PLOT, OBJ_TEXT, OBJ_LEGEND = 9, 2, 12
NULL_FLOOR = 0x8000  # values at or above this are sentinels (0xFFFF = none), never renumbered


def parents(chunks: list[Chunk]) -> list[Chunk | None]:
    """The innermost open container chunk of each chunk."""
    out: list[Chunk | None] = []
    stack: list[Chunk] = []
    for c in chunks:
        out.append(stack[-1] if stack else None)
        if c.is_container:
            stack.append(c)
        elif c.is_marker:
            opener = (c.tag & 0x3FFF) | 0x8000
            while stack and stack[-1].tag != opener:
                stack.pop()
            if stack:
                stack.pop()
    return out


# Context-specific fields: (tag, offset, required parent tag or None, namespace).
# Pie-chart objects, learned from the parts-of-whole DuplicateFamily diff.
CTX_FIELDS: list[tuple[int, int, int | None, str]] = [
    (0x00F9, 8, 0x80FA, "pie"), (0x00F9, 16, 0x80FA, "pie"),
    (0x80F4, 4, None, "pie"), (0x80F4, 8, None, "pie2"), (0x80F4, 152, None, "pie"),
    (0x80F4, 156, None, "pie3"), (0x80F4, 160, None, "pie3"), (0x00F5, 8, 0x80F4, "pie"),
    (0x00F7, 8, None, "pie3"),
]
# (tag, offset, parent tag, parent header type, namespace)
CTX_TYPED_FIELDS: list[tuple[int, int, int, int, str]] = [
    (0x00A9, 16, 0x80FA, 17, "pie"),  # elsewhere under 0x80fa this field is a constant (110)
]
PIE_LABEL_TEXT_REFS = (0x00F9, 64, 12)  # text ids at 64, 76, 88, ... (12-byte records)


def _fields(c: Chunk, parent: Chunk | None = None):
    for tag, off, ptag, ns in CTX_FIELDS:
        if c.tag == tag and len(c.payload) >= off + 2 and (ptag is None or (parent is not None and parent.tag == ptag)):
            yield off, ns
    for tag, off, ptag, ptype, ns in CTX_TYPED_FIELDS:
        if (c.tag == tag and len(c.payload) >= off + 2 and parent is not None and parent.tag == ptag
                and parent.payload and len(parent.payload) >= 2 and _u16(parent.payload, 0) == ptype):
            yield off, ns
    if c.tag == PIE_LABEL_TEXT_REFS[0] and parent is not None and parent.tag == 0x80FA:
        o = PIE_LABEL_TEXT_REFS[1]
        while o + 2 <= len(c.payload):
            yield o, "text"
            o += PIE_LABEL_TEXT_REFS[2]
    for (tag, off), ns in ID_FIELDS.items():
        if c.tag == tag and len(c.payload) >= off + 2:
            need = PARENT_ONLY.get((tag, off))
            if need is not None:
                ptag, ptype = need
                if parent is None or parent.tag != ptag:
                    continue
                if ptype is not None and (len(parent.payload or b"") < 2 or _u16(parent.payload, 0) != ptype):
                    continue
            yield off, ns
    for off in _slot_offsets(c):
        yield off, "dataset"


def collect_ids(chunks: list[Chunk]) -> dict[str, set[int]]:
    ids: dict[str, set[int]] = defaultdict(set)
    for c, par in zip(chunks, parents(chunks), strict=True):
        if c.payload is not None:
            for off, ns in _fields(c, par):
                v = _u16(c.payload, off)
                if v < NULL_FLOOR:  # 0xFFFF (-1) means "no reference"
                    ids[ns].add(v)
    return ids


def renumber(chunks: list[Chunk], taken: dict[str, set[int]],
             plot_map: dict[int, int] | None = None) -> dict[str, dict[int, int]]:
    """Give text and axis-settings IDs fresh values above everything in
    `taken` (IDs used anywhere in the document). Plot IDs are data-set fenIDs:
    they change only through `plot_map` (old fenID -> new fenID) when the copy
    plots other data sets. Edits chunks in place."""
    mine = collect_ids(chunks)
    maps: dict[str, dict[int, int]] = {"plot": dict(plot_map or {})}
    for ns, vals in mine.items():
        if ns == "plot":
            continue
        # constant shift per namespace (keeps gaps, like Prism's own copies)
        shift = max(taken.get(ns, set()) | vals) + 1 - min(vals)
        maps[ns] = {v: v + shift for v in vals}
    # frames first: decide from the original (pre-renumbering) framed IDs
    for s, e in containers(chunks, 0x8020) + containers(chunks, 0x80FA):
        kids = [i for i in range(s + 1, e) if chunks[i].payload is not None]
        frame = next((i for i in kids if chunks[i].tag == FRAME[0] and len(chunks[i].payload) >= FRAME[1] + 2), None)
        if frame is None:
            continue
        for tag, ns in FRAMED_PRIORITY:
            obj = next((i for i in kids if chunks[i].tag == tag), None)
            if obj is not None:
                old = _u16(chunks[frame].payload, FRAME[1])
                if old in maps.get(ns, {}):
                    _set_u16(chunks[frame], FRAME[1], maps[ns][old])
                break
    for c, par in zip(chunks, parents(chunks), strict=True):
        if c.payload is None:
            continue
        for off, ns in list(_fields(c, par)):
            old = _u16(c.payload, off)
            if old in maps.get(ns, {}):
                _set_u16(c, off, maps[ns][old])
    return maps


def mark_copy_slots(chunks: list[Chunk]) -> None:
    """Prism's copies write -1 into the two u32s after each 0x0016 slot id and
    the 12 bytes after each 0x00a0 slot id (DuplicateFamily diff)."""
    for c in chunks:
        if c.payload is None:
            continue
        p = bytearray(c.payload)
        if c.tag == 0x0016:
            for o in _slot_offsets(c):
                p[o + 4:o + 12] = b"\xff" * 8
        elif c.tag == 0x00A0:
            for o in _slot_offsets(c):
                p[o + 4:o + 16] = b"\xff" * 12
        else:
            continue
        c.payload = bytes(p)


def set_graph_fen(chunks: list[Chunk], fen: int) -> None:
    for c in chunks:
        for tag, off in GRAPH_FEN_FIELDS:
            if c.tag == tag and c.payload is not None and len(c.payload) >= off + 2:
                _set_u16(c, off, fen)


def survival_dataset_offsets(c: Chunk) -> list[int]:
    """u32 data-set fenID fields of a survival graph's chunks (survival
    DuplicateFamily diff, E-survival):
      0x201a, the number-at-risk table cache: header (u32 header size, 0,
        graph fen, record count n, group count g, record size, ...), n records
        each starting with the group's data-set fen, then g name entries of
        24 bytes (fen, 0, string offset, 0, string length, -1) and the names;
      0x2019: ends with one 20-byte entry per group (fen first) and a closing
        entry whose fen is -1."""
    p = c.payload or b""
    out: list[int] = []
    if c.tag == 0x201A and len(p) >= 24:
        head, _z, _g, n, groups, size = struct.unpack_from("<6I", p, 0)
        recs = [head + k * size for k in range(n)]
        names = [head + n * size + 24 * k for k in range(groups)]
        out = [o for o in recs + names if o + 4 <= len(p)]
    elif c.tag == 0x2019 and len(p) >= 40:
        o = len(p) - 20
        if struct.unpack_from("<i", p, o)[0] == -1:
            o -= 20
            while o >= 40 and struct.unpack_from("<i", p, o)[0] not in (-1,) and \
                    0 <= struct.unpack_from("<i", p, o)[0] < NULL_FLOOR and struct.unpack_from("<i", p, o + 4)[0] == 0:
                out.insert(0, o)
                o -= 20
    return out


def map_survival_datasets(chunks: list[Chunk], fen_map: dict[int, int]) -> None:
    """Re-point the data-set fenIDs of survival chunks (u32); fens mapped to
    a u16 sentinel (deleted, 0xFFFD) become the i32 form (-3)."""
    for c in chunks:
        if c.tag not in SURVIVAL_TAGS or c.payload is None:
            continue
        p = bytearray(c.payload)
        for o in survival_dataset_offsets(c):
            v = struct.unpack_from("<i", p, o)[0]
            if v in fen_map:
                nv = fen_map[v]
                struct.pack_into("<i", p, o, nv - 0x10000 if nv >= NULL_FLOOR else nv)
        c.payload = bytes(p)


def set_graph_name(chunks: list[Chunk], name: str) -> None:
    """0x0009 holds the graph sheet's name, NUL-terminated."""
    for c in chunks:
        if c.tag == 0x0009 and c.payload is not None:
            c.payload = name.encode("latin-1") + b"\x00"
            return


def new_instance_uuid(chunks: list[Chunk]) -> None:
    for c in chunks:
        if c.tag == 0x2015 and c.payload is not None and len(c.payload) == 37:
            c.payload = str(uuid.uuid4()).upper().encode() + b"\x00"


def set_dataset_refs(chunks: list[Chunk], new_fens: list[int]) -> None:
    """Point the graph at other data sets: 0x0015 = u32 count + u32 data-set
    fenID per plot (the JSON inputDataSets carry the same binding)."""
    for c in chunks:
        if c.tag == 0x0015 and c.payload is not None:
            p = bytearray(c.payload)
            n = struct.unpack_from("<I", p, 0)[0]
            for k in range(min(n, len(new_fens))):
                struct.pack_into("<I", p, 4 + 4 * k, new_fens[k])
            c.payload = bytes(p)
