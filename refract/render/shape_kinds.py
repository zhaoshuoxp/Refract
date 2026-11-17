"""The objects that can be drawn on a graph (Draw menu): each kind is made
of the four primitives Prism stores for drawn objects - line, arrow,
rectangle, ellipse - so that Refract and Prism show the same marks
(refract.formats.graph_objects writes the primitives). A kind drawn with
"label" (lines with text) also carries a text, written as a text box.

Coordinates are points from the plot's top-left; a kind is drawn in the
box from (x1, y1) to (x2, y2), dragged on the graph.
"""

from __future__ import annotations

import math

# kind -> (menu group, label); in the Draw menu's order
KINDS: dict[str, tuple[str, str]] = {
    "ellipse": ("Shapes", "Ellipse"), "circle": ("Shapes", "Circle"), "rect": ("Shapes", "Rectangle"),
    "square": ("Shapes", "Square"), "roundrect": ("Shapes", "Rounded rectangle"),
    "elbow": ("Shapes", "Elbow connector"), "elbow_arrow": ("Shapes", "Elbow arrow"),
    "line": ("Lines", "Line"), "arrow": ("Lines", "Arrow"), "arrow2": ("Lines", "Double arrow"),
    "ibeam": ("Lines", "Line with end bars"), "cap": ("Lines", "Line with an end bar"),
    "bracket": ("Lines", "Bracket (legs down)"), "bracket_up": ("Lines", "Bracket (legs up)"),
    "bracket_left": ("Lines", "Square bracket ["), "bracket_right": ("Lines", "Square bracket ]"),
}
PRIMITIVE = ("line", "arrow", "rect", "ellipse")
LEG = 4.0  # pt: a bracket's legs when it is drawn flat (as a significance bracket's)
CAP = 3.0  # pt: half an end bar
LABELLED = ("line", "arrow", "arrow2", "ibeam", "cap", "bracket", "bracket_up", "bracket_left", "bracket_right")


def _ln(sh: dict, x1, y1, x2, y2, kind: str = "line") -> dict:
    out = {k: sh[k] for k in ("color", "width", "dash") if k in sh}
    out.update(kind=kind, x1=x1, y1=y1, x2=x2, y2=y2)
    return out


def primitives(sh: dict) -> list[dict]:
    """The lines, arrows, rectangles and ellipses that draw object `sh`."""
    kind = sh.get("kind", "line")
    x1, y1, x2, y2 = (float(sh.get(k) or 0.0) for k in ("x1", "y1", "x2", "y2"))
    if kind in PRIMITIVE:
        return [dict(sh)]
    if kind in ("circle", "square"):
        d = max(abs(x2 - x1), abs(y2 - y1))
        box = {**sh, "kind": "ellipse" if kind == "circle" else "rect",
               "x2": x1 + math.copysign(d, (x2 - x1) or 1), "y2": y1 + math.copysign(d, (y2 - y1) or 1)}
        return [box]
    if kind == "roundrect":
        return [{**sh, "kind": "rect"}]  # Prism has no rounded box: a rectangle there
    x0, xa = sorted((x1, x2))
    y0, ya = sorted((y1, y2))
    if kind in ("elbow", "elbow_arrow"):  # across, then down (or up) to the end
        return [_ln(sh, x1, y1, x2, y1), _ln(sh, x2, y1, x2, y2, "arrow" if kind == "elbow_arrow" else "line")]
    if kind == "arrow2":
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        return [_ln(sh, mx, my, x1, y1, "arrow"), _ln(sh, mx, my, x2, y2, "arrow")]
    if kind in ("ibeam", "cap"):
        d = math.hypot(x2 - x1, y2 - y1) or 1.0
        nx, ny = -(y2 - y1) / d * CAP, (x2 - x1) / d * CAP
        out = [_ln(sh, x1, y1, x2, y2), _ln(sh, x2 - nx, y2 - ny, x2 + nx, y2 + ny)]
        if kind == "ibeam":
            out.append(_ln(sh, x1 - nx, y1 - ny, x1 + nx, y1 + ny))
        return out
    if kind in ("bracket", "bracket_up"):
        l1, l2 = legs(sh)
        s_ = 1 if kind == "bracket" else -1  # legs down, or up
        y_bar = y0 if kind == "bracket" else ya
        return [_ln(sh, x0, y_bar + s_ * l1, x0, y_bar), _ln(sh, x0, y_bar, xa, y_bar),
                _ln(sh, xa, y_bar, xa, y_bar + s_ * l2)]
    if kind in ("bracket_left", "bracket_right"):
        l1, l2 = legs(sh)
        s_ = 1 if kind == "bracket_left" else -1  # arms to the right, or to the left
        x_bar = x0 if kind == "bracket_left" else xa
        return [_ln(sh, x_bar + s_ * l1, y0, x_bar, y0), _ln(sh, x_bar, y0, x_bar, ya),
                _ln(sh, x_bar, ya, x_bar + s_ * l2, ya)]
    return [_ln(sh, x1, y1, x2, y2)]


