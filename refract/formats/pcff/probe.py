"""Build probe documents: a seed bundle with one graph blob mutated."""

from __future__ import annotations

import copy
import json
import os
from collections.abc import Callable

from ..zipio import ZipArchive
from .walker import Chunk, parse, serialize

Mutator = Callable[[list[Chunk]], None]


def single_graph_entry(arc: ZipArchive) -> str:
    bins = [e.name for e in arc.entries if e.name.startswith("graphs/") and e.name.endswith("data.bin")]
    if len(bins) != 1:
        raise ValueError(f"seed must contain exactly one graph, found {len(bins)}")
    return bins[0]


def build_probes(seed_path: str, out_dir: str, probes: dict[str, tuple[str, Mutator | None]]) -> None:
    """Write <out_dir>/<name>.prism for each probe plus manifest.json.

    Asserts that each probe differs from the seed only in the graph entry and
    that a probe with no mutator is byte-identical to the seed.
    """
    os.makedirs(out_dir, exist_ok=True)
    os.makedirs(os.path.join(out_dir, "pdf"), exist_ok=True)
    with open(seed_path, "rb") as f:
        raw = f.read()
    base = ZipArchive.from_bytes(raw)
    assert base.to_bytes() == raw, "seed does not round-trip byte-identically"
    bin_name = single_graph_entry(base)
    blob = base.read(bin_name)
    chunks0 = parse(blob)
    assert serialize(chunks0) == blob

    manifest = {"seed": os.path.basename(seed_path), "graph_entry": bin_name, "probes": {}}
    for name, (desc, mutate) in probes.items():
        arc = ZipArchive.from_bytes(raw)
        if mutate is not None:
            ch = copy.deepcopy(chunks0)
            mutate(ch)
            new_blob = serialize(ch)
            assert new_blob != blob, f"{name}: mutation changed nothing"
            arc.entry(bin_name).replace(new_blob)
        out = arc.to_bytes()
        other = ZipArchive.from_bytes(out)
        diff = [a.name for a, b in zip(base.entries, other.entries, strict=True) if a.read() != b.read()]
        assert diff == ([] if mutate is None else [bin_name]), (name, diff)
        if mutate is None:
            assert out == raw
        with open(os.path.join(out_dir, name + ".prism"), "wb") as f:
            f.write(out)
        manifest["probes"][name] = desc
        print(f"{name:30s} {desc}")
    with open(os.path.join(out_dir, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
