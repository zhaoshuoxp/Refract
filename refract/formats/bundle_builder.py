"""Synthesise new .prism bundles from scratch (data tables and info sheets).

Every field and default comes from documents Prism wrote (local corpus) or
from prismbinder docs/format. Nothing is copied from a GraphPad file. The
experiments E1/E2 test whether Prism accepts what this writes.

Entry order follows Prism-written files:
info/ -> document.json -> data/ -> data/sheets/ -> data/sets/ -> data/tables/
"""

from __future__ import annotations

import datetime as _dt
import math
import random
import re
import uuid
from dataclasses import dataclass, field

from . import prismjson
from .zipio import ZipArchive

Value = float | int | str | None

SUBCOLS = {"y_single": 1, "y_sd_n": 3, "y_sd": 2, "y_se": 2, "y_high_low": 3}
TABLE_CLASS = {"xy": "XYDataTable", "survival": "XYDataTable"}
DS_SCHEMA = "sheets/data_sheet/data_table/data_set.schema.json"


_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_rng = random.Random()


def set_seed(seed: int | str | None) -> None:
    """Make UIDs and revision tokens reproducible (probe generation, tests)."""
    _rng.seed(seed)


def new_uid() -> str:
    return str(uuid.UUID(int=_rng.getrandbits(128), version=4)).upper()


def new_token() -> str:
    """32 lowercase hex chars, the shape of data.dt / parameters.dt."""
    return uuid.UUID(int=_rng.getrandbits(128), version=4).hex


class Num(str):
    """A number cell kept as the text it was typed as: written unchanged and
    counted as numeric (the document model never routes cells through floats)."""


def fmt_cell(v: Value) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return ""
    if isinstance(v, Num):
        return str(v)
    if isinstance(v, bool):
        raise TypeError("bool is not a Prism cell value")
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        v = float(v)  # numpy floats subclass float but repr as "np.float64(...)"
        return str(int(v)) if v.is_integer() and abs(v) < 1e15 else repr(v)
    s = str(v)
    if any(c in s for c in ',"\n\r'):
        s = '"' + s.replace('"', '""') + '"'
    return s


def decimals_of(values: list[Value]) -> int:
    """decimalsLength Prism uses for display: digits after the point (max 15)."""
    best = 0
    for v in values:
        t = fmt_cell(v)
        if t and (not isinstance(v, str) or isinstance(v, Num)) and "." in t and "e" not in t.lower():
            best = max(best, len(t.split(".")[1]))
    return min(best, 15)


def _span(values: list[Value]) -> tuple[int, int]:
    rows = [i for i, v in enumerate(values) if fmt_cell(v) != ""]
    return (rows[0], rows[-1]) if rows else (-1, -1)


@dataclass
class DataSet:
    title: str
    subcolumns: list[list[Value]]  # one list of row values per subcolumn
    decimals: int | None = None  # display decimals; None: from the values (decimals_of)
    variable: dict | None = None  # Multiple variables: model DataSet.variable (type, manual, categories)


@dataclass
class TableSpec:
    title: str
    kind: str  # column | grouped | xy | parts_of_whole | survival (X = time, Y = event codes per group)
    data_format: str = "y_single"  # y_single | y_replicates | y_sd_n
    datasets: list[DataSet] = field(default_factory=list)
    row_titles: list[str] | None = None
    x_title: str | None = None
    x_values: list[Value] | None = None
    replicates: int = 1
    x_decimals: int | None = None  # as DataSet.decimals

    @property
    def n_rows(self) -> int:
        cols = [sc for d in self.datasets for sc in d.subcolumns]
        if self.row_titles:
            cols.append(self.row_titles)
        if self.x_values:
            cols.append(self.x_values)
        return max((len(c) for c in cols), default=0)

    def subcols_per_dataset(self) -> int:
        return self.replicates if self.data_format == "y_replicates" else SUBCOLS[self.data_format]


