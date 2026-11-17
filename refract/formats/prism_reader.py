"""Read a .prism / .prismt bundle into the document model.

Column mapping (prismbinder §5, verified on every local table): row titles,
then X (unless it is a generated series), then each data set's subcolumns in
`dataSets` order. The table's `dataFormat` decides the subcolumn count; the
data sets' own formats can disagree with it.
"""

from __future__ import annotations

import csv
import io
import json
from typing import Any

from ..model.document import (
    Analysis,
    DataSet,
    DataTable,
    Graph,
    InfoSheet,
    Project,
    subcolumns_for,
)
from . import cellmeta
from .zipio import ZipArchive


def _rows(spec: str) -> range:
    """'34' -> 34..34, '0~1' -> 0..1"""
    if "~" in spec:
        a, b = spec.split("~")
        return range(int(a), int(b) + 1)
    return range(int(spec), int(spec) + 1)


def _title(j: dict) -> str | None:
    t = j.get("title")
    if isinstance(t, dict):
        return t.get("string")
    return t


def _replicate_specs(j: dict) -> list[tuple[list[int], dict]]:
    """[(subcolumn indexes, replicate dict)] for both `replicates` and
    `replicate ranges` encodings."""
    if "replicate ranges" in j:
        out = []
        for rr in j["replicate ranges"]:
            subs = list(_rows(rr["range"]))
            out.append((subs, rr["replicate"]))
        return out
    return [([k], r) for k, r in enumerate(j.get("replicates", []))]


def _cell_meta(j: dict) -> dict:
    """DataSet keyword arguments: per-cell attributes, alignments and text
    formats ((subcolumn, row) keys) from every replicate (refract.formats.cellmeta)."""
    attrs: dict[tuple[int, int], set[str]] = {}
    align: dict[tuple[int, int], object] = {}
    text: dict[tuple[int, int], object] = {}
    for subs, rep in _replicate_specs(j):
        d = cellmeta.decode(rep)
        for s in subs:
            for r, v in d["cellAttributes"].items():
                attrs.setdefault((s, r), set()).update(v)
            for r, v in d["cellAlignments"].items():
                align[(s, r)] = v
            for r, v in d["cellTextFormats"].items():
                text[(s, r)] = v
    return {"cell_attributes": attrs, "cell_alignments": align, "cell_text_formats": text}


def _series(j: dict) -> dict[str, float] | None:
    for _, rep in _replicate_specs(j):
        if rep.get("@class") == "SeriesReplicate":
            return {"start": float(rep["startValue"]), "interval": float(rep["interval"])}
    return None


def read_csv(data: bytes) -> list[list[str]]:
    if not data:
        return []
    return list(csv.reader(io.StringIO(data.decode("utf-8"), newline="")))


