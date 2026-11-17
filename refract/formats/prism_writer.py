"""Write edited data tables back into a .prism bundle with minimal change.

Only tables whose cells changed are rewritten. For each such table
(prismbinder docs/format §5 "Derived state"):
  data.csv      rebuilt from the model (cells are stored text)
  content.json  numberOfRows / numberOfColumns follow the shape
  data.dt       new revision token (Prism recomputes it on save; E4)
  data sets     replicates[].firstRow/lastRow recomputed (union span of the
                data set's subcolumns); per-range spans for `replicate ranges`.
                Caches Prism does not maintain (realsCount, ...) are preserved.
Everything else (graphs, analyses, other tables) is carried byte for byte.
"""

from __future__ import annotations

import copy
import csv
import io
import json

from ..model.document import DataSet, DataTable, Project, to_number
from . import bundle as B
from . import bundle_builder as BB
from . import cellmeta
from .bundle_builder import new_token
from .prism_reader import _title, read_table
from .zipio import ZipArchive


def table_grid(t: DataTable) -> list[list[str]]:
    """Inverse of the reader's column mapping."""
    cols: list[list[str]] = []
    if t.row_titles is not None:
        cols.append(t.row_titles.subcolumns[0])
    if t.x is not None and t.x.generated is None:
        cols.extend(t.x.subcolumns)
    for d in t.datasets:
        cols.extend(d.subcolumns)
    n = t.n_rows
    return [[(c[r] if r < len(c) else "") for c in cols] for r in range(n)]


def write_csv(grid: list[list[str]]) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n", quoting=csv.QUOTE_MINIMAL)
    for row in grid:
        w.writerow(row)
    return buf.getvalue().encode("utf-8")


def _span(subs: list[list[str]]) -> tuple[int, int]:
    rows = [r for s in subs for r, v in enumerate(s) if v.strip()]
    return (min(rows), max(rows)) if rows else (-1, -1)


def _set_span(rep: dict, first: int, last: int) -> None:
    """Prism 11 writes lastRow always and firstRow only when it is not 0
    (E2 and P1 re-saves); key order is kept for keys already present."""
    rep["lastRow"] = last
    if first == 0:
        rep.pop("firstRow", None)
    else:
        rep["firstRow"] = first


def _want(ds: DataSet, sub: int, rep: dict) -> dict[str, dict[int, object]]:
    """The model's cell metadata of one subcolumn, as cellmeta fields; each
    row's attributes keep their stored order, new names after it."""
    have = cellmeta.decode(rep)["cellAttributes"]
    order = [a for v in have.values() for a in v]
    attrs = {}
    for (s, r), names in ds.cell_attributes.items():
        if s != sub or not names:
            continue
        stored = have.get(r, [])
        if set(stored) == names:
            attrs[r] = stored
        else:
            attrs[r] = [a for a in dict.fromkeys(order) if a in names] + sorted(names - set(order))
    return {"cellAttributes": attrs,
            "cellAlignments": {r: v for (s, r), v in ds.cell_alignments.items() if s == sub},
            "cellTextFormats": {r: v for (s, r), v in ds.cell_text_formats.items() if s == sub}}


def _update_set_json(j: dict, subs: list[list[str]], ds: DataSet | None = None) -> None:
    if "replicate ranges" in j:
        if ds is not None:  # a range whose subcolumns now differ is split into one range each
            split = []
            for rr in j["replicate ranges"]:
                idx = list(cellmeta.rows_of(rr["range"]))
                wants = [_want(ds, i, rr["replicate"]) for i in idx]
                if len(idx) > 1 and any(w != wants[0] for w in wants):
                    split += [{**rr, "range": str(i), "replicate": copy.deepcopy(rr["replicate"])} for i in idx]
                else:
                    split.append(rr)
            j["replicate ranges"] = split
        for rr in j["replicate ranges"]:
            idx = list(cellmeta.rows_of(rr["range"]))
            first, last = _span([subs[i] for i in idx if i < len(subs)])
            _set_span(rr["replicate"], first, last)
            if ds is not None:
                cellmeta.encode(rr["replicate"], _want(ds, idx[0], rr["replicate"]))
    else:
        first, last = _span(subs)
        for k, rep in enumerate(j.get("replicates", [])):
            if rep.get("@class") == "SeriesReplicate":
                continue
            _set_span(rep, first, last)
            if ds is not None:
                cellmeta.encode(rep, _want(ds, k, rep))


