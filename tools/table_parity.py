"""Parity of the table-output analyses (refract.stats.transforms) with
Prism: Normalize, Transform, Remove baseline, Row statistics, Transpose.

Usage: .venv/bin/python -I tools/table_parity.py <out_dir> [--reuse]
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

from refract.formats.bundle_builder import DataSet, TableSpec
from refract.stats import transforms as TR

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")


def _seed(k):
    with open(os.path.join(ROOT, "corpus", "seeds", f"{k}_params.json")) as f:
        return json.load(f)


SEEDS = {"NORMALIZE": _seed("normalize"), "TRNSFORM": _seed("transform"), "REMOVE_BASELINE": _seed("remove_baseline"),
         "ROW_STATISTICS": _seed("row_statistics"), "TRANSPOSE": _seed("transpose")}
Y_FUNCS = ["Y*K", "Y+K", "Y-K", "Y/K", "Y^2", "Y^K", "LOG10(Y)", "LN(Y)", "10^Y", "EXP(Y)", "1/Y", "SQRT(Y)", "LOGIT(Y)",
           "PROBIT(Y)", "ABS(Y)", "Y*X", "Y/X", "Y-X", "Y+X", "K-Y", "K/Y", "LOG2(Y)", "2^Y"]
X_FUNCS = ["X*K", "X^2", "LOG10(X)", "LN(X)", "1/X", "SQRT(X)", "K-X", "LOG2(X)"]
CONFIGS = [  # (name, class, overrides, applies to table kinds)
    ("n_def", "NORMALIZE", {}, None),
    ("n_first_last", "NORMALIZE", {"calc/value_0/defineAs": "FIRST", "calc/value_100/defineAs": "LAST"}, None),
    ("n_custom", "NORMALIZE", {"calc/value_0/defineAs": "CUSTOM", "calc/value_0/customValue": 1.0,
                               "calc/value_100/defineAs": "CUSTOM", "calc/value_100/customValue": 20.0}, None),
    ("n_sum", "NORMALIZE", {"calc/value_0/defineAs": "CUSTOM", "calc/value_0/customValue": 0.0,
                            "calc/value_100/defineAs": "SUM_OF_VALUES", "options/reportResultsAs": "FRACTIONS"}, None),
    *[(f"y_{i:02d}", "TRNSFORM", {"calc/standardFunction/xTransform/enabled": False,
                                   "calc/standardFunction/yTransform/enabled": True,
                                   "calc/standardFunction/yTransform/function": f,
                                   "calc/standardFunction/yTransform/k": 2.5}, None) for i, f in enumerate(Y_FUNCS)],
    *[(f"x_{i:02d}", "TRNSFORM", {"calc/standardFunction/xTransform/enabled": True,
                                   "calc/standardFunction/xTransform/function": f,
                                   "calc/standardFunction/xTransform/k": 3.0}, ("xy",)) for i, f in enumerate(X_FUNCS)],
    *[(f"b_{e.lower()}", "REMOVE_BASELINE", {"calc/expression": e}, None)
      for e in ("RATIO", "DIFFERENCE", "PERCENT", "PERCENTAGE_DIFFERENCE")],
    ("b_odd", "REMOVE_BASELINE", {"data/columnBaseline/type": "EVERY_OTHER_COLUMN_1_3_5"}, None),
    ("b_reps", "REMOVE_BASELINE", {"data/treatSubcolumnsAs": "REPLICATES", "calc/expression": "DIFFERENCE"}, None),
    ("b_row1", "REMOVE_BASELINE", {"data/baselineType": "BASELINE_ROW", "data/rowBaseline/type": "FIRST_ROW"}, None),
    ("b_rowN", "REMOVE_BASELINE", {"data/baselineType": "BASELINE_ROW", "data/rowBaseline/type": "LAST_ROW",
                                   "calc/expression": "DIFFERENCE"}, None),
    ("b_keep", "REMOVE_BASELINE", {"data/baselineType": "BASELINE_ROW", "options/removeBaselineFromResults": False}, None),
    *[(f"r_{s.lower()}", "ROW_STATISTICS", {"calc/statistics": s}, None) for s in TR._ROW_FORMAT],
    ("r_col_sd", "ROW_STATISTICS", {"data/scope": "COLUMN"}, None),
    ("r_col_ci", "ROW_STATISTICS", {"data/scope": "COLUMN", "calc/statistics": "MEAN_WITH_CI"}, None),
    ("t_def", "TRANSPOSE", {}, ("xy",)),
]


def params(cls, ov):
    c = copy.deepcopy(SEEDS[cls])
    for path, v in ov.items():
        d = c
        *head, last = path.split("/")
        for h in head:
            d = d.setdefault(h, {})
        d[last] = v
    return c


def gen(seed: int = 51):
    """[(name, kind, table dict)]"""
    rnd = random.Random(seed)
    out = []
    specs = [("xy", 7, 1, 3), ("xy", 6, 3, 2), ("grouped", 4, 2, 4), ("grouped", 5, 1, 3), ("grouped", 3, 3, 2),
             ("xyfrac", 6, 2, 2)]
    for i, (kind, nr, reps, k) in enumerate(specs):
        frac = kind == "xyfrac"
        sets = []
        for d in range(k):
            subs = []
            for _ in range(reps):
                col = []
                for r in range(nr):
                    v = rnd.uniform(0.05, 0.95) if frac else rnd.uniform(-2, 30) if i == 3 else rnd.uniform(0.5, 30)
                    col.append(round(v, 3))
                subs.append(col)
            if i % 2 == 1:
                subs[0][rnd.randrange(nr)] = None
            sets.append({"title": chr(65 + d), "subs": subs})
        x = [round(rnd.uniform(0.2, 12), 2) for _ in range(nr)] if kind != "grouped" else None
        rows = None if kind != "grouped" else [f"R{r + 1}" for r in range(nr)]
        out.append((f"tb{i}_{kind}", "xy" if kind != "grouped" else "grouped",
                    {"title": "XY" if kind != "grouped" else "G", "x": x, "rows": rows, "sets": sets}))
    return out


def spec_for(kind, t):
    reps = len(t["sets"][0]["subs"])
    fmt = "y_replicates" if reps > 1 else "y_single"
    ds = [DataSet(s["title"], s["subs"]) for s in t["sets"]]
    if kind == "xy":
        return TableSpec(t["title"], "xy", fmt, ds, x_title="X", x_values=t["x"], replicates=reps)
    return TableSpec(t["title"], "grouped", fmt, ds, row_titles=t["rows"], replicates=reps)


def _cmp_num(a, b) -> float:
    if a is None and b is None:
        return 0.0
    if a is None or b is None:
        return math.inf
    if abs(a - b) <= 1e-12:
        return 0.0
    return abs(a - b) / max(abs(b), 1e-300)


def compare_all(sets, res):
    acc, missing = collections.defaultdict(list), collections.Counter()
    for name, kind, t in sets:
        for cname, cls, ov, kinds in CONFIGS:
            if kinds and kind not in kinds:
                continue
            theirs = res.get(name, {}).get(cname)
            if theirs is None:
                missing[f"{cname}: no Prism result"] += 1
                continue
            tabs = list(theirs["tables"].values())
            if not tabs:
                missing[f"{cname}: no result table ({theirs['results'].get('status')})"] += 1
                continue
            pt = tabs[0]
            try:
                ours = TR.ANALYSES[cls](params(cls, ov), t)
            except NotImplementedError as ex:
                missing[f"{cname}: {ex}"] += 1
                continue
            g = f"{cname}/"
            acc[g + "format"].append(0.0 if ours["format"] == pt["format"] else math.inf)
            if len(ours["sets"]) != len(pt["sets"]):
                acc[g + "set count"].append(math.inf)
                continue
            for so, sp in zip(ours["sets"], pt["sets"], strict=True):
                acc[g + "title"].append(0.0 if (so["title"] or "") == (sp["title"] or "") else math.inf)
                for si, (co, cp) in enumerate(zip(so["subs"], sp["subs"], strict=False)):
                    n = max(len(co), len(cp))
                    for r in range(n):
                        a = co[r] if r < len(co) else None
                        b = TO.num(cp[r]) if r < len(cp) else None
                        acc[f"{g}sub{si}"].append(_cmp_num(a, b))
                if len(so["subs"]) != len(sp["subs"]):
                    acc[g + "subcolumn count"].append(math.inf)
            if pt["x"] is not None and ours.get("x") is not None:
                for a, b in zip(ours["x"], pt["x"][0], strict=False):
                    acc[g + "x"].append(_cmp_num(a, TO.num(b)))
            if pt["rows"] is not None and ours.get("rows") is not None:
                acc[g + "rows"].append(0.0 if [r or "" for r in ours["rows"]] == pt["rows"][:len(ours["rows"])] else math.inf)
    return acc, missing


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--reuse", action="store_true")
    a = ap.parse_args()
    sets = gen()
    cases = []
    for name, kind, t in sets:
        cfgs = [c for c in CONFIGS if not c[3] or kind in c[3]]
        cases.append(O.Case(name, [spec_for(kind, t)], [(c[1], params(c[1], c[2]), 0, c[0]) for c in cfgs]))
    res = TO.run_tables(cases, a.out, timeout=60, reuse=a.reuse)
    acc, missing = compare_all(sets, res)
    good = 0
    for k in sorted(acc):
        w = max(acc[k])
        if w <= 1e-9:
            good += 1
        else:
            bad = sum(1 for v in acc[k] if v > 1e-9)
            print(f"   {w:9.2e}  {k}  (bad {bad}/{len(acc[k])})")
    print(f"   {good} field groups agree")
    for k, v in sorted(missing.items()):
        print(f"   missing {v:3d}  {k}")


if __name__ == "__main__":
    main()
