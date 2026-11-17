"""Parity of ROC curves (ROC_CURVE) and area under the curve
(AREA_UNDER_CURVE) with Prism on generated tables.

Usage: .venv/bin/python -I tools/roc_parity.py <out_dir> [--reuse]
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


ROC, AUC = _seed("roc_curve"), _seed("area_under_curve")
ROC_CONFIGS = [("roc", {}), ("roc_cp", {"options/confidenceMethod": "CLOPPER_PEARSON"}),
               ("roc_w", {"options/confidenceMethod": "WILSON"}), ("roc_frac", {"options/reportResultsAs": "FRACTION"}),
               ("roc90", {"options/confidenceLevel": 90.0})]
AUC_CONFIGS = [("auc", {}), ("auc_base", {"calc/baseline/useSpecificValue": False, "calc/baseline/firstRowsMeanCount": 2}),
               ("auc_neg", {"calc/peak/calcPositivePeaksOnly": False}),
               ("auc_amp", {"calc/peak/height/minimumAmplitudePercentage": 30.0}),
               ("auc_narrow", {"calc/peak/width/ignoreNarrowPeak": True, "calc/peak/width/adjacentPointCount": 3}),
               ("auc_b5", {"calc/baseline/value": 5.0})]


def params(base, ov, roc=False):
    c = copy.deepcopy(base)
    if roc:
        c["data"]["controlID"], c["data"]["patientID"] = {"col": {"idx": 0}}, {"col": {"idx": 1}}
    for path, v in ov.items():
        d = c
        *head, last = path.split("/")
        for h in head:
            d = d.setdefault(h, {})
        d[last] = v
    return c


def gen_roc(seed: int = 91):
    rnd = random.Random(seed)
    out = []
    for i, (n0, n1) in enumerate([(10, 12), (48, 50), (50, 51), (52, 30), (60, 45), (100, 80), (20, 20), (15, 25)]):
        shift = rnd.choice([0.5, 1.0, 2.0, -1.0])
        dec = 0 if i % 3 == 0 else 2  # integers: ties
        ctrl = [round(rnd.gauss(10, 2), dec) for _ in range(n0)]
        pat = [round(rnd.gauss(10 + 2 * shift, 2), dec) for _ in range(n1)]
        out.append((f"roc{i}_{n0}_{n1}", [ctrl, pat]))
    return out


def gen_auc(seed: int = 93):
    rnd = random.Random(seed)
    out = []
    for i in range(6):
        n = rnd.choice([20, 40, 60])
        x = sorted(round(rnd.uniform(0, 50), 2) for _ in range(n)) if i % 2 else [float(k) for k in range(n)]
        sets = []
        for _ in range(rnd.choice([1, 2])):
            peaks = [(rnd.uniform(0, 50), rnd.uniform(2, 8), rnd.uniform(-5, 20)) for _ in range(rnd.choice([1, 2, 3]))]
            y = [round(sum(h * math.exp(-((xv - c) / w) ** 2) for c, w, h in peaks) + rnd.gauss(0, 0.8), 3) for xv in x]
            sets.append(y)
        out.append((f"auc{i}_n{n}", x, sets))
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


def norm_samples(c):
    c = copy.deepcopy(c)
    if "samples" in c:
        c["samples"] = {str(v["id"]["col"]["idx"]): v["value"] for v in c["samples"].values()}
    return c


def compare_all(rsets, asets, res):
    from refract.stats import roc as RC

    acc, missing = collections.defaultdict(list), collections.Counter()

    def cmp(cname, ours, theirs):
        o = dict(leaves(norm_samples(ours)))
        for k, v in leaves(norm_samples(theirs)):
            if k.endswith(("/uid", "/title")):
                continue
            g = cname + "/".join("*" if s.isdigit() else s for s in k.split("/"))
            if k not in o:
                missing[g] += 1
                continue
            acc[g].append(close(o[k], v))
        for k in o:
            if k not in dict(leaves(norm_samples(theirs))):
                missing["EXTRA " + cname + k] += 1

    for name, cols in rsets:
        for cname, ov in ROC_CONFIGS:
            t = res.get(name, {}).get(cname)
            if t is not None:
                cmp(cname, RC.roc_curve(params(ROC, ov, True), cols), t["results"])
    for name, x, sets in asets:
        for cname, ov in AUC_CONFIGS:
            t = res.get(name, {}).get(cname)
            if t is not None:
                cmp(cname, RC.area_under_curve(params(AUC, ov), x, sets), t["results"])
    return acc, missing


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--reuse", action="store_true")
    a = ap.parse_args()
    rsets, asets = gen_roc(), gen_auc()
    cases = []
    for name, cols in rsets:
        spec = TableSpec("C", "column", "y_single", [DataSet("Controls", [cols[0]]), DataSet("Patients", [cols[1]])])
        cases.append(O.Case(name, [spec], [("ROC_CURVE", params(ROC, ov, True), 0, cn) for cn, ov in ROC_CONFIGS]))
    for name, x, sets in asets:
        spec = TableSpec("XY", "xy", "y_single", [DataSet(chr(65 + i), [s]) for i, s in enumerate(sets)], x_title="X", x_values=x)
        cases.append(O.Case(name, [spec], [("AREA_UNDER_CURVE", params(AUC, ov), 0, cn) for cn, ov in AUC_CONFIGS]))
    res = TO.run_tables(cases, a.out, timeout=60, reuse=a.reuse)
    try:
        acc, missing = compare_all(rsets, asets, res)
    except (ImportError, AttributeError) as ex:
        print("implementation incomplete:", ex)
        return
    good = 0
    for k in sorted(acc):
        w = max(acc[k])
        if w <= 1e-9:
            good += 1
        else:
            print(f"   {w:9.2e}  {k}  (bad {sum(1 for v in acc[k] if v > 1e-9)}/{len(acc[k])})")
    print(f"   {good} field groups agree")
    for k, v in sorted(missing.items())[:40]:
        print(f"   missing {v:3d}  {k}")


if __name__ == "__main__":
    main()
