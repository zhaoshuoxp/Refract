"""Parity of engine.compute for ONE_SAMPLE_TESTS and NORMALITY_TESTS with Prism.

Column tables with many sample sizes (2..120), ties, zeros/negatives and
values equal to the hypothetical mean; several option variants.

Usage: .venv/bin/python -I tools/column_tests_parity.py <out_dir> [--n 6] [--reuse]
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


def _seed(name):
    with open(os.path.join(ROOT, "corpus", "seeds", name)) as f:
        return json.load(f)


OS_BASE, NT_BASE = _seed("one_sample_tests_params.json"), _seed("normality_tests_params.json")
CONFIGS = [  # (name, class, overrides)
    ("os_t", "ONE_SAMPLE_TESTS", {"experimentalDesign": "ONE_SAMPLE_T_TEST"}),
    ("os_t_mu", "ONE_SAMPLE_TESTS", {"experimentalDesign": "ONE_SAMPLE_T_TEST", "calc/hypotheticalValue": 10.0,
                                     "options/significanceLevel": 0.01}),
    ("os_w", "ONE_SAMPLE_TESTS", {"experimentalDesign": "WILCOXON_SIGNED_RANK_TEST"}),
    ("os_w_mu", "ONE_SAMPLE_TESTS", {"experimentalDesign": "WILCOXON_SIGNED_RANK_TEST", "calc/hypotheticalValue": 10.0}),
    ("os_w_nopratt", "ONE_SAMPLE_TESTS", {"experimentalDesign": "WILCOXON_SIGNED_RANK_TEST", "calc/hypotheticalValue": 10.0,
                                          "calc/usePrattMethod": False}),
    ("nt_all", "NORMALITY_TESTS", {"calc/testforLognormality": True, "calc/testRelativeLikelihood": True}),
    ("nt_sub", "NORMALITY_TESTS", {"calc/tests/andersonDarling": False, "calc/tests/dAgostinoPearson": False,
                                   "options/significanceLevel": 0.1}),
]


def params(cls, overrides):
    c = copy.deepcopy(OS_BASE if cls == "ONE_SAMPLE_TESTS" else NT_BASE)
    for path, v in overrides.items():
        d = c
        *head, last = path.split("/")
        for h in head:
            d = d.setdefault(h, {})
        d[last] = v
    return c


SIZES = [2, 3, 4, 5, 6, 7, 8, 9, 12, 20, 35, 60, 120]


def gen(n_sets: int, seed: int = 9):
    rnd = random.Random(seed)
    out = []
    for i in range(n_sets):
        cols = []
        for c, n in enumerate(SIZES):
            kind = (i + c) % 4
            if kind == 0:
                v = [rnd.gauss(10, 2) for _ in range(n)]
            elif kind == 1:
                v = [rnd.lognormvariate(2.2, 0.5) for _ in range(n)]
            elif kind == 2:
                v = [rnd.uniform(5, 15) for _ in range(n)]
            else:
                v = [round(rnd.gauss(10, 1.5)) for _ in range(n)]  # ties, exact 10s
            if i % 3 == 2 and n > 3:
                v[0] = 0.0 if c % 2 else -1.5  # impossible for lognormal
            cols.append([round(x, 4) for x in v])
        out.append((f"ct{i:02d}", cols))
    return out


def normalise(c: dict) -> dict:
    c = copy.deepcopy(c)
    if "samples" in c:
        c["samples"] = {str(v["id"]["col"]["idx"]): v["value"] for v in c["samples"].values()}
    return c


def compare_all(sets, res):
    acc, missing = collections.defaultdict(list), collections.Counter()
    for name, cols in sets:
        titles = [f"n{n}" for n in SIZES]
        for cfg in CONFIGS:
            theirs = res.get(name, {}).get(cfg[0])
            if theirs is None:
                continue
            ours = engine.compute(cfg[1], params(cfg[1], cfg[2]), cols, titles)
            o, t = dict(leaves(normalise(ours))), dict(leaves(normalise(theirs)))
            for p_, v in t.items():
                if p_.endswith(("/idx", "/title")):
                    continue
                parts = p_.split("/")
                g = cfg[0] + "/".join(f"n{SIZES[int(x)]}" if (k == 2 and x.isdigit()) else x for k, x in enumerate(parts))
                if p_ not in o:
                    missing[g] += 1
                    continue
                acc[g].append(close(o[p_], v))
            for p_ in o:
                if p_ not in t:
                    parts = p_.split("/")
                    missing["EXTRA " + cfg[0] + "/".join(f"n{SIZES[int(x)]}" if (k == 2 and x.isdigit()) else x
                                                         for k, x in enumerate(parts))] += 1
    return acc, missing


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--n", type=int, default=6)
    ap.add_argument("--reuse", action="store_true")
    a = ap.parse_args()
    sets = gen(a.n)
    rp = os.path.join(a.out, "results.json")
    if a.reuse and os.path.exists(rp):
        with open(rp) as f:
            res = json.load(f)
    else:
        cases = [O.Case(name, [TableSpec("C", "column", "y_single", [DataSet(f"n{n}", [c]) for n, c in zip(SIZES, cols, strict=True)])],
                        [(c[1], params(c[1], c[2]), 0, c[0]) for c in CONFIGS]) for name, cols in sets]
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
    print(f"   {good} fields agree to <= 1e-9 relative (or 1e-13 absolute)")
    for k, v in sorted(missing.items()):
        print(f"   missing {v:3d}  {k}")


if __name__ == "__main__":
    main()
