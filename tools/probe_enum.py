"""Probe enum values of one parameter path: one Prism document per candidate,
report which result models each produces.

Library use: probe(cls, base_content, path, candidates, tables, out) -> {cand: results content}
"""

from __future__ import annotations

import copy
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import stats_oracle as O


def stem(c) -> str:
    """File-system-safe case name for a candidate value."""
    import re
    import zlib

    raw = str(c)[:60]
    safe = re.sub(r"[^A-Za-z0-9_.+-]", "_", raw)
    return f"P_{safe}" if safe == raw else f"P_{safe}_{zlib.crc32(raw.encode()) % 10000:04d}"


def set_path(d: dict, path: str, value) -> None:
    keys = path.strip("/").split("/")
    for k in keys[:-1]:
        d = d.setdefault(k, {})
    d[keys[-1]] = value


def probe(cls: str, base: dict, path: str, candidates: list, tables, out: str, schema: str | None = None,
          extra: dict | None = None) -> dict:
    cases = []
    for c in candidates:
        content = copy.deepcopy(base)
        set_path(content, path, c)
        for p, v in (extra or {}).items():
            set_path(content, p, v)
        cases.append(O.Case(stem(c), tables, [(cls, content, 0, f"p {c}")]))
    if schema:
        from refract.formats.analysis_writer import SCHEMA
        SCHEMA.setdefault(cls, schema)
    res = O.run(cases, out)
    return {c: (list(res[stem(c)].values()) or [{}])[0] for c in candidates}


def retained(out: str, candidates: list, path: str) -> dict:
    """After probe(): what Prism wrote back at `path` in its re-saved parameters
    (an unknown enum value is reset to the default)."""
    import json

    from refract.formats.zipio import ZipArchive
    out_vals = {}
    for c in candidates:
        rs = os.path.join(out, "prism", stem(c), "resaved.prism")
        if not os.path.exists(rs):
            out_vals[c] = "<no resave>"
            continue
        z = ZipArchive.open(rs)
        a = json.loads(z.read("document.json"))["sheets"]["analyses"][0]
        v = json.loads(z.read(f"analyses/{a}/parameters.json"))["content"]
        for k in path.strip("/").split("/"):
            v = v.get(k) if isinstance(v, dict) else None
        out_vals[c] = v
    return out_vals
