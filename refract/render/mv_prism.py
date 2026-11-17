"""Prism's graphs of a Multiple-variables table (E-mv).

Prism stores these not as a PCFF blob but as JSON in the graph sheet
(graphs/<uid>/sheet.json, "graph": {"@class": "MVGraph", ...}):

  * xVariables / yVariables: the data-set uids of the X and Y variables;
    dataSheet: the table's sheet uid;
  * gdoTypes.defaults: the figures ("symbols": bubbles, "lines": lines
    through the points); gdoSettings.<figure>: its colour variable and
    colormap (SingleColormap: one colour; CategoricalColormap: one colour per
    category from a Prism colour scheme; GradientColormap: a named gradient
    over a numeric variable, with colorsTransparencyPercent) and its size
    variable and evaluator (SymbolSizeEvaluator: one size; CategoricalSize-
    Evaluator: a size per category; ContinuousSizeEvaluator: a size range);
  * axisX / axisY: titles and segments (lowerLimit, upperLimit, interval).

read() draws one as Refract's bubble graph of the table.
"""

from __future__ import annotations

import json

from .model import Axis, Graph, Series

GRADIENTS = {"Viridis": "viridis", "Magma": "magma", "Inferno": "inferno", "Plasma": "plasma", "Grays": "grays",
             "Blues": "blues", "Rainbow": "rainbow"}
CATEGORY_FILLS = [(0, 0, 0, 255), (160, 160, 164, 255), (93, 126, 169, 255), (233, 164, 154, 255),
                  (164, 197, 182, 255), (240, 198, 170, 255)]


def sheet_graph(archive, uid: str | None) -> dict | None:
    """The MVGraph JSON of graph sheet `uid`, or None."""
    if archive is None or not uid or not archive.has(f"graphs/{uid}/sheet.json"):
        return None
    try:
        g = json.loads(archive.read(f"graphs/{uid}/sheet.json")).get("graph")
    except ValueError:
        return None
    return g if isinstance(g, dict) and g.get("@class") == "MVGraph" else None


def _text(o) -> str:
    return ((o or {}).get("text") or {}).get("string", "") if isinstance(o, dict) else ""


def _limits(axis: dict) -> tuple[float | None, float | None, float | None]:
    seg = ((axis or {}).get("segments") or [{}])[0]
    vals = [seg.get(k) for k in ("lowerLimit", "upperLimit", "interval")]
    return tuple(v if isinstance(v, int | float) else None for v in vals)  # type: ignore[return-value]


def read(project, mv: dict, title: str) -> Graph:
    t = next((t for t in project.tables if t.sheet_uid == mv.get("dataSheet")), None)
    if t is None:
        raise NotImplementedError("the graph's Multiple-variables table is not in the file")
    return read_table(t, mv, title)


