"""Build a render Graph for a graph sheet of a Prism document: the data its
data sets point at (Prism's default graph for the table type, from
refract.render.build), then the graph's own settings as far as they are
decoded from its PCFF blob (docs/format/findings.md):

* texts (0x002C, in stream order): graph title, X title, Y title, right Y
  title, then one legend entry per data set; the placeholders "XTitle",
  "YTitle" and "Y1Title" are hidden titles (verified on the default graphs);
* axis range and major tick (0x8025, honoured when 0x00A5 says manual);
* colours (0x0852 property store, per data set: fill, symbol, error bar and
  bar border), converted from Generic RGB to sRGB (refract.render.color);
* text formatting (0x002D runs: 1 size, 2 style bits 1 bold / 2 italic,
  4 colour 0x00BBGGRR, 6 rotation in 0.1 deg) and tick / category label
  fonts (0x8025 main segment: +38 size, +42 style bits, +44 R G B), and the
  category label angle (X 0x8025 +26: 0 horizontal, 0x40 90 deg, 0x80 auto).

Everything else (plot type, symbol shapes and sizes, error-bar kind, axis
lengths, fonts) still comes from Prism's defaults.
"""

from __future__ import annotations

import json
import struct
from dataclasses import replace

from ..formats.pcff import fields as F
from ..formats.pcff import propstore as PS
from ..formats.pcff import walker
from ..model.document import DataTable, Project
from . import build
from .color import to_srgb
from .model import Graph, TextStyle

PLACEHOLDERS = {"XTitle", "YTitle", "Y1Title", "Y2Title"}


def _table_for(project: Project, uids: list[str], archive=None) -> DataTable | None:
    """The data table holding the graph's data sets, restricted to them (in
    the graph's order); for graphs of analysis results (survival curves) the
    analysis's input table."""
    for t in project.tables:
        mine = {ds.uid: ds for ds in t.datasets}
        sel = [mine[u] for u in uids if u in mine]
        if sel:
            idx = [t.datasets.index(ds) for ds in sel]
            return replace(t, datasets=[t.datasets[i] for i in idx])
    if archive is None or not uids:
        return None
    for n in archive.names():  # result sheet holding the data set -> its analysis
        if n.startswith("data/sheets/") and n.endswith("/sheet.json"):
            s = json.loads(archive.read(n))
            if uids[0] in s.get("table", {}).get("dataSets", []):
                title = s.get("title", "")
                a = next((a for a in project.analyses if title.startswith(a.title + ":")), None)
                if a is not None and a.input_sheets:
                    return next((t for t in project.tables if t.sheet_uid == a.input_sheets[0]), None)
    return None


ESTIMATION_VIEW = ":Estimation Plot"


def _estimation_view(project: Project, uids: list[str], archive=None):
    """(view table, paired, confidence level) when the graph plots a t test's
    estimation-plot view (an analysis view sheet titled "<analysis>:Estimation
    Plot" with three data sets), else None."""
    if archive is None or not uids:
        return None
    from ..formats.prism_reader import read_table

    for n in archive.names():
        if n.startswith("data/sheets/") and n.endswith("/sheet.json"):
            s = json.loads(archive.read(n))
            if uids[0] not in s.get("table", {}).get("dataSets", []):
                continue
            title = s.get("title", "")
            if not title.endswith(ESTIMATION_VIEW) or len(s["table"]["dataSets"]) < 3:
                return None
            a = next((a for a in project.analyses if title.startswith(a.title + ":")), None)
            content = (a.parameters.get("content") or {}) if a is not None else {}
            paired = content.get("experimentalDesign") == "PAIRED_T_TEST"
            level = content.get("confidenceLevel") or 95
            level = level / 100 if level > 1 else level
            return read_table(archive, s["uid"], []), paired, level, a
    return None


def estimation_from_data(project: Project, a, view: DataTable, level: float) -> DataTable | None:
    """The estimation view recomputed from the analysis's input data as it is
    now (after edits): its two data sets (grouped tables: each row's mean, as
    Prism analyses them), and B - A: each subject's difference (paired), or
    the difference of the means with its t confidence interval (unpaired:
    pooled SD; Welch: Welch's SE and df)."""
    import math

    from scipy import stats

    from ..model.document import DataSet

    if a is None or len(a.input_datasets) < 2 or not a.input_sheets:
        return None
    t = next((x for x in project.tables if x.sheet_uid == a.input_sheets[0]), None)
    if t is None:
        return None
    idx = [next((j for j, d in enumerate(t.datasets) if d.uid == u), None) for u in a.input_datasets[:2]]
    if None in idx:
        return None

    def col(j: int) -> list[float | None]:
        out = []
        for r in range(t.n_rows):
            vals = [t.values(j, s)[r] for s in range(t.subcolumns_per_dataset)
                    if r < len(t.values(j, s)) and t.values(j, s)[r] is not None]
            out.append(sum(vals) / len(vals) if vals else None)
        return out

    ca, cb = col(idx[0]), col(idx[1])
    design = (a.parameters.get("content") or {}).get("experimentalDesign")
    if design == "PAIRED_T_TEST":
        diff = [(y - x) if x is not None and y is not None else None for x, y in zip(ca, cb, strict=True)]
    else:
        va, vb = [x for x in ca if x is not None], [x for x in cb if x is not None]
        if len(va) < 2 or len(vb) < 2:
            return None
        ma, mb = sum(va) / len(va), sum(vb) / len(vb)
        sa = sum((x - ma) ** 2 for x in va) / (len(va) - 1)
        sb = sum((x - mb) ** 2 for x in vb) / (len(vb) - 1)
        if design == "WELCH_T_TEST":
            se = math.sqrt(sa / len(va) + sb / len(vb))
            df = (sa / len(va) + sb / len(vb)) ** 2 / ((sa / len(va)) ** 2 / (len(va) - 1)
                                                       + (sb / len(vb)) ** 2 / (len(vb) - 1))
        else:
            df = len(va) + len(vb) - 2
            sp = ((len(va) - 1) * sa + (len(vb) - 1) * sb) / df
            se = math.sqrt(sp * (1 / len(va) + 1 / len(vb)))
        h = float(stats.t.ppf(0.5 + level / 2, df)) * se
        diff = [mb - ma - h, mb - ma, mb - ma + h]

    def text(vs):
        return [["" if v is None else repr(float(v)) for v in vs]]

    n = max(len(ca), len(diff))
    sets = [DataSet(view.datasets[k].title if k < len(view.datasets) else "", text(v)) for k, v in
            enumerate((ca, cb, diff))]
    return DataTable(view.title, "view", "y_single", sets, n)
    return None


def _store(chunks) -> PS.Dict | None:
    for c in chunks:
        if c.tag == PS.TAG and c.payload and c.payload[:4] == b"Zval":
            return PS.decode_payload(c.payload)[0]
    return None


def _rgba(v) -> tuple[int, int, int, int] | None:
    if isinstance(v, PS.Scalar) and len(v.raw) == 4:
        return to_srgb(tuple(v.raw))
    return None