def read_table(arc: ZipArchive, sheet_uid: str, warnings: list[str]) -> DataTable:
    sheet = json.loads(arc.read(f"data/sheets/{sheet_uid}/sheet.json"))
    t = sheet["table"]
    tuid = t["uid"]
    path = f"data/tables/{tuid}/content.json"
    if arc.has(path):
        content = json.loads(arc.read(path))
    else:  # an empty table has no storage folder (seen in Prism-saved documents)
        content = {"numberOfRows": 0, "numberOfColumns": 0}
        warnings.append(f"table {tuid}: no content.json (empty table)")
    rows = read_csv(arc.read(f"data/tables/{tuid}/data.csv")) if arc.has(f"data/tables/{tuid}/data.csv") else []
    n_rows = content.get("numberOfRows", len(rows))
    n_cols = content.get("numberOfColumns", max((len(r) for r in rows), default=0))
    grid = [(r + [""] * n_cols)[:n_cols] for r in rows]
    grid += [[""] * n_cols for _ in range(n_rows - len(grid))]
    col = 0

    def take(k: int) -> list[list[str]]:
        nonlocal col
        # a table holding fewer columns than its format implies (seen in Prism's own result tables): blanks
        subs = [[grid[r][col + i] if col + i < n_cols else "" for r in range(n_rows)] for i in range(k)]
        col += k
        return subs

    def load(uid: str) -> dict:
        return json.loads(arc.read(f"data/sets/{uid}.json"))

    replicates = int(t.get("replicatesCount", 1) or 1)
    k = subcolumns_for(t["dataFormat"], replicates)
    rt = x = st = None
    if t.get("rowTitlesDataSet"):
        j = load(t["rowTitlesDataSet"])
        rt = DataSet(_title(j), take(1), "RT", j.get("format"), j["uid"], j.get("fenID"), raw=j, **_cell_meta(j))
    if t.get("xDataSet"):
        j = load(t["xDataSet"])
        series = _series(j) if (j.get("format") == "series" or t.get("xDataSetFormat") == "series") else None
        if series is not None:
            x = DataSet(_title(j), [], "X", "series", j["uid"], j.get("fenID"), {}, series, raw=j)
        else:
            xk = subcolumns_for(t.get("xDataSetFormat") or j.get("format") or "y_single")
            x = DataSet(_title(j), take(xk), "X", j.get("format"), j["uid"], j.get("fenID"), raw=j, **_cell_meta(j))
    if t.get("subcolumnTitlesDataSet"):
        j = load(t["subcolumnTitlesDataSet"])
        st = DataSet(_title(j), [], "SUBTITLES", j.get("format"), j["uid"], j.get("fenID"), {}, raw=j)
    datasets = []
    for uid in t["dataSets"]:
        j = load(uid)
        ds = DataSet(_title(j), take(k), "Y", j.get("format"), uid, j.get("fenID"), raw=j, **_cell_meta(j))
        vs = j.get("valuesStorageData")
        if isinstance(vs, dict):
            expr = vs.get("expression") or vs.get("formula") or json.dumps(vs)[:200]
            ds.formula = str(expr)
        datasets.append(ds)
    if col != n_cols:
        warnings.append(f"{sheet.get('title')}: column mapping used {col} of {n_cols} columns")
    return DataTable(
        title=sheet.get("title", ""), kind=t["format"], data_format=t["dataFormat"], datasets=datasets,
        n_rows=n_rows, replicates=replicates, row_titles=rt, x=x, subcolumn_titles=st,
        sheet_uid=sheet_uid, table_uid=tuid, is_result="ANALYSIS_VIEW" in sheet.get("flags", []), raw_sheet=sheet,
    )


def read_prism(path_or_bytes: str | bytes, include_results: bool = False) -> Project:
    arc = ZipArchive.from_bytes(path_or_bytes) if isinstance(path_or_bytes, bytes) else ZipArchive.open(path_or_bytes)
    doc: dict[str, Any] = json.loads(arc.read("document.json"))
    sheets = doc.get("sheets", {})
    p = Project("prism", created_by=doc.get("createdBy", {}))
    uids = list(sheets.get("data", []))
    if include_results:
        listed = set(uids)
        uids += [n.split("/")[2] for n in arc.names()
                 if n.startswith("data/sheets/") and n.endswith("/sheet.json") and n.split("/")[2] not in listed]
    for u in uids:
        if arc.has(f"data/sheets/{u}/sheet.json"):
            p.tables.append(read_table(arc, u, p.warnings))
        else:
            p.warnings.append(f"data sheet {u} listed but missing")
    for u in sheets.get("info", []):
        n = f"info/{u}/sheet.json"
        if arc.has(n):
            j = json.loads(arc.read(n))
            p.infos.append(InfoSheet(j.get("title", ""), [(c.get("name", ""), c.get("value", "")) for c in j.get("constants", [])],
                                     j.get("notesText", ""), u))
    for u in sheets.get("analyses", []):
        base = f"analyses/{u}"
        if not arc.has(f"{base}/sheet.json"):
            continue
        s = json.loads(arc.read(f"{base}/sheet.json"))
        params = json.loads(arc.read(f"{base}/parameters.json")) if arc.has(f"{base}/parameters.json") else {}
        results = json.loads(arc.read(f"{base}/results.json")) if arc.has(f"{base}/results.json") else {}
        p.analyses.append(Analysis(s.get("title", ""), s.get("analysisClass", ""), params, results,
                                   [x["uid"] for x in s.get("inputSheets", [])],
                                   [x["uid"] for x in s.get("inputDataSets", [])], u))
    for kind, target in (("graphs", p.graphs), ("layouts", p.layouts)):
        for u in sheets.get(kind, []):
            sj = f"{kind}/{u}/sheet.json"
            s = json.loads(arc.read(sj)) if arc.has(sj) else {}
            blob = arc.read(f"{kind}/{u}/data.bin") if arc.has(f"{kind}/{u}/data.bin") else None
            target.append(Graph(s.get("title", ""), s.get("inputDataSets", []), blob, u, s.get("fenID")))
    from . import native_graphs

    p.native_graphs = native_graphs.read(arc, p)
    p.native_layouts = native_graphs.read_layouts(arc, p)
    return p
