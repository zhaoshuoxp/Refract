"""Objects drawn on a graph in Refract - lines, arrows, rectangles,
ellipses, text boxes - written as Prism's own graph objects (E-elements).

Prism keeps each as a graph object (0x8020 in the object list 0x8018:
type 3 line or arrow, 1 rectangle, 6 ellipse, 2 text) with a property-store
entry in SEDObject_Array (same order) for its colours. Their stored form
comes from objects drawn by hand in Prism (seed_graphs/objects.json, made by
tools/make_object_templates.py); this module fills in:

  * 0x8020 +2: three boxes (page units, 1/600 inch): the object's box
    widened by 36, the box itself, and the box narrowed by 24 (a text box's
    words wrap inside it), with a copy as 32-bit numbers at 0x00DB +162;
  * a line's ends (0x00D9 +4 x, +8 y) and its arrow head (0x0023 +8,
    0x80D8 +28 = 1); 0x80D8 +4 is the line's own id: unique in the graph,
    or Prism keeps only one of the lines sharing it (E-elements2);
  * line widths: 0x0023 (a line) or 0x0022 (a box's border) +0 the width
    code (as a plot's: 7 + width / 0.72 pt) and the width in 1/600 inch
    (f32 at +22, +16);
  * colours: PCFF_LineStyle::linecolor, PCFF_BorderStyle::bordercolor,
    PCFF_FillStyle::fillcolor (no fill: alpha 0) in the store; the box's
    fill also in 0x0021 +2 (R G B, then 0; none: FF);
  * a text box's words (0x002C), their length (0x802B +6; the last index
    0x002E +2), the line's width (0x002E +10, page units) and a text id of
    its own (0x802B +0); its formatting run (0x002D) stays the template's.
"""

from __future__ import annotations

import json
import os
import struct

from ..render import color, formatting
from .pcff import propstore as P
from .pcff.walker import Chunk, subtree_end

TEMPLATES = os.path.join(os.path.dirname(__file__), "seed_graphs", "objects.json")
U = 600 / 72  # page units per point
WIDEN, NARROW = 36, 24  # the object's outer and inner boxes, page units
TEXT_PAD = 3.0  # pt around a text box's words (refract.render.qt.NOTE_PAD)
DB_BOXES = 162
_templates: dict | None = None


def templates() -> dict:
    global _templates
    if _templates is None:
        with open(TEMPLATES) as f:
            _templates = json.load(f)
    return _templates


def _code(w: float) -> int:
    return 0 if w <= 0 else max(8, min(255, round(w / 0.72) + 7))


def _rgba(hex_or_rgba, alpha: int = 255) -> bytes:
    rgba = formatting.rgba(hex_or_rgba) if isinstance(hex_or_rgba, str) else tuple(hex_or_rgba)
    return bytes(color.from_srgb((*rgba[:3], alpha)))


def _objects(ch: list[Chunk]) -> tuple[int | None, list[int]]:
    d = next((c.depth for c in ch if c.tag == 0x8018), None)
    if d is None:
        return None, []
    return d, [i for i, c in enumerate(ch) if c.tag == 0x8020 and c.payload and c.depth == d + 1]


def _plot_origin(ch: list[Chunk]) -> tuple[int, int] | None:
    for c in ch:
        if c.tag == 0x0013 and c.payload and len(c.payload) >= 8:
            x0, y0, x1, y1 = struct.unpack_from("<4h", c.payload, 0)
            if x1 > x0 and y1 > y0:
                return x0, y0
    return None


def _boxes(x0: int, y0: int, x1: int, y1: int) -> bytes:
    def box(a, b, c, d):
        return struct.pack("<4h", int(a), int(b), int(c), int(d))
    return box(x0 - WIDEN, y0 - WIDEN, x1 + WIDEN, y1 + WIDEN) + box(x0, y0, x1, y1) + \
        box(x0 + NARROW, y0 + NARROW, x1 - NARROW, y1 - NARROW)


