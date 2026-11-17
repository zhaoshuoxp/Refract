"""A survival analysis's result tables, written into a .prism bundle so a
survival graph can plot them (PLAN §2.4 level B; experiment E-survival).

Prism's survival graph does not plot the data table: it plots the
"Survival proportions" result table of a survival analysis. Result tables are
data sheets (data/sheets, data/tables, data/sets) that document.json does not
list; the analysis names them through its views (analyses/<uid>/result_sheets).
A Kaplan-Meier result table, as Prism writes it (batch5 sample):
  - XY table, X = every distinct time of any group (first row 0); each data
    set has a value on the rows of its own subjects' times and blanks elsewhere;
  - "Survival proportions": percent (or fraction) surviving, the first row 100;
    rows where subjects were censored carry the cell attribute CENSORED;
  - "# at risk", "# deaths/events", "# censored subjects": counts per time.
"""

from __future__ import annotations

import numpy as np

from ..model.document import DataTable
from ..stats.survival import _subjects, kaplan_meier
from . import bundle as B
from . import prismjson
from .bundle_builder import DataSet as SpecSet
from .bundle_builder import TableSpec, _put, new_uid, next_set_fen, table_entries
from .zipio import ZipArchive

# (view name, view index, shown in Prism's tab bar, what the table holds)
XY_VIEWS = [("Survival proportions", 0, False, "proportion"), ("# at risk", 1, True, "at_risk"),
            ("# deaths/events", 5, False, "events"), ("# censored subjects", 6, False, "censored")]


def km_columns(t: DataTable, event: float = 1, censor: float = 0, percent: bool = True):
    """Rows of the XY result tables: (times, {what: [column per data set]},
    censored rows per data set). Columns are lists of floats or None."""
    x = t.x_values()
    per = []
    for j in range(len(t.datasets)):
        tt, ee = _subjects(x, t.values(j, 0), event, censor)
        per.append({r[0]: r for r in kaplan_meier(np.asarray(tt, float), np.asarray(ee, int))} if len(tt) else {})
    times = sorted({0.0} | {u for p in per for u in p})
    scale = 100.0 if percent else 1.0
    cols: dict[str, list[list]] = {k: [] for _n, _i, _v, k in XY_VIEWS}
    censored: list[list[int]] = []
    for p in per:
        n0 = max((r[1] for r in p.values()), default=0)
        prop, risk, ev, cen, marks = [], [], [], [], []
        for i, u in enumerate(times):
            if u == 0.0 and u not in p:
                prop.append(scale)
                risk.append(n0)
                ev.append(0)
                cen.append(0)
                continue
            r = p.get(u)
            if r is None:
                prop.append(None)
                risk.append(None)
                ev.append(None)
                cen.append(None)
                continue
            _u, n, d, c, s, _gw = r
            prop.append(scale * s)
            risk.append(n)
            ev.append(d)
            cen.append(c)
            if c:
                marks.append(i)
        cols["proportion"].append(prop)
        cols["at_risk"].append(risk)
        cols["events"].append(ev)
        cols["censored"].append(cen)
        censored.append(marks)
    return times, cols, censored


def _ranges(rows: list[int]) -> list[str]:
    """Row runs as Prism writes cell attributes: "4~5" (inclusive), "3"."""
    out: list[str] = []
    i = 0
    while i < len(rows):
        j = i
        while j + 1 < len(rows) and rows[j + 1] == rows[j] + 1:
            j += 1
        out.append(f"{rows[i]}~{rows[j]}" if j > i else f"{rows[i]}")
        i = j + 1
    return out


