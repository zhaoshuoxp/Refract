"""Two-way ANOVA (Prism: TWO_WAY_ANOVA), with Prism's result keys.

Data are given as cells[r][c] = list of replicate values (None/NaN = missing),
rows = the row factor, columns = the column factor (Prism's grouped table).
Sums of squares come from a linear model with sum-to-zero (effect) coding;
a term's SS is the increase in residual SS when it is dropped (Type III; equal
to the classical SS for balanced data).
"""

from __future__ import annotations

import math

import numpy as np
from scipy import stats

from . import multiple_comparisons as MC


def _p(value: float, alpha: float) -> dict:
    return {"value": float(value), "level": alpha, "isSignificant": bool(value < alpha), "state": "P_VALUE_EQUAL"}


def clean_cells(cells) -> list[list[np.ndarray]]:
    return [[np.asarray([v for v in cell if v is not None and math.isfinite(v)], dtype=float) for cell in row]
            for row in cells]


def _effect(idx: np.ndarray, k: int) -> np.ndarray:
    """Sum-to-zero coding: k-1 columns, last level = -1 everywhere."""
    x = np.zeros((len(idx), k - 1))
    for j in range(k - 1):
        x[idx == j, j] = 1.0
    x[idx == k - 1, :] = -1.0
    return x


def _sse(x: np.ndarray, y: np.ndarray) -> float:
    beta, *_ = np.linalg.lstsq(x, y, rcond=None)
    r = y - x @ beta
    return float(r @ r)


def design(cells):
    g = clean_cells(cells)
    nr, nc = len(g), len(g[0])
    y, ri, ci = [], [], []
    for r in range(nr):
        for c in range(nc):
            y.extend(g[r][c])
            ri.extend([r] * len(g[r][c]))
            ci.extend([c] * len(g[r][c]))
    return g, np.asarray(y), np.asarray(ri), np.asarray(ci)


def anova_terms(y, ri, ci, nr, nc, interaction: bool, ss_type: int = 3) -> dict:
    one = np.ones((len(y), 1))
    xr, xc = _effect(ri, nr), _effect(ci, nc)
    xrc = np.einsum("ni,nj->nij", xr, xc).reshape(len(y), -1)
    full = [one, xr, xc] + ([xrc] if interaction else [])
    sse_full = _sse(np.hstack(full), y)
    ss = {}
    if ss_type == 3 or not interaction:
        ss["row"] = _sse(np.hstack([one, xc] + ([xrc] if interaction else [])), y) - sse_full
        ss["col"] = _sse(np.hstack([one, xr] + ([xrc] if interaction else [])), y) - sse_full
    else:  # Type II
        sse_add = _sse(np.hstack([one, xr, xc]), y)
        ss["row"] = _sse(np.hstack([one, xc]), y) - sse_add
        ss["col"] = _sse(np.hstack([one, xr]), y) - sse_add
    if interaction:
        ss["int"] = _sse(np.hstack([one, xr, xc]), y) - sse_full
    return {"ss": ss, "sse": sse_full}


def ordinary(cells, alpha: float = 0.05, interaction: bool = True, row_titles=None, col_titles=None,
             ss_type: int = 3) -> dict:
    g, y, ri, ci = design(cells)
    nr, nc = len(g), len(g[0])
    counts = np.array([[len(g[r][c]) for c in range(nc)] for r in range(nr)])
    if (counts == 0).any():
        interaction = False  # Prism fits main effects only when a cell is empty
    n = len(y)
    t = anova_terms(y, ri, ci, nr, nc, interaction, ss_type)
    ss_t = float(((y - y.mean()) ** 2).sum())
    df_e = n - (nr * nc if interaction else nr + nc - 1)
    ms_e = t["sse"] / df_e

    def term(ss, df):
        f = (ss / df) / ms_e
        return {"ss": ss, "df": float(df), "ms": ss / df, "variation": 100 * ss / ss_t,
                "fTest": {"status": "VALID", "f": f, "dfNumerator": float(df), "dfDenominator": float(df_e),
                          "pValue": _p(stats.f.sf(f, df, df_e), alpha)}}

    table = {"rowFactor": term(t["ss"]["row"], nr - 1), "colFactor": term(t["ss"]["col"], nc - 1)}
    if interaction:
        table["rowFactorVsColFactor"] = term(t["ss"]["int"], (nr - 1) * (nc - 1))
    table["residual"] = {"ss": t["sse"], "df": float(df_e), "ms": ms_e}
    table["total"] = {"ss": ss_t, "df": float(n - 1)}
    row_titles = row_titles or [f"Row {r + 1}" for r in range(nr)]
    col_titles = col_titles or [chr(65 + c) for c in range(nc)]
    # Prism reports least-squares (predicted) means: cell means for the full
    # model, additive-model predictions for main effects only
    cell_items = [({}, (r, c)) for r in range(nr) for c in range(nc)]
    pred, _ = lsmeans(cells, cell_items, interaction)
    pm = np.asarray(pred).reshape(nr, nc)
    model = {"status": "VALID", "anovaTable": table}
    model.update(difference_blocks(cells, interaction, ms_e, df_e))
    model["means"] = means_block(pm, row_titles, col_titles)
    model["dataSummary"] = {"colCount": nc, "rowCount": nr, "pointCount": n,
                            "isBalancedDesign": bool(interaction and (counts == counts.flat[0]).all())}
    return {"ordinaryAnovaModel": model}


