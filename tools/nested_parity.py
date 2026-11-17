"""Parity of the nested t test (NESTED_T_TEST) and nested one-way ANOVA
(ONE_WAY_NESTED_ANOVA) with Prism on generated nested tables.

Usage: .venv/bin/python -I tools/nested_parity.py <out_dir> [--reuse]
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
import table_oracle as TO
from anova_parity import close

from refract.formats.bundle_builder import DataSet, TableSpec

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")


def _seed(k):
    with open(os.path.join(ROOT, "corpus", "seeds", f"{k}_params.json")) as f:
        return json.load(f)


T_BASE, A_BASE = _seed("nested_t_test"), _seed("one_way_nested_anova")
T_CONFIGS = [("t", {}), ("t_noswap", {"options/swapDirection": False}), ("t01", {"options/significanceLevel": 0.01})]
A_CONFIGS = [("a", {})]


def params(base, ov):
    c = copy.deepcopy(base)
    for path, v in ov.items():
        d = c
        *head, last = path.split("/")
        for h in head:
            d = d.setdefault(h, {})
        d[last] = v
    return c


def gen(seed: int = 97):
    """[(name, groups[g][s][values])]"""
    rnd = random.Random(seed)
    out = []
    for i in range(12):
        k = 2 if i < 6 else rnd.choice([3, 4])
        reps = rnd.choice([2, 3, 4, 5])
        sub_sd, res_sd = rnd.choice([0.2, 1.0, 3.0]), rnd.choice([1.0, 2.0])
        groups = []
        for g in range(k):
            mu = 10 + g * rnd.uniform(0, 2)
            subs = []
            for _ in range(reps):
                m = mu + rnd.gauss(0, sub_sd)
                n = rnd.choice([3, 4, 6, 8]) if i % 2 else 5
                subs.append([round(rnd.gauss(m, res_sd), 2) for _ in range(n)])
            groups.append(subs)
        out.append((f"ns{i:02d}_k{k}r{reps}", groups))
    return out


def spec_for(groups):
    reps = len(groups[0])
    nmax = max(len(s) for g in groups for s in g)
    ds = [DataSet(chr(65 + i), [s + [None] * (nmax - len(s)) for s in g]) for i, g in enumerate(groups)]
    return TableSpec("N", "nested", "y_replicates", ds, replicates=reps)


def leaves(o, pre=""):
    if isinstance(o, dict):
        for k, v in o.items():
            yield from leaves(v, f"{pre}/{k}")
    elif isinstance(o, (bool, str)):
        yield pre, o
    elif isinstance(o, (int, float)):
        yield pre, float(o)


def compare_all(sets, res):
    from refract.stats import nested as NS

    acc, missing = collections.defaultdict(list), collections.Counter()
    for name, groups in sets:
        cfgs = T_CONFIGS if len(groups) == 2 else A_CONFIGS
        for cname, ov in cfgs:
            t = res.get(name, {}).get(cname)
            if t is None:
                missing[f"{cname}: no Prism result"] += 1
                continue
            ours = NS.nested_t(params(T_BASE, ov), groups) if len(groups) == 2 else NS.nested_one_way(params(A_BASE, ov), groups)
            o = dict(leaves(ours))
            for k, v in leaves(t["results"]):
                if k not in o:
                    missing[cname + k] += 1
                    continue
                small = isinstance(v, float) and isinstance(o[k], float) and abs(v) < 1e-10 and abs(o[k]) < 1e-10
                acc[cname + k].append(0.0 if small else close(o[k], v))  # e.g. chi2 of a zero variance: 1.7e-13 vs 0
    return acc, missing


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--reuse", action="store_true")
    a = ap.parse_args()
    sets = gen()
    cases = []
    for name, groups in sets:
        if len(groups) == 2:
            an = [("NESTED_T_TEST", params(T_BASE, ov), 0, cn) for cn, ov in T_CONFIGS]
        else:
            an = [("ONE_WAY_NESTED_ANOVA", params(A_BASE, ov), 0, cn) for cn, ov in A_CONFIGS]
        cases.append(O.Case(name, [spec_for(groups)], an))
    res = TO.run_tables(cases, a.out, timeout=60, reuse=a.reuse)
    acc, missing = compare_all(sets, res)
    good = 0
    for k in sorted(acc):
        w = max(acc[k])
        if w <= 1e-6:
            good += 1
        else:
            print(f"   {w:9.2e}  {k}  (bad {sum(1 for v in acc[k] if v > 1e-6)}/{len(acc[k])})")
    print(f"   {good} field groups agree to 1e-6")
    for k, v in sorted(missing.items()):
        print(f"   missing {v:3d}  {k}")


if __name__ == "__main__":
    main()
