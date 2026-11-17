"""Parity of refract.stats with Prism on generated data (Prism = oracle).

Usage: .venv/bin/python -I tools/stats_parity.py <out_dir> [--n 24] [--reuse]

For every generated data pair, writes one document with column statistics and
all seven two-sample designs, lets Prism compute them (tools/stats_oracle.py),
and compares every numeric field present in both results.
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

from stats_oracle import Case, run

from refract.formats.bundle_builder import DataSet, TableSpec
from refract.formats.zipio import ZipArchive
from refract.stats.descriptive import describe
from refract.stats.two_sample import DESIGNS, two_sample

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")


def template(path: str, cls: str) -> dict:
    z = ZipArchive.open(path)
    d = json.loads(z.read("document.json"))
    for a in d["sheets"].get("analyses", []):
        if json.loads(z.read(f"analyses/{a}/sheet.json"))["analysisClass"] == cls:
            return json.loads(z.read(f"analyses/{a}/parameters.json"))["content"]
    raise KeyError(cls)


def gen_pairs(k: int, seed: int = 1) -> list[tuple[str, list[float], list[float]]]:
    rnd = random.Random(seed)
    out = []
    for i in range(k):
        n = rnd.choice([3, 4, 5, 6, 8, 10, 12, 15, 20, 30])
        kind = i % 7
        if kind == 0:   # plain normal
            a = [round(rnd.gauss(10, 2), 4) for _ in range(n)]
            b = [round(x + rnd.gauss(1.5, 1), 4) for x in a]
        elif kind == 1:  # ties (integers)
            a = [rnd.randint(1, 6) for _ in range(n)]
            b = [rnd.randint(2, 8) for _ in range(n)]
        elif kind == 2:  # negatives and mixed scale
            a = [round(rnd.uniform(-5, 5), 3) for _ in range(n)]
            b = [round(rnd.uniform(-3, 8), 3) for _ in range(n)]
        elif kind == 3:  # skewed positive (ratio-friendly)
            a = [round(rnd.lognormvariate(1, 0.6), 5) for _ in range(n)]
            b = [round(x * rnd.lognormvariate(0.2, 0.3), 5) for x in a]
        elif kind == 4:  # unequal variances
            a = [round(rnd.gauss(0, 1), 4) for _ in range(n)]
            b = [round(rnd.gauss(1, 4), 4) for _ in range(n)]
        elif kind == 5:  # near-identical groups
            a = [round(rnd.gauss(50, 5), 2) for _ in range(n)]
            b = [round(x + rnd.choice([-0.5, 0.0, 0.5]), 2) for x in a]
        else:            # unequal group sizes
            m = rnd.choice([3, 5, 7, 11, 16, 25])
            a = [round(rnd.gauss(5, 2), 3) for _ in range(n)]
            b = [round(rnd.gauss(6, 3), 3) for _ in range(m)]
        out.append((f"pair{i:02d}_n{n}_k{kind}", a, b))
    return out


def leaves(o, prefix=""):
    if isinstance(o, dict):
        for k, v in o.items():
            yield from leaves(v, f"{prefix}/{k}")
    elif isinstance(o, (int, float)) and not isinstance(o, bool):
        yield prefix, float(o)


def compare(ours: dict, theirs: dict, stats_acc: dict, missing: collections.Counter, scope: str) -> None:
    o = dict(leaves(ours))
    t = dict(leaves(theirs))
    for path, tv in t.items():
        if path.endswith(("/level", "/idx")):
            continue
        key = f"{scope}{path}"
        if path not in o:
            missing[key] += 1
            continue
        ov = o[path]
        if math.isnan(ov) and math.isnan(tv):
            continue
        err = abs(ov - tv) / max(abs(tv), 1e-300) if tv != 0 else abs(ov)
        stats_acc[key].append(err)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--n", type=int, default=24)
    ap.add_argument("--reuse", action="store_true", help="reuse Prism results already in <out>/results.json")
    a = ap.parse_args()
    base_t = template(os.path.join(ROOT, "corpus", "seeds", "R_paired_ttest.prism"), "T_TESTS_AND_NONPARAMETRIC")
    base_c = template("/Applications/Prism 11.app/Contents/SharedSupport/Portfolio/Graphs to explore/Geometric mean.pzt",
                      "COLUMN_STATISTICS")
    pairs = gen_pairs(a.n)
    cases = []
    for name, x, y in pairs:
        analyses = [("COLUMN_STATISTICS", base_c, 0, "colstats")]
        for d in DESIGNS:
            p = copy.deepcopy(base_t)
            p["experimentalDesign"] = d
            analyses.append(("T_TESTS_AND_NONPARAMETRIC", p, 0, d))
        cases.append(Case(name, [TableSpec("G", "column", "y_single", [DataSet("A", [x]), DataSet("B", [y])])], analyses))
    res_path = os.path.join(a.out, "results.json")
    if a.reuse and os.path.exists(res_path):
        with open(res_path) as f:
            res = json.load(f)
    else:
        res = run(cases, a.out)
    acc: dict[str, list[float]] = collections.defaultdict(list)
    missing: collections.Counter = collections.Counter()
    for name, x, y in pairs:
        r = res.get(name, {})
        cs = r.get("colstats", {}).get("samples", {})
        for s in cs.values():
            col = s["id"]["col"]["idx"]
            compare(describe(x if col == 0 else y), s["value"]["descriptiveStatistics"], acc, missing, "colstats")
        for d in DESIGNS:
            if d not in r or not r[d]:
                missing[f"{d}: no Prism result"] += 1
                continue
            ours = two_sample(d, x, y, swap=True, alpha=0.05, level=95.0)
            model = next(iter(ours))
            compare(ours[model], r[d].get(model, {}), acc, missing, f"{d}")
    print(f"{len(pairs)} data pairs; worst relative error per field (fields matching to 1e-9 summarised):")
    good = 0
    for key in sorted(acc):
        worst = max(acc[key])
        if worst <= 1e-9:
            good += 1
        else:
            print(f"   {worst:9.2e}  {key}  (n={len(acc[key])})")
    print(f"   {good} fields agree to <= 1e-9 relative")
    if missing:
        print("fields Prism reports that we do not (count):")
        for k, v in sorted(missing.items()):
            print(f"   {v:3d}  {k}")


if __name__ == "__main__":
    main()
