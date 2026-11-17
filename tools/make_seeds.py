"""Build the seed graphs shipped with Refract (refract/formats/seed_graphs/).

A seed is a graph Prism made. To ship seeds that carry nothing from any
sample file, Refract makes a project of its own with neutral, generated data
(six data sets per table), writes its graphs for Prism from the local seeds,
and Prism re-saves it: Prism rebuilds each graph from Refract's tables, adds
the plots of the extra data sets and recomputes the cached titles, legends
and ranges. Only the graph blobs and the data-set fenIDs they plot are then
kept; no data table, info sheet or analysis is shipped.

Usage:
  .venv/bin/python tools/make_seeds.py make <out_dir>
  .venv/bin/python -I tools/prism_auto.py <out_dir>/prism <out_dir>/seeds.prism
  .venv/bin/python tools/make_seeds.py extract <out_dir>/prism/seeds/resaved.prism [dest_dir]

The pie (parts_of_whole) cannot be made this way: Prism does not rewrite a
pie graph's blob when it re-saves a file, so the source pie's cached legend
texts would stay in the seed (E-pie). Its seed is a default pie that Prism
drew on Refract's neutral table (corpus/manual/pie_seed_table.prism, the
graph made by hand in Prism, which its scripts cannot do), taken as is:
  .venv/bin/python tools/make_seeds.py extract <that file.prism> [dest_dir] --only parts_of_whole
"""

from __future__ import annotations

import json
import os
import re
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)

N_SETS = 6
KINDS = ("column", "grouped", "xy", "survival", "parts_of_whole")
SETS = {"parts_of_whole": 1}  # a pie plots one data set
DEST = os.path.join(ROOT, "refract", "formats", "seed_graphs")
# Text that must not be in a shipped seed: the sample tables the local seeds came from.
FORBIDDEN = ("Entering replicate", "Hours", "Survival", "Control", "Treated", "Col:", "XY:", "Grouped:",
             "Days elapsed")
ALLOWED = ("Probability of Survival",)  # Prism's own default Y axis title of a survival graph


def _value(kind: str, ds: int, sub: int, row: int) -> str:
    return f"{10 + 3 * ds + 2 * row + (sub % 3) * 0.5 + (row * ds % 3) * 0.7:g}"


def make(out: str) -> int:
    from refract.formats import seeds
    from refract.model import templates as T
    from refract.render import qt
    from refract.ui.document import Document

    qt.ensure_app()
    if not seeds.library():
        print("no local seed file: see refract/formats/seeds.py")
        return 1
    os.makedirs(out, exist_ok=True)
    doc = Document.new()
    for kind in KINDS:
        if kind == "parts_of_whole":  # see the module docstring
            continue
        t = doc.add_table(T.make(kind, f"Seed {kind}", n_sets=N_SETS))
        if kind == "survival":  # four subjects per group, each on its own rows; the last one censored
            cells = []
            for i, ds in enumerate(t.datasets):
                for k in range(4):
                    r = 4 * i + k
                    cells += [(t.x, 0, r, f"{5 + 3 * i + 7 * k}"), (ds, 0, r, "0" if k == 3 else "1")]
            doc.set_cells(t, cells)
            continue
        rows = 5
        cells = [(ds, s, r, _value(kind, i, s, r)) for i, ds in enumerate(t.datasets)
                 for s in range(len(ds.subcolumns)) for r in range(rows)]
        if t.row_titles is not None:  # without them Prism labels a grouped graph's X axis with row numbers
            cells += [(t.row_titles, 0, r, f"Row {r + 1}") for r in range(rows)]
        if t.x is not None:
            cells += [(t.x, 0, r, f"{r + 1}") for r in range(rows)]
        doc.set_cells(t, cells)
    path = os.path.join(out, "seeds.prism")
    doc.save(path)
    print(path, doc.last_report or "")
    return 0


def _strings(blob: bytes) -> set[str]:
    return {m.group().decode() for m in re.finditer(rb"[ -~]{4,}", blob)} | \
        {m.group().decode("utf-16-le") for m in re.finditer(rb"(?:[ -~]\x00){4,}", blob)}


def extract(resaved: str, dest: str = DEST, only: tuple[str, ...] = KINDS) -> int:
    """Seeds of the `only` kinds from the file; with fewer than all kinds they
    are merged into dest's index.json."""
    from refract.formats.graph_transplant import Seed, is_pie
    from refract.formats.zipio import ZipArchive

    z = ZipArchive.open(resaved)
    index = {}
    os.makedirs(dest, exist_ok=True)
    for g in json.loads(z.read("document.json"))["sheets"].get("graphs", []):
        try:
            s = Seed.from_bundle(z, g)
        except ValueError:
            continue
        if s.kind not in only or s.kind in index or (s.kind == "parts_of_whole" and not is_pie(s.blob)):
            continue
        text = list(_strings(s.blob))
        for a in ALLOWED:
            text = [t.replace(a, "") for t in text]
        bad = [t for t in text for f in FORBIDDEN if f in t]
        if bad:
            print(f"{s.kind}: sample text left in the graph: {bad}")
            return 1
        if len(s.y_fens) != SETS.get(s.kind, N_SETS):
            print(f"{s.kind}: {len(s.y_fens)} data sets, expected {SETS.get(s.kind, N_SETS)}")
            return 1
        name = f"{s.kind}.pcff"
        with open(os.path.join(dest, name), "wb") as f:
            f.write(s.blob)
        sheet = {k: v for k, v in s.sheet.items() if k in ("@class", "$id")}
        index[s.kind] = {"file": name, "sheet": sheet, "y_fens": s.y_fens, "row_fen": s.row_fen,
                         "x_fen": s.x_fen}
        print(s.kind, len(s.blob), "bytes,", len(s.y_fens), "data sets; text:", sorted(_strings(s.blob)))
    path = os.path.join(dest, "index.json")
    if set(only) != set(KINDS) and os.path.exists(path):
        with open(path) as f:
            index = {**json.load(f), **index}
    with open(path, "w") as f:
        json.dump({k: index[k] for k in KINDS if k in index}, f, indent=1)
        f.write("\n")
    return 0 if set(only) <= set(index) else 1


if __name__ == "__main__":
    args = sys.argv[1:]
    only = KINDS
    if "--only" in args:
        k = args.index("--only")
        only = tuple(args[k + 1].split(","))
        del args[k:k + 2]
    raise SystemExit(make(args[1]) if args[0] == "make" else extract(*args[1:], only=only))