def means_block(pm: np.ndarray, row_titles, col_titles) -> dict:
    nr, nc = pm.shape
    return {
        "total": float(pm.mean()),
        "rows": {f"row{r}": {"id": {"row": {"idx": r, "title": row_titles[r]}}, "value": float(pm[r].mean())}
                 for r in range(nr)},
        "cols": {f"col{c}": {"id": {"col": {"title": col_titles[c], "idx": c}}, "value": float(pm[:, c].mean())}
                 for c in range(nc)},
        "cells": {f"col{c}": {"id": {"col": {"title": col_titles[c], "idx": c}}, "value": {
            f"row{r}": {"id": {"row": {"idx": r, "title": row_titles[r]}}, "value": float(pm[r, c])} for r in range(nr)}}
            for c in range(nc)},
    }


def difference_blocks(cells, interaction: bool, ms_e: float, df_e: float, alpha: float = 0.05) -> dict:
    """Prism's extra blocks for two-level factors: differenceBetweenColMeans
    (2 columns), differenceBetweenRowMeans (2 rows), interaction (2 x 2):
    LS-mean differences with a t interval on the residual df."""
    nr, nc = len(cells), len(cells[0])
    tc = stats.t.ppf(1 - alpha / 2, df_e)
    level = 100 * (1 - alpha)
    out = {}

    def block(items):
        est, cov = lsmeans(cells, items, interaction)
        d = float(est[0] - est[1])
        se = math.sqrt(ms_e * (cov[0, 0] + cov[1, 1] - 2 * cov[0, 1]))
        return {"mean1": float(est[0]), "mean2": float(est[1]), "difference": d, "differenceSE": se,
                "differenceCI": {"lower": d - tc * se, "upper": d + tc * se, "level": level}}

    if nc == 2:
        out["differenceBetweenColMeans"] = block([({}, (None, 0)), ({}, (None, 1))])
    if nr == 2:
        out["differenceBetweenRowMeans"] = block([({}, (0, None)), ({}, (1, None))])
    if nr == 2 and nc == 2 and not interaction:  # additive fit: no interaction, no interval
        est, _ = lsmeans(cells, [({}, (r, c)) for r in range(2) for c in range(2)], False)
        d1, d2 = float(est[0] - est[1]), float(est[2] - est[3])
        out["interaction"] = {"meanDifference1": d1, "meanDifference2": d2, "interaction": 0.0, "interactionSE": 0.0}
    if nr == 2 and nc == 2 and interaction:
        est, cov = lsmeans(cells, [({}, (r, c)) for r in range(2) for c in range(2)], interaction)
        lv = np.array([1.0, -1.0, -1.0, 1.0])
        d1, d2 = float(est[0] - est[1]), float(est[2] - est[3])
        se = math.sqrt(ms_e * float(lv @ cov @ lv))
        out["interaction"] = {"meanDifference1": d1, "meanDifference2": d2, "interaction": d1 - d2, "interactionSE": se,
                              "interactionCI": {"lower": d1 - d2 - tc * se, "upper": d1 - d2 + tc * se, "level": level}}
    return out


def _gg(pooled_cov: np.ndarray) -> float:
    k = pooled_cov.shape[0]
    c = np.eye(k) - np.ones((k, k)) / k
    sc = c @ pooled_cov @ c
    return float(np.trace(sc) ** 2 / ((k - 1) * np.sum(sc * sc)))


