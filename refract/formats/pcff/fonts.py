"""The document's font table, misc/used_fonts.bin (E-pairs).

Graph texts name their font by an index into it: text-run attribute 0
(refract.formats.pcff.texts) and 0x8025 +34 for tick labels. Layout:

  +0   b"PCFF \\0\\0\\0"
  +8   u32 record count, u32 record size (44), u32 names offset (32),
       u32 names length, u32 records offset, u32 records length
  +32  the names, concatenated, no terminators
  then the records: i32 index, i32 flag (1 on the first), i32 name offset,
       i32 name length, 4 x i32 (0 in Prism's own new entries), i32 weight
       (400 regular, 700 bold), 2 x i32 (0)

Prism keeps one record per (name, weight) a document uses; a bold text uses
the weight-700 record and text-run attribute 2 = 1 (findings.md, E-pairs).
A bundle without the table (one Refract made) gets one starting with
Prism's defaults, Arial regular and bold (indices 0 and 1).
"""

from __future__ import annotations

import struct

NAME = "misc/used_fonts.bin"
MAGIC = b"PCFF \x00\x00\x00"
RECORD = 44
REGULAR, BOLD = 400, 700


def parse(blob: bytes) -> list[tuple[str, int, bytes]]:
    """(name, weight, raw record) per record, in index order."""
    if blob[:8] != MAGIC:
        raise ValueError("not a font table")
    n, size, no, nl, ro, _rl = struct.unpack_from("<6I", blob, 8)
    names = blob[no:no + nl]
    out = []
    for k in range(n):
        r = blob[ro + size * k:ro + size * (k + 1)]
        off, length = struct.unpack_from("<2i", r, 8)
        weight = struct.unpack_from("<i", r, 32)[0] if len(r) >= 36 else REGULAR
        out.append((names[off:off + length].decode("cp1252", errors="replace"), weight, r))
    return out


def build(records: list[tuple[str, int, bytes]]) -> bytes:
    """The table for these records (raw records keep their other fields)."""
    names = b"".join(n.encode("cp1252", errors="replace") for n, _w, _r in records)
    recs, off = [], 0
    for k, (name, weight, raw) in enumerate(records):
        r = bytearray(raw.ljust(RECORD, b"\x00")[:RECORD])
        length = len(name.encode("cp1252", errors="replace"))
        struct.pack_into("<i", r, 0, k)
        struct.pack_into("<2i", r, 8, off, length)
        struct.pack_into("<i", r, 32, weight)
        recs.append(bytes(r))
        off += length
    body = b"".join(recs)
    head = MAGIC + struct.pack("<6I", len(records), RECORD, 32, len(names), 32 + len(names), len(body))
    return head + names + body


def _new(name: str, weight: int, first: bool = False) -> tuple[str, int, bytes]:
    r = bytearray(RECORD)
    struct.pack_into("<i", r, 4, 1 if first else 0)
    return name, weight, bytes(r)


def index(arc, name: str, bold: bool, touched: list[str] | None = None) -> int:
    """The index of (name, bold) in the bundle's font table, added if
    missing (the entry's name then goes into touched)."""
    had = arc.has(NAME)
    records = parse(arc.read(NAME)) if had else [_new("Arial", REGULAR, True), _new("Arial", BOLD)]
    weight = BOLD if bold else REGULAR
    k = next((k for k, (n, w, _r) in enumerate(records) if n == name and w == weight), None)
    if k is None:
        records.append(_new(name, weight))
        k = len(records) - 1
    elif had:
        return k
    arc.put(NAME, build(records))
    if touched is not None and NAME not in touched:
        touched.append(NAME)
    return k