def plot_colors(store: PS.Dict | None) -> list[dict[str, tuple[int, int, int, int]]]:
    """Per plotted data set (SEDObject_Array entries with an XYPlot_Map, in
    order): {fill, symbol, symbol_border, error, bar_border, line}."""
    out = []
    arr = store.get("SEDObject_Array") if store is not None else None
    for obj in (arr.items if isinstance(arr, PS.Array) else []):
        plot = obj.get("XYPlot_Map") if isinstance(obj, PS.Dict) else None
        if not isinstance(plot, PS.Dict):
            continue
        names = {"fill": "PCFF_Plot::fillcolor", "symbol": "PCFF_Plot::symbolcolor",
                 "symbol_border": "PCFF_Plot::symbolBorderColor", "error": "PCFF_Plot::errorcolor",
                 "bar_border": "PCFF_Plot::BarBoxBordercolor", "line": "PCFF_Plot::connectlinecolor",
                 "pattern": "PCFF_Plot::patterncolor"}
        out.append({k: c for k, n in names.items() if (c := _rgba(plot.get(n))) is not None})
    return out


def slice_fills(store: PS.Dict | None) -> list[tuple[int, int, int, int]]:
    """Pie slices' fills (PCFF_PieSlice_Array of the pie plot), sRGB."""
    arr = store.get("SEDObject_Array") if store is not None else None
    for obj in (arr.items if isinstance(arr, PS.Array) else []):
        plot = obj.get("XYPlot_Map") if isinstance(obj, PS.Dict) else None
        sl = plot.get("PCFF_PieSlice_Array") if isinstance(plot, PS.Dict) else None
        if isinstance(sl, PS.Array):
            return [c for x in sl.items if isinstance(x, PS.Dict) and (c := _rgba(x.get("PCFF_PieSlice::fillcolor"))) is not None]
    return []


def _pie_border(store: PS.Dict | None) -> tuple[int, int, int, int] | None:
    arr = store.get("SEDObject_Array") if store is not None else None
    for obj in (arr.items if isinstance(arr, PS.Array) else []):
        plot = obj.get("XYPlot_Map") if isinstance(obj, PS.Dict) else None
        if isinstance(plot, PS.Dict) and plot.get("PCFF_PiePlotData::clOuterBorderColor") is not None:
            return _rgba(plot.get("PCFF_PiePlotData::clOuterBorderColor"))
    return None


def legend_entries(chunks) -> list[dict]:
    """Legend entries (0x8020 type 12) in order: their text object id (the
    0x802B among the children), the data set / pie slice they stand for
    (0x00db +4) and whether the swatch is hidden (0x0084 byte 1 bit 0x02:
    PROVISIONAL, one pie whose legend labels the slices)."""
    import struct

    out = []
    for k, c in enumerate(chunks):
        if c.tag != 0x8020 or not c.payload or len(c.payload) < 10 or struct.unpack_from("<H", c.payload, 0)[0] != 12:
            continue
        e = {"text": None, "index": len(out), "swatch": True}
        for x in chunks[k + 1:k + 14]:
            if x.tag == 0x8020:
                break
            if x.tag == 0x802B and x.payload and e["text"] is None:
                e["text"] = struct.unpack_from("<H", x.payload, 0)[0]
            elif x.tag == 0x00DB and x.payload and len(x.payload) >= 8:
                e["index"] = struct.unpack_from("<I", x.payload, 4)[0]
            elif x.tag == 0x0084 and x.payload and len(x.payload) >= 2:
                e["swatch"] = not x.payload[1] & 0x02
        out.append(e)
    return out


def text_runs(payload: bytes) -> list[tuple[int, dict[int, int]]]:
    """0x002D: [(start, {attribute: value})] formatting runs of a text object
    (u16 runs; per run u16 count, u32 start, then (u16 id, u32 value)s)."""
    import struct

    n = struct.unpack_from("<H", payload, 0)[0]
    i, out = 2, []
    for _ in range(n):
        cnt, start = struct.unpack_from("<HI", payload, i)
        i += 6
        attrs = {}
        for _ in range(cnt):
            k, v = struct.unpack_from("<HI", payload, i)
            i += 6
            attrs[k] = v
        out.append((start, attrs))
    return out


def _style(attrs: dict[int, int]) -> TextStyle:
    c = attrs.get(4)
    color = to_srgb((c & 0xFF, (c >> 8) & 0xFF, (c >> 16) & 0xFF, 255)) if c is not None else (0, 0, 0, 255)
    bits = attrs.get(2, 0)
    return TextStyle(size=attrs.get(1), bold=bool(bits & 1), italic=bool(bits & 2), color=color)


def hidden_texts(chunks) -> set[int]:
    """Ids of text objects whose graph object (0x8020 type 2) is hidden: its
    header byte +28 has bit 0x02 (verified: hidden titles "32 03", shown
    "30 01")."""
    import struct

    out = set()
    for k, c in enumerate(chunks):
        if c.tag == 0x8020 and c.payload and len(c.payload) >= 30 and struct.unpack_from("<H", c.payload, 0)[0] == 2:
            t = next((x for x in chunks[k + 1:k + 12] if x.tag == 0x802B and x.payload), None)
            if t is not None and c.payload[28] & 0x02:
                out.add(struct.unpack_from("<H", t.payload, 0)[0])
    return out


def text_objects(chunks) -> dict[int, tuple[str, TextStyle]]:
    """Text objects by id (0x802B +0): (text, style of its first run); hidden
    ones have an empty text."""
    import struct

    out = {}
    hidden = hidden_texts(chunks)
    for i, c in enumerate(chunks):
        if c.tag == 0x802B and c.payload and i + 1 < len(chunks) and chunks[i + 1].tag == F.TAG_TEXT:
            txt = chunks[i + 1].payload.decode("latin-1")
            fmt = chunks[i + 2] if i + 2 < len(chunks) else None
            runs = text_runs(fmt.payload) if fmt is not None and fmt.tag == 0x002D and fmt.payload else []
            tid = struct.unpack_from("<H", c.payload, 0)[0]
            out[tid] = ("" if tid in hidden else txt, _style(runs[0][1] if runs else {}))
    return out


def text_styles(chunks) -> list[TextStyle]:
    """Style of each text object (its first run), in stream order."""
    out = []
    for i, c in enumerate(chunks):
        if c.tag == F.TAG_TEXT and i + 1 < len(chunks) and chunks[i + 1].tag == 0x002D and chunks[i + 1].payload:
            runs = text_runs(chunks[i + 1].payload)
            out.append(_style(runs[0][1] if runs else {}))
        elif c.tag == F.TAG_TEXT:
            out.append(TextStyle())
    return out


def _axis_label_style(payload: bytes) -> TextStyle:
    import struct

    size = struct.unpack_from("<H", payload, 38)[0]
    bits = payload[42]
    return TextStyle(size=size or None, bold=bool(bits & 1), italic=bool(bits & 2),
                     color=to_srgb((payload[44], payload[45], payload[46], 255)))


# 0x009c +133 plot style. 3: column tables, scatter of the values (Prism's
# default column graph); grouped tables, bars with the values (its default
# grouped graph). 7, 8: the mean as a symbol with error bars, no bars or
# individual values. 1, 2, 4, 5, 9: bars. XY: 0. (Corpus statistics, 285
# graphs; findings.md.)
COLUMN_SCATTER = {3, 7, 8}
SCATTER_STYLES = {7, 8}