def rm_by_rows(cells, alpha: float = 0.05, assume_sphericity: bool = False, row_titles=None, col_titles=None) -> dict:
    """Row factor repeated: in column c, replicate (subcolumn) s is one subject
    measured at every row. Split-plot: column factor between subjects
    (tested against subjects-within-columns), row factor and the interaction
    within subjects (tested against the residual, Geisser-Greenhouse
    corrected unless sphericity is assumed). Subjects with a missing value
    are dropped (Prism fits a mixed model instead; not reproduced)."""
    g = clean_cells(cells)
    nr, nc = len(cells), len(cells[0])
    mats = []  # per column: subjects x rows
    for c in range(nc):
        reps = max(len(cells[r][c]) for r in range(nr))
        rows = []
        for s in range(reps):
            vals = [cells[r][c][s] if s < len(cells[r][c]) else None for r in range(nr)]
            if all(v is not None and math.isfinite(v) for v in vals):
                rows.append(vals)
        mats.append(np.asarray(rows, float))
    ns = np.array([len(m) for m in mats])
    y = np.concatenate([m.ravel() for m in mats])
    gm = y.mean()
    ss_t = float(((y - gm) ** 2).sum())
    n_sub = int(ns.sum())
    row_means = np.concatenate(mats).mean(axis=0)
    ss_c = float(sum(n * nr * (m.mean() - gm) ** 2 for n, m in zip(ns, mats, strict=True)))
    ss_r = float(n_sub * ((row_means - gm) ** 2).sum())
    ss_cells = float(sum(n * ((m.mean(axis=0) - gm) ** 2).sum() for n, m in zip(ns, mats, strict=True)))
    ss_int = ss_cells - ss_r - ss_c
    ss_subj = float(sum(nr * ((m.mean(axis=1) - m.mean()) ** 2).sum() for m in mats))
    ss_e = ss_t - ss_r - ss_c - ss_int - ss_subj
    df_r, df_c = nr - 1, nc - 1
    df_int, df_subj = df_r * df_c, n_sub - nc
    df_e = df_r * df_subj
    ms_e, ms_subj = ss_e / df_e, ss_subj / df_subj
    pooled = sum((m - m.mean(axis=0)).T @ (m - m.mean(axis=0)) for m in mats) / df_subj
    eps = _gg(pooled)

    def term(ss, df, denom_ms, denom_df, within):
        f = (ss / df) / denom_ms
        d1, d2 = (df, denom_df) if (assume_sphericity or not within) else (eps * df, eps * denom_df)
        out = {"ss": ss, "df": float(df), "ms": ss / df, "variation": 100 * ss / ss_t}
        if within and not assume_sphericity and nr > 2:  # Prism omits epsilon (= 1) for two levels
            out["ggEpsilon"] = eps
        out["fTest"] = {"status": "VALID", "f": f, "dfNumerator": float(d1), "dfDenominator": float(d2),
                        "pValue": _p(stats.f.sf(f, d1, d2), alpha)}
        return out

    table = {"rowFactor": term(ss_r, df_r, ms_e, df_e, True),
             "colFactor": term(ss_c, df_c, ms_subj, df_subj, False),
             "rowFactorVsColFactor": term(ss_int, df_int, ms_e, df_e, True),
             "residual": {"ss": ss_e, "df": float(df_e), "ms": ms_e, "variation": 100 * ss_e / ss_t}}
    row_titles = row_titles or [f"Row {r + 1}" for r in range(nr)]
    col_titles = col_titles or [chr(65 + c) for c in range(nc)]
    allr = np.concatenate(mats)
    means = {
        "total": float(gm),
        "rows": {f"row{r}": {"id": {"row": {"idx": r, "title": row_titles[r]}}, "value": float(allr[:, r].mean())}
                 for r in range(nr)},
        "cols": {f"col{c}": {"id": {"col": {"title": col_titles[c], "idx": c}}, "value": float(mats[c].mean())}
                 for c in range(nc)},
        "cells": {f"col{c}": {"id": {"col": {"title": col_titles[c], "idx": c}}, "value": {
            f"row{r}": {"id": {"row": {"idx": r, "title": row_titles[r]}}, "value": float(mats[c][:, r].mean())}
            for r in range(nr)}} for c in range(nc)},
    }
    missing = int(sum(len(x) for row in cells for x in row) - sum(len(x) for row in g for x in row))
    return {"repeatedMeasuresGlmAnovaModel": {
        "status": "VALID", "anovaTable": table, "means": means,
        "dataSummary": {"colCount": nc, "rowCount": nr, "matchedCount": n_sub, "missingCount": missing},
        "_errors": {"row": (ms_e, df_e), "col": (ms_subj, df_subj), "int": (ms_e, df_e)}}}


def _swap_factors(model: dict) -> dict:
    """Relabel a by-rows result computed on the transposed table."""
    m = model["repeatedMeasuresGlmAnovaModel"]
    t = m["anovaTable"]
    t["rowFactor"], t["colFactor"] = t["colFactor"], t["rowFactor"]
    m["anovaTable"] = {k: t[k] for k in ("rowFactor", "colFactor", "rowFactorVsColFactor", "residual")}
    mn = m["means"]
    rows = {f"row{i}": {"id": {"row": {"idx": i, "title": v["id"]["col"]["title"]}}, "value": v["value"]}
            for i, v in enumerate(mn["cols"].values())}
    cols = {f"col{i}": {"id": {"col": {"title": v["id"]["row"]["title"], "idx": i}}, "value": v["value"]}
            for i, v in enumerate(mn["rows"].values())}
    nr, nc = len(rows), len(cols)
    cells = {f"col{c}": {"id": cols[f"col{c}"]["id"], "value": {
        f"row{r}": {"id": rows[f"row{r}"]["id"], "value": mn["cells"][f"col{r}"]["value"][f"row{c}"]["value"]}
        for r in range(nr)}} for c in range(nc)}
    m["means"] = {"total": mn["total"], "rows": rows, "cols": cols, "cells": cells}
    ds = m["dataSummary"]
    ds["colCount"], ds["rowCount"] = ds["rowCount"], ds["colCount"]
    e = m["_errors"]
    m["_errors"] = {"row": e["col"], "col": e["row"], "int": e["int"]}
    return model


