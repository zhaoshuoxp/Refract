"""Parity of Cox proportional-hazards regression (MULTIPLE_COX_REGRESSION)
with Prism on generated multiple-variables tables.

Usage: .venv/bin/python -I tools/cox_parity.py <out_dir> [--reuse]
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
from anova_parity import close

from refract.formats.bundle_builder import DataSet, TableSpec

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
with open(os.path.join(ROOT, "corpus", "seeds", "cox_regression_params.json")) as _f:
    BASE = json.load(_f)
DIAG = ("hazardRatio", "parSignificanceTest", "parCorrelation", "parMulticollinearity", "logLikelihood",
        "neg2logLikelihood", "pseudoR2", "aic", "likelihoodRatioTest", "waldTest", "scoreTest", "harrellC")
CONFIGS = [("profile", {"confidence/ciMethod": "PROFILE_LIKELIHOOD"}),
           ("wald", {"confidence/ciMethod": "WALD"})]


def ref(i):
    return {"col": {"idx": i}}


def params(spec, ov):
    """spec: (titles, kinds) of the table; column 0 time, 1 event; kinds 'cat'/'num'."""
    titles, kinds, levels = spec
    p = copy.deepcopy(BASE)
    m = p["model"]
    m["timeVariable"], m["dependentVariable"] = ref(0), ref(1)
    m["outcome0"], m["outcome1"] = {"value": "Censored", "label": "Censored"}, {"value": "Died", "label": "Died"}
    m["modelDef"] = [{"componentType": "ADDITIVE", "variables": [ref(i)]} for i in range(2, len(titles))]
    info = [{"variable": ref(0), "variableType": "CONTINUOUS"},
            {"variable": ref(1), "variableType": "CATEGORICAL", "referenceLevelType": "AUTO_FIRST_LEVEL",
             "referenceLevelValue": "Censored", "levelCount": 2, "levelOrderType": "VISUAL"}]
    for i in range(2, len(titles)):
        if kinds[i] == "cat":
            info.append({"variable": ref(i), "variableType": "CATEGORICAL", "referenceLevelType": "AUTO_FIRST_LEVEL",
                         "referenceLevelValue": levels[i][0], "levelCount": len(levels[i]), "levelOrderType": "VISUAL"})
        else:
            info.append({"variable": ref(i), "variableType": "CONTINUOUS"})
    m["variableInfo"] = info
    for k in DIAG:
        p["diagnostics"][k] = True
    for path, v in ov.items():
        d = p
        *head, last = path.split("/")
        for h in head:
            d = d.setdefault(h, {})
        d[last] = v
    return p


def gen(n_sets: int = 10, seed: int = 81):
    """[(name, columns, (titles, kinds, levels))]"""
    rnd = random.Random(seed)
    out = []
    for i in range(n_sets):
        n = rnd.choice([30, 50, 80, 120])
        ncov = rnd.choice([1, 2, 3])
        kinds, titles, levels, covs = ["num", "cat"], ["Time", "Event"], [None, ["Censored", "Died"]], []
        for c in range(ncov):
            if rnd.random() < 0.5:
                lv = ["L0", "L1", "L2"][: rnd.choice([2, 3])]
                kinds.append("cat")
                levels.append(lv)
                covs.append([rnd.choice(lv) for _ in range(n)])
            else:
                kinds.append("num")
                levels.append(None)
                covs.append([round(rnd.gauss(50, 10), 1) for _ in range(n)])
            titles.append(f"V{c + 1}")
        beta = [rnd.uniform(-0.6, 0.6) for _ in range(ncov)]
        times, events = [], []
        for r in range(n):
            lp = 0.0
            for c in range(ncov):
                v = covs[c][r]
                lp += beta[c] * (levels[c + 2].index(v) if isinstance(v, str) else (v - 50) / 10)
            t = rnd.expovariate(0.03 * math.exp(lp))
            cens = rnd.uniform(5, 80)
            tt = min(t, cens)
            times.append(float(round(tt)) if i % 3 == 0 else round(tt, 2))  # integer times: ties
            events.append("Died" if t <= cens else "Censored")
        out.append((f"cx{i:02d}_n{n}k{ncov}", [times, events, *covs], (titles, kinds, levels)))
    return out


def leaves(o, pre=""):
    if isinstance(o, dict):
        for k, v in o.items():
            yield from leaves(v, f"{pre}/{k}")
    elif isinstance(o, list):
        for i, v in enumerate(o):
            yield from leaves(v, f"{pre}/{i}")
    elif isinstance(o, (bool, str)):
        yield pre, o
    elif isinstance(o, (int, float)):
        yield pre, float(o)


def compare_all(sets, res):
    from refract.stats import cox as CX

    acc, missing = collections.defaultdict(list), collections.Counter()
    for name, cols, spec in sets:
        for cname, ov in CONFIGS:
            theirs = res.get(name, {}).get(cname)
            if theirs is None:
                missing[f"{cname}: no Prism result"] += 1
                continue
            o = dict(leaves(CX.cox_from_params(params(spec, ov), cols, spec[0])))
            for k, v in leaves(theirs["results"]):
                if k.endswith("/equation") or "/harrellC/ci/" in k:  # known: C's CI formula not found
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
    cases = []
    for name, cols, spec in sets:
        t = TableSpec("MV", "multivariable", "y_single", [DataSet(ti, [c]) for ti, c in zip(spec[0], cols, strict=True)])
        cases.append(O.Case(name, [t], [("MULTIPLE_COX_REGRESSION", params(spec, ov), 0, cn) for cn, ov in CONFIGS]))
    res = TO.run_tables(cases, a.out, timeout=90, reuse=a.reuse)
    try:
        acc, missing = compare_all(sets, res)
    except ImportError:
        print("refract.stats.cox not written yet;", len(res), "documents collected")
        return
    good = 0
    for k in sorted(acc):
        w = max(acc[k])
        if w <= 1e-6:
            good += 1
        else:
            print(f"   {w:9.2e}  {k}  (bad {sum(1 for v in acc[k] if v > 1e-6)}/{len(acc[k])})")
    print(f"   {good} field groups agree")
    for k, v in sorted(missing.items()):
        print(f"   missing {v:3d}  {k}")


if __name__ == "__main__":
    main()
