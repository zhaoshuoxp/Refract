"""Parity of the mixed-effects (REML) fits Prism uses for repeated measures
with missing values: one-way (ONE_WAY_ANOVA, REPEATED_MEASURES_ANOVA) and
two-way (TWO_WAY_ANOVA, the three RM designs), with post tests.

Usage: .venv/bin/python -I tools/mixed_parity.py <out_dir> [--n 10] [--reuse]
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import anova_parity as A
import stats_oracle as O
import twoway_parity as T

from refract.formats.bundle_builder import DataSet, TableSpec
from refract.stats import engine

OW_CONFIGS = [  # (name, pairwise design, mc type, test, overrides)
    ("ow_tukey", "ALL_VS_ALL", "STATISTICAL", "TUKEY", {}),
    ("ow_dunnett", "CONTROL_VS_ALL", "STATISTICAL", "DUNNET", {}),
    ("ow_holm", "ALL_VS_ALL", "STATISTICAL", "HOLM_SIDAK", {}),
    ("ow_sph", "ALL_VS_ALL", "STATISTICAL", "TUKEY", {"repeatedMeasures/assumeSphericity": True}),
]
TW_NAMES = ("br_row", "br_col", "br_cell", "bc_col", "bc_row", "bc_cell", "bc_col_sph", "bb_row", "bb_col", "bb_cell",
            "bb_sph", "br_s_rwc", "br_s_cwr", "bc_s_cwr", "bb_s_cwr")
TW_CONFIGS = [c for c in T.CONFIGS if c[0] in TW_NAMES]
# Known, not reproduced:
# - fits where Prism removed two or more random effects (warning
#   RANDOM_EFFECTS_REMOVED): its remaining estimate is not the REML optimum of
#   the reduced model (our -log L is lower), so those fits are skipped;
# - Dunnett after a one-way mixed-model fit: the correlation Prism uses is not
#   found (closest rule: paired n vs the control's n, exact for 4 of 10 sets).
KNOWN_CONFIGS = {"ow_dunnett"}


def gen_ow(n_sets: int, seed: int = 41):
    rnd = random.Random(seed)
    out = []
    for i in range(n_sets):
        k, n = rnd.choice([3, 4, 5]), rnd.choice([4, 5, 6, 8])
        subj = [rnd.gauss(0, 2) for _ in range(n)]
        cols = [[round(10 + j * rnd.uniform(0, 1.5) + subj[s] + rnd.gauss(0, 1 + 0.3 * j), 3) for s in range(n)] for j in range(k)]
        for _ in range(rnd.randint(1, 3)):
            j, s = rnd.randrange(k), rnd.randrange(n)
            if sum(v is not None for v in cols[j]) > 2:
                cols[j][s] = None
        out.append((f"ow{i:02d}_k{k}n{n}", cols))
    return out


def gen_tw(n_sets: int, seed: int = 43):
    """Incomplete grouped tables: columns[c][s][r] with 1-3 missing values."""
    rnd = random.Random(seed)
    out = []
    for i in range(n_sets):
        nr, nc, reps = rnd.choice([2, 3, 4]), rnd.choice([2, 3]), rnd.choice([3, 4, 5])
        subj = [[rnd.gauss(0, 1.5) for _ in range(reps)] for _ in range(max(nr, nc))]
        cols = [[[round(10 + r * 0.8 + c * 0.6 + subj[c % len(subj)][s] + rnd.gauss(0, 1.0 + 0.3 * r), 3) for r in range(nr)]
                 for s in range(reps)] for c in range(nc)]
        for _ in range(rnd.randint(1, 3)):
            c, s, r = rnd.randrange(nc), rnd.randrange(reps), rnd.randrange(nr)
            if sum(1 for ss in range(reps) if cols[c][ss][r] is not None) > 2:
                cols[c][s][r] = None
        out.append((f"tw{i:02d}_r{nr}c{nc}n{reps}", cols))
    return out


def ow_params(pw, mct, test, ov):
    return A.params("REPEATED_MEASURES_ANOVA", pw, mct, test, ov)


def compare_all(ow_sets, tw_sets, res):
    acc, missing = collections.defaultdict(list), collections.Counter()
    for name, cols in ow_sets:
        for cfg in OW_CONFIGS:
            theirs = res.get(name, {}).get(cfg[0])
            if theirs is None:
                continue
            try:
                ours = engine.compute("ONE_WAY_ANOVA", ow_params(*cfg[1:]), cols, [chr(65 + i) for i in range(len(cols))])
            except Exception as ex:  # noqa: BLE001 - report and keep comparing
                missing[f"{cfg[0]}: ERROR {type(ex).__name__}: {ex}"[:100]] += 1
                continue
            o, t = A.normalise(ours), A.normalise(theirs)
            for d in (o, t):
                for m in d.values():
                    if isinstance(m, dict):
                        m.pop("compactLetterDisplay", None)
            A.cmp(o, t, cfg[0], acc, missing)
    for name, cols in tw_sets:
        for cfg in TW_CONFIGS:
            theirs = res.get(name, {}).get(cfg[0])
            if theirs is None:
                continue
            if "RANDOM_EFFECTS_REMOVED" in theirs.get("status", {}).get("warning", []):
                missing["known: two or more random effects removed (skipped)"] += 1
                continue
            titles = [chr(65 + i) for i in range(len(cols))]
            rows = [f"R{r + 1}" for r in range(len(cols[0][0]))]
            try:
                ours = engine.compute("TWO_WAY_ANOVA", T.params(*cfg[1:7]), cols, titles, rows)
            except Exception as ex:  # noqa: BLE001 - report and keep comparing
                missing[f"{cfg[0]}: ERROR {type(ex).__name__}: {ex}"[:100]] += 1
                continue
            T.cmp(T.normalise(ours), T.normalise(theirs), cfg[0], acc, missing)
    return acc, missing


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--n", type=int, default=10)
    ap.add_argument("--reuse", action="store_true")
    a = ap.parse_args()
    ow_sets, tw_sets = gen_ow(a.n), gen_tw(a.n)
    rp = os.path.join(a.out, "results.json")
    if a.reuse and os.path.exists(rp):
        with open(rp) as f:
            res = json.load(f)
    else:
        cases = []
        for name, cols in ow_sets:
            spec = TableSpec("G", "column", "y_single", [DataSet(chr(65 + i), [c]) for i, c in enumerate(cols)])
            cases.append(O.Case(name, [spec], [("ONE_WAY_ANOVA", ow_params(*c[1:]), 0, c[0]) for c in OW_CONFIGS]))
        for name, cols in tw_sets:
            nr = len(cols[0][0])
            spec = TableSpec("G", "grouped", "y_replicates", [DataSet(chr(65 + i), col) for i, col in enumerate(cols)],
                             row_titles=[f"R{r + 1}" for r in range(nr)], replicates=len(cols[0]))
            cases.append(O.Case(name, [spec], [("TWO_WAY_ANOVA", T.params(*c[1:7]), 0, c[0]) for c in TW_CONFIGS]))
        res = O.run(cases, a.out, timeout=40)
    acc, missing = compare_all(ow_sets, tw_sets, res)
    good = 0
    for k in sorted(acc):
        w = max(acc[k])
        if k.split("/")[0] in KNOWN_CONFIGS and "multipleComparisons/tests" in k and w > 1e-6:
            print(f"   known {w:9.2e}  {k}")
            continue
        if w <= 1e-6:
            good += 1
        else:
            print(f"   {w:9.2e}  {k}  (n={len(acc[k])})")
    print(f"   {good} field groups agree to 1e-6")
    for k, v in sorted(missing.items()):
        print(f"   missing {v:3d}  {k}")


if __name__ == "__main__":
    main()