def _replicate(values: list[Value], value_type: str = "real", attrs: list[str] | None = None,
               decimals: int | None = None, extra: dict | None = None) -> dict:
    """decimals=None omits decimalsLength. Prism then displays 0 decimals (E2)."""
    r: dict = {"@class": "DriverReplicate", "valueType": value_type, "commonAttributes": attrs or ["NUMERIC"]}
    if decimals is not None:
        r["decimalsLength"] = decimals
    r["significantDigitsCount"] = 7
    if extra:
        r.update(extra)
    first, last = _span(values)
    r["lastRow"] = last
    r["firstRow"] = first
    return r


def _is_text(v: Value) -> bool:
    return isinstance(v, str) and not isinstance(v, Num) and v != ""


def _variable_set(values: list[Value], decimals: int | None = None, variable: dict | None = None) -> dict:
    """VariableDataSet fields of a multiple-variables column (layout of a
    Prism-saved table). Without a given type: numeric values give a
    continuous variable, text a categorical one. A given type (from a .pzfx)
    is kept: categorical (numbers allowed, its categories' ids and order kept,
    usage recounted), label, continuous, and whether it was set by hand."""
    texts = [v for v in values if _is_text(v)]
    nums = [v for v in values if (isinstance(v, Num) or (isinstance(v, (int, float)) and not isinstance(v, bool)))
            and fmt_cell(v) != ""]
    ints = sum(1 for v in nums if float(v).is_integer())
    typ = (variable or {}).get("type") or ("categorical" if texts else "continuous")
    if typ == "continuous" and texts:
        typ = "categorical"
    if typ != "continuous":
        dec = None
    elif decimals is not None:
        dec = decimals
    else:  # the decimals typed (without decimalsLength Prism shows none, E2); integers only: left out
        dec = decimals_of(nums) if ints < len(nums) else None
    out: dict = {"@class": "VariableDataSet", "replicates": [_replicate(values, "real", ["NUMERIC"], dec)]}
    if typ == "categorical":
        given = (variable or {}).get("categories") or []
        names = [fmt_cell(v) for v in values]
        used: dict[str, dict] = {}
        for i, nm in enumerate(names):
            if nm == "":
                continue
            if nm in used:
                used[nm]["usageCount"] += 1
            else:
                used[nm] = {"firstRowIndex": i, "usageCount": 1, "name": nm}
        ids = {nm: cid for cid, nm in given if nm in used}
        free = max([cid for cid, _ in given] + [-1]) + 1
        order = [nm for _, nm in given if nm in used] + [nm for nm in used if nm not in ids]
        cats = []
        for nm in order:
            if nm not in ids:
                ids[nm], free = free, free + 1
            cats.append({"id": ids[nm], **used[nm]})
        cats.sort(key=lambda c: c["name"])  # Prism lists them by name (every Prism-saved file)
        out.update({"currentType": "categorical"})
    else:
        out.update({"currentType": typ})
    if (variable or {}).get("manual"):
        out["isManual"] = True
    out.update({"realsCount": len(nums) - ints, "integersCount": ints, "textsCount": len(texts)})
    if typ == "categorical":
        out.update({"categories": cats, "levelsOrder": {"type": "entry", "direction": "ascending"}})
    return out


