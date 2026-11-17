"""Parity of refract.stats.engine (ONE_WAY_ANOVA) with Prism.

Generates column tables, adds one ONE_WAY_ANOVA analysis per configuration,
lets Prism compute and re-save them (stats_oracle), then compares every
results field with ours (engine.compute on the same parameters).

Usage: .venv/bin/python -I tools/anova_parity.py <out_dir> [--n 20] [--reuse] [--only a,b]
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

from refract.formats.bundle_builder import DataSet, TableSpec
from refract.stats import engine

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
with open(os.path.join(ROOT, "corpus", "seeds", "oneway_tukey_params.json")) as _f:
    BASE = json.load(_f)

# (name, design, pairwise design, multipleComparisons.type, test, {param path: value})
CONFIGS = [
    ("ord_tukey", "ORDINARY_ANOVA", "ALL_VS_ALL", "STATISTICAL", "TUKEY", {}),
    ("ord_bonf", "ORDINARY_ANOVA", "ALL_VS_ALL", "STATISTICAL", "BONFERRONI_SIDAK", {}),
    ("ord_holm", "ORDINARY_ANOVA", "ALL_VS_ALL", "STATISTICAL", "HOLM_SIDAK", {}),
    ("ord_nk", "ORDINARY_ANOVA", "ALL_VS_ALL", "STATISTICAL", "NEWMAN_KEULS", {}),
    ("ord_fdr", "ORDINARY_ANOVA", "ALL_VS_ALL", "FDR", "TUKEY", {}),
    ("ord_lsd", "ORDINARY_ANOVA", "ALL_VS_ALL", "NO_CORRECTION", "TUKEY", {}),
    ("ord_dunnett", "ORDINARY_ANOVA", "CONTROL_VS_ALL", "STATISTICAL", "DUNNET", {}),
    ("ord_ctrl_holm", "ORDINARY_ANOVA", "CONTROL_VS_ALL", "STATISTICAL", "HOLM_SIDAK", {}),
    ("ord_ctrl_bonf", "ORDINARY_ANOVA", "CONTROL_VS_ALL", "STATISTICAL", "BONFERRONI_SIDAK", {}),
    ("bf_gh", "BROWN_FORSYTHE_ANOVA", "ALL_VS_ALL", "STATISTICAL", "GAMES_HOWELL", {}),
    ("bf_t3", "BROWN_FORSYTHE_ANOVA", "ALL_VS_ALL", "STATISTICAL", "DUNNET_T3", {}),
    ("bf_t2", "BROWN_FORSYTHE_ANOVA", "ALL_VS_ALL", "STATISTICAL", "TAMHANE_T2", {}),
    ("kw_dunn", "KRUSKAL_WALLIS_TEST", "ALL_VS_ALL", "STATISTICAL", "DUNN", {}),
    ("fr_dunn", "FRIEDMAN_TEST", "ALL_VS_ALL", "STATISTICAL", "DUNN", {}),
    ("rm_tukey", "REPEATED_MEASURES_ANOVA", "ALL_VS_ALL", "STATISTICAL", "TUKEY", {}),
    # options
    ("ord_tukey_a01", "ORDINARY_ANOVA", "ALL_VS_ALL", "STATISTICAL", "TUKEY",
     {"postTests/pairwiseTests/multipleComparisons/statistical/options/significanceLevel": 0.01}),
    ("ord_tukey_swap", "ORDINARY_ANOVA", "ALL_VS_ALL", "STATISTICAL", "TUKEY",
     {"postTests/pairwiseTests/options/swapDirection": True}),
    ("rm_tukey_sph", "REPEATED_MEASURES_ANOVA", "ALL_VS_ALL", "STATISTICAL", "TUKEY",
     {"repeatedMeasures/assumeSphericity": True}),
    ("ord_report", "ORDINARY_ANOVA", "ALL_VS_ALL", "STATISTICAL", "TUKEY",
     {"report/goodnessOfFit": True, "report/effectSizes": True, "report/descriptiveStatistics": True}),
]
PAIRED = ("FRIEDMAN_TEST", "REPEATED_MEASURES_ANOVA")


def params(design, pw, mct, test, overrides=None):
    c = copy.deepcopy(BASE)
    c["experimentalDesign"] = design
    c["postTests"]["type"] = "PAIRWISE_TESTS"
    c["postTests"]["pairwiseTests"]["pairwiseDesign"]["type"] = pw
    c["postTests"]["pairwiseTests"]["pairwiseDesign"]["controlID"]["col"]["idx"] = 0
    c["postTests"]["pairwiseTests"]["multipleComparisons"]["type"] = mct
    c["postTests"]["pairwiseTests"]["multipleComparisons"]["statistical"]["test"] = test
    for path, v in (overrides or {}).items():
        d = c
        *head, last = path.split("/")
        for h in head:
            d = d[h]
        d[last] = v
    return c


def gen(k_sets: int, seed: int = 3):
    rnd = random.Random(seed)
    out = []
    for i in range(k_sets):
        k = rnd.choice([3, 4, 5, 6])
        equal = i % 3 != 2
        n = rnd.choice([3, 4, 5, 6, 8, 10])
        groups = []
        for _ in range(k):
            m = n if equal else rnd.choice([3, 4, 5, 7, 9])
            mu, sd = rnd.uniform(5, 15), rnd.choice([1.0, 2.0, 4.0])
            groups.append([round(rnd.gauss(mu, sd), 2 if i % 4 == 1 else 4) for _ in range(m)])
        out.append((f"set{i:02d}_k{k}_n{n}{'' if equal else '_uneq'}", groups, equal))
    return out


def prism_tests(mc: dict) -> dict:
    """Prism's nested multipleComparisons.tests -> {(i, j): test}."""
    out = {}
    for g in mc.get("tests", {}).values():
        i = g["id"]["col"]["idx"]
        for t in g["value"].values():
            out[(i, t["id"]["col"]["idx"])] = t["value"]
    return out


