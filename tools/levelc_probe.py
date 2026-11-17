"""E-levelc: which chunks of a graph Prism needs, and which it rebuilds.

From a graph Refract wrote for Prism (seed + patch), one variant per chunk
tag with every chunk of that tag removed (a container with all it holds).
Prism opens, exports and re-saves each variant (tools/prism_auto.py); the
result per tag:
  kept     - the graph survives and is drawn as before (SSIM >= 0.98 to the
             unmodified graph's export)
  changed  - drawn, but differently
  lost     - Prism dropped the graph, or the file did not open
and whether Prism's re-save has the tag back (rebuilt).

Usage:
  .venv/bin/python tools/levelc_probe.py make <out_dir> [--kind column] [--only 0x0017,0x00db]
  .venv/bin/python -I tools/prism_auto.py <out_dir>/prism <out_dir>/v_*.prism
  .venv/bin/python tools/levelc_probe.py compare <out_dir>
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from refract.formats.pcff.walker import Chunk, parse, serialize, subtree_end
from refract.formats.zipio import ZipArchive


def without(ch: list[Chunk], tag: int) -> list[Chunk]:
    out, i = [], 0
    while i < len(ch):
        if ch[i].tag == tag and not ch[i].is_marker:
            i = subtree_end(ch, i)
            continue
        out.append(ch[i])
        i += 1
    return out


def make(out: str, kind: str, only: list[int] | None) -> int:
    from refract.model import templates as T
    from refract.render import qt
    from refract.ui.document import Document

    qt.ensure_app()
    os.makedirs(out, exist_ok=True)
    doc = Document.new()
    doc.add_table(T.make(kind, f"Probe {kind}", sample=True))
    base = os.path.join(out, "v_base.prism")
    doc.save(base)
    uid = doc.project.native_graphs[0].prism_uid
    blob = ZipArchive.open(base).read(f"graphs/{uid}/data.bin")
    ch = parse(blob)
    tags = sorted({c.tag for c in ch if not c.is_marker} - {0x8001})  # 0x8001: the whole graph
    if only:
        tags = [t for t in tags if t in only]
    for t in tags:
        z = ZipArchive.open(base)
        z.put(f"graphs/{uid}/data.bin", serialize(without(ch, t)))
        with open(os.path.join(out, f"v_{t:04x}.prism"), "wb") as f:
            f.write(z.to_bytes())
    with open(os.path.join(out, "cases.json"), "w") as f:
        json.dump({"kind": kind, "graph": uid, "tags": [f"{t:#06x}" for t in tags],
                   "counts": {f"{t:#06x}": sum(1 for c in ch if c.tag == t) for t in tags}}, f, indent=1)
    print(f"{len(tags)} variants + base in {out}")
    return 0


def compare(out: str) -> int:
    from image_compare import load_grey, ssim

    with open(os.path.join(out, "cases.json")) as f:
        cases = json.load(f)
    uid = cases["graph"]
    base_png = os.path.join(out, "prism", "v_base", "graph_1.png")
    ref = load_grey(base_png)
    rows, summary = [], collections.Counter()
    for t in cases["tags"]:
        d = os.path.join(out, "prism", f"v_{int(t, 16):04x}")
        png, res = os.path.join(d, "graph_1.png"), os.path.join(d, "resaved.prism")
        state, score, back = "lost", None, None
        if os.path.exists(res):
            z = ZipArchive.open(res)
            if z.has(f"graphs/{uid}/data.bin"):
                try:
                    back = sum(1 for c in parse(z.read(f"graphs/{uid}/data.bin")) if c.tag == int(t, 16))
                except ValueError as e:  # Prism wrote a blob the walker cannot frame
                    back = f"unframed ({e})"
                if os.path.exists(png):
                    score = ssim(load_grey(png, (ref.shape[1], ref.shape[0])), ref)
                    state = "kept" if score >= 0.98 else "changed"
        summary[state] += 1
        rows.append({"tag": t, "count": cases["counts"][t], "state": state, "ssim": score, "rebuilt": back})
        print(f"  {t} x{cases['counts'][t]:<3d} {state:8s} ssim {score if score is None else round(score, 3)}"
              f"  in re-save: {back}")
    with open(os.path.join(out, "rows.json"), "w") as f:
        json.dump(rows, f, indent=1)
    print(dict(summary))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["make", "compare"])
    ap.add_argument("out")
    ap.add_argument("--kind", default="column")
    ap.add_argument("--only", default="")
    a = ap.parse_args()
    if a.cmd == "make":
        only = [int(x, 16) for x in a.only.split(",") if x] or None
        return make(a.out, a.kind, only)
    return compare(a.out)


if __name__ == "__main__":
    raise SystemExit(main())
