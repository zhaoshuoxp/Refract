"""Parity of engine.compute(SURVIVAL) with Prism.

Usage: .venv/bin/python -I tools/survival_parity.py <out_dir> [--n 16] [--reuse]
"""

from __future__ import annotations

import argparse
import collections
import copy
import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import stats_oracle as O
from anova_parity import close, leaves

from refract.formats.bundle_builder import DataSet, TableSpec
from refract.stats import engine

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
with open(os.path.join(ROOT, "corpus", "seeds", "survival_params.json")) as _f:
    BASE = json.load(_f)
CONFIGS = [("sv_default", {}), ("sv_gbw_ci90", {"calc/gehanBreslowWilcoxonTest": True, "calc/ciLevel": 90.0})]


def params(ov):
    c = copy.deepcopy(BASE)
    for path, v in ov.items():
        d = c
        *head, last = path.split("/")
        for h in head:
            d = d.setdefault(h, {})
        d[last] = v
    return c


def gen(n_sets: int, seed: int = 17):
    """[(name, x times, [codes per group])]: one subject per row, 2-4 groups,
    tied times in some sets, some heavy censoring."""
    rnd = random.Random(seed)
    out = []
    for i in range(n_sets):
        k = [2, 2, 3, 4][i % 4]
        x, groups = [], [[] for _ in range(k)]
        for g in range(k):
            n = rnd.randint(6, 30)
            rate = rnd.uniform(0.5, 2.0) * (1 + 0.4 * g)
            cens = rnd.choice([0.1, 0.3, 0.6])
            for _ in range(n):
                t = rnd.expovariate(rate) * 100
                t = round(t) if i % 3 == 0 else round(t, 1)  # integer times -> ties
                x.append(max(t, 1))
                for h in range(k):
                    groups[h].append((0 if rnd.random() < cens else 1) if h == g else None)
        out.append((f"sv{i:02d}_k{k}", x, groups))
    return out


def normalise(c):
    c = copy.deepcopy(c)
    if "dataSummary" in c:
        c["dataSummary"] = {str(v["id"]["col"]["idx"]): v["value"] for v in c["dataSummary"].values()}
    return c


def compare_all(sets, res):
    acc, missing = collections.defaultdict(list), collections.Counter()
    for name, x, groups in sets:
        titles = [f"G{g + 1}" for g in range(len(groups))]
        for cfg, ov in CONFIGS:
            theirs = res.get(name, {}).get(cfg)
            if theirs is None:
                continue
            ours = engine.compute("SURVIVAL", params(ov), groups, titles, x_values=x)
            o, t = dict(leaves(normalise(ours))), dict(leaves(normalise(theirs)))
            for p_, v in t.items():
                if p_.endswith(("/idx", "/title", "/uid")) or "/id/" in p_:
                    continue
                g = cfg + "/".join("*" if x_.isdigit() else x_ for x_ in p_.split("/"))
                if p_ not in o:
                    missing[g] += 1
                    continue
                acc[g].append(close(o[p_], v))
            for p_ in o:
                if p_ not in t and not (p_.endswith(("/idx", "/title")) or "/id/" in p_):
                    missing["EXTRA " + cfg + "/".join("*" if x_.isdigit() else x_ for x_ in p_.split("/"))] += 1
    return acc, missing


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--n", type=int, default=16)
    ap.add_argument("--reuse", action="store_true")
    a = ap.parse_args()
    sets = gen(a.n)
    rp = os.path.join(a.out, "results.json")
    if a.reuse and os.path.exists(rp):
        with open(rp) as f:
            res = json.load(f)
    else:
        cases = [O.Case(name, [TableSpec("S", "survival", "y_single", [DataSet(f"G{g + 1}", [codes]) for g, codes in enumerate(groups)],
                                         x_title="Days", x_values=x)],
                        [("SURVIVAL", params(ov), 0, cfg) for cfg, ov in CONFIGS]) for name, x, groups in sets]
        res = O.run(cases, a.out, timeout=30)
    acc, missing = compare_all(sets, res)
    good = 0
    print(f"{len(sets)} data sets")
    for k in sorted(acc):
        w = max(acc[k])
        if w <= 1e-9:
            good += 1
        else:
            print(f"   {w:9.2e}  {k}  (n={len(acc[k])})")
    print(f"   {good} fields agree")
    for k, v in sorted(missing.items()):
        print(f"   missing {v:3d}  {k}")


if __name__ == "__main__":
    main()