# 0x8028 +59 a plot's centre (0 mean, 4 median), +12 its error bars, by centre (E-compare
# error probe: Prism's drawing of each code on column bars)
MEDIAN_CENTRES = (4, 5, 6, 7)
XY_AREA = 8  # on an XY plot: the area below its line filled
MEAN_PLOTS = {0: "mean", 1: "mean_sd", 2: "mean_sem", 3: "mean_ci", 4: "mean_range"}
MEDIAN_PLOTS = {0: "median", 3: "median_iqr", 4: "median_range"}
BUILT_PLOTS = ("mean_sd", "mean_sem", "mean_ci")  # drawn by build from the error kind


def _plot_choice(head: bytes | None) -> str | None:
    """The plot's centre and error bars as a Refract plot choice (None: unknown)."""
    if not head or len(head) <= 59:
        return None
    centre = head[59] & 0x7F  # +59 bit 0x80: set by Prism on horizontal graphs (E-compare re-save)
    if centre in MEDIAN_CENTRES:
        return MEDIAN_PLOTS.get(head[12], "median")
    return MEAN_PLOTS.get(head[12]) if centre in (0, 1, 2, 3) else None


# 0x009C +32: how a grouped plot sits with the next data set's (E-types: Prism's interleaved graphs
# 0, 1, 1, ...; separated 0, 0, ...; stacked 2, ..., 2, 0)
BESIDE, STACKED = 1, 2
EACH = 0x10  # 0x8028 +58: every replicate plotted (XY; E-types)
HEAT = 0x02  # 0x009C +15 on a grouped plot: drawn as a heat map (E-types, one reference graph)
BAR_SYMBOL = 15  # 0x8028 +60: the symbol is a bar from the axis (XY bars; E-types)
# 0x0013 +42 of a survival graph: the wizard's choice (E-types, Prism's own graph of each)
SURVIVAL_TYPES = {11: "surv_ticks", 12: "surv_points", 14: "surv_steps_symbols", 16: "surv_inverted_ticks",
                  17: "surv_inverted_points"}
BAR_STYLES = (1, 2, 5)  # 0x009C +133 of bars; 2 on horizontal graphs (E-types round 2)


def plot_settings(chunks) -> list[dict]:
    """Per data-set plot object (0x8020 type 9, in order): from its 0x009c
    record +133 plot style, +66 individual points (0 = shown, 255 = not:
    68/70 and 176/181 corpus graphs), +81 symbol size code (diameter 1.58 pt
    per step: 3 -> 4.73, 4 -> 6.32, 97 %), and from its 0x8028 header: +94
    the bar border (0 none, 8.. -> (code - 7) * 0.72 pt; PROVISIONAL), +12 the
    error bars (1 SD, 2 SEM; 3 CI provisional), +8 their direction (2 both,
    0 away from the baseline) and +10 = 0 none (provisional) - from 43
    graphs labelled by their PDFs' error-bar lengths; +112 bit 0x40: hidden. 0x009c +8 = 1: the
    means are connected (never set on the 293 corpus graphs whose PDF has no
    such line), +145 its width, coded like the bar border (27 of 27)."""
    out = []
    for k, c in enumerate(chunks):
        if c.tag != 0x8020 or not c.payload or c.payload[:2] != b"\x09\x00":
            continue
        head = rec = None
        for x in chunks[k + 1:k + 8]:
            if x.tag == 0x8028:
                head = x.payload
            elif x.tag == 0x009C and x.payload and len(x.payload) > 140:
                rec = x.payload
                break
        if rec is None:
            continue
        code = head[94] if head and len(head) > 94 else 0
        kind = {1: "sd", 2: "sem", 3: "ci"}.get(head[12], "sd") if head and len(head) > 12 else "sd"
        direction = "both"
        if head and len(head) > 10:
            direction = "none" if head[10] == 0 else {0: "up", 2: "both"}.get(head[8], "both")
        if head and len(head) > 112 and head[112] & 0x40:  # error bars hidden (14 of 15 such graphs, 0 of 115 others)
            direction = "none"
        style = rec[133]
        if style == BOX_STYLE and (rec[67] == VIOLIN or (head and len(head) > 126 and head[126] == VIOLIN)):
            style = VIOLIN  # a violin as Prism saves it: the box code in its drawing copies (E-compare)
        out.append({"style": style, "points": rec[66] == 0, "bar": bool(rec[15] & 0x10),
                    # the fields of the types read from Prism's own graphs (E-types)
                    "floating": rec[125:129] == b"\xff\xff\xff\xff", "arrange": rec[32],
                    "each_line": rec[12] == 1, "each": bool(head) and len(head) > 60 and bool(head[58] & EACH),
                    "bar_symbol": bool(head) and len(head) > 60 and head[60] == BAR_SYMBOL,
                    "heat": bool(rec[15] & HEAT) and rec[133] == 1, "error": kind, "direction": direction,
                    "symbol_size": 1.58 * rec[81] if 0 < rec[81] < 20 else None,
                    "size_code": rec[81] if 0 < rec[81] < 20 else None,
                    "border": 0.0 if code == 0 else (code - 7) * 0.72 if code >= 8 else None,
                    "connect": rec[8] == 1, "join": rec[8], "shape": rec[34],
                    # E-elements: the error bars' width code (as the border's), the hatch (drawn when its
                    # colour, +221, is opaque) and its colour
                    "error_width": (head[122] - 7) * 0.72 if head and len(head) > 122 and head[122] >= 8 else None,
                    "pattern": _pattern(rec),
                    "whiskers": WHISKERS.get(rec[WHISKERS_AT], "min_max"),
                    "plot": _plot_choice(head),
                    "area": bool(head) and len(head) > 59 and head[59] == XY_AREA,
                    "pie": head[99] if head and len(head) > 99 else 0,
                    "pie_outline": bool(head) and len(head) > 96 and head[96] == 2,
                    "fen": int.from_bytes(rec[313:317], "little", signed=True) if len(rec) >= 317 else None, "line_width": (rec[145] - 7) * 0.72 if rec[145] >= 8 else None})
    return out


def _pattern(rec: bytes) -> str | None:
    """The hatch code 0x009C +85 as a pattern name (graph() draws it only with an opaque pattern colour)."""
    from ..formats.graph_patch import PATTERN_CODES

    return next((k for k, v in PATTERN_CODES.items() if v == rec[85]), None) if len(rec) > 85 else None


def plot_rect(chunks) -> tuple[int, int, int, int] | None:
    """0x0013 +0: the plot rectangle (x0, y0, x1, y1) in 1/600 inch, page
    coordinates, y down (verified: 1800 x 1200 for Prism's default XY graph)."""
    import struct

    for c in chunks:
        if c.tag == F.TAG_GRAPH_KIND and c.payload and len(c.payload) >= 8:
            r = struct.unpack_from("<4h", c.payload, 0)
            return r if r[2] > r[0] and r[3] > r[1] else None
    return None


def object_boxes(chunks, kind: int) -> list[tuple[int, int, int, int]]:
    """Boxes (x0, y0, x1, y1; 1/600 inch) of the graph objects (0x8020) of a
    type: 2 text, 8 axis, 9 data-set plot, 10 frame, 12 legend entry."""
    import struct

    out = []
    for c in chunks:
        if c.tag == 0x8020 and c.payload and len(c.payload) >= 10 and struct.unpack_from("<H", c.payload, 0)[0] == kind:
            out.append(struct.unpack_from("<4h", c.payload, 2))
    return out


