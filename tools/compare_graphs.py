"""Compare Refract's drawing of graphs with Prism's own, automatically.

For every graph of the projects that tools/prism_auto.py exported (each
<dir>/<stem>/resaved.prism with graph_<n>.png), Refract draws the same graph
from the same file (refract.render.from_prism) and the two pictures are
compared:

  * both are cropped to their ink (non-white) and scaled to a common size;
  * SSIM (structural similarity, 7 px windows, on grey levels) and the
    overlap of their ink (IoU of the dark pixels, slightly dilated) are
    computed.

With --as-type, Refract also draws each graph's table as the graph type
that corresponds to Prism's plot style (refract.render.graph_types), to
compare its own graph types with Prism's on the same data.

Writes <out>/report.md (graphs by score, worst first) and a side-by-side
picture per graph (<out>/pairs/<stem>_<n>.png: Prism left, Refract right).

  .venv/bin/python -I tools/compare_graphs.py corpus/auto/compare_samples corpus/auto/compare_report
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PIL import Image

SIZE = 360  # the common size (longer side) the two pictures are compared at


def ink_crop(img: Image.Image) -> Image.Image:
    g = np.asarray(img.convert("L"), dtype=np.float32)
    ys, xs = np.nonzero(g < 235)
    if len(xs) == 0:
        return img.convert("L")
    return img.convert("L").crop((int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1))


def common(a: Image.Image, b: Image.Image) -> tuple[np.ndarray, np.ndarray]:
    """Both cropped to their ink, each scaled into the same box (aspect kept, padded white)."""
    out = []
    for im in (ink_crop(a), ink_crop(b)):
        k = SIZE / max(im.width, im.height)
        im = im.resize((max(1, round(im.width * k)), max(1, round(im.height * k))), Image.LANCZOS)
        canvas = Image.new("L", (SIZE, SIZE), 255)
        canvas.paste(im, ((SIZE - im.width) // 2, (SIZE - im.height) // 2))
        out.append(np.asarray(canvas, dtype=np.float64))
    return out[0], out[1]


def ssim(x: np.ndarray, y: np.ndarray, win: int = 7) -> float:
    from scipy.ndimage import uniform_filter

    c1, c2 = (0.01 * 255) ** 2, (0.03 * 255) ** 2
    mx, my = uniform_filter(x, win), uniform_filter(y, win)
    sxx = uniform_filter(x * x, win) - mx * mx
    syy = uniform_filter(y * y, win) - my * my
    sxy = uniform_filter(x * y, win) - mx * my
    m = ((2 * mx * my + c1) * (2 * sxy + c2)) / ((mx * mx + my * my + c1) * (sxx + syy + c2))
    return float(m.mean())


def ink_iou(x: np.ndarray, y: np.ndarray) -> float:
    from scipy.ndimage import binary_dilation

    a, b = x < 160, y < 160
    a2, b2 = binary_dilation(a, iterations=2), binary_dilation(b, iterations=2)
    inter = (a & b2).sum() + (b & a2).sum()
    return float(inter / max(1, a.sum() + b.sum()))


def side_by_side(a: Image.Image, b: Image.Image, path: str) -> None:
    h = 300
    ims = []
    for im in (a, b):
        im = im.convert("RGB")
        ims.append(im.resize((max(1, round(im.width * h / im.height)), h), Image.LANCZOS))
    c = Image.new("RGB", (ims[0].width + ims[1].width + 16, h), "white")
    c.paste(ims[0], (0, 0))
    c.paste(ims[1], (ims[0].width + 16, 0))
    c.save(path)


def refract_picture(g, path: str) -> Image.Image:
    from refract.render import qt

    qt.to_png(g, path, dpi=150)
    return Image.open(path)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("exports")
    ap.add_argument("out")
    ap.add_argument("--as-type", action="store_true", help="also draw each table as the matching Refract graph type")
    args = ap.parse_args()
    from refract.formats import open_document
    from refract.formats.pcff import walker
    from refract.formats.zipio import ZipArchive
    from refract.render import from_prism, qt
    from refract.render import graph_types as GT

    qt.ensure_app()
    os.makedirs(os.path.join(args.out, "pairs"), exist_ok=True)
    rows = []
    for d in sorted(glob.glob(os.path.join(args.exports, "*"))):
        src = os.path.join(d, "resaved.prism")
        if not os.path.exists(src):
            continue
        stem = os.path.basename(d)
        try:
            p = open_document(src)
            arc = ZipArchive.open(src)
        except Exception as e:  # noqa: BLE001
            rows.append({"stem": stem, "graph": 0, "error": f"open: {e}"})
            continue
        for i, gs in enumerate(p.graphs):
            png = os.path.join(d, f"graph_{i + 1}.png")
            if not os.path.exists(png):
                continue
            row = {"stem": stem, "graph": i + 1, "title": gs.title}
            try:
                plots = from_prism.plot_settings(walker.parse(gs.blob)) if gs.blob else []
                row["styles"] = sorted({ps["style"] for ps in plots})
            except Exception:  # noqa: BLE001
                row["styles"] = []
            prism = Image.open(png)
            try:
                g = from_prism.graph(p, i, arc)
                ours = refract_picture(g, os.path.join(args.out, "_ours.png"))
            except Exception as e:  # noqa: BLE001
                row["error"] = f"{type(e).__name__}: {e}"[:160]
                rows.append(row)
                continue
            x, y = common(prism, ours)
            row["ssim"], row["ink"] = round(ssim(x, y), 3), round(ink_iou(x, y), 3)
            row["family"] = g.family
            pair = os.path.join(args.out, "pairs", f"{stem}_{i + 1}.png")
            side_by_side(prism, ours, pair)
            row["pair"] = os.path.relpath(pair, args.out)
            if args.as_type:
                gt = style_type(g, row["styles"])
                tables = from_prism.source_tables(p, i, arc)
                if gt is not None and tables:
                    try:
                        g2 = GT.make(tables[0], gt, gt.plots[0][0] if gt.plots else None, gs.title)
                        ours2 = refract_picture(g2, os.path.join(args.out, "_ours2.png"))
                        x2, y2 = common(prism, ours2)
                        row["type"], row["type_ssim"] = gt.key, round(ssim(x2, y2), 3)
                        side_by_side(prism, ours2, os.path.join(args.out, "pairs", f"{stem}_{i + 1}_type.png"))
                    except Exception as e:  # noqa: BLE001
                        row["type_error"] = f"{type(e).__name__}: {e}"[:120]
            rows.append(row)
    with open(os.path.join(args.out, "scores.json"), "w") as f:
        json.dump(rows, f, indent=1)
    ok = [r for r in rows if "ssim" in r]
    lines = ["# Refract vs Prism: the same graphs from the same files", "",
             (f"{len(ok)} graphs compared, {len(rows) - len(ok)} not drawn. SSIM 1 = identical; ink = overlap of the "
             "dark pixels (1 = same strokes)."), "",
             f"Median SSIM {np.median([r['ssim'] for r in ok]):.3f}, median ink overlap "
             f"{np.median([r['ink'] for r in ok]):.3f}." if ok else "", "",
             "| file | graph | family | Prism styles | SSIM | ink | picture |", "|---|---|---|---|---|---|---|"]
    for r in sorted(ok, key=lambda r: r["ink"]):
        lines.append(f"| {r['stem']} | {r['graph']} {r.get('title', '')[:30]} | {r['family']} | {r['styles']} | "
                     f"{r['ssim']} | {r['ink']} | {r['pair']} |")
    bad = [r for r in rows if "ssim" not in r]
    if bad:
        lines += ["", "## Not drawn", ""] + [f"- {r['stem']} graph {r['graph']}: {r.get('error')}" for r in bad]
    with open(os.path.join(args.out, "report.md"), "w") as f:
        f.write("\n".join(lines) + "\n")
    print(f"{len(ok)} compared, median SSIM {np.median([r['ssim'] for r in ok]) if ok else 0:.3f}, "
          f"median ink {np.median([r['ink'] for r in ok]) if ok else 0:.3f}; {len(bad)} not drawn")


def style_type(g, styles: list[int]):
    """The Refract graph type closest to a Prism graph (its family and plot styles)."""
    from refract.render import graph_types as GT

    key = {"column": "col_scatter", "grouped": "grp_bars_points", "xy": "xy_points", "survival": "surv_ticks",
           "pie": "pie"}.get(g.family)
    return GT.BY_KEY.get(key) if key else None


if __name__ == "__main__":
    main()
