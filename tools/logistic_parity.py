"""Parity of simple logistic regression (SIMPLE_LOGISTIC_REGRESSION) with
Prism on generated XY tables with 0/1 outcomes.

Usage: .venv/bin/python -I tools/logistic_parity.py <out_dir> [--reuse]
"""

from __future__ import annotations

import argparse
import collections
import copy
import json
import math
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import stats_oracle as O
import table_oracle as TO
from anova_parity import close, leaves

from refract.formats.bundle_builder import DataSet, TableSpec
from refract.stats import logistic as LG

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
with open(os.path.join(ROOT, "corpus", "seeds", "simple_logistic_regression_params.json")) as _f:
    BASE = json.load(_f)
CONFIGS = [("l95", {}), ("l90", {"options/confidenceLevel": 90.0})]
SKIP = ()


def params(ov):
    c = copy.deepcopy(BASE)
    for path, v in ov.items():
        d = c
        *head, last = path.split("/")
        for h in head:
            d = d.setdefault(h, {})
        d[last] = v
    return c


def gen(n_sets: int = 10, seed: int = 71):
    rnd = random.Random(seed)
    out = []
    for i in range(n_sets):
        n = rnd.choice([15, 25, 40, 80])
        slope, mid = rnd.uniform(0.3, 2.0), rnd.uniform(3, 7)
        x = [round(rnd.uniform(0, 10), 2) for _ in range(n)]
        y = [1 if rnd.random() < 1 / (1 + math.exp(-(v - mid) * slope)) else 0 for v in x]
        if sum(y) in (0, n):
            y[0] = 1 - y[0]
        if i % 3 == 2:
            y[1] = None
        out.append((f"lg{i:02d}_n{n}", x, y))
    return out


def norm(c):
    return {k: (list(v.values())[0]["value"] if k == "models" else v) for k, v in c.items()}


def compare_all(sets, res):
    acc, missing = collections.defaultdict(list), collections.Counter()
    for name, x, y in sets:
        for cname, ov in CONFIGS:
            theirs = res.get(name, {}).get(cname)
            if theirs is None:
                missing[f"{cname}: no Prism result"] += 1
                continue
            o, t = dict(leaves(norm(LG.simple_logistic(params(ov), x, y)))), dict(leaves(norm(theirs["results"])))
            for k, v in t.items():
                if k.endswith(("/uid", "/title", "/equation")) or k.endswith(SKIP):
                    continue
                if k not in o:
                    missing[f"{cname}{k}"] += 1
                    continue
                acc[cname + k].append(close(o[k], v))
    return acc, missing


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--reuse", action="store_true")
    a = ap.parse_args()
    sets = gen()
    cases = [O.Case(name, [TableSpec("XY", "xy", "y_single", [DataSet("Y", [y])], x_title="X", x_values=x)],
                    [("SIMPLE_LOGISTIC_REGRESSION", params(ov), 0, cn) for cn, ov in CONFIGS]) for name, x, y in sets]
    res = TO.run_tables(cases, a.out, timeout=60, reuse=a.reuse)
    acc, missing = compare_all(sets, res)
    good = 0
    for k in sorted(acc):
        w = max(acc[k])
        if w <= 1e-8:
            good += 1
        else:
            print(f"   {w:9.2e}  {k}  (bad {sum(1 for v in acc[k] if v > 1e-8)}/{len(acc[k])})")
    print(f"   {good} field groups agree")
    for k, v in sorted(missing.items()):
        print(f"   missing {v:3d}  {k}")


if __name__ == "__main__":
    main()