def _object(kind: str, ox: int, oy: int, sh: dict, text_id: int | None = None, width_pt: float = 0.0,
            height_pt: float = 0.0, line_id: int | None = None) -> tuple[list[Chunk], list[tuple[str, bytes]]]:
    """The chunks and store entry of one object; sh: a formatting SHAPE (or a NOTE for "text")."""
    t = templates()[kind]
    chunks = [Chunk(0, tag, None if p is None else bytes.fromhex(p), 0) for tag, p in t["chunks"]]
    store = [(k, bytes.fromhex(v)) for k, v in t["store"]]
    if kind == "text":
        cx, top = float(sh.get("x") or 0.0), float(sh.get("y") or 0.0) - TEXT_PAD  # the box around the words
        x1, y1 = ox + (cx - width_pt / 2) * U, oy + top * U
        x2, y2 = ox + (cx + width_pt / 2) * U, oy + (top + height_pt) * U
    else:
        x1, y1 = ox + float(sh.get("x1") or 0) * U, oy + float(sh.get("y1") or 0) * U
        x2, y2 = ox + float(sh.get("x2") or 0) * U, oy + float(sh.get("y2") or 0) * U
    head = bytearray(chunks[0].payload)
    boxes = _boxes(round(min(x1, x2)), round(min(y1, y2)), round(max(x1, x2)), round(max(y1, y2)))
    head[2:26] = boxes
    head[26:30] = b"\x00\x00\x00\x00"
    chunks[0].payload = bytes(head)
    for c in chunks:  # 0x00DB +162: the same boxes as 32-bit numbers (Prism places the object from these)
        if c.tag == 0x00DB and c.payload and len(c.payload) >= DB_BOXES + 48:
            q = bytearray(c.payload)
            struct.pack_into("<12i", q, DB_BOXES, *struct.unpack("<12h", boxes))
            c.payload = bytes(q)
    width = formatting._num(sh.get("width"))
    width = 1.0 if width is None else width
    code = _code(width)
    line_rgb = _rgba(sh.get("color") or "#000000")
    fill = sh.get("fill")
    ends = iter([(x1, y1), (x2, y2)])
    for c in chunks:
        if c.payload is None:
            continue
        q = bytearray(c.payload)
        if c.tag == 0x00D9 and kind in ("line", "arrow"):
            x, y = next(ends)
            struct.pack_into("<2I", q, 4, round(x), round(y))
        elif c.tag == 0x0023 and kind in ("line", "arrow"):
            q[0:4] = struct.pack("<I", code)
            q[4:7] = line_rgb[:3]
            struct.pack_into("<f", q, 22, (code - 7) * 6.0 if code else 0.0)
        elif c.tag == 0x0022 and kind in ("rect", "ellipse"):
            q[0:4] = struct.pack("<I", code)
            struct.pack_into("<f", q, 16, (code - 7) * 6.0 if code else 0.0)
        elif c.tag == 0x0022 and kind == "text":  # Refract's text boxes have no frame
            q[0:4] = struct.pack("<I", 0)
            struct.pack_into("<f", q, 16, 0.0)
        elif c.tag == 0x0021 and kind in ("rect", "ellipse", "text"):
            q[2:6] = (_rgba(fill)[:3] + b"\x00") if fill is not None else b"\xff\xff\xff\xff"
        elif c.tag == 0x80D8 and kind in ("line", "arrow") and line_id is not None and len(q) >= 8:
            struct.pack_into("<I", q, 4, line_id)
        elif c.tag == 0x802B and text_id is not None:
            q[0:2] = struct.pack("<H", text_id)
        elif c.tag == 0x002C and kind == "text":
            q = bytearray(str(sh.get("text", "")).replace("\n", "\r").encode("latin-1", "replace"))
        c.payload = bytes(q)
    if kind == "text":  # the run and line ends follow the words
        n = len(next(c for c in chunks if c.tag == 0x002C).payload)
        for c in chunks:
            if c.tag == 0x802B and c.payload:  # the text's length
                c.payload = c.payload[:6] + struct.pack("<H", n) + c.payload[8:]
            elif c.tag == 0x002E and c.payload and len(c.payload) >= 12:  # the line's end and width
                q = bytearray(c.payload)
                struct.pack_into("<H", q, 2, max(n - 1, 0))
                struct.pack_into("<H", q, 10, max(1, round((width_pt - 2 * TEXT_PAD) * U)))
                c.payload = bytes(q)
    out = []
    for k, raw in store:
        if k == "PCFF_LineStyle::linecolor" and kind in ("line", "arrow"):
            raw = line_rgb
        elif k == "PCFF_BorderStyle::bordercolor" and kind in ("rect", "ellipse"):
            raw = line_rgb if width > 0 else _rgba(sh.get("color") or "#000000", 0)
        elif k == "PCFF_BorderStyle::bordercolor" and kind == "text":
            raw = b"\x00\x00\x00\x00"
        elif k == "PCFF_FillStyle::fillcolor" and kind in ("rect", "ellipse", "text"):
            raw = _rgba(fill) if fill is not None else b"\xff\xff\xff\x00"
        out.append((k, raw))
    return chunks, out


