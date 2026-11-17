"""Compare Refract with the results Prism stored in its own bundled sample
templates (read in place, read-only; nothing is copied): every analysis the
templates hold is recomputed from its own parameters and data, and each value
and result-table cell is compared with Prism's.

The trial Prism on this machine does not compute clustering or the analyses of
a Multiple-variables table (variableDesign), so these templates are the
reference for them (docs/experiments.md E-cluster, E-mv).

Usage: .venv/bin/python -I tools/template_parity.py [TEMPLATE ...]
(default: every Multiple-variables template of the installed Prism)
"""

from __future__ import annotations

import glob
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import table_oracle as TO

from refract.formats.prism_reader import read_prism
from refract.stats import inputs as I

SAMPLES = "/Applications/Prism 11.app/Contents/SharedSupport/SampleData/MultipleVariables"
CLASSES = {"HIERARCHICAL_CLUSTERING", "T_TESTS_AND_NONPARAMETRIC", "NONLINEAR_REGRESSION", "SURVIVAL",
           "EXTRACT_REARRANGE", "SELECT_TRANSFORM", "PCA"}
# K-means: Prism starts from one random partition, so its clusters are not reproduced (clustering.k_means)


def close(a: float, b: float) -> bool:
    return abs(a - b) <= 1e-6 * max(1.0, abs(a)) or (math.isnan(a) and math.isnan(b))


def cells(pt: dict, ot: dict) -> tuple[int, int]:
    cols = ([pt["rows"]] if pt.get("rows") else []) + [sub for st in pt["sets"] for sub in st["subs"]]
    if pt.get("x"):  # an XY result table: its X column comes first
        cols = [pt["x"][0], *cols]
    rows = ot["rows"]
    if ot.get("row_titles"):  # Refract keeps a table's row titles beside its rows
        rows = [[ot["row_titles"][r], *row] for r, row in enumerate(rows)]
    if not pt.get("x") and ot.get("columns", [""])[0] == "X":  # Prism's curve X: a series, not stored
        rows = [row[1:] for row in rows]
    n = bad = 0
    for j, col in enumerate(cols):
        for r, cell in enumerate(col):
            o = rows[r][j] if r < len(rows) and j < len(rows[r]) else None
            c = TO.num(cell)
            n += 1
            if isinstance(c, float) and isinstance(o, (int, float)):
                bad += not close(c, float(o))
            else:
                bad += (cell or "") != ("" if o is None else (f"{o:g}" if isinstance(o, float) else str(o)))
    return n, bad


def main(paths: list[str]) -> int:
    total = wrong = 0
    for f in paths:
        proj = read_prism(f, include_results=True)
        tabs = TO.collect_tables(f)
        for a in proj.analyses:
            if a.analysis_class not in CLASSES:
                continue
            try:
                ours = I.recompute(proj, a)
            except NotImplementedError as e:
                print(f"{os.path.basename(f)}: {a.title} ({a.analysis_class}): not supported ({e})")
                continue
            stored = a.results.get("content", a.results) if isinstance(a.results, dict) else {}
            diffs = I.compare(stored, ours)
            both = [d for d in diffs if d.stored is not None and d.ours is not None]
            # PCA's parallel analysis: Prism's own random simulations, not reproduced (refract.stats.pca)
            both = [d for d in both if "parallelAnalysisValue" not in d.path]
            bad = [d for d in both if not close(d.stored, d.ours)]
            print(f"{os.path.basename(f)}: {a.title} ({a.analysis_class}): {len(both)} values, {len(bad)} differ, "
                  f"{sum(d.ours is None for d in diffs)} not computed")
            for d in bad[:5]:
                print(f"    {d.path}: Prism {d.stored}, Refract {d.ours}")
            total += len(both)
            wrong += len(bad)
            mine = ours.get("_tables") or {}
            for name, pt in tabs.get(a.title, {}).get("tables", {}).items():
                ot = mine.get(name) or (mine.get("Result") if a.analysis_class in I.TABLE_OUT else None)
                if ot is not None:
                    n, b = cells(pt, ot)
                    print(f"    table {name}: {n} cells, {b} differ")
                    total += n
                    wrong += b
    print(f"{total} values and cells compared, {wrong} differ")
    return 1 if wrong else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] or sorted(glob.glob(os.path.join(SAMPLES, "*.prismt")))))
