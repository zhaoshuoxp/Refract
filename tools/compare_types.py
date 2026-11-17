"""The same data drawn by both programs, every graph type at once.

1. Refract makes a project from its own sample tables (refract.model.templates)
   with one Refract graph per graph type (refract.render.graph_types) and
   saves it; on save each graph is also written as a Prism graph.
2. tools/prism_auto.py has Prism open the file and export every graph.
3. Each Prism picture is compared with Refract's own drawing of the same
   graph (tools/compare_graphs: SSIM and ink overlap, side-by-side pictures).

Types whose look Refract cannot write for Prism yet are written as Prism's
default graph of the table; the report marks them ("not written") so their
score is read as "how far Prism's default is", not as a rendering error.

  .venv/bin/python -I tools/compare_types.py corpus/auto/compare_types
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from compare_graphs import common, ink_iou, refract_picture, side_by_side, ssim
from PIL import Image

KIND_OF = {"xy": "xy", "column": "column", "grouped": "grouped", "contingency": "contingency",
           "survival": "survival", "parts_of_whole": "parts_of_whole", "nested": "nested",
           "multivariable": "multivariable"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--families", default="", help="comma-separated families (default: all)")
    ap.add_argument("--skip-prism", action="store_true", help="reuse the last Prism export")
    ap.add_argument("--all-plots", action="store_true",
                    help="also one graph per further plot choice (whiskers, error bars, ...) of the written types")
    ap.add_argument("--scheme", default="", help="colour every graph with a scheme: its name, or hex codes")
    ap.add_argument("--sheets", action="store_true", help="also contact sheets of the pairs, one per family")
    args = ap.parse_args()
    os.environ.setdefault("REFRACT_SETTINGS", os.path.join(args.out, "settings.ini"))
    from refract.model import templates as T
    from refract.render import graph_types as GT
    from refract.render import native, qt, schemes
    from refract.ui import schemes_dialog as SD
    from refract.ui.document import Document

    qt.ensure_app()
    colors = (SD.all_schemes().get(args.scheme) or schemes.parse_colors(args.scheme)) if args.scheme else []
    os.makedirs(os.path.join(args.out, "pairs"), exist_ok=True)
    fams = set(args.families.split(",")) if args.families else None
    path = os.path.join(args.out, "types.prism")
    d = Document.new()
    tables = {}
    for gt in GT.TYPES:
        if fams and gt.family not in fams:
            continue
        kind = KIND_OF[gt.family]
        if kind not in tables:
            tables[kind] = d.add_table(T.make(kind, f"{kind} sample", sample=True), with_graph=False)
        choices = [c for c, _ in gt.plots] or [None]
        if not (args.all_plots and gt.prism is not None):
            choices = choices[:1]
        for k, plot in enumerate(choices):
            ng = d.add_native_graph(tables[kind], title=gt.key if k == 0 else f"{gt.key}:{plot}", style=gt.key)
            if ng is not None and plot is not None:
                ng.error = plot
            if ng is not None and gt.family == "multivariable":  # bubble and scatter graphs: numbers on X
                ng.options = {"color": "Sex", "size": "Dose", "x": "Age" if key_xy(gt.key) else "Sex", "y": "Response",
                              "lines": "Dose"}
            if ng is not None and colors:
                try:
                    ng.format = schemes.apply(ng.format, native.graph(d.project, ng, d.results, d.source_of), colors)
                except Exception as e:  # noqa: BLE001 - a type that cannot draw its sample keeps its colours
                    print(f"{gt.key}: not coloured ({e})")
    d.save(path)
    written_notes = {r.split(":", 1)[0]: r for r in d.last_report}
    exports = os.path.join(args.out, "prism")
    if not args.skip_prism:
        subprocess.run([sys.executable, "-I", os.path.join(HERE, "prism_auto.py"), exports, path, "--no-resave",
                        "--timeout", "60"], check=True)
    export_dir = os.path.join(exports, "types")
    rows = []
    d = Document.open(path)  # the saved file: its graph sheets include the Prism copies, in Prism's order
    p = d.project
    for i, gs in enumerate(p.graphs):
        ng = next((n for n in p.native_graphs if n.prism_uid == gs.uid), None)
        png = os.path.join(export_dir, f"graph_{i + 1}.png")
        if ng is None or not os.path.exists(png):
            continue
        gt = GT.resolve(ng.table.kind, ng.style)
        row = {"type": ng.title, "label": gt.label if gt else "", "family": gt.family if gt else "",
               "written": gt is not None and (key_xy(gt.key) or GT.in_prism(gt, ng.table.kind) == "In Prism: the same graph"),
               "note": written_notes.get(ng.title, "")}
        try:
            ours = refract_picture(native.graph(p, ng, d.results, d.source_of), os.path.join(args.out, "_o.png"))
        except Exception as e:  # noqa: BLE001
            row["error"] = str(e)[:120]
            rows.append(row)
            continue
        prism = Image.open(png)
        x, y = common(prism, ours)
        row["ssim"], row["ink"] = round(ssim(x, y), 3), round(ink_iou(x, y), 3)
        side_by_side(prism, ours, os.path.join(args.out, "pairs", f"{ng.title.replace(':', '_')}.png"))
        rows.append(row)
    for ng in p.native_graphs:  # graphs not written for Prism at all (no Prism graph for that table kind)
        if ng.prism_uid and any(gs.uid == ng.prism_uid for gs in p.graphs):
            continue
        gt = GT.resolve(ng.table.kind, ng.style)
        row = {"type": ng.title, "label": gt.label if gt else "", "family": gt.family if gt else "",
               "written": False, "unwritten": True, "note": written_notes.get(ng.title, "")}
        try:
            ours = refract_picture(native.graph(p, ng, d.results, d.source_of), os.path.join(args.out, "_o.png"))
        except Exception as e:  # noqa: BLE001
            row["error"] = str(e)[:120]
            rows.append(row)
            continue
        blank = Image.new("RGB", ours.size, "white")
        from PIL import ImageDraw

        ImageDraw.Draw(blank).text((10, ours.height // 2), "not written for Prism", fill="#b35900")
        side_by_side(blank, ours, os.path.join(args.out, "pairs", f"{ng.title.replace(':', '_')}.png"))
        rows.append(row)
    with open(os.path.join(args.out, "scores.json"), "w") as f:
        json.dump(rows, f, indent=1)
    ok = [r for r in rows if "ink" in r]
    wr = [r for r in ok if r["written"]]
    lines = ["# The same sample data drawn by Prism and by Refract, every graph type", "",
             (f"{len(ok)} types compared; {len(wr)} are written for Prism as that type, the others as Prism's default "
             "graph of the table (their scores only say how far that default is)."), "",
             "| type | family | written for Prism | SSIM | ink overlap | picture |", "|---|---|---|---|---|---|"]
    for r in sorted(ok, key=lambda r: (not r["written"], r["ink"])):
        lines.append(f"| {r['type']} ({r['label']}) | {r['family']} | {'yes' if r['written'] else 'no'} | "
                     f"{r['ssim']} | {r['ink']} | pairs/{r['type'].replace(':', '_')}.png |")
    with open(os.path.join(args.out, "report.md"), "w") as f:
        f.write("\n".join(lines) + "\n")
    import statistics

    if args.sheets:
        sheets(rows, gt_order=[t.key for t in GT.TYPES], out=args.out,
               title=f"colours: {args.scheme}" if args.scheme else "default colours")

    if wr:
        print(f"{len(ok)} compared; written types: median ink {statistics.median(r['ink'] for r in wr):.3f}, "
              f"median SSIM {statistics.median(r['ssim'] for r in wr):.3f} ({len(wr)} types)")


def key_xy(key: str) -> bool:
    return key in ("mv_bubble", "mv_scatter")


def sheets(rows: list[dict], gt_order: list[str], out: str, title: str) -> list[str]:
    """One picture per family: every pair (Prism left, Refract right) with its
    type, whether it is written for Prism as that type, and its scores."""
    from PIL import ImageDraw

    os.makedirs(os.path.join(out, "sheets"), exist_ok=True)
    order = {k: i for i, k in enumerate(gt_order)}
    by_family: dict[str, list[dict]] = {}
    for r in rows:
        by_family.setdefault(r["family"] or "other", []).append(r)
    written = []
    W, H, cols, head = 640, 320, 3, 34
    for fam, rs in by_family.items():
        rs.sort(key=lambda r: (order.get(r["type"].split(":")[0], 999), r["type"]))
        n = len(rs)
        sheet = Image.new("RGB", (cols * W, head + ((n + cols - 1) // cols) * H), "white")
        dr = ImageDraw.Draw(sheet)
        dr.text((8, 8), f"{fam}: Prism (left) and Refract (right), the same sample data, {title}", fill="black")
        for i, r in enumerate(rs):
            x, y = (i % cols) * W, head + (i // cols) * H
            tag = "written for Prism" if r["written"] else "no Prism graph for this table kind yet" \
                if r.get("unwritten") else "Prism shows its default graph"
            score = f"ink {r['ink']:.2f}  SSIM {r['ssim']:.2f}" if "ink" in r else r.get("error", "")
            dr.rectangle((x + 2, y + 2, x + W - 3, y + H - 3), outline="#bbbbbb")
            dr.text((x + 8, y + 6), f"{r['type']}  {r['label']}"[:90], fill="black")
            dr.text((x + 8, y + 20), f"{tag}   {score}", fill="#1a7f37" if r["written"] else "#b35900")
            if r.get("note"):  # what the save reported for this graph
                dr.text((x + 8, y + 34), r["note"].split(": ", 1)[-1][:105], fill="#666666")
            pair = os.path.join(out, "pairs", f"{r['type'].replace(':', '_')}.png")
            if os.path.exists(pair):
                im = Image.open(pair).convert("RGB")
                im.thumbnail((W - 16, H - 58))
                sheet.paste(im, (x + 8, y + 52))
        path = os.path.join(out, "sheets", f"{fam}.png")
        sheet.save(path)
        written.append(path)
    return written


if __name__ == "__main__":
    main()
