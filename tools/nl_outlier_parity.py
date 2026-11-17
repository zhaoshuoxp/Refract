"""Parity of nonlinear regression with ROUT outlier elimination
(method.outliers.method ELIMINATE) and robust fitting (fittingMethod ROBUST)
with Prism, on the curves of tools/nonlinear_parity.py with planted outliers.

Usage: .venv/bin/python -I tools/nl_outlier_parity.py <out_dir> [--reuse]
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

import nonlinear_parity as NP
import stats_oracle as O
from anova_parity import close

from refract.formats.bundle_builder import DataSet, TableSpec

CONFIGS = [("rout1", {**NP.DIAG_ALL, "method/outliers/method": "ELIMINATE", "method/outliers/q": 1.0}),
           ("rout10", {**NP.DIAG_ALL, "method/outliers/method": "ELIMINATE", "method/outliers/q": 10.0}),
           ("robust", {**NP.DIAG_ALL, "method/fittingMethod": "ROBUST"})]


CONVERGENCE_TOL = 1e-3  # Prism's medium criterion; robust fits and 4-parameter curves (findings.md)


def gen(seed: int = 41):
    rnd = random.Random(seed)
    out = []
    for name, eq, x, sets in NP.gen(14, seed=37):
        sets = copy.deepcopy(sets)
        for subs in sets:
            ys = [v for s in subs for v in s]
            span = max(ys) - min(ys)
            for _ in range(rnd.choice([0, 1, 2])):
                s, r = rnd.randrange(len(subs)), rnd.randrange(len(x))
                subs[s][r] = round(subs[s][r] + rnd.choice([-1, 1]) * rnd.uniform(0.3, 0.8) * span, 3)
        out.append((name, eq, x, sets))
    return out


def norm_outliers(content):
    out = {}
    for v in (content.get("outliers") or {}).values():
        out[str(v["id"]["col"]["idx"])] = v["value"]
    return out


def compare_all(sets, res):
    from refract.stats import nonlinear as NL

    acc, missing = collections.defaultdict(list), collections.Counter()
    for name, eq, x, ys in sets:
        for cname, ov in CONFIGS:
            theirs = res.get(name, {}).get(cname)
            if theirs is None:
                missing[f"{cname}: no Prism result"] += 1
                continue
            p = NP.params(eq, ov)
            fmt = "y_replicates" if len(ys[0]) > 1 else "y_single"
            ours = {str(i): NL.fit_dataset(p, x, subs, i, data_format=fmt) for i, subs in enumerate(ys)}
            t = NP._norm_prism(theirs)
            tout = norm_outliers(theirs)
            for i, f in t.items():
                if i not in ours:
                    continue
                o = dict(NP.leaves({"fit": ours[i]}))
                th = dict(NP.leaves({"fit": f}))
                if i in tout:
                    o.update(NP.leaves({"outliers": ours[i].get("_outliers", {})}))
                    th.update(NP.leaves({"outliers": tout[i]}))
                for k, v in th.items():
                    g = f"{cname}/{eq[:20]}/" + "/".join("*" if s.isdigit() else s for s in k.split("/")[1:])
                    if k not in o:
                        missing[g] += 1
                        continue
                    acc[g].append(close(o[k], v))
    return acc, missing


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--reuse", action="store_true")
    a = ap.parse_args()
    sets = gen()
    rp = os.path.join(a.out, "results.json")
    if a.reuse and os.path.exists(rp):
        with open(rp) as f:
            res = json.load(f)
    else:
        cases = []
        for name, eq, x, ys in sets:
            reps = len(ys[0])
            spec = TableSpec("XY", "xy", "y_replicates" if reps > 1 else "y_single",
                             [DataSet(chr(65 + i), s) for i, s in enumerate(ys)], x_title="X", x_values=x, replicates=reps)
            cases.append(O.Case(name, [spec], [("NONLINEAR_REGRESSION", NP.params(eq, ov), 0, cn) for cn, ov in CONFIGS]))
        res = O.run(cases, a.out, timeout=40)
    acc, missing = compare_all(sets, res)
    good = conv = 0
    for k in sorted(acc):
        w = max(acc[k])
        if w <= 1e-6:
            good += 1
        elif w <= CONVERGENCE_TOL:
            conv += 1
        else:
            print(f"   {w:9.2e}  {k}  (bad {sum(1 for v in acc[k] if v > 1e-6)}/{len(acc[k])})")
    print(f"   {good} field groups agree to 1e-6, {conv} more to {CONVERGENCE_TOL:g} (Prism's convergence, known)")
    for k, v in sorted(missing.items()):
        print(f"   missing {v:3d}  {k}")


if __name__ == "__main__":
    main()