class BundleBuilder:
    def __init__(self, creator_name: str = "Refract", creator_version: str = "0.0.1", full_ui: bool = False):
        self.creator = {"name": creator_name, "user": "", "version": creator_version, "platform": "Mac"}
        self.full_ui = full_ui
        self.tables: list[TableSpec] = []
        self.info_title: str | None = None
        self.info_constants: list[tuple[str, str]] | None = None
        self.info_notes = ""

    def add_table(self, t: TableSpec) -> None:
        self.tables.append(t)

    def add_info(self, title: str = "Project info 1", constants: list[tuple[str, str]] | None = None,
                 notes: str = "") -> None:
        """The project's info sheet: its title, (name, value) constants (default:
        Prism's six, empty) and notes as plain text."""
        self.info_title = title
        self.info_constants = list(constants) if constants is not None else None
        self.info_notes = notes

    # ------------------------------------------------------------------
    def build(self) -> ZipArchive:
        now = _dt.datetime.now(_dt.UTC).replace(microsecond=0)
        ts = (now.year, now.month, now.day, now.hour, now.minute, now.second)
        arc = ZipArchive.new()
        fen = 0
        sheets_data: list[str] = []
        attr_map: dict[str, dict] = {}
        files: dict[str, bytes] = {}
        info_uid = None

        if self.info_title:
            info_uid = new_uid()
            files[f"info/{info_uid}/sheet.json"] = prismjson.dumps(self._info_sheet(info_uid, now))
            attr_map[info_uid] = {"title": self.info_title}

        sheet_files: dict[str, bytes] = {}
        set_files: dict[str, bytes] = {}
        table_files: dict[str, bytes] = {}
        for si, t in enumerate(self.tables):
            sheet_uid, groups, fen = table_entries(t, si, fen)
            for target, g in zip((sheet_files, set_files, table_files), groups, strict=True):
                target.update(g)
            sheets_data.append(sheet_uid)
            attr_map[sheet_uid] = {"title": t.title}

        doc = {
            "@class": "Document", "$id": "document.schema.json",
            "creationDate": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "modificationDate": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "createdBy": dict(self.creator), "modifiedBy": dict(self.creator),
            "formatVersion": "1-6-0", "minFormatVersion": "1-2-0", "minPrismVersion": "10.1.0",
            "compatibility": [{"formatVersion": "1-0-0", "action": "warningOpen"}],
            "sheets": ({"info": [info_uid]} if info_uid else {}) | {"data": sheets_data},
            "uiSettings": self._ui(sheets_data, info_uid),
            "sheetAttributesMap": attr_map,
        }

        def put(name: str, data: bytes) -> None:
            parts = name.split("/")[:-1]
            for i in range(1, len(parts) + 1):
                d = "/".join(parts[:i]) + "/"
                if not arc.has(d):
                    arc.add(d, timestamp=ts)
            arc.add(name, data, timestamp=ts)

        for n, b in files.items():
            put(n, b)
        put("document.json", prismjson.dumps(doc))
        if not arc.has("data/"):
            arc.add("data/", timestamp=ts)
        for group in (sheet_files, set_files, table_files):
            for n, b in group.items():
                put(n, b)
        return arc

    def _ui(self, data_uids: list[str], info_uid: str | None) -> dict:
        ui: dict = {"currentSheetType": "Data", "viewMode": "sheet", "nextDataSheetNumber": len(data_uids) + 1}
        if self.full_ui:
            ui["printer"] = {"defaultPaperSize": {"width": 8.5, "height": 11.0}, "deviceName": "", "driverVersion": 0,
                             "specVersion": 0, "driverExtra": 0, "orientation": 1, "paperLength": 2794,
                             "paperWidth": 2159, "scale": 100, "copies": 1, "defaultSource": 7,
                             "printQuality": 72, "color": 1, "y_resolution": 72, "collate": 1}
            ui["navigator"] = {"width": 240, "sheetsPaneFraction": 50, "collapsedFolders": {
                k: False for k in ("data", "info", "analyses", "graphs", "layouts", "dataAndAnalyses", "search", "family")}}
        cur: dict = {}
        if data_uids:
            cur["data"] = data_uids[0]
        if info_uid:
            cur["info"] = info_uid
        ui["currentSheets"] = cur
        return ui

    def _info_sheet(self, uid: str, now: _dt.datetime) -> dict:
        consts = self.info_constants
        if consts is None:
            consts = [(n, "") for n in ("Experiment Date", "Experiment ID", "Notebook ID", "Project", "Experimenter",
                                        "Protocol")]
        date = next((v for n, v in consts if n == "Experiment Date" and _ISO_DATE.fullmatch(v or "")), None)
        return {
            "@class": "InfoSheet", "$id": "sheets/info_sheet/info_sheet.schema.json", "uid": uid, "fenID": 0,
            "title": self.info_title, "experimentDate": date or now.strftime("%Y-%m-%d"), "notesText": self.info_notes,
            "uiState": {"columnNamesWidth": 0.5, "columnValuesWidth": 0.5, "constantPanelProportion": 0.4},
            "selectedCellsRange": {"endCell": {"row": 0, "column": 0}, "startCell": {"row": 0, "column": 0}},
            "constants": [{"name": n, "value": v} for n, v in consts] + [{"name": "", "value": ""}],
        }


