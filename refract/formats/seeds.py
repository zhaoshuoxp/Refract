"""Seed graphs for writing Refract's graphs as Prism graphs (PLAN §2.4
level B). A seed is a graph Prism made; Refract copies it and binds it to a
table (refract.formats.graph_transplant).

The seeds shipped with Refract are in seed_graphs/: one graph blob per table
kind, made by tools/make_seeds.py from a project of Refract's own with
neutral generated data that Prism re-saved, so they hold Prism's default
graph structure and nothing of any sample or user file. index.json gives,
per kind, the blob and the data-set fenIDs it plots (six data sets; the pie
one).

$REFRACT_SEEDS may name another seed source: a seed_graphs-style directory,
or a .prism file whose graphs are read as seeds (the first of each kind).
"""

from __future__ import annotations

import json
import os

from .graph_transplant import Seed, is_pie
from .zipio import ZipArchive

SHIPPED = os.path.join(os.path.dirname(os.path.abspath(__file__)), "seed_graphs")
CANDIDATES = [SHIPPED]
KINDS = ("column", "grouped", "xy", "survival", "parts_of_whole")
# survival: plots a survival analysis's results; parts_of_whole: a pie of the first data set

_cache: dict[str, dict[str, Seed]] = {}


def path() -> str | None:
    for p in [os.environ.get("REFRACT_SEEDS"), *CANDIDATES]:
        if p and os.path.exists(p):
            return p
    return None


def _from_dir(d: str) -> dict[str, Seed]:
    with open(os.path.join(d, "index.json")) as f:
        index = json.load(f)
    out: dict[str, Seed] = {}
    for kind, e in index.items():
        with open(os.path.join(d, e["file"]), "rb") as f:
            blob = f.read()
        out[kind] = Seed(blob, e["sheet"], e["y_fens"], e.get("row_fen"), e.get("x_fen"), kind)
    return out


def _from_prism(p: str) -> dict[str, Seed]:
    z = ZipArchive.open(p)
    out: dict[str, Seed] = {}
    for g in json.loads(z.read("document.json"))["sheets"].get("graphs", []):
        try:
            s = Seed.from_bundle(z, g)
        except (ValueError, KeyError):
            continue
        if s.kind == "parts_of_whole" and not is_pie(s.blob):
            continue
        out.setdefault(s.kind, s)
    return out


def library() -> dict[str, Seed]:
    """Seeds by table kind ({} without a seed source)."""
    p = path()
    if p is None:
        return {}
    if p not in _cache:
        lib = _from_dir(p) if os.path.isdir(p) else _from_prism(p)
        _cache[p] = {k: s for k, s in lib.items() if k in KINDS and s.blob[:8] == b"PCFFGRA4"}
    return _cache[p]


TYPES = os.path.join(SHIPPED, "types")  # per graph type (tools/make_type_seeds.py)
_types: dict[str, Seed] | None = None


def type_seed(key: str) -> Seed | None:
    """The seed of a graph type Refract writes from a graph Prism made of that
    type (separated, stacked, floating bars and the other types whose stored
    form was taken from Prism's own graphs: tools/make_type_seeds.py); None
    when there is none."""
    global _types
    if _types is None:
        _types = {}
        index = os.path.join(TYPES, "index.json")
        if os.path.exists(index):
            with open(index) as f:
                for k, e in json.load(f).items():
                    with open(os.path.join(TYPES, e["file"]), "rb") as g:
                        blob = g.read()
                    if blob[:8] == b"PCFFGRA4":
                        _types[k] = Seed(blob, e["sheet"], e["y_fens"], e.get("row_fen"), e.get("x_fen"), e["kind"])
    return _types.get(key)
