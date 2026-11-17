"""Formatting of Refract's graphs (Format Graph / Format Axes, docs/ui-spec.md
§3.4): a JSON-friendly dict of overrides on top of the graph built from the
table, stored with the graph (x-refract/graphs.json).

    {"title": str, "title_size": pt, "font": family, "legend": bool,
     "width": in, "height": in,                      # axis lengths
     "x": AXIS, "y": AXIS,
     "sets": {"<data set index>": SET}}
    AXIS = {"title": str, "title_size": pt, "label_size": pt, "min", "max",
            "tick": number, "log": bool, "minor": int, "angle": degrees}
    SET  = {"fill": "#rrggbb", "color": "#rrggbb", "symbol": name,
            "size": pt, "points": bool, "connect": bool,
            "border": "#rrggbb", "border_width": pt (0: none),  # bars, boxes
            "pattern": PATTERN, "pattern_color": "#rrggbb",  # a hatch over the fill
            "error_color": "#rrggbb", "error_width": pt,
            "line_color": "#rrggbb", "line_width": pt}  # the connecting line
    PATTERN = a key of PATTERNS ("" none, "/", "x bold", "bricks", ...)
    "texts": {"<text id>": TEXT}      # text objects edited on the canvas
    TEXT = {"text": str, "dx": pt, "dy": pt, "size": pt, "bold", "italic",
            "underline": bool, "color": "#rrggbb", "family": name}
    "notes": [NOTE]                   # text boxes added in Refract
    NOTE = {"text": str, "x", "y": pt from the plot's top-left (box centre,
            top), and TEXT's style keys}
    "background", "plot_fill", "axis_color": "#rrggbb"
    "shapes": [SHAPE]                 # objects drawn in Refract
    SHAPE = {"kind": a refract.render.shape_kinds.KINDS key, "x1", "y1", "x2",
             "y2": pt from the plot's top-left, "color": "#rrggbb", "width": pt,
             "fill": "#rrggbb" (boxes and ellipses; absent: none), "dash": bool,
             "label": text, "label_size": pt, "label_color" (lines with text)}
    SET "bars": {"<bar index>": {"fill", "pattern", "pattern_color", "border",
             "border_width"}}         # Format This Bar
    "scheme": the colour scheme applied (colour menus offer its colours first)

Text ids (refract.render.qt.text_items): "title", "x.title", "y.title",
"x.labels", "y.labels" (style only), "legend.<data set>", "sig.<bracket>",
"ann.<annotation>" (texts placed in Prism), "note.<n>". Other objects
(refract.render.qt.object_at): "set.<data set>", "bracket.<j>" (a
significance bracket: "texts" {"dx", "dy", "color", "width", "dl", "dr"
(its ends stretched), "ll", "lr" (its legs lengthened), "hidden"} moves it
with its label), "abr.<annotation>" (a bracket or arrow placed in Prism:
"texts" {"dx", "dy", "left", "right", "leg_first", "leg_last", "color",
"width", "hidden"}), "shape.<n>" (a drawn bracket's legs: SHAPE "leg1",
"leg2"). The graph title's and
axis titles' text and size live in their usual keys ("title",
"title_size", AXIS) so that they are written for Prism too.

Missing keys keep what the graph has (Prism's defaults for the table).
"""

from __future__ import annotations

import copy
import math
from typing import Any

from .model import Axis, Graph, Series, TextStyle

SYMBOLS = {"circle": "Circle", "square": "Square", "triangle": "Triangle", "triangle_down": "Triangle (down)",
           "diamond": "Diamond", "none": "None"}
FONTS = ["Arial", "Helvetica", "Times New Roman", "Courier New", "Verdana"]
POINTS_PER_INCH = 72.0


def hex_color(rgba) -> str:
    r, g, b = rgba[:3]
    return f"#{r:02x}{g:02x}{b:02x}"


def rgba(text: str, alpha: int = 255) -> tuple[int, int, int, int]:
    t = text.lstrip("#")
    return int(t[0:2], 16), int(t[2:4], 16), int(t[4:6], 16), alpha


