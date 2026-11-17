"""Build refract/formats/seed_graphs/objects.json: the stored form of a
drawn line, arrow, rectangle, ellipse and text box on a Prism graph
(E-elements), as templates refract.formats.graph_objects fills in.

Source: a reference file whose graphs each hold one object drawn by hand
in Prism (corpus/manual/elements_reference.prism, made on Refract's sample
tables). Only each object's own chunks and its property-store entry are
kept: geometry, colours and widths are set when written; the text box's
text is replaced by a placeholder and checked.

  .venv/bin/python tools/make_object_templates.py corpus/manual/elements_reference.prism
"""

from __future__ import annotations

import json
import os
import struct
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)

DEST = os.path.join(ROOT, "refract", "formats", "seed_graphs", "objects.json")
SOURCES = {"line": "e08_drawn_line", "arrow": "e09_arrow", "rect": "e10_rect_filled", "ellipse": "e11_ellipse",
           "text": "e12_textbox"}


def main(path: str) -> int:
    from refract.formats import open_document
    from refract.formats.pcff import propstore as P
    from refract.formats.pcff import skeleton as SK
    from refract.formats.pcff.walker import parse, subtree_end
    from refract.render import from_prism as FP

    p = open_document(path)
    by = {g.title: g for g in p.graphs}
    out = {}
    for kind, title in SOURCES.items():
        ch = parse(by[title].blob)
        objs = SK._objects(ch)
        last = objs[-1]  # the object drawn by hand: the last one
        sub = ch[last:subtree_end(ch, last)]
        chunks = [[c.tag, None if c.payload is None else c.payload.hex()] for c in sub]
        if kind == "text":  # its words: a placeholder, set when written
            for c in chunks:
                if c[0] == 0x002C:
                    assert bytes.fromhex(c[1]) == b"Note", "the text box should say Note"
        arr = FP._store(ch).get("SEDObject_Array")
        assert len(arr.items) == len(objs)
        entry = arr.items[-1]
        store = [[k, v.raw.hex()] for k, v in entry.items if isinstance(v, P.Scalar)]
        out[kind] = {"type": struct.unpack_from("<H", sub[0].payload, 0)[0], "chunks": chunks, "store": store}
        print(kind, len(chunks), "chunks")
    with open(DEST, "w") as f:
        json.dump(out, f, indent=1)
        f.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