BRACKETS = ("bracket", "bracket_up", "bracket_left", "bracket_right")


def legs(sh: dict) -> tuple[float, float]:
    """A bracket's two legs (or a square bracket's two arms), pt: "leg1" / "leg2" when set (dragged by
    their handles), else the dragged box's height (width), or LEG when it was drawn flat."""
    x1, y1, x2, y2 = (float(sh.get(k) or 0.0) for k in ("x1", "y1", "x2", "y2"))
    side = abs(x2 - x1) if sh.get("kind") in ("bracket_left", "bracket_right") else abs(y2 - y1)
    base = side if side >= 2 else LEG
    out = []
    for k in ("leg1", "leg2"):
        v = sh.get(k)
        out.append(max(0.0, float(v)) if isinstance(v, (int, float)) else base)
    return out[0], out[1]


def leg_tips(sh: dict) -> list[tuple[int, float, float]]:
    """A bracket's leg-tip handles: (3, x, y) and (4, x, y), points from the plot's top-left."""
    if sh.get("kind") not in BRACKETS:
        return []
    p = primitives(sh)
    return [(3, p[0]["x1"], p[0]["y1"]), (4, p[2]["x2"], p[2]["y2"])]


def leg_change(sh: dict, dx: float, dy: float) -> float:
    """How much a leg grows when its tip is dragged by (dx, dy)."""
    return {"bracket": dy, "bracket_up": -dy, "bracket_left": dx, "bracket_right": -dx}.get(sh.get("kind"), 0.0)


def label_anchor(sh: dict) -> tuple[float, float, str]:
    """Where a labelled object's text goes: (x, y, side) - "above" (centred
    on x, its baseline at y) or "right" / "left" (beside the point)."""
    kind = sh.get("kind", "line")
    x1, y1, x2, y2 = (float(sh.get(k) or 0.0) for k in ("x1", "y1", "x2", "y2"))
    x0, xa = sorted((x1, x2))
    y0, ya = sorted((y1, y2))
    if kind == "bracket_left":
        return x0 - 3, (y0 + ya) / 2, "left"
    if kind == "bracket_right":
        return xa + 3, (y0 + ya) / 2, "right"
    if kind == "bracket_up":
        return (x0 + xa) / 2, ya + 12, "above"
    if kind == "bracket":
        return (x0 + xa) / 2, y0 - 2, "above"
    return (x1 + x2) / 2, min(y1, y2) - 3, "above"


def for_prism(shapes: list[dict], measure=None) -> tuple[list[dict], list[dict]]:
    """Refract's drawn objects as Prism can store them: their primitives
    (refract.formats.graph_objects) and, for lines with text, a text box
    (formatting NOTE: centre x, top y) holding the text where Refract draws
    it. measure(note) -> (width, height) pt places a text box beside a
    square bracket; without it the box's height is taken from its size."""
    prims, notes = [], []
    for sh in shapes:
        if not sh:
            continue
        prims += primitives(sh)
        text = str(sh.get("label") or "")
        if not text:
            continue
        size = float(sh.get("label_size") or 12.0)
        note = {"text": text, **({"size": size} if sh.get("label_size") else {})}  # 12 pt: Prism's own default
        if sh.get("label_color"):
            note["color"] = sh["label_color"]
        w, h = measure(note) if measure else (0.6 * size * len(text) + 6, 1.2 * size + 6)
        x, y, side = label_anchor(sh)
        top = y - 0.9 * size - 3 if side == "above" else y - h / 2
        cx = x if side == "above" else (x + w / 2 if side == "right" else x - w / 2)
        notes.append({**note, "x": round(cx, 2), "y": round(top, 2)})
    return prims, notes
