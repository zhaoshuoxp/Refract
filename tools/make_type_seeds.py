"""Build the per-type seed graphs shipped with Refract
(refract/formats/seed_graphs/types/), for the graph types Prism's script
language cannot make and whose stored form was not found field by field
(separated and stacked bars, floating bars, horizontal grouped graphs, XY
replicates and bars, survival variants, nested graphs; E-types).

Source: reference files with one Prism-made graph per type, each graph
named by its Refract type key (made by hand in Prism on Refract's own
sample tables: corpus/manual/type_reference.prism and type_reference2.prism;
a later file's graph of a type wins). As for the kind seeds
(tools/make_seeds.py), nothing of it is shipped as is: Refract writes each
type, seeded from its reference graph, on neutral generated tables (six
data sets), Prism re-saves the file - rebuilding each graph from those
tables - and only the graph blobs are kept, checked for sample text.

  .venv/bin/python tools/make_type_seeds.py make <reference.prism>... <out_dir> [--only=key,...]
  .venv/bin/python -I tools/prism_auto.py <out_dir>/prism <out_dir>/type_seeds.prism
  .venv/bin/python tools/make_type_seeds.py extract <out_dir>/prism/type_seeds/resaved.prism

extract adds the file's types to the shipped index (types made before are kept).
"""

from __future__ import annotations

import json
import os
import re
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)

DEST = os.path.join(ROOT, "refract", "formats", "seed_graphs", "types")
N_SETS = 6
# reference graph name -> Refract graph type (names that are not a type key)
# (the reference "nest_bars", made from Prism's nested Bars choice, shows the values over the bars: Refract's
# "scatter with bars")
ALIASES = {"surv_inverted": "surv_inverted_points", "nest_default": "nest_scatter", "nest_bars": "nest_scatter_bar",
           "grp_heat": "grp_heat_viridis"}
# not made: the reference's before-after "with bars" came out as Prism's plain before-after (Refract writes
# that already). The heat map made Prism quit until its copy kept the heat map's own indices (E-heat)
# pow_stacked is a pie's kin (0x80D6 +20 = 4, written on the pie seed): Prism does not rewrite a pie's blob
# when it re-saves, so a seed made this way keeps the reference's slice texts (E-pie)
# cont_percent: the sample table's rows already sum to 100, so the reference shows no 100 % stacking (only the
# probability Y scale chosen on it); it is not taken
# surv_plain: the reference has censor ticks like Prism's default staircase (the wizard's "no ticks" was not
# the one chosen), so it shows nothing of the plain staircase
# pow_stacked_h: as pow_stacked (0x80D6 +20 = 3 on the pie seed, refract.formats.graph_patch.PIE_CHARTS)
# surv_plain (2nd batch) and cont_percent: Prism's wizard has no such graph (the user, 2026-11-16)
# grp_means_h: the reference made is Prism's horizontal interleaved bars (grp_bars_h), not symbols
SKIP = {"col_before_after_bars", "mv_default", "pow_stacked", "pow_stacked_h", "cont_percent",
        "surv_plain", "grp_means_h"}
# text that must not be in a shipped seed: Refract's sample tables the references were made on
FORBIDDEN = ("Untreated", "Treated", "Wild type", "Mutant", "Vehicle", "dose", "Exposed", "disease",
             "Standard", "treatment", "Protein", "Carbohydrate", "Control", "Time (h)", "Days")
ALLOWED = ("Probability of Survival", "Probability of Death")


def _value(ds: int, sub: int, row: int) -> str:
    return f"{10 + 3 * ds + 2 * row + (sub % 3) * 0.5 + (row * ds % 3) * 0.7:g}"


def _table(T, doc, kind: str):
    if kind == "xy":
        t = doc.add_table(T.make("xy", "Seed xy", data_format="y_replicates", replicates=3, n_sets=N_SETS),
                          with_graph=False)
    elif kind == "parts_of_whole":
        t = doc.add_table(T.make(kind, "Seed parts", n_sets=1), with_graph=False)
    else:
        t = doc.add_table(T.make(kind, f"Seed {kind}", n_sets=N_SETS), with_graph=False)
    if kind == "survival":  # four subjects per group, each on its own rows; the last one censored
        cells = []
        for i, ds in enumerate(t.datasets):
            for k in range(4):
                r = 4 * i + k
                cells += [(t.x, 0, r, f"{5 + 3 * i + 7 * k}"), (ds, 0, r, "0" if k == 3 else "1")]
        doc.set_cells(t, cells)
        return t
    rows = 5
    cells = [(ds, s, r, _value(i, s, r)) for i, ds in enumerate(t.datasets)
             for s in range(len(ds.subcolumns)) for r in range(rows)]
    if t.row_titles is not None:
        cells += [(t.row_titles, 0, r, f"Row {r + 1}") for r in range(rows)]
    if t.x is not None:
        cells += [(t.x, 0, r, f"{r + 1}") for r in range(rows)]
    doc.set_cells(t, cells)
    return t


