"""E-structure: data sets added, removed and renamed, and tables renamed in
Refract, saved into an existing .prism, must open in Prism as edited.

Usage:
  .venv/bin/python tools/structure_probe.py make <out_dir> <existing.prism>
  .venv/bin/python -I tools/prism_auto.py <out_dir>/prism <out_dir>/st_edit.prism --no-png
  .venv/bin/python tools/structure_probe.py compare <out_dir>
"""

from __future__ import annotations

import json
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))


def _shape(t):
    from refract.formats import prism_writer as PW

    return {"title": t.title, "sets": [d.title for d in t.datasets], "grid": PW.table_grid(t)}


def make(out: str, existing: str) -> int:
    from refract.render import qt
    from refract.ui.document import Document

    qt.ensure_app()
    os.makedirs(out, exist_ok=True)
    doc = Document.open(existing)
    kinds = {t.kind: t for t in doc.project.tables if not t.is_result}
    xy, col, grp = kinds["xy"], kinds["column"], kinds["grouped"]
    ds = doc.add_dataset(xy, title="Added")  # a new last data set with values
    for r in range(min(4, xy.n_rows)):
        for k in range(xy.subcolumns_per_dataset):
            doc.set_cell(xy, ds, k, r, f"{50 + 10 * r + k}.5")
    doc.rename_dataset(xy, xy.datasets[0], "Control (renamed)")
    doc.delete_datasets(col, [col.datasets[1]])  # the middle column
    doc.rename_table(col, "Column table renamed")
    first = doc.add_dataset(grp, at=0, title="Inserted first")
    doc.set_cell(grp, first, 0, 0, "7")
    path = os.path.join(out, "st_edit.prism")
    touched = doc.save(path)
    want = {t.title: _shape(t) for t in (xy, col, grp)}
    with open(os.path.join(out, "cases.json"), "w") as f:
        json.dump(want, f)
    print(path, len(touched), "entries rewritten")
    return 0


def compare(out: str) -> int:
    from refract.formats import open_document

    with open(os.path.join(out, "cases.json")) as f:
        want = json.load(f)
    mine = open_document(os.path.join(out, "st_edit.prism"))
    theirs = open_document(os.path.join(out, "prism", "st_edit", "resaved.prism"))
    bad = 0
    for title, w in want.items():
        for label, p in (("Refract", mine), ("Prism", theirs)):
            t = next((t for t in p.tables if t.title == title), None)
            ok = t is not None and _shape(t) == w
            bad += not ok
            print(f"  {'ok ' if ok else 'DIFF'} {label:7s} {title}: {None if t is None else [d.title for d in t.datasets]}")
            if t is not None and not ok:
                print("      ", _shape(t)["grid"][:2], "vs", w["grid"][:2])
    return 1 if bad else 0


if __name__ == "__main__":
    if sys.argv[1] == "make":
        raise SystemExit(make(sys.argv[2], sys.argv[3]))
    raise SystemExit(compare(sys.argv[2]))