def rm_by_cols(cells, alpha: float = 0.05, assume_sphericity: bool = False, row_titles=None, col_titles=None) -> dict:
    """Column factor repeated: in row r, replicate s is one subject measured
    in every column (matched values spread across a row)."""
    nr, nc = len(cells), len(cells[0])
    row_titles = row_titles or [f"Row {r + 1}" for r in range(nr)]
    col_titles = col_titles or [chr(65 + c) for c in range(nc)]
    t = [[cells[r][c] for r in range(nr)] for c in range(nc)]
    return _swap_factors(rm_by_rows(t, alpha, assume_sphericity, row_titles=col_titles, col_titles=row_titles))


def _helmert(k: int) -> np.ndarray:
    """(k-1) x k orthonormal contrasts."""
    h = np.zeros((k - 1, k))
    for i in range(1, k):
        h[i - 1, :i] = 1.0
        h[i - 1, i] = -i
        h[i - 1] /= math.sqrt(i * (i + 1))
    return h


def _gg_contrast(x: np.ndarray, m: np.ndarray) -> float:
    """Geisser-Greenhouse epsilon of the contrasts m (p x q) applied to the
    subjects x q data matrix x."""
    s = np.cov(x @ m.T, rowvar=False).reshape(m.shape[0], m.shape[0])
    p = m.shape[0]
    return float(np.trace(s) ** 2 / (p * np.sum(s * s)))


def rm_by_both(cells, alpha: float = 0.05, assume_sphericity: bool = False, row_titles=None, col_titles=None) -> dict:
    """Both factors repeated: replicate s is one subject measured in every
    cell. Each effect is tested against its interaction with subjects."""
    nr, nc = len(cells), len(cells[0])
    reps = max(len(cells[r][c]) for r in range(nr) for c in range(nc))
    subj = []
    for s in range(reps):
        vals = [cells[r][c][s] if s < len(cells[r][c]) else None for r in range(nr) for c in range(nc)]
        if all(v is not None and math.isfinite(v) for v in vals):
            subj.append(vals)
    x = np.asarray(subj, float)  # subjects x (r, c) in row-major order
    n = len(x)
    cube = x.reshape(n, nr, nc)
    gm = cube.mean()
    ss_t = float(((cube - gm) ** 2).sum())
    m_r, m_c, m_s = cube.mean(axis=(0, 2)), cube.mean(axis=(0, 1)), cube.mean(axis=(1, 2))
    m_rc, m_sr, m_sc = cube.mean(axis=0), cube.mean(axis=2), cube.mean(axis=1)
    ss_r = float(n * nc * ((m_r - gm) ** 2).sum())
    ss_c = float(n * nr * ((m_c - gm) ** 2).sum())
    ss_s = float(nr * nc * ((m_s - gm) ** 2).sum())
    ss_rc = float(n * ((m_rc - m_r[:, None] - m_c[None, :] + gm) ** 2).sum())
    ss_sr = float(nc * ((m_sr - m_s[:, None] - m_r[None, :] + gm) ** 2).sum())
    ss_sc = float(nr * ((m_sc - m_s[:, None] - m_c[None, :] + gm) ** 2).sum())
    ss_e = ss_t - ss_r - ss_c - ss_s - ss_rc - ss_sr - ss_sc
    df_r, df_c, df_s = nr - 1, nc - 1, n - 1
    df_rc, df_sr, df_sc, df_e = df_r * df_c, df_s * df_r, df_s * df_c, df_s * df_r * df_c
    hr, hc = _helmert(nr), _helmert(nc)
    eps = {"row": _gg_contrast(x, np.kron(hr, np.ones((1, nc)) / math.sqrt(nc))),
           "col": _gg_contrast(x, np.kron(np.ones((1, nr)) / math.sqrt(nr), hc)),
           "int": _gg_contrast(x, np.kron(hr, hc))}

    def term(ss, df, ss_den, df_den, key):
        f = (ss / df) / (ss_den / df_den)
        e = 1.0 if assume_sphericity else eps[key]
        out = {"ss": ss, "df": float(df), "ms": ss / df, "variation": 100 * ss / ss_t}
        if not assume_sphericity:
            out["ggEpsilon"] = eps[key]
        out["fTest"] = {"status": "VALID", "f": f, "dfNumerator": float(e * df), "dfDenominator": float(e * df_den),
                        "pValue": _p(stats.f.sf(f, e * df, e * df_den), alpha)}
        return out

    def plain(ss, df):
        return {"ss": ss, "df": float(df), "ms": ss / df, "variation": 100 * ss / ss_t}

    table = {"rowFactor": term(ss_r, df_r, ss_sr, df_sr, "row"),
             "colFactor": term(ss_c, df_c, ss_sc, df_sc, "col"),
             "rowFactorVsColFactor": term(ss_rc, df_rc, ss_e, df_e, "int"),
             "matchedFactorVsRowFactor": plain(ss_sr, df_sr),
             "matchedFactorVsColFactor": plain(ss_sc, df_sc),
             "residual": plain(ss_e, df_e)}
    row_titles = row_titles or [f"Row {r + 1}" for r in range(nr)]
    col_titles = col_titles or [chr(65 + c) for c in range(nc)]
    means = {
        "total": float(gm),
        "rows": {f"row{r}": {"id": {"row": {"idx": r, "title": row_titles[r]}}, "value": float(m_r[r])} for r in range(nr)},
        "cols": {f"col{c}": {"id": {"col": {"title": col_titles[c], "idx": c}}, "value": float(m_c[c])} for c in range(nc)},
        "cells": {f"col{c}": {"id": {"col": {"title": col_titles[c], "idx": c}}, "value": {
            f"row{r}": {"id": {"row": {"idx": r, "title": row_titles[r]}}, "value": float(m_rc[r, c])} for r in range(nr)}}
            for c in range(nc)},
    }
    return {"repeatedMeasuresGlmAnovaModel": {
        "status": "VALID", "anovaTable": table, "means": means,
        "dataSummary": {"colCount": nc, "rowCount": nr, "matchedCount": n,
                        "missingCount": int(sum(1 for r in range(nr) for c in range(nc) for v in cells[r][c]
                                                if v is None or not math.isfinite(v)))},
        "_errors": {"row": (ss_sr / df_sr, df_sr), "col": (ss_sc / df_sc, df_sc), "int": (ss_e / df_e, df_e)}}}


