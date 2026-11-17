"""E-acceptance: the phase 4 acceptance scenario (tests/test_acceptance.py)
saved to a file, opened and re-saved by Prism, then reopened in Refract.

Usage:
  .venv/bin/python tools/acceptance_probe.py make <out_dir>
  .venv/bin/python -I tools/prism_auto.py <out_dir>/prism <out_dir>/scenario.prism --no-png
  .venv/bin/python tools/acceptance_probe.py compare <out_dir>
"""

from __future__ import annotations

import os
import pathlib
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))


def make(out: str) -> int:
    import test_acceptance as A

    from refract.render import qt

    qt.ensure_app()
    os.makedirs(out, exist_ok=True)
    _w, a, _t, labels, path, _g = A.scenario(pathlib.Path(out))
    print(path, a.title, labels)
    return 0


def compare(out: str) -> int:
    from refract.formats import native_graphs as NG
    from refract.formats import open_document
    from refract.formats import prism_writer as PW
    from refract.formats.zipio import ZipArchive
    from refract.render import native, qt
    from refract.stats import inputs as I

    qt.ensure_app()
    mine = open_document(os.path.join(out, "scenario.prism"))
    path = os.path.join(out, "prism", "scenario", "resaved.prism")
    theirs = open_document(path)
    bad = 0

    def check(ok, what):
        nonlocal bad
        bad += not ok
        print(f"  {'ok ' if ok else 'FAIL'} {what}")

    check(PW.table_grid(theirs.tables[0]) == PW.table_grid(mine.tables[0]), "table unchanged by Prism")
    a = theirs.analyses[0]
    stored = a.results.get("content") or {}
    d = [x for x in I.compare(stored, I.recompute(theirs, a)) if x.stored is not None and x.ours is not None]
    check((stored.get("status") or {}).get("error") == "VALID" and d and all(x.agrees for x in d),
          f"Prism computed {a.title}: {sum(x.agrees for x in d)}/{len(d)} values agree with Refract")
    check(ZipArchive.open(path).has(NG.ENTRY), f"Prism kept {NG.ENTRY}")
    check(len(theirs.native_graphs) == 1 and theirs.native_graphs[0].table is theirs.tables[0],
          "the Refract graph still names its table after Prism's re-save")
    if theirs.native_graphs:
        g = native.graph(theirs, theirs.native_graphs[0], lambda an: an.results.get("content") or {},
                         lambda an: I.source(theirs, an))
        check([b["label"] for b in g.significance] != [], f"stars from Prism's stored results: "
              f"{[b['label'] for b in g.significance]}")
    return 1 if bad else 0


if __name__ == "__main__":
    if sys.argv[1] == "make":
        raise SystemExit(make(sys.argv[2]))
    raise SystemExit(compare(sys.argv[2]))
