"""Prism layouts read for display (docs/format/findings.md, phase 4 batch 8).

A layout's PCFF blob holds one 0x8020 container per placed object. For a
placed graph:
  0x8020 payload: u16, then three rectangles of 4 x i16 (left, top, right,
                  bottom) in 1/600 inch; the first is the object's frame
  0x002f (child): u16 fenID of the graph sheet
  0x0030 (child): u16 x 2, the graph's own size in 1/600 inch
The graph is drawn at frame / own size, its top-left corner at the frame's
(the scale is the same both ways: median difference 1.8 % over 98 corpus
objects). Against Prism's own PDF exports of 26 corpus layouts the drawing
scores a median SSIM of 0.70 (tools/layout_corpus.py); what differs is the
graphs themselves (phase 5), the placement agrees. The page shown here is
the placed objects' bounding box plus a margin, as Prism exports a layout.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from ..formats.pcff import walker as W
from ..model.document import Project
from . import from_prism
from .page import Page, Placement

UNIT = 72 / 600  # 1/600 inch -> points
MARGIN = 6.0


@dataclass
class Placed:
    fen: int | None
    frame: tuple[float, float, float, float]  # points
    own: tuple[float, float] | None  # the graph's own size, points


def placed(blob: bytes) -> list[Placed]:
    chunks = W.parse(blob)
    out: list[Placed] = []
    for i, c in enumerate(chunks):
        if c.tag != 0x8020 or not c.payload or len(c.payload) < 10:
            continue
        rect = struct.unpack_from("<4h", c.payload, 2)
        fen = own = None
        for x in chunks[i + 1:]:
            if x.depth <= c.depth:
                break
            if x.depth != c.depth + 1 or x.payload is None:
                continue
            if x.tag == 0x002F and len(x.payload) >= 2:
                fen = struct.unpack_from("<H", x.payload)[0]
            elif x.tag == 0x0030 and len(x.payload) >= 4:
                w, h = struct.unpack_from("<HH", x.payload)
                own = (w * UNIT, h * UNIT)
        out.append(Placed(fen, tuple(v * UNIT for v in rect), own))
    return out


def page(project: Project, index: int, archive) -> Page:
    """The layout's graphs placed as Prism places them (graphs Refract cannot
    draw, and other objects, are listed in page.notes)."""
    lay = project.layouts[index]
    if not lay.blob or lay.blob[:8] != b"PCFFGRA4":
        raise NotImplementedError("this layout is not stored as PCFF")
    by_fen = {g.fen: i for i, g in enumerate(project.graphs) if g.fen is not None}
    items: list[Placement] = []
    notes: list[str] = []
    for obj in placed(lay.blob):
        if obj.fen is None or obj.fen not in by_fen:
            notes.append("an object that is not a graph of this project (text, picture or table)")
            continue
        gi = by_fen[obj.fen]
        try:
            g = from_prism.graph(project, gi, archive)
        except NotImplementedError as e:
            notes.append(f"graph {project.graphs[gi].title!r}: {e}")
            continue
        x0, y0, x1, y1 = obj.frame
        if obj.own and obj.own[0] > 0 and obj.own[1] > 0:
            k = min((x1 - x0) / obj.own[0], (y1 - y0) / obj.own[1])
        else:
            from . import qt

            gl = qt.layout(g)
            k = min((x1 - x0) / gl.width, (y1 - y0) / gl.height)
        items.append(Placement(g, x0, y0, k, key=gi))
    if not items:
        return Page(200, 100, [], notes or ["no graphs placed"])
    left = min(it.box[0] for it in items) - MARGIN
    top = min(it.box[1] for it in items) - MARGIN
    for it in items:
        it.x -= left
        it.y -= top
    width = max(it.box[2] for it in items) + MARGIN
    height = max(it.box[3] for it in items) + MARGIN
    return Page(width, height, items, notes)
