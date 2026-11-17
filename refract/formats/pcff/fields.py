"""Typed accessors for PCFF chunks whose meaning is known.

Every field documents its evidence. "hypothesis" fields are what E7 tests.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from .walker import Chunk

TAG_AXIS = 0x0017  # 60 bytes, three per graph (prismbinder M16)
TAG_GRAPH_KIND = 0x0013  # byte +14 = graph kind (prismbinder M16)
TAG_TEXT_CONTAINER = 0x802B  # header u16 @6 = text length (275/275 local corpus)
TAG_TEXT = 0x002C  # raw single-byte text, no terminator


@dataclass
class Axis:
    """Tag 0x0017. Offsets from prismbinder M16."""

    data_min: float  # +0  lowest value plotted
    data_max: float  # +8  highest value plotted
    draw_min: float  # +16 where the drawn axis starts (log10 of value when log)
    draw_max: float  # +24 where the drawn axis ends
    cross: float  # +32 where it crosses the other axis
    log: int  # +46 u16: 0 linear, 1 log

    @classmethod
    def read(cls, c: Chunk) -> Axis:
        assert c.tag == TAG_AXIS and c.payload is not None and len(c.payload) == 60
        d = struct.unpack_from("<5d", c.payload, 0)
        (log,) = struct.unpack_from("<H", c.payload, 46)
        return cls(*d, log)

    def write(self, c: Chunk) -> None:
        assert c.tag == TAG_AXIS and c.payload is not None
        p = bytearray(c.payload)
        struct.pack_into("<5d", p, 0, self.data_min, self.data_max, self.draw_min, self.draw_max, self.cross)
        struct.pack_into("<H", p, 46, self.log)
        c.payload = bytes(p)


TAG_AXIS_SETTINGS = 0x8025  # container header, 134 bytes (122 in older files)


@dataclass
class AxisSettings:
    """Tag 0x8025: the axis settings Prism actually renders from.

    There are 9 per graph, in stream order: 3 axes (X, left Y, right Y) x 3
    segments, so the main segment of X / Y / Y2 is at position 0 / 3 / 6.
    Evidence: min/max equal the drawn range in 0x0017 on 1,696 of 1,710 axes
    (all 14 exceptions are segmented axes), and byte +28 separates log10 axes
    (1, 35/35) from linear ones (0). E7 showed that 0x0017 is a cache
    recomputed on open. Log axes store exponents (min -1, max 5 = 0.1 .. 1e5).
    """

    object_id: int  # +0  u16, renumbered per document
    min: float  # +2
    max: float  # +10
    unknown18: float  # +18 (hypothesis: derived scale factor)
    log10: int  # +28 u8: 1 = log10 scale (other scale codes unmapped)
    major_tick: float  # +54 major tick interval (1 = one decade on log axes)
    length: int = 0  # +30 u32: axis length in 1/600 inch (main segments; verified: 1800 / 800 / 1200
    #                  for Prism's default XY / 3-column / grouped X axes, 1200 for every default Y)

    @classmethod
    def read(cls, c: Chunk) -> AxisSettings:
        assert c.tag == TAG_AXIS_SETTINGS and c.payload is not None and len(c.payload) >= 62
        p = c.payload
        (oid,) = struct.unpack_from("<H", p, 0)
        mn, mx, u18 = struct.unpack_from("<3d", p, 2)
        (tick,) = struct.unpack_from("<d", p, 54)
        (length,) = struct.unpack_from("<I", p, 30)
        return cls(oid, mn, mx, u18, p[28], tick, length)

    def write(self, c: Chunk) -> None:
        assert c.tag == TAG_AXIS_SETTINGS and c.payload is not None
        p = bytearray(c.payload)
        struct.pack_into("<3d", p, 2, self.min, self.max, self.unknown18)
        p[28] = self.log10
        struct.pack_into("<d", p, 54, self.major_tick)
        c.payload = bytes(p)


TAG_AXIS_MODE = 0x00A5  # 68 bytes, one per axis (X, Y, Y2), before the 0x80ad blocks


@dataclass
class AxisMode:
    """Tag 0x00A5: per-axis user mode flags, in X, Y, Y2 order.

    Verified by E7e (written by us, rendered by Prism 11.1 Viewer):
    +4  u32 flags. OR-ing in MANUAL_RANGE (0xC) makes Prism use the 0x8025
        header min/max. With the flags at 0 the axis is auto and recomputed on open.
        0x10 is NOT manual tick spacing.
    +64 u16 scale. 1 = log10 (set together with +66 = 1, as Prism 11 writes it).
    """

    MANUAL_RANGE = 0xC  # Prism itself writes 0x800C when the range is set via SetAxisLimits
    MANUAL_TICK = 0x10000  # verified E7f-01 (major tick from 0x8025 +54)
    LOG10 = 1

    flags: int
    scale: int
    scale2: int

    @classmethod
    def read(cls, c: Chunk) -> AxisMode:
        assert c.tag == TAG_AXIS_MODE and c.payload is not None
        p = c.payload
        (flags,) = struct.unpack_from("<I", p, 4)
        scale, scale2 = struct.unpack_from("<HH", p, 64) if len(p) >= 68 else (0, 0)
        return cls(flags, scale, scale2)

    def write(self, c: Chunk) -> None:
        assert c.tag == TAG_AXIS_MODE and c.payload is not None and len(c.payload) >= 68
        p = bytearray(c.payload)
        struct.pack_into("<I", p, 4, self.flags)
        struct.pack_into("<HH", p, 64, self.scale, self.scale2)
        c.payload = bytes(p)


def axis_modes(chunks: list[Chunk]) -> list[Chunk]:
    return [c for c in chunks if c.tag == TAG_AXIS_MODE]


def axis_settings(chunks: list[Chunk]) -> list[Chunk]:
    return [c for c in chunks if c.tag == TAG_AXIS_SETTINGS]


def axes(chunks: list[Chunk]) -> list[Chunk]:
    return [c for c in chunks if c.tag == TAG_AXIS]


def graph_kind(chunks: list[Chunk]) -> int | None:
    for c in chunks:
        if c.tag == TAG_GRAPH_KIND and c.payload is not None and len(c.payload) > 14:
            return c.payload[14]
    return None


def texts(chunks: list[Chunk]) -> list[tuple[int, str]]:
    """(index of the 0x002C chunk, decoded text) for every text object."""
    out = []
    for i, c in enumerate(chunks):
        if c.tag == TAG_TEXT and c.payload is not None:
            out.append((i, c.payload.decode("latin-1")))
    return out


def set_text(chunks: list[Chunk], index: int, text: str, update_length: bool = True) -> None:
    """Replace the text at chunks[index]. Updates the container's length field
    unless update_length is False (diagnostic probes only)."""
    c = chunks[index]
    assert c.tag == TAG_TEXT
    c.payload = text.encode("latin-1")
    if update_length:
        h = chunks[index - 1]
        assert h.tag == TAG_TEXT_CONTAINER and h.payload is not None
        p = bytearray(h.payload)
        struct.pack_into("<H", p, 6, len(c.payload))
        h.payload = bytes(p)
