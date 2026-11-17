"""Probe when Prism reports exact P values for Kruskal-Wallis and Friedman.

Usage: .venv/bin/python -I tools/anova_exact_probe.py <out_dir> [--reuse]
Prints, per design, the sizes, whether ties exist, Prism's exact P, and ours.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import stats_oracle as O
from anova_parity import params

from refract.formats.bundle_builder import DataSet, TableSpec
from refract.stats import one_way as OW

KW = [[6, 6, 6], [5, 6, 6], [2] * 8, [1, 8, 8], [4, 4, 4, 5], [3, 3, 3, 3, 4], [5, 5, 5], [7, 7, 7], [4, 4, 4, 4, 1],
      [9, 9], [8, 9], [3, 3, 3]]
KW_TIES = [[3, 3, 3], [4, 4, 4, 4], [5, 5, 5]]
FR = [(3, 10), (3, 12), (3, 14), (7, 3), (5, 4), (4, 6), (4, 7), (8, 2), (6, 4), (3, 9)]
FR_TIES = [(3, 5), (4, 4), (3, 8)]
# second round: Kruskal-Wallis designs with 1.07e9 < perms < 7e9 (--round 2)
KW2 = [[1, 1, 1, 3, 4, 8], [1, 2, 2, 3, 3, 5], [1, 3, 9, 9], [1, 5, 6, 9], [1, 2, 3, 3, 3, 4], [1, 1, 1, 4, 4, 7],
       [1, 2, 4, 4, 8], [1, 1, 1, 5, 5, 5], [1, 5, 7, 9]]


def gen(seed=11, rnd_no=1):
    rnd = random.Random(seed)
    out = []
    if rnd_no == 2:
        for sizes in KW2:
            vals = rnd.sample(range(1, 1000), sum(sizes))
            it = iter(v / 10 for v in vals)
            out.append(("kw_" + "-".join(map(str, sizes)), "KRUSKAL_WALLIS_TEST", [[next(it) for _ in range(n)] for n in sizes]))
        return out
    for sizes in KW:
        vals = rnd.sample(range(1, 1000), sum(sizes))
        it = iter(v / 10 for v in vals)
        out.append(("kw_" + "-".join(map(str, sizes)), "KRUSKAL_WALLIS_TEST", [[next(it) for _ in range(n)] for n in sizes]))
    for sizes in KW_TIES:
        it = iter(rnd.choice(range(1, 12)) for _ in range(sum(sizes)))
        out.append(("kwties_" + "-".join(map(str, sizes)), "KRUSKAL_WALLIS_TEST", [[next(it) for _ in range(n)] for n in sizes]))
    for k, n in FR:
        out.append((f"fr_k{k}_n{n}", "FRIEDMAN_TEST", [[rnd.random() * 10 + c for _ in range(n)] for c in range(k)]))
    for k, n in FR_TIES:
        g = [[float(rnd.randint(1, 4)) for _ in range(n)] for _ in range(k)]
        out.append((f"frties_k{k}_n{n}", "FRIEDMAN_TEST", g))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--reuse", action="store_true")
    ap.add_argument("--round", type=int, default=1)
    a = ap.parse_args()
    sets = gen(rnd_no=a.round)
    res_path = os.path.join(a.out, "results.json")
    if a.reuse and os.path.exists(res_path):
        with open(res_path) as f:
            res = json.load(f)
    else:
        cases = [O.Case(name, [TableSpec("G", "column", "y_single", [DataSet(chr(65 + i), [g]) for i, g in enumerate(groups)])],
                        [("ONE_WAY_ANOVA", params(design, "ALL_VS_ALL", "STATISTICAL", "DUNN"), 0, "a")])
                 for name, design, groups in sets]
        res = O.run(cases, a.out, timeout=30)
    for name, design, groups in sets:
        r = res.get(name, {}).get("a")
        if not r:
            print(f"{name:22s} no result")
            continue
        model = next((v for k, v in r.items() if k.endswith("Model")), None)
        if model is None:
            print(f"{name:22s} no model: {list(r)} {str(r)[:120]}")
            continue
        t = model.get("kruskalWallisTest") or model.get("friedmanTest")
        ex = t.get("pValueExact", {}).get("value")
        ours = OW.kruskal_wallis(groups) if design.startswith("KRUSKAL") else OW.friedman(groups)
        ot = next(iter(ours.values()))
        ot = ot.get("kruskalWallisTest") or ot.get("friedmanTest")
        oe = ot.get("pValueExact", {}).get("value")
        cells = sum(len(g) for g in groups)
        if design.startswith("KRUSKAL"):
            size = math.factorial(cells) / math.prod(math.factorial(len(g)) for g in groups)
        else:
            size = math.factorial(len(groups)) ** len(groups[0])
        print(f"{name:22s} N={cells:3d} perms={size:9.3g} prism exact={ex!s:24.24s} ours={oe!s:24.24s} "
              f"pValue={t['pValue']['value']}")


if __name__ == "__main__":
    main()
