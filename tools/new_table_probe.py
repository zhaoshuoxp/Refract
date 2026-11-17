"""E-new-tables: data tables made by the New Data Table dialog
(refract.model.templates + Document.add_table + save) must open in Prism with
the same cells, and analyses of them must compute.

Usage:
  .venv/bin/python tools/new_table_probe.py make <out_dir> <existing.prism>
  .venv/bin/python -I tools/prism_auto.py <out_dir>/prism <out_dir>/*.prism --no-png
  .venv/bin/python tools/new_table_probe.py compare <out_dir>
"""

from __future__ import annotations

import json
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

ANALYSES = {"column": ("one_way", {}), "grouped": ("two_way", {}), "xy": ("linear", {}),
            "survival": ("survival", {}), "contingency": ("contingency", {})}


def make(out: str, existing: str) -> int:
    from refract.formats import prism_writer as PW
    from refract.model import templates as T
    from refract.render import qt
    from refract.stats import catalog
    from refract.ui.document import Document

    qt.ensure_app()
    os.makedirs(out, exist_ok=True)
    cases = {}
    for name, doc in (("nt_new", Document.new()), ("nt_insert", Document.open(existing))):
        tables, analyses = [], []
        for k in T.KINDS:
            for fmt in k.formats:
                for sample in (True, False) if name == "nt_new" else (True,):
                    t = doc.add_table(T.make(k.key, f"{k.label} {fmt}{'' if sample else ' empty'}", fmt, 3, sample=sample))
                    tables.append(t.title)
                    if sample and k.key in ANALYSES and fmt == k.formats[0]:
                        key, values = ANALYSES[k.key]
                        analyses.append(doc.add_analysis(t, catalog.by_key(key), values).title)
        path = os.path.join(out, f"{name}.prism")
        doc.save(path)
        cases[path] = {"tables": {t: PW.table_grid(doc.project.table(t)) for t in tables}, "analyses": analyses}
        print(f"{path}: {len(tables)} tables, {len(analyses)} analyses")
    with open(os.path.join(out, "cases.json"), "w") as f:
        json.dump(cases, f)
    return 0


def compare(out: str) -> int:
    from refract.formats import open_document
    from refract.formats import prism_writer as PW
    from refract.stats import inputs as I

    with open(os.path.join(out, "cases.json")) as f:
        cases = json.load(f)
    bad = 0
    for path, c in cases.items():
        stem = os.path.splitext(os.path.basename(path))[0]
        resaved = os.path.join(out, "prism", stem, "resaved.prism")
        if not os.path.exists(resaved):
            print(f"{stem}: no re-save from Prism")
            bad += 1
            continue
        p = open_document(resaved)
        print(f"{stem}: Prism re-saved {len(p.tables)} tables, {len(p.analyses)} analyses")
        for title, grid in c["tables"].items():
            t = next((t for t in p.tables if t.title == title), None)
            ok = t is not None and PW.table_grid(t) == grid
            bad += not ok
            if not ok:
                print(f"  DIFF table {title}: {None if t is None else PW.table_grid(t)[:2]} vs {grid[:2]}")
        print(f"  tables identical after Prism's re-save: {sum(1 for _ in c['tables']) - bad}/{len(c['tables'])}")
        for title in c["analyses"]:
            a = next((a for a in p.analyses if a.title == title), None)
            if a is None:
                print(f"  MISSING analysis {title}")
                bad += 1
                continue
            stored = a.results.get("content") or {}
            d = [x for x in I.compare(stored, I.recompute(p, a)) if x.stored is not None and x.ours is not None]
            ag = sum(x.agrees for x in d)
            st = (stored.get("status") or {}).get("error")
            ok = st == "VALID" and d and ag == len(d)
            bad += not ok
            print(f"  {'ok ' if ok else 'DIFF'} {ag:4d}/{len(d):4d} status={st}  {title}")
    return 1 if bad else 0


if __name__ == "__main__":
    if sys.argv[1] == "make":
        raise SystemExit(make(sys.argv[2], sys.argv[3]))
    raise SystemExit(compare(sys.argv[2]))
