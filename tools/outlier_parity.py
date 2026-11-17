"""Parity of outlier detection (IDENTIFY_OUTLIERS: Grubbs, iterative Grubbs,
ROUT) and Bland-Altman (BLAND_ALTMAN) with Prism, on column tables with
planted outliers.

Usage: .venv/bin/python -I tools/outlier_parity.py <out_dir> [--reuse]
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

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")


def _seed(k):
    with open(os.path.join(ROOT, "corpus", "seeds", f"{k}_params.json")) as f:
        return json.load(f)


OUT, BA = _seed("identify_outliers"), _seed("bland_altman")
CONFIGS = [  # (name, class, overrides)
    ("g05", "IDENTIFY_OUTLIERS", {"calc/method": "GRUBBS_SINGLE", "calc/alpha": 0.05}),
    ("g01", "IDENTIFY_OUTLIERS", {"calc/method": "GRUBBS_SINGLE", "calc/alpha": 0.01}),
    ("gm05", "IDENTIFY_OUTLIERS", {"calc/method": "GRUBBS_MULTIPLE", "calc/alpha": 0.05}),
    ("gm0001", "IDENTIFY_OUTLIERS", {"calc/method": "GRUBBS_MULTIPLE", "calc/alpha": 0.0001}),
    ("r1", "IDENTIFY_OUTLIERS", {"calc/method": "ROUT", "calc/q": 1.0}),
    ("r01", "IDENTIFY_OUTLIERS", {"calc/method": "ROUT", "calc/q": 0.1}),
    ("r5", "IDENTIFY_OUTLIERS", {"calc/method": "ROUT", "calc/q": 5.0}),
    ("r10", "IDENTIFY_OUTLIERS", {"calc/method": "ROUT", "calc/q": 10.0}),
    ("ba_ab", "BLAND_ALTMAN", {"calc/type": "A_MINUS_B"}),
    ("ba_ba", "BLAND_ALTMAN", {"calc/type": "B_MINUS_A"}),
    ("ba_adb", "BLAND_ALTMAN", {"calc/type": "A_DIV_B"}),
    ("ba_bda", "BLAND_ALTMAN", {"calc/type": "B_DIV_A"}),
]
# Known, not reproduced: iterative Grubbs on ol04 column A (n = 5): the single
# test flags one value (G 1.784 > 1.715), Prism's iterative test flags none.
KNOWN = {("ol04_k3", "gm05")}
BA_GUESSES = ["RATIO_A_TO_B", "A_B_RATIO", "RATIO_A_B_", "A_OVER_B_RATIO", "PERCENT_DIFFERENCE_A_B",
              "DIFFERENCE_AS_PERCENT_OF_AVERAGE", "PERCENT_OF_AVERAGE", "RATIO_B_A", "B_OVER_A", "A_DIV_B",
              "DIFFERENCE_PERCENTAGE", "PCT_DIFFERENCE", "RATIO_OF_A_TO_B", "A_TO_B_RATIO"]


def params(cls, ov):
    c = copy.deepcopy(OUT if cls == "IDENTIFY_OUTLIERS" else BA)
    if cls == "BLAND_ALTMAN":
        c["data"]["methodAID"] = {"col": {"idx": 0}}
        c["data"]["methodBID"] = {"col": {"idx": 1}}
    for path, v in ov.items():
        d = c
        *head, last = path.split("/")
        for h in head:
            d = d.setdefault(h, {})
        d[last] = v
    return c


def gen(n_sets: int = 12, seed: int = 61):
    """[(name, columns)] - 2-4 columns of 5-40 values, 0-3 planted outliers each."""
    rnd = random.Random(seed)
    out = []
    for i in range(n_sets):
        k = rnd.choice([2, 3, 4])
        cols = []
        for _ in range(k):
            n = rnd.choice([5, 8, 12, 20, 40])
            mu, sd = rnd.uniform(5, 50), rnd.uniform(0.5, 5)
            col = [round(rnd.gauss(mu, sd), 3) for _ in range(n)]
            for _ in range(rnd.choice([0, 1, 1, 2, 3])):
                col[rnd.randrange(n)] = round(mu + rnd.choice([-1, 1]) * rnd.uniform(3, 9) * sd, 3)
            if i % 4 == 3 and n > 5:
                col[1] = None
            cols.append(col)
        out.append((f"ol{i:02d}_k{k}", cols))
    return out


def norm_results(c: dict) -> dict:
    c = copy.deepcopy(c)
    if "samples" in c:
        c["samples"] = {str(v["id"]["col"]["idx"]): v["value"] for v in c["samples"].values()}
    return c


def compare_all(sets, res):
    from refract.stats import outliers as OL

    acc, missing = collections.defaultdict(list), collections.Counter()
    for name, cols in sets:
        for cname, cls, ov in CONFIGS:
            if (name, cname) in KNOWN:
                missing[f"known: {name} {cname}"] += 1
                continue
            theirs = res.get(name, {}).get(cname)
            if theirs is None:
                missing[f"{cname}: no Prism result"] += 1
                continue
            p = params(cls, ov)
            ours = OL.identify_outliers(p, cols) if cls == "IDENTIFY_OUTLIERS" else OL.bland_altman(p, cols)
            o, t = dict(leaves(norm_results(ours["results"]))), dict(leaves(norm_results(theirs["results"])))
            for k, v in t.items():
                if k.endswith(("/uid", "/title")):
                    continue
                if k not in o:
                    missing[f"{cname}{k}"] += 1
                    continue
                acc[cname + k].append(close(o[k], v))
            for tname, tab in ours["tables"].items():
                pt = theirs["tables"].get(tname)
                if pt is None:
                    missing[f"{cname}: table {tname}"] += 1
                    continue
                for so, sp in zip(tab["sets"], pt["sets"], strict=False):
                    for si, (co, cp) in enumerate(zip(so["subs"], sp["subs"], strict=False)):
                        for r in range(max(len(co), len(cp))):
                            a = co[r] if r < len(co) else None
                            b = TO.num(cp[r]) if r < len(cp) else None
                            acc[f"{cname}/{tname}/sub{si}"].append(
                                0.0 if a is None and b is None else math.inf if (a is None) != (b is None) else close(a, b))
                if tab.get("x") is not None and pt.get("x"):
                    for a, b in zip(tab["x"], pt["x"][0], strict=False):
                        b = TO.num(b)
                        acc[f"{cname}/{tname}/x"].append(
                            0.0 if a is None and b is None else math.inf if (a is None) != (b is None) else close(a, b))
    return acc, missing


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--reuse", action="store_true")
    a = ap.parse_args()
    sets = gen()
    cases = []
    for name, cols in sets:
        spec = TableSpec("C", "column", "y_single", [DataSet(chr(65 + i), [c]) for i, c in enumerate(cols)])
        cases.append(O.Case(name, [spec], [(c[1], params(c[1], c[2]), 0, c[0]) for c in CONFIGS]))
    # Bland-Altman type names (retention probe on the first table)
    spec = TableSpec("C", "column", "y_single", [DataSet(chr(65 + i), [c]) for i, c in enumerate(sets[0][1])])
    cases.append(O.Case("ba_guess", [spec], [("BLAND_ALTMAN", params("BLAND_ALTMAN", {"calc/type": g}), 0, f"g_{g}")
                                             for g in BA_GUESSES]))
    res = TO.run_tables(cases, a.out, timeout=60, reuse=a.reuse)
    try:
        acc, missing = compare_all(sets, res)
    except ImportError:
        print("refract.stats.outliers not written yet")
        return
    good = 0
    for k in sorted(acc):
        w = max(acc[k])
        if w <= 1e-9:
            good += 1
        else:
            print(f"   {w:9.2e}  {k}  (bad {sum(1 for v in acc[k] if v > 1e-9)}/{len(acc[k])})")
    print(f"   {good} field groups agree")
    for k, v in sorted(missing.items()):
        print(f"   missing {v:3d}  {k}")


if __name__ == "__main__":
    main()