# ------------------------------------------------------- multiple comparisons
def _cell_stats(cells):
    g = clean_cells(cells)
    nr, nc = len(g), len(g[0])
    mean = np.array([[g[r][c].mean() if len(g[r][c]) else np.nan for c in range(nc)] for r in range(nr)])
    n = np.array([[len(g[r][c]) for c in range(nc)] for r in range(nr)], float)
    return mean, n


# simple effects: (compare rows within each column?, one family for all?)
SIMPLE = {
    "COMPARE_CELLS_BY_ROWS_WITHIN_COLUMNS_SEPARATE_FAMILIES": (True, False),
    "COMPARE_CELLS_BY_ROWS_WITHIN_COLUMNS_SINGLE_FAMILY": (True, True),
    "COMPARE_CELLS_BY_COLUMNS_WITHIN_ROWS_SEPARATE_FAMILIES": (False, False),
    "COMPARE_CELLS_BY_COLUMNS_WITHIN_ROWS_SINGLE_FAMILY": (False, True),
}


def _families(means_design: str, nr: int, nc: int, k: int) -> list[list[int]]:
    """Item indices (cells numbered row-major) of each comparison family, in
    Prism's order: by column for rows-within-columns, by row otherwise."""
    if means_design not in SIMPLE:
        return [list(range(k))]
    rows_within_cols, _ = SIMPLE[means_design]
    if rows_within_cols:
        return [[r * nc + c for r in range(nr)] for c in range(nc)]
    return [[r * nc + c for c in range(nc)] for r in range(nr)]


def _ids(means_design: str, nr: int, nc: int, row_titles, col_titles):
    """Items compared, in Prism's order, as (id dict, (r or None, c or None))."""
    if means_design == "COMPARE_COLUMNS":
        return [({"col": {"title": col_titles[c], "idx": c}}, (None, c)) for c in range(nc)]
    if means_design == "COMPARE_ROWS":
        return [({"row": {"idx": r, "title": row_titles[r]}}, (r, None)) for r in range(nr)]
    if means_design == "COMPARE_CELLS" or means_design in SIMPLE:
        return [({"col": {"title": col_titles[c], "idx": c}, "row": {"idx": r, "title": row_titles[r]}}, (r, c))
                for r in range(nr) for c in range(nc)]
    raise NotImplementedError(f"meansDesignType {means_design}")


def lsmeans(cells, items, interaction: bool):
    """Least-squares means of the items and their unscaled covariance
    (multiply by MS_residual): L b and L (X'X)^-1 L' for the effect-coded
    linear model (full, or main effects only)."""
    g, y, ri, ci = design(cells)
    nr, nc = len(g), len(g[0])
    if any(len(g[r][c]) == 0 for r in range(nr) for c in range(nc)):
        interaction = False
    one = np.ones((len(y), 1))
    xr, xc = _effect(ri, nr), _effect(ci, nc)
    parts = [one, xr, xc]
    if interaction:
        parts.append(np.einsum("ni,nj->nij", xr, xc).reshape(len(y), -1))
    x = np.hstack(parts)
    xtx_inv = np.linalg.pinv(x.T @ x)
    beta = xtx_inv @ x.T @ y

    def code(level, k):
        v = np.zeros(k - 1)
        if level is None:
            return v
        if level == k - 1:
            v[:] = -1.0
        else:
            v[level] = 1.0
        return v

    rows = []
    for _, (r, c) in items:
        lr, lc = code(r, nr), code(c, nc)
        row = [np.ones(1), lr, lc]
        if interaction:
            row.append(np.outer(lr, lc).ravel())
        rows.append(np.concatenate(row))
    lm = np.array(rows)
    return lm @ beta, lm @ xtx_inv @ lm.T


