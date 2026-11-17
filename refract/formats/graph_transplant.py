"""Graphs written for Prism by "seed and patch" (PLAN §2.4 level B): a graph
Prism made (the seed, from another document) is copied into the target
bundle and bound to one of its data tables.

The copy uses the DuplicateFamily rules (refract.formats.graph_copy): every
document-wide id in the seed is renumbered above the target's maxima, the
graph gets a fresh fenID, and the seed's data-set fenIDs are mapped onto the
target table's (Y data sets in order, then row titles and X). The graph
sheet's `inputDataSets` names the target's data sets; Prism draws from them
(E6b). What happens when the table has more or fewer data sets than the seed
is settled by experiment E-seed (docs/experiments.md).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from . import bundle as B
from .bundle_builder import new_uid
from .graph_copy import _graph_blobs, doc_maxima, family_copy_blob
from .pcff import idmap
from .pcff.walker import serialize
from .zipio import ZipArchive

DELETED = 0xFFFD  # u16 form of fenID -3: a plot of a deleted data set (not drawn)
PIE = "parts_of_whole"  # a pie graph plots the first data set of its table, one slice per row (E-pie)


def is_pie(blob: bytes) -> bool:
    """A pie graph: its pie plot data block (0x80d6; 21 of 21 corpus pies).
    A parts-of-whole table can also be graphed as bars, which this rejects."""
    from .pcff.walker import parse

    return any(c.tag == 0x80D6 for c in parse(blob))


@dataclass
class Seed:
    """A seed graph: its blob and sheet, and the data-set fenIDs it plots."""

    blob: bytes
    sheet: dict
    y_fens: list[int]
    row_fen: int | None
    x_fen: int | None
    kind: str  # the plotted table's kind (column, grouped, xy, ...); survival: a survival analysis's
    # Survival proportions table (refract.formats.survival_writer); result: another result table

    @classmethod
    def from_bundle(cls, arc: ZipArchive, graph_uid: str) -> Seed:
        gs = B.get_json(arc, f"graphs/{graph_uid}/sheet.json")
        inputs = gs.get("inputDataSets", [])
        table, sheet = None, None
        for n in arc.names():  # data tables and analysis result tables alike
            if n.startswith("data/sheets/") and n.endswith("/sheet.json"):
                sheet = B.get_json(arc, n)
                t = sheet.get("table", {})
                if inputs and inputs[0] in t.get("dataSets", []):
                    table = t
                    break
        if table is None:
            raise ValueError("the seed graph's data table was not found")
        kind = table.get("format", "")
        if "ANALYSIS_VIEW" in sheet.get("flags", []):  # it plots a result table: of which analysis?
            kind = "result"
            for n in arc.names():
                if "/result_sheets/" in n and n.endswith(".json") and \
                        B.get_json(arc, n).get("dataSheet") == sheet["uid"]:
                    a = B.get_json(arc, n.split("/result_sheets/")[0] + "/sheet.json")
                    if a.get("analysisClass") == "SURVIVAL" and B.get_json(arc, n).get("name") == \
                            "Survival proportions":
                        kind = "survival"  # Prism's survival graph: the Survival proportions table

        def fen(uid):
            return B.get_json(arc, f"data/sets/{uid}.json")["fenID"] if uid else None

        # a pie plots one data set (the one its sheet names), not every data set of its table
        ys = [u for u in inputs if u in table["dataSets"]][:1] if kind == PIE else table["dataSets"]
        return cls(arc.read(f"graphs/{graph_uid}/data.bin"), gs, [fen(u) for u in ys],
                   fen(table.get("rowTitlesDataSet")), fen(table.get("xDataSet")), kind)


def transplant(arc: ZipArchive, seed: Seed, data_sheet_uid: str, title: str,
               extra: str = "deleted", patch=None) -> str:
    """Add a copy of the seed graph to the bundle, plotting the table's data
    sets. `extra` says what becomes of seed plots beyond the table's data sets:
    "deleted" binds them to the deleted marker. Returns the new graph uid."""
    doc = B.get_json(arc, "document.json")
    t = B.get_json(arc, f"data/sheets/{data_sheet_uid}/sheet.json")["table"]

    def fen(uid):
        return B.get_json(arc, f"data/sets/{uid}.json")["fenID"] if uid else None

    ys = list(t.get("dataSets", []))
    if seed.kind == PIE:
        ys = ys[:1]
    fen_map: dict[int, int] = {}
    for i, f in enumerate(seed.y_fens):
        if i < len(ys):
            fen_map[f] = fen(ys[i])
        elif extra == "deleted":
            fen_map[f] = DELETED
    for f, role in ((seed.row_fen, "rowTitlesDataSet"), (seed.x_fen, "xDataSet")):
        if f is not None and t.get(role):
            fen_map[f] = fen(t[role])
    gfens = [B.get_json(arc, f"graphs/{g}/sheet.json")["fenID"] for g in doc["sheets"].get("graphs", [])
             if arc.has(f"graphs/{g}/sheet.json")]
    gfen = max(gfens, default=-1) + 2
    maxima = doc_maxima(_graph_blobs(arc, doc) + [seed.blob])
    ch = family_copy_blob(seed.blob, maxima, fen_map, gfen)
    sheet_fen = B.get_json(arc, f"data/sheets/{data_sheet_uid}/sheet.json")["fenID"]
    for c in ch:  # 0x0014: the sheet fenIDs of the tables the graph plots (2098 of 2145 corpus graphs)
        if c.tag == 0x0014 and c.payload:
            c.payload = struct.pack("<II", 1, sheet_fen)
    idmap.set_graph_name(ch, title)
    idmap.new_instance_uuid(ch)
    if patch is not None:  # properties written into the copy (refract.formats.graph_patch)
        patch(ch)
    uid = new_uid()
    gs = dict(seed.sheet)
    gs.update(uid=uid, fenID=gfen, title=title, isCustomTitle=True, inputDataSets=ys)
    gs.pop("floatingNotes", None)
    gs.pop("isAutoCreated", None)
    B.put_json(arc, f"graphs/{uid}/sheet.json", gs)
    arc.put(f"graphs/{uid}/data.bin", serialize(ch))

    def upd(d):
        sheets = d["sheets"]
        if "graphs" not in sheets:  # Prism writes graphs first
            d["sheets"] = {"graphs": [], **sheets}
        d["sheets"]["graphs"].append(uid)
        d["sheetAttributesMap"][uid] = {"title": title}
    B.edit_json(arc, "document.json", upd)
    return uid


def remove_graph(arc: ZipArchive, uid: str) -> None:
    """Remove a graph sheet written earlier (and its layout links)."""
    for n in [n for n in arc.names() if n.startswith(f"graphs/{uid}/")]:
        arc.remove(n)

    def upd(d):
        lst = d["sheets"].get("graphs", [])
        if uid in lst:
            lst.remove(uid)
        d.get("sheetAttributesMap", {}).pop(uid, None)
    B.edit_json(arc, "document.json", upd)
    doc = B.get_json(arc, "document.json")
    for lay in doc["sheets"].get("layouts", []):
        name = f"layouts/{lay}/sheet.json"
        if arc.has(name) and uid in B.get_json(arc, name).get("linkedGraphSheets", []):
            B.edit_json(arc, name, lambda j: j.__setitem__("linkedGraphSheets",
                                                          [u for u in j["linkedGraphSheets"] if u != uid]))
