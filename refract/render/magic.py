"""Magic (Graph ▸ Magic, docs/ui-spec.md §3.4): make a graph look like
another one, or like a saved style template, by copying chosen parts of the
example's formatting into the graph's Format Graph overrides
(refract.render.formatting).

style_of() reads the formatting in effect on a built graph (whatever its
origin: a Prism file, Refract's defaults or overrides) as a format dict;
match() merges the chosen parts of such a dict into another graph's."""

from __future__ import annotations

import copy

from .formatting import SYMBOLS, hex_color
from .model import Graph, TextStyle
from .qt import DRAWN, Layout

# what Magic can copy, with the format keys each part covers
PARTS = {
    "colors": "Colors, fills and symbols of the data sets",
    "text": "Fonts, text sizes and text styles",
    "lengths": "Axis lengths (the graph's size)",
    "ranges": "Axis ranges, ticks and scales",
    "titles": "Titles and axis titles (their words)",
    "legend": "Legend shown or hidden",
    "background": "Background, plot area and axis colors",
}
DEFAULT_PARTS = ("colors", "text", "lengths", "legend", "background")


def _style(ts: TextStyle, size: float, bold: bool) -> dict:
    return {"size": ts.size or size, "bold": bold if ts.bold is None else ts.bold, "italic": ts.italic,
            "underline": ts.underline, "color": hex_color(ts.color), **({"family": ts.family} if ts.family else {})}


def style_of(g: Graph, lay: Layout) -> dict:
    """The formatting in effect on graph g (laid out as lay), as a format dict."""
    left, top, right, bottom = lay.plot
    fmt: dict = {"font": g.font, "legend": g.legend,
                 "width": round((right - left) / DRAWN / 72, 4), "height": round((bottom - top) / DRAWN / 72, 4),
                 "title": g.title, "x": {"title": g.x_axis.title}, "y": {"title": g.y_axis.title}, "sets": {},
                 "texts": {"title": _style(g.title_style, 14.0, True),
                           "x.title": _style(g.x_axis.title_style, 12.0, True),
                           "y.title": _style(g.y_axis.title_style, 12.0, True),
                           "x.labels": _style(g.x_axis.label_style, 11.0, True),
                           "y.labels": _style(g.y_axis.label_style, 11.0, True)}}
    for k, ax in (("x", g.x_axis), ("y", g.y_axis)):
        rng = {"min": lay.x.lo if k == "x" else lay.y.lo, "max": lay.x.hi if k == "x" else lay.y.hi,
               "tick": lay.x.tick if k == "x" else lay.y.tick, "log": ax.log}
        fmt[k].update({"range": rng})
        if ax.label_angle is not None:
            fmt[k]["angle"] = ax.label_angle
    for i, s in enumerate(g.series):
        f = {"fill": hex_color(s.fill), "color": hex_color(s.point_color or s.color), "size": s.symbol_size}
        if s.symbol in SYMBOLS:
            f["symbol"] = s.symbol
        f["_bar"] = s.kind == "bar"
        fmt["sets"][str(i)] = f
    for k in ("background", "plot_fill", "axis_color"):
        v = getattr(g, k)
        if v is not None:
            fmt[k] = hex_color(v)
    return fmt


def match(target_fmt: dict | None, target: Graph, example: dict, parts) -> dict:
    """target_fmt with the chosen `parts` of example (a style_of dict or a
    saved template) merged in; data sets beyond the example's take its
    colours in turn."""
    out = copy.deepcopy(target_fmt or {})
    parts = set(parts)
    if "colors" in parts and example.get("sets"):
        ex = [example["sets"][k] for k in sorted(example["sets"], key=int)]
        sets = out.setdefault("sets", {})
        for i, s in enumerate(target.series):
            e = ex[i % len(ex)]
            f = sets.setdefault(str(i), {})
            if s.kind == "bar":
                f["fill"] = e["fill"] if e.get("_bar", True) else e["color"]
                if e.get("_bar"):
                    f["color"] = e["color"]
            else:
                f["color"] = e["color"] if not e.get("_bar") else e["fill"]
                f["fill"] = f["color"]
                if "symbol" in e:
                    f["symbol"] = e["symbol"]
                if e.get("size"):
                    f["size"] = e["size"]
    if "text" in parts:
        if example.get("font"):
            out["font"] = example["font"]
        texts = out.setdefault("texts", {})
        for key, st in (example.get("texts") or {}).items():
            t = texts.setdefault(key, {})
            for k, v in st.items():
                if k == "size":
                    continue  # sizes go to their own keys below
                t[k] = v
        sizes = example.get("texts") or {}
        if "title" in sizes:
            out["title_size"] = sizes["title"]["size"]
        for ax in ("x", "y"):
            a = out.setdefault(ax, {})
            if f"{ax}.title" in sizes:
                a["title_size"] = sizes[f"{ax}.title"]["size"]
            if f"{ax}.labels" in sizes:
                a["label_size"] = sizes[f"{ax}.labels"]["size"]
    if "lengths" in parts:
        for k in ("width", "height"):
            if example.get(k):
                out[k] = example[k]
    if "ranges" in parts:
        for ax in ("x", "y"):
            rng = (example.get(ax) or {}).get("range")
            if not rng or (ax == "x" and target.family in ("column", "grouped")):
                continue
            a = out.setdefault(ax, {})
            a.update({k: rng[k] for k in ("min", "max", "tick", "log") if rng.get(k) is not None})
    if "titles" in parts:
        if "title" in example:
            out["title"] = example["title"]
        for ax in ("x", "y"):
            if "title" in (example.get(ax) or {}):
                out.setdefault(ax, {})["title"] = example[ax]["title"]
    if "legend" in parts and "legend" in example:
        out["legend"] = bool(example["legend"])
    if "background" in parts:
        for k in ("background", "plot_fill", "axis_color"):
            if example.get(k):
                out[k] = example[k]
            else:
                out.pop(k, None)
    return _clean(out)


def template(example: dict) -> dict:
    """A saved style template: the example's style without its words and
    ranges (they belong to its data)."""
    out = copy.deepcopy(example)
    out.pop("title", None)
    for ax in ("x", "y"):
        (out.get(ax) or {}).pop("title", None)
        (out.get(ax) or {}).pop("range", None)
    return out


def _clean(d: dict) -> dict:
    for k in list(d):
        if isinstance(d[k], dict):
            _clean(d[k])
            if not d[k]:
                del d[k]
    return d