def _meta(t: DataTable) -> list:
    sets = [*t.datasets, *([t.row_titles] if t.row_titles else []), *([t.x] if t.x and t.x.generated is None else [])]
    return [(d.uid, d.cell_attributes, d.cell_alignments, d.cell_text_formats) for d in sets]


def _shape(t: DataTable) -> tuple:
    """What a structural edit changes: the table title, the data sets and their titles."""
    return t.title, [d.uid for d in t.datasets], [d.title or "" for d in t.datasets]


def table_changed(arc: ZipArchive, t: DataTable) -> bool:
    current = read_table(arc, t.sheet_uid, [])
    return (table_grid(current) != table_grid(t) or current.n_rows != t.n_rows or _meta(current) != _meta(t)
            or _shape(current) != _shape(t))


def _set_title(j: dict, title: str | None) -> None:
    """Keep the stored form of the title (plain or {"string", "version"})."""
    if (_title(j) or "") == (title or ""):
        return
    if isinstance(j.get("title"), dict):
        j["title"]["string"] = title or ""
    elif title:
        j["title"] = title
    else:
        j.pop("title", None)


def _structure(arc: ZipArchive, t: DataTable) -> list[str]:
    """Data sets added (new data/sets entries), removed (entries deleted) or
    reordered, and a renamed table: sheet.json and document.json follow."""
    touched = []
    name = f"data/sheets/{t.sheet_uid}/sheet.json"
    sheet = B.get_json(arc, name)
    tab = sheet["table"]
    old = list(tab.get("dataSets", []))
    fen = BB.next_set_fen(arc)
    k = t.subcolumns_per_dataset
    for d in t.datasets:
        if d.uid is None or not arc.has(f"data/sets/{d.uid}.json"):  # new (or redone after a save removed it)
            d.uid = d.uid or BB.new_uid()
            cells = [[_cell(c) for c in (sc + [""] * t.n_rows)[: t.n_rows]] for sc in d.subcolumns]
            j = BB.dataset_json(t.kind, t.data_format, k, BB.DataSet(d.title or "", cells), t.n_rows, d.uid, fen)
            d.fen, d.raw = fen, j
            fen += 1
            BB._put(arc, f"data/sets/{d.uid}.json", BB.prismjson.dumps(j))
            touched.append(f"data/sets/{d.uid}.json")
    new = [d.uid for d in t.datasets]
    for u in old:
        if u not in new and arc.has(f"data/sets/{u}.json"):
            arc.remove(f"data/sets/{u}.json")
            touched.append(f"data/sets/{u}.json")
    if new != old or sheet.get("title") != t.title:
        tab["dataSets"] = new
        sheet["title"] = t.title
        B.put_json(arc, name, sheet)
        touched.append(name)
        doc = B.get_json(arc, "document.json")
        if doc.get("sheetAttributesMap", {}).get(t.sheet_uid, {}).get("title") != t.title:
            B.edit_json(arc, "document.json", lambda d: d["sheetAttributesMap"].setdefault(t.sheet_uid, {})
                        .__setitem__("title", t.title))
            touched.append("document.json")
    return touched


