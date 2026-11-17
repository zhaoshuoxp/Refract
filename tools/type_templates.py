"""What makes a graph type, from graphs Prism made (E-types).

A reference file holds one Prism-made graph per graph type, each named by
its Refract type key (corpus/manual/type_reference.prism: Refract's own
sample tables, the graphs made by hand in Prism, whose scripts cannot
choose a graph type). Each is compared field by field with Refract's
default skeleton of its table kind (refract.formats.pcff.skeleton):

  * the graph header 0x0013 and the nine axis settings 0x8025;
  * every plot's header 0x8028 and record 0x009C: the offsets where all the
    reference's plots agree with each other and differ from the skeleton's
    plots are the type's own fields (per-data-set fields - ids, fenIDs,
    colours, indices - differ between plots and drop out).

Writes the fields as JSON (type key -> {"kind": {offset: value}, "axes":
[{offset: value}] * 9, "head": {...}, "rec": {...}}) and prints a summary.

  .venv/bin/python -I tools/type_templates.py corpus/manual/type_reference.prism out.json
"""

from __future__ import annotations

import json
import os
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)

from refract.formats import open_document
from refract.formats.pcff import fields as F
from refract.formats.pcff import skeleton as S
from refract.formats.pcff.walker import parse

KIND = {"column": "column", "grouped": "grouped", "xy": "xy", "survival": "survival", "contingency": "grouped",
        "parts_of_whole": "parts_of_whole", "nested": "column", "multivariable": None}
# never part of a type: object ids, data-set links, rectangles and text references
# (0x009C +113 numbers the plots in the file; 0x8028 +98..+108 and 0x009C +121 vary with the table and
# the plot's place, not with the type: the reference's own graphs disagree on them)
SKIP = {"kind": set(range(28)) | {32, 33}, "head": set(range(12)) | set(range(22, 58)) | set(range(66, 100))
        | set(range(98, 109)) | {113},
        "rec": set(range(4)) | set(range(209, 240)) | set(range(305, 317)) | {113, 121}}


def plots(ch):
    out = []
    for k, c in enumerate(ch):
        if c.tag == 0x8020 and c.payload and c.payload[:2] == b"\x09\x00":
            head = rec = None
            for x in ch[k + 1:k + 8]:
                if x.tag == 0x8028:
                    head = x.payload
                elif x.tag == 0x009C and x.payload and len(x.payload) > 140:
                    rec = x.payload
                    break
            if head is not None and rec is not None:
                out.append((head, rec))
    return out


def common_diff(ref: list[bytes], base: list[bytes], skip: set[int]) -> dict[int, int]:
    """Offsets where every reference payload has the same value, different
    from every base payload's."""
    if not ref or not base:
        return {}
    n = min(len(p) for p in ref + base)
    out = {}
    for o in range(n):
        if o in skip:
            continue
        vals = {p[o] for p in ref}
        if len(vals) == 1:
            v = vals.pop()
            if all(p[o] != v for p in base):
                out[o] = v
    return out


def main() -> None:
    src, dest = sys.argv[1], sys.argv[2]
    p = open_document(src)
    by_ds = {ds.uid: t for t in p.tables for ds in t.datasets if ds.uid}
    result = {}
    for gs in p.graphs:
        if not gs.blob or gs.blob[:8] != b"PCFFGRA4":
            print(f"{gs.title}: no PCFF graph blob (a different graph format)")
            continue
        kinds = {by_ds[u].kind for u in gs.input_datasets if u in by_ds}
        tk = next(iter(kinds), "survival")
        kind = KIND.get(tk)
        if kind is None:
            continue
        ch = parse(gs.blob)
        base = parse(S.build(kind, "", 6)[0])
        kh = next(c.payload for c in ch if c.tag == F.TAG_GRAPH_KIND and c.payload)
        bh = next(c.payload for c in base if c.tag == F.TAG_GRAPH_KIND and c.payload)
        rp, bp = plots(ch), plots(base)
        t = {"table": tk, "kind": common_diff([kh], [bh], SKIP["kind"]),
             "head": common_diff([h for h, _ in rp], [h for h, _ in bp], SKIP["head"]),
             "rec": common_diff([r for _, r in rp], [r for _, r in bp], SKIP["rec"]),
             "axes": [common_diff([a.payload], [b.payload], set(range(2)))
                      for a, b in zip(F.axis_settings(ch), F.axis_settings(base), strict=False)],
             "n_plots": len(rp), "chunks": len(ch)}
        result[gs.title] = t
        ax = {i: a for i, a in enumerate(t["axes"]) if a}
        print(f"{gs.title:24s} {tk:14s} plots={len(rp)} kind={t['kind']} head={t['head']} rec={t['rec']} axes={ax}")
    with open(dest, "w") as f:
        json.dump(result, f, indent=1)


if __name__ == "__main__":
    main()