def make(refs_in: list[str], out: str, only: set[str] | None = None) -> int:
    from refract.formats import open_document
    from refract.formats.graph_transplant import Seed
    from refract.formats.pcff import skeleton as SK
    from refract.formats.zipio import ZipArchive
    from refract.model import templates as T
    from refract.render import graph_types as GT
    from refract.render import qt
    from refract.ui.document import Document

    qt.ensure_app()
    refs = {}
    for ref in refs_in:
        rp, ra = open_document(ref), ZipArchive.open(ref)
        for g in rp.graphs:
            key = ALIASES.get(g.title, g.title)
            if g.title in SKIP or key not in GT.BY_KEY or not g.blob or (only and key not in only):
                continue
            refs[key] = (ra, g.uid)
    orig = SK.seed

    def seed(kind, title, n, plots):  # each type from its reference graph
        return Seed.from_bundle(*refs[title]) if title in refs else orig(kind, title, n, plots)

    SK.seed = seed
    SK.WRITTEN_KINDS = (*SK.WRITTEN_KINDS, "nested")
    GT.HORIZONTAL_KINDS.update({"grouped", "contingency"})
    os.makedirs(out, exist_ok=True)
    doc = Document.new()
    tables = {}
    for key in refs:
        kind = GT.BY_KEY[key].family
        if kind not in tables:
            tables[kind] = _table(T, doc, kind)
        doc.add_native_graph(tables[kind], title=key, style=key)
    path = os.path.join(out, "type_seeds.prism")
    doc.save(path)
    print(path, len(refs), "types;", [r for r in doc.last_report if "not written" in r])
    return 0


def _strings(blob: bytes) -> set[str]:
    return {m.group().decode() for m in re.finditer(rb"[ -~]{4,}", blob)} | \
        {m.group().decode("utf-16-le") for m in re.finditer(rb"(?:[ -~]\x00){4,}", blob)}


# cached drawing Prism rebuilds when it opens a graph (skeleton.REBUILT): a violin's curves (0x00AE) are
# megabytes, so the seeds go without them (E-types: the violins drew the same)
CACHED = frozenset({0x00AE})


def lean(blob: bytes) -> bytes:
    from refract.formats.pcff.walker import parse, serialize, subtree_end

    ch, out, i = parse(blob), [], 0
    while i < len(ch):
        if not ch[i].is_marker and ch[i].tag in CACHED:
            i = subtree_end(ch, i)
            continue
        out.append(ch[i])
        i += 1
    return serialize(out)


def extract(resaved: str, dest: str = DEST) -> int:
    from refract.formats.graph_transplant import Seed
    from refract.formats.zipio import ZipArchive
    from refract.render import graph_types as GT

    z = ZipArchive.open(resaved)
    at = os.path.join(dest, "index.json")
    index = {}
    if os.path.exists(at):
        with open(at) as f:
            index = json.load(f)
    os.makedirs(dest, exist_ok=True)
    for g in json.loads(z.read("document.json"))["sheets"].get("graphs", []):
        sheet = json.loads(z.read(f"graphs/{g}/sheet.json"))
        key = sheet.get("title", "")
        if key not in GT.BY_KEY or key in SKIP:
            continue
        s = Seed.from_bundle(z, g)
        text = list(_strings(s.blob))
        for a in ALLOWED:
            text = [t.replace(a, "") for t in text]
        bad = [t for t in text for f in FORBIDDEN if f in t]
        if bad:
            print(f"{key}: sample text left in the graph: {bad}")
            return 1
        name = f"{key}.pcff"
        with open(os.path.join(dest, name), "wb") as f:
            f.write(lean(s.blob))
        index[key] = {"file": name, "sheet": {k: v for k, v in s.sheet.items() if k in ("@class", "$id")},
                      "y_fens": s.y_fens, "row_fen": s.row_fen, "x_fen": s.x_fen, "kind": s.kind}
        print(key, len(s.blob), "bytes,", len(s.y_fens), "data sets")
    with open(at, "w") as f:
        json.dump(dict(sorted(index.items())), f, indent=1)
        f.write("\n")
    return 0


if __name__ == "__main__":
    a = sys.argv[1:]
    keys = next((x.split("=", 1)[1].split(",") for x in a if x.startswith("--only=")), None)
    a = [x for x in a if not x.startswith("--only=")]
    raise SystemExit(make(a[1:-1], a[-1], set(keys) if keys else None) if a[0] == "make" else extract(*a[1:]))
