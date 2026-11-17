"""Probe TWO_WAY_ANOVA enum values in Prism (retention: Prism resets unknown values).

Usage: .venv/bin/python -I tools/twoway_probe.py <out_dir> <path> CAND [CAND ...]
   e.g. tools/twoway_probe.py corpus/auto/tw_enum experimentalDesign REPEATED_MEASURES_BY_ROW ...
Prints, per candidate, the value Prism kept and the result model keys.
"""

from __future__ import annotations

import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from probe_enum import probe, retained

from refract.formats.bundle_builder import DataSet, TableSpec

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")


def table(rows=3, cols=3, reps=4, seed=1):
    rnd = random.Random(seed)
    sets = []
    for c in range(cols):
        subs = [[round(rnd.gauss(10 + 2 * c + 3 * r, 2), 3) for r in range(rows)] for _ in range(reps)]
        sets.append(DataSet(chr(65 + c), subs))
    return TableSpec("G", "grouped", "y_replicates", sets, row_titles=[f"R{r + 1}" for r in range(rows)], replicates=reps)


def main():
    out, path, *cands = sys.argv[1:]
    with open(os.path.join(ROOT, "corpus", "seeds", "twoway_params.json")) as f:
        base = json.load(f)
    extra = {}
    if os.environ.get("TW_EXTRA"):
        extra = json.loads(os.environ["TW_EXTRA"])
    res = probe("TWO_WAY_ANOVA", base, path, cands, [table()], out, extra=extra)
    kept = retained(out, cands, path)
    for c in cands:
        r = res.get(c, {})
        model = next((k for k in r if k.endswith("Model")), None)
        sub = list(r.get(model, {})) if model else []
        print(f"{c:45s} kept={kept[c]!s:45.45s} model={model} {sub[:8]} status={r.get('status')}")


if __name__ == "__main__":
    main()
