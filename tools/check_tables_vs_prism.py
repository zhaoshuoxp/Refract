"""Compare our readers' tables with Prism's own ExportTable output.

Usage: .venv/bin/python -I tools/check_tables_vs_prism.py <prism_auto out dir>

For each job dir (input.* plus data_<k>.csv written by Prism) the k-th table
we read is compared with data_<k>.csv: data-set titles against the header row,
then every cell. Prism exports *displayed* values, so a number matches when
it is within half a unit of the last digit Prism printed. Text must match
exactly (whitespace-trimmed).
"""

from __future__ import annotations

import csv
import glob
import json
import math
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from refract.formats import open_document
from refract.model.document import to_number

NUM = re.compile(r"^\s*([-+]?)(\d*)(?:\.(\d*))?(?:[eE]([-+]?\d+))?\s*$")


def tolerance(shown: str) -> float | None:
    m = NUM.match(shown)
    if not m or (not m.group(2) and not m.group(3)):
        return None
    decimals = len(m.group(3) or "")
    exp = int(m.group(4) or 0)
    return 0.5 * 10 ** (exp - decimals) * 1.000001


def expected_grid(t) -> tuple[list[str], list[list[str]]]:
    header, cols = [], []
    if t.row_titles is not None and any(c.strip() for c in t.row_titles.subcolumns[0]):
        header.append("")
        cols.append(t.row_titles.subcolumns[0])
    if t.x is not None:
        if t.x.generated is not None:
            cols.append([repr(v) for v in t.x_values()])
            header.append(t.x.title or "")
        else:
            for s in t.x.subcolumns:
                cols.append(s)
                header.append(t.x.title or "")
    for d in t.datasets:
        if not d.title and not any(c.strip() for sub in d.subcolumns for c in sub):
            continue  # Prism leaves untitled, empty data sets out of its export
        for s in d.subcolumns:
            cols.append(s)
            header.append(d.title or "")
    n = max((len(c) for c in cols), default=0)
    rows = [[(c[r] if r < len(c) else "") for c in cols] for r in range(n)]
    return header, rows


def formula_columns(t) -> set[int]:
    """Column indexes (in the export grid) of in-table formula data sets: Prism
    computes them on open, so the file has no values to compare."""
    cols, i = set(), 0
    if t.row_titles is not None and any(c.strip() for c in t.row_titles.subcolumns[0]):
        i += 1
    if t.x is not None:
        i += 1 if t.x.generated is not None else len(t.x.subcolumns)
    for d in t.datasets:
        if not d.title and not any(c.strip() for sub in d.subcolumns for c in sub):
            continue
        for _ in d.subcolumns:
            if d.formula is not None:
                cols.add(i)
            i += 1
    return cols


def compare(t, path: str) -> list[str]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        theirs = list(csv.reader(f))
    if not theirs:
        return ["Prism export empty"]
    header, ours = expected_grid(t)
    formula_cols = formula_columns(t)
    issues = []
    if not any(h.strip() for h in header):
        theirs = [[""] * len(header)] + theirs  # Prism writes no title row when every title is empty
    th = theirs[0]
    # title row: compare data-set titles (Prism may leave a leading cell empty)
    ours_titles = [h for h in header if h]
    their_titles = [h for h in th if h]
    norm = lambda xs: [x.strip().replace("\r", "\n") for x in xs]  # noqa: E731
    if norm(ours_titles) != norm(their_titles)[: len(ours_titles)] and ours_titles:
        issues.append(f"titles: ours {ours_titles[:6]} vs Prism {their_titles[:6]}")
    body = theirs[1:]
    width = len(header)
    for r in range(max(len(body), len(ours))):
        a = ours[r] if r < len(ours) else [""] * width
        b = (body[r] + [""] * width)[:width] if r < len(body) else [""] * width
        for c in range(width):
            x, y = a[c].strip().replace("\r", "\n"), b[c].strip().replace("\r", "\n")
            y_clean = y.rstrip("*").strip()  # excluded values carry an asterisk
            if x == y or x == y_clean or (x == "(Bad value)" and y_clean == "#N/A"):
                continue
            if not x and not y_clean:
                continue
            hms = re.fullmatch(r"(\d+):(\d\d):(\d\d(?:\.\d+)?)", y_clean)  # time-formatted display
            if hms and to_number(x) is not None:
                hours = int(hms.group(1)) + int(hms.group(2)) / 60 + float(hms.group(3)) / 3600
                if abs(to_number(x) - hours) < 1 / 3600:
                    continue
            if formula_cols and c in formula_cols:
                continue
            tol = tolerance(y_clean)
            xv = to_number(x)
            if tol is not None and xv is not None:
                yv = float(y_clean)
                if math.isclose(xv, yv, abs_tol=tol) or abs(xv - yv) <= tol + 1e-12 * abs(yv):
                    continue
            issues.append(f"r{r} c{c}: ours {x!r} vs Prism {y!r}")
            if len(issues) > 6:
                return issues
    return issues


def main(out: str) -> None:
    with open(os.path.join(out, "summary.json")) as fh:
        summary = json.load(fh)
    ok_tables = bad_tables = 0
    for job in summary["files"]:
        d = os.path.join(out, job["stem"])
        inp = next(iter(glob.glob(os.path.join(d, "input.*"))), None)
        if inp is None:
            continue
        p = open_document(inp)
        for k, t in enumerate(p.tables, 1):
            exp = os.path.join(d, f"data_{k}.csv")
            if not os.path.exists(exp):
                print(f"  -- {job['stem']} table {k} '{t.title}': no Prism export (job status {job['status']})")
                continue
            issues = compare(t, exp)
            if issues:
                bad_tables += 1
                print(f"  !! {job['stem']} table {k} '{t.title}' ({t.kind}/{t.data_format}):")
                for i in issues[:5]:
                    print(f"       {i}")
            else:
                ok_tables += 1
    print(f"tables matching Prism's export: {ok_tables}; mismatching: {bad_tables}")


if __name__ == "__main__":
    main(sys.argv[1])
