"""Colour schemes for graphs (Graph ▸ Color Scheme, docs/ui-spec.md §3.4):
named lists of data-set colours, applied as Format Graph overrides
(refract.render.formatting "sets"). The built-in lists are our own picks
(one taken from a colour picture the user supplied), published
colour-blind-safe palettes (Okabe & Ito 2008; Tol 2021) and samples of the
open perceptually uniform colour maps (viridis family).
Custom schemes are kept in the user's preferences (refract.ui.look)."""

from __future__ import annotations

import copy
import re

from .model import Graph

BUILT_IN: dict[str, list[str]] = {
    "Black": ["#000000"] * 6,
    "Grays": ["#000000", "#595959", "#8c8c8c", "#b3b3b3", "#d4d4d4", "#2e2e2e"],
    "Bright": ["#1f5fd6", "#e0352b", "#2a9d3c", "#9b3fd1", "#f08a00", "#000000"],
    "Colorblind safe (Okabe-Ito)": ["#e69f00", "#56b4e9", "#009e73", "#f0e442", "#0072b2", "#d55e00", "#cc79a7",
                                    "#000000"],
    "Colorblind safe (Tol bright)": ["#4477aa", "#ee6677", "#228833", "#ccbb44", "#66ccee", "#aa3377", "#bbbbbb"],
    "Ocean": ["#03396c", "#005b96", "#6497b1", "#b3cde0", "#011f4b", "#2a7f9e"],
    "Sunset": ["#5b1a5e", "#a2295f", "#de4d4d", "#f78c46", "#fbc65a", "#2d1b3d"],
    "Forest": ["#1b4332", "#2d6a4f", "#52b788", "#95d5b2", "#7f5539", "#b08968"],
    "Pastel": ["#8fb8de", "#f4a6a6", "#a8d8a0", "#d3b5e5", "#f9cf8b", "#a5a5a5"],
    # taken from a colour picture the user supplied (E-colors, 2026-11-16)
    "Misty Blue and Peach": ["#6f91b8", "#a9cbe3", "#d7e7ef", "#e8a49a", "#f0c6aa", "#a4c5b6"],
    "Viridis": ["#440154", "#414487", "#2a788e", "#22a884", "#7ad151", "#fde725"],
    "Magma": ["#000004", "#3b0f70", "#8c2981", "#de4968", "#fe9f6d", "#fcfdbf"],
    "Inferno": ["#000004", "#420a68", "#932667", "#dd513a", "#fca50a", "#fcffa4"],
    "Plasma": ["#0d0887", "#6a00a8", "#b12a90", "#e16462", "#fca636", "#f0f921"],
    "Cividis": ["#00224e", "#35456c", "#666970", "#948e77", "#c8b866", "#fee838"],
}


def _library() -> dict[str, dict[str, dict[str, list[str]]]]:
    """The R packages' palettes (refract.render.palette_library) by package,
    menu group and palette; a group of continuous palettes is split by its
    first word (bs5, material, tw3) to keep the menus short."""
    from . import palette_library as L

    gg: dict[str, dict[str, list[str]]] = {}
    for group, pals in L.GGSCI.items():
        if group != "Continuous":
            gg[group] = pals
            continue
        for name, cols in pals.items():
            sub = {"bs5": "Continuous: Bootstrap 5", "material": "Continuous: Material",
                   "tw3": "Continuous: Tailwind"}.get(name.split()[0], "Continuous")
            gg.setdefault(sub, {})[name] = cols
    return {"RColorBrewer": L.BREWER, "ggsci": gg}


LIBRARY = _library()


def library_name(package: str, palette: str) -> str:
    """A library palette's scheme name (unique among all schemes)."""
    return f"{package} {palette}"


def library_schemes() -> dict[str, list[str]]:
    return {library_name(pkg, name): cols for pkg, groups in LIBRARY.items() for pals in groups.values()
            for name, cols in pals.items()}


HEX = re.compile(r"#([0-9A-Fa-f]{6})(?:[0-9A-Fa-f]{2})?\b|\b([0-9A-Fa-f]{6})\b")  # #RRGGBB[AA], RRGGBB


def parse_colors(text: str) -> list[str]:
    """The colours written in a text, in order: hex codes with or without #
    (#6F91B8, 6f91b8; R's #RRGGBBAA without its alpha), as pasted from a
    palette picture's caption, a CSS or R vector, or a list file. Repeats are
    kept (a scheme may repeat a colour)."""
    return [f"#{(m.group(1) or m.group(2)).upper()}" for m in HEX.finditer(text or "")]


def apply(fmt: dict | None, g: Graph, colors: list[str]) -> dict:
    """fmt with the data sets coloured from `colors` in turn: bars get their
    fill (borders and error bars keep theirs), symbols and lines their colour."""
    out = copy.deepcopy(fmt or {})
    if not colors:
        return out
    sets = out.setdefault("sets", {})
    for i, s in enumerate(g.series):
        c = colors[i % len(colors)]
        f = sets.setdefault(str(i), {})
        f["fill"] = c
        if s.kind != "bar":
            f["color"] = c
    return out


def colors_of(g: Graph) -> list[str]:
    """The data sets' colours as a scheme (bars: fill; others: colour)."""
    from .formatting import hex_color

    return [hex_color(s.fill if s.kind == "bar" else (s.point_color or s.color)) for s in g.series]
