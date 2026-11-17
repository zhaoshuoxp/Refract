"""Parity of multiple linear regression (MULTIPLE_LINEAR_REGRESSION),
multiple logistic regression (MULTIPLE_LOGISTIC_REGRESSION) and PCA with
Prism on generated multiple-variables tables.

Usage: .venv/bin/python -I tools/multreg_parity.py <out_dir> [--reuse]
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


def _seed(k):
    with open(os.path.join(ROOT, "corpus", "seeds", f"{k}_params.json")) as f:
        return json.load(f)


LIN, LOG, PCA = _seed("multiple_linear_regression"), _seed("multiple_logistic_regression"), _seed("pca")
LIN_CONFIGS = [("lin", {}), ("lin_wald", {"confidence/ciMethod": "WALD"})]
LOG_CONFIGS = [("log", {}), ("log_wald", {"confidence/ciMethod": "WALD"})]
PCA_CONFIGS = [("pca_kai", {"calc/method": "KAISER_RULE"}),
               ("pca_thr", {"calc/method": "EIGENVALUE_ABOVE_THRESHOLD", "calc/eigenvalueThreshold": 0.9}),
               ("pca_cnt", {"calc/method": "SPECIFIC_NUMBER", "calc/componentCount": 3}),
               ("pca_var", {"calc/method": "TOTAL_EXPLAINED_VARIANCE", "calc/explainedVariance": 80.0}),
               ("pca_all", {"calc/method": "ALL_COMPONENTS"}),
               ("pca_ctr", {"calc/method": "KAISER_RULE", "calc/transform": "CENTER_DATA"})]


def ref(i):
    return {"col": {"idx": i}}


def _set(p, ov):
    for path, v in ov.items():
        d = p
        *head, last = path.split("/")
        for h in head:
            d = d.setdefault(h, {})
        d[last] = v
    return p


def _info(i, kind, levels):
    if kind == "cat":
        return {"variable": ref(i), "variableType": "CATEGORICAL", "referenceLevelType": "AUTO_FIRST_LEVEL",
                "referenceLevelValue": levels[0], "levelCount": len(levels), "levelOrderType": "VISUAL"}
    return {"variable": ref(i), "variableType": "CONTINUOUS"}


def reg_params(base, spec, ov):
    titles, kinds, levels = spec
    p = copy.deepcopy(base)
    m = p["model"]
    m["dependentVariable"] = ref(0)
    m["modelDef"] = [{"componentType": "INTERCEPT", "variables": []}] + \
        [{"componentType": "ADDITIVE", "variables": [ref(i)]} for i in range(1, len(titles))]
    m["variableInfo"] = [_info(i, kinds[i], levels[i]) for i in range(len(titles))]
    if kinds[0] == "cat":
        m["outcome0"], m["outcome1"] = ({"value": v, "label": v} for v in levels[0])
    return _set(p, ov)


def pca_params(k, ov):
    p = copy.deepcopy(PCA)
    p["data"]["variables"] = [ref(i) for i in range(k)]
    return _set(p, ov)


def gen(seed: int = 113):
    """[(name, kind, columns, spec)]"""
    rnd = random.Random(seed)
    out = []
    for i in range(12):
        kind = ("lin", "log", "pca")[i % 3]
        n = rnd.choice([40, 60, 100, 150])
        ncov = rnd.choice([2, 3, 4]) if kind != "pca" else rnd.choice([3, 4, 5, 6])
        kinds, titles, levels, covs, z0 = [], [], [], [], None
        for c in range(ncov):
            if kind != "pca" and rnd.random() < 0.35:
                lv = ["A", "B", "C"][: rnd.choice([2, 3])]
                kinds.append("cat")
                levels.append(lv)
                covs.append([rnd.choice(lv) for _ in range(n)])
            else:
                kinds.append("num")
                levels.append(None)
                base = [rnd.gauss(0, 1) for _ in range(n)]
                if z0 is None:
                    z0 = base
                elif rnd.random() < 0.5:  # correlated with the first numeric variable
                    base = [0.7 * a + 0.3 * b for a, b in zip(z0, base, strict=True)]
                covs.append([round(20 + 5 * b, 2) for b in base])
            titles.append(f"V{c + 1}")
        if kind == "pca":
            out.append((f"pc{i:02d}_n{n}k{ncov}", kind, covs, (titles, kinds, levels)))
            continue
        lp = []
        for r in range(n):
            s = 0.0
            for c in range(ncov):
                v = covs[c][r]
                s += 0.4 * (levels[c].index(v) if isinstance(v, str) else (v - 20) / 5)
            lp.append(s)
        if kind == "lin":
            y = [round(10 + 2 * s + rnd.gauss(0, 1.5), 3) for s in lp]
            out.append((f"ln{i:02d}_n{n}k{ncov}", kind, [y, *covs], (["Y", *titles], ["num", *kinds], [None, *levels])))
        else:
            y = ["Yes" if rnd.random() < 1 / (1 + math.exp(-(s - 0.2))) else "No" for s in lp]
            out.append((f"lg{i:02d}_n{n}k{ncov}", kind, [y, *covs],
                        (["Out", *titles], ["cat", *kinds], [["No", "Yes"], *levels])))
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


def analyses(kind, spec):
    if kind == "lin":
        return [("MULTIPLE_LINEAR_REGRESSION", reg_params(LIN, spec, ov), 0, cn) for cn, ov in LIN_CONFIGS]
    if kind == "log":
        return [("MULTIPLE_LOGISTIC_REGRESSION", reg_params(LOG, spec, ov), 0, cn) for cn, ov in LOG_CONFIGS]
    return [("PCA", pca_params(len(spec[0]), ov), 0, cn) for cn, ov in PCA_CONFIGS]


def compare_all(sets, res):
    from refract.stats import engine as E
    from refract.stats import pca as PC

    acc, missing = collections.defaultdict(list), collections.Counter()
    for name, kind, cols, spec in sets:
        for cls, p, _, cname in analyses(kind, spec):
            theirs = res.get(name, {}).get(cname)
            if theirs is None:
                missing[f"{cname}: no Prism result"] += 1
                continue
            full = PC.pca(p, cols, spec[0]) if cls == "PCA" else None
            o = dict(leaves(full["results"] if full else E.compute(cls, p, cols, titles=spec[0])))
            for k, v in leaves(theirs["results"]):
                if "parallelAnalysis" in k or k.endswith("/equation"):
                    continue
                if k not in o:
                    missing[f"{cname}{k}"] += 1
                    continue
                acc[cname + k].append(close(o[k], v))
            if full:
                for tn, ot in full["tables"].items():
                    pt = theirs.get("tables", {}).get(tn)
                    if pt is None:
                        missing[f"{cname} table {tn}"] += 1
                        continue
                    psets = [s for s in pt["sets"] if s["title"] != "Var"]
                    acc[f"{cname} table {tn}: columns"].append(float(len(psets) != len(ot["sets"])))
                    for j, (so, sp) in enumerate(zip(ot["sets"], psets, strict=False)):
                        # known: the orientation of PC2.. (findings.md); PC1's is checked
                        f = (lambda v: v) if j == 0 else abs
                        acc[f"{cname} table {tn}"].append(max(close(f(a), f(TO.num(b))) for a, b in
                                                             zip(so["subs"][0], sp["subs"][0], strict=False)))
    return acc, missing


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--reuse", action="store_true")
    a = ap.parse_args()
    sets = gen()
    cases = []
    for name, kind, cols, spec in sets:
        t = TableSpec("MV", "multivariable", "y_single", [DataSet(ti, [c]) for ti, c in zip(spec[0], cols, strict=True)])
        cases.append(O.Case(name, [t], analyses(kind, spec)))
    res = TO.run_tables(cases, a.out, timeout=90, reuse=a.reuse)
    acc, missing = compare_all(sets, res)
    good = 0
    for k in sorted(acc):
        w = max(acc[k])
        if w <= 1e-6:
            good += 1
        else:
            print(f"   {w:9.2e}  {k}  (bad {sum(1 for v in acc[k] if v > 1e-6)}/{len(acc[k])})")
    print(f"   {good} field groups agree to 1e-6")
    for k, v in sorted(missing.items()):
        print(f"   missing {v:3d}  {k}")


if __name__ == "__main__":
    main()
