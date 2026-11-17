"""Parity of nonlinear model comparison (two equations, a constrained
parameter, shared parameters; F test and AICc) and global fits with shared
parameters, with Prism - on the Prism-made sample
(corpus/manual/batch4_samples.prism) and on generated curves.

Usage: .venv/bin/python -I tools/nl_compare_parity.py <out_dir> [--reuse]
"""

from __future__ import annotations

import argparse
import collections
import copy
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import nonlinear_parity as NP
import stats_oracle as O
from anova_parity import close, leaves

from refract.formats.bundle_builder import DataSet, TableSpec

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
SAMPLE = os.path.join(ROOT, "corpus", "manual", "batch4_samples.prism")


def _label(ident) -> str:
    col = (ident or {}).get("col")
    return str(col["idx"]) if col else "shared"


def _flat_layer(layer, single: bool, top="global"):
    """A hash layer {h: {id, value}} -> value (single, per-data-set model) or
    {label: value}."""
    if not (isinstance(layer, dict) and layer and all(isinstance(v, dict) and "value" in v and "id" in v
                                                     for v in layer.values())):
        return layer
    if single and len(layer) == 1:
        return next(iter(layer.values()))["value"]
    out = {}
    for v in layer.values():
        lab = _label(v["id"])
        out[top if lab == "shared" and top else lab] = v["value"]
    return out


def canon_prism(content: dict) -> dict:
    models = {}
    for m in content.get("models", {}).values():
        col = m["id"].get("col")
        key = f"{m['id']['model']['name']}|{f'col{col["idx"]}' if col else 'global'}"
        v = copy.deepcopy(m["value"])
        for k in ("equation", "equationTex", "iterationCount"):
            v.pop(k, None)
        single = col is not None
        for name, layer in list(v.get("parameters", {}).items()):
            if single:
                e = next(iter(layer.values()))["value"]
                e.pop("dsList", None)
                v["parameters"][name] = e
            else:
                v["parameters"][name] = {_label(x["id"]): x["value"] for x in layer.values()}
        for k, layer in list(v.get("goodnessOfFit", {}).items()):
            v["goodnessOfFit"][k] = _flat_layer(layer, single)
        for a, row in list(v.get("covariance", {}).items()):
            for b, layer in list(row.items()):
                row[b] = _flat_layer(layer, single, top=None)
        models[key] = v
    comp = {}
    for c in (content.get("modelComparison") or {}).values():
        col = c["id"][0].get("col")
        comp[f"col{col['idx']}" if col else "global"] = c["value"]
    return {"models": models, "modelComparison": comp}


def canon_ours(out: dict) -> dict:
    return {"models": {k: m["value"] for k, m in out["models"].items()}, "modelComparison":
            {k: c["value"] for k, c in (out.get("modelComparison") or {}).items()}}


def _unstable(c: dict) -> bool:
    """Prism marked a parameter UNSTABLE (it ran off, e.g. a Hill slope to a
    step): the fit then depends on Prism's iteration path (known)."""
    for m in c["models"].values():
        for layer in m.get("parameters", {}).values():
            entries = [layer] if "status" in layer else list(layer.values())
            if any(isinstance(e, dict) and e.get("status") == "UNSTABLE" for e in entries):
                return True
    return False


# known profile edge cases (findings.md): a sign-symmetric Hill slope (Prism
# takes the far crossing, as in batch 9) and a limit at a data X where another
# curve's held profile turns into a step (Prism: undefined)
KNOWN = {("cmp05_k2r1", "share", "/models/Model 2|global/parameters/HillSlope/0/ci/lower"),
         ("cmp02_k2r2", "share", "/models/Model 2|global/parameters/LogEC50/shared/ci/lower"),
         ("cmp02_k2r2", "share", "/models/Model 2|global/parameters/EC50/shared/ci/lower")}


def compare(ours: dict, theirs: dict, tag: str, acc, missing, table: str = ""):
    ct = canon_prism(theirs)
    if _unstable(ct):
        missing[f"known: {tag} with an UNSTABLE parameter"] += 1
        return
    o, t = dict(leaves(canon_ours(ours))), dict(leaves(ct))
    for k, v in t.items():
        if (table, tag, k) in KNOWN:
            missing[f"known: {tag} profile edge case"] += 1
            continue
        g = tag + "/" + "/".join("*" if s.isdigit() else s for s in k.split("/")[1:])
        if k not in o:
            missing[g] += 1
            continue
        acc[g].append(close(o[k], v))


def _num(v):
    return None if v in (None, "") else float(v)


def sample_check():
    import zipfile

    from refract.formats.prism_reader import read_prism
    from refract.stats import nonlinear_global as NG

    t = read_prism(SAMPLE).tables[0]
    x = [_num(v) for v in t.x_values()]
    ds = [[[_num(v) for v in s] for s in d.subcolumns] for d in t.datasets]
    titles = [d.title for d in t.datasets]
    z = zipfile.ZipFile(SAMPLE)
    acc, missing = collections.defaultdict(list), collections.Counter()
    for n in sorted(z.namelist()):
        if n.startswith("analyses") and n.endswith("/sheet.json"):
            p = json.loads(z.read(n.replace("sheet", "parameters")))["content"]
            r = json.loads(z.read(n.replace("sheet", "results")))["content"]
            tag = p["modelComparison"]["type"] + "_" + p["modelComparison"]["method"]
            compare(NG.analysis(p, x, ds, titles, "y_replicates"), r, tag, acc, missing)
    return acc, missing


def report(acc, missing, tol=1e-6):
    good = 0
    for k in sorted(acc):
        w = max(acc[k])
        if w <= tol:
            good += 1
        else:
            print(f"   {w:9.2e}  {k}  (bad {sum(1 for v in acc[k] if v > tol)}/{len(acc[k])})")
    print(f"   {good} field groups agree to {tol:g}")
    for k, v in sorted(missing.items()):
        print(f"   missing {v:3d}  {k}")