def table_entries(t: TableSpec, sheet_fen: int, fen: int) -> tuple[str, tuple[dict, dict, dict], int]:
    """The bundle entries of one data table: (sheet uid, (sheet files, data
    set files, table files), next free fenID)."""
    si = sheet_fen
    sheet_files: dict[str, bytes] = {}
    set_files: dict[str, bytes] = {}
    table_files: dict[str, bytes] = {}
    sheet_uid, table_uid = new_uid(), new_uid()
    n_rows = t.n_rows
    table: dict = {
        "@class": TABLE_CLASS.get(t.kind, "DataTable"),
        "$id": "sheets/data_sheet/data_table/data_table.schema.json",
        "uid": table_uid,
        "format": t.kind,
        "dataFormat": t.data_format,
    }
    if t.data_format == "y_replicates":
        table["replicatesCount"] = t.replicates
    csv_cols: list[list[Value]] = []
    if t.row_titles is not None:
        uid = new_uid()
        table["rowTitlesDataSet"] = uid
        set_files[f"data/sets/{uid}.json"] = prismjson.dumps({
            "@class": "DataSet", "$id": DS_SCHEMA, "uid": uid, "fenID": fen, "format": "text",
            "attributes": ["DS_ATTR_RT"],
            "replicates": [_replicate(list(t.row_titles), "string", ["NUMERIC"], 15)],
        })
        fen += 1
        csv_cols.append(list(t.row_titles))
    x_uid = None
    if t.kind in ("xy", "survival"):
        x_uid = new_uid()
        xs = list(t.x_values or [])
        xset = {"@class": "DataSet", "$id": DS_SCHEMA, "uid": x_uid, "fenID": fen, "format": "y_single"}
        if t.x_title:
            xset["title"] = t.x_title
        xset["attributes"] = ["DS_ATTR_X"]
        xdec = t.x_decimals if t.x_decimals is not None else decimals_of(xs)
        xset["replicates"] = [_replicate(xs, "real", ["NUMERIC", "NOTCONV"], xdec)]
        set_files[f"data/sets/{x_uid}.json"] = prismjson.dumps(xset)
        fen += 1
        csv_cols.append(xs)
    ds_uids = []
    k = t.subcols_per_dataset()
    for d in t.datasets:
        if len(d.subcolumns) != k:
            raise ValueError(f"{t.title}/{d.title}: expected {k} subcolumns, got {len(d.subcolumns)}")
        uid = new_uid()
        ds_uids.append(uid)
        ds = dataset_json(t.kind, t.data_format, k, d, n_rows, uid, fen)
        fen += 1
        set_files[f"data/sets/{uid}.json"] = prismjson.dumps(ds)
        csv_cols.extend(d.subcolumns)
    table["dataSets"] = ds_uids
    if t.kind == "nested":  # subcolumn titles (Prism writes one per nested subcolumn)
        st_uid = new_uid()
        titles = [{"column": c, "replicates": [
            {"replicate": r, "name": {"string": f"{d.title} {r + 1}", "version": 1}}
            for r in range(len(d.subcolumns))]} for c, d in enumerate(t.datasets)]
        set_files[f"data/sets/{st_uid}.json"] = prismjson.dumps({
            "@class": "SubColumnTitlesDataSet", "$id": DS_SCHEMA, "uid": st_uid, "fenID": fen,
            "format": "text_replicates", "replicate count": t.replicates, "titles": titles})
        fen += 1
        table = {**{k: v for k, v in table.items() if k != "dataSets"}, "subcolumnTitlesDataSet": st_uid,
                 "dataSets": ds_uids}
    if x_uid:
        table["xDataSetFormat"] = "y_single"
        table["xDataSet"] = x_uid

    sheet = {
        "@class": "DataSheet", "$id": "sheets/data_sheet/data_sheet.schema.json",
        "uid": sheet_uid, "fenID": si, "title": t.title, "isCustomTitle": True, "table": table,
        "font": {"family": "Arial", "size": 12.0},
        "titleWidth": 60, "xSubColWidth": 60, "maxDataSets": 2048, "maxRow": 500000,
        "selectionRange": {"startCell": {"row": 0, "column": 0, "subcolumn": 0},
                           "endCell": {"row": 0, "column": 0, "subcolumn": 0}},
        "anchorRow": 0, "anchorColumn": 0, "firstSubColumn": 0,
        "rowTitlesWidth": 114, "subColumnTitleType": "default",
    }
    sheet_files[f"data/sheets/{sheet_uid}/sheet.json"] = prismjson.dumps(sheet)
    rows = []
    for i in range(n_rows):
        rows.append(",".join(fmt_cell(c[i] if i < len(c) else None) for c in csv_cols))
    csv = ("\n".join(rows) + "\n").encode("utf-8") if rows else b""
    if t.kind == "multivariable":
        sheet["flags"] = ["HIDE_ROW_TITLES"]
    elif t.kind == "nested":
        sheet["flags"] = ["DATASETS_USES_OWN_TITLES", "HIDE_ROW_TITLES"]
    table_files[f"data/tables/{table_uid}/content.json"] = prismjson.dumps_storage({
        "$id": "sheets/data_sheet/data_table/data_table_storage.schema.json",
        "numberOfColumns": len(csv_cols), "numberOfRows": n_rows,
        "version": 1 if t.kind == "multivariable" else 6})
    table_files[f"data/tables/{table_uid}/data.csv"] = csv
    table_files[f"data/tables/{table_uid}/data.dt"] = new_token().encode()
    return sheet_uid, (sheet_files, set_files, table_files), fen


