"""Compare a Prism DuplicateFamily result with the original graph and report
renumbered u16 fields that refract.formats.pcff.idmap does not cover.

Usage: .venv/bin/python -I tools/check_idmap_coverage.py <control.prism> <dupfamily.prism>
"""
from __future__ import annotations

import collections
import difflib
import json
import os
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from refract.formats.pcff import fields, idmap
from refract.formats.pcff.walker import parse
from refract.formats.zipio import ZipArchive

KNOWN_OTHER = {0x2015, 0x0009, 0x0015, 0x000A, 0x0013, 0x0014, 0x0091, 0x0016, 0x00A0, 0x8012, 0x8018}


def graphs(path):
    z = ZipArchive.open(path)
    d = json.loads(z.read("document.json"))
    out = {}
    for g in d["sheets"].get("graphs", []):
        s = json.loads(z.read(f"graphs/{g}/sheet.json"))
        out[g] = (s["title"], z.read(f"graphs/{g}/data.bin"))
    return out


def main(ctrl, dup):
    a, b = graphs(ctrl), graphs(dup)
    new = {g: v for g, v in b.items() if g not in a}
    print(f"{os.path.basename(os.path.dirname(dup))}: {len(a)} graphs -> {len(b)}; copies: {[v[0] for v in new.values()]}")
    gaps = collections.Counter()
    covered = 0
    for g, (title, blob) in new.items():
        src = next((x for x in a.values() if "Copy of " + x[0] == title), None)
        if src is None or blob[:8] != b"PCFFGRA4":
            continue
        ca, cb = parse(src[1]), parse(blob)
        pa = idmap.parents(ca)
        known = {(c_i, off) for c_i, (c, par) in enumerate(zip(ca, pa, strict=True)) if c.payload for off, _ in idmap._fields(c, par)}
        sm = difflib.SequenceMatcher(None, [c.tag for c in ca], [c.tag for c in cb], autojunk=False)
        for op, i1, i2, j1, _ in sm.get_opcodes():
            if op != "equal":
                gaps[("structural", op)] += 1
                continue
            for k in range(i2 - i1):
                x, y = ca[i1 + k], cb[j1 + k]
                if x.payload == y.payload or x.payload is None:
                    continue
                if x.tag in KNOWN_OTHER or x.tag == fields.TAG_TEXT or x.tag == 0x0852:
                    continue
                for off in range(0, min(len(x.payload), len(y.payload)) - 1, 2):
                    u, v = struct.unpack_from("<H", x.payload, off)[0], struct.unpack_from("<H", y.payload, off)[0]
                    if u != v and u < 4096 and v < 4096:
                        if (i1 + k, off) in known:
                            covered += 1
                        else:
                            gaps[(hex(x.tag), off)] += 1
    print(f"   renumbered fields covered by idmap: {covered}; NOT covered: {dict(gaps.most_common(20))}")


if __name__ == "__main__":
    main(*sys.argv[1:3])