def text_boxes(chunks) -> dict[int, tuple[int, int, int, int]]:
    """Boxes (1/600 inch, page coordinates) of the text objects (0x8020 type
    2), by text id (the 0x802B that follows)."""
    import struct

    out = {}
    for k, c in enumerate(chunks):
        if c.tag == 0x8020 and c.payload and len(c.payload) >= 10 and struct.unpack_from("<H", c.payload, 0)[0] == 2:
            for x in chunks[k + 1:k + 12]:
                if x.tag == 0x8020:
                    break
                if x.tag == 0x802B and x.payload:
                    out.setdefault(struct.unpack_from("<H", x.payload, 0)[0], struct.unpack_from("<4h", c.payload, 2))
                    break
    return out


U = 72 / 600  # points per file unit (1/600 inch)
# symbol shape, 0x009c +34 (from 1600 symbols matched by colour in the corpus
# PDFs): 1-5 filled, 6-10 the same filled with a border; 0 none
SHAPES = {0: "none", 1: "square", 2: "triangle", 3: "triangle_down", 4: "diamond", 5: "circle",
          6: "square", 7: "triangle", 8: "triangle_down", 9: "diamond", 10: "circle"}
BORDERED = {6, 7, 8, 9, 10}
REVERSED_FAMILIES = {"xy", "survival"}
PIE_STYLE = 9  # 0x009c +133 on parts-of-whole tables; 0x8028 +99: 0 pie, 1 dot plot, 3 donut
DONUT_HOLE = 0.5
# 0x80D6 +20: the parts-of-whole chart (1 pie, 2 donut, 4 stacked bar, 5 percentage dot plot)
# - the one setting that differs between Prism's own pie and donut of the same table (E-donut)
PIE_PIE, PIE_DONUT, PIE_STACKED_BAR = 1, 2, 4  # 4: Prism's parts-of-whole stacked bar (E-types)
PIE_STACKED_BAR_H = 3  # the same on its side (E-types round 2)
PIE_OUTLINE = 1.44
DELETED = -3  # 0x009c +313 of a plot whose data set was deleted
TEXT_PAD = 62.5  # text objects: box = line box padded by ~7.5 pt
TITLE_SNAP = 1.5  # graph title: stored height used within this of Prism's rule (pt)
BRACKET_INSET = 36  # brackets: the bar runs this far inside the box top (verified, 3 brackets)


COMPARISON_TEXT = "???"  # the text of a pairwise comparison's bracket: Prism fills in its summary


def comparison_summaries(project: Project, t: DataTable | None) -> list[str]:
    """The P value summaries (ns, *, ... ****) of the pairwise comparisons of
    the first analysis of table t that has them, in their stored order (the
    brackets' 0x80D8 +4 index; bundled asterisks sample: Control vs Drug A
    first, *** as Prism shows it)."""
    from ..stats import report
    from . import native

    if t is None:
        return []
    for a in project.analyses:
        if t.sheet_uid not in a.input_sheets and t.table_uid not in a.input_sheets:
            continue
        cmp = native.comparisons(a.results)
        if cmp:
            st = report.Style.of(a.parameters)
            return [report.stars(p, st) for _first, _second, p in cmp]
    return []


def annotations(chunks, rect, used: set, summaries: list[str] | None = None) -> list[dict]:
    """Lines and brackets (0x8020 type 3: a bracket's leg ends and its label's
    anchor in three 0x00d9 (+4 x, +8 y), the bar BRACKET_INSET inside the box
    top; a line's two ends; 0x0023 +0 width
    code, +4 R G B, +8 = 1 an arrow head), rectangles and ellipses (types 1,
    6: refract.formats.graph_objects) and free texts (type 2 objects that
    are no title), in points relative to the plot rectangle's top-left corner. Hidden objects (header +28 bit
    0x02, as hidden texts) are left out; a pairwise comparison's bracket
    (0x80D8 +4: the comparison) is followed by its text "???", drawn as the
    comparison's summary from `summaries` (E-compare, asterisks sample)."""
    import struct

    x0, y0 = rect[0], rect[1]
    hidden = hidden_texts(chunks)
    objs = text_objects(chunks)
    out = []
    comparison = None  # the last bracket's comparison
    for k, c in enumerate(chunks):
        if c.tag != 0x8020 or not c.payload or len(c.payload) < 10:
            continue
        kind = struct.unpack_from("<H", c.payload, 0)[0]
        box = struct.unpack_from("<4h", c.payload, 2)
        kids = []
        for x in chunks[k + 1:k + 14]:
            if x.tag == 0x8020:
                break
            kids.append(x)
        if kind == 3:
            if len(c.payload) > 28 and c.payload[28] & 0x02:  # hidden (Prism: comparisons not shown)
                comparison = None
                continue
            cmp = next((x.payload for x in kids if x.tag == 0x80D8 and x.payload and len(x.payload) >= 8), None)
            comparison = struct.unpack_from("<I", cmp, 4)[0] if cmp is not None else None
            ends = [struct.unpack_from("<2I", x.payload, 4) for x in kids if x.tag == 0x00D9 and x.payload and len(x.payload) >= 12]
            line = next((x.payload for x in kids if x.tag == 0x0023 and x.payload and len(x.payload) >= 8), None)
            code = struct.unpack_from("<I", line, 0)[0] if line else 8
            color = to_srgb((line[4], line[5], line[6], 255)) if line else (0, 0, 0, 255)
            width = max(code - 7, 1) * 0.72 if code >= 8 else 0.72
            if len(ends) >= 3:  # a bracket: its legs' ends (and its label's anchor); the bar BRACKET_INSET
                bar = box[1] + BRACKET_INSET  # inside the box top (the bundled asterisks sample: ink 0.36, the anchor's 0.34)
                pts = [(ends[0][0], ends[0][1]), (ends[0][0], bar), (ends[1][0], bar), (ends[1][0], ends[1][1])]
            elif len(ends) == 2:  # a straight line: drawn, or Prism 11's pairwise comparison (E-elements)
                pts = [ends[0], ends[1]]
            else:
                continue
            arrow = line is not None and len(line) > 8 and line[8] == 1
            out.append({"kind": "bracket", "points": [((x - x0) * U, (y - y0) * U) for x, y in pts],
                        "width": width, "color": color, "arrow": arrow})
        elif kind in (1, 6):  # a rectangle, an ellipse: their box, border (0x0022) and fill (0x0021)
            inner = struct.unpack_from("<4h", c.payload, 10) if len(c.payload) >= 18 else box
            border = next((x.payload for x in kids if x.tag == 0x0022 and x.payload and len(x.payload) >= 8), None)
            fill = next((x.payload for x in kids if x.tag == 0x0021 and x.payload and len(x.payload) >= 6), None)
            code = struct.unpack_from("<I", border, 0)[0] if border else 8
            out.append({"kind": "shape", "shape": {
                "kind": "rect" if kind == 1 else "ellipse",
                "x1": (inner[0] - x0) * U, "y1": (inner[1] - y0) * U, "x2": (inner[2] - x0) * U, "y2": (inner[3] - y0) * U,
                "width": (code - 7) * 0.72 if code >= 8 else 0.0,
                "color": to_srgb((border[4], border[5], border[6], 255)) if border else (0, 0, 0, 255),
                **({"fill": to_srgb((fill[2], fill[3], fill[4], 255))} if fill and fill[5] == 0 else {})}})
        elif kind == 2:
            t = next((x for x in kids if x.tag == 0x802B and x.payload), None)
            if t is None:
                continue
            tid = struct.unpack_from("<H", t.payload, 0)[0]
            if tid in used or tid in hidden or tid not in objs:
                continue
            txt, style = objs[tid]
            txt = txt.replace("\r", "\n").strip()
            if txt == COMPARISON_TEXT and comparison is not None and summaries and comparison < len(summaries):
                txt = summaries[comparison]
            if txt and txt not in PLACEHOLDERS:
                a = {"kind": "text", "cx": ((box[0] + box[2]) / 2 - x0) * U, "top": (box[1] + TEXT_PAD - y0) * U,
                     "text": "\n".join(x.strip() for x in txt.splitlines()), "style": style}
                border = next((x.payload for x in kids if x.tag == 0x0022 and x.payload and len(x.payload) >= 8), None)
                code = struct.unpack_from("<I", border, 0)[0] if border else 0
                if code >= 8:  # a text box's border (E-elements: Prism's own text box, code 9)
                    a["frame"] = ((code - 7) * 0.72, to_srgb((border[4], border[5], border[6], 255)))
                out.append(a)
    return out


