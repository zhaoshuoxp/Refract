"""Compare Prism-printed PDFs of probe files against the baseline.

Usage: .venv/bin/python -I tools/compare_pdfs.py <pdf_dir> [baseline_stem]

For each PDF: is it vector (text extractable, few/no embedded images)? What
text does it contain? How many pixels differ from the baseline rendering, and
where? It also writes <stem>.png renders and <stem>_diff.png overlays next to
the PDFs.
"""

from __future__ import annotations

import os
import sys

import numpy as np
import pypdfium2 as pdfium
from PIL import Image

DPI = 150


def render(path: str) -> tuple[np.ndarray, str, int, int]:
    pdf = pdfium.PdfDocument(path)
    page = pdf[0]
    img = page.render(scale=DPI / 72).to_pil().convert("L")
    text = page.get_textpage().get_text_range()
    n_images = sum(1 for obj in page.get_objects() if obj.type == pdfium.raw.FPDF_PAGEOBJ_IMAGE)
    return np.asarray(img), text, n_images, len(pdf)


def main(pdf_dir: str, baseline: str = "E7-00_baseline") -> None:
    files = sorted(f for f in os.listdir(pdf_dir) if f.lower().endswith(".pdf"))
    if not files:
        print("no PDFs found in", pdf_dir)
        return
    base_path = os.path.join(pdf_dir, baseline + ".pdf")
    base = render(base_path)[0] if os.path.exists(base_path) else None
    for f in files:
        stem = f[:-4]
        arr, text, n_img, n_pages = render(os.path.join(pdf_dir, f))
        Image.fromarray(arr).save(os.path.join(pdf_dir, stem + ".png"))
        words = " ".join(text.split())
        line = f"{stem:28s} pages={n_pages} images={n_img} text_chars={len(text):4d}"
        if base is not None and stem != baseline:
            if arr.shape != base.shape:
                line += f"  size differs {arr.shape} vs {base.shape}"
            else:
                d = np.abs(arr.astype(int) - base.astype(int)) > 40
                frac = d.mean()
                line += f"  diff_pixels={frac:.4%}"
                if d.any():
                    ys, xs = np.nonzero(d)
                    line += f" bbox(px)=({xs.min()},{ys.min()})-({xs.max()},{ys.max()})"
                    ov = np.stack([base, base, base], -1).copy()
                    ov[d] = [255, 0, 0]
                    Image.fromarray(ov.astype(np.uint8)).save(os.path.join(pdf_dir, stem + "_diff.png"))
        print(line)
        print("   text:", words[:300])


if __name__ == "__main__":
    main(*sys.argv[1:])