def add(ch: list[Chunk], shapes: list[dict] | None, notes: list[dict] | None, measure=None) -> list[Chunk]:
    """Graph chunks `ch` with Refract's drawn objects and text boxes added as
    Prism objects. measure(note) -> (width, height) in points of a text box
    (refract.render.qt metrics); without it, text boxes are not written."""
    shapes = [s for s in (shapes or []) if isinstance(s, dict) and s.get("kind") in ("line", "arrow", "rect", "ellipse")]
    notes = [n for n in (notes or []) if isinstance(n, dict) and str(n.get("text", "")).strip()] if measure else []
    if not shapes and not notes:
        return ch
    depth, objs = _objects(ch)
    origin = _plot_origin(ch)
    store_c = next((c for c in ch if c.tag == P.TAG and c.payload), None)
    if depth is None or not objs or origin is None or store_c is None:
        raise ValueError("the graph has no object list, plot or colour store")
    v, _raw, tail = P.decode_payload(store_c.payload)
    arr = v.get("SEDObject_Array") if isinstance(v, P.Dict) else None
    if arr is None or len(arr.items) != len(objs):
        raise ValueError("the colour store does not list the graph's objects")
    text_ids = [struct.unpack_from("<H", c.payload, 0)[0] for c in ch if c.tag == 0x802B and c.payload]
    next_id = max(text_ids, default=0) + 1
    line_ids = [struct.unpack_from("<I", c.payload, 4)[0] for c in ch if c.tag == 0x80D8 and c.payload
                and len(c.payload) >= 8]
    next_line = max(line_ids, default=0) + 1
    new: list[Chunk] = []
    for sh in shapes:
        lid = None
        if sh["kind"] in ("line", "arrow"):
            lid, next_line = next_line, next_line + 1
        cs, entry = _object(sh["kind"], *origin, sh, line_id=lid)
        new += cs
        arr.items.append(P.Dict([(k, P.Scalar(raw)) for k, raw in entry]))
    for note in notes:
        w, h = measure(note)
        cs, entry = _object("text", *origin, note, next_id, w, h)
        next_id += 1
        new += cs
        arr.items.append(P.Dict([(k, P.Scalar(raw)) for k, raw in entry]))
    end = subtree_end(ch, objs[-1])  # after the last object, inside the object list
    out = ch[:end] + new + ch[end:]
    store_c.payload = P.encode_payload(v, 6, tail)
    count = next((c for c in out if c.tag == 0x8018 and c.payload and len(c.payload) >= 8), None)
    if count is not None:
        q = bytearray(count.payload)
        struct.pack_into("<I", q, 4, len(objs) + len(shapes) + len(notes))
        count.payload = bytes(q)
    return out
