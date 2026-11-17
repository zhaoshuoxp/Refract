"""Probe enum values of any analysis parameter in Prism (retention: Prism
resets unknown values to the default when it re-saves).

Usage:
  .venv/bin/python -I tools/class_probe.py <out_dir> <ANALYSIS_CLASS> <seed_params.json> <path> CAND [CAND ...]
      [--table grouped:ROWS:COLS:REPS | column:K:N | xy:N:REPS | contingency:ROWS:COLS] [--schema SCHEMA_ID] [--extra JSON]
Prints, per candidate, the value Prism kept and the shape of the results.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from probe_enum import probe, retained

from refract.formats.bundle_builder import DataSet, TableSpec


def make_table(spec: str, seed: int = 1) -> TableSpec:
    rnd = random.Random(seed)
    kind, *nums = spec.split(":")
    nums = [int(x) for x in nums]
    if kind == "grouped":
        rows, cols, reps = nums
        sets = [DataSet(chr(65 + c), [[round(rnd.gauss(10 + 2 * c + r, 2), 3) for r in range(rows)] for _ in range(reps)])
                for c in range(cols)]
        return TableSpec("G", "grouped", "y_replicates", sets, row_titles=[f"R{r + 1}" for r in range(rows)], replicates=reps)
    if kind == "column":
        k, n = nums
        return TableSpec("C", "column", "y_single", [DataSet(chr(65 + i), [[round(rnd.gauss(10 + i, 2), 3) for _ in range(n)]])
                                                     for i in range(k)])
    if kind == "xy":
        n, reps = nums
        xs = [float(i) for i in range(n)]
        ys = [[round(2 + 0.5 * x + rnd.gauss(0, 0.3), 3) for x in xs] for _ in range(reps)]
        return TableSpec("XY", "xy", "y_replicates" if reps > 1 else "y_single", [DataSet("Y", ys)], x_title="X", x_values=xs,
                         replicates=reps)
    if kind == "contingency":
        rows, cols = nums
        sets = [DataSet(f"Out{c + 1}", [[rnd.randint(3, 60) for _ in range(rows)]]) for c in range(cols)]
        return TableSpec("CT", "contingency", "y_single", sets, row_titles=[f"Grp{r + 1}" for r in range(rows)])
    raise ValueError(spec)


def _value(s: str):
    try:
        return json.loads(s)
    except ValueError:
        return s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("cls")
    ap.add_argument("seed_params")
    ap.add_argument("path")
    ap.add_argument("cands", nargs="+")
    ap.add_argument("--table", default="column:3:6")
    ap.add_argument("--schema")
    ap.add_argument("--extra")
    a = ap.parse_args()
    with open(a.seed_params) as f:
        base = json.load(f)
    extra = json.loads(a.extra) if a.extra else None
    cands = [_value(c) for c in a.cands]  # JSON literals (true, 1.5) are typed; anything else is a string
    res = probe(a.cls, base, a.path, cands, [make_table(a.table)], a.out, schema=a.schema, extra=extra)
    kept = retained(a.out, cands, a.path)
    for c in cands:
        r = res.get(c, {})
        shape = {k: (list(v)[:6] if isinstance(v, dict) else v) for k, v in r.items() if k != "status"}
        print(f"{c!s:52s} kept={kept[c]!s:45.45s} status={r.get('status')} {json.dumps(shape)[:160]}")


if __name__ == "__main__":
    main()