def compare(cells, design: str, means_design: str, method: str, pair_design: str = "ALL_VS_ALL",
            mc_type: str = "STATISTICAL", alpha: float = 0.05, control: int = 0, row_titles=None, col_titles=None,
            ms_error: float | None = None, df_error: float | None = None, discovery_level: float = 0.05,
            subjects=None, interaction: bool = True, rm_pooled: bool = False, mixed_fit: dict | None = None) -> dict:
    """Two-way post tests. Ordinary designs: least-squares (predicted) means
    with the pooled residual MS; Var(LS mean) = MS * mean_over_levels(1/n)/levels.
    Repeated factor of an RM design: paired differences over all subjects
    (df = subjects - 1). subjects: per-item arrays for the RM case."""
    mean, n = _cell_stats(cells)
    nr, nc = mean.shape
    row_titles = row_titles or [f"Row {r + 1}" for r in range(nr)]
    col_titles = col_titles or [chr(65 + c) for c in range(nc)]
    items = _ids(means_design, nr, nc, row_titles, col_titles)
    k = len(items)
    est, var, cnt = [], [], []
    for _, (r, c) in items:
        if r is None:
            est.append(float(np.mean(mean[:, c]))); var.append(float(np.mean(1 / n[:, c]) / nr)); cnt.append(int(n[:, c].sum()))
        elif c is None:
            est.append(float(np.mean(mean[r, :]))); var.append(float(np.mean(1 / n[r, :]) / nc)); cnt.append(int(n[r, :].sum()))
        else:
            est.append(float(mean[r, c])); var.append(float(1 / n[r, c])); cnt.append(int(n[r, c]))
    cov = None
    rm_cells = None
    ls_df = None
    if mixed_fit is not None and (subjects == "BETWEEN" or (rm_pooled and subjects is not None and
                                                          not isinstance(subjects, tuple))):
        # mixed-model fit: least-squares means and their covariance, df of the factor's stratum (verified)
        lmat = np.array([mixed_fit["lsm"](r, c) for _, (r, c) in items])
        est = [float(v) for v in lmat @ mixed_fit["beta"]]
        cov = lmat @ mixed_fit["cov"] @ lmat.T
        ls_df = float(mixed_fit["df"]["col" if means_design == "COMPARE_COLUMNS" else "row"])
        subjects = None
    if isinstance(subjects, tuple):  # ("CELLS", design): simple effects in an RM design
        rm_cells = subjects[1]
        subjects = None
        cov = np.zeros((k, k))
        rep_levels = {"REPEATED_MEASURES_BY_ROWS": nr, "REPEATED_MEASURES_BY_COLS": nc}.get(rm_cells, 0)
        allc = [np.asarray(cells[r][c], float) for r in range(nr) for c in range(nc)]
        wc_df = sum(len(x) - 1 for x in allc)
        wc_ms = sum(((x - x.mean()) ** 2).sum() for x in allc) / wc_df
    elif isinstance(subjects, str):  # "BETWEEN": between-subjects factor, error = MS(subjects)
        cov = np.diag([1.0 / c for c in cnt])
        subjects = None
    elif subjects is None and ls_df is None:
        est_v, cov = lsmeans(cells, items, interaction)
        est = [float(v) for v in est_v]
    fams = _families(means_design, nr, nc, k)
    fam_pairs = [[(f[a], f[b]) for a, b in MC.pairs(len(f), pair_design, control)] for f in fams]
    prs = [pr for fp in fam_pairs for pr in fp]
    raw = []
    pair_stats: dict = {}
    too_few: dict = {}
    for i, j in prs:
        diff = est[i] - est[j]
        if rm_cells is not None:
            (ri_, ci_), (rj_, cj_) = items[i][1], items[j][1]
            a, b = np.asarray(cells[ri_][ci_], float), np.asarray(cells[rj_][cj_], float)
            shared = (rm_cells == "REPEATED_MEASURES_BY_BOTH_FACTORS" or
                      (rm_cells == "REPEATED_MEASURES_BY_ROWS" and ci_ == cj_) or
                      (rm_cells == "REPEATED_MEASURES_BY_COLS" and ri_ == rj_))
            if shared:  # same subjects: paired differences (subjects with both values)
                ok = ~np.isnan(a) & ~np.isnan(b)
                d = a[ok] - b[ok]
                if len(d) < 2:
                    too_few[(i, j)] = float(d.sum())
                    pair_stats[(i, j)] = ((float(a[ok].sum()), int(ok.sum())), (float(b[ok].sum()), int(ok.sum())))
                    continue
                se, df = float(d.std(ddof=1) / math.sqrt(len(d))), float(len(d) - 1)
                if not ok.all():
                    diff = float(d.mean())
                    pair_stats[(i, j)] = ((float(a[ok].mean()), int(ok.sum())), (float(b[ok].mean()), int(ok.sum())))
            elif mixed_fit is not None and rep_levels == 2:  # different subjects, two repeated levels,
                # mixed-model fit: LS covariance, df = N - cells (verified)
                li, lj = mixed_fit["lsm"](ri_, ci_), mixed_fit["lsm"](rj_, cj_)
                lv = li - lj
                diff = float(lv @ mixed_fit["beta"])
                pair_stats[(i, j)] = ((float(li @ mixed_fit["beta"]), cnt[i]), (float(lj @ mixed_fit["beta"]), cnt[j]))
                se = float(math.sqrt(lv @ mixed_fit["cov"] @ lv))
                df = float(mixed_fit["n_obs"] - nr * nc)
            elif rep_levels == 2:  # two repeated levels: pooled within-cell MS, df = df_subjects + df_residual
                se = math.sqrt(wc_ms * (1 / len(a) + 1 / len(b)))
                df = float(wc_df)
            else:  # different subjects: Welch (on the available values)
                a, b = a[~np.isnan(a)], b[~np.isnan(b)]
                va, vb = a.var(ddof=1) / len(a), b.var(ddof=1) / len(b)
                se = math.sqrt(va + vb)
                df = (va + vb) ** 2 / (va ** 2 / (len(a) - 1) + vb ** 2 / (len(b) - 1))
        elif ls_df is not None:
            se = math.sqrt(cov[i, i] + cov[j, j] - 2 * cov[i, j])
            df = ls_df
        elif subjects is not None and rm_pooled:  # sphericity assumed: pooled residual MS
            se, df = math.sqrt(ms_error * 2 / len(subjects[i])), float(df_error)
        elif subjects is not None:
            # paired differences over the subjects measured at both levels
            # (with missing values, Prism's mixed-model post tests: verified)
            ok = ~np.isnan(subjects[i]) & ~np.isnan(subjects[j])
            d = subjects[i][ok] - subjects[j][ok]
            if len(d) < 2:  # one subject with both values: TOO_FEW_POINTS (verified)
                too_few[(i, j)] = float(d.sum())
                pair_stats[(i, j)] = ((float(subjects[i][ok].sum()), int(ok.sum())), (float(subjects[j][ok].sum()), int(ok.sum())))
                continue
            se, df = float(d.std(ddof=1) / math.sqrt(len(d))), float(len(d) - 1)
            if not ok.all():
                diff = float(d.mean())
                pair_stats[(i, j)] = ((float(subjects[i][ok].mean()), int(ok.sum())),
                                      (float(subjects[j][ok].mean()), int(ok.sum())))
        else:
            se = math.sqrt(ms_error * (cov[i, i] + cov[j, j] - 2 * cov[i, j]))
            df = float(df_error)
        t = abs(diff) / se
        raw.append((i, j, diff, se, t, df, float(2 * stats.t.sf(t, df))))
    by_pair = {(r[0], r[1]): r for r in raw}
    single = SIMPLE.get(means_design, (None, True))[1]
    if means_design in SIMPLE and single and method in ("TUKEY", "DUNNET", "NEWMAN_KEULS"):
        method = "BONFERRONI_SIDAK"  # Prism switches range-based tests to Sidak for one pooled family
    groups = [prs] if single else fam_pairs
    tests, name = {}, ""
    for fp_all in groups:
        fp = [pr for pr in fp_all if pr in by_pair]
        fraw = [by_pair[pr] for pr in fp]
        kk = len(fams[0]) if means_design in SIMPLE else k
        lam = None
        if method == "DUNNET" and mc_type == "STATISTICAL":
            # Prism uses the total n of each level (not the LS-mean variances)
            lam = [math.sqrt(cnt[j] / (cnt[j] + cnt[i])) for i, j in fp]
        if single:
            t_, name, _ = MC.adjust_family(fraw, method, mc_type, alpha, kk, np.array(est), fp, lam, discovery_level,
                                            q_level_quirk=False, individual=True)
        else:  # one family: local indices (Newman-Keuls orders the family's own means)
            fam = sorted({x for pr in fp for x in pr})
            loc = {g_: a for a, g_ in enumerate(fam)}
            lraw = [(loc[r[0]], loc[r[1]], *r[2:]) for r in fraw]
            lt, name, _ = MC.adjust_family(lraw, method, mc_type, alpha, kk, np.array([est[g_] for g_ in fam]),
                                           [(loc[i], loc[j]) for i, j in fp], lam, discovery_level,
                                           q_level_quirk=False, individual=True)
            t_ = {(fam[a], fam[b]): v for (a, b), v in lt.items()}
        tests.update(t_)
    if method == "DUNNET" and mc_type == "STATISTICAL":  # Prism reports the adjusted P as individual too
        for t in tests.values():
            t["pValueIndividual"] = dict(t["pValueAdjusted"])
    for pr, dv in too_few.items():
        tests[pr] = {"status": "TOO_FEW_POINTS", "meansDifference": dv}
    tests = {pr: tests[pr] for pr in prs if pr in tests}  # Prism's pair order
    for (i, j), t in tests.items():
        (m1, n1), (m2, n2) = pair_stats.get((i, j), ((est[i], cnt[i]), (est[j], cnt[j])))
        t["sample1"] = {"id": items[i][0], "value": {"mean": m1, "n": n1}}
        t["sample2"] = {"id": items[j][0], "value": {"mean": m2, "n": n2}}
    out = {"status": "VALID", "method": name, "familyCount": len(groups),
           "comparisonPerFamilyCount": len(groups[0])}
    # (two-way results carry no discoveryCount)
    out["tests"] = {"items": items, "pairs": tests}
    return out


