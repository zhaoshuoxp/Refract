"""Frequency distribution (Prism: FREQUENCY_DISTRIBUTION).

Bins are centred on binCenterFirst + k * binWidth. The automatic bin width,
first and last centres are chosen by Prism from all data sets together and
written back as "autoValue"; `auto_bins` reproduces that choice. Output:
{"auto": {...}, "table": {"x": centres, "sets": [counts per data set]},
 "results": results.json content}.
"""

from __future__ import annotations

import math

import numpy as np

from .descriptive import describe

_SUMMARY = ("n", "mean", "sd", "meanSE", "meanCI", "minimum", "firstQuartile", "median", "thirdQuartile", "maximum")


def _nice_down(x: float) -> float:
    """Largest 1, 2 or 5 x 10^k at or below x."""
    e = math.floor(math.log10(x))
    for m in (5, 2, 1):
        v = m * 10.0 ** e
        if v <= x * (1 + 1e-12):
            return v
    return 10.0 ** (e - 1) * 5


def auto_bins(cols: list[np.ndarray]) -> tuple[float, float, float]:
    """Prism's automatic bins (after GraphPad FAQ 1660): per data set width =
    range / (floor(log2 n) + 2); mean over data sets; rounded down to 1/2/5 x
    10^k; integer data: down to an integer, at least 1. First / last bin
    centres: min / max rounded to the nearest multiple of the width.
    Verified on every single-data-set case; several data sets mixing integer
    and non-integer data are not fully reproduced (findings.md)."""
    # bin count floor(log2 n) + 2 (FAQ: 1 + log2 n; Prism rounds it up, and
    # an exact power of two gets one more): verified on all single data sets
    ws = [(c.max() - c.min()) / (math.floor(math.log2(len(c))) + 2) for c in cols if len(c)]
    allv = np.concatenate([c for c in cols if len(c)])
    w = float(np.mean(ws)) if ws else 0.0
    w = _nice_down(w) if w > 0 else 1.0
    if np.all(allv == np.round(allv)):
        w = max(1.0, math.floor(w))
    first = math.floor(allv.min() / w + 0.5) * w + 0.0  # + 0.0: no negative zero
    last = math.floor(allv.max() / w + 0.5) * w + 0.0
    return w, first, last


RELATIVE = {"RELATIVE_PERCENTAGES": 100.0, "RELATIVE_FRACTIONS": 1.0}  # calc.tabulate (Prism's own, E-stats8)


def frequency(params: dict, columns: list, titles: list[str]) -> dict:
    calc = params.get("calc", {})
    cols = [np.asarray([v for v in c if v is not None and math.isfinite(v)], float) for c in columns]
    bw = calc.get("binWidth", {})
    cf, cl = calc.get("binCenterFirst", {}), calc.get("binCenterLast", {})
    auto: dict = {}
    if bw.get("type", "AUTO_BINS") == "NO_BINS":
        # one row per distinct value of each data set in turn (not merged);
        # a data set's counts sit in its own rows, other cells are blank
        x, sets = [], [[] for _ in cols]
        for i, c in enumerate(cols):
            vals, counts = np.unique(c, return_counts=True)
            for v, k in zip(vals.tolist(), counts.tolist(), strict=True):
                x.append(v)
                for j in range(len(cols)):
                    sets[j].append(int(k) if j == i else None)
        binned = [len(c) for c in cols]
    else:
        aw, af, al = auto_bins(cols)
        raw = params.get("_replicates")  # an XY / grouped table's replicates: the width from every value
        if raw:
            aw = auto_bins([np.asarray([v for v in c if v is not None and math.isfinite(v)], float) for c in raw])[0]
            allv = np.concatenate([c for c in cols if len(c)])
            af = math.floor(allv.min() / aw + 0.5) * aw + 0.0
            al = math.floor(allv.max() / aw + 0.5) * aw + 0.0
        auto = {"binWidth": aw, "binCenterFirst": af, "binCenterLast": al}
        w = aw if bw.get("type", "AUTO_BINS") == "AUTO_BINS" else bw.get("value", aw)
        first = af if cf.get("isAuto", True) else cf.get("value", af)
        last = al if cl.get("isAuto", True) else cl.get("value", al)
        nb = round((last - first) / w) + 1
        x = [first + i * w for i in range(nb)]
        sets, binned = [], []
        for c in cols:
            idx = np.floor((c - first) / w + 0.5).astype(int)  # Prism's float arithmetic, no tolerance
            ok = (idx >= 0) & (idx < nb)
            sets.append([int((idx[ok] == i).sum()) for i in range(nb)])
            binned.append(int(ok.sum()))
    if calc.get("distributionType", "FREQUENCY") == "CUMULATIVE_FREQUENCY":
        sets = [[int(v) for v in np.cumsum([0 if u is None else u for u in s])] for s in sets]
    scale = RELATIVE.get(calc.get("tabulate", "VALUE_COUNT"))
    if scale is not None:  # relative frequencies: of the data set's binned values (E-stats8)
        sets = [[None if u is None else (u * scale / binned[i] if binned[i] else 0.0) for u in s]
                for i, s in enumerate(sets)]
    samples = {}
    for i, c in enumerate(cols):
        d = describe(list(c))
        samples[f"col{i}"] = {"id": {"col": {"idx": i}}, "value": {
            "dataSummary": {k: d[k] for k in _SUMMARY if k in d},
            "binsSummary": {"binnedValuesCount": binned[i], "excludedValuesCount": len(c) - binned[i]}}}
    return {"auto": auto, "table": {"x": x, "sets": sets},
            "results": {"status": {"error": "VALID", "warning": []}, "samples": samples}}