EQ3, EQ4 = "log(agonist) vs. response (three parameters)", "log(agonist) vs. response -- Variable slope (four parameters)"


def _other(eq, constraints=None):
    return {"equation": copy.deepcopy(NP.EQUATIONS[eq]["equation"]), "constraints": constraints or {}, "initialValues": {}}


CONFIGS = [  # (name, main equation, main constraints, modelComparison)
    ("f2eq", EQ4, {}, {"type": "TWO_MODLES", "method": "STAT_TEST", "modelToCompare": _other(EQ3)}),
    ("aic2eq", EQ4, {}, {"type": "TWO_MODLES", "method": "AIC_TEST", "modelToCompare": _other(EQ3)}),
    ("hyp", EQ4, {}, {"type": "CONSTRAINED_PARAMETER", "method": "STAT_TEST",
                      "options": {"parameterName": "HillSlope", "hypoteticalValue": 1.0},
                      "modelToCompare": _other(EQ4, {"HillSlope": {"type": "CONST", "value": 1.0}})}),
    ("share", EQ4, {}, {"type": "SHARED_PARAMETERS", "method": "STAT_TEST", "options": {"sharedParameters": ["LogEC50"]},
                        "modelToCompare": _other(EQ4, {"LogEC50": {"type": "SHARE", "value": "undefined"}})}),
    ("share2aic", EQ3, {}, {"type": "SHARED_PARAMETERS", "method": "AIC_TEST",
                            "options": {"sharedParameters": ["Bottom", "Top"]},
                            "modelToCompare": _other(EQ3, {"Bottom": {"type": "SHARE", "value": "undefined"},
                                                           "Top": {"type": "SHARE", "value": "undefined"}})}),
    ("global", EQ4, {"HillSlope": {"type": "SHARE", "value": "undefined"}}, {"type": "NO_COMPARISON"}),
    ("global_wald", EQ3, {"Bottom": {"type": "SHARE", "value": "undefined"}}, {"type": "NO_COMPARISON", "wald": True}),
]


def params_for(cfg):
    _, eq, cons, mc = cfg
    p = NP.params(eq, NP.DIAG_ALL)
    p["model"]["constraints"] = copy.deepcopy(cons)
    mc = copy.deepcopy(mc)
    if mc.pop("wald", False):
        p["confidence"]["ciMethod"] = "WALD"
    p["modelComparison"] = {**p["modelComparison"], **mc}
    return p


def gen(seed: int = 53):
    """[(name, x, datasets)]: 2-3 dose-response curves per table."""
    import random

    from refract.stats.equation import Model

    rnd = random.Random(seed)
    e = NP.EQUATIONS[EQ4]["equation"]
    model = Model(e["definition"], e["parameters"])
    out = []
    for i in range(8):
        n = rnd.choice([7, 9, 12])
        x = [round(-9 + 6 * k / (n - 1), 4) for k in range(n)]
        reps, k_ds = rnd.choice([1, 2, 3]), rnd.choice([2, 2, 3])
        sets = []
        for d in range(k_ds):
            p = [5 + rnd.uniform(-3, 3), 95 + rnd.uniform(-10, 10), -6 + rnd.uniform(-0.8, 0.8), rnd.choice([0.7, 1.0, 1.4])]
            ys = model(x, p)
            noise = rnd.choice([2.0, 4.0, 8.0])
            sets.append([[round(float(y) + rnd.gauss(0, noise), 3) for y in ys] for _ in range(reps)])
        out.append((f"cmp{i:02d}_k{k_ds}r{reps}", x, sets))
    return out


def compare_all(sets, res):
    from refract.stats import nonlinear_global as NG

    acc, missing = collections.defaultdict(list), collections.Counter()
    for name, x, ds in sets:
        fmt = "y_replicates" if len(ds[0]) > 1 else "y_single"
        for cfg in CONFIGS:
            theirs = res.get(name, {}).get(cfg[0])
            if theirs is None:
                missing[f"{cfg[0]}: no Prism result"] += 1
                continue
            ours = NG.analysis(params_for(cfg), x, ds, [chr(65 + i) for i in range(len(ds))], fmt)
            compare(ours, theirs, cfg[0], acc, missing, name)
    return acc, missing


CONVERGENCE_TOL = 1e-3  # Prism's medium criterion (4-parameter and global fits; findings.md)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out", nargs="?")
    ap.add_argument("--reuse", action="store_true")
    a = ap.parse_args()
    print("sample:")
    report(*sample_check())
    if not a.out:
        return
    sets = gen()
    rp = os.path.join(a.out, "results.json")
    if a.reuse and os.path.exists(rp):
        with open(rp) as f:
            res = json.load(f)
    else:
        cases = []
        for name, x, ds in sets:
            reps = len(ds[0])
            spec = TableSpec("XY", "xy", "y_replicates" if reps > 1 else "y_single",
                             [DataSet(chr(65 + i), s) for i, s in enumerate(ds)], x_title="X", x_values=x, replicates=reps)
            cases.append(O.Case(name, [spec], [("NONLINEAR_REGRESSION", params_for(c), 0, c[0]) for c in CONFIGS]))
        res = O.run(cases, a.out, timeout=60)
    print("generated:")
    acc, missing = compare_all(sets, res)
    conv = {k: v for k, v in acc.items() if 1e-6 < max(v) <= CONVERGENCE_TOL}
    report({k: v for k, v in acc.items() if k not in conv}, missing)
    print(f"   {len(conv)} more field groups agree to {CONVERGENCE_TOL:g} (Prism's convergence, known)")


if __name__ == "__main__":
    main()