def rm_subjects(design: str, means_design: str, cells):
    """Post tests in repeated-measures designs (Prism 11, verified):
    the repeated factor of a one-factor RM design and the cells of a
    both-factors design are compared with paired differences over all
    subjects. Returns (subject vectors per item, warning): (None,
    "POSTTEST_DISABLED") for a between-subjects factor (allowed, as "BETWEEN",
    only when the repeated factor has two levels) or a main effect of the
    both-factors design; (None, None) when Prism silently skips (cells of a
    one-factor RM design). Simple effects: ("CELLS", design) -- pairs that
    share subjects use paired differences, others a Welch t (verified)."""
    nr, nc = len(cells), len(cells[0])
    reps = len(cells[0][0])
    if means_design in SIMPLE:  # simple effects: paired within subjects, Welch between
        return ("CELLS", design), None
    if design == "REPEATED_MEASURES_BY_COLS":
        if means_design == "COMPARE_COLUMNS":
            x = np.array([[cells[r][c][s] for c in range(nc)] for r in range(nr) for s in range(reps)], float)
            return [x[:, c] for c in range(nc)], None
        if means_design == "COMPARE_ROWS":  # between subjects: only when the repeated factor has two levels
            return ("BETWEEN", None) if nc == 2 else (None, "POSTTEST_DISABLED")
        return None, None
    if design == "REPEATED_MEASURES_BY_ROWS":
        if means_design == "COMPARE_ROWS":
            x = np.array([[cells[r][c][s] for r in range(nr)] for c in range(nc) for s in range(reps)], float)
            return [x[:, r] for r in range(nr)], None
        if means_design == "COMPARE_COLUMNS":
            return ("BETWEEN", None) if nr == 2 else (None, "POSTTEST_DISABLED")
        return None, None
    if design == "REPEATED_MEASURES_BY_BOTH_FACTORS":
        if means_design == "COMPARE_CELLS":
            x = np.array([[cells[r][c][s] for r in range(nr) for c in range(nc)] for s in range(reps)], float)
            return [x[:, i] for i in range(nr * nc)], None
        return None, "POSTTEST_DISABLED"
    return None, None


