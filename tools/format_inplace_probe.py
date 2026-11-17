"""E-inplace: graphs from a Prism file formatted in Refract and patched in
place on save (PLAN §2.4 level A), opened, exported and re-saved by Prism.

Usage:
  .venv/bin/python tools/format_inplace_probe.py make <out_dir> <file.prism> [--titles]
  .venv/bin/python -I tools/prism_auto.py <out_dir>/prism <out_dir>/formatted.prism
  .venv/bin/python tools/format_inplace_probe.py compare <out_dir> <file.prism>
"""

from __future__ import annotations

import json
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

FORMATS = {  # graph title prefix -> overrides
    "Grouped": {"y": {"min": 0.0, "max": 60.0, "tick": 20.0}, "sets": {"0": {"fill": "#e07a5f"}, "1": {"fill": "#3d85c6"}}},
    "XY": {"y": {"log": True}, "sets": {"1": {"color": "#d1495b"}}},
    "Col": {"y": {"max": 12.0}},
}
# --titles (E-axes): titles, text sizes, label angle and symbol shapes instead
TITLES = {
    "Grouped": {"y": {"title": "Counts per field", "title_size": 14}, "x": {"label_size": 9}},
    "XY": {"title": "Renamed XY", "title_size": 18, "x": {"title": "Elapsed (h)"},
           "sets": {"0": {"symbol": "triangle"}}},
    "Col": {"x": {"angle": 90}, "y": {"title": "Response", "label_size": 14}},
}


def make(out: str, src: str) -> int:
    from refract.render import qt
    from refract.ui.document import Document

    qt.ensure_app()
    os.makedirs(out, exist_ok=True)
    doc = Document.open(src)
    formats = TITLES if "--titles" in sys.argv else FORMATS
    for i, g in enumerate(doc.project.graphs):
        for prefix, fmt in formats.items():
            if g.title.startswith(prefix):
                doc.set_prism_format(i, fmt)
    touched = doc.save(os.path.join(out, "formatted.prism"))
    print("rewritten:", touched)
    print("report:", doc.last_report)
    return 0


def compare(out: str, src: str) -> int:
    from refract.formats.pcff import fields as F
    from refract.formats.pcff import walker as W
    from refract.formats.zipio import ZipArchive

    a, mine = ZipArchive.open(src), ZipArchive.open(os.path.join(out, "formatted.prism"))
    same = [n for n in a.names() if mine.has(n) and a.read(n) == mine.read(n)]
    print(f"entries unchanged by Refract: {len(same)} of {len(a.names())}")
    res = ZipArchive.open(os.path.join(out, "prism", "formatted", "resaved.prism"))
    doc = json.loads(res.read("document.json"))
    for k, uid in enumerate(doc["sheets"]["graphs"], 1):
        gs = json.loads(res.read(f"graphs/{uid}/sheet.json"))
        ch = W.parse(res.read(f"graphs/{uid}/data.bin"))
        s = F.AxisSettings.read(F.axis_settings(ch)[3])
        m = F.AxisMode.read(F.axis_modes(ch)[1])
        print(f"  graph_{k} {gs['title'][:24]:24s} Y {'log ' if s.log10 else ''}{s.min:g}..{s.max:g} tick "
              f"{s.major_tick:g} manual {bool(m.flags & 0xC)}")
    return 0


if __name__ == "__main__":
    if sys.argv[1] == "make":
        raise SystemExit(make(sys.argv[2], sys.argv[3]))
    raise SystemExit(compare(sys.argv[2], sys.argv[3]))
