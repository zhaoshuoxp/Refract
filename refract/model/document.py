"""Format-neutral document model.

Cells are kept as the text that is stored in the file (Prism writes numbers
with %.18g and the CSV must not be routed through floats, see prismbinder
docs/format §5); `DataTable.values()` gives parsed numbers for analysis.
Graphs, layouts and anything not modelled are carried as opaque payloads
by the readers and writers.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

# Bundle `table.dataFormat` -> subcolumns per data set (prismbinder §5)
SUBCOLUMNS = {
    "text": 1, "y_single": 1,
    "y_sd": 2, "y_se": 2, "y_cv": 2,
    "y_plus_minus": 3, "y_high_low": 3, "y_sd_n": 3, "y_se_n": 3, "y_cv_n": 3,
}
REPLICATE_FORMATS = {"y_replicates", "text_replicates"}

# The eight user-facing table kinds in both vocabularies (prismbinder §6)
KIND_TO_PZFX = {
    "xy": ("XY", None), "column": ("OneWay", None), "grouped": ("TwoWay", None),
    "contingency": ("Contingency", None), "survival": ("Survival", None),
    "parts_of_whole": ("PartsOfWhole", None), "multivariable": ("OneWay", "MultipleVariables"),
    "nested": ("TwoWay", "Nested"),
}


def subcolumns_for(data_format: str, replicates: int = 1) -> int:
    if data_format in REPLICATE_FORMATS:
        return max(1, replicates)
    return SUBCOLUMNS.get(data_format, 1)


def to_number(cell: str) -> float | None:
    """Parse a stored cell. Accepts a decimal comma ("56,92015"), which Prism
    reads as a number in files written under such locales (bundled samples)."""
    s = cell.strip()
    if not s:
        return None
    if "," in s and "." not in s and s.count(",") == 1:
        s = s.replace(",", ".")
    try:
        v = float(s)
    except ValueError:
        return None
    return v if math.isfinite(v) else None


@dataclass
class DataSet:
    title: str | None
    subcolumns: list[list[str]]  # [subcolumn][row] stored text, "" = empty
    role: str = "Y"  # Y | X | RT (row titles) | SUBTITLES
    format: str | None = None
    uid: str | None = None
    fen: int | None = None
    # (subcolumn, row) -> attribute names, e.g. {"EXCLUDED"}, {"CENSORED"}
    cell_attributes: dict[tuple[int, int], set[str]] = field(default_factory=dict)
    # (subcolumn, row) -> the cell's stored alignment / text formatting (bundle
    # `cellAlignments`, `cellTextFormats`), kept so rows can move losslessly
    cell_alignments: dict[tuple[int, int], Any] = field(default_factory=dict)
    cell_text_formats: dict[tuple[int, int], Any] = field(default_factory=dict)
    generated: dict[str, float] | None = None  # series X: {"start":..., "interval":...}
    formula: str | None = None  # in-table formula column (values computed by Prism, not stored)
    decimals: int | None = None  # display decimals from the source (.pzfx Decimals), for new bundles
    # a Multiple variables column's type from the source (.pzfx MVType), for new bundles:
    # {"type": "continuous" | "categorical" | "label", "manual": bool, "categories": [(id, name), ...]}
    variable: dict[str, Any] | None = None
    raw: dict[str, Any] | None = None  # source JSON (bundle) for lossless writing

    def is_excluded(self, sub: int, row: int) -> bool:
        return "EXCLUDED" in self.cell_attributes.get((sub, row), set())


@dataclass
class DataTable:
    title: str
    kind: str  # column | grouped | xy | ... | view (analysis results)
    data_format: str
    datasets: list[DataSet]
    n_rows: int
    replicates: int = 1
    row_titles: DataSet | None = None
    x: DataSet | None = None
    subcolumn_titles: DataSet | None = None
    sheet_uid: str | None = None
    table_uid: str | None = None
    is_result: bool = False
    raw_sheet: dict[str, Any] | None = None

    @property
    def subcolumns_per_dataset(self) -> int:
        return subcolumns_for(self.data_format, self.replicates)

    def column_count(self) -> int:
        n = len(self.datasets) * self.subcolumns_per_dataset
        if self.row_titles is not None:
            n += 1
        if self.x is not None and self.x.generated is None:
            n += len(self.x.subcolumns)
        return n

    def x_values(self) -> list[float | None]:
        if self.x is None:
            return []
        if self.x.generated is not None:
            g = self.x.generated
            return [g["start"] + i * g["interval"] for i in range(self.n_rows)]
        return [to_number(c) for c in self.x.subcolumns[0]]

    def values(self, ds: int, sub: int = 0, include_excluded: bool = False) -> list[float | None]:
        d = self.datasets[ds]
        out = []
        for r, cell in enumerate(d.subcolumns[sub]):
            out.append(None if (not include_excluded and d.is_excluded(sub, r)) else to_number(cell))
        return out


@dataclass
class InfoSheet:
    title: str
    constants: list[tuple[str, str]] = field(default_factory=list)
    notes: str = ""
    uid: str | None = None


@dataclass
class Analysis:
    title: str
    analysis_class: str
    parameters: dict[str, Any]
    results: dict[str, Any]
    input_sheets: list[str]
    input_datasets: list[str]
    uid: str | None = None


@dataclass
class Graph:
    title: str
    input_datasets: list[str]
    blob: bytes | None  # PCFF payload (opaque here)
    uid: str | None = None
    fen: int | None = None


def new_uid() -> str:
    import uuid

    return str(uuid.uuid4()).upper()


@dataclass
class NativeGraph:
    """A graph made in Refract from a data table (Prism cannot show it yet:
    it is kept in the bundle's private entry x-refract/graphs.json)."""

    title: str
    table: DataTable
    # its graph type (refract.render.graph_types; "default" | "bars" | "means" | "donut" are
    # older names); "" while none is chosen yet (a new table's graph sheet waits for the choice)
    style: str = "default"
    error: str = "sd"  # the type's plot option (mean_sd, median, tukey, ...; older: sd | sem)
    stars: str = "auto"  # auto: from the first analysis of the table with pairwise comparisons | none
    show_ns: bool = False
    format: dict[str, Any] = field(default_factory=dict)  # overrides (refract.render.formatting)
    options: dict[str, Any] = field(default_factory=dict)  # type options (survival scale, variables)
    uid: str = field(default_factory=new_uid)  # layouts refer to it
    prism_uid: str | None = None  # its copy written as a Prism graph (refract.formats.graph_transplant)
    prism_sig: str | None = None  # what that copy was written from (rewritten when it changes)
    prism_analysis: str | None = None  # survival graphs: the analysis whose result table the copy plots
    # what Refract read of that copy when it last saved (refract.render.prism_sync.summary): a change
    # seen on opening was made in Prism and is taken into this graph
    prism_base: dict[str, Any] | None = None


@dataclass
class LayoutItem:
    """A graph placed on a layout page: `graph` is "prism:<graph sheet uid>" or
    "refract:<NativeGraph uid>"; the box in points from the page's top-left;
    the graph is scaled to fit the box and centred in it."""

    graph: str
    x: float
    y: float
    w: float
    h: float


@dataclass
class NativeLayout:
    """A page of graphs made in Refract (x-refract/layouts.json)."""

    title: str
    width: float = 612.0  # US Letter portrait, points
    height: float = 792.0
    items: list[LayoutItem] = field(default_factory=list)
    uid: str = field(default_factory=new_uid)


@dataclass
class Project:
    source_format: str  # "prism" | "pzfx"
    tables: list[DataTable] = field(default_factory=list)
    infos: list[InfoSheet] = field(default_factory=list)
    analyses: list[Analysis] = field(default_factory=list)
    graphs: list[Graph] = field(default_factory=list)
    layouts: list[Graph] = field(default_factory=list)
    native_graphs: list[NativeGraph] = field(default_factory=list)
    native_layouts: list[NativeLayout] = field(default_factory=list)
    created_by: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def table(self, title: str) -> DataTable:
        return next(t for t in self.tables if t.title == title)