def _data_uids(project: Project, gs, plots: list[dict]) -> list[str]:
    """The graph's data sets: the sheet's inputDataSets, or else the ones its
    plots name by fen id (0x009c +313; equals the input data sets' fen on 300
    of 301 graphs), in the table's order."""
    uids = list(gs.input_datasets)
    if not uids and plots:
        order = [ds for tb in project.tables for ds in tb.datasets]
        want = {ps["fen"] for ps in plots}
        uids = [ds.uid for ds in order if ds.fen is not None and ds.fen in want]
    return uids


def source_tables(project: Project, index: int, archive=None) -> list[DataTable]:
    """The project's data tables (the objects themselves) that graph `index`
    plots, for invalidating it when they are edited; for an analysis's
    estimation plot (with the archive), the analysis's input table."""
    gs = project.graphs[index]
    try:
        plots = plot_settings(walker.parse(gs.blob)) if gs.blob else []
    except ValueError:
        plots = []
    uid_list = _data_uids(project, gs, plots)
    uids = set(uid_list)
    out = [t for t in project.tables if any(ds.uid in uids for ds in t.datasets)]
    if not out and archive is not None:
        est = _estimation_view(project, uid_list, archive)
        a = est[3] if est is not None else None
        if a is not None and a.input_sheets:
            out = [t for t in project.tables if t.sheet_uid == a.input_sheets[0]]
    return out


