"""Parity of contingency-table analysis (CONTINGENCY_TABLE) with Prism on
generated tables (2 x 2 with small / zero cells, and R x C).

Usage: .venv/bin/python -I tools/contingency_parity.py <out_dir> [--n 16] [--reuse]
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
from refract.stats import contingency as CT

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
with open(os.path.join(ROOT, "corpus", "seeds", "contingency_table_params.json")) as f:
    BASE = json.load(f)

ALL = ("relativeRisk", "differenceBetweenProportions", "oddsRatio", "proportions", "associationMeasures")
CONFIGS = [  # (name, overrides)
    ("fisher", {"calc/method": "FISHER_EXACT_TEST"}),
    ("chi", {"calc/method": "CHI_SQUARE_TEST"}),
    ("fisher_1t", {"calc/method": "FISHER_EXACT_TEST", "options/pValueTailType": "P_VALUE_ONE_TAILED"}),
    ("chi_a01", {"calc/method": "CHI_SQUARE_TEST", "options/significanceLevel": 0.01}),
    ("chi_1t_cp", {"calc/method": "CHI_SQUARE_TEST", "options/pValueTailType": "P_VALUE_ONE_TAILED",
                   "calc/proportions/ciMethod": "CI_PROPORTION_METHOD_CLOPPER_PEARSON",
                   "calc/differenceBetweenProportions/ciMethod": "CI_PROPORTIONS_DIFFERENCE_METHOD_NEWCOMBE_WILSON"}),
    ("fisher_wilson", {"calc/method": "FISHER_EXACT_TEST", "calc/proportions/ciMethod": "CI_PROPORTION_METHOD_WILSON"}),
    ("chi_asym", {"calc/method": "CHI_SQUARE_TEST", "calc/relativeRisk/ciMethod": "CI_RELATIVE_RISK_METHOD_KATZ_LOG",
                  "calc/oddsRatio/ciMethod": "CI_ODDS_RATIO_METHOD_WOOLF_LOGIT",
                  "calc/differenceBetweenProportions/ciMethod": "CI_PROPORTIONS_DIFFERENCE_METHOD_ASYMPTOTIC"}),
]
# Prism's Koopman interval is a solver artefact when a row proportion is 0 or 1 and the
# other count is non-zero ([[37, 0], [38, 22]]: 1.57894..1.57944); not reproduced.
KNOWN = {("ct09_2x2", "relativeRiskModel", "KOOPMAN")}


def params(ov):
    c = copy.deepcopy(BASE)
    for k in ALL:
        c["calc"][k]["calculate"] = True
    for path, v in ov.items():
        d = c
        *head, last = path.split("/")
        for h in head:
            d = d.setdefault(h, {})
        d[last] = v
    return c


def gen(n: int, seed: int = 23):
    """[(name, table[r][c])]"""
    rnd = random.Random(seed)
    shapes = [(2, 2)] * 3 + [(2, 3), (3, 2), (3, 3), (4, 2), (2, 5)]
    out = []
    for i in range(n):
        r, c = shapes[i % len(shapes)]
        hi = rnd.choice([6, 15, 40, 200])
        t = [[rnd.randint(1, hi) for _ in range(c)] for _ in range(r)]
        if i % 5 == 4:
            t[rnd.randrange(r)][rnd.randrange(c)] = 0
        out.append((f"ct{i:02d}_{r}x{c}", t))
    return out


def spec_for(t):
    r, c = len(t), len(t[0])
    sets = [DataSet(f"Out{j + 1}", [[t[i][j] for i in range(r)]]) for j in range(c)]
    return TableSpec("CT", "contingency", "y_single", sets, row_titles=[f"Grp{i + 1}" for i in range(r)])


def compare_all(sets, res):
    acc, missing, extra = collections.defaultdict(list), collections.Counter(), collections.Counter()
    for name, t in sets:
        for cname, ov in CONFIGS:
            theirs = res.get(name, {}).get(cname)
            if theirs is None:
                continue
            try:
                o = dict(leaves(CT.contingency(params(ov), t)))
            except Exception as e:  # noqa: BLE001 - report and keep comparing
                missing[f"{cname}/ERROR {type(e).__name__}: {e}"[:110]] += 1
                continue
            th = dict(leaves(theirs))
            shape = f"{len(t)}x{len(t[0])}" if (len(t), len(t[0])) == (2, 2) else "RxC"
            for p_, v in th.items():
                if (name, p_.split("/")[1], "KOOPMAN") in KNOWN and "KATZ" not in json.dumps(ov):
                    continue
                g = f"{cname}/{shape}/{p_}"
                if p_ not in o:
                    missing[g] += 1
                    continue
                acc[g].append(close(o[p_], v))
            for p_ in o:
                if p_ not in th:
                    extra[f"{cname}/{shape}/{p_}"] += 1
    return acc, missing, extra


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
        cases = [O.Case(name, [spec_for(t)], [("CONTINGENCY_TABLE", params(ov), 0, cn) for cn, ov in CONFIGS])
                 for name, t in sets]
        res = O.run(cases, a.out, timeout=30)
    acc, missing, extra = compare_all(sets, res)
    good = 0
    print(f"{len(sets)} tables")
    for k in sorted(acc):
        w = max(acc[k])
        if w <= 1e-9:
            good += 1
        else:
            print(f"   {w:9.2e}  {k}  (n={len(acc[k])})")
    print(f"   {good} fields agree")
    for k, v in sorted(missing.items()):
        print(f"   missing {v:3d}  {k}")
    for k, v in sorted(extra.items()):
        print(f"   extra   {v:3d}  {k}")


if __name__ == "__main__":
    main()
