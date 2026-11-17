"""Parity of engine.compute(MULTIPLE_TWO_SAMPLE_TESTS) with Prism.

Usage: .venv/bin/python -I tools/multi_t_parity.py <out_dir> [--n 10] [--reuse] [--only a,b]
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
with open(os.path.join(ROOT, "corpus", "seeds", "multi_t_params.json")) as _f:
    BASE = json.load(_f)

EQ, UNEQ = "MULTIPLE_UNPAIRED_TWO_SAMPLE_EQUAL_SD_TESTS", "MULTIPLE_UNPAIRED_TWO_SAMPLE_UNEQUAL_SD_TESTS"
MC = "multipleComparisons/"
CONFIGS = [  # (name, test, overrides)
    ("eq_none", EQ, {}),
    ("uneq_none", UNEQ, {}),
    ("paired_none", "MULTIPLE_PAIRED_TWO_SAMPLE_TESTS", {}),
    ("ratio_none", "MULTIPLE_RATIO_PAIRED_TWO_SAMPLE_TESTS", {}),
    ("mw_none", "MULTIPLE_MANN_WHITNEY_TESTS", {}),
    ("wil_none", "MULTIPLE_WILCOXON_TESTS", {}),
    ("ks_none", "MULTIPLE_KOLMOGOROV_SMIRNOV_TESTS", {}),
    ("eq_holm", EQ, {MC + "type": "STATISTICAL", MC + "statistical/test": "HOLM_SIDAK"}),
    ("eq_bonf", EQ, {MC + "type": "STATISTICAL", MC + "statistical/test": "BONFERRONI_DUNN"}),
    ("eq_sidak", EQ, {MC + "type": "STATISTICAL", MC + "statistical/test": "BONFERRONI_SIDAK"}),
    ("uneq_bky", UNEQ, {MC + "type": "FDR", MC + "fdr/test": "BENJAMINI_KRIEGER_YEKUTIELI", MC + "fdr/options/discoveryLevel": 10.0}),
    ("ks_bonf", "MULTIPLE_KOLMOGOROV_SMIRNOV_TESTS", {MC + "type": "STATISTICAL", MC + "statistical/test": "BONFERRONI_DUNN"}),
    ("ratio_holm", "MULTIPLE_RATIO_PAIRED_TWO_SAMPLE_TESTS", {MC + "type": "STATISTICAL", MC + "statistical/test": "HOLM_SIDAK"}),
    ("wil_by", "MULTIPLE_WILCOXON_TESTS", {MC + "type": "FDR", MC + "fdr/test": "BENJAMINI_YEKUTIELI", MC + "fdr/options/discoveryLevel": 20.0}),
    ("eq_bky1", EQ, {MC + "type": "FDR", MC + "fdr/test": "BENJAMINI_KRIEGER_YEKUTIELI", MC + "fdr/options/discoveryLevel": 1.0}),
    ("eq_bky5", EQ, {MC + "type": "FDR", MC + "fdr/test": "BENJAMINI_KRIEGER_YEKUTIELI", MC + "fdr/options/discoveryLevel": 5.0}),
    ("eq_bh", EQ, {MC + "type": "FDR", MC + "fdr/test": "BENJAMINI_HOCHBERG", MC + "fdr/options/discoveryLevel": 5.0}),
    ("eq_by", EQ, {MC + "type": "FDR", MC + "fdr/test": "BENJAMINI_YEKUTIELI", MC + "fdr/options/discoveryLevel": 5.0}),
    ("paired_holm_a10", "MULTIPLE_PAIRED_TWO_SAMPLE_TESTS",
     {MC + "type": "STATISTICAL", MC + "statistical/test": "HOLM_SIDAK", MC + "statistical/options/significanceLevel": 0.1}),
    ("mw_bh", "MULTIPLE_MANN_WHITNEY_TESTS", {MC + "type": "FDR", MC + "fdr/test": "BENJAMINI_HOCHBERG"}),
    ("eq_swap", EQ, {"options/swapDirection": True}),
    ("wil_swap", "MULTIPLE_WILCOXON_TESTS", {"options/swapDirection": True}),
]


def params(test, overrides):
    c = copy.deepcopy(BASE)
    c["test"] = test
    for path, v in overrides.items():
        d = c
        *head, last = path.split("/")
        for h in head:
            d = d[h]
        d[last] = v
    return c


def gen(n_sets: int, seed: int = 5):
    """[(name, [setA subcols, setB subcols], row titles)]: positive values,
    some missing cells, some coarse rounding (ties)."""
    rnd = random.Random(seed)
    out = []
    for i in range(n_sets):
        rows, reps = rnd.randint(4, 14), rnd.choice([2, 3, 4, 5])
        digits = 1 if i % 3 == 2 else 3
        cols = []
        for c in range(2):
            subs = [[round(abs(rnd.gauss(10 + (r % 4) + 1.5 * c * (r % 2), 1 + r % 3)) + 0.1, digits) for r in range(rows)]
                    for _ in range(reps)]
            cols.append(subs)
        if i % 2:
            for _ in range(rnd.randint(1, 3)):
                cols[rnd.randrange(2)][rnd.randrange(reps)][rnd.randrange(rows)] = None
        out.append((f"mt{i:02d}_r{rows}n{reps}", cols, [f"G{r + 1}" for r in range(rows)]))
    return out


def normalise(c: dict) -> dict:
    c = copy.deepcopy(c)
    if "rows" in c:
        c["rows"] = {str(v["id"]["row"]["idx"]): v["value"] for v in c["rows"].values()}
    return c


def compare_all(sets, res):
    acc, missing = collections.defaultdict(list), collections.Counter()
    for name, cols, rows in sets:
        for cfg in CONFIGS:
            theirs = res.get(name, {}).get(cfg[0])
            if theirs is None:
                continue
            try:
                ours = engine.compute("MULTIPLE_TWO_SAMPLE_TESTS", params(cfg[1], cfg[2]), cols, ["A", "B"], rows)
            except NotImplementedError as ex:
                missing[f"{cfg[0]}: not implemented ({ex})"] += 1
                continue
            o, t = dict(leaves(normalise(ours))), dict(leaves(normalise(theirs)))
            for p_, v in t.items():
                if p_.endswith(("/idx", "/title")):
                    continue
                if p_.endswith("/ratioOfPairs/geometricMeanOfRatios") and \
                        t.get(p_.replace("ratioOfPairs/geometricMeanOfRatios", "ratioPairedTTest/status")) == "TOO_FEW_POINTS":
                    missing["known: ratio TOO_FEW geometric mean skipped"] += 1  # Prism quirk (findings.md)
                    continue
                g = cfg[0] + "/".join("*" if x.isdigit() else x for x in p_.split("/"))
                if p_ not in o:
                    missing[g] += 1
                    continue
                acc[g].append(close(o[p_], v))
            for p_ in o:
                if p_ not in t:
                    missing["EXTRA " + cfg[0] + "/".join("*" if x.isdigit() else x for x in p_.split("/"))] += 1
    return acc, missing


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--n", type=int, default=10)
    ap.add_argument("--reuse", action="store_true")
    ap.add_argument("--only")
    a = ap.parse_args()
    only = set(a.only.split(",")) if a.only else None
    sets = gen(a.n)
    rp = os.path.join(a.out, "results.json")
    if a.reuse and os.path.exists(rp):
        with open(rp) as f:
            res = json.load(f)
    else:
        cases = []
        for name, cols, rows in sets:
            reps = len(cols[0])
            spec = TableSpec("G", "grouped", "y_replicates", [DataSet("A", cols[0]), DataSet("B", cols[1])],
                             row_titles=rows, replicates=reps)
            cases.append(O.Case(name, [spec], [("MULTIPLE_TWO_SAMPLE_TESTS", params(c[1], c[2]), 0, c[0])
                                               for c in CONFIGS if only is None or c[0] in only]))
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
