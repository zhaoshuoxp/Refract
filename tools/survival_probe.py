"""E-survival: Refract's survival graphs written as Prism graphs. A survival
graph plots the "Survival proportions" result table of a survival analysis,
so the analysis, its result tables (refract.formats.survival_writer) and the
graph (a seed, refract.formats.graph_transplant) are written together.

Variants (one file each):
  A_prop   the analysis with only its Survival proportions table, filled
  B_allxy  all four XY result tables, filled
  C_empty  the Survival proportions table with no rows (Prism to fill it)
Each file has a 2-group and a 3-group table (the seed plots 2).

Usage:
  .venv/bin/python tools/survival_probe.py make <out_dir> <seed.prism>
  .venv/bin/python -I tools/prism_auto.py <out_dir>/prism <out_dir>/A_prop.prism <out_dir>/B_allxy.prism <out_dir>/C_empty.prism
  .venv/bin/python tools/survival_probe.py compare <out_dir>
"""

from __future__ import annotations

import json
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

VARIANTS = {"A_prop": {"views": ["Survival proportions"]}, "B_allxy": {"views": None},
            "C_empty": {"views": ["Survival proportions"], "empty": True}}


def survival_seed(seed_path: str):
    from refract.formats.graph_transplant import Seed
    from refract.formats.zipio import ZipArchive

    z = ZipArchive.open(seed_path)
    for g in json.loads(z.read("document.json"))["sheets"]["graphs"]:
        s = Seed.from_bundle(z, g)
        for n in z.names():
            if n.startswith("data/sheets/") and n.endswith("/sheet.json"):
                j = json.loads(z.read(n))
                if j.get("title", "").endswith(":Survival proportions") and \
                        s.sheet["inputDataSets"][0] in j["table"]["dataSets"]:
                    return s
    raise SystemExit("no survival graph in the seed file")


def make(out: str, seed_path: str) -> int:
    from refract.formats import analysis_writer as AW
    from refract.formats import graph_transplant as GT
    from refract.formats import survival_writer as SW
    from refract.formats.zipio import ZipArchive
    from refract.model import templates as T
    from refract.render import qt
    from refract.stats import catalog
    from refract.ui.document import Document

    qt.ensure_app()
    os.makedirs(out, exist_ok=True)
    seed = survival_seed(seed_path)
    cases = {}
    for name, v in VARIANTS.items():
        doc = Document.new()
        tables = []
        for n in (2, 3):
            t = doc.add_table(T.make("survival", f"Surv {n}", sample=True), with_graph=False)
            if n == 3:
                ds = doc.add_dataset(t, title="Third")
                times = [(5, 1), (12, 1), (20, 0), (33, 1), (41, 1), (58, 1)]
                start = t.n_rows
                cells = [(t.x, 0, start + i, str(tm)) for i, (tm, _c) in enumerate(times)] + \
                        [(ds, 0, start + i, str(c)) for i, (_tm, c) in enumerate(times)]
                doc.set_cells(t, cells)
            tables.append(t)
        path = os.path.join(out, f"{name}.prism")
        doc.save(path)
        arc = ZipArchive.open(path)
        info = []
        for t in tables:
            title = f"Survival of {t.title}"
            a = AW.add_analysis(arc, "SURVIVAL", catalog.build(catalog.by_key("survival"), {}), t.sheet_uid,
                                title=title)
            res = SW.add_result_tables(arc, a, t, views=v["views"], empty=v.get("empty", False))
            sheet_uid, _fen, ys = res["Survival proportions"]
            g = GT.transplant(arc, seed, sheet_uid, t.title)
            info.append({"table": t.title, "sets": len(t.datasets), "analysis": a, "graph": g,
                         "views": {k: r[0] for k, r in res.items()}, "ys": ys})
        arc.save(path)
        cases[name] = info
        print(name, [(i["table"], i["graph"][:8]) for i in info])
    with open(os.path.join(out, "cases.json"), "w") as f:
        json.dump(cases, f, indent=1)
    return 0


def compare(out: str) -> int:
    from refract.formats.zipio import ZipArchive

    with open(os.path.join(out, "cases.json")) as f:
        cases = json.load(f)
    for name, info in cases.items():
        resaved = os.path.join(out, "prism", name, "resaved.prism")
        if not os.path.exists(resaved):
            print(name, "not re-saved")
            continue
        z = ZipArchive.open(resaved)
        doc = json.loads(z.read("document.json"))
        graphs = doc["sheets"].get("graphs", [])
        print(name)
        for k, c in enumerate(info):
            kept = c["graph"] in graphs
            line = f"  {c['table']}: graph kept {kept}"
            if kept:
                gs = json.loads(z.read(f"graphs/{c['graph']}/sheet.json"))
                line += f", inputs {len(gs.get('inputDataSets', []))} (sets {c['sets']}), same sets {gs.get('inputDataSets') == c['ys']}"
            a = f"analyses/{c['analysis']}/sheet.json"
            if z.has(a):
                s = json.loads(z.read(a))
                views = {r["title"]: r["uid"] for r in s.get("resultSheets", [])}
                kept_views = {v: (views.get(v) is not None) for v in c["views"]}
                sheets = {}
                for v, u in views.items():
                    j = json.loads(z.read(f"analyses/{c['analysis']}/result_sheets/{u}.json"))
                    sheets[v] = j["dataSheet"]
                same = {v: sheets.get(v) == c["views"][v] for v in c["views"]}
                line += f"; views {len(views)}, ours kept {kept_views}, same sheets {same}"
                sp = sheets.get("Survival proportions")
                if sp:
                    tb = json.loads(z.read(f"data/sheets/{sp}/sheet.json"))["table"]["uid"]
                    line += "\n    proportions: " + z.read(f"data/tables/{tb}/data.csv").decode()[:200].replace("\n", " | ")
            else:
                line += "; analysis gone"
            pdf = os.path.join(out, "prism", name, f"graph_{k + 1}.pdf")
            if os.path.exists(pdf):
                import pypdfium2 as pdfium

                d = pdfium.PdfDocument(pdf)
                line += "\n    graph text: " + d[0].get_textpage().get_text_range().replace("\r\n", " ")[:160]
            print(line)
    return 0


if __name__ == "__main__":
    cmd = sys.argv[1]
    raise SystemExit(make(*sys.argv[2:4]) if cmd == "make" else compare(sys.argv[2]))
