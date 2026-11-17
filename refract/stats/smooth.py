"""Smooth, differentiate or integrate a curve (SMOOTH_CURVE), as Prism 11.1
computes it (E-stats8, Prism's own results on even and uneven X):

  * CURVE: Savitzky-Golay smoothing over neighborCount points each side,
    by row (X spacing ignored), the window padded with the end values; the
    curve is smoothed whatever smoothing.enabled says;
  * FIRST_DERIVATIVE / SECOND_DERIVATIVE: differences between neighbours at
    their midpoints (twice), then smoothed when smoothing is enabled;
  * INTEGRAL: the trapezoidal running area from integralY0, then smoothed.

Smoothing polynomials of order 0 and 2 are reproduced; Prism's order 4 and
6 are not yet (they differ from the Savitzky-Golay ones)."""

from __future__ import annotations

import math

import numpy as np
from scipy.integrate import cumulative_trapezoid
from scipy.signal import savgol_filter

ORDERS = {0, 1, 2, 3}  # Savitzky-Golay orders that give Prism's values (odd ones equal the even below)


def _smooth(y: np.ndarray, k: int, order: int) -> np.ndarray:
    if order not in ORDERS:
        raise NotImplementedError(f"smoothing with a polynomial of order {order}")
    if len(y) == 0:
        return y.copy()
    w = 2 * k + 1  # also wider than the data: the end values pad it (as Prism)
    return savgol_filter(y, w, min(order, w - 1), mode="nearest")


def smooth_curve(params: dict, x: list, columns: list, titles: list[str]) -> dict:
    calc = params.get("calc", {})
    kind = calc.get("type", "CURVE")
    sm = calc.get("smoothing", {}) or {}
    k, order = int(sm.get("neighborCount", 4)), int(sm.get("polynomialOrder", 2))
    smooth = kind == "CURVE" or bool(sm.get("enabled", True))
    cols, warn = [], []
    for col in columns:
        pts = [(float(a), float(b)) for a, b in zip(x or [], col, strict=False)
               if a is not None and b is not None and math.isfinite(a) and math.isfinite(b)]
        xs = np.array([p[0] for p in pts])
        ys = np.array([p[1] for p in pts])
        if smooth and len(xs) > 2 and not np.allclose(np.diff(xs), np.diff(xs)[0]) and "NON_EQUAL_SPACING" not in warn:
            warn.append("NON_EQUAL_SPACING")
        if kind == "CURVE":
            vx, vy = xs, _smooth(ys, k, order)
        elif kind in ("FIRST_DERIVATIVE", "SECOND_DERIVATIVE"):
            vx, vy = xs, ys
            for _ in range(1 if kind == "FIRST_DERIVATIVE" else 2):
                vy = np.diff(vy) / np.diff(vx)
                vx = (vx[1:] + vx[:-1]) / 2
            if smooth:
                vy = _smooth(vy, k, order)
        elif kind == "INTEGRAL":
            vx = xs
            vy = float(calc.get("integralY0", 0.0)) + cumulative_trapezoid(ys, xs, initial=0)
            if smooth:
                vy = _smooth(vy, k, order)
        else:
            raise NotImplementedError(f"smooth type {kind}")
        cols.append(([float(v) for v in vx], [float(v) for v in vy]))
    # Prism's table: the data sets one below the other, each in its own column (E-stats8)
    rows = [[xv, *(yv if j == jj else None for jj in range(len(cols)))]
            for j, (cx, cy) in enumerate(cols) for xv, yv in zip(cx, cy, strict=True)]
    return {"status": {"error": "VALID", "warning": warn},
            "_tables": {"X Y coordinates": {"columns": ["X", *titles], "rows": rows, "row_titles": None}}}