def read_table(t, mv: dict, title: str) -> Graph:
    """The MV graph `mv` of table t; its variables named by data-set uid (or
    by index: Refract's own bubble graphs, refract.render.graph_types)."""
    from .qt import colormap

    uids = {ds.uid: j for j, ds in enumerate(t.datasets) if ds.uid}

    def index(k) -> int | None:  # a variable: its data set's uid, or its index
        return k if isinstance(k, int) and 0 <= k < len(t.datasets) else uids.get(k)

    xi = index((mv.get("xVariables") or [None])[0])
    yi = index((mv.get("yVariables") or [None])[0])
    if xi is None or yi is None:
        raise NotImplementedError("the graph's X or Y variable is not in its table")
    figures = (mv.get("gdoTypes") or {}).get("defaults") or ["symbols"]
    settings = (mv.get("gdoSettings") or {}).get("symbols") or (mv.get("gdoSettings") or {}).get("lines") or {}
    ci, si = index(settings.get("colorVariable")), index(settings.get("sizeVariable"))
    cmap, sizes = settings.get("colormap") or {}, settings.get("sizeEvaluator") or {}
    xs, ys = t.values(xi, 0), t.values(yi, 0)
    n = min(len(xs), len(ys))
    text = (lambda j: [c.strip() for c in (t.datasets[j].subcolumns[0] if t.datasets[j].subcolumns else [])])
    g = Graph(title=title, family="xy")
    g.x_axis = Axis(title=_text(mv.get("axisX", {}).get("title")) or (t.datasets[xi].title or ""))
    g.y_axis = Axis(title=_text(mv.get("axisY", {}).get("title")) or (t.datasets[yi].title or ""))
    for ax, key in ((g.x_axis, "axisX"), (g.y_axis, "axisY")):
        ax.min, ax.max, ax.tick = _limits(mv.get(key))
    g.title = _text(mv.get("title")) or title
    # the size of each point
    base = float(sizes.get("symbolSize") or 6.0)
    size_of = [base] * n
    size_legend = None
    if si is not None and sizes.get("@class") == "CategoricalSizeEvaluator":
        cats = text(si)
        table = {str(k).lower(): float(v) for k, v in (sizes.get("sizesDictionary") or {}).items()}
        size_of = [table.get(cats[r].lower(), base) if r < len(cats) else base for r in range(n)]
    elif si is not None and sizes.get("@class") == "ContinuousSizeEvaluator":
        sv = t.values(si, 0)
        ok = [v for v in sv[:n] if v is not None]
        lo = sizes.get("customMinimalValue")
        lo = float(lo) if isinstance(lo, int | float) and lo > 0 else min(ok, default=1.0)
        big = float(sizes.get("largestSymbolSize") or base * 3)
        # the area in proportion to the value from the smallest one (E-mv: 10, 20, 30 -> 3.9, 5.5, 7 pt)
        size_of = [min(big, base * (sv[r] / lo) ** 0.5) if r < len(sv) and sv[r] is not None and lo > 0
                   and sv[r] > 0 else base for r in range(n)]
        hi = max(ok, default=lo)
        if settings.get("isSizeLegendEnabled", True) and hi > lo > 0:
            # Prism's sizes legend: the smallest, the geometric middle and the largest value, two decimals
            # (E-mv: 1.80, 3.26, 5.90 at 6, 8.07, 10.86 pt)
            vals = (lo, (lo * hi) ** 0.5, hi)
            size_legend = {"title": t.datasets[si].title or "",
                           "entries": [(f"{v:.2f}", min(big, base * (v / lo) ** 0.5)) for v in vals]}
    # the colour of each point, and the legend's groups
    alpha = round(255 * (1 - float(cmap.get("colorsTransparencyPercent") or 0) / 100))
    groups: dict[str, list[int]] = {}
    colour: dict[str, tuple[int, int, int, int]] = {}
    if ci is not None and cmap.get("@class") == "GradientColormap":
        cv = t.values(ci, 0)
        ok = [v for v in cv[:n] if v is not None]
        lo, hi = (min(ok), max(ok)) if ok else (0.0, 1.0)
        name = GRADIENTS.get(cmap.get("colorScheme", ""), "viridis")
        for r in range(n):
            f = (cv[r] - lo) / (hi - lo) if r < len(cv) and cv[r] is not None and hi > lo else 0.0
            key = f"\x00{r}"
            groups[key] = [r]
            c = colormap(name, f)
            colour[key] = (*c[:3], alpha)
        g.color_bar = {"cmap": name, "lo": lo, "hi": hi, "alpha": alpha, "title": t.datasets[ci].title or ""}
        g.legend = si is not None and sizes.get("@class") == "CategoricalSizeEvaluator"
    elif ci is not None and cmap.get("@class") == "CategoricalColormap":
        cats = text(ci)
        for r in range(n):
            groups.setdefault(cats[r] if r < len(cats) else "", []).append(r)
        named = {str(k).lower(): v for k, v in (cmap.get("colorsDictionary") or {}).items()}
        listed = cmap.get("colorSchemeColors") or []
        for k, key in enumerate(groups):
            h = named.get(key.lower()) or (listed[k % len(listed)] if listed else None)
            if isinstance(h, str) and len(h.lstrip("#")) >= 6:  # the colours written out (Prism's or Refract's)
                v = h.lstrip("#")
                colour[key] = (int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16), alpha)
            else:
                colour[key] = (*CATEGORY_FILLS[k % len(CATEGORY_FILLS)][:3], alpha)
        g.legend = False  # Prism's: titled, first, the sizes after it (E-mv)
        g.category_legend = {"title": t.datasets[ci].title or "", "entries": [
            (key, colour[key], max(size_of, default=base)) for key in groups]}
    else:
        groups[t.datasets[yi].title or ""] = list(range(n))
        single = str(cmap.get("color") or "#000000ff").lstrip("#")
        rgba = tuple(int(single[k:k + 2], 16) for k in (0, 2, 4, 6)) if len(single) >= 8 else (0, 0, 0, 255)
        colour[next(iter(groups))] = rgba  # type: ignore[assignment]
        g.legend = False
    g.size_legend = size_legend
    if mv.get("width") and mv.get("height"):  # the plot's size in points
        g.x_length, g.y_length = float(mv["width"]), float(mv["height"])
    lines = "lines" in figures
    for key, rows in groups.items():
        rows = [r for r in rows if xs[r] is not None and ys[r] is not None]
        if lines:
            rows.sort(key=lambda r: xs[r])
        s = Series("" if key.startswith("\x00") else key, "points", [xs[r] for r in rows], [ys[r] for r in rows],
                   symbol="circle", symbol_size=base, connect=lines, in_legend=not key.startswith("\x00"))
        s.fill = s.color = s.point_color = colour[key]
        s.sizes = [size_of[r] for r in rows]
        if "symbols" not in figures:
            s.symbol = "none"
        g.series.append(s)
    if si is not None and sizes.get("@class") == "CategoricalSizeEvaluator":  # the sizes' legend: one per category
        seen: list[str] = []
        for c in text(si):
            if c and c not in seen:
                seen.append(c)
                s = Series(c, "points", [], [], symbol="circle", symbol_size=size_of[text(si).index(c)])
                s.fill = s.color = s.point_color = (0, 0, 0, 255)
                g.series.append(s)
        g.legend = True
    return g
