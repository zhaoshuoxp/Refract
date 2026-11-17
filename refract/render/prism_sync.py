"""Keeping a Refract graph and its Prism graph one graph (PLAN §2.4).

Refract writes each of its graphs as a Prism graph (refract.ui.document).
To keep the two the same graph when the file goes back and forth, Refract
records, when it saves, a summary of the Prism graph as written: what
refract.render.from_prism reads of it (plot styles and choices, titles,
colours, symbols, axis ranges and lengths, fonts, the legend). When the
file is opened again:

  * the Prism graph is gone (deleted in Prism): the Refract graph goes too;
  * its summary is unchanged (Prism only opened and saved it): the Refract
    graph stays as it is;
  * it changed (edited in Prism): the changes are taken into the Refract
    graph - its type when Prism's plot styles name one of Refract's types,
    and the formatting that changed - and the Prism graph is kept as Prism
    left it until the graph is changed in Refract.
"""

from __future__ import annotations

import copy
import math

ROUND = 3  # digits kept of ranges (Prism re-saves floats as it reads them)


def _clean(v):
    if isinstance(v, float):
        return None if not math.isfinite(v) else round(v, ROUND)
    if isinstance(v, dict):
        return {k: _clean(x) for k, x in v.items() if not str(k).startswith("_")}
    if isinstance(v, list | tuple):
        return [_clean(x) for x in v]
    return v


def _explicit_title(chunks, tid) -> str | None:
    """A title's text when it is the user's (not one Prism derives: 0x802B +8 bit 0x4000)."""
    import struct

    from ..formats.pcff import texts as TX

    if tid is None:
        return None
    i = TX.index(chunks, tid)
    if i is None:
        return None
    flags = struct.unpack_from("<H", chunks[i].payload, 8)[0]
    if flags & TX.AUTO:
        return None
    return chunks[i + 1].payload.decode("cp1252", "replace").replace("\r", "\n")


def summary(project, index: int, archive=None) -> dict | None:
    """The settings of Prism graph `index` that a user sets and Prism keeps as
    set when it re-saves (E-compare: Prism re-derives automatic titles,
    ranges, lengths and symbol sizes, and the legend, so those are left
    out): the plots' styles and choices, their colours and symbol shapes,
    titles that are not automatic, manual axis ranges, the horizontal flag.
    None if the graph cannot be read."""

    from ..formats.pcff import fields as F
    from ..formats.pcff import texts as TX
    from ..formats.pcff import walker
    from . import from_prism

    gs = project.graphs[index]
    if not gs.blob:
        return None
    try:
        ch = walker.parse(gs.blob)
        plots = from_prism.plot_settings(ch)
        colors = from_prism.plot_colors(from_prism._store(ch))
    except Exception:  # noqa: BLE001 - a graph Refract cannot read is left alone
        return None
    head = next((c.payload for c in ch if c.tag == F.TAG_GRAPH_KIND and c.payload and len(c.payload) >= 34), None)
    out_plots = []
    for k, p in enumerate(plots):
        d = {"style": p["style"], "plot": p["plot"], "connect": p["connect"], "area": p.get("area"), "bar": p["bar"],
             "shape": p["shape"], "color": [[r, list(v)] for r, v in sorted((colors[k] if k < len(colors) else {}).items())]}
        if p["style"] in (from_prism.BOX_STYLE, from_prism.VIOLIN):
            d["whiskers"] = p["whiskers"]  # its values are shown through the whisker mode
        else:
            d["points"] = p["points"]
        out_plots.append(d)
    ranges = {}
    modes = [F.AxisMode.read(c) for c in F.axis_modes(ch)]
    sets = [F.AxisSettings.read(c) for c in F.axis_settings(ch)]
    for i, name in ((0, "x"), (1, "y")):
        if i < len(modes) and 3 * i < len(sets) and modes[i].flags & F.AxisMode.MANUAL_RANGE:
            s = sets[3 * i]
            ranges[name] = [s.min, s.max, s.major_tick]
    titles = {"title": _explicit_title(ch, TX.graph_title_id(ch)),
              "x": _explicit_title(ch, TX.axis_title_id(ch, 0)), "y": _explicit_title(ch, TX.axis_title_id(ch, 1))}
    return _clean({"horizontal": bool(head is not None and len(head) > 29 and head[29] & from_prism.HORIZONTAL),
                   "plots": out_plots, "ranges": ranges, "titles": titles})