def rm_difference_blocks(cells, errors: dict, alpha: float = 0.05) -> dict:
    """differenceBetweenColMeans / RowMeans / interaction for complete RM data:
    each uses the error term that tests that effect (and its df)."""
    nr, nc = len(cells), len(cells[0])
    m = np.array([[np.mean(cells[r][c]) for c in range(nc)] for r in range(nr)])
    n = np.array([[len(cells[r][c]) for c in range(nc)] for r in range(nr)], float)
    level = 100 * (1 - alpha)
    out = {}

    def block(m1, m2, n1, n2, key):
        ms, df = errors[key]
        tc = stats.t.ppf(1 - alpha / 2, df)
        d = float(m1 - m2)
        se = math.sqrt(ms * (1 / n1 + 1 / n2))
        return {"mean1": float(m1), "mean2": float(m2), "difference": d, "differenceSE": se,
                "differenceCI": {"lower": d - tc * se, "upper": d + tc * se, "level": level}}

    if nc == 2:
        out["differenceBetweenColMeans"] = block(m[:, 0].mean(), m[:, 1].mean(), n[:, 0].sum(), n[:, 1].sum(), "col")
    if nr == 2:
        out["differenceBetweenRowMeans"] = block(m[0].mean(), m[1].mean(), n[0].sum(), n[1].sum(), "row")
    if nr == 2 and nc == 2:
        ms, df = errors["int"]
        tc = stats.t.ppf(1 - alpha / 2, df)
        d1, d2 = float(m[0, 0] - m[0, 1]), float(m[1, 0] - m[1, 1])
        se = math.sqrt(ms * float((1 / n).sum()))
        out["interaction"] = {"meanDifference1": d1, "meanDifference2": d2, "interaction": d1 - d2, "interactionSE": se,
                              "interactionCI": {"lower": d1 - d2 - tc * se, "upper": d1 - d2 + tc * se, "level": level}}
    return out
