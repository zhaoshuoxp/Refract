"""Structural similarity (SSIM, Wang et al. 2004) between two images, for
comparing our renders with Prism's exports. Grey levels, Gaussian window
sigma 1.5, K1 0.01, K2 0.03, as in the paper.

Usage: .venv/bin/python -I tools/image_compare.py a.png|a.pdf b.png|b.pdf [--size W H]
PDFs are rasterised with pdfium at 300 dpi; images of different sizes are
compared on their common top-left region (layouts anchor there).
"""

from __future__ import annotations

import argparse

import numpy as np
from scipy.ndimage import gaussian_filter


def load_grey(path: str, size: tuple[int, int] | None = None) -> np.ndarray:
    from PIL import Image

    im = Image.open(path).convert("RGBA")
    bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
    im = Image.alpha_composite(bg, im).convert("L")
    if size is not None and im.size != size:
        im = im.resize(size, Image.LANCZOS)
    return np.asarray(im, dtype=float)


def pdf_grey(path: str, dpi: float = 300) -> np.ndarray:
    import pypdfium2 as pdfium

    page = pdfium.PdfDocument(path)[0]
    im = page.render(scale=dpi / 72).to_pil().convert("L")
    return np.asarray(im, dtype=float)


def load_any(path: str) -> np.ndarray:
    return pdf_grey(path) if path.lower().endswith(".pdf") else load_grey(path)


def ssim_aligned(a: np.ndarray, b: np.ndarray) -> float:
    """SSIM over the common top-left region; the uncovered remainder of the
    larger image counts as mismatched in proportion to its area."""
    h, w = min(a.shape[0], b.shape[0]), min(a.shape[1], b.shape[1])
    core = ssim(a[:h, :w], b[:h, :w])
    area = max(a.shape[0] * a.shape[1], b.shape[0] * b.shape[1])
    return core * (h * w) / area


def ssim(a: np.ndarray, b: np.ndarray, data_range: float = 255.0, sigma: float = 1.5) -> float:
    if a.shape != b.shape:
        raise ValueError(f"shapes differ: {a.shape} vs {b.shape}")
    c1, c2 = (0.01 * data_range) ** 2, (0.03 * data_range) ** 2
    mu_a, mu_b = gaussian_filter(a, sigma), gaussian_filter(b, sigma)
    saa = gaussian_filter(a * a, sigma) - mu_a ** 2
    sbb = gaussian_filter(b * b, sigma) - mu_b ** 2
    sab = gaussian_filter(a * b, sigma) - mu_a * mu_b
    m = ((2 * mu_a * mu_b + c1) * (2 * sab + c2)) / ((mu_a ** 2 + mu_b ** 2 + c1) * (saa + sbb + c2))
    return float(m.mean())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("a")
    ap.add_argument("b")
    ap.add_argument("--size", nargs=2, type=int)
    a = ap.parse_args()
    if a.size:
        size = tuple(a.size)
        print(f"{ssim(load_grey(a.a, size), load_grey(a.b, size)):.4f}")
    else:
        print(f"{ssim_aligned(load_any(a.a), load_any(a.b)):.4f}")


if __name__ == "__main__":
    main()
