"""One PDF report of tools/compare_types.py runs: every graph type drawn by
Prism and by Refract from the same sample data, with and without a colour
scheme.

  .venv/bin/python -I tools/compare_report.py <out.pdf> <run_dir> [<run_dir with a scheme> <its scheme>]

Each run directory is a compare_types.py output (scores.json, pairs/,
sheets/). The report: a summary (types written for Prism as that type, the
median scores per family, why the others are not), a table of every type,
then every pair, one per family, Prism left and Refract right.
"""

from __future__ import annotations

import html
import json
import os
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

FAMILIES = ["column", "xy", "grouped", "contingency", "survival", "parts_of_whole", "nested", "multivariable"]
# why a type is not written for Prism as that type (E-types, E-mv)
WHY = {
    "grp_heat": "written as a heat map in Prism's default viridis colours (Prism's colour-map field is not known yet)",
    "grp3": "no reference graph of Prism's three-way graphs yet",
    "cont_percent": "Prism has no such graph (its Create New Graph window)",
    "surv_plain": "Prism has no such graph (staircases always show their censor ticks)",
    "surv_inverted_plain": "Prism has no such graph (staircases always show their censor ticks)",
    "waffle": "Prism has no such graph",
    "col_before_after_bars": "the reference came out as Prism's plain before-after graph",
    "grp_floating_sep": "no reference graph",
    "nest_bars": "no reference graph",
    "mv_": "Prism's Multiple-variables graphs other than bubble and scatter need a licence the trial lacks",
}


def why(key: str) -> str:
    return next((v for k, v in WHY.items() if key == k or key.startswith(k)), "")


def _rows(run: str) -> list[dict]:
    with open(os.path.join(run, "scores.json")) as f:
        return json.load(f)


def _median(rows: list[dict], k: str) -> str:
    v = [r[k] for r in rows if k in r]
    return f"{statistics.median(v):.3f}" if v else "-"


def build(out: str, run: str, scheme_run: str | None = None, scheme: str = "") -> str:
    rows = _rows(run)
    srows = {r["type"]: r for r in _rows(scheme_run)} if scheme_run else {}
    written = [r for r in rows if r["written"] and "ink" in r]
    other = [r for r in rows if not r["written"]]
    h = ["<html><body style='font-family: Arial; font-size: 9pt'>",
         "<h1>Refract and Prism: every graph type from the same data</h1>",
         ("<p>Refract makes one graph of each type from its own sample tables and saves the project as a "
         "<i>.prism</i> file; Prism opens that file and exports every graph; each Prism picture is compared with "
         "Refract's own drawing of the same graph. <b>Ink overlap</b>: the share of inked pixels the two pictures "
         "have in common (1 = the same marks). <b>SSIM</b>: structural similarity (1 = identical).</p>"),
         (f"<p><b>{len(rows)}</b> graph types; <b>{len(written)}</b> are written for Prism as that same graph: "
         f"median ink overlap <b>{_median(written, 'ink')}</b>, median SSIM <b>{_median(written, 'ssim')}</b>")]
    if srows:
        sw = [srows[r["type"]] for r in written if r["type"] in srows and "ink" in srows[r["type"]]]
        h.append(f"; with the colour scheme {html.escape(scheme)}: median ink overlap <b>{_median(sw, 'ink')}</b>, "
                 f"median SSIM <b>{_median(sw, 'ssim')}</b>")
    h.append(".</p>")
    # per family
    h.append("<h2>By family</h2><table border='1' cellspacing='0' cellpadding='3'>"
             "<tr><th>family</th><th>types</th><th>written as that graph</th><th>median ink</th>"
             "<th>median SSIM</th></tr>")
    for fam in FAMILIES:
        fr = [r for r in rows if r["family"] == fam]
        fw = [r for r in fr if r["written"] and "ink" in r]
        h.append(f"<tr><td>{fam}</td><td>{len(fr)}</td><td>{len(fw)}</td><td>{_median(fw, 'ink')}</td>"
                 f"<td>{_median(fw, 'ssim')}</td></tr>")
    h.append("</table>")
    # not written
    h.append(f"<h2>Not written for Prism as that graph ({len(other)})</h2>"
             "<p>Refract draws and keeps these; in the .prism file Prism shows its default graph of the table, or "
             "none for a Multiple-variables table.</p><table border='1' cellspacing='0' cellpadding='3'>"
             "<tr><th>type</th><th>why</th></tr>")
    for r in other:
        h.append(f"<tr><td>{html.escape(r['type'])} ({html.escape(r['label'])})</td>"
                 f"<td>{html.escape(why(r['type']))}</td></tr>")
    h.append("</table>")
    # every type
    h.append("<h2>Every type</h2><table border='1' cellspacing='0' cellpadding='3'>"
             "<tr><th>type</th><th>family</th><th>written</th><th>ink</th><th>SSIM</th>"
             + ("<th>ink (scheme)</th><th>SSIM (scheme)</th>" if srows else "") + "</tr>")
    order = {f: i for i, f in enumerate(FAMILIES)}
    for r in sorted(rows, key=lambda r: (order.get(r["family"], 99), not r["written"], -r.get("ink", 0))):
        s = srows.get(r["type"], {})
        cells = [f"{html.escape(r['type'])}<br/><span style='color:#555'>{html.escape(r['label'])}</span>",
                 r["family"], "yes" if r["written"] else "no",
                 f"{r['ink']:.3f}" if "ink" in r else "-", f"{r['ssim']:.3f}" if "ssim" in r else "-"]
        if srows:
            cells += [f"{s['ink']:.3f}" if "ink" in s else "-", f"{s['ssim']:.3f}" if "ssim" in s else "-"]
        h.append("<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>")
    h.append("</table>")
    # the pictures
    for label, d in (("default colours", run), (f"colour scheme {scheme}", scheme_run)):
        if not d:
            continue
        for fam in FAMILIES:
            p = os.path.join(d, "sheets", f"{fam}.png")
            if os.path.exists(p):
                h.append(f"<h2 style='page-break-before: always'>{fam}: Prism (left), Refract (right), "
                         f"{html.escape(label)}</h2><img src='{os.path.abspath(p)}' width='700'/>")
    h.append("</body></html>")
    return _pdf("\n".join(h), out)


def _pdf(text: str, out: str) -> str:
    from PySide6.QtCore import QMarginsF, QSizeF
    from PySide6.QtGui import QPageLayout, QPageSize, QPdfWriter, QTextDocument

    from refract.render import qt

    qt.ensure_app()
    w = QPdfWriter(out)
    w.setResolution(150)
    w.setPageLayout(QPageLayout(QPageSize(QPageSize.A4), QPageLayout.Portrait, QMarginsF(12, 12, 12, 12),
                                QPageLayout.Millimeter))
    doc = QTextDocument()
    doc.setHtml(text)
    doc.setPageSize(QSizeF(w.width(), w.height()))
    doc.print_(w)
    return out


if __name__ == "__main__":
    a = sys.argv[1:]
    print(build(a[0], a[1], a[2] if len(a) > 2 else None, a[3] if len(a) > 3 else ""))
