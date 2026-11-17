"""Graph object model (PLAN §3.3), independent of Prism's file format and of
the drawing backend. Lengths are in points (1/72 inch).

A Graph holds axes and series; refract.render.build makes one from a data
table, refract.render.layout places it, and refract.render.qt draws it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

RGBA = tuple[int, int, int, int]
BLACK: RGBA = (0, 0, 0, 255)


@dataclass
class TextStyle:
    """Overrides of the default text style; None keeps Prism's default."""

    size: float | None = None
    bold: bool | None = None
    italic: bool = False
    color: RGBA = BLACK
    family: str | None = None  # None: the graph's font
    underline: bool = False


@dataclass
class Axis:
    title: str = ""
    min: float | None = None  # None: automatic (refract.render.autoscale)
    max: float | None = None
    tick: float | None = None
    log: bool = False
    minor: int = 0  # minor intervals per major tick (0: none)
    # minor ticks Prism chooses itself (refract.render.autoscale.auto_minor): no
    # minor setting, on a graph Refract made (a Prism graph's own choice is in `minor`)
    minor_auto: bool = True
    title_style: TextStyle = field(default_factory=TextStyle)
    label_style: TextStyle = field(default_factory=TextStyle)  # tick / category labels
    label_angle: float | None = None  # category labels; None: Prism's automatic choice
    # a broken axis: its segments (lo, hi, tick, length in points) from the bottom up; None: one
    segments: list[tuple[float, float, float, float]] | None = None
    # title as placed in Prism, points from the plot's top-left corner: X title
    # (centre x, line-box top), Y title (line-box left, centre y); None: default
    title_pos: tuple[float, float] | None = None
    # the title's line takes space even when empty (Prism's placeholder titles do;
    # deleted or hidden ones do not)
    title_space: bool = True


@dataclass
class Series:
    """One data set as plotted.

    kind "bar": one bar per position (height ys[i]); "points": one symbol per
    (xs[i], ys[i]); "scatter": every value of points[i] at position xs[i]
    (column scatter plots), with ys[i] the centre line (mean or median);
    "steps": a polyline through (xs[i], ys[i]) (survival staircases), with
    censor marks at `marks`.
    err_lo / err_hi: error-bar ends (absolute values), None for none."""

    title: str
    kind: str  # bar | points | scatter | steps | line (a connecting line only)
    xs: list[float]
    ys: list[float | None]
    err_lo: list[float | None] = field(default_factory=list)
    err_hi: list[float | None] = field(default_factory=list)
    points: list[list[float]] = field(default_factory=list)
    color: RGBA = BLACK  # line / symbol / border colour
    fill: RGBA = BLACK
    symbol: str = "circle"  # circle, square, triangle, diamond, ...
    symbol_size: float = 6.32  # pt (circle diameter)
    line_width: float = 1.0
    connect: bool = False  # join points with a line
    line_color: tuple[int, int, int, int] | None = None  # the connecting line; None: color
    symbol_border: tuple[int, int, int, int] | None = None  # outline (0.72 pt); None: none
    slice_fills: list[tuple[int, int, int, int]] | None = None  # pie: per slice (row)
    hole: float = 0.0  # pie: inner radius / outer radius (donut)
    stacked_bar: bool = False  # pie: drawn as one bar of the parts, top down (Prism's stacked bar, E-types)
    width: float = 0.0  # bars: width in X data units (category pitch = 1)
    spread_step: float = 0.0  # individual points: horizontal step between slots, in points
    marks: list[tuple[float, float]] = field(default_factory=list)  # steps: censored subjects (x, y)
    error_color: RGBA | None = None  # None: color
    point_color: RGBA | None = None  # individual points / symbols; None: color
    legend_color: RGBA | None = None  # legend text; None: the graph's legend style
    legend_style: TextStyle | None = None  # this entry's text; None: the graph's legend style
    border_width: float | None = None  # bars: None = Prism's default (2.16 pt); 0 = no border
    base: list[float | None] | None = None  # stacked bars: each bar's bottom (ys are the tops)
    # kinds "box", "violin", "floating": per position {"lo", "q1", "med", "q3", "hi", "mean",
    # "centre" (the line drawn: "median" | "mean" | None), "kde": [(y, density)]} (refract.render.graph_types)
    box: list[dict | None] | None = None
    fill_area: bool = False  # points / line: the area under the line filled (fill colour)
    sizes: list[float] | None = None  # points: each symbol's own size (bubble plots)
    dash: bool = False  # steps / lines drawn dotted (survival confidence bands)
    in_legend: bool = True  # False: drawn, but not listed (three-way graphs list each pairing once)
    # bars and boxes: one of Prism's hatches over the fill (refract.render.formatting.PATTERNS)
    pattern: str | None = None
    pattern_color: RGBA | None = None  # None: black
    bar_styles: dict | None = None  # bar index -> its own fill, pattern, pattern_color, border, border_width
    error_width: float | None = None  # error bars' line (pt); None: Prism's default


