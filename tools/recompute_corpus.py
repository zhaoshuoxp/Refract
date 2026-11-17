"""Recompute every stored analysis in the local corpus with refract.stats
(inputs taken from the tables the way the user interface takes them,
refract.stats.inputs) and compare value by value with Prism's stored results.

Usage: .venv/bin/python tools/recompute_corpus.py [--timeout 20]

Files under */inputs/ and input.prism copies are skipped: probes changed
their data without Prism recomputing, so their stored results are stale.
"""

from __future__ import annotations

import argparse
import collections
import glob
import os
import signal
import sys
import warnings

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)

from refract.formats import open_document  # noqa: E402
from refract.stats import inputs as INP  # noqa: E402


class _Timeout(Exception):
    pass


def _alarm(*_a):
    raise _Timeout


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeout", type=int, default=20, help="seconds per analysis")
    args = ap.parse_args()
    warnings.filterwarnings("ignore")
    signal.signal(signal.SIGALRM, _alarm)
    pats = [os.path.join(ROOT, "corpus", d, "**", "*.prism") for d in ("user", "manual", "auto")]
    files = sorted({f for p in pats for f in glob.glob(p, recursive=True)
                    if "/inputs/" not in f and not f.endswith("input.prism")})
    stats = collections.defaultdict(lambda: [0, 0, 0, 0, 0])  # stored, computed, all agree, values agree, values
    fails: collections.Counter = collections.Counter()
    for f in files:
        try:
            p = open_document(f)
        except Exception:  # noqa: BLE001 - unreadable corpus files are counted elsewhere
            continue
        for a in p.analyses:
            stored = a.results.get("content")
            if a.analysis_class not in INP.SUPPORTED or not stored:
                continue
            s = stats[a.analysis_class]
            s[0] += 1
            signal.alarm(args.timeout)
            try:
                ours = INP.recompute(p, a)
            except Exception as e:  # noqa: BLE001
                fails[f"{a.analysis_class}: {type(e).__name__}: {str(e)[:70]}"] += 1
                continue
            finally:
                signal.alarm(0)
            s[1] += 1
            both = [d for d in INP.compare(stored, ours) if d.stored is not None and d.ours is not None]
            ag = sum(d.agrees for d in both)
            s[2] += bool(both) and ag == len(both)
            s[3] += ag
            s[4] += len(both)
    print(f"{'class':30s} {'stored':>6s} {'run':>5s} {'exact':>6s}  values agreeing")
    for k, (n, r, full, ag, tot) in sorted(stats.items()):
        print(f"{k:30s} {n:6d} {r:5d} {full:6d}  {ag}/{tot} ({ag / max(tot, 1):.4f})")
    for msg, n in fails.most_common(10):
        print(f"  not computed x{n}: {msg}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
