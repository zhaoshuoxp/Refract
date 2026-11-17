"""Compare refract.render.autoscale with the auto axes of the local corpus.

Usage: .venv/bin/python -I tools/autoscale_check.py [axes.json] [--show N]
axes.json: rows {kind, axis, dmin, dmax, lo, hi, tick, log, auto} (collected from PCFF).
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from refract.render.autoscale import auto_range


def main():
    path = sys.argv[1]
    show = int(sys.argv[sys.argv.index("--show") + 1]) if "--show" in sys.argv else 20
    rows = [r for r in json.load(open(path)) if r["auto"] and not r["log"] and r["kind"] in (0, 1, 3, 5, 7, 8)
            and (r["axis"] == "Y" or r["kind"] == 0)]
    ok, bad = 0, []
    for r in rows:
        lo, hi, t = auto_range(r["dmin"], r["dmax"])
        if all(abs(a - b) <= 1e-9 * max(1, abs(b)) for a, b in ((lo, r["lo"]), (hi, r["hi"]), (t, r["tick"]))):
            ok += 1
        else:
            bad.append((r, (lo, hi, t)))
    print(f"{ok}/{len(rows)} auto linear axes reproduced")
    for r, got in bad[:show]:
        print(f"  k{r['kind']} {r['axis']} data {r['dmin']:.5g}..{r['dmax']:.5g}  prism {r['lo']:.5g}..{r['hi']:.5g}/{r['tick']:.5g}"
              f"  ours {got[0]:.5g}..{got[1]:.5g}/{got[2]:.5g}  {r['file'][:28]}")


if __name__ == "__main__":
    main()