def _result_table(arc: ZipArchive, title: str, x_title: str | None, times, columns, names,
                  censored: list[list[int]] | None, percent: bool) -> tuple[str, int, list[str]]:
    """Add one XY result table; returns (sheet uid, sheet fen, Y data-set uids)."""
    sheet_fens = [B.get_json(arc, n).get("fenID", -1) for n in arc.names()
                  if n.startswith("data/sheets/") and n.endswith("/sheet.json")]
    fen = max(sheet_fens, default=-1) + 1
    spec = TableSpec(title, "xy", "y_single", [SpecSet(nm, [list(c)]) for nm, c in zip(names, columns, strict=True)],
                     x_title=x_title, x_values=list(times))
    sheet_uid, groups, _ = table_entries(spec, fen, next_set_fen(arc))
    sheet_files, set_files, table_files = groups
    name = f"data/sheets/{sheet_uid}/sheet.json"
    sheet = prismjson.loads(sheet_files[name])
    for k in ("isCustomTitle", "rowTitlesWidth"):
        sheet.pop(k, None)
    sheet["isCollapsed"] = True
    sheet["flags"] = ["HIDE_ROW_TITLES", "ANALYSIS_VIEW"]
    sheet["selectionRange"] = {"startCell": {"row": 0, "column": -1, "subcolumn": 0},
                               "endCell": {"row": 0, "column": -1, "subcolumn": 0}}
    if percent:
        sheet["subColumnTitleType"] = "percentage"
    sheet_files[name] = prismjson.dumps(sheet)
    ys = sheet["table"]["dataSets"]
    for k, u in enumerate(ys):
        n = f"data/sets/{u}.json"
        j = prismjson.loads(set_files[n])
        rep = j["replicates"][0]
        rep["decimalsLength"] = 3
        if censored and censored[k]:
            rep["cellAttributes"] = [{"rows": r, "attributes": ["CENSORED"]} for r in _ranges(censored[k])]
        set_files[n] = prismjson.dumps(j)
    for g in (sheet_files, set_files, table_files):
        for n, b in g.items():
            _put(arc, n, b)
    return sheet_uid, fen, ys


def add_result_tables(arc: ZipArchive, analysis_uid: str, t: DataTable, views=None, empty: bool = False,
                      percent: bool = True) -> dict[str, tuple[str, int, list[str]]]:
    """Write the analysis's XY result tables and views (all four, or those
    named in `views`). Returns {view name: (sheet uid, sheet fen, Y set uids)}."""
    base = f"analyses/{analysis_uid}"
    sheet = B.get_json(arc, f"{base}/sheet.json")
    times, cols, censored = km_columns(t, percent=percent)
    names = [d.title or "" for d in t.datasets]
    x_title = t.x.title if t.x is not None else None
    out = {}
    for view, idx, visible, what in XY_VIEWS:
        if views is not None and view not in views:
            continue
        ts, cs = ([], [[] for _ in names]) if empty else (times, cols[what])
        uid_sheet, fen, ys = _result_table(arc, f"{sheet['title']}:{view}", x_title, ts, cs, names,
                                           None if empty or what != "proportion" else censored,
                                           percent and what == "proportion")
        vuid = new_uid()
        B.put_json(arc, f"{base}/result_sheets/{vuid}.json", {
            "@class": "AnalysisView", "uid": vuid, "$id": "analyses/view.schema.json", "dataSheet": uid_sheet,
            "name": view, "viewIdx": idx, "graphId": -1, "graphFlags": 0, "tabState": "AUTO",
            "isVisible": visible, "isInternal": False, "isColumnLabelsVisible": True, "isGraphData": False,
            "useGraphData": False})
        sheet["resultSheets"].append({"uid": vuid, "title": view})
        out[view] = (uid_sheet, fen, ys)
    first = sheet["resultSheets"][0]["uid"] if sheet["resultSheets"] else None
    if first:
        sheet.update(currentResultSheet=first, defaultResultSheet=first, preferredResultSheet=first)
    B.put_json(arc, f"{base}/sheet.json", sheet)
    return out


