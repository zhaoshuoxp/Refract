"""Refract's bubble and scatter graphs of a Multiple-variables table written
as Prism graphs (E-mv).

Prism keeps such a graph as JSON in its graph sheet ("graph": {"@class":
"MVGraph"}, refract.render.mv_prism) and builds what it leaves out itself
(legends, data limits, title placement: E-mv, a sheet with only the keys
below drew as Prism's own). Refract writes: the plot's place and size, the
title, the axes (titles, range and interval), the X and Y variables, and
one symbols figure with its colour (one colour, or a colour per category
written out) and size (one size, or sizes over a numeric variable).
"""

from __future__ import annotations

from . import bundle as B
from .bundle_builder import new_uid
from .zipio import ZipArchive

PLACE = (198.0, 324.0)  # where Prism puts a new graph's plot on the page (its own new MV graph)


def _hex(rgba) -> str:
    r, g, b, a = (list(rgba) + [255])[:4]
    return f"#{r:02x}{g:02x}{b:02x}{a:02x}"


def _text(s: str, size: float | None = None) -> dict:
    """A text with Prism's default formatting (bold, centred; the title 14 pt)."""
    attrs = {"textColor": "#000000ff", "fontWeight": "bold", "horizontalAlignment": "center"}
    if size:
        attrs["fontSize"] = size
    return {"text": {"string": s, "version": 1,
                     "formatting": [{"range": f"0~{max(len(s) - 1, 0)}", "attributes": attrs}]},
            "isVisible": True, "isDefault": False}


def _axis(title: str, lo: float, hi: float, tick: float, vertical: bool) -> dict:
    t = _text(title)
    t.update({"rotationAngle": 90.0, "dockPosition": "left", "dockAlignment": "middle", "moveDirection": "any"}
             if vertical else {"dockPosition": "below", "dockAlignment": "middle", "moveDirection": "verticalOnly"})
    return {"@class": "Axis", "title": t, "orientation": "vertical" if vertical else "horizontal",
            "strokeThickness": 1.0, "strokeColor": "#000000ff", "strokeStyle": "solid",
            "segments": [{"@class": "LinearAxisSegment",
                          "ticksOptions": {"direction": "outside", "length": "normal", "thickness": 1.0, "angle": 0.0,
                                           "color": "#000000ff"},
                          "relativeLength": 1.0, "ticksVisibility": "all",
                          "labelsSettings": {"isVisible": True, "alignment": "auto",
                                             "font": {"family": "Arial", "size": 11.0, "weight": "bold"},
                                             "textColor": "#000000ff", "numbersFormat": "decimal"},
                          "lowerLimit": float(lo), "upperLimit": float(hi), "interval": float(tick),
                          "startTicksValue": float(lo), "minorTicksCount": 0}]}


GRADIENT = ("Viridis", 50)  # a numeric colour variable: Prism's own default bubble graph's gradient, 50 % clear


