"""Principal component analysis (Prism: PCA) on a multiple-variables table,
with Prism's result keys (verified against a Prism-made sample and
tools/multreg_parity.py).

Standardised data: eigen-decomposition of the correlation matrix (centred
data: of the covariance matrix), via the SVD of the transformed data;
loadings = eigenvector * sqrt(eigenvalue);
scores = transformed data x eigenvectors. Parallel analysis uses Prism's own
random simulations, which are not reproduced (our simulation, same method).
"""

from __future__ import annotations

import numpy as np
import scipy.linalg as sl

# calc.method -> label in dataSummary.method (Prism 11.1)
METHODS = {"PARALLEL_ANALYSIS": "Parallel analysis", "KAISER_RULE": "Eigenvalue > 1 (Kaiser)",
           "EIGENVALUE_ABOVE_THRESHOLD": "Eigenvalue > {thr} (Manual)", "SPECIFIC_NUMBER": "Largest {n} eigenvalues",
           "TOTAL_EXPLAINED_VARIANCE": "{var} total explained variance", "ALL_COMPONENTS": "Select all",
           "UNKNOWN": ""}


def _g(v: float) -> str:
    """Prism's label carries only the first character of the number
    (threshold 0.9 -> "0", 75 % -> "7", 80 % -> "8"; verified)."""
    return f"{v:g}"[:1]


def pca(params: dict, columns, titles) -> dict:
    calc = params.get("calc", {})
    idx = [v["col"]["idx"] for v in params["data"]["variables"]]
    n_total = max(len(columns[i]) for i in idx)
    rows = [r for r in range(n_total)
            if all(r < len(columns[i]) and columns[i][r] not in (None, "") for i in idx)]
    x = np.array([[float(columns[i][r]) for i in idx] for r in rows])
    n, k = x.shape
    centred = x - x.mean(axis=0)
    if calc.get("transform", "STANDARDIZE_DATA") == "STANDARDIZE_DATA":
        z = centred / x.std(axis=0, ddof=1)
    else:
        z = centred
    # SVD of the transformed data (LAPACK gesvd): its orientation is Prism's for PC1
    # in every case checked; later components' signs follow no rule found (findings.md)
    _, s, vt = sl.svd(z, full_matrices=False, lapack_driver="gesvd")
    w, v = s ** 2 / (n - 1), vt.T
    total = float(w.sum())
    method = calc.get("method", "PARALLEL_ANALYSIS")
    pa = None
    if method == "PARALLEL_ANALYSIS":
        pa_cfg = calc.get("parallelAnalysis", {})
        rng = np.random.default_rng(int(pa_cfg.get("randomSeed", 1)))
        sims = []
        for _ in range(int(pa_cfg.get("simulationCount", 1000))):
            r = rng.standard_normal((n, k))
            sims.append(np.sort(np.linalg.eigvalsh(np.corrcoef(r, rowvar=False)))[::-1])
        sims = np.array(sims)
        lvl = pa_cfg.get("percentileLevel", 95.0)
        pa = (sims.mean(axis=0), np.percentile(sims, 100 - lvl, axis=0), np.percentile(sims, lvl, axis=0))
        selected = int(next((j for j in range(k) if w[j] <= pa[0][j]), k))
    elif method == "KAISER_RULE":
        selected = int((w > 1.0).sum())
    elif method == "EIGENVALUE_ABOVE_THRESHOLD":
        selected = int((w > calc.get("eigenvalueThreshold", 1.0)).sum())
    elif method == "SPECIFIC_NUMBER":
        selected = min(int(calc.get("componentCount", 2)), k)
    elif method == "TOTAL_EXPLAINED_VARIANCE":
        cum = np.cumsum(w) / total * 100
        selected = min(int(np.searchsorted(cum, calc.get("explainedVariance", 75.0)) + 1), k)
    else:  # ALL_COMPONENTS, and an unknown value (Prism stores UNKNOWN and keeps all)
        selected = k
    eig = {}
    cum = 0.0
    for j in range(k):
        cum += 100 * w[j] / total
        e = {"value": float(w[j]), "explainedVariance": float(100 * w[j] / total),
             "cumulativeExplainedVariance": float(cum)}
        if pa is not None:
            e["parallelAnalysisValue"] = {"value": float(pa[0][j]),
                                          "percentile": {"lower": float(pa[1][j]), "upper": float(pa[2][j])}}
        eig[f"PC{j + 1}"] = e
    label = METHODS.get(method, "").format(thr=_g(calc.get("eigenvalueThreshold", 1.0)), n=selected,
                                          var=_g(calc.get("explainedVariance", 75.0)))
    summary = {"dataStatus": "VALID", "variablesCount": k, "componentsCount": k, "method": label,
               "selectedComponentsCount": selected, "rowsTotal": n_total, "rowsSkipped": n_total - n, "rowsAnalyzed": n}
    loadings = v * np.sqrt(np.maximum(w, 0))
    scores = z @ v
    tables = {"Loadings": {"rows": [titles[i] for i in idx], "sets": [{"title": f"PC{j + 1}", "subs": [loadings[:, j].tolist()]}
                                                                    for j in range(selected)]},
              "PC scores": {"sets": [{"title": f"PC{j + 1}", "subs": [scores[:, j].tolist()]} for j in range(selected)]}}
    return {"results": {"status": {"error": "VALID", "warning": []}, "eigenvalues": eig, "dataSummary": summary},
            "tables": tables}
