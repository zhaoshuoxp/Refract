"""Structural diff of two PCFF graph blobs (or two .prism files' graph N).

Chunks are aligned by tag sequence (difflib), then each aligned pair is
compared byte by byte. Changed spans are printed with candidate decodings
(u8/u16/u32/f64 at the span's natural alignment).

Usage:
  .venv/bin/python -I tools/pcff_diff.py <a.prism> <b.prism> [--graph 1] [--quiet-tags 0x2015,...]
Importable: diff_blobs(a_bytes, b_bytes) -> list of dicts.
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from refract.formats.pcff.walker import Chunk, parse
from refract.formats.zipio import ZipArchive


def graph_blob(path: str, graph: int = 1) -> bytes:
    z = ZipArchive.open(path)
    doc = json.loads(z.read("document.json"))
    g = doc["sheets"]["graphs"][graph - 1]
    return z.read(f"graphs/{g}/data.bin")


def _spans(a: bytes, b: bytes) -> list[tuple[int, int]]:
    out, i, n = [], 0, min(len(a), len(b))
    while i < n:
        if a[i] != b[i]:
            j = i
            while j < n and a[j] != b[j]:
                j += 1
            out.append((i, j))
            i = j
        else:
            i += 1
    return out


def decode(p: bytes, off: int) -> dict:
    d = {"u8": p[off]}
    if off + 2 <= len(p):
        d["u16"] = struct.unpack_from("<H", p, off)[0]
    if off + 4 <= len(p):
        d["u32"] = struct.unpack_from("<I", p, off)[0]
        d["f32"] = round(struct.unpack_from("<f", p, off)[0], 6)
    if off + 8 <= len(p):
        d["f64"] = struct.unpack_from("<d", p, off)[0]
    return d


def _path(chunks: list[Chunk], i: int) -> str:
    """Container tags enclosing chunk i (outermost first)."""
    stack: list[int] = []
    for c in chunks[:i]:
        if c.is_marker:
            opener = (c.tag & 0x3FFF) | 0x8000
            while stack and stack[-1] != opener:
                stack.pop()
            if stack:
                stack.pop()
        elif c.is_container:
            stack.append(c.tag)
    return "/".join(f"{t:#06x}" for t in stack)


def diff_blobs(a: bytes, b: bytes) -> list[dict]:
    ca, cb = parse(a), parse(b)
    sm = difflib.SequenceMatcher(None, [c.tag for c in ca], [c.tag for c in cb], autojunk=False)
    out = []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            for k in range(i2 - i1):
                x, y = ca[i1 + k], cb[j1 + k]
                if x.payload == y.payload:
                    continue
                pa, pb = x.payload or b"", y.payload or b""
                spans = _spans(pa, pb)
                rec = {"op": "changed", "tag": f"{x.tag:#06x}", "index_a": i1 + k, "path": _path(ca, i1 + k),
                       "len": [len(pa), len(pb)], "spans": []}
                for s, e in spans[:12]:
                    al = s - (s % 2)
                    rec["spans"].append({"bytes": [s, e], "a": pa[s:e].hex(), "b": pb[s:e].hex(),
                                         "decode_a": decode(pa, al), "decode_b": decode(pb, al)})
                if len(pa) != len(pb):
                    rec["text_b"] = pb.decode("latin-1") if x.tag == 0x002C else None
                out.append(rec)
        else:
            out.append({"op": op, "a": [f"{c.tag:#06x}" for c in ca[i1:i2]][:20],
                        "b": [f"{c.tag:#06x}" for c in cb[j1:j2]][:20], "index_a": i1, "path": _path(ca, i1)})
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("a")
    ap.add_argument("b")
    ap.add_argument("--graph", type=int, default=1)
    args = ap.parse_args()
    for r in diff_blobs(graph_blob(args.a, args.graph), graph_blob(args.b, args.graph)):
        if r["op"] != "changed":
            print(f"{r['op']:8s} at #{r['index_a']} in {r['path']}: {r['a']} -> {r['b']}")
            continue
        print(f"changed  #{r['index_a']:<5d} {r['tag']} in {r['path']} len {r['len']}")
        for s in r["spans"]:
            print(f"           bytes {s['bytes']}: {s['a']} -> {s['b']}   f64 {s['decode_a'].get('f64')} -> {s['decode_b'].get('f64')}"
                  f"  u16 {s['decode_a'].get('u16')} -> {s['decode_b'].get('u16')}")


if __name__ == "__main__":
    main()
