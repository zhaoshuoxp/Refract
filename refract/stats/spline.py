"""Fit spline / LOWESS (Prism: FIT_SPLINE_LOWESS): a curve through or among
the points of each data set, as Prism 11.1 draws it (E-stats8c).

  * CUBIC_SPLINE: the natural cubic spline through the points.
  * AKIMA_SPLINE: Akima's spline through the points.
  * LOWESS: at each data X, a weighted straight-line fit (tricube weights,
    no robustness steps) over a window of half-width a fraction of the X
    range (FINE 1/20, MEDIUM 1/10, COARSE 1/5); the curve joins those
    values with straight lines. With very few points, the cubic spline.
  * The curve: calc.curve.segmentCount points (Prism sets 4 per data row)
    from the smallest to the largest X of the table, one X series; each data
    set's curve only over its own X range.
  * SMOOTHING_SPLINE: a natural cubic regression spline (least squares)
    with calc.curve.knotCount knots: 2 a straight line; 3 to 7 at Harrell's
    percentiles of the X values (as Hmisc's rcspline: 3 at 10/50/90 %, ...),
    8 or more at evenly spaced percentiles from the smallest to the largest
    X; a percentile p is the value at rank p (n + 1) (interpolated, clamped).
    No curve (Prism) with more knots than points, or (8 knots or more) as
    many. Verified, 38 curves.

POINT_TO_POINT is not reproduced yet.
"""

from __future__ import annotations

import math

import numpy as np
from scipy import interpolate

WINDOW = {"FINE": 1 / 20, "MEDIUM": 1 / 10, "COARSE": 1 / 5}


def _points(x, col) -> tuple[np.ndarray, np.ndarray]:
    """The points of a data set (replicates averaged; equal X averaged), in X order."""
    subs = col if col and isinstance(col[0], (list, tuple)) else [col]
    by: dict[float, list[float]] = {}
    for r, xv in enumerate(x or []):
        if xv is None or not math.isfinite(xv):
            continue
        vals = [s[r] for s in subs if r < len(s) and s[r] is not None and math.isfinite(s[r])]
        if vals:
            by.setdefault(float(xv), []).append(float(np.mean(vals)))
    xs = np.array(sorted(by))
    return xs, np.array([float(np.mean(by[v])) for v in xs])


def _lowess(xs: np.ndarray, ys: np.ndarray, h: float) -> np.ndarray:
    out = np.empty(len(xs))
    for i, x0 in enumerate(xs):
        u = np.clip(np.abs(xs - x0) / h, 0, 1)
        w = (1 - u ** 3) ** 3
        sw = np.sqrt(w)
        a = np.vstack([np.ones(len(xs)), xs - x0]).T * sw[:, None]
        out[i] = np.linalg.lstsq(a, ys * sw, rcond=None)[0][0]
    return out


HARRELL = {3: [.1, .5, .9], 4: [.05, .35, .65, .95], 5: [.05, .275, .5, .725, .95],
           6: [.05, .23, .41, .59, .77, .95], 7: [.025, .1833, .3417, .5, .6583, .8167, .975]}


def _knots(xs: np.ndarray, k: int) -> np.ndarray:
    ps = HARRELL.get(k) or list(np.linspace(0, 1, k))
    return np.quantile(xs, ps, method="weibull")


def _natural(knots: np.ndarray, x: np.ndarray) -> np.ndarray:
    """The natural cubic spline basis with these knots (truncated powers)."""
    k = len(knots)

    def d(j):
        return (np.maximum(x - knots[j], 0) ** 3 - np.maximum(x - knots[-1], 0) ** 3) / (knots[-1] - knots[j])
    return np.column_stack([np.ones_like(x), x] + [d(j) - d(k - 2) for j in range(k - 2)])


def smoothing_spline(xs: np.ndarray, ys: np.ndarray, at: np.ndarray, k: int) -> np.ndarray:
    if k < 2 or len(xs) < k or (k >= 8 and len(xs) == k):  # Prism draws none (6 points: 6 knots drawn,
        return np.full(len(at), np.nan)  # 10 points: 10 knots not)
    kn = _knots(xs, k)
    if len(np.unique(kn)) < len(kn):
        return np.full(len(at), np.nan)
    lo, span = float(kn[0]), float(kn[-1] - kn[0])  # X scaled to the knots' range: a better-conditioned basis

    def basis(x):
        return _natural((kn - lo) / span, (np.asarray(x, float) - lo) / span)
    beta = np.linalg.lstsq(basis(xs), ys, rcond=None)[0]
    return basis(at) @ beta


MIN_LOWESS = 12  # fewer points: the cubic spline (Prism: 5 to 11 points; verified)


def curve(kind: str, resolution: str, xs: np.ndarray, ys: np.ndarray, at: np.ndarray, knots: int = 4) -> np.ndarray:
    if kind == "SMOOTHING_SPLINE":
        return smoothing_spline(xs, ys, at, knots)
    if len(xs) < 2:
        return np.full(len(at), np.nan)
    if kind == "LOWESS" and len(xs) >= MIN_LOWESS:
        h = WINDOW.get(resolution, WINDOW["MEDIUM"]) * float(xs[-1] - xs[0])
        return np.interp(at, xs, _lowess(xs, ys, h))
    if kind == "AKIMA_SPLINE" and len(xs) >= 3:
        return interpolate.Akima1DInterpolator(xs, ys)(at)
    if kind in ("CUBIC_SPLINE", "LOWESS", "AKIMA_SPLINE"):
        if len(xs) == 2:
            return np.interp(at, xs, ys)
        return interpolate.CubicSpline(xs, ys, bc_type="natural")(at)
    raise NotImplementedError(f"curve type {kind}")


def fit_spline(params: dict, x: list, columns: list, titles: list[str]) -> dict:
    cv = (params.get("calc") or {}).get("curve") or {}
    kind, resolution = cv.get("type", "CUBIC_SPLINE"), cv.get("resolution", "MEDIUM")
    if kind not in ("CUBIC_SPLINE", "AKIMA_SPLINE", "LOWESS", "SMOOTHING_SPLINE"):
        raise NotImplementedError(f"curve type {kind}")
    known = [float(v) for v in (x or []) if v is not None and math.isfinite(v)]
    if not known:
        raise ValueError("no X values")
    n = 4 * len(known)  # Prism: segmentCount, 4 per data row
    grid = np.linspace(min(known), max(known), n)
    cols = []
    for col in columns:
        xs, ys = _points(x, col)
        y = curve(kind, resolution, xs, ys, grid, int(cv.get("knotCount", 4)))
        if len(xs):
            eps = 1e-9 * max(1.0, abs(float(xs[-1] - xs[0])))
            y = np.where((grid >= xs[0] - eps) & (grid <= xs[-1] + eps), y, np.nan)
        cols.append(y)
    rows = [[float(g), *(float(c[k]) if math.isfinite(c[k]) else None for c in cols)] for k, g in enumerate(grid)]
    return {"status": {"error": "VALID", "warning": []},
            "_tables": {"Curve": {"columns": ["X", *titles], "rows": rows, "row_titles": None}}}