def figure(t, color: int | None, size: int | None, colors: dict[str, tuple], single,
           size_range: tuple[float, float], numeric_color: bool = False, ref=None) -> dict:
    """The symbols figure (BubblesFigure::Settings) of table t: coloured by
    `color` (a gradient when it is numeric, else colors: category -> RGBA),
    or the one colour `single`; sized by `size` over size_range. ref: data
    set index -> how a variable is named (its uid; refract.render.graph_types
    passes the index itself)."""
    ds = t.datasets
    ref = ref or (lambda j: ds[j].uid)
    figure: dict = {"@class": "BubblesFigure::Settings", "uid": new_uid(), "isColorLegendEnabled": color is not None,
                    "isSizeLegendEnabled": size is not None, "isSizeLegendSeparate": False}
    if color is not None and numeric_color:
        figure["colorVariable"] = ref(color)
        figure["colormap"] = {"@class": "GradientColormap", "outlierColor": "#00000080", "colorArrayType": "gradient",
                              "colorScheme": GRADIENT[0], "colorsTransparencyPercent": GRADIENT[1], "customValues": {}}
    elif color is not None and colors:
        hexes = [_hex(c) for c in colors.values()]
        figure["colorVariable"] = ref(color)
        figure["colormap"] = {"@class": "CategoricalColormap", "colorArrayType": "dataFill",
                              "colorSchemeColors": hexes, "colorsTransparencyPercent": 0,
                              "colorsDictionary": {k.lower(): _hex(c) for k, c in colors.items()},
                              "colors": {str(i): h for i, h in enumerate(hexes)}}
    else:
        figure["colorVariable"] = None
        figure["colormap"] = {"@class": "SingleColormap", "color": _hex(single)}
    if size is not None:
        vals = [v for v in t.values(size, 0) if v is not None]
        figure["sizeVariable"] = ref(size)
        figure["sizeEvaluator"] = {"@class": "ContinuousSizeEvaluator", "symbolSize": size_range[0],
                                   "customMinimalValue": float(min(vals, default=0.0)), "skipBelowMinimalSize": True,
                                   "customMaximalValue": "auto", "skipAboveMaximalSize": False,
                                   "largestSymbolSize": size_range[1], "method": "Smallest"}
    else:
        figure["sizeVariable"] = None
        figure["sizeEvaluator"] = {"@class": "SymbolSizeEvaluator", "symbolSize": size_range[0]}
    figure["rowSymbolSettings"] = {"symbolShapeType": "circleFill", "symbolShape": "circleFill",
                                   "symbolBorderColor": "#000000ff", "symbolBorderThickness": 0.5}
    return figure


def graph_json(t, title: str, x: int, y: int, color: int | None, size: int | None, colors: dict[str, tuple],
               single, axes, length: tuple[float, float], size_range: tuple[float, float],
               numeric_color: bool = False) -> dict:
    """The MVGraph of table t: variables by data-set index, the symbols as
    figure(); axes: ((xlo, xhi, xtick), (ylo, yhi, ytick))."""
    ds = t.datasets
    fig = figure(t, color, size, colors, single, size_range, numeric_color)
    (xl, xh, xt), (yl, yh, yt) = axes
    return {"@class": "MVGraph", "x": PLACE[0], "y": PLACE[1], "width": float(length[0]), "height": float(length[1]),
            "title": {**_text(title, 14.0), "offsetY": 14.0, "dockPosition": "above", "dockAlignment": "middle",
                      "moveDirection": "verticalOnly"},
            "axisX": _axis(ds[x].title or "", xl, xh, xt, False), "axisY": _axis(ds[y].title or "", yl, yh, yt, True),
            "xVariables": [ds[x].uid], "yVariables": [ds[y].uid], "dataSheet": t.sheet_uid,
            "gdoTypes": {"defaults": ["symbols"]}, "gdoSettings": {"symbols": fig}}


def add_graph(arc: ZipArchive, title: str, graph: dict) -> str:
    """A graph sheet holding `graph`, listed after the file's graphs; its uid."""
    doc = B.get_json(arc, "document.json")
    gfens = [B.get_json(arc, f"graphs/{g}/sheet.json").get("fenID", 0) for g in doc["sheets"].get("graphs", [])
             if arc.has(f"graphs/{g}/sheet.json")]  # as graph_transplant numbers a new graph
    uid = new_uid()
    sheet = {"@class": "GraphSheet", "$id": "sheets/graph_sheet.schema.json", "uid": uid,
             "fenID": max(gfens, default=-1) + 2, "title": title, "isCustomTitle": True,
             "paperDimensions": {"width": 612.0, "height": 792.0}, "paperOrientation": "portrait",
             "backgroundColor": "#ffffffff", "drawings": [], "graph": graph}
    B.put_json(arc, f"graphs/{uid}/sheet.json", sheet)
    doc.setdefault("sheets", {}).setdefault("graphs", []).append(uid)
    B.put_json(arc, "document.json", doc)
    return uid
