"""Minimal-change editing helpers for existing .prism bundles."""

from __future__ import annotations

import json
import os
from collections.abc import Callable

from . import prismjson
from .pcff import fields
from .pcff.walker import Chunk, parse, serialize
from .zipio import ZipArchive


def get_json(arc: ZipArchive, name: str):
    return prismjson.loads(arc.read(name))


def put_json(arc: ZipArchive, name: str, obj) -> None:
    storage = name.startswith("data/tables/") and name.endswith("content.json")
    arc.put(name, prismjson.dumps_storage(obj) if storage else prismjson.dumps(obj))


def edit_json(arc: ZipArchive, name: str, fn: Callable[[dict], None]) -> None:
    obj = get_json(arc, name)
    fn(obj)
    put_json(arc, name, obj)


def edit_blob(arc: ZipArchive, name: str, fn: Callable[[list[Chunk]], None]) -> None:
    ch = parse(arc.read(name))
    fn(ch)
    arc.put(name, serialize(ch))


def graph_entries(arc: ZipArchive) -> list[str]:
    return [e.name for e in arc.entries if e.name.startswith("graphs/") and e.name.endswith("data.bin")]


def set_graph_title(arc: ZipArchive, old: str, new: str, blob_name: str | None = None) -> None:
    def fn(ch):
        idx = {t: i for i, t in fields.texts(ch)}[old]
        fields.set_text(ch, idx, new)
    edit_blob(arc, blob_name or graph_entries(arc)[0], fn)


def changed_entries(before: ZipArchive, after: ZipArchive) -> dict[str, list[str]]:
    a = {e.name: e for e in before.entries}
    b = {e.name: e for e in after.entries}
    return {
        "added": [n for n in b if n not in a],
        "removed": [n for n in a if n not in b],
        "modified": [n for n in b if n in a and a[n].read() != b[n].read()],
    }


def build_variants(seed_path: str, out_dir: str,
                   variants: dict[str, tuple[str, Callable[[ZipArchive], None] | None]]) -> dict:
    """Write one .prism per variant (seed + edit), plus manifest.json listing
    exactly which archive entries each variant touched."""
    os.makedirs(os.path.join(out_dir, "pdf"), exist_ok=True)
    os.makedirs(os.path.join(out_dir, "resaved"), exist_ok=True)
    with open(seed_path, "rb") as f:
        raw = f.read()
    base = ZipArchive.from_bytes(raw)
    assert base.to_bytes() == raw, "seed does not round-trip byte-identically"
    manifest = {"seed": os.path.basename(seed_path), "variants": {}}
    for name, (desc, fn) in variants.items():
        arc = ZipArchive.from_bytes(raw)
        if fn is not None:
            fn(arc)
        out = arc.to_bytes()
        ZipArchive.from_bytes(out)  # must re-parse
        ch = changed_entries(base, ZipArchive.from_bytes(out))
        with open(os.path.join(out_dir, name + ".prism"), "wb") as f:
            f.write(out)
        manifest["variants"][name] = {"description": desc, "changes": ch}
        n = sum(len(v) for v in ch.values())
        print(f"{name:34s} {n:2d} entries changed  {desc}")
    with open(os.path.join(out_dir, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    return manifest