def _num(v) -> float | None:
    if isinstance(v, bool) or v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _axis(ax: Axis, f: dict[str, Any], numeric: bool) -> None:
    if "title" in f:
        ax.title = str(f["title"])
    if _num(f.get("title_size")):
        ax.title_style.size = _num(f["title_size"])
    if _num(f.get("label_size")):
        ax.label_style.size = _num(f["label_size"])
    if "angle" in f:
        ax.label_angle = _num(f["angle"])  # None: automatic
    if not numeric:
        return
    log = bool(f.get("log", ax.log))
    if log != ax.log:  # switching scale: the range in effect (e.g. cached from the file) no longer applies
        ax.min = ax.max = ax.tick = None
    ax.log = log
    for k in ("min", "max", "tick"):
        v = _num(f.get(k))
        if k in f:
            setattr(ax, k, v if not (log and v is not None and v <= 0) else None)
    if "minor" in f and _num(f["minor"]) is not None:
        ax.minor = max(0, int(_num(f["minor"])))
        ax.minor_auto = False


def _series(s: Series, f: dict[str, Any]) -> None:
    if "fill" in f:
        s.fill = rgba(f["fill"])  # a chosen colour is opaque (the defaults may be translucent)
    if "color" in f:
        c = rgba(f["color"])
        s.color = c
        if s.kind in ("points", "scatter", "steps", "line"):
            s.point_color = c
    if f.get("symbol") in SYMBOLS:
        s.symbol = f["symbol"]
    if _num(f.get("size")):
        s.symbol_size = _num(f["size"])
    if f.get("points") is False:
        s.points = []
    if "connect" in f and s.kind == "points":
        s.connect = bool(f["connect"])
    if f.get("border"):  # a bar's or box's outline; a symbol's border
        if s.kind in ("bar", "box", "violin", "floating"):
            s.color = rgba(f["border"])
        else:
            s.symbol_border = rgba(f["border"])
    if _num(f.get("border_width")) is not None:
        s.border_width = max(0.0, _num(f["border_width"]))
    if f.get("pattern") in PATTERNS:
        s.pattern = f["pattern"] or None
    if f.get("pattern_color"):
        s.pattern_color = rgba(f["pattern_color"])
    if f.get("error_color"):
        s.error_color = rgba(f["error_color"])
    if _num(f.get("error_width")):
        s.error_width = _num(f["error_width"])
    if f.get("line_color"):
        s.line_color = rgba(f["line_color"])
    if _num(f.get("line_width")):
        s.line_width = _num(f["line_width"])
    bars = f.get("bars")
    if isinstance(bars, dict) and s.kind == "bar":  # Format This Bar: one bar's own look
        own = {}
        for k, b in bars.items():
            if not str(k).isdigit() or not isinstance(b, dict):
                continue
            d = {}
            for name in ("fill", "border", "pattern_color"):
                if b.get(name):
                    d[name] = rgba(b[name])
            if b.get("pattern") in PATTERNS:
                d["pattern"] = b["pattern"] or None
            if _num(b.get("border_width")) is not None:
                d["border_width"] = max(0.0, _num(b["border_width"]))
            if d:
                own[int(k)] = d
        s.bar_styles = own or None


# Prism's hatch patterns in its own order (refract.render.qt.PATTERNS draws them)
PATTERNS = {"": "None", ".": "Fine dots", "checker": "Checkerboard", "checker_large": "Large checkerboard",
            "-": "Horizontal lines", "|": "Vertical lines", "/": "Diagonal /", "\\": "Diagonal \\", "+": "Grid",
            "x": "Diamond grid", "\\ bold": "Bold diagonal \\", "/ bold": "Bold diagonal /",
            "| bold": "Bold vertical lines", "- bold": "Bold horizontal lines", "+ bold": "Bold grid",
            "x bold": "Bold diamond grid", "bricks_dark": "Dark bricks", "bricks": "Bricks",
            "scatter": "Scattered dots", "texture": "Texture"}
def _shape_names() -> dict[str, str]:
    from .shape_kinds import KINDS

    return {k: v[1] for k, v in KINDS.items()}


SHAPES = _shape_names()


STYLE_KEYS = ("size", "bold", "italic", "underline", "color", "family")


def styled(ts: TextStyle | None, f: dict[str, Any]) -> TextStyle:
    """A copy of ts with a TEXT dict's style keys applied."""
    ts = copy.copy(ts) if ts is not None else TextStyle()
    if _num(f.get("size")):
        ts.size = _num(f["size"])
    for k in ("bold", "italic", "underline"):
        if k in f:
            setattr(ts, k, bool(f[k]))
    if f.get("color"):
        ts.color = rgba(f["color"])
    if f.get("family"):
        ts.family = str(f["family"])
    return ts