def apply(ng, base: dict, now: dict) -> list[str]:
    """Take into Refract graph `ng` what changed in its Prism graph between
    the summaries `base` (as Refract saved it) and `now`; returns what was
    taken, in words."""
    from . import graph_types as GT
    from .formatting import hex_color

    took: list[str] = []
    fmt = copy.deepcopy(ng.format or {})
    horizontal = bool(now.get("horizontal"))
    if base.get("plots") != now.get("plots") or base.get("horizontal") != horizontal:
        styles = [{k: v for k, v in p.items() if k != "color"} for p in now.get("plots", [])]
        old = [{k: v for k, v in p.items() if k != "color"} for p in base.get("plots", [])]
        if styles != old or base.get("horizontal") != horizontal:
            found = GT.from_prism_plots(ng.table.kind, styles, horizontal)
            if found is not None:
                key, plot = found
                if key != ng.style or (plot and plot != ng.error):
                    ng.style = key
                    if plot:
                        ng.error = plot
                    took.append(f"graph type ({GT.BY_KEY[key].label})")
            else:
                took.append("plot styles (not a Refract graph type: Refract keeps its own)")
    count = len(now.get("plots", []))
    for i, (b, n) in enumerate(zip(base.get("plots", []), now.get("plots", []), strict=False)):
        if b.get("color") == n.get("color") or not n.get("color"):
            continue
        c = {k: tuple(v) for k, v in _color_keys(n["color"])}
        j = count - 1 - i if ng.table.kind in ("xy", "survival") else i  # XY plots: stored last data set first
        f = fmt.setdefault("sets", {}).setdefault(str(j), {})
        if "fill" in c:
            f["fill"] = hex_color(c["fill"])
        line = c.get("bar_border") if n.get("bar") or n.get("style") in (1, 5) else c.get("symbol")
        if line is not None:
            f["color"] = hex_color(line)
        if "data-set colours" not in took:
            took.append("data-set colours")
    names = {"x": "y", "y": "x"} if horizontal else {"x": "x", "y": "y"}  # stored X: the values when on its side
    for ax, rng in (now.get("ranges") or {}).items():
        if (base.get("ranges") or {}).get(ax) != rng and rng:
            a = fmt.setdefault(names[ax], {})
            a["min"], a["max"], a["tick"] = rng[0], rng[1], rng[2]
            took.append(f"{names[ax].upper()} axis range")
    for ax in set(base.get("ranges") or {}) - set(now.get("ranges") or {}):  # made automatic again
        for k in ("min", "max", "tick"):
            (fmt.get(names[ax]) or {}).pop(k, None)
        took.append(f"{names[ax].upper()} axis range (automatic)")
    bt, nt = base.get("titles") or {}, now.get("titles") or {}
    for key in ("title", "x", "y"):
        if bt.get(key) != nt.get(key) and nt.get(key) is not None:
            if key == "title":
                fmt["title"] = nt[key]
            else:
                fmt.setdefault(names[key], {})["title"] = nt[key]
            took.append({"title": "title", "x": "X title", "y": "Y title"}[key] if not horizontal or key == "title"
                        else f"{names[key].upper()} title")
    ng.format = {k: v for k, v in fmt.items() if v != {}}
    return took


def _color_keys(pairs):
    """The colour entries of a summary (sorted (role, rgba) pairs)."""
    return [(k, v) for k, v in pairs] if pairs and isinstance(pairs[0], list | tuple) and len(pairs[0]) == 2 \
        and isinstance(pairs[0][0], str) else []
