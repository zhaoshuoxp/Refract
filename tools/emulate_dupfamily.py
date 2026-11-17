"""Offline test: can we reproduce Prism's DuplicateFamily graph blob byte for
byte? Uses the new data-set fenIDs and graph fenID Prism chose (read from its
JSON) and our ID rules for everything inside the blob.

Usage: .venv/bin/python -I tools/emulate_dupfamily.py <control.prism> <dupfamily.prism>
"""

from __future__ import annotations

import json
import os
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from refract.formats.pcff import idmap
from refract.formats.pcff.walker import parse
from refract.formats.zipio import ZipArchive


def load(path):
    z = ZipArchive.open(path)
    d = json.loads(z.read("document.json"))
    gs = {}
    for g in d["sheets"].get("graphs", []):
        s = json.loads(z.read(f"graphs/{g}/sheet.json"))
        gs[g] = (s, z.read(f"graphs/{g}/data.bin"))
    return z, d, gs


def u16(p, o):
    return struct.unpack_from("<H", p, o)[0]


from refract.formats.graph_copy import doc_maxima, family_copy_blob  # noqa: E402


def emulate(src_blob, maxima, fen_map, gfen, family_size=1):
    return family_copy_blob(src_blob, maxima, fen_map, gfen, family_size)


def main(ctrl: str, dup: str) -> None:
    za, da, ga = load(ctrl)
    zb, db, gb = load(dup)
    maxima = doc_maxima([b for _, b in ga.values()])
    # data-set fen map: original table set fens -> copied table set fens (same order)
    def set_key(z, i, role):
        j = json.loads(z.read(f"data/sets/{i}.json"))
        t = j.get("title")
        t = t.get("string") if isinstance(t, dict) else t
        return (role, t), j["fenID"]

    def table_fens_uid(z, u):
        s = json.loads(z.read(f"data/sheets/{u}/sheet.json"))
        return _fens_of(z, s["table"])

    def _fens_of(z, t):
        out = {}
        for k, i in enumerate(t["dataSets"]):
            key, fen = set_key(z, i, "Y")
            out[(key[0], key[1], k)] = fen
        for role in ("rowTitlesDataSet", "xDataSet"):
            if t.get(role):
                out[(role, None, 0)] = set_key(z, t[role], role)[1]
        return out

    def table_fens(z, d, title):
        """{(role, data-set title): fenID} for the table with this sheet title."""
        for u in d["sheets"]["data"]:
            s = json.loads(z.read(f"data/sheets/{u}/sheet.json"))
            if s["title"] == title:
                t = s["table"]
                out = {}
                for k, i in enumerate(t["dataSets"]):
                    key, fen = set_key(z, i, "Y")
                    out[(key[0], key[1], k)] = fen
                for role in ("rowTitlesDataSet", "xDataSet"):
                    if t.get(role):
                        key, fen = set_key(z, t[role], role)
                        out[(role, None, 0)] = fen
                return out
        return {}
    for g, (sheet, blob) in gb.items():
        if g in ga or blob[:8] != b"PCFFGRA4":
            continue
        src = next(((s, b) for s, b in ga.values() if "Copy of " + s["title"] == sheet["title"]), None)
        if src is None:
            continue
        fen_map: dict[int, int] = {}
        for u in db["sheets"]["data"]:
            if u in da["sheets"]["data"]:
                continue  # only tables added by this DuplicateFamily
            s = json.loads(zb.read(f"data/sheets/{u}/sheet.json"))
            if s["title"].startswith("Copy of "):
                old = table_fens(za, da, s["title"][len("Copy of "):])
                new = table_fens_uid(zb, u)
                fen_map.update({old[k]: new[k] for k in old if k in new})
        ours = emulate(src[1], maxima, fen_map, sheet["fenID"])
        theirs = parse(blob)
        diffs = []
        for i, (x, y) in enumerate(zip(ours, theirs, strict=False)):
            if x.payload != y.payload and x.tag not in (0x2015, 0x0009):
                offs = [o for o in range(min(len(x.payload or b""), len(y.payload or b""))) if x.payload[o] != y.payload[o]]
                diffs.append((i, hex(x.tag), offs[:6], [(x.payload[o], y.payload[o]) for o in offs[:3]]))
        same_len = len(ours) == len(theirs)
        print(f"{os.path.basename(os.path.dirname(dup))}: copy of '{src[0]['title']}': {len(diffs)} chunks differ from Prism's copy"
              f"{'' if same_len else ' (chunk count differs!)'}")
        for d in diffs[:8]:
            print("     ", d)


if __name__ == "__main__":
    main(*sys.argv[1:3])
