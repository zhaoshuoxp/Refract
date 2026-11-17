"""Text objects of a PCFF graph, written (graph and axis titles; E-axes).

A text object is a 0x802B container (+0 its id, +6 the text length, +8 flags)
followed by 0x002C (the text, single-byte, code page 1252) and 0x002D (its
formatting runs: u16 run count; per run u16 attribute count, u32 start, then
(u16 id, u32 value) pairs; 1 = size, 9 = size x 1000).

0x802B +8 bit 0x4000 marks a text Prism derives itself (the graph title from
the graph's name, an XY graph's X title from the X column's title, the
placeholders "XTitle"/"YTitle"): Prism ignores the stored text and draws its
own. Writing a text clears it, and Prism then draws the text as written,
laying it out itself (verified in Prism, E-axes).
"""

from __future__ import annotations

import struct

from .walker import Chunk

AUTO = 0x4000
FONT, SIZE, BOLD, SIZE_1000 = 0, 1, 2, 9  # text-run attributes


def _u16(p: bytes, o: int) -> int:
    return struct.unpack_from("<H", p, o)[0]


def graph_title_id(chunks: list[Chunk]) -> int | None:
    """The graph title's text id (0x0013 +32)."""
    c = next((c for c in chunks if c.tag == 0x0013 and c.payload and len(c.payload) >= 34), None)
    v = _u16(c.payload, 32) if c is not None else 0xFFFF
    return None if v == 0xFFFF else v


def axis_title_id(chunks: list[Chunk], which: int) -> int | None:
    """An axis title's text id (0x0017 +48; which: 0 X, 1 Y, 2 right Y)."""
    axes = [c for c in chunks if c.tag == 0x0017 and c.payload and len(c.payload) >= 50]
    v = _u16(axes[which].payload, 48) if which < len(axes) else 0xFFFF
    return None if v == 0xFFFF else v


def index(chunks: list[Chunk], tid: int) -> int | None:
    for i, c in enumerate(chunks[:-1]):
        if c.tag == 0x802B and c.payload and len(c.payload) >= 10 and _u16(c.payload, 0) == tid \
                and chunks[i + 1].tag == 0x002C:
            return i
    return None


def encodable(text: str) -> bool:
    try:
        text.encode("cp1252")
    except UnicodeEncodeError:
        return False
    return True


def set_text(chunks: list[Chunk], tid: int, text: str) -> bool:
    """Write the text and make Prism draw it as written; False if there is no
    such text object."""
    i = index(chunks, tid)
    if i is None:
        return False
    raw = text.encode("cp1252", errors="replace")
    p = bytearray(chunks[i].payload)
    struct.pack_into("<H", p, 6, len(raw))
    struct.pack_into("<H", p, 8, _u16(p, 8) & ~AUTO)
    chunks[i].payload = bytes(p)
    chunks[i + 1].payload = raw
    return True


def set_size(chunks: list[Chunk], tid: int, size: float) -> bool:
    """Font size of every formatting run of the text."""
    i = index(chunks, tid)
    if i is None or i + 2 >= len(chunks) or chunks[i + 2].tag != 0x002D or not chunks[i + 2].payload:
        return False
    p = bytearray(chunks[i + 2].payload)
    n, o = _u16(p, 0), 2
    hit = False
    for _ in range(n):
        cnt = _u16(p, o)
        o += 6
        for _ in range(cnt):
            k = _u16(p, o)
            if k == SIZE:
                struct.pack_into("<I", p, o + 2, round(size))
                hit = True
            elif k == SIZE_1000:
                struct.pack_into("<I", p, o + 2, round(size * 1000))
                hit = True
            o += 6
    chunks[i + 2].payload = bytes(p)
    return hit


def set_fonts(chunks: list[Chunk], font_index) -> int:
    """Every text's font: font_index(bold) gives the font-table index
    (refract.formats.pcff.fonts) for a run that is bold or not. Returns the
    number of runs changed."""
    hit = 0
    for c in chunks:
        if c.tag != 0x002D or not c.payload or len(c.payload) < 2:
            continue
        p = bytearray(c.payload)
        o = 2
        for _ in range(_u16(p, 0)):
            if o + 6 > len(p):
                break
            cnt = _u16(p, o)
            attrs = {}
            for k in range(cnt):
                a = o + 6 + 6 * k
                attrs[_u16(p, a)] = (a, struct.unpack_from("<I", p, a + 2)[0])
            if FONT in attrs:
                bold = attrs.get(BOLD, (0, 0))[1] == 1
                struct.pack_into("<I", p, attrs[FONT][0] + 2, font_index(bold))
                hit += 1
            o += 6 + 6 * cnt
        c.payload = bytes(p)
    return hit

