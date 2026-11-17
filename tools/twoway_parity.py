"""Parity of refract.stats.engine (TWO_WAY_ANOVA) with Prism.

Generates grouped tables (rows x data sets x replicates), adds one
TWO_WAY_ANOVA per configuration, lets Prism compute and re-save, and compares
every results field with engine.compute.

Usage: .venv/bin/python -I tools/twoway_parity.py <out_dir> [--n 12] [--reuse] [--only a,b]
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
with open(os.path.join(ROOT, "corpus", "seeds", "twoway_params.json")) as _f:
    BASE = json.load(_f)

PT = "postTests/pairwiseTests/"
RWC, CWR = "COMPARE_CELLS_BY_ROWS_WITHIN_COLUMNS_", "COMPARE_CELLS_BY_COLUMNS_WITHIN_ROWS_"
ORD, BR, BC, BB = "ORDINARY_ANOVA", "REPEATED_MEASURES_BY_ROWS", "REPEATED_MEASURES_BY_COLS", "REPEATED_MEASURES_BY_BOTH_FACTORS"
# (name, design, meansDesignType, pairwise design, multipleComparisons.type, test, overrides)
CONFIGS = [
    ("o_col_tukey", ORD, "COMPARE_COLUMNS", "ALL_VS_ALL", "STATISTICAL", "TUKEY", {}),
    ("o_col_bonf", ORD, "COMPARE_COLUMNS", "ALL_VS_ALL", "STATISTICAL", "BONFERRONI_SIDAK", {}),
    ("o_col_holm", ORD, "COMPARE_COLUMNS", "ALL_VS_ALL", "STATISTICAL", "HOLM_SIDAK", {}),
    ("o_col_nk", ORD, "COMPARE_COLUMNS", "ALL_VS_ALL", "STATISTICAL", "NEWMAN_KEULS", {}),
    ("o_col_fdr", ORD, "COMPARE_COLUMNS", "ALL_VS_ALL", "FDR", "TUKEY", {}),
    ("o_col_lsd", ORD, "COMPARE_COLUMNS", "ALL_VS_ALL", "NO_CORRECTION", "TUKEY", {}),
    ("o_col_dunnett", ORD, "COMPARE_COLUMNS", "CONTROL_VS_ALL", "STATISTICAL", "DUNNET", {}),
    ("o_row_tukey", ORD, "COMPARE_ROWS", "ALL_VS_ALL", "STATISTICAL", "TUKEY", {}),
    ("o_row_dunnett", ORD, "COMPARE_ROWS", "CONTROL_VS_ALL", "STATISTICAL", "DUNNET", {}),
    ("o_cell_tukey", ORD, "COMPARE_CELLS", "ALL_VS_ALL", "STATISTICAL", "TUKEY", {}),
    ("o_cell_bonf", ORD, "COMPARE_CELLS", "ALL_VS_ALL", "STATISTICAL", "BONFERRONI_SIDAK", {}),
    ("o_noint_col", ORD, "COMPARE_COLUMNS", "ALL_VS_ALL", "STATISTICAL", "TUKEY", {"options/includeInteractionTerm": False}),
    ("o_col_swap", ORD, "COMPARE_COLUMNS", "ALL_VS_ALL", "STATISTICAL", "TUKEY", {PT + "options/swapDirection": True}),
    ("br_row", BR, "COMPARE_ROWS", "ALL_VS_ALL", "STATISTICAL", "TUKEY", {}),
    ("br_col", BR, "COMPARE_COLUMNS", "ALL_VS_ALL", "STATISTICAL", "TUKEY", {}),
    ("br_cell", BR, "COMPARE_CELLS", "ALL_VS_ALL", "STATISTICAL", "TUKEY", {}),
    ("bc_col", BC, "COMPARE_COLUMNS", "ALL_VS_ALL", "STATISTICAL", "BONFERRONI_SIDAK", {}),
    ("bc_row", BC, "COMPARE_ROWS", "ALL_VS_ALL", "STATISTICAL", "TUKEY", {}),
    ("bc_cell", BC, "COMPARE_CELLS", "ALL_VS_ALL", "STATISTICAL", "TUKEY", {}),
    ("bc_col_sph", BC, "COMPARE_COLUMNS", "ALL_VS_ALL", "STATISTICAL", "TUKEY", {"repeatedMeasures/assumeSphericity": True}),
    ("bb_row", BB, "COMPARE_ROWS", "ALL_VS_ALL", "STATISTICAL", "TUKEY", {}),
    ("bb_col", BB, "COMPARE_COLUMNS", "ALL_VS_ALL", "STATISTICAL", "TUKEY", {}),
    ("bb_cell", BB, "COMPARE_CELLS", "ALL_VS_ALL", "STATISTICAL", "TUKEY", {}),
    ("bb_sph", BB, "NO_TESTS", "ALL_VS_ALL", "STATISTICAL", "TUKEY", {"repeatedMeasures/assumeSphericity": True}),
    # simple effects (names from a Prism-made sample, corpus/manual/tw_simple.prism)
    ("s_rwc_sep_tukey", ORD, RWC + "SEPARATE_FAMILIES", "ALL_VS_ALL", "STATISTICAL", "TUKEY", {}),
    ("s_rwc_one_tukey", ORD, RWC + "SINGLE_FAMILY", "ALL_VS_ALL", "STATISTICAL", "TUKEY", {}),
    ("s_cwr_sep_tukey", ORD, CWR + "SEPARATE_FAMILIES", "ALL_VS_ALL", "STATISTICAL", "TUKEY", {}),
    ("s_cwr_one_tukey", ORD, CWR + "SINGLE_FAMILY", "ALL_VS_ALL", "STATISTICAL", "TUKEY", {}),
    ("s_cwr_sep_bonf", ORD, CWR + "SEPARATE_FAMILIES", "ALL_VS_ALL", "STATISTICAL", "BONFERRONI_SIDAK", {}),
    ("s_cwr_one_holm", ORD, CWR + "SINGLE_FAMILY", "ALL_VS_ALL", "STATISTICAL", "HOLM_SIDAK", {}),
    ("s_rwc_sep_nk", ORD, RWC + "SEPARATE_FAMILIES", "ALL_VS_ALL", "STATISTICAL", "NEWMAN_KEULS", {}),
    ("s_cwr_sep_dunnett", ORD, CWR + "SEPARATE_FAMILIES", "CONTROL_VS_ALL", "STATISTICAL", "DUNNET", {}),
    ("s_rwc_one_dunnett", ORD, RWC + "SINGLE_FAMILY", "CONTROL_VS_ALL", "STATISTICAL", "DUNNET", {}),
    ("s_cwr_one_fdr", ORD, CWR + "SINGLE_FAMILY", "ALL_VS_ALL", "FDR", "TUKEY", {}),
    ("s_rwc_sep_lsd", ORD, RWC + "SEPARATE_FAMILIES", "ALL_VS_ALL", "NO_CORRECTION", "TUKEY", {}),
    ("br_s_rwc", BR, RWC + "SEPARATE_FAMILIES", "ALL_VS_ALL", "STATISTICAL", "TUKEY", {}),
    ("br_s_cwr", BR, CWR + "SEPARATE_FAMILIES", "ALL_VS_ALL", "STATISTICAL", "TUKEY", {}),
    ("bc_s_cwr", BC, CWR + "SEPARATE_FAMILIES", "ALL_VS_ALL", "STATISTICAL", "TUKEY", {}),
    ("bc_s_rwc", BC, RWC + "SINGLE_FAMILY", "ALL_VS_ALL", "STATISTICAL", "BONFERRONI_SIDAK", {}),
    ("bb_s_cwr", BB, CWR + "SEPARATE_FAMILIES", "ALL_VS_ALL", "STATISTICAL", "TUKEY", {}),
    ("bb_s_rwc", BB, RWC + "SINGLE_FAMILY", "ALL_VS_ALL", "STATISTICAL", "TUKEY", {}),
]


def params(design, md, pw, mct, test, overrides=None):
    c = copy.deepcopy(BASE)
    c["experimentalDesign"] = design
    p = c["postTests"]
    p["type"] = "PAIRWISE_TESTS" if md != "NO_TESTS" else "NO_TESTS"
    p["pairwiseTests"]["meansDesignType"] = md
    p["pairwiseTests"]["pairwiseDesign"]["type"] = pw
    p["pairwiseTests"]["pairwiseDesign"]["controlID"] = {"col": {"idx": 0}, "row": {"idx": 0}}
    p["pairwiseTests"]["multipleComparisons"]["type"] = mct
    p["pairwiseTests"]["multipleComparisons"]["statistical"]["test"] = test
    for path, v in (overrides or {}).items():
        d = c
        *head, last = path.split("/")
        for h in head:
            d = d[h]
        d[last] = v
    return c


def gen(n_sets: int, seed: int = 7):
    """[(name, columns[c][s][r], complete)] -- complete sets are balanced with
    no missing values (usable by the RM designs)."""
    rnd = random.Random(seed)
    out = []
    for i in range(n_sets):
        nr, nc, reps = rnd.choice([2, 3, 4]), rnd.choice([2, 3, 4]), rnd.choice([3, 4, 5])
        complete = i % 3 != 2
        rowe = [rnd.uniform(-3, 3) for _ in range(nr)]
        cole = [rnd.uniform(-3, 3) for _ in range(nc)]
        subj = [[rnd.gauss(0, 1.5) for _ in range(reps)] for _ in range(max(nr, nc))]
        cols = []
        for c in range(nc):
            subs = []
            for s in range(reps):
                vals = []
                for r in range(nr):
                    v = 10 + rowe[r] + cole[c] + 0.5 * rowe[r] * cole[c] / 3 + subj[c % len(subj)][s] + rnd.gauss(0, 1.0)
                    vals.append(round(v, 3))
                subs.append(vals)
            cols.append(subs)
        if not complete:  # drop a few values, never emptying a cell
            for _ in range(rnd.randint(1, 4)):
                c, s, r = rnd.randrange(nc), rnd.randrange(reps), rnd.randrange(nr)
                if sum(1 for ss in range(reps) if cols[c][ss][r] is not None) > 1:
                    cols[c][s][r] = None
        out.append((f"tw{i:02d}_r{nr}c{nc}n{reps}{'' if complete else '_unb'}", cols, complete))
    return out


def _item_key(idd: dict) -> str:
    parts = []
    if "col" in idd:
        parts.append(f"c{idd['col']['idx']}")
    if "row" in idd:
        parts.append(f"r{idd['row']['idx']}")
    return "".join(parts)


def normalise(content: dict) -> dict:
    c = copy.deepcopy(content)
    for k, m in c.items():
        if not (k.endswith("Model") and isinstance(m, dict)):
            continue
        m.pop("compactLetterDisplay", None)
        mn = m.get("means")
        if mn:
            mn["rows"] = {_item_key(v["id"]): v["value"] for v in mn.get("rows", {}).values()}
            mn["cols"] = {_item_key(v["id"]): v["value"] for v in mn.get("cols", {}).values()}
            mn["cells"] = {_item_key(v["id"]): {_item_key(w["id"]): w["value"] for w in v["value"].values()}
                           for v in mn.get("cells", {}).values()}
        mc = m.get("multipleComparisons")
        if mc and "tests" in mc:
            flat = {}
            for g in mc["tests"].values():
                for t in g["value"].values():
                    flat[f"{_item_key(g['id'])}-{_item_key(t['id'])}"] = t["value"]
            mc["tests"] = flat
    return c


def generic(path: str) -> str:
    parts = path.split("/")
    if len(parts) > 4 and parts[3] == "tests":
        parts[4] = "*"
        if len(parts) > 5 and parts[5] in ("sample1", "sample2"):
            parts[5] = "sample"
    if len(parts) > 3 and parts[2] == "means" and parts[3] in ("rows", "cols", "cells"):
        parts[4:5] = ["*"]
        if parts[3] == "cells" and len(parts) > 5:
            parts[5] = "*"
    return "/".join(parts)


def cmp(ours, theirs, scope, acc, missing):
    o, t = dict(leaves(ours)), dict(leaves(theirs))
    for p_, v in t.items():
        if p_.endswith(("/idx", "/uid", "/title")) or (p_.endswith("/level") and not isinstance(v, float)):
            continue
        key = scope + generic(p_)
        if p_ not in o:
            missing[key] += 1
            continue
        if p_.endswith(("CI/lower", "CI/upper")) and isinstance(v, float) and isinstance(o[p_], float):
            acc[key].append(0.0 if abs(o[p_] - v) <= 1e-9 * max(1.0, abs(v)) else abs(o[p_] - v) / max(abs(v), 1.0))
        else:
            acc[key].append(close(o[p_], v))
    for p_ in o:
        if p_ not in t and not p_.endswith(("/idx", "/title")):
            missing[f"EXTRA {scope}{generic(p_)}"] += 1


def compare_all(sets, res):
    acc, missing = collections.defaultdict(list), collections.Counter()
    for name, cols, _ in sets:
        for cfg in CONFIGS:
            theirs = res.get(name, {}).get(cfg[0])
            if theirs is None:
                continue
            titles = [chr(65 + i) for i in range(len(cols))]
            rows = [f"R{r + 1}" for r in range(len(cols[0][0]))]
            try:
                ours = engine.compute("TWO_WAY_ANOVA", params(*cfg[1:7]), cols, titles, rows)
            except NotImplementedError as ex:
                missing[f"{cfg[0]}: not implemented ({ex})"] += 1
                continue
            o, t = normalise(ours), normalise(theirs)
            nr, nc = len(cols[0][0]), len(cols)
            if cfg[1] == BB and {nr, nc} == {3, 4}:
                # known deviation: Prism's GG epsilon for the row factor and the
                # interaction of 3 x 4 / 4 x 3 both-factors RM tables (findings.md)
                for d in (o, t):
                    tab = d["repeatedMeasuresGlmAnovaModel"]["anovaTable"]
                    for k in ("rowFactor", "rowFactorVsColFactor"):
                        tab[k].pop("ggEpsilon", None)
                        tab[k].pop("fTest", None)
                missing["known: BB 3x4 epsilon skipped"] += 1
            cmp(o, t, cfg[0], acc, missing)
    return acc, missing


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--n", type=int, default=12)
    ap.add_argument("--reuse", action="store_true")
    ap.add_argument("--only")
    a = ap.parse_args()
    only = set(a.only.split(",")) if a.only else None
    sets = gen(a.n)
    res_path = os.path.join(a.out, "results.json")
    if a.reuse and os.path.exists(res_path):
        with open(res_path) as f:
            res = json.load(f)
    else:
        cases = []
        for name, cols, complete in sets:
            cfgs = [c for c in CONFIGS if (complete or c[1] == ORD) and (only is None or c[0] in only)]
            nr = len(cols[0][0])
            reps = len(cols[0])
            spec = TableSpec("G", "grouped", "y_replicates", [DataSet(chr(65 + i), col) for i, col in enumerate(cols)],
                             row_titles=[f"R{r + 1}" for r in range(nr)], replicates=reps)
            cases.append(O.Case(name, [spec], [("TWO_WAY_ANOVA", params(*c[1:7]), 0, c[0]) for c in cfgs]))
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
