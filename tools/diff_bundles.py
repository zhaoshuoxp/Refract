"""Structural diff of two .prism bundles: ours vs Prism's re-save.

Usage: .venv/bin/python -I tools/diff_bundles.py <ours.prism> <prism_resaved.prism>

Entries are matched by path, with each UUID replaced by its first-seen index
so that renamed UUIDs do not hide a structural match. JSON entries are diffed
by key path, CSV by cell, and binary entries by size and equality only.
Values are printed, so do not paste the output anywhere public when the input
contains real data.
"""

from __future__ import annotations

import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from refract.formats.zipio import ZipArchive

UUID = re.compile(r"[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}")


def json_paths(obj, prefix=""):
    if isinstance(obj, dict):
        if not obj:
            yield prefix or "/", "{}"
        for k, v in obj.items():
            yield from json_paths(v, f"{prefix}/{k}")
    elif isinstance(obj, list):
        if not obj:
            yield prefix or "/", "[]"
        for i, v in enumerate(obj):
            yield from json_paths(v, f"{prefix}[{i}]")
    else:
        yield prefix, json.dumps(obj, ensure_ascii=False)


def main(a_path: str, b_path: str) -> None:
    a, b = ZipArchive.open(a_path), ZipArchive.open(b_path)
    an, bn = {e.name: e for e in a.entries}, {e.name: e for e in b.entries}
    print(f"entries: ours {len(an)}, prism {len(bn)}")
    only_a = sorted(set(an) - set(bn))
    only_b = sorted(set(bn) - set(an))
    for n in only_a:
        print("  only in ours:  ", n)
    for n in only_b:
        print("  only in prism: ", n)
    print("entry order identical:", [e.name for e in a.entries if e.name in bn] == [e.name for e in b.entries if e.name in an])
    for n in sorted(set(an) & set(bn)):
        x, y = an[n].read(), bn[n].read()
        if x == y:
            continue
        if n.endswith(".json"):
            px = dict(json_paths(json.loads(x)))
            py = dict(json_paths(json.loads(y)))
            print(f"~ {n}")
            for k in sorted(set(px) | set(py)):
                if px.get(k) != py.get(k):
                    print(f"     {k}: {px.get(k, '<absent>')}  ->  {py.get(k, '<absent>')}")
        elif n.endswith(".csv"):
            rx, ry = x.decode().split("\n"), y.decode().split("\n")
            print(f"~ {n}: rows {len(rx)} -> {len(ry)}")
            for i, (r1, r2) in enumerate(zip(rx, ry, strict=False)):
                if r1 != r2:
                    print(f"     row {i}: {r1[:80]!r} -> {r2[:80]!r}")
        else:
            print(f"~ {n}: {len(x)} -> {len(y)} bytes ({x[:40]!r} -> {y[:40]!r})")


if __name__ == "__main__":
    main(*sys.argv[1:3])
