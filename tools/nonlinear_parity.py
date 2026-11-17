"""Parity of nonlinear regression (NONLINEAR_REGRESSION) with Prism on data
generated from the built-in equations (corpus/seeds/nonlinear_equations.json).

Usage: .venv/bin/python -I tools/nonlinear_parity.py <out_dir> [--n 14] [--reuse] [--ci WALD_NAME]
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
from refract.stats import nonlinear as NL
from refract.stats.equation import Model

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")


def _seed(name):
    with open(os.path.join(ROOT, "corpus", "seeds", name)) as f:
        return json.load(f)


BASE, EQUATIONS = _seed("nonlinear_params.json"), _seed("nonlinear_equations.json")
TRUTH = {  # equation name -> (true parameters, x range, log-spaced?)
    "One site binding (hyperbola)": ({"Bmax": 100.0, "Kd": 5.0}, (0.5, 40.0), True),
    "One phase decay": ({"Y0": 100.0, "Plateau": 10.0, "K": 0.3}, (0.0, 20.0), False),
    "log(agonist) vs. response (three parameters)": ({"Bottom": 5.0, "Top": 95.0, "LogEC50": -6.0}, (-9.0, -3.0), False),
    "Straight line": ({"YIntercept": 2.0, "Slope": 0.5}, (0.0, 10.0), False),
    "Sigmoidal dose-response (variable slope)": ({"Bottom": 5.0, "Top": 95.0, "LogEC50": -6.0, "HillSlope": 1.5},
                                                 (-9.0, -3.0), False),
    "Gaussian distribution": ({"AREA": 100.0, "SD": 2.0, "Mean": 10.0}, (2.0, 18.0), False),
    "log(agonist) vs. response -- Variable slope (four parameters)": (
        {"Bottom": 5.0, "Top": 95.0, "LogEC50": -6.0, "HillSlope": 0.8}, (-9.0, -3.0), False),
}
DIAG_ALL = {f"diagnostics/{k}": True for k in ("r2", "adjR2", "lfv", "syx", "rmse", "aicc", "parCovariance")}
CONFIGS = [("profile", {**DIAG_ALL}), ("const", {**DIAG_ALL, "constraint": ("CONST", 1.0)}),
           ("less", {**DIAG_ALL, "constraint": ("LESS", 0.97)})]  # ("wald", ...) added by --ci


# Known, not reproduced:
# - nl11 data set 0: HillSlope is not identifiable (SE 4.0 > estimate 2.4); its
#   profile is symmetric in the sign of HillSlope and crosses the threshold at
#   +1.034 and -1.034. We report the first crossing (+1.034), Prism -1.034.
# - Prism stops at its "medium" convergence criterion: estimates of the
#   Gaussian and variable-slope models differ from the exact least-squares
#   optimum in the 6th digit (our SS is lower or equal), see CONVERGENCE_TOL.
# - An active LESS / GREATER bound: Prism stops just inside the bound with a
#   larger SS than the constrained least-squares optimum (e.g. 164.3 vs 113.1),
#   so those fits are skipped (ACTIVE_BOUND_SKIP); inactive bounds agree, and a
#   profile interval that reaches the bound ends at the bound, as in Prism.
#   Profile intervals near an active constraint follow Prism's own
#   constrained optimiser (sometimes the bound, sometimes "undefined"), so CIs
#   of the "less" configuration are not compared (SKIP_CI_CONFIGS).
KNOWN = {("nl11_Bott", "0", "parameters/HillSlope/ci/lower")}
SKIP_CI_CONFIGS = {"less"}
ACTIVE_BOUND_SKIP = True
CONVERGENCE_TOL = 1e-4


def params(eq_name, ov):
    c = copy.deepcopy(BASE)
    c["model"]["equation"] = copy.deepcopy(EQUATIONS[eq_name]["equation"])
    c["model"]["initialValues"] = {}
    c["model"]["constraints"] = {}
    for path, v in ov.items():
        if path == "constraint":  # (type, factor): constrain the first parameter at factor * its true value
            first = c["model"]["equation"]["parameters"][0]
            c["model"]["constraints"] = {first: {"type": v[0], "value": TRUTH[eq_name][0][first] * v[1]}}
            continue
        d = c
        *head, last = path.split("/")
        for h in head:
            d = d.setdefault(h, {})
        d[last] = v
    return c


def gen(n_sets: int, seed: int = 31):
    """[(name, equation, x, [Y data sets as [subcolumn][row]])]"""
    rnd = random.Random(seed)
    names = list(TRUTH)
    out = []
    for i in range(n_sets):
        eq = names[i % len(names)]
        truth, (x0, x1), logx = TRUTH[eq]
        e = EQUATIONS[eq]["equation"]
        model = Model(e["definition"], e["parameters"])
        n = rnd.choice([7, 9, 12, 16])
        if logx:
            x = [round(x0 * (x1 / x0) ** (k / (n - 1)), 4) for k in range(n)]
        else:
            x = [round(x0 + (x1 - x0) * k / (n - 1), 4) for k in range(n)]
        reps = rnd.choice([1, 2, 3])
        k_sets = rnd.choice([1, 2])
        sets = []
        for s in range(k_sets):
            p = [truth[nm] * (1 + 0.1 * s) for nm in e["parameters"]]
            ys = model(x, p)
            span = max(ys) - min(ys)
            noise = float(rnd.choice([0.02, 0.05, 0.1]) * span)
            subs = [[float(round(float(y) + float(rnd.gauss(0, noise)), 3)) for y in ys] for _ in range(reps)]
            sets.append(subs)
        out.append((f"nl{i:02d}_{e['parameters'][0][:4]}", eq, x, sets))
    return out


def _norm_prism(content):
    """Flatten Prism's per-model / per-data-set hash layers to {col idx: fit}."""
    out = {}
    for m in content.get("models", {}).values():
        idx = m["id"]["col"]["idx"]
        v = copy.deepcopy(m["value"])
        for k in ("equation", "equationTex"):
            v.pop(k, None)
        for name, layer in list(v.get("parameters", {}).items()):
            (inner,) = layer.values()
            inner["value"].pop("dsList", None)
            v["parameters"][name] = inner["value"]
        for k, layer in list(v.get("goodnessOfFit", {}).items()):
            if isinstance(layer, dict) and len(layer) == 1 and "value" in next(iter(layer.values()), {}):
                v["goodnessOfFit"][k] = next(iter(layer.values()))["value"]
        v.pop("iterationCount", None)  # known: Prism's iteration path is not reproduced
        for a_, row in list(v.get("covariance", {}).items()):
            for b_, layer in list(row.items()):
                (inner,) = layer.values()
                row[b_] = inner["value"]
        out[str(idx)] = v
    return out