def add_companion(arc: ZipArchive, t: DataTable, title: str | None = None) -> tuple[str, str]:
    """A survival analysis of the table (Prism's default parameters) with its
    Survival proportions table, for a survival graph to plot: Prism keeps the
    table (same uid), adds the other result views and recomputes the values
    when it shows the graph or the results (E-survival). Returns (analysis
    uid, Survival proportions sheet uid)."""
    from ..stats import catalog
    from . import analysis_writer as AW

    doc = B.get_json(arc, "document.json")
    names = {v.get("title") for v in doc.get("sheetAttributesMap", {}).values()}
    base = title or f"Survival of {t.title}"
    title, n = base, 2
    while title in names:
        title, n = f"{base} ({n})", n + 1
    content = catalog.build(catalog.by_key("survival"), {})
    percent = content.get("calc", {}).get("probabilityAs", "PERCENTAGE") == "PERCENTAGE"
    uid = AW.add_analysis(arc, "SURVIVAL", content, t.sheet_uid, title=title)
    res = add_result_tables(arc, uid, t, views=["Survival proportions"], percent=percent)
    return uid, res["Survival proportions"][0]


def find_analysis(arc: ZipArchive, t: DataTable, exclude=()) -> tuple[str, str | None] | None:
    """A survival analysis of the table already in the bundle (the first in
    the document's order, other than `exclude`): (its uid, the data sheet of
    its "Survival proportions" view, or None when it has no such view yet)."""
    doc = B.get_json(arc, "document.json")
    for uid in doc["sheets"].get("analyses", []):
        name = f"analyses/{uid}/sheet.json"
        if uid in exclude or not arc.has(name):
            continue
        a = B.get_json(arc, name)
        if a.get("analysisClass") != "SURVIVAL" or [s.get("uid") for s in a.get("inputSheets", [])][:1] != [t.sheet_uid]:
            continue
        for r in a.get("resultSheets", []):
            view = f"analyses/{uid}/result_sheets/{r['uid']}.json"
            if arc.has(view) and B.get_json(arc, view).get("name") == "Survival proportions":
                sheet = B.get_json(arc, view).get("dataSheet")
                if sheet and arc.has(f"data/sheets/{sheet}/sheet.json"):
                    return uid, sheet
        return uid, None
    return None


def proportions_of(arc: ZipArchive, t: DataTable, exclude=()) -> tuple[str, str] | None:
    """The table's own survival analysis and the Survival proportions table a
    graph can plot; the table is added (Refract's Kaplan-Meier values, which
    Prism recomputes) when the analysis has none, e.g. one made in Refract."""
    found = find_analysis(arc, t, exclude)
    if found is None:
        return None
    uid, sheet = found
    if sheet is None:
        params = B.get_json(arc, f"analyses/{uid}/parameters.json") if arc.has(f"analyses/{uid}/parameters.json") else {}
        calc = (params.get("content") or params).get("calc", {}) if isinstance(params, dict) else {}
        percent = calc.get("probabilityAs", "PERCENTAGE") == "PERCENTAGE"
        sheet = add_result_tables(arc, uid, t, views=["Survival proportions"], percent=percent)["Survival proportions"][0]
    return uid, sheet


def remove_analysis(arc: ZipArchive, uid: str) -> None:
    """Remove an analysis with its result views and result tables (also the
    views Prism added when it re-saved the file)."""
    from . import analysis_writer as AW

    base = f"analyses/{uid}"
    for n in [n for n in arc.names() if n.startswith(f"{base}/result_sheets/") and n.endswith(".json")]:
        s = B.get_json(arc, n).get("dataSheet")
        name = f"data/sheets/{s}/sheet.json"
        if not s or not arc.has(name):
            continue
        tbl = B.get_json(arc, name).get("table", {})
        sets = [*tbl.get("dataSets", []), *(tbl.get(k) for k in ("xDataSet", "rowTitlesDataSet"))]
        for u in sets:
            if u and arc.has(f"data/sets/{u}.json"):
                arc.remove(f"data/sets/{u}.json")
        prefixes = (f"data/sheets/{s}/", f"data/tables/{tbl.get('uid')}/")
        for m in [m for m in arc.names() if m.startswith(prefixes)]:
            arc.remove(m)
    AW.remove_analysis(arc, uid)
