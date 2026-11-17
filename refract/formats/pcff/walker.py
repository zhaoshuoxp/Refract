"""Lossless parser for the PCFFGRA4 graph/layout binary.

Framing (prismbinder M16, re-verified on the local corpus):
    magic  b"PCFFGRA4"
    then a stream of items:
      tag & 0x4000 and not tag & 0x8000 -> 2-byte close marker, no length
      otherwise                         -> <u16 tag><u32 length><payload>
    tag & 0x8000 opens a container. Its own payload is a header; the children
    follow it in the stream until the matching close marker
    ((tag & 0x3FFF) | 0x4000). A close marker implicitly closes any children
    still open, so lengths never need fixing up when a payload changes size.

Chunks are kept as a flat list of spans into the original buffer, so an
unmodified blob serialises back to identical bytes.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

MAGIC = b"PCFFGRA4"


@dataclass
class Chunk:
    offset: int  # offset of the tag in the blob
    tag: int
    payload: bytes | None  # None for close markers
    depth: int

    @property
    def is_marker(self) -> bool:
        return self.payload is None

    @property
    def is_container(self) -> bool:
        return bool(self.tag & 0x8000)

    @property
    def payload_offset(self) -> int:
        return self.offset + 6


def parse(blob: bytes) -> list[Chunk]:
    if blob[:8] != MAGIC:
        raise ValueError(f"not a PCFFGRA4 blob (magic {blob[:8]!r})")
    chunks: list[Chunk] = []
    stack: list[int] = []
    i = 8
    n = len(blob)
    while i < n:
        if i + 2 > n:
            raise ValueError(f"truncated tag at {i}")
        tag = struct.unpack_from("<H", blob, i)[0]
        if tag & 0x4000 and not tag & 0x8000:
            opener = (tag & 0x3FFF) | 0x8000
            if opener not in stack:
                raise ValueError(f"close marker {tag:#06x} at {i} has no open container")
            # A close marker also closes any still-open children implicitly
            # (seen: 0x8003 left open, closed by the root's 0x4001).
            while stack[-1] != opener:
                stack.pop()
            stack.pop()
            chunks.append(Chunk(i, tag, None, len(stack)))
            i += 2
            continue
        if i + 6 > n:
            raise ValueError(f"truncated length at {i}")
        length = struct.unpack_from("<I", blob, i + 2)[0]
        end = i + 6 + length
        if end > n:
            raise ValueError(f"chunk {tag:#06x} at {i} overruns blob ({end} > {n})")
        chunks.append(Chunk(i, tag, blob[i + 6 : end], len(stack)))
        if tag & 0x8000:
            stack.append(tag)
        i = end
    if stack:
        raise ValueError(f"unclosed containers at end of blob: {[hex(t) for t in stack]}")
    return chunks


def subtree_end(chunks: list[Chunk], i: int) -> int:
    """Index after chunk i and, for a container, everything it holds: up to
    its close marker, or up to (not including) an enclosing container's
    marker that closes it implicitly (0x8003 has none of its own)."""
    if not chunks[i].is_container:
        return i + 1
    stack, j = [chunks[i].tag], i + 1
    while j < len(chunks):
        c = chunks[j]
        if c.is_marker:
            opener = (c.tag & 0x3FFF) | 0x8000
            if opener not in stack:
                return j
            while stack[-1] != opener:
                stack.pop()
            stack.pop()
            if not stack:
                return j + 1
        elif c.is_container:
            stack.append(c.tag)
        j += 1
    return j


def serialize(chunks: list[Chunk]) -> bytes:
    out = bytearray(MAGIC)
    for c in chunks:
        out += struct.pack("<H", c.tag)
        if c.payload is not None:
            out += struct.pack("<I", len(c.payload))
            out += c.payload
    return bytes(out)


def dump(chunks: list[Chunk], max_payload: int = 24) -> str:
    lines = []
    for c in chunks:
        pad = "  " * c.depth
        if c.is_marker:
            lines.append(f"{c.offset:7d} {pad}</{c.tag & 0x3FFF:#06x}>")
        else:
            p = c.payload or b""
            head = p[:max_payload].hex(" ")
            more = "…" if len(p) > max_payload else ""
            kind = "<" if c.is_container else " "
            lines.append(f"{c.offset:7d} {pad}{kind}{c.tag:#06x} len={len(p):<5d} {head}{more}")
    return "\n".join(lines)
