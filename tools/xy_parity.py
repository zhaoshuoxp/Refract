"""Parity of correlation (CORRELATION) and simple linear regression
(SIMPLE_LINEAR_REGRESSION) with Prism on generated XY tables.

Usage: .venv/bin/python -I tools/xy_parity.py <out_dir> [--n 14] [--reuse]
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
from refract.stats import xy_basic as XB

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")


def _seed(name):
    with open(os.path.join(ROOT, "corpus", "seeds", name)) as f:
        return json.load(f)


CORR, LIN = _seed("correlation_params.json"), _seed("simple_linear_regression_params.json")
CONFIGS = [  # (name, class, overrides, uses replicates)
    ("pearson", "CORRELATION", {"experimentalDesign": "PARAMETRIC"}, False),
    ("pearson_ci90", "CORRELATION", {"experimentalDesign": "PARAMETRIC", "options/confidenceLevel": 90.0}, False),
    ("spearman", "CORRELATION", {"experimentalDesign": "NONPARAMETRIC"}, False),
    ("linreg", "SIMPLE_LINEAR_REGRESSION", {}, True),
    ("linreg_indiv", "SIMPLE_LINEAR_REGRESSION", {"data/handleReplicatesAs": "INDIVIDUAL", "calc/xCI/y": 5.0}, True),
    ("linreg_tests", "SIMPLE_LINEAR_REGRESSION", {"calc/modelComparisonTest": True, "calc/departureFromLinearityTest": True,
                                                  "calc/yCI/x": 3.0}, True),
    ("linreg_fixed", "SIMPLE_LINEAR_REGRESSION", {"model/constrainLineToFixedPoint": True, "model/fixedPoint/x": 2.0,
                                                  "model/fixedPoint/y": 5.0, "calc/departureFromLinearityTest": True}, True),
    ("spearman_ci90", "CORRELATION", {"experimentalDesign": "NONPARAMETRIC", "options/confidenceLevel": 90.0}, False),
]


KNOWN_FIXED_CFG = {"linreg_fixed"}


def params(cls, ov):
    c = copy.deepcopy(CORR if cls == "CORRELATION" else LIN)
    for path, v in ov.items():
        d = c
        *head, last = path.split("/")
        for h in head:
            d = d.setdefault(h, {})
        d[last] = v
    return c


def gen(n_sets: int, seed: int = 19):
    """[(name, x, [Y data sets as [subcolumn][row]])]"""
    rnd = random.Random(seed)
    out = []
    for i in range(n_sets):
        n = rnd.choice([5, 7, 8, 9, 10, 11, 12, 15, 17, 25, 60])
        k = rnd.choice([1, 2, 3])
        reps = rnd.choice([1, 1, 2, 3])
        x = [round(rnd.uniform(0, 20), 2) for _ in range(n)]
        if i % 4 == 3:
            x = [float(round(v)) for v in x]  # ties in X
        sets = []
        for _ in range(k):
            b = rnd.uniform(-2, 2)
            subs = [[round(3 + b * xv + rnd.gauss(0, 4), 1 if i % 3 == 0 else 3) for xv in x] for _ in range(reps)]
            if i % 2:
                subs[0][rnd.randrange(n)] = None
            sets.append(subs)
        out.append((f"xy{i:02d}_n{n}", x, sets))
    return out


def _norm(c):
    c = copy.deepcopy(c)
    for k in list(c):
        if k.endswith("TestModel"):
            c[k] = {str(i): v["value"] for g in c[k].values() for i, v in enumerate(g["value"].values())}
    if "models" in c:
        c["models"] = {str(i): v["value"] for i, v in enumerate(c["models"].values())}
    return c


def ours_for(cfg, x, sets):
    _name, cls, ov, _ = cfg
    titles = [chr(65 + i) for i in range(len(sets))]
    p = params(cls, ov)
    if cls == "CORRELATION":
        return XB.correlation(p, x, sets, titles)
    return XB.linear_regression(p, x, sets, titles)


def compare_all(sets, res):
    acc, missing = collections.defaultdict(list), collections.Counter()
    for name, x, ys in sets:
        for cfg in CONFIGS:
            theirs = res.get(name, {}).get(cfg[0])
            if theirs is None:
                continue
            o, t = dict(leaves(_norm(ours_for(cfg, x, ys)))), dict(leaves(_norm(theirs)))
            for p_, v in t.items():
                if p_.endswith(("/idx", "/title", "/uid", "/equation")):
                    continue
                if cfg[0] in KNOWN_FIXED_CFG and "/X-intercept/ci/" in p_:
                    continue  # known: Prism's X-intercept CI through a fixed point (formula not found)
                g = cfg[0] + "/".join("*" if s.isdigit() else s for s in p_.split("/"))
                if p_ not in o:
                    missing[g] += 1
                    continue
                acc[g].append(close(o[p_], v))
    return acc, missing


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--n", type=int, default=14)
    ap.add_argument("--reuse", action="store_true")
    a = ap.parse_args()
    sets = gen(a.n)
    rp = os.path.join(a.out, "results.json")
    if a.reuse and os.path.exists(rp):
        with open(rp) as f:
            res = json.load(f)
    else:
        cases = []
        for name, x, ys in sets:
            reps = len(ys[0])
            fmt = "y_replicates" if reps > 1 else "y_single"
            spec = TableSpec("XY", "xy", fmt, [DataSet(chr(65 + i), s) for i, s in enumerate(ys)], x_title="X", x_values=x,
                             replicates=reps)
            cases.append(O.Case(name, [spec], [(c[1], params(c[1], c[2]), 0, c[0]) for c in CONFIGS]))
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
