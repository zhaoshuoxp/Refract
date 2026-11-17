"""Refract's own graphs in a .prism bundle: the private entry
x-refract/graphs.json (Prism keeps unknown entries when it re-saves: E5).
Graphs name their table by its sheet uid."""

from __future__ import annotations

import json

from ..model.document import LayoutItem, NativeGraph, NativeLayout, Project
from .zipio import ZipArchive

ENTRY = "x-refract/graphs.json"
VERSION = 1


def read(arc: ZipArchive, project: Project) -> list[NativeGraph]:
    if not arc.has(ENTRY):
        return []
    try:
        j = json.loads(arc.read(ENTRY))
    except ValueError:
        project.warnings.append(f"{ENTRY}: not readable, Refract's graphs were skipped")
        return []
    by_uid = {t.sheet_uid: t for t in project.tables if t.sheet_uid}
    out = []
    for g in j.get("graphs", []):
        t = by_uid.get(g.get("table"))
        if t is None:
            project.warnings.append(f"Refract graph {g.get('title')!r}: its table is gone")
            continue
        fmt = g.get("format") if isinstance(g.get("format"), dict) else {}
        ng = NativeGraph(g.get("title", t.title), t, g.get("style", "default"), g.get("error", "sd"),
                         g.get("stars", "auto"), bool(g.get("show_ns", False)), fmt)
        if isinstance(g.get("options"), dict):
            ng.options = g["options"]
        if isinstance(g.get("uid"), str):
            ng.uid = g["uid"]
        if isinstance(g.get("prism"), dict):
            ng.prism_uid, ng.prism_sig = g["prism"].get("uid"), g["prism"].get("sig")
            ng.prism_analysis = g["prism"].get("analysis")
            if isinstance(g["prism"].get("base"), dict):
                ng.prism_base = g["prism"]["base"]
        out.append(ng)
    return out


def dumps(graphs: list[NativeGraph]) -> bytes:
    body = {"version": VERSION, "graphs": [
        {"title": g.title, "table": g.table.sheet_uid, "style": g.style, "error": g.error, "stars": g.stars,
         "show_ns": g.show_ns, **({"format": g.format} if g.format else {}),
         **({"options": g.options} if g.options else {}), "uid": g.uid,
         **({"prism": {"uid": g.prism_uid, "sig": g.prism_sig,
                       **({"analysis": g.prism_analysis} if g.prism_analysis else {}),
                       **({"base": g.prism_base} if g.prism_base else {})}} if g.prism_uid else {})}
        for g in graphs]}
    return (json.dumps(body, indent=1, ensure_ascii=False) + "\n").encode("utf-8")


def write(arc: ZipArchive, graphs: list[NativeGraph]) -> bool:
    """Store the graphs (remove the entry when there are none). True if the
    bundle changed."""
    if not graphs:
        if arc.has(ENTRY):
            arc.remove(ENTRY)
            return True
        return False
    data = dumps(graphs)
    if arc.has(ENTRY):
        if arc.read(ENTRY) == data:
            return False
        arc.put(ENTRY, data)
    else:
        if not arc.has("x-refract/"):
            arc.add("x-refract/")
        arc.add(ENTRY, data)
    return True


# ------------------------------------------------------------------ layouts
LAYOUTS = "x-refract/layouts.json"


def read_layouts(arc: ZipArchive, project: Project) -> list[NativeLayout]:
    if not arc.has(LAYOUTS):
        return []
    try:
        j = json.loads(arc.read(LAYOUTS))
    except ValueError:
        project.warnings.append(f"{LAYOUTS}: not readable, Refract's layouts were skipped")
        return []
    out = []
    for lay in j.get("layouts", []):
        items = [LayoutItem(str(i["graph"]), float(i["x"]), float(i["y"]), float(i["w"]), float(i["h"]))
                 for i in lay.get("items", []) if isinstance(i, dict) and "graph" in i]
        nl = NativeLayout(lay.get("title", "Layout"), float(lay.get("width", 612)), float(lay.get("height", 792)), items)
        if isinstance(lay.get("uid"), str):
            nl.uid = lay["uid"]
        out.append(nl)
    return out


def dumps_layouts(layouts: list[NativeLayout]) -> bytes:
    body = {"version": VERSION, "layouts": [
        {"title": lay.title, "width": lay.width, "height": lay.height, "uid": lay.uid,
         "items": [{"graph": i.graph, "x": round(i.x, 3), "y": round(i.y, 3), "w": round(i.w, 3), "h": round(i.h, 3)}
                   for i in lay.items]} for lay in layouts]}
    return (json.dumps(body, indent=1, ensure_ascii=False) + "\n").encode("utf-8")


def write_layouts(arc: ZipArchive, layouts: list[NativeLayout]) -> bool:
    return _write_entry(arc, LAYOUTS, dumps_layouts(layouts) if layouts else None)


def _write_entry(arc: ZipArchive, name: str, data: bytes | None) -> bool:
    if data is None:
        if arc.has(name):
            arc.remove(name)
            return True
        return False
    if arc.has(name):
        if arc.read(name) == data:
            return False
        arc.put(name, data)
    else:
        if not arc.has("x-refract/"):
            arc.add("x-refract/")
        arc.add(name, data)
    return True