def graph(project: Project, index: int, archive=None, use_cached: bool = True) -> Graph:
    """Render model of the project's graph sheet `index` (document order).
    use_cached: take automatic axis ranges from Prism's cache (what it drew
    last); False recomputes them (refract.render.autoscale), e.g. after edits."""
    gs = project.graphs[index]
    if not gs.blob or gs.blob[:8] != b"PCFFGRA4":  # a Multiple-variables graph: JSON in its sheet (mv_prism)
        from . import mv_prism

        mv = mv_prism.sheet_graph(archive, gs.uid)
        if mv is not None:
            return mv_prism.read(project, mv, gs.title)
    try:
        ch = walker.parse(gs.blob) if gs.blob else None
    except ValueError as e:  # e.g. the older Cox-regression graph blobs
        raise NotImplementedError(f"graph blob not decoded: {e}") from e
    plots = plot_settings(ch) if ch is not None else []
    uids = _data_uids(project, gs, plots)
    est = _estimation_view(project, uids, archive)
    if est is not None and not use_cached:  # its data were edited: Prism's stored view is out of date
        fresh = estimation_from_data(project, est[3], est[0], est[2])
        if fresh is not None:
            est = (fresh, *est[1:])
    t = est[0] if est is not None else _table_for(project, uids, archive)
    if t is None:
        raise NotImplementedError("graph data not found (layout, analysis result or embedded object)")
    if ch is None:
        return build.from_table(t, title=gs.title)
    # plots whose data set was deleted (fen -3) are not drawn
    live = [i for i, ps in enumerate(plots) if ps["fen"] != DELETED]
    plots = [plots[i] for i in live]
    error = plots[0]["error"] if plots else "sd"
    pie = t.kind == "parts_of_whole" and bool(plots) and plots[0]["style"] == PIE_STYLE
    if est is not None:
        g = build.estimation_graph(t, est[1], gs.title, est[2])
    elif pie:
        if plots[0]["pie"] == 1:
            raise NotImplementedError("percentage dot plots")
        g = build.pie_graph(t, title=gs.title)
    else:
        if t.kind in ("parts_of_whole", "contingency"):  # drawn as bars: rows are the categories, as on a
            t = replace(t, kind="grouped")  # grouped table (a contingency table: Refract writes it so, E-compare)
        if t.kind == "nested":  # Refract's nested graphs (Prism's: E-types)
            from . import graph_types as GT

            g = GT.make(t, GT.BY_KEY[type_of(t, plots, None) or "nest_scatter"], None, gs.title)
        else:
            g = build.from_table(t, error=error, title=gs.title)
    # XY and survival graphs store their plots last data set first (19 of 19
    # corpus graphs matched by legend colours; grouped and column in order)
    reverse = g.family in REVERSED_FAMILIES
    if reverse:
        plots = plots[::-1]
    # texts by role: the graph title is the text object referenced by 0x0013
    # +32, the X / Y / right Y titles those referenced by the 0x0017 axis
    # chunks +48 (verified on 4 graphs whose stream order differs)
    objs = text_objects(ch)
    import struct

    head = next((c.payload for c in ch if c.tag == F.TAG_GRAPH_KIND and c.payload and len(c.payload) >= 34), None)
    axes_refs = [struct.unpack_from("<H", c.payload, 48)[0] for c in F.axes(ch) if c.payload and len(c.payload) >= 50]
    title_ref = struct.unpack_from("<H", head, 32)[0] if head is not None else None
    if title_ref in objs:
        g.title, g.title_style = objs[title_ref]
    horizontal = head is not None and len(head) > 29 and bool(head[29] & HORIZONTAL) and \
        g.family in ("column", "grouped")
    # a horizontal graph's stored X axis is its value axis (bottom), its Y axis the categories (left)
    axes_pair = (g.y_axis, g.x_axis) if horizontal else (g.x_axis, g.y_axis)
    for ax, ref in zip(axes_pair, axes_refs, strict=False):
        if ref in objs:
            txt, ts = objs[ref]
            ax.title = "" if txt in PLACEHOLDERS else txt
            ax.title_space = bool(txt.strip())  # placeholder: kept; deleted / hidden: none
            ax.title_style = ts
    by_text = {txt: ts for txt, ts in objs.values()}
    for s in g.series:
        if s.title in by_text:
            g.legend_style = by_text[s.title]
            s.legend_color = by_text[s.title].color
    raw_sets = [c.payload for c in F.axis_settings(ch)]
    if len(raw_sets) > 3 and len(raw_sets[0]) > 46:
        g.x_axis.label_style = _axis_label_style(raw_sets[0])
        g.y_axis.label_style = _axis_label_style(raw_sets[3])
        if head is not None and len(head) > 29 and head[29] & HORIZONTAL:
            g.x_axis.label_style, g.y_axis.label_style = g.y_axis.label_style, g.x_axis.label_style
        flag = raw_sets[0][26]
        g.x_axis.label_angle = 0.0 if flag == 0 else 90.0 if flag == 0x40 else None
    # axes: manual range / tick
    modes = [F.AxisMode.read(c) for c in F.axis_modes(ch)]
    sets = [F.AxisSettings.read(c) for c in F.axis_settings(ch)]
    for ax, i in (((g.y_axis, 0),) if horizontal else ((g.x_axis, 0), (g.y_axis, 1))):
        if i < len(modes) and 3 * i < len(sets) and not (g.family in ("column", "grouped") and i == 0
                                                          and not horizontal):
            m, s = modes[i], _data_segment(sets, 3 * i)
            # the stored range is what Prism drew (manual, or its automatic choice
            # cached when the graph was last shown); used for display
            if (m.flags & F.AxisMode.MANUAL_RANGE or use_cached) and s.max > s.min and not s.log10:
                ax.min, ax.max = s.min, s.max
            if (m.flags & F.AxisMode.MANUAL_TICK or use_cached) and s.major_tick > 0 and not s.log10:
                ax.tick = s.major_tick
            # minor intervals per major tick (0x8025 +52): set, or Prism's own
            # choice cached with the graph (E-pairs: 5 -> four minor ticks)
            raw = F.axis_settings(ch)[3 * i].payload
            ax.minor_auto = False  # what Prism chose is in the file
            if len(raw) > 52 and 0 < raw[52] <= 20 and not s.log10:
                ax.minor = raw[52]
            if s.log10:  # log10 axis: the stored range is in exponents (0.1 .. 1e5 = -1 .. 5)
                ax.log = True
                if (m.flags & F.AxisMode.MANUAL_RANGE or use_cached) and s.max > s.min:
                    ax.min, ax.max = 10.0 ** s.min, 10.0 ** s.max
    if len(sets) > 3:  # axis lengths, 1/600 inch (plausible values only: 0.1-20 in)
        g.x_length, g.y_length = (v * 72 / 600 if 60 <= v <= 12000 else None
                                  for v in (sets[0].length, _data_segment(sets, 3).length & 0xFFFF))
        top = _data_segment(sets, 3)
        if top is not sets[3] and not horizontal and 60 <= sets[3].length <= 12000 and sets[3].major_tick > 0:
            low = sets[3]  # a broken Y axis: the main setting is its bottom segment
            g.y_axis.segments = [(low.min, low.max, low.major_tick, low.length * 72 / 600),
                                 (top.min, top.max, top.major_tick, (top.length & 0xFFFF) * 72 / 600)]
            g.y_axis.min, g.y_axis.max, g.y_axis.tick = low.min, top.max, top.major_tick
            from .qt import AXIS_BREAK_GAP

            g.y_length = sum(sg[3] for sg in g.y_axis.segments) + AXIS_BREAK_GAP
        if horizontal:  # x_length is the category axis, y_length the values'
            g.x_length, g.y_length = g.y_length, g.x_length
    # legend: entry boxes (0x8020 type 12) relative to the plot rectangle
    # (0x0013 +0: x0, y0, x1, y1 in 1/600 inch); no entries -> no legend
    rect = plot_rect(ch)
    boxes = object_boxes(ch, 12)
    if rect is not None:
        if boxes:
            g.legend_pos = [((b[0] - rect[2]) * 72 / 600, (b[1] - rect[1]) * 72 / 600) for b in boxes]
        elif g.family != "survival":
            g.legend = False
    if rect is not None:
        g.annotations = annotations(ch, rect, used={t for t in (title_ref, *axes_refs)},
                                    summaries=comparison_summaries(project, t))
        # titles where Prism placed them: box = line box padded TEXT_PAD (verified on
        # the 4 default graphs to 0.2 pt; the Y title's box is the rotated line box).
        # The graph title's stored height is often stale (6 pt high in older files):
        # Prism draws it by its own rule, just above the topmost element (127 of 146
        # corpus titles within 1.5 pt, the stored box 73); the stored height is
        # kept only when it agrees with the rule to TITLE_SNAP (then it is exact).
        hidden = hidden_texts(ch)
        tb = {k: v for k, v in text_boxes(ch).items() if k not in hidden}
        if title_ref in tb:
            b = tb[title_ref]
            g.title_pos = (((b[0] + b[2]) / 2 - rect[0]) * U, (b[1] + TEXT_PAD - rect[1]) * U)
            g.title_snap = TITLE_SNAP
        if axes_refs and axes_refs[0] in tb:
            b = tb[axes_refs[0]]
            g.x_axis.title_pos = (((b[0] + b[2]) / 2 - rect[0]) * U, (b[1] + TEXT_PAD - rect[1]) * U)
        if len(axes_refs) > 1 and axes_refs[1] in tb:
            b = tb[axes_refs[1]]
            g.y_axis.title_pos = ((b[0] + TEXT_PAD - rect[0]) * U, ((b[1] + b[3]) / 2 - rect[1]) * U)
    if g.estimation is not None:
        return _estimation_settings(g, ch, plots, axes_refs, objs, live)
    # per data set: plot style, points, symbol size, bar border, error bars (findings.md)
    if g.family == "column" and plots and all(ps["style"] not in COLUMN_SCATTER for ps in plots):
        build.column_bars(g, t, error)
    if g.family in ("column", "grouped") and plots and all(ps["style"] in SCATTER_STYLES for ps in plots):
        build.mean_symbols(g, error)
    _plot_centres(g, t, plots)
    for s, ps in zip(g.series, plots, strict=False):
        if ps["symbol_size"]:
            s.symbol_size = ps["symbol_size"]
        if ps["shape"] in SHAPES:
            s.symbol = SHAPES[ps["shape"]]
        if ps.get("error_width"):
            s.error_width = ps["error_width"]
        if s.kind == "bar":
            if not ps["points"]:
                s.points = []  # not drawn, and not part of the autoscale extent
            s.border_width = ps["border"]
        if ps["direction"] == "up":  # away from the baseline only
            s.err_lo = [None if (y is not None and y >= 0) else lo for y, lo in zip(s.ys, s.err_lo, strict=False)]
            s.err_hi = [hi if (y is not None and y >= 0) else None for y, hi in zip(s.ys, s.err_hi, strict=False)]
        elif ps["direction"] == "none":
            s.err_lo, s.err_hi = [], []
    # colours
    colors = plot_colors(_store(ch))
    if len(colors) >= (live[-1] + 1 if live else 0):  # parallel to the plot objects, deleted ones included
        colors = [colors[i] for i in live]
    if reverse:
        colors = colors[::-1]
    for s, c in zip(g.series, colors, strict=False):
        if s.kind == "bar":
            s.fill = c.get("fill", s.fill)
            s.color = c.get("bar_border", s.color)
        else:
            s.color = c.get("symbol", s.color)
        s.point_color = c.get("symbol")
        s.error_color = c.get("error")
    for s, ps, c in zip(g.series, plots, colors + [{}] * len(plots), strict=False):
        if ps["shape"] in BORDERED:
            s.symbol_border = c.get("symbol_border", (0, 0, 0, 255))
        # a hatch: its code, drawn when its colour in the store is opaque (none: ffffff00; E-elements)
        hatch = c.get("pattern")
        if ps.get("pattern") and hatch is not None and hatch[3] > 0 and s.kind in ("bar", "box", "violin", "floating"):
            s.pattern, s.pattern_color = ps["pattern"], hatch
    # connecting lines: within each data set; a column graph joins the data
    # sets' means, left to right, in the first data set's line style
    for s, ps, c in zip(g.series, plots, colors + [{}] * len(plots), strict=False):
        if ps["connect"] and g.family != "column":
            s.connect = True
            s.line_width = ps["line_width"] or s.line_width
        if g.family == "xy" and ps.get("area"):  # 0x8028 +59 = 8: the area below the line (E-compare probe 11)
            s.connect = s.fill_area = True
            s.line_width = ps["line_width"] or s.line_width
            s.line_color = c.get("line")
    if g.family == "column" and plots and plots[0]["connect"] and BEFORE_AFTER not in [ps["style"] for ps in plots]:
        pts = [(s.xs[0], s.ys[0]) for s in g.series if s.xs and s.ys and s.ys[0] is not None]
        if len(pts) > 1:
            c = colors[0] if colors else {}
            # first, so it lies under the symbols
            g.series.insert(0, build.Series(title="", kind="line", xs=[x for x, _ in pts], ys=[y for _, y in pts],
                                         connect=True, line_width=plots[0]["line_width"] or 1.0,
                                         line_color=c.get("line")))
    if pie:
        _pie_settings(g, ch, plots[0], rect, objs)
    _plot_kinds(g, t, plots)
    g.horizontal = horizontal or g.horizontal
    key = type_of(t, plots, head)
    if key is not None:
        g = as_type(g, t, key, plots)
    return g


