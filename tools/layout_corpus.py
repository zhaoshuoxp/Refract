"""Prism layouts drawn by Refract (refract.render.prism_layout) against the
PDFs Prism exported of them (tools/prism_auto.py: layout_<i>.pdf).

Usage: .venv/bin/python tools/layout_corpus.py <prism_auto out dir> <file.prism> [...]
(the files in the order they were given to prism_auto). Both pages are
rasterised at 144 dpi and cropped to their content; ours is resized to
Prism's crop and compared with SSIM (tools/image_compare.py).
"""

from __future__ import annotations

import os
import statistics
import sys

import numpy as np

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from image_compare import ssim

DPI = 144


def _crop(a: np.ndarray) -> np.ndarray:
    ys, xs = np.nonzero(a < 245)
    if len(xs) == 0:
        return a
    return a[ys.min():ys.max() + 1, xs.min():xs.max() + 1]


def main() -> int:
    import pypdfium2 as pdfium
    from PIL import Image

    from refract.formats import open_document
    from refract.formats.zipio import ZipArchive
    from refract.render import page as PG
    from refract.render import prism_layout as PL
    from refract.render import qt

    qt.ensure_app()
    out, files = sys.argv[1], sys.argv[2:]
    scores, ratios, rows = [], [], []
    for n, f in enumerate(files, 1):
        d = os.path.join(out, "resaved" if n == 1 else f"resaved_{n}")
        p = open_document(f)
        arc = ZipArchive.open(f)
        for li, lay in enumerate(p.layouts):
            pdf = os.path.join(d, f"layout_{li + 1}.pdf")
            if not os.path.exists(pdf):
                rows.append((f, li, "no Prism export"))
                continue
            for obj in PL.placed(lay.blob):
                if obj.own and obj.own[0] > 0 and obj.own[1] > 0:
                    x0, y0, x1, y1 = obj.frame
                    ratios.append(((x1 - x0) / obj.own[0]) / ((y1 - y0) / obj.own[1]))
            try:
                pg = PL.page(p, li, arc)
            except NotImplementedError as e:
                rows.append((f, li, f"not drawn: {e}"))
                continue
            tmp = os.path.join(d, f"refract_layout_{li + 1}.png")
            PG.to_image(pg, DPI / 72).save(tmp)
            ours = np.asarray(Image.open(tmp).convert("L"), dtype=float)
            theirs = np.asarray(pdfium.PdfDocument(pdf)[0].render(scale=DPI / 72).to_pil().convert("L"), dtype=float)
            a, b = _crop(ours), _crop(theirs)
            a = np.asarray(Image.fromarray(a.astype("uint8")).resize((b.shape[1], b.shape[0]), Image.LANCZOS), float)
            s = ssim(a, b)
            scores.append(s)
            rows.append((os.path.basename(os.path.dirname(f)), li, f"SSIM {s:.3f}  graphs {len(pg.items)}"
                         f"  size ours {a.shape[1]}x{a.shape[0]} vs {b.shape[1]}x{b.shape[0]}"
                         + (f"  not drawn: {len(pg.notes)}" if pg.notes else "")))
    for r in rows:
        print(*r)
    if scores:
        print(f"\n{len(scores)} layouts drawn: median SSIM {statistics.median(scores):.3f}, "
              f"min {min(scores):.3f}, max {max(scores):.3f}")
    if ratios:
        dev = [abs(r - 1) for r in ratios]
        print(f"frame/own scale, x over y: {len(ratios)} objects, median deviation {statistics.median(dev):.3f}, "
              f"max {max(dev):.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
