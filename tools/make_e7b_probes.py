"""E7b: edit the axis *settings* chunk (0x8025), which E7 showed is what
Prism renders from (0x0017 is a cache recomputed on open).

Usage: .venv/bin/python -I tools/make_e7b_probes.py <seed.prism> <out_dir>
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from refract.formats.pcff import fields  # noqa: E402
from refract.formats.pcff.probe import build_probes  # noqa: E402

Y = 3  # position of the left-Y main segment among the 9 settings chunks


def y_settings(**changes):
    def apply(ch):
        c = fields.axis_settings(ch)[Y]
        s = fields.AxisSettings.read(c)
        for k, v in changes.items():
            setattr(s, k, v)
        s.write(c)
    return apply


def y_settings_and_cache(**changes):
    def apply(ch):
        y_settings(**changes)(ch)
        a_chunk = fields.axes(ch)[1]
        a = fields.Axis.read(a_chunk)
        if "min" in changes:
            a.draw_min = changes["min"]
        if "max" in changes:
            a.draw_max = changes["max"]
        a.write(a_chunk)
    return apply


PROBES = {
    "E7b-01_ymax3": ("Y settings max 1.5 -> 3", y_settings(max=3.0)),
    "E7b-02_ymin05": ("Y settings min 0 -> 0.5", y_settings(min=0.5)),
    "E7b-03_ytick025": ("Y major tick interval 0.5 -> 0.25", y_settings(major_tick=0.25)),
    "E7b-04_ylog": ("Y log10 on, range 10^-2 .. 10^1, tick 1 decade",
                    y_settings(log10=1, min=-2.0, max=1.0, major_tick=1.0)),
    "E7b-05_ymax3_both": ("Y max 1.5 -> 3 in settings AND cache (in case 01 shows nothing)",
                          y_settings_and_cache(max=3.0)),
}

if __name__ == "__main__":
    build_probes(sys.argv[1], sys.argv[2], PROBES)
