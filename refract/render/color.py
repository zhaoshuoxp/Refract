"""Prism's stored colours -> sRGB.

Prism (macOS) stores graph colours in Apple's Generic RGB (gamma 1.8) and
exports them converted to sRGB. Converting through the system's Generic RGB
and sRGB profiles matches Prism's PDFs to +/-1 level (7 colours); this fitted
model (gamma 1.8011 and a 3x3 matrix, max error 0.85 / 255 on 9 colours from
the grouped-bar seed and default grouped graphs) needs no profile files, so it also runs
off macOS. Verified on: (124,160,212)->(142,177,220), (40,82,145)->(50,102,162),
(160,160,164)->(176,176,179), ...
"""

from __future__ import annotations

GAMMA = 1.8011
MATRIX = ((1.0319, -0.0176, -0.0065),
          (0.0233, 0.9507, 0.0282),
          (-0.0060, 0.0066, 0.9986))


def _enc(v: float) -> float:
    v = min(max(v, 0.0), 1.0)
    return 12.92 * v if v <= 0.0031308 else 1.055 * v ** (1 / 2.4) - 0.055


def to_srgb(rgba: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    lin = [(c / 255) ** GAMMA for c in rgba[:3]]
    out = [round(255 * _enc(sum(m * x for m, x in zip(row, lin, strict=True)))) for row in MATRIX]
    return out[0], out[1], out[2], rgba[3]


def _dec(v: float) -> float:
    v = min(max(v, 0.0), 1.0)
    return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4


def _inverse(m):
    (a, b, c), (d, e, f), (g, h, i) = m
    det = a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)
    return (((e * i - f * h) / det, (c * h - b * i) / det, (b * f - c * e) / det),
            ((f * g - d * i) / det, (a * i - c * g) / det, (c * d - a * f) / det),
            ((d * h - e * g) / det, (b * g - a * h) / det, (a * e - b * d) / det))


INVERSE = _inverse(MATRIX)


def from_srgb(rgba: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    """sRGB -> the Generic RGB Prism stores (the inverse of to_srgb)."""
    lin = [_dec(c / 255) for c in rgba[:3]]
    gen = [min(max(sum(m * x for m, x in zip(row, lin, strict=True)), 0.0), 1.0) for row in INVERSE]
    out = [round(255 * v ** (1 / GAMMA)) for v in gen]
    return out[0], out[1], out[2], rgba[3]