def dataset_json(kind: str, data_format: str, k: int, d: DataSet, n_rows: int, uid: str, fen: int) -> dict:
    """The data/sets JSON of one Y data set (k subcolumns per data set)."""
    ds = {"@class": "DataSet", "$id": DS_SCHEMA, "uid": uid, "fenID": fen, "format": data_format,
          "title": d.title, "attributes": ["DS_ATTR_Y"]}

    def dec(sc: list[Value]) -> int:
        return d.decimals if d.decimals is not None else decimals_of(sc)

    if data_format == "y_replicates":
        union = [next((sc[i] for sc in d.subcolumns if i < len(sc) and fmt_cell(sc[i]) != ""), None)
                 for i in range(n_rows)]
        dec_ = d.decimals if d.decimals is not None else max((decimals_of(sc) for sc in d.subcolumns), default=0)
        ds["replicate ranges"] = [{"range": f"0~{k - 1}" if k > 1 else "0",
                                   "replicate": _replicate(union, decimals=dec_)}]
    elif data_format == "y_sd_n":
        mean, sd, n = d.subcolumns
        ds["replicates"] = [
            _replicate(mean, decimals=dec(mean)),
            _replicate(sd, "real", ["POSITIVE", "NUMERIC"], dec(sd)),
            _replicate(n, "int", ["INTEGER", "POSITIVE", "NUMERIC"], 15),
        ]
    elif data_format in ("y_sd", "y_se"):  # mean, then SD or SEM (Prism's own sets)
        mean, err = d.subcolumns
        ds["replicates"] = [_replicate(mean, decimals=dec(mean)),
                            _replicate(err, "real", ["POSITIVE", "NUMERIC"], dec(err))]
    elif data_format == "y_high_low":  # mean, plus (high), minus (low) as Prism writes them
        ds["replicates"] = [_replicate(d.subcolumns[0], decimals=dec(d.subcolumns[0])),
                            _replicate(d.subcolumns[1], "real", ["NUMERIC", "USER"], dec(d.subcolumns[1])),
                            _replicate(d.subcolumns[2], decimals=dec(d.subcolumns[2]))]
    elif kind == "multivariable":  # one variable per data set: continuous or categorical text
        ds.update(_variable_set(d.subcolumns[0], d.decimals, d.variable))
    else:
        ds["replicates"] = [_replicate(sc, decimals=dec(sc)) for sc in d.subcolumns]
    return ds