def type_of(t: DataTable, plots: list[dict], head: bytes | None) -> str | None:
    """The Refract graph type of a Prism graph whose look Refract draws only
    as that type (separated, stacked, floating, XY replicates and bars,
    nested; E-types: the fields of Prism's own graphs of each type)."""
    if not plots:
        return None
    p = plots[0]
    st = p["style"]
    if t.kind == "survival":
        key = SURVIVAL_TYPES.get(head[42]) if head is not None and len(head) > 42 else None
        return None if key == "surv_ticks" else key
    if t.kind == "column" and st == BOX_STYLE and p["floating"]:
        return "col_floating"
    if t.kind in ("grouped", "contingency"):
        if st == BOX_STYLE and p["floating"]:
            return "grp_floating"
        arrange = [q["arrange"] for q in plots]
        if st in BAR_STYLES and STACKED in arrange[:-1]:
            return "grp_stacked"
        if len(plots) > 1 and all(a == 0 for a in arrange):  # each data set a block of its own: separated
            return {3: "grp_bars_points_sep" if p["bar"] else "grp_scatter_sep", 1: "grp_bars_sep", 2: "grp_bars_sep",
                    5: "grp_bars_sep",
                    7: "grp_means_sep", BOX_STYLE: "grp_box_sep", VIOLIN: "grp_violin_sep"}.get(st)
        if st == 0 and p["connect"] and p["each_line"]:
            return "grp_rep_lines"
        if p["heat"]:
            return "grp_heat_viridis"
    if t.kind == "xy":
        if p["bar_symbol"]:
            return "xy_bars"
        if p["each"]:
            return "xy_rep_lines" if p["each_line"] else "xy_replicates_line" if p["connect"] else "xy_replicates"
    if t.kind == "nested":
        if st == BOX_STYLE:
            return "nest_floating" if p["floating"] else "nest_box"
        if st == VIOLIN:
            return "nest_violin"
        return "nest_scatter_bar" if p["bar"] else "nest_scatter"
    return None


def as_type(g: Graph, t: DataTable, key: str, plots: list[dict]) -> Graph:
    """Graph g (read from Prism) drawn as Refract type `key` from table t,
    keeping what Prism set: titles, their styles, axis ranges and lengths,
    the legend, data-set colours and symbols."""
    from dataclasses import replace as _replace

    from . import graph_types as GT

    gt = GT.BY_KEY[key]
    if t.kind == "grouped" and gt.family == "contingency":
        gt = GT.BY_KEY[key.replace("cont_", "grp_")]
    plot = plots[0].get("plot") if plots else None
    out = GT.make(t, gt, plot if plot in [c for c, _ in gt.plots] else None, g.title)
    out.title, out.title_style = g.title, g.title_style
    for a, b in ((out.x_axis, g.x_axis), (out.y_axis, g.y_axis)):
        for k in ("title", "title_style", "label_style", "title_space"):
            setattr(a, k, getattr(b, k))
    if key not in ("grp_stacked",) and not key.endswith("_sep"):
        out.y_axis = _replace(out.y_axis, min=g.y_axis.min, max=g.y_axis.max, tick=g.y_axis.tick)
    out.x_length, out.y_length = g.x_length or out.x_length, g.y_length or out.y_length
    out.legend, out.legend_style = g.legend, g.legend_style
    out.horizontal = g.horizontal or out.horizontal
    by_title = {s.title: s for s in g.series if s.title}
    for s in out.series:
        src = by_title.get(s.title)
        if src is not None:
            s.fill, s.color, s.point_color = src.fill, src.color, src.point_color
            if out.family == "survival" and s.symbol != "none":  # the symbols Prism draws at the steps
                s.symbol, s.symbol_border = src.symbol, src.symbol_border
    return out


HORIZONTAL = 0x80  # 0x0013 +29: categories down the left, values along the bottom (7 of 7 sample graphs, 0 of 96)
BOX_STYLE, BEFORE_AFTER = 4, 8  # 0x009C +133 (bundled samples: box and whiskers; a line to the next data set)
VIOLIN = 11  # 0x009C +133: violin (E-compare style probe, column and grouped)
# 0x009C +125: a box plot's whiskers (E-compare whisker probe; the bundled 10-90 sample has 2)
WHISKERS_AT = 125
# a box plot's values are drawn 0.72 pt per 0x009C +81 size step, not 1.58 (Prism's exports of the two
# bundled box samples: size 4 -> 2.7-2.9 pt dots)
BOX_SIZE_STEP = 0.72
WHISKERS = {0: "min_max", 1: "tukey", 2: "p10_90", 3: "p5_95", 6: "min_max_points"}  # 6: all values shown


def _data_segment(sets: list, base: int):
    """A broken axis's segment holding the data: the 0x8025 settings at
    base + 1 / + 2 are segments when they are objects of their own (else
    their ids are their positions, 0 to 100 by 10) and lie above the main
    one (the bundled asterisks sample: 0..40 under 50..80, its length in the
    low 16 bits of +30); graph() keeps both as the axis's segments."""
    main = sets[base] if base < len(sets) else None
    for k in (2, 1):
        if main is None or base + k >= len(sets):
            continue
        seg = sets[base + k]
        if seg.object_id != base + k and seg.max > seg.min >= main.max and not seg.log10 and \
                60 <= seg.length & 0xFFFF <= 12000:
            return seg
    return main


