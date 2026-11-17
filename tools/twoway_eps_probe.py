"""RM-by-both-factors Geisser-Greenhouse epsilon across table shapes (Prism vs ours).

Usage: .venv/bin/python -I tools/twoway_eps_probe.py <out_dir> [--reuse]
"""

from __future__ import annotations

import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import stats_oracle as O
from twoway_parity import BB, params

from refract.formats.bundle_builder import DataSet, TableSpec
from refract.stats import engine

SHAPES = [(3, 3, 4), (3, 3, 5), (4, 3, 4), (4, 3, 5), (4, 3, 6), (3, 4, 5), (4, 4, 5), (5, 3, 5), (3, 5, 5), (4, 3, 3),
          (5, 4, 6), (3, 3, 3)]


def gen(seed=21):
    rnd = random.Random(seed)
    out = []
    for nr, nc, n in SHAPES:
        subj = [rnd.gauss(0, 2) for _ in range(n)]
        cols = [[[round(10 + r + c + subj[s] + rnd.gauss(0, 1.5), 3) for r in range(nr)] for s in range(n)] for c in range(nc)]
        out.append((f"bb_r{nr}c{nc}n{n}", cols))
    return out


def main():
    out = sys.argv[1]
    sets = gen()
    p = params(BB, "NO_TESTS", "ALL_VS_ALL", "STATISTICAL", "TUKEY")
    rp = os.path.join(out, "results.json")
    if "--reuse" in sys.argv and os.path.exists(rp):
        with open(rp) as f:
            res = json.load(f)
    else:
        cases = [O.Case(name, [TableSpec("G", "grouped", "y_replicates", [DataSet(chr(65 + i), c) for i, c in enumerate(cols)],
                                         row_titles=[f"R{r + 1}" for r in range(len(cols[0][0]))], replicates=len(cols[0]))],
                        [("TWO_WAY_ANOVA", p, 0, "a")]) for name, cols in sets]
        res = O.run(cases, out, timeout=30)
    for name, cols in sets:
        t = res.get(name, {}).get("a", {}).get("repeatedMeasuresGlmAnovaModel", {}).get("anovaTable", {})
        o = engine.compute("TWO_WAY_ANOVA", p, cols)["repeatedMeasuresGlmAnovaModel"]["anovaTable"]
        print(name, " ".join(f"{k[:6]} prism={t.get(k, {}).get('ggEpsilon', '-')!s:.8} ours={o[k].get('ggEpsilon', '-')!s:.8}"
                             for k in ("rowFactor", "colFactor", "rowFactorVsColFactor")))


if __name__ == "__main__":
    main()