def _offset(g: Graph, key: str, f: dict[str, Any]) -> None:
    dx, dy = _num(f.get("dx")) or 0.0, _num(f.get("dy")) or 0.0
    if dx or dy:
        g.offsets[key] = (dx, dy)


def _annotation_bracket(g: Graph, i: int, f: dict[str, Any]) -> None:
    """A bracket or arrow placed in Prism ("abr.<annotation>"), moved (dx, dy),
    its left / right ends stretched ("left", "right": pt), recoloured,
    re-widthed, or hidden."""
    a = g.annotations[i] = dict(g.annotations[i])
    pts = [tuple(q) for q in a["points"]]
    if f.get("hidden"):
        a["points"] = []
        return
    if pts:
        lo, hi = min(q[0] for q in pts), max(q[0] for q in pts)
        dl, dr = _num(f.get("left")) or 0.0, _num(f.get("right")) or 0.0
        dx, dy = _num(f.get("dx")) or 0.0, _num(f.get("dy")) or 0.0
        out = []
        for x, y in pts:
            if hi > lo and abs(x - lo) < 1e-6:
                x += dl
            elif hi > lo and abs(x - hi) < 1e-6:
                x += dr
            out.append((x + dx, y + dy))
        lf, ll_ = _num(f.get("leg_first")) or 0.0, _num(f.get("leg_last")) or 0.0
        if len(out) >= 3:  # its legs: the path's first and last points, lengthened away from the bar
            for idx, d in ((0, lf), (len(out) - 1, ll_)):
                nb = out[1] if idx == 0 else out[-2]
                sign = 1.0 if out[idx][1] >= nb[1] else -1.0
                out[idx] = (out[idx][0], out[idx][1] + sign * d)
        a["points"] = out
    if f.get("color"):
        a["color"] = rgba(f["color"])
    if _num(f.get("width")):
        a["width"] = _num(f["width"])


def _texts(g: Graph, texts: dict[str, Any], notes: list) -> None:
    for key, f in texts.items():
        if not isinstance(f, dict):
            continue
        kind, _, rest = key.partition(".")
        if key == "title":
            if "text" in f:
                g.title = str(f["text"])
            g.title_style = styled(g.title_style, f)
            _offset(g, key, f)
        elif key in ("x.title", "y.title"):
            ax = g.x_axis if kind == "x" else g.y_axis
            if "text" in f:
                ax.title = str(f["text"])
            ax.title_style = styled(ax.title_style, f)
            _offset(g, key, f)
        elif key in ("x.labels", "y.labels"):
            ax = g.x_axis if kind == "x" else g.y_axis
            ax.label_style = styled(ax.label_style, f)
        elif key == "legend":  # every entry (their own styles keep what they set)
            g.legend_style = styled(g.legend_style, f)
            for s in g.series:
                if s.legend_style is not None:
                    s.legend_style = styled(s.legend_style, f)
                elif s.legend_color is not None and f.get("color"):
                    s.legend_color = None
            _offset(g, key, f)
        elif rest.isdigit():
            i = int(rest)
            if kind == "legend" and i < len(g.series):
                s = g.series[i]
                if "text" in f:
                    s.title = str(f["text"])
                if any(k in f for k in STYLE_KEYS):
                    base = s.legend_style or copy.copy(g.legend_style)
                    if s.legend_style is None and s.legend_color is not None:
                        base.color = s.legend_color
                    s.legend_style = styled(base, f)
                _offset(g, key, f)
            elif kind == "sig" and i < len(g.significance):
                b = g.significance[i]
                if "text" in f:
                    b["label"] = str(f["text"])
                if any(k in f for k in STYLE_KEYS):
                    b["style"] = styled(b.get("style") or g.sig_style or g.legend_style, f)
                _offset(g, key, f)
            elif kind == "bracket" and i < len(g.significance):
                b = g.significance[i] = dict(g.significance[i])
                if f.get("color"):
                    b["color"] = rgba(f["color"])
                if _num(f.get("width")):
                    b["width"] = _num(f["width"])
                b["dl"], b["dr"] = _num(f.get("dl")) or 0.0, _num(f.get("dr")) or 0.0  # its ends stretched (pt)
                b["ll"], b["lr"] = _num(f.get("ll")) or 0.0, _num(f.get("lr")) or 0.0  # its legs lengthened (pt)
                if f.get("hidden"):
                    b["hidden"] = True
                _offset(g, key, f)
            elif kind == "abr" and i < len(g.annotations) and g.annotations[i]["kind"] == "bracket":
                _annotation_bracket(g, i, f)
            elif kind == "ann" and i < len(g.annotations) and g.annotations[i]["kind"] == "text":
                a = g.annotations[i] = dict(g.annotations[i])
                if "text" in f:
                    a["text"] = str(f["text"])
                a["style"] = styled(a["style"], f)
                a["cx"] += _num(f.get("dx")) or 0.0
                a["top"] += _num(f.get("dy")) or 0.0
    for n, f in enumerate(notes):
        if isinstance(f, dict) and str(f.get("text", "")).strip():
            g.annotations.append({"kind": "text", "cx": _num(f.get("x")) or 0.0, "top": _num(f.get("y")) or 0.0,
                                  "text": str(f["text"]), "style": styled(TextStyle(), f), "note": n})


