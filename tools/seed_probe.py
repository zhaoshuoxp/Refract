"""E-seed: Prism-made seed graphs transplanted into a Refract-made project
(refract.formats.graph_transplant) and bound to tables with as many, more or
fewer data sets than the seed's table.

Usage:
  .venv/bin/python tools/seed_probe.py make <out_dir> <seed.prism>
  .venv/bin/python -I tools/prism_auto.py <out_dir>/prism <out_dir>/seeded.prism
  .venv/bin/python tools/seed_probe.py compare <out_dir>
"""

from __future__ import annotations

import json
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

# (table kind, data sets wanted)
CASES = [("column", 3), ("column", 2), ("column", 5), ("grouped", 2), ("grouped", 3), ("grouped", 1), ("xy", 2),
         ("xy", 4), ("xy", 1)]  # survival graphs plot an analysis's results: not transplanted yet


def _seeds(seed_path: str):
    from refract.formats.graph_transplant import Seed
    from refract.formats.zipio import ZipArchive

    z = ZipArchive.open(seed_path)
    doc = json.loads(z.read("document.json"))
    out = {}
    for g in doc["sheets"]["graphs"]:
        s = Seed.from_bundle(z, g)
        out.setdefault(s.kind, s)
    return out


def make(out: str, seed_path: str) -> int:
    from refract.formats import graph_transplant as GT
    from refract.formats.zipio import ZipArchive
    from refract.model import templates as T
    from refract.render import qt
    from refract.ui.document import Document

    qt.ensure_app()
    os.makedirs(out, exist_ok=True)
    seeds = _seeds(seed_path)
    doc = Document.new()
    made = []
    for kind, n in CASES:
        t = doc.add_table(T.make(kind, f"{kind} {n}", sample=True), with_graph=False)
        while len(t.datasets) > n:
            doc.delete_datasets(t, [t.datasets[-1]])
        k = 0
        while len(t.datasets) < n:  # extra data sets: a copy of an existing one, shifted
            src = t.datasets[k % len(t.datasets)]
            ds = doc.add_dataset(t, title=f"Extra {len(t.datasets) + 1}")
            cells = [(ds, s, r, (f"{float(v) * 1.3 + 2:g}" if kind not in ("survival",) else v) if v else "")
                     for s, col in enumerate(src.subcolumns) for r, v in enumerate(col)]
            doc.set_cells(t, cells)
            k += 1
        made.append(t)
    plain = os.path.join(out, "plain.prism")
    doc.save(plain)
    arc = ZipArchive.open(plain)
    cases = []
    for t in made:
        seed = seeds.get(t.kind)
        uid = GT.transplant(arc, seed, t.sheet_uid, f"{t.title} graph")
        cases.append({"table": t.title, "graph": uid, "sets": len(t.datasets), "seed_sets": len(seed.y_fens)})
    path = os.path.join(out, "seeded.prism")
    arc.save(path)
    with open(os.path.join(out, "cases.json"), "w") as f:
        json.dump(cases, f, indent=1)
    print(path, len(cases), "graphs")
    return 0


def compare(out: str) -> int:
    from refract.formats import open_document
    from refract.formats.pcff import walker as W
    from refract.formats.zipio import ZipArchive

    with open(os.path.join(out, "cases.json")) as f:
        cases = json.load(f)
    resaved = os.path.join(out, "prism", "seeded", "resaved.prism")
    p = open_document(resaved)
    z = ZipArchive.open(resaved)
    doc = json.loads(z.read("document.json"))
    order = doc["sheets"].get("graphs", [])
    print("Prism kept", len(order), "of", len(cases), "graphs; warnings:", p.warnings[:2])
    for c in cases:
        if c["graph"] not in order:
            print(f"  DROPPED  {c['table']}")
            continue
        i = order.index(c["graph"]) + 1
        ch = W.parse(z.read(f"graphs/{c['graph']}/data.bin"))
        plots = sum(1 for x in ch if x.tag == 0x8028)
        gs = json.loads(z.read(f"graphs/{c['graph']}/sheet.json"))
        pdf = os.path.join(out, "prism", "seeded", f"graph_{i}.pdf")
        print(f"  {c['table']:12s} sets {c['sets']} (seed {c['seed_sets']}): Prism plots {plots}, inputs "
              f"{len(gs.get('inputDataSets', []))}, exported {os.path.exists(pdf)} graph_{i}")
    return 0


if __name__ == "__main__":
    if sys.argv[1] == "make":
        raise SystemExit(make(sys.argv[2], sys.argv[3]))
    raise SystemExit(compare(sys.argv[2]))
