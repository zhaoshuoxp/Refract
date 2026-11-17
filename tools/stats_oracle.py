"""Prism as a statistics oracle.

Build documents that contain our test data and analyses written from scratch
(refract/formats/analysis_writer.py). Have Prism open each one, display every
result (it computes lazily), and save (tools/prism_auto.py). Then read back the
full-precision results.json Prism wrote.

Library use:
    cases = [Case(name, tables=[TableSpec...], analyses=[(cls, content, table_index, title)])]
    results = run(cases, out_dir)   # {case: {analysis title: results content}}
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass, field

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from refract.formats import bundle as B
from refract.formats.analysis_writer import add_analysis
from refract.formats.bundle_builder import BundleBuilder, TableSpec, set_seed
from refract.formats.zipio import ZipArchive

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")


@dataclass
class Case:
    name: str
    tables: list[TableSpec]
    analyses: list[tuple[str, dict, int, str]] = field(default_factory=list)  # (class, content, table idx, title)


def build(case: Case, path: str) -> None:
    set_seed(case.name)
    b = BundleBuilder(full_ui=True)
    b.add_info()
    for t in case.tables:
        b.add_table(t)
    arc = b.build()
    sheets = B.get_json(arc, "document.json")["sheets"]["data"]
    for cls, content, ti, title in case.analyses:
        add_analysis(arc, cls, content, sheets[ti], title=title)
    arc.save(path)


def collect(resaved: str) -> dict[str, dict]:
    z = ZipArchive.open(resaved)
    d = json.loads(z.read("document.json"))
    out = {}
    for a in d["sheets"].get("analyses", []):
        s = json.loads(z.read(f"analyses/{a}/sheet.json"))
        r = json.loads(z.read(f"analyses/{a}/results.json"))
        out[s["title"]] = r.get("content", {})
    return out


def run(cases: list[Case], out_dir: str, timeout: float = 15) -> dict[str, dict[str, dict]]:
    probes = os.path.join(out_dir, "inputs")
    os.makedirs(probes, exist_ok=True)
    paths = []
    for c in cases:
        p = os.path.join(probes, c.name + ".prism")
        build(c, p)
        paths.append(p)
    auto = os.path.join(out_dir, "prism")
    subprocess.run([sys.executable, "-I", os.path.join(ROOT, "tools", "prism_auto.py"), auto, "--timeout", str(timeout),
                    "--no-png", "--tables-only", *paths], check=True, capture_output=True)
    results = {}
    for c in cases:
        rs = os.path.join(auto, c.name, "resaved.prism")
        results[c.name] = collect(rs) if os.path.exists(rs) else {}
    with open(os.path.join(out_dir, "results.json"), "w") as f:
        json.dump(results, f, indent=1)
    return results
