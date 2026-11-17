"""Learn Prism's automatic axis ranges by controlled data variants.

Takes a seed document whose first graph has auto axes, replaces the numbers
of the graph's data table with generated values (same shape), lets Prism
re-save every variant (prism_auto), and records what Prism wrote: the data
extent cache (0x0017) and the drawn range + major tick (0x8025).

Usage: .venv/bin/python -I tools/autoscale_probe.py <out_dir> <seed.prism> [--n 30] [--seed 1] [--reuse]
Writes <out_dir>/rows.json: [{variant, values, axis, dmin, dmax, lo, hi, tick}]
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from refract.formats import open_document
from refract.formats.pcff import fields as F
from refract.formats.pcff import walker
from refract.formats.prism_writer import save_project
from refract.formats.zipio import ZipArchive

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")


def graph_table(path: str, graph: int = 0):
    """(index of the data table feeding the graph, graph uid)."""
    z = ZipArchive.open(path)
    d = json.loads(z.read("document.json"))
    g = d["sheets"]["graphs"][graph]
    sets = set(json.loads(z.read(f"graphs/{g}/sheet.json")).get("inputDataSets", []))
    proj = open_document(path)
    for i, t in enumerate(proj.tables):
        if any(ds.uid in sets for ds in t.datasets):
            return i, g
    return None, g  # fed by an analysis (e.g. survival): pass --table


def variant_values(rnd: random.Random, n_cells: int) -> list[float]:
    scale = 10 ** rnd.uniform(-3, 6)
    kind = rnd.choice(["pos0", "pos_far", "pos_mid", "neg", "mixed", "tight"])
    if kind == "pos0":
        lo, hi = 0.0, scale
    elif kind == "pos_far":
        lo, hi = scale * rnd.uniform(0.55, 0.95), scale
    elif kind == "pos_mid":
        lo, hi = scale * rnd.uniform(0.2, 0.55), scale
    elif kind == "neg":
        lo, hi = -scale, -scale * rnd.uniform(0, 0.6)
    elif kind == "mixed":
        lo, hi = -scale * rnd.uniform(0.1, 1), scale
    else:
        lo, hi = scale * 0.999, scale
    vals = [rnd.uniform(lo, hi) for _ in range(n_cells)]
    digits = max(0, 4 - math.floor(math.log10(scale)))
    return [round(v, digits) for v in vals]


def axes_of(path: str, graph_uid: str) -> list[dict]:
    z = ZipArchive.open(path)
    ch = walker.parse(z.read(f"graphs/{graph_uid}/data.bin"))
    ax = [F.Axis.read(c) for c in F.axes(ch)]
    st = [F.AxisSettings.read(c) for c in F.axis_settings(ch)]
    md = [F.AxisMode.read(c) for c in F.axis_modes(ch)]
    out = []
    for i, name in ((0, "X"), (1, "Y")):
        out.append({"axis": name, "kind": F.graph_kind(ch), "dmin": ax[i].data_min, "dmax": ax[i].data_max,
                    "lo": st[3 * i].min, "hi": st[3 * i].max, "tick": st[3 * i].major_tick,
                    "log": st[3 * i].log10, "auto": (md[i].flags & 0xC) == 0})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("seed")
    ap.add_argument("--n", type=int, default=30)
    ap.add_argument("--seed", dest="rseed", type=int, default=1)
    ap.add_argument("--reuse", action="store_true")
    ap.add_argument("--png", action="store_true", help="also export graph PNGs")
    ap.add_argument("--vary-x", action="store_true", help="also replace the X column (own random scale)")
    ap.add_argument("--only-x", action="store_true", help="replace only the X column, with positive values (survival)")
    ap.add_argument("--table", type=int, help="index of the data table to vary (default: the one feeding the first graph)")
    ap.add_argument("--graph", type=int, default=0, help="index of the graph to read back")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    ti, guid = graph_table(a.seed, a.graph)
    if a.table is not None:
        ti = a.table
    if ti is None:
        raise SystemExit("no data table feeds that graph directly: pass --table")
    rnd = random.Random(a.rseed)
    paths, values = [], {}
    for v in range(a.n):
        proj = open_document(a.seed)
        t = proj.tables[ti]
        cells = [(ds, s, r) for ds in t.datasets for s, sub in enumerate(ds.subcolumns) for r, x in enumerate(sub)
                 if x.strip() and _num(x) is not None]
        vals = [] if a.only_x else variant_values(rnd, len(cells))
        for (ds, s, r), x in zip(cells, vals, strict=False):
            ds.subcolumns[s][r] = _fmt(x)
        if (a.vary_x or a.only_x) and t.x is not None and t.x.generated is None:
            xc = [r for r, x in enumerate(t.x.subcolumns[0]) if x.strip() and _num(x) is not None]
            xv = variant_values(rnd, len(xc))
            if a.only_x:
                xv = [abs(v) or 1.0 for v in xv]
            for r, x in zip(xc, xv, strict=True):
                t.x.subcolumns[0][r] = _fmt(x)
            vals = vals + xv
        p = os.path.join(a.out, "inputs", f"v{v:03d}.prism")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        if not (a.reuse and os.path.exists(p)):
            save_project(a.seed, proj, p)
        paths.append(p)
        values[f"v{v:03d}"] = vals
    auto_dir = os.path.join(a.out, "prism")
    if not a.reuse:
        cmd = [sys.executable, "-I", os.path.join(ROOT, "tools", "prism_auto.py"), auto_dir, "--timeout", "30", *paths]
        if not a.png:
            cmd.insert(6, "--no-png")
        subprocess.run(cmd, check=True, capture_output=True)
    rows = []
    for v, vals in values.items():
        rs = os.path.join(auto_dir, v, "resaved.prism")
        if not os.path.exists(rs):
            continue
        for r in axes_of(rs, guid):
            r.update(variant=v, vmin=min(vals), vmax=max(vals))
            rows.append(r)
    with open(os.path.join(a.out, "rows.json"), "w") as f:
        json.dump({"seed": os.path.basename(os.path.dirname(a.seed)), "values": values, "rows": rows}, f)
    print(f"{len(rows)} axis rows from {len(values)} variants")


def _fmt(x: float) -> str:
    return repr(x) if not float(x).is_integer() else str(int(x)) if abs(x) < 1e15 else repr(x)


def _num(s: str):
    try:
        return float(s)
    except ValueError:
        return None


if __name__ == "__main__":
    main()
