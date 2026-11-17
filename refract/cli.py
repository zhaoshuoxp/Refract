"""Command line: python -m refract <command> ...

  inspect   FILE              summary of tables, analyses, graphs, warnings
  verify    FILE              lossless checks (ZIP, graph blobs, CSV rebuild, no-op save)
  export    FILE OUTDIR       every data table as CSV (+ info sheets as JSON)
  diff      A B               what differs between two documents (entries, cells)
  anonymize FILE OUT          clear account names and info-sheet personal fields
  gui [FILE]                  open the desktop app
  selftest [--keep DIR]       check this installation (statistics, drawing, saving)

Values are printed by `diff` and `export`: do not paste their output anywhere
public when the file holds unpublished data.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys

from .formats import open_document, sniff
from .model.document import DataTable


def _read(path: str) -> bytes:
    with open(path, "rb") as f:
        return f.read()


def cmd_inspect(a) -> int:
    data = _read(a.file)
    p = open_document(data)
    print(f"{os.path.basename(a.file)}: {p.source_format}, created by {p.created_by.get('name')} {p.created_by.get('version')}")
    for t in p.tables:
        extra = []
        if t.row_titles is not None:
            extra.append("row titles")
        if t.x is not None:
            extra.append("X series" if t.x.generated else "X")
        if any(d.formula for d in t.datasets):
            extra.append("formula columns")
        print(f"  table  {t.title!r}: {t.kind}/{t.data_format}, {len(t.datasets)} data sets x {t.subcolumns_per_dataset}, "
              f"{t.n_rows} rows{' (' + ', '.join(extra) + ')' if extra else ''}")
    for an in p.analyses:
        print(f"  analysis {an.title!r}: {an.analysis_class}")
    for g in p.graphs:
        print(f"  graph  {g.title!r}: {len(g.blob or b'')} bytes")
    for w in p.warnings:
        print(f"  warning: {w}")
    return 0


def cmd_verify(a) -> int:
    from .formats.pcff.walker import parse, serialize
    data = _read(a.file)
    kind = sniff(data)
    failures = []
    if kind == "prism":
        from .formats.prism_reader import read_prism
        from .formats.prism_writer import save_project, table_grid, write_csv
        from .formats.zipio import ZipArchive
        arc = ZipArchive.from_bytes(data)
        if arc.to_bytes() != data:
            failures.append("ZIP container does not round-trip")
        for e in arc.entries:
            if e.name.endswith("data.bin"):
                b = e.read()
                if b[:8] == b"PCFFGRA4" and serialize(parse(b)) != b:
                    failures.append(f"graph blob {e.name} does not round-trip")
        p = read_prism(data, include_results=True)
        for t in p.tables:
            if write_csv(table_grid(t)) != arc.read(f"data/tables/{t.table_uid}/data.csv"):
                failures.append(f"table {t.title!r}: CSV does not rebuild identically")
        if save_project(data, read_prism(data))[0] != data:
            failures.append("saving without edits changes the file")
        failures += [f"reader: {w}" for w in p.warnings]
    elif kind == "pzfx":
        p = open_document(data)
        for g in p.graphs:
            if g.blob and g.blob[:8] == b"PCFFGRA4" and serialize(parse(g.blob)) != g.blob:
                failures.append("Template blob does not round-trip")
        failures += [f"reader: {w}" for w in p.warnings]
    else:
        failures.append(f"unsupported format: {kind}")
    print("OK" if not failures else "\n".join(f"FAIL {f}" for f in failures))
    return 1 if failures else 0


def _table_rows(t: DataTable) -> list[list[str]]:
    header, cols = [], []
    if t.row_titles is not None:
        header.append("")
        cols.append(t.row_titles.subcolumns[0])
    if t.x is not None:
        if t.x.generated is not None:
            header.append(t.x.title or "X")
            cols.append([repr(v) for v in t.x_values()])
        else:
            for s in t.x.subcolumns:
                header.append(t.x.title or "X")
                cols.append(s)
    for d in t.datasets:
        for s in d.subcolumns:
            header.append(d.title or "")
            cols.append(s)
    return [header] + [[c[r] if r < len(c) else "" for c in cols] for r in range(t.n_rows)]


def cmd_export(a) -> int:
    p = open_document(_read(a.file))
    os.makedirs(a.outdir, exist_ok=True)
    for k, t in enumerate(p.tables, 1):
        safe = "".join(ch if ch.isalnum() or ch in "-_ " else "_" for ch in t.title)[:60] or f"table{k}"
        path = os.path.join(a.outdir, f"{k:02d}_{safe}.csv")
        with open(path, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerows(_table_rows(t))
        print(path)
    if p.infos:
        path = os.path.join(a.outdir, "info.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump([{"title": i.title, "constants": i.constants, "notes": i.notes} for i in p.infos], f, indent=1, ensure_ascii=False)
        print(path)
    return 0


def cmd_diff(a) -> int:
    da, db = _read(a.a), _read(a.b)
    pa, pb = open_document(da), open_document(db)
    changed = False
    if sniff(da) == sniff(db) == "prism":
        from .formats.zipio import ZipArchive
        ea = {e.name: e for e in ZipArchive.from_bytes(da).entries}
        eb = {e.name: e for e in ZipArchive.from_bytes(db).entries}
        for n in sorted(set(ea) | set(eb)):
            if n not in eb:
                print(f"- {n}")
            elif n not in ea:
                print(f"+ {n}")
            elif ea[n].read() != eb[n].read():
                print(f"~ {n}")
            else:
                continue
            changed = True
    ta = {t.title: t for t in pa.tables}
    for t in pb.tables:
        o = ta.get(t.title)
        if o is None:
            print(f"table added: {t.title!r}")
            changed = True
            continue
        ra, rb = _table_rows(o), _table_rows(t)
        for r in range(max(len(ra), len(rb))):
            x = ra[r] if r < len(ra) else []
            y = rb[r] if r < len(rb) else []
            for c in range(max(len(x), len(y))):
                u = x[c] if c < len(x) else ""
                v = y[c] if c < len(y) else ""
                if u != v:
                    print(f"cell {t.title!r} r{r} c{c}: {u!r} -> {v!r}")
                    changed = True
    return 1 if changed else 0


def cmd_anonymize(a) -> int:
    data = _read(a.file)
    if sniff(data) != "prism":
        print("anonymize supports .prism bundles", file=sys.stderr)
        return 2
    from .formats import bundle as B
    from .formats.zipio import ZipArchive
    arc = ZipArchive.from_bytes(data)

    def doc(d):
        for k in ("createdBy", "modifiedBy"):
            if isinstance(d.get(k), dict):
                d[k]["user"] = ""
    B.edit_json(arc, "document.json", doc)
    personal = {"Experimenter", "Notebook ID", "Experiment ID", "Project"}
    for n in arc.names():
        if n.startswith("info/") and n.endswith("sheet.json"):
            def info(j):
                for c in j.get("constants", []):
                    if c.get("name") in personal:
                        c["value"] = ""
                j["notesText"] = ""
            B.edit_json(arc, n, info)
    arc.save(a.out)
    print(a.out)
    return 0


def cmd_gui(a) -> int:
    from .ui.app import main as gui

    return gui([a.file] if a.file else [])


def cmd_selftest(a) -> int:
    from .selftest import run

    return run(a.keep)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="refract", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    from . import about

    ap.add_argument("--version", action="version", version=f"{about.APP_NAME} {about.VERSION}")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("inspect"); s.add_argument("file"); s.set_defaults(fn=cmd_inspect)
    s = sub.add_parser("verify"); s.add_argument("file"); s.set_defaults(fn=cmd_verify)
    s = sub.add_parser("export"); s.add_argument("file"); s.add_argument("outdir"); s.set_defaults(fn=cmd_export)
    s = sub.add_parser("diff"); s.add_argument("a"); s.add_argument("b"); s.set_defaults(fn=cmd_diff)
    s = sub.add_parser("anonymize"); s.add_argument("file"); s.add_argument("out"); s.set_defaults(fn=cmd_anonymize)
    s = sub.add_parser("gui"); s.add_argument("file", nargs="?"); s.set_defaults(fn=cmd_gui)
    s = sub.add_parser("selftest"); s.add_argument("--keep"); s.set_defaults(fn=cmd_selftest)
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