def normalise(content: dict) -> dict:
    """Re-key hash-keyed maps by column index so ours and Prism's line up;
    drop the compact letter display (not implemented)."""
    c = copy.deepcopy(content)
    if "descriptiveStatistics" in c:
        c["descriptiveStatistics"] = {str(v["id"]["col"]["idx"]): v["value"] for v in c["descriptiveStatistics"].values()}
    for k, m in c.items():
        if k.endswith("Model") and isinstance(m, dict):
            m.pop("compactLetterDisplay", None)
            if "multipleComparisons" in m:
                m["multipleComparisons"]["tests"] = {f"{i}-{j}": t for (i, j), t in prism_tests(m["multipleComparisons"]).items()}
    return c


def leaves(o, prefix=""):
    """Numeric, string and boolean leaves (strings: 'undefined', method names)."""
    if isinstance(o, dict):
        for k, v in o.items():
            yield from leaves(v, f"{prefix}/{k}")
    elif isinstance(o, (bool, str)):
        yield prefix, o
    elif isinstance(o, (int, float)):
        yield prefix, float(o)


def close(a, b) -> float:
    """0 when equal; else relative error, or 0 when within 1e-13 absolute
    (P values from 1 - cdf carry ~1e-15 absolute noise in both programs)."""
    if isinstance(a, (bool, str)) or isinstance(b, (bool, str)):
        return 0.0 if a == b else math.inf
    if math.isnan(a) and math.isnan(b):
        return 0.0
    if abs(a - b) <= 1e-13:
        return 0.0
    return abs(a - b) / max(abs(b), 1e-300)


def generic(path: str) -> str:
    """Field path with the pair / column keys folded (for aggregation)."""
    parts = path.split("/")  # ['', <model>, 'multipleComparisons', 'tests', '0-1', ...]
    if len(parts) > 4 and parts[3] == "tests":
        parts[4] = "*"
        if len(parts) > 5 and parts[5] in ("sample1", "sample2"):
            parts[5] = "sample"
    if len(parts) > 2 and parts[1] == "descriptiveStatistics":
        parts[2] = "*"
    return "/".join(parts)


def cmp(ours: dict, theirs: dict, scope: str, acc, missing) -> None:
    o, t = dict(leaves(ours)), dict(leaves(theirs))
    for p_, v in t.items():
        if p_.endswith(("/idx", "/uid", "/title")) or (p_.endswith("/level") and not isinstance(v, float)):
            continue
        key = scope + generic(p_)
        if p_ not in o:
            missing[key] += 1
            continue
        acc[key].append(close(o[p_], v))


def compare_all(sets, res):
    """Compare engine.compute with Prism's stored results for every data set
    and configuration -> ({field: [relative errors]}, Counter of missing)."""
    acc = collections.defaultdict(list)
    missing = collections.Counter()
    for name, groups, _ in sets:
        for cfg in CONFIGS:
            theirs = res.get(name, {}).get(cfg[0])
            if theirs is None:
                continue
            titles = [chr(65 + i) for i in range(len(groups))]
            try:
                ours = engine.compute("ONE_WAY_ANOVA", params(*cfg[1:6]), groups, titles)
            except NotImplementedError as ex:
                missing[f"{cfg[0]}: not implemented ({ex})"] += 1
                continue
            cmp(normalise(ours), normalise(theirs), cfg[0], acc, missing)
    return acc, missing


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--reuse", action="store_true")
    ap.add_argument("--only", help="comma-separated config names to run in Prism")
    a = ap.parse_args()
    only = set(a.only.split(",")) if a.only else None
    sets = gen(a.n)
    res_path = os.path.join(a.out, "results.json")
    if a.reuse and os.path.exists(res_path):
        with open(res_path) as f:
            res = json.load(f)
    else:
        cases = []
        for name, groups, equal in sets:
            cfgs = [c for c in CONFIGS if (equal or c[1] not in PAIRED) and (only is None or c[0] in only)]
            cases.append(O.Case(name, [TableSpec("G", "column", "y_single", [DataSet(chr(65 + i), [g]) for i, g in enumerate(groups)])],
                                [("ONE_WAY_ANOVA", params(*c[1:6]), 0, c[0]) for c in cfgs]))
        res = O.run(cases, a.out, timeout=20)
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