def ours_for(cfg_ov, eq, x, sets):
    p = params(eq, cfg_ov)
    fmt = "y_replicates" if len(sets[0]) > 1 else "y_single"
    return {str(i): NL.fit_dataset(p, x, subs, i, data_format=fmt) for i, subs in enumerate(sets)}


def compare_all(sets, res, configs=None):
    acc, missing = collections.defaultdict(list), collections.Counter()
    for name, eq, x, ys in sets:
        for cname, ov in configs or CONFIGS:
            theirs = res.get(name, {}).get(cname)
            if theirs is None:
                continue
            ours = ours_for(ov, eq, x, ys)
            if ACTIVE_BOUND_SKIP:
                ours = {i: f for i, f in ours.items() if f["status"] != "HIT_CONSTRAINT"}
            o, t = dict(leaves(ours)), dict(leaves({i: f for i, f in _norm_prism(theirs).items() if i in ours}))
            for p_, v in t.items():
                parts = p_.split("/")
                if (name, parts[1], "/".join(parts[2:])) in KNOWN or (cname in SKIP_CI_CONFIGS and "/ci/" in p_):
                    continue
                g = f"{cname}/{eq[:24]}/" + "/".join("*" if s.isdigit() else s for s in parts[2:])
                if p_ not in o:
                    missing[g] += 1
                    continue
                acc[g].append(close(o[p_], v))
    return acc, missing


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--n", type=int, default=14)
    ap.add_argument("--reuse", action="store_true")
    ap.add_argument("--ci", help="enum name of the asymptotic CI method, adds a config")
    a = ap.parse_args()
    configs = list(CONFIGS)
    if a.ci:
        configs.append(("wald", {**DIAG_ALL, "confidence/ciMethod": a.ci}))
    sets = gen(a.n)
    rp = os.path.join(a.out, "results.json")
    if a.reuse and os.path.exists(rp):
        with open(rp) as f:
            res = json.load(f)
    else:
        cases = []
        for name, eq, x, ys in sets:
            reps = len(ys[0])
            fmt = "y_replicates" if reps > 1 else "y_single"
            spec = TableSpec("XY", "xy", fmt, [DataSet(chr(65 + i), s) for i, s in enumerate(ys)], x_title="X", x_values=x,
                             replicates=reps)
            cases.append(O.Case(name, [spec], [("NONLINEAR_REGRESSION", params(eq, ov), 0, cn) for cn, ov in configs]))
        res = O.run(cases, a.out, timeout=40)
    acc, missing = compare_all(sets, res, configs)
    good = conv = 0
    print(f"{len(sets)} data sets")
    for k in sorted(acc):
        w = max(acc[k])
        if w <= 1e-6:
            good += 1
        elif w <= CONVERGENCE_TOL:
            conv += 1
        else:
            print(f"   {w:9.2e}  {k}  (n={len(acc[k])})")
    print(f"   {good} field groups agree to 1e-6, {conv} more to {CONVERGENCE_TOL:g} (Prism's convergence)")
    for k, v in sorted(missing.items()):
        print(f"   missing {v:3d}  {k}")



if __name__ == "__main__":
    main()
