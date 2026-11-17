"""Row-keyed cell metadata of a bundle replicate (data/sets/*.json):
`cellAttributes` [{"rows": "0~4", "attributes": [...]}], `cellAlignments`
[{"rows": "2~7", "attributes": "left"}] and `cellTextFormats` {"<row>": ...}.

decode() gives {row: value} per field; encode() writes a field back only
when its content changed (an unchanged file stays byte-identical), with
consecutive rows of equal value as one "a~b" run and a new key placed
before lastRow (Prism's order, 1,100+ corpus replicates). Verified encoding
of an exclusion: Prism re-saved a .pzfx value marked Excluded as
{"rows": "0", "attributes": ["EXCLUDED"]} (docs/experiments.md, E-excl)."""

from __future__ import annotations

from typing import Any

FIELDS = ("cellAlignments", "cellTextFormats", "cellAttributes")  # stored order


def rows_of(spec: str) -> range:
    if "~" in spec:
        a, b = spec.split("~")
        return range(int(a), int(b) + 1)
    return range(int(spec), int(spec) + 1)


def decode(rep: dict) -> dict[str, dict[int, Any]]:
    out: dict[str, dict[int, Any]] = {f: {} for f in FIELDS}
    for e in rep.get("cellAttributes", []):
        for r in rows_of(e["rows"]):
            out["cellAttributes"].setdefault(r, [])
            out["cellAttributes"][r] += [a for a in e.get("attributes", []) if a not in out["cellAttributes"][r]]
    for e in rep.get("cellAlignments", []):
        for r in rows_of(e["rows"]):
            out["cellAlignments"][r] = e.get("attributes")
    for k, v in (rep.get("cellTextFormats") or {}).items():
        out["cellTextFormats"][int(k)] = v
    return out


def _runs(rows: dict[int, Any]) -> list[tuple[str, Any]]:
    out: list[tuple[int, int, Any]] = []
    for r in sorted(rows):
        v = rows[r]
        if out and out[-1][1] == r - 1 and out[-1][2] == v:
            out[-1] = (out[-1][0], r, v)
        else:
            out.append((r, r, v))
    return [(str(a) if a == b else f"{a}~{b}", v) for a, b, v in out]


def _put(rep: dict, key: str, value) -> None:
    if key in rep or value is None:
        if value is None:
            rep.pop(key, None)
        else:
            rep[key] = value
        return
    items = list(rep.items())
    at = next((i for i, (k, _) in enumerate(items) if k in ("lastRow", "firstRow")), len(items))
    later = FIELDS[FIELDS.index(key) + 1:]
    at = min([at] + [i for i, (k, _) in enumerate(items) if k in later])
    items.insert(at, (key, value))
    rep.clear()
    rep.update(items)


def encode(rep: dict, want: dict[str, dict[int, Any]]) -> bool:
    """Bring the replicate's fields to `want` ({field: {row: value}}); True when
    anything changed."""
    have = decode(rep)
    changed = False
    for f in FIELDS:
        w = {r: v for r, v in want.get(f, {}).items() if v not in (None, [], "")}
        if f == "cellAttributes":
            same = {r: set(v) for r, v in have[f].items()} == {r: set(v) for r, v in w.items()}
        else:
            same = have[f] == w
        if same:
            continue
        changed = True
        if f == "cellTextFormats":
            _put(rep, f, {str(r): w[r] for r in sorted(w)} or None)
        else:
            _put(rep, f, [{"rows": spec, "attributes": v} for spec, v in _runs(w)] or None)
    return changed
