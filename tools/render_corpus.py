"""Render Prism documents' graphs from their files (refract.render.from_prism)
and compare each with Prism's own PDF export (SSIM, pdfium 300 dpi, top-left
aligned). Folders are prism_auto export folders: <dir>/resaved.prism (or
input.prism) plus graph_<n>.pdf in document order.

Usage: .venv/bin/python -I tools/render_corpus.py <folder-with-export-dirs> ... [--out DIR] [--json FILE]
"""

from __future__ import annotations

import argparse
import collections
import glob
import json
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import image_compare as IC

from refract.formats import open_document
from refract.formats.zipio import ZipArchive
from refract.render import from_prism, qt


def export_dirs(roots):
    for r in roots:
        cands = [r] if glob.glob(os.path.join(r, "graph_*.pdf")) else sorted(glob.glob(os.path.join(r, "*", "")))
        for d in cands:
            doc = next((os.path.join(d, n) for n in ("resaved.prism", "input.prism") if os.path.exists(os.path.join(d, n))), None)
            if doc and glob.glob(os.path.join(d, "graph_*.pdf")):
                yield d.rstrip("/"), doc


def run(roots, out_dir):
    rows = []
    for d, doc in export_dirs(roots):
        try:
            proj = open_document(doc)
            arc = ZipArchive.open(doc)
        except Exception as e:  # noqa: BLE001 - report and continue
            rows.append({"dir": d, "graph": None, "status": f"open: {e!r}"[:120]})
            continue
        for i, gs in enumerate(proj.graphs):
            ref = os.path.join(d, f"graph_{i + 1}.pdf")
            if not os.path.exists(ref):
                continue
            row = {"dir": os.path.basename(d), "graph": i + 1, "title": gs.title}
            try:
                g = from_prism.graph(proj, i, arc)
                row["family"] = g.family
                out = os.path.join(out_dir, f"{os.path.basename(d)}_{i + 1}.pdf")
                qt.to_pdf(g, out)
                row["ssim"] = round(IC.ssim_aligned(IC.pdf_grey(ref), IC.pdf_grey(out)), 4)
                row["status"] = "ok"
            except NotImplementedError as e:
                row["status"] = f"unsupported: {e}"[:120]
            except Exception as e:  # noqa: BLE001
                row["status"] = f"error: {e!r}"[:160]
                row["trace"] = traceback.format_exc(limit=3)[-400:]
            rows.append(row)
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("roots", nargs="+")
    ap.add_argument("--out", default="/tmp/refract_render_corpus")
    ap.add_argument("--json")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    rows = run(a.roots, a.out)
    ok = [r for r in rows if r.get("status") == "ok"]
    by = collections.defaultdict(list)
    for r in ok:
        by[r["family"]].append(r["ssim"])
    print(f"{len(rows)} graphs: {len(ok)} rendered")
    for fam, v in sorted(by.items()):
        v = sorted(v)
        print(f"   {fam:9s} n={len(v):3d}  median SSIM {v[len(v) // 2]:.3f}  min {v[0]:.3f}  max {v[-1]:.3f}")
    status = collections.Counter(r["status"].split(":")[0] if r.get("status") else "?" for r in rows if r.get("status") != "ok")
    print("   not rendered:", dict(status))
    if a.json:
        with open(a.json, "w") as f:
            json.dump(rows, f, indent=1)


if __name__ == "__main__":
    main()