def write_table(arc: ZipArchive, t: DataTable) -> list[str]:
    """Write one table into the archive. Returns the entries touched."""
    if t.table_uid is None or t.sheet_uid is None:
        raise ValueError("table has no bundle identity; new tables go through BundleBuilder")
    touched = _structure(arc, t)
    grid = table_grid(t)
    base = f"data/tables/{t.table_uid}"
    arc.put(f"{base}/data.csv", write_csv(grid))
    touched.append(f"{base}/data.csv")
    content = B.get_json(arc, f"{base}/content.json")
    ncols = len(grid[0]) if grid else t.column_count()
    if content.get("numberOfRows") != t.n_rows or content.get("numberOfColumns") != ncols:
        content["numberOfRows"], content["numberOfColumns"] = t.n_rows, ncols
        B.put_json(arc, f"{base}/content.json", content)
        touched.append(f"{base}/content.json")
    arc.put(f"{base}/data.dt", new_token().encode())
    touched.append(f"{base}/data.dt")
    for d in [*t.datasets, *([t.row_titles] if t.row_titles else []), *([t.x] if t.x and t.x.generated is None else [])]:
        if d.uid is None:
            continue
        name = f"data/sets/{d.uid}.json"
        before = arc.read(name)
        j = json.loads(before)
        if d.role == "Y":
            _set_title(j, d.title)
        _update_set_json(j, d.subcolumns, d)
        B.put_json(arc, name, j)
        if arc.read(name) != before:
            touched.append(name)
    return touched


def save_project(src: str | bytes, project: Project, out_path: str | None = None) -> tuple[bytes, list[str]]:
    """Apply the project's table edits onto the source bundle."""
    arc = ZipArchive.from_bytes(src) if isinstance(src, bytes) else ZipArchive.open(src)
    touched: list[str] = []
    for t in project.tables:
        if t.sheet_uid and not t.is_result and table_changed(arc, t):
            touched += write_table(arc, t)
    out = arc.to_bytes()
    if out_path:
        with open(out_path, "wb") as f:
            f.write(out)
    return out, touched


# ------------------------------------------------------------------ new tables
def _cell(text: str):
    if not text.strip():
        return None
    return BB.Num(text) if to_number(text) is not None else text


def spec_of(t: DataTable) -> BB.TableSpec:
    """A table made in Refract as a bundle_builder spec (cells as typed)."""
    n = t.n_rows

    def col(c: list[str]) -> list:
        return [_cell(c[r]) if r < len(c) else None for r in range(n)]

    sets = [BB.DataSet(d.title or "", [col(sc) for sc in d.subcolumns], d.decimals, d.variable) for d in t.datasets]
    rows = None
    if t.row_titles is not None:
        cells = t.row_titles.subcolumns[0] if t.row_titles.subcolumns else []
        rows = [(cells[r] if r < len(cells) and cells[r].strip() else None) for r in range(n)]
    x = col(t.x.subcolumns[0]) if t.x is not None and t.x.subcolumns else None
    return BB.TableSpec(t.title, t.kind, t.data_format, sets, rows, t.x.title if t.x is not None else None,
                        x, t.replicates, t.x.decimals if t.x is not None else None)


def adopt(t: DataTable, arc: ZipArchive, sheet_uid: str) -> None:
    """Give a model table the bundle identity of the entries just written for
    it, so later edits go through write_table."""
    fresh = read_table(arc, sheet_uid, [])
    t.sheet_uid, t.table_uid, t.raw_sheet = fresh.sheet_uid, fresh.table_uid, fresh.raw_sheet
    pairs = [(t.row_titles, fresh.row_titles), (t.x, fresh.x), (t.subcolumn_titles, fresh.subcolumn_titles),
             *zip(t.datasets, fresh.datasets, strict=True)]
    for mine, theirs in pairs:
        if mine is not None and theirs is not None:
            mine.uid, mine.fen, mine.raw = theirs.uid, theirs.fen, theirs.raw


def forget(t: DataTable) -> None:
    """Drop the bundle identity (the table was removed from the bundle)."""
    t.sheet_uid = t.table_uid = t.raw_sheet = None
    for d in [t.row_titles, t.x, t.subcolumn_titles, *t.datasets]:
        if d is not None:
            d.uid = d.fen = d.raw = None


def insert_new_table(arc: ZipArchive, t: DataTable) -> str:
    """Insert a table made in Refract (or converted from a .pzfx): its cells
    as typed, then what spec_of cannot carry (excluded values) as an edit."""
    uid = BB.insert_table(arc, spec_of(t))
    adopt(t, arc, uid)
    if table_changed(arc, t):
        write_table(arc, t)
    return uid