@dataclass
class Graph:
    title: str = ""
    family: str = "xy"  # xy, column, grouped, survival, pie
    series: list[Series] = field(default_factory=list)
    x_axis: Axis = field(default_factory=Axis)
    y_axis: Axis = field(default_factory=Axis)
    categories: list[str] = field(default_factory=list)  # column / grouped X labels
    legend: bool = True
    font: str = "Arial"
    title_style: TextStyle = field(default_factory=TextStyle)
    # (centre x, line-box top) from the plot's top-left; None: default (either part)
    title_pos: tuple[float | None, float | None] | None = None
    # use title_pos's height only within this distance of the default rule's
    # (Prism files often hold stale title heights); None: always
    title_snap: float | None = None
    legend_style: TextStyle = field(default_factory=TextStyle)
    # legend entries as placed in Prism: (dx, dy) in points of each entry's box
    # from the plot's top-right corner (refract.render.from_prism); None: default place
    legend_pos: list[tuple[float, float]] | None = None
    # free objects placed in Prism (points, relative to the plot's top-left corner):
    # {"kind": "bracket", "points": [(x, y), ...], "width", "color"} or
    # {"kind": "text", "cx", "top", "text", "style"}
    annotations: list[dict] = field(default_factory=list)
    # legend entries' own texts and swatch colours (pies: one entry per slice,
    # text as Prism stored it, e.g. "46%  Democratic"; a None swatch: text only)
    legend_texts: list[str] | None = None
    legend_fills: list[tuple[int, int, int, int] | None] | None = None
    # significance brackets in data units: {"x1", "x2", "y" (the bar), "top" (above
    # its label, for the axis range), "label"} (refract.render.build.add_significance)
    significance: list[dict] = field(default_factory=list)
    x_length: float | None = None  # axis lengths in points; None: Prism's defaults (refract.render.style)
    y_length: float | None = None
    # an estimation plot (t tests): two groups and their difference on a second,
    # right-hand axis whose zero is the first group's mean (build.estimation_graph):
    # {"paired", "a", "b" (values), "pairs" [(a, b)], "diffs", "lo", "mean", "hi",
    #  "mean_a", "mean_b", "right_title", "color", "symbol_size", "line_width"}
    estimation: dict | None = None
    # text objects moved on the canvas: id ("title", "x.title", "y.title",
    # "legend.<i>", "sig.<j>") -> (dx, dy) points (refract.render.formatting "texts")
    offsets: dict[str, tuple[float, float]] = field(default_factory=dict)
    sig_style: TextStyle | None = None  # significance labels; None: the legend style
    background: RGBA | None = None  # the graph's background; None: white
    plot_fill: RGBA | None = None  # inside the axes; None: none
    axis_color: RGBA | None = None  # axis lines and ticks; None: black
    dividers: list[float] = field(default_factory=list)  # vertical lines between groups (data units) and a top frame
    # a heat map: {"values": [[row][col]], "rows": [...], "cols": [...], "cmap": name, "lo", "hi"}
    heatmap: dict | None = None
    horizontal: bool = False  # column / grouped graphs: categories down the left, values along the bottom
    # a waffle chart (parts of whole): {"parts": [(title, value, fill)], "rows": 10, "cols": 10}
    waffle: dict | None = None
    panel_labels: list[tuple[float, str]] = field(default_factory=list)  # (centre x in data units, label) above the plot
    legend_reverse: bool = False  # the legend lists the data sets last first (Prism's stacked bars)
    y_autoscale: str | None = None  # the Y autoscale rule when not the family's (refract.render.autoscale)
    x_as_columns: bool = False  # categories spaced as a column graph's (one bar each: stacked bars)
    x_columns_length: float | None = None  # then the X length (pt) when not set: Prism's default for the type
    legend_on_columns: bool = False  # a column-family graph that has a legend (Prism's nested graphs)
    # a colour bar beside the plot: {"cmap", "lo", "hi", "title", "alpha"} (Prism's MV graphs coloured by a number)
    color_bar: dict | None = None
    # the symbol sizes' legend beside it: {"title", "entries": [(text, diameter pt)]} (Prism's MV graphs sized
    # by a number)
    size_legend: dict | None = None
    # the categories' legend of a graph coloured by a text variable, drawn as Prism's MV graphs draw it (titled,
    # first, the sizes after it): {"title", "entries": [(text, RGBA, diameter pt)]}
    category_legend: dict | None = None
    # objects drawn on the graph (refract.render.formatting "shapes"): {"kind": "line" | "arrow" | "rect" |
    # "ellipse", "x1", "y1", "x2", "y2" (points from the plot's top-left), "color", "width", "fill", "dash"}
    shapes: list[dict] = field(default_factory=list)

    def extent(self) -> tuple[float, float, float, float] | None:
        """(xmin, xmax, ymin, ymax) of everything plotted: bars, symbols,
        individual points and error-bar ends (what Prism autoscales on)."""
        xs, ys = [], []
        for s in self.series:
            for i, x in enumerate(s.xs):
                vals = [s.ys[i]] if i < len(s.ys) else []
                vals += [v for e in (s.err_lo, s.err_hi) if i < len(e) for v in [e[i]]]
                vals += list(s.points[i]) if i < len(s.points) else []
                b = s.box[i] if s.kind == "violin" and s.box and i < len(s.box) else None
                vals += [b["kde"][0][0], b["kde"][-1][0]] if b and b.get("kde") else []  # the violin's tails
                vals = [v for v in vals if v is not None]
                if vals:
                    xs.append(x)
                    ys.extend(vals)
        ys += [b["top"] for b in self.significance]
        if not ys:
            return None
        return min(xs), max(xs), min(ys), max(ys)
