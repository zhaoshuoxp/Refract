"""Prism as oracle for analyses whose output is a data table (Normalize,
Transform, Remove baseline, Row statistics, Transpose, ...): run cases,
collect every result table of every analysis.

Library: run_tables(cases, out_dir) -> {case: {analysis title: {"results": content,
    "tables": {result sheet title: table}}}} with table = {"kind", "format", "x",
    "rows", "sets": [{"title", "subs"}]} (cells as Prism's stored text).
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import stats_oracle as O

from refract.formats.prism_reader import read_prism
from refract.formats.zipio import ZipArchive


def _table(t) -> dict:
    return {"kind": t.kind, "format": t.data_format, "n_rows": t.n_rows,
            "x": t.x.subcolumns if t.x is not None else None,
            "rows": t.row_titles.subcolumns[0] if t.row_titles is not None else None,
            "sets": [{"title": d.title, "subs": d.subcolumns} for d in t.datasets]}


def collect_tables(resaved: str) -> dict:
    z = ZipArchive.open(resaved)
    d = json.loads(z.read("document.json"))
    proj = read_prism(resaved, include_results=True)
    out = {}
    for a in d["sheets"].get("analyses", []):
        s = json.loads(z.read(f"analyses/{a}/sheet.json"))
        title = s["title"]
        try:
            res = json.loads(z.read(f"analyses/{a}/results.json")).get("content", {})
        except KeyError:
            res = {}
        tables = {}
        sheets = {r["uid"]: r["title"] for r in s.get("resultSheets", [])}
        for t in proj.tables:
            if t.is_result and t.sheet_uid in sheets:
                tables[sheets[t.sheet_uid]] = _table(t)
            elif t.is_result and t.title == title and sheets:
                tables[next(iter(sheets.values()))] = _table(t)
            elif t.is_result and t.title.startswith(title + ":"):
                tables[t.title[len(title) + 1:].strip()] = _table(t)
        out[title] = {"results": res, "tables": tables}
    return out


def run_tables(cases, out_dir: str, timeout: float = 30, reuse: bool = False) -> dict:
    path = os.path.join(out_dir, "tables.json")
    if reuse and os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    O.run(cases, out_dir, timeout=timeout)
    res = {}
    for c in cases:
        rs = os.path.join(out_dir, "prism", c.name, "resaved.prism")
        if os.path.exists(rs):
            res[c.name] = collect_tables(rs)
    with open(path, "w") as f:
        json.dump(res, f)
    return res


def num(cell: str):
    """Stored text -> float (None for blank)."""
    if cell is None or cell == "":
        return None
    try:
        return float(cell)
    except ValueError:
        return cell