def apply(g: Graph, fmt: dict[str, Any] | None) -> Graph:
    """The graph with the overrides applied (in place; returned for chaining)."""
    if not fmt:
        return g
    if "title" in fmt:
        g.title = str(fmt["title"])
    if _num(fmt.get("title_size")):
        g.title_style.size = _num(fmt["title_size"])
    if fmt.get("font"):
        g.font = str(fmt["font"])
    if "legend" in fmt:
        g.legend = bool(fmt["legend"])
    if _num(fmt.get("width")):
        g.x_length = _num(fmt["width"]) * POINTS_PER_INCH
    if _num(fmt.get("height")):
        g.y_length = _num(fmt["height"]) * POINTS_PER_INCH
    numeric_x = g.family in ("xy",)
    _axis(g.x_axis, fmt.get("x") or {}, numeric_x)
    if g.family != "pie":
        _axis(g.y_axis, fmt.get("y") or {}, True)
    for key, f in (fmt.get("sets") or {}).items():
        try:
            i = int(key)
        except ValueError:
            continue
        if 0 <= i < len(g.series):
            _series(g.series[i], f or {})
    for k in ("background", "plot_fill", "axis_color"):
        if fmt.get(k):
            setattr(g, k, rgba(fmt[k]))
    if fmt.get("texts") or fmt.get("notes"):
        g.offsets = dict(g.offsets)
        g.annotations = list(g.annotations)
        g.significance = list(g.significance)
        _texts(g, fmt.get("texts") or {}, fmt.get("notes") or [])
    if fmt.get("shapes"):
        g.shapes = [_shape(sh) for sh in fmt["shapes"] if isinstance(sh, dict) and sh.get("kind") in SHAPES]
    return g


def _shape(f: dict) -> dict:
    out = {"kind": f["kind"], "width": _num(f.get("width")) if _num(f.get("width")) is not None else 1.0,
           "color": rgba(f["color"]) if f.get("color") else (0, 0, 0, 255), "dash": bool(f.get("dash"))}
    for k in ("x1", "y1", "x2", "y2"):
        out[k] = _num(f.get(k)) or 0.0
    if f.get("fill"):
        out["fill"] = rgba(f["fill"])
    if str(f.get("label") or ""):  # lines with text
        out["label"] = str(f["label"])
        if _num(f.get("label_size")):
            out["label_size"] = _num(f["label_size"])
        if f.get("label_color"):
            out["label_color"] = rgba(f["label_color"])
    return out


# ------------------------------------------------------- drawn objects (canvas)
def add_shape(fmt: dict | None, kind: str, x1: float, y1: float, x2: float, y2: float) -> tuple[dict, str]:
    """fmt with a new drawn object (points from the plot's top-left), and its id."""
    out = copy.deepcopy(fmt or {})
    shapes = out.setdefault("shapes", [])
    shapes.append({"kind": kind, "x1": round(x1, 2), "y1": round(y1, 2), "x2": round(x2, 2), "y2": round(y2, 2),
                   "color": "#000000", "width": 1.0})
    return out, f"shape.{len(shapes) - 1}"