def _plot_kinds(g: Graph, t: DataTable, plots: list[dict]) -> None:
    """Plot styles drawn by Refract's graph types: box and whiskers (the
    whiskers the plot names, the values beyond them as symbols; all values
    over the box when the plot shows them), violins, and before-
    after lines from each plot with style 8 to the next data set, row by row,
    the values as symbols without centre lines (bundled samples)."""
    from . import graph_types as GT

    if g.family == "grouped" and plots:
        _grouped_boxes(g, t, plots)
    if g.family != "column" or not plots:
        return
    styles = [ps["style"] for ps in plots]
    if BOX_STYLE in styles or VIOLIN in styles:
        for j, (s, ps) in enumerate(zip(g.series, plots, strict=False)):
            if ps["style"] not in (BOX_STYLE, VIOLIN):
                continue
            vals = [v for v in t.values(j, 0) if v is not None] if j < len(t.datasets) else []
            violin = ps["style"] == VIOLIN
            b, out = GT.box_stats(vals, "min_max" if violin else ps.get("whiskers", "min_max"))
            if b is not None and violin:
                b["kde"] = GT.kde(vals)
            s.kind, s.box = ("violin" if violin else "box"), [b]
            if not violin and ps.get("size_code"):
                s.symbol_size = BOX_SIZE_STEP * ps["size_code"]
            s.ys = [b["med"] if b else None]
            s.err_lo, s.err_hi = [b["lo"] if b else None], [b["hi"] if b else None]
            s.points = [vals if ps["points"] else out]
            s.width = s.width or 0.6
    if BEFORE_AFTER in styles:
        n = max((len(t.values(j, 0)) for j in range(len(t.datasets))), default=0)
        lines = []
        for j, ps in enumerate(plots):
            if ps["style"] != BEFORE_AFTER or j + 1 >= len(g.series) or j + 1 >= len(t.datasets):
                continue
            a, b = t.values(j, 0), t.values(j + 1, 0)
            for r in range(n):
                if r < len(a) and r < len(b) and a[r] is not None and b[r] is not None:
                    lines.append(build.Series("", "line", [float(j), float(j + 1)], [a[r], b[r]], connect=True,
                                              color=g.series[j].color, in_legend=False))
        for j, s in enumerate(g.series):  # the values at their column, no centre line
            if s.kind == "scatter" and j < len(t.datasets):
                s.kind, s.spread_step = "points", 0.0
                vals = t.values(j, 0)
                s.xs = [float(j)] * len(vals)
                s.ys = list(vals)
                s.err_lo, s.err_hi, s.points = [], [], []
        g.series = lines + g.series


def _plot_centres(g: Graph, t: DataTable, plots: list[dict]) -> None:
    """Column and grouped plots whose centre and error bars build does not
    draw from the error kind (mean only, medians, ranges): recomputed from
    the values (refract.render.graph_types.summary, Prism's quantiles)."""
    from . import graph_types as GT

    if g.family not in ("column", "grouped") or t.data_format not in ("y_replicates", "y_single") or \
            not any(ps.get("plot") not in (None, *BUILT_PLOTS) for ps in plots):
        return
    if g.family == "column":
        groups = GT.groups(t)
        cols = [[vals] for _, vals in groups]
    else:
        _rows, _sets, vals = GT.cells(t)
        cols = [[vals[r][j] for r in range(len(vals))] for j in range(len(_sets))]
    for j, (s, ps) in enumerate(zip(g.series, plots, strict=False)):
        if ps.get("plot") in (None, *BUILT_PLOTS) or j >= len(cols) or s.kind not in ("bar", "scatter", "points"):
            continue
        sm = [GT.summary(v, ps["plot"]) for v in cols[j][:len(s.xs)]]
        s.ys = [c for c, _, _ in sm]
        s.err_lo, s.err_hi = [lo for _, lo, _ in sm], [hi for _, _, hi in sm]


def _grouped_boxes(g: Graph, t: DataTable, plots: list[dict]) -> None:
    """Grouped plots in box (the plot's whiskers) or violin style: one box per row
    at the data set's place, Prism's colours kept (E-compare style probe)."""
    from . import graph_types as GT

    if not any(ps["style"] in (BOX_STYLE, VIOLIN) for ps in plots):
        return
    _rows, _sets, vals = GT.cells(t)
    m = max(len(g.series), 1)
    for j, (s, ps) in enumerate(zip(g.series, plots, strict=False)):
        if ps["style"] not in (BOX_STYLE, VIOLIN) or j >= len(_sets):
            continue
        violin = ps["style"] == VIOLIN
        boxes, outs = [], []
        for r in range(len(s.xs)):
            v = vals[r][j] if r < len(vals) else []
            b, out = GT.box_stats(v, "min_max" if violin else ps.get("whiskers", "min_max"))
            if b is not None and violin:
                b["kde"] = GT.kde(v)
            boxes.append(b)
            outs.append(v if ps["points"] else out)
        s.kind, s.box = ("violin" if violin else "box"), boxes
        if not violin and ps.get("size_code"):
            s.symbol_size = BOX_SIZE_STEP * ps["size_code"]
        s.ys = [b["med"] if b else None for b in boxes]
        s.err_lo, s.err_hi = [b["lo"] if b else None for b in boxes], [b["hi"] if b else None for b in boxes]
        s.points = outs
        s.width = 0.8 / (m + 0.5)


def _estimation_settings(g: Graph, ch, plots: list[dict], axes_refs: list[int], objs: dict, live: list[int]) -> Graph:
    """An estimation plot's own parts from the file: the right axis title
    (the third axis's text), the symbols' size, shape and colour and the
    pair lines' width (the first plot's settings)."""
    if len(axes_refs) > 2 and axes_refs[2] in objs:
        txt, ts = objs[axes_refs[2]]
        if txt.strip() and txt not in PLACEHOLDERS:
            g.estimation["right_title"] = txt
        g.estimation["right_style"] = ts
    if plots:
        ps = plots[0]
        g.estimation["symbol_size"] = ps["symbol_size"] or g.estimation["symbol_size"]
        g.estimation["line_width"] = ps["line_width"] or g.estimation["line_width"]
        if ps["shape"] in SHAPES:
            g.estimation["symbol"] = SHAPES[ps["shape"]]
    colors = plot_colors(_store(ch))
    if colors and colors[0].get("symbol"):
        g.estimation["color"] = colors[0]["symbol"]
    return g


def _pie_settings(g: Graph, ch, ps: dict, rect, objs) -> None:
    """Pie: the plot rectangle is the pie's square; slice fills; donut hole
    (chart type 3; 0.5 of the radius on the one corpus donut); legend entries
    with Prism's own texts and their slices' fills."""
    if rect is not None:
        g.x_length = g.y_length = (rect[2] - rect[0]) * U
    s = g.series[0]
    s.slice_fills = slice_fills(_store(ch)) or None
    kind = next((struct.unpack_from("<I", c.payload, 20)[0] for c in ch if c.tag == 0x80D6 and c.payload
                 and len(c.payload) >= 24), None)
    s.hole = DONUT_HOLE if kind == PIE_DONUT or ps["pie"] == 3 else 0.0
    s.stacked_bar = kind in (PIE_STACKED_BAR, PIE_STACKED_BAR_H)
    g.horizontal = kind == PIE_STACKED_BAR_H
    # 0x8028 +96 = 2: the pie's outer edge and the swatches outlined (PROVISIONAL:
    # 14 of 16 pies agree with their PDFs' strokes), in the outer border colour
    if ps["pie_outline"]:
        s.border_width = PIE_OUTLINE
        s.symbol_border = _pie_border(_store(ch)) or (0, 0, 0, 255)
    texts, fills = [], []
    for e in legend_entries(ch):
        txt, ts = objs.get(e["text"], ("", g.legend_style))
        texts.append(txt.replace("\r", " ").strip())
        g.legend_style = ts
        sf = s.slice_fills or []
        fills.append(sf[e["index"]] if e["swatch"] and e["index"] < len(sf) else None)
    g.legend_texts, g.legend_fills = texts, fills
