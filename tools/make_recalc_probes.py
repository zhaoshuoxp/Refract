"""Does Prism recompute analysis X on open? Variants per analysis:
  control          unchanged
  results_cleared  results.json -> {"@class": "AnalysisResults"}
  results_tampered every float in results.json content -> 12345.678
  input_changed    first numeric cell of the analysis' first input table x 2 (+1)

Usage: .venv/bin/python -I tools/make_recalc_probes.py <seed.prism> <analysis_uid> <out_dir>
Then run tools/prism_auto.py on the outputs and compare result_*.csv.
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from refract.formats import bundle as B


def tamper(o):
    if isinstance(o, dict):
        return {k: tamper(v) for k, v in o.items()}
    if isinstance(o, list):
        return [tamper(v) for v in o]
    if isinstance(o, float):
        return 12345.678
    return o


def main(seed: str, a: str, out: str) -> None:
    res = f"analyses/{a}/results.json"

    def cleared(arc):
        arc.put(res, json.dumps({"@class": "AnalysisResults"}, indent="\t").encode())

    def tampered(arc):
        B.edit_json(arc, res, lambda j: j.__setitem__("content", tamper(j["content"])))

    def input_changed(arc):
        sheet = B.get_json(arc, f"analyses/{a}/sheet.json")["inputSheets"][0]["uid"]
        t = B.get_json(arc, f"data/sheets/{sheet}/sheet.json")["table"]["uid"]
        name = f"data/tables/{t}/data.csv"
        rows = arc.read(name).decode().split("\n")
        for r, row in enumerate(rows):
            cells = row.split(",")
            for c, v in enumerate(cells):
                try:
                    x = float(v)
                except ValueError:
                    continue
                cells[c] = repr(x * 2 + 1)
                rows[r] = ",".join(cells)
                arc.put(name, "\n".join(rows).encode())
                print(f"    input change: row {r} col {c}: {v} -> {cells[c]}")
                return
        raise SystemExit("no numeric input cell found")

    B.build_variants(seed, out, {
        "control": ("unchanged", None),
        "results_cleared": ("results.json emptied", cleared),
        "results_tampered": ("all result floats = 12345.678", tampered),
        "input_changed": ("first numeric input cell x2+1", input_changed),
    })


if __name__ == "__main__":
    main(*sys.argv[1:4])