def with_shape(fmt: dict | None, key: str, values: dict[str, Any]) -> dict:
    """fmt with drawn object `key` changed: "move" (dx, dy) moves it, "end"
    (k, dx, dy) moves one end (1 or 2: a corner of a box), other keys are
    SHAPE keys (None removes one)."""
    out = copy.deepcopy(fmt or {})
    n = int(key.partition(".")[2])
    shapes = out.get("shapes") or []
    if n >= len(shapes) or not shapes[n]:
        return out
    sh = shapes[n]
    values = dict(values)
    move, end = values.pop("move", None), values.pop("end", None)
    if move:
        for a, d in (("x1", move[0]), ("x2", move[0]), ("y1", move[1]), ("y2", move[1])):
            sh[a] = round((_num(sh.get(a)) or 0.0) + d, 2)
    if end:
        k, dx, dy = end
        if k in (3, 4):  # a bracket's leg tip: that leg longer or shorter
            from .shape_kinds import leg_change, legs

            cur = legs({**sh, "x1": _num(sh.get("x1")) or 0.0, "x2": _num(sh.get("x2")) or 0.0,
                        "y1": _num(sh.get("y1")) or 0.0, "y2": _num(sh.get("y2")) or 0.0})[k - 3]
            sh[f"leg{k - 2}"] = round(max(0.0, cur + leg_change(sh, dx, dy)), 2)
        else:
            sh[f"x{k}"] = round((_num(sh.get(f"x{k}")) or 0.0) + dx, 2)
            sh[f"y{k}"] = round((_num(sh.get(f"y{k}")) or 0.0) + dy, 2)
    for k, v in values.items():
        if v is None:
            sh.pop(k, None)
        else:
            sh[k] = v
    return out


def remove_shape(fmt: dict | None, key: str) -> dict:
    """fmt without drawn object `key` (the others keep their ids)."""
    out = copy.deepcopy(fmt or {})
    n = int(key.partition(".")[2])
    shapes = out.get("shapes") or []
    if n < len(shapes):
        shapes[n] = {}
    if not any(shapes):
        out.pop("shapes", None)
    return out


def with_object(fmt: dict | None, key: str, values: dict[str, Any]) -> dict:
    """fmt with graph object `key` changed: a data set's SET keys, a
    bracket's ("move", "color", "width"), a drawn object's (with_shape), or a
    text's (with_text)."""
    kind, _, rest = key.partition(".")
    if kind == "set" and rest.isdigit():
        values = dict(values)
        bar = values.pop("bar", None)  # Format This Bar: {"bar": k, ...}
        if bar is not None:
            return merged(fmt, ["sets", rest, "bars", str(int(bar))], values)
        return merged(fmt, ["sets", rest], values)
    if kind == "shape" and rest.isdigit():
        return with_shape(fmt, key, values)
    if kind in ("bracket", "abr") and "end" in values:  # an end dragged: stretch that side
        values = dict(values)
        k, dx, dy = values.pop("end")
        out = copy.deepcopy(fmt or {})
        t = out.setdefault("texts", {}).setdefault(key, {})
        if k in (3, 4):  # a leg's tip: the leg longer or shorter (dy)
            name, d = (("ll" if k == 3 else "lr") if kind == "bracket" else ("leg_first" if k == 3 else "leg_last")), dy
        else:  # an end: the bracket wider or narrower (dx)
            name, d = ("dl" if k == 1 else "dr") if kind == "bracket" else ("left" if k == 1 else "right"), dx
        t[name] = round((_num(t.get(name)) or 0.0) + d, 2)
        return with_text(out, key, values) if values else _prune(out)
    return with_text(fmt, key, values)


def merged(fmt: dict | None, path: list[str], values: dict[str, Any]) -> dict:
    """A copy of fmt with `values` merged at `path` (e.g. ["sets", "0"]);
    a value of None removes that key (back to the default)."""
    out = copy.deepcopy(fmt or {})
    d = out
    for k in path:
        d = d.setdefault(k, {})
    for k, v in values.items():
        if v is None:
            d.pop(k, None)
        else:
            d[k] = v
    return _prune(out)


def _prune(d: dict) -> dict:
    for k in list(d):
        if isinstance(d[k], dict):
            _prune(d[k])
            if not d[k]:
                del d[k]
    return d