def next_set_fen(arc: ZipArchive) -> int:
    import json as _json

    return max((_json.loads(arc.read(n)).get("fenID", -1) for n in arc.names()
                if n.startswith("data/sets/") and n.endswith(".json")), default=-1) + 1


# ------------------------------------------------- tables in an existing bundle
def _put(arc: ZipArchive, name: str, data: bytes) -> None:
    parts = name.split("/")[:-1]
    for i in range(1, len(parts) + 1):
        d = "/".join(parts[:i]) + "/"
        if not arc.has(d):
            arc.add(d)
    arc.put(name, data) if arc.has(name) else arc.add(name, data)


def insert_table(arc: ZipArchive, t: TableSpec) -> str:
    """Add a data table to an existing bundle, after its other data tables.
    fenIDs continue after the largest in use (data sheets including result
    tables; data sets). Returns the new sheet uid."""
    import json as _json

    # every data sheet counts, also analysis result tables (they are not listed
    # in document.json but share the fenID range; a clash makes Prism drop the
    # new table: E-new-tables)
    sheet_fens = [_json.loads(arc.read(n)).get("fenID", -1) for n in arc.names()
                  if n.startswith("data/sheets/") and n.endswith("/sheet.json")]
    set_fens = [_json.loads(arc.read(n)).get("fenID", -1) for n in arc.names()
                if n.startswith("data/sets/") and n.endswith(".json")]
    sheet_uid, groups, _fen = table_entries(t, max(sheet_fens, default=-1) + 1, max(set_fens, default=-1) + 1)
    for g in groups:
        for n, b in g.items():
            _put(arc, n, b)

    def upd(d: dict) -> None:
        sheets = d.setdefault("sheets", {})
        if "data" not in sheets:  # Prism's key order: info, data, ...
            d["sheets"] = {**({"info": sheets["info"]} if "info" in sheets else {}), "data": [],
                           **{k: v for k, v in sheets.items() if k != "info"}}
        d["sheets"]["data"].append(sheet_uid)
        d.setdefault("sheetAttributesMap", {})[sheet_uid] = {"title": t.title}
        ui = d.get("uiSettings")
        if isinstance(ui, dict) and isinstance(ui.get("nextDataSheetNumber"), int):
            ui["nextDataSheetNumber"] += 1

    from . import bundle as _B

    _B.edit_json(arc, "document.json", upd)
    return sheet_uid


def remove_table(arc: ZipArchive, sheet_uid: str) -> None:
    """Remove a data table added earlier (nothing may refer to it)."""
    import json as _json

    from . import bundle as _B

    sheet = _json.loads(arc.read(f"data/sheets/{sheet_uid}/sheet.json"))
    tab = sheet.get("table", {})
    sets = [tab.get(k) for k in ("rowTitlesDataSet", "xDataSet", "subcolumnTitlesDataSet")] + list(tab.get("dataSets", []))
    gone = {f"data/sets/{u}.json" for u in sets if u}
    prefixes = (f"data/sheets/{sheet_uid}/", f"data/tables/{tab.get('uid')}/")
    for n in [n for n in arc.names() if n in gone or n.startswith(prefixes)]:
        arc.remove(n)

    def upd(d: dict) -> None:
        lst = d.get("sheets", {}).get("data", [])
        if sheet_uid in lst:
            lst.remove(sheet_uid)
        d.get("sheetAttributesMap", {}).pop(sheet_uid, None)
        cur = d.get("uiSettings", {}).get("currentSheets", {})
        if cur.get("data") == sheet_uid:
            if lst:
                cur["data"] = lst[0]
            else:
                cur.pop("data")

    _B.edit_json(arc, "document.json", upd)