# ------------------------------------------------------- text objects (canvas)
def text_style(g: Graph, key: str) -> TextStyle | None:
    """The style in effect for text object `key` of the built graph."""
    kind, _, rest = key.partition(".")
    if key == "title":
        return g.title_style
    if key == "legend":
        return g.legend_style
    if key in ("x.title", "y.title"):
        return (g.x_axis if kind == "x" else g.y_axis).title_style
    if key in ("x.labels", "y.labels"):
        return (g.x_axis if kind == "x" else g.y_axis).label_style
    if not rest.isdigit():
        return None
    i = int(rest)
    if kind == "legend" and i < len(g.series):
        return g.series[i].legend_style or g.legend_style
    if kind == "sig" and i < len(g.significance):
        return g.significance[i].get("style") or g.sig_style or g.legend_style
    if kind in ("ann", "note"):
        for k, a in enumerate(g.annotations):
            if a["kind"] == "text" and (a.get("note") == i if kind == "note" else k == i and "note" not in a):
                return a["style"]
    return None


DEFAULT_SIZES = {"title": 14.0, "x.title": 12.0, "y.title": 12.0, "x.labels": 11.0, "y.labels": 11.0}
DEFAULT_BOLD = {"title", "x.title", "y.title", "x.labels", "y.labels"}


def text_defaults(key: str) -> tuple[float, bool]:
    """(size, bold) Prism's default style gives a text object."""
    return DEFAULT_SIZES.get(key, 12.0), key in DEFAULT_BOLD


def with_text(fmt: dict | None, key: str, values: dict[str, Any]) -> dict:
    """A copy of fmt with text object `key` changed: "text", "move" (dx, dy
    added to where it is), style keys (None removes one). The graph title's
    and axis titles' text and size go to their usual keys."""
    out = copy.deepcopy(fmt or {})
    values = dict(values)
    move = values.pop("move", None)
    kind, _, rest = key.partition(".")
    if kind == "note" and rest.isdigit():
        notes = out.setdefault("notes", [])
        n = int(rest)
        if n < len(notes):
            note = notes[n]
            if move:
                note["x"] = (_num(note.get("x")) or 0.0) + move[0]
                note["y"] = (_num(note.get("y")) or 0.0) + move[1]
            for k, v in values.items():
                if v is None:
                    note.pop(k, None)
                else:
                    note[k] = v
        return _prune(out)
    if key == "title" or key in ("x.title", "y.title", "x.labels", "y.labels"):
        target = out if key == "title" else out.setdefault(kind, {})
        if "text" in values and key != "x.labels" and key != "y.labels":
            target["title"] = values.pop("text")
        if "size" in values:
            v = values.pop("size")
            name = "label_size" if key.endswith("labels") else "title_size"
            if v is None:
                target.pop(name, None)
            else:
                target[name] = v
    t = out.setdefault("texts", {}).setdefault(key, {})
    if move:
        t["dx"] = round((_num(t.get("dx")) or 0.0) + move[0], 2)
        t["dy"] = round((_num(t.get("dy")) or 0.0) + move[1], 2)
    for k, v in values.items():
        if v is None:
            t.pop(k, None)
        else:
            t[k] = v
    return _prune(out)


def add_note(fmt: dict | None, x: float, y: float, text: str = "Text") -> tuple[dict, str]:
    """fmt with a new text box (centre x, top y from the plot's top-left), and its id."""
    out = copy.deepcopy(fmt or {})
    notes = out.setdefault("notes", [])
    notes.append({"text": text, "x": round(x, 2), "y": round(y, 2)})
    return out, f"note.{len(notes) - 1}"


def remove_text(fmt: dict | None, key: str) -> dict:
    """fmt without text object `key`: a text box is deleted, other texts are
    emptied (titles hidden, labels blank)."""
    kind, _, rest = key.partition(".")
    if kind == "note" and rest.isdigit():
        out = copy.deepcopy(fmt or {})
        notes = out.get("notes") or []
        if int(rest) < len(notes):
            notes[int(rest)] = {}  # keeps the other boxes' ids
        return _prune(out) if any(notes) else _prune({k: v for k, v in out.items() if k != "notes"})
    if key.endswith("labels"):
        return copy.deepcopy(fmt or {})
    return with_text(fmt, key, {"text": ""})
