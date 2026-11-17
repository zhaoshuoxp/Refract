"""Hierarchical clustering (Prism: HIERARCHICAL_CLUSTERING) and K-means
clustering (Prism: K_MEANS_CLUSTERING) of a Multiple-variables table, with
Prism's result keys.

Hierarchical: the rows (and, for data.inputType ROWS_COLUMNS, the variables)
are clustered by agglomerative linkage of the transformed data. Verified
against the results Prism 11.1 stored in its own two clustering templates
(read locally, E-cluster): every merge distance, the merge order, the node
order within a merge, the clusters of a cut and their order, the cophenetic
correlation and distances, the within-cluster sums of squares and the
distance matrices. The trial Prism on this machine does not compute these
analyses (E-cluster), so options the templates do not use are computed as
the usual definitions say and are not verified.
"""

from __future__ import annotations

import math

import numpy as np
from scipy.cluster import hierarchy as H
from scipy.spatial.distance import pdist, squareform

# calc.linkage -> scipy method (GROUP_AVERAGE, COMPLETE: verified; the others by name)
LINKAGE = {"GROUP_AVERAGE": "average", "COMPLETE": "complete", "SINGLE": "single", "WARD": "ward",
           "CENTROID": "centroid", "MEDIAN": "median", "WEIGHTED_AVERAGE": "weighted"}
# calc.distance.type -> scipy metric (EUCLIDIAN: verified)
DISTANCE = {"EUCLIDIAN": "euclidean", "MANHATTAN": "cityblock", "MINKOWSKI": "minkowski",
            "CHEBYSHEV": "chebyshev", "PEARSON": "correlation", "COSINE": "cosine"}


def _transform(x: np.ndarray, how: str, axis: int) -> np.ndarray:
    """NONE; CENTER: less the mean; STANDARDIZE: less the mean, over the SD (n - 1) - of each column
    (axis 0) or each row (axis 1)."""
    if how in ("", "NONE", None):
        return x
    m = x.mean(axis=axis, keepdims=True)
    if how == "CENTER":
        return x - m
    if how == "STANDARDIZE":
        sd = x.std(axis=axis, ddof=1, keepdims=True)
        sd[sd == 0] = 1.0
        return (x - m) / sd
    raise NotImplementedError(f"transform {how}")


def _number(v) -> float | None:
    if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v):
        return float(v)
    return None


def _labels(params: dict, columns, rows: list[int]) -> list[str]:
    lab = (params.get("data") or {}).get("label") or {}
    i = ((lab.get("variable") or {}).get("col") or {}).get("idx") if lab.get("type") == "VARIABLE" else None
    if isinstance(i, int) and 0 <= i < len(columns):
        c = columns[i]
        out = []
        for r in rows:
            v = c[r] if r < len(c) else None
            out.append("" if v is None else (f"{v:g}" if isinstance(v, float) else str(v)))
        return out
    return [str(r + 1) for r in rows]


def _tree(z: np.ndarray, n: int):
    """Prism's merge records from a scipy linkage: (node1, node2, distance) per merge, the new
    cluster n + j. Prism keeps its clusters in a list; a merge puts the new cluster where the later
    of the two was and drops the earlier one, and names the earlier one node1 (verified, 42/42)."""
    active = list(range(n))
    merges = []
    for j, (a, b, h, _) in enumerate(z):
        pa, pb = active.index(int(a)), active.index(int(b))
        p, q = min(pa, pb), max(pa, pb)
        merges.append((active[p], active[q], float(h)))
        active[q] = n + j
        del active[p]
    return merges


def _members(merges, n: int) -> dict[int, list[int]]:
    m = {i: [i] for i in range(n)}
    for j, (a, b, _) in enumerate(merges):
        m[n + j] = m[a] + m[b]
    return m


def _cut(merges, n: int, k: int) -> list[int]:
    """The roots of a cut into k clusters, in Prism's cluster order: as they appear in the last
    k - 1 merges (verified)."""
    k = max(1, min(k, n))
    if k == 1:
        return [2 * n - 2] if n > 1 else [0]
    first = n + (n - k)  # the clusters made after the cut
    out = []
    for a, b, _ in merges[n - k:]:
        for x in (a, b):
            if x < first and x not in out:
                out.append(x)
    return out


def _wcss(z: np.ndarray, groups: list[list[int]]) -> float:
    return float(sum(((z[g] - z[g].mean(axis=0)) ** 2).sum() for g in groups if g))


def _side(z: np.ndarray, labels: list[str], define: dict, calc: dict, report: dict, plots: list[str],
          suffix: str, raw: np.ndarray, var_names: list[str], label_title: str, tables: dict) -> dict:
    n = len(z)
    dist = calc.get("distance") or {}
    metric = DISTANCE.get(dist.get("type", "EUCLIDIAN"))
    method = LINKAGE.get(calc.get("linkage", "GROUP_AVERAGE"))
    if metric is None or method is None:
        raise NotImplementedError(f"distance {dist.get('type')} / linkage {calc.get('linkage')}")
    d = pdist(z, metric, p=float(dist.get("value") or 2.0)) if metric == "minkowski" else pdist(z, metric)
    if method in ("ward", "centroid", "median"):
        link = H.linkage(z, method, metric="euclidean")
    else:
        link = H.linkage(d, method)
    merges = _tree(link, n)
    members = _members(merges, n)

    def name(node: int) -> str:
        return labels[node] if node < n else f"Cluster {node - n + 1}"

    out: dict = {"status": "VALID", "dendrogram": [
        {"node1": {"id": a, "label": name(a)}, "node2": {"id": b, "label": name(b)}, "distance": h,
         "cluster": {"id": n + j, "label": name(n + j)}} for j, (a, b, h) in enumerate(merges)]}
    coph = squareform(H.cophenet(link))
    if report.get("copheneticCorrelation"):
        out["copheneticCorrelation"] = float(H.cophenet(link, d)[0])
    how = (define or {}).get("method", "NONE")
    roots = None
    if how == "NUMBER_OF_CLUSTERS":
        roots = _cut(merges, n, int(define.get("clusterCount") or 2))
    elif how == "CUTOFF_HEIGHT":  # every merge above the height splits off a cluster
        hgt = float(define.get("cutoffHeight") or 0.0)
        roots = _cut(merges, n, 1 + sum(1 for *_, h in merges if h > hgt))
    if roots is not None:
        out["clusters"] = [{"points": [{"id": i, "idx": i, "label": labels[i]} for i in sorted(members[r])]}
                           for r in roots]
    if "ELBOW_PLOT" in plots:
        out["clusteringDetails"] = [{"clusterCount": k, "wcss": _wcss(z, [members[r] for r in _cut(merges, n, k)])}
                                    for k in range(1, n)]
        tables[f"Elbow plot ({suffix})"] = {"columns": ["X", "WCSS"], "row_titles": None,
                                            "rows": [[float(c["clusterCount"]), c["wcss"]]
                                                     for c in out["clusteringDetails"]]}
    if roots is not None:
        which = {i: c for c, r in enumerate(roots) for i in members[r]}
        tables[f"Clustered data ({suffix})"] = {
            "columns": [label_title, *var_names, "Cluster"], "row_titles": None,
            "rows": [[labels[i], *raw[i].tolist(), f"Cluster {which[i] + 1}"] for i in range(n)]}
    full = bool(report.get("outputFullMatrix"))

    def matrix(m: np.ndarray, diag) -> list[list]:
        rows = []
        for i in range(n):
            cells = []
            for j in range(n):
                if i == j:
                    cells.append(diag)
                elif full or i > j:
                    cells.append(float(m[i, j]))
                else:
                    cells.append(None)
            rows.append([labels[i], *cells])
        return rows

    if report.get("distanceMatrix"):
        tables[f"Distance matrix ({suffix})"] = {"columns": ["", *labels], "row_titles": None,
                                                 "rows": matrix(squareform(d), 0.0 if full else None)}
    if report.get("copheneticDistanceMatrix"):
        tables[f"Cophenetic distances ({suffix})"] = {"columns": ["", *labels], "row_titles": None,
                                                      "rows": matrix(coph, None)}
    if report.get("mergeMap"):
        tables[f"Merge map ({suffix})"] = {
            "columns": ["Merge order", "Node 1", "Node 2", "Cophenetic distance"], "row_titles": None,
            "rows": [[float(j + 1), name(a), name(b), h] for j, (a, b, h) in enumerate(merges)]}
    return out


def hierarchical(params: dict, columns, titles: list[str]) -> dict:
    data = params.get("data") or {}
    calc = params.get("calc") or {}
    idx = [v["col"]["idx"] for v in data.get("variables", [])]
    n_total = max((len(columns[i]) for i in idx), default=0)
    rows = [r for r in range(n_total) if all(r < len(columns[i]) and _number(columns[i][r]) is not None for i in idx)]
    if len(rows) < 2 or not idx:
        return {"status": {"error": "NOT_ENOUGH_DATA", "warning": []}}
    raw = np.array([[_number(columns[i][r]) for i in idx] for r in rows])
    z = _transform(_transform(raw, calc.get("rowTransform", "NONE"), 1), calc.get("columnTransform", "NONE"), 0)
    labels = _labels(params, columns, rows)
    lab = data.get("label") or {}
    li = ((lab.get("variable") or {}).get("col") or {}).get("idx") if lab.get("type") == "VARIABLE" else None
    label_title = titles[li] if isinstance(li, int) and 0 <= li < len(titles) else ""
    names = [titles[i] for i in idx]
    report = params.get("report") or {}
    plots = (params.get("graph") or {}).get("plots") or []
    define = params.get("defineClusters") or {}
    tables: dict = {}
    if report.get("standardizedData"):
        tables["Standardized/centered data"] = {"columns": [label_title, *names], "row_titles": None,
                                                "rows": [[labels[i], *z[i].tolist()] for i in range(len(rows))]}
    out = {"status": {"error": "VALID", "warning": []},
           "rows": _side(z, labels, define.get("rows"), calc, report, plots, "rows", raw, names, label_title, tables)}
    summary = {"variablesCount": len(idx), "rowsTotal": n_total, "rowsSkipped": n_total - len(rows),
               "rowsAnalyzed": len(rows)}
    if data.get("inputType") == "ROWS_COLUMNS":
        out["columns"] = _side(z.T.copy(), names, define.get("columns"), calc, report, plots, "columns", raw.T,
                               labels, "", tables)
        summary.update(columnsSkipped=0, columnsAnalyzed=len(idx))
    out["dataSummary"] = summary
    out["_tables"] = tables
    return out


# ---------------------------------------------------------------- K-means
def _assign(z: np.ndarray, c: np.ndarray) -> np.ndarray:
    return ((z[:, None, :] - c[None]) ** 2).sum(2).argmin(1)


def _centres(z: np.ndarray, lab: np.ndarray, k: int, old: np.ndarray) -> np.ndarray:
    return np.array([z[lab == j].mean(0) if (lab == j).any() else old[j] for j in range(k)])


def _refine(z: np.ndarray, lab: np.ndarray, k: int, max_iter: int) -> tuple[np.ndarray, int]:
    """Lloyd steps, then single-point transfers that lower the within-cluster sum of squares
    (Hartigan's criterion, n_j / (n_j - 1) and n_l / (n_l + 1)) until none does."""
    it = 0
    c = _centres(z, lab, k, z[:k])
    for it in range(1, max(1, max_iter) + 1):
        new = _assign(z, c)
        if (new == lab).all() and it > 1:
            break
        lab = new
        c = _centres(z, lab, k, c)
    counts = np.bincount(lab, minlength=k).astype(float)
    moved = True
    passes = 0
    while moved and passes < 50:
        moved = False
        passes += 1
        for i in range(len(z)):
            j = lab[i]
            if counts[j] <= 1:
                continue
            d = ((c - z[i]) ** 2).sum(1)
            cost_out = d[j] * counts[j] / (counts[j] - 1)
            gain = d * counts / (counts + 1)
            gain[j] = np.inf
            m = int(gain.argmin())
            if gain[m] < cost_out - 1e-12:
                c[j] = (c[j] * counts[j] - z[i]) / (counts[j] - 1)
                c[m] = (c[m] * counts[m] + z[i]) / (counts[m] + 1)
                counts[j] -= 1
                counts[m] += 1
                lab[i] = m
                moved = True
    return lab, it


def kmeans(z: np.ndarray, k: int, seed: int, starts: int = 25, max_iter: int = 10) -> tuple[np.ndarray, int]:
    """The best of `starts` k-means++ starts, refined (Hartigan transfers): labels numbered by
    first appearance, and the iterations of the best start."""
    n = len(z)
    k = max(1, min(k, n))
    rng = np.random.default_rng(seed)
    best = None
    for _ in range(starts if k > 1 else 1):
        idx = [int(rng.integers(n))]
        for _ in range(1, k):
            d2 = ((z[:, None, :] - z[idx][None]) ** 2).sum(2).min(1)
            idx.append(int(rng.choice(n, p=d2 / d2.sum())) if d2.sum() > 0 else int(rng.integers(n)))
        lab, it = _refine(z, _assign(z, z[idx]), k, max_iter)
        w = _wcss(z, [np.flatnonzero(lab == j).tolist() for j in range(k)])
        if best is None or w < best[0] - 1e-9:
            best = (w, lab, it)
    _, lab, it = best
    order = list(dict.fromkeys(lab.tolist()))
    remap = {old: new for new, old in enumerate(order)}
    return np.array([remap[v] for v in lab]), it


def _metrics(z: np.ndarray, d: np.ndarray, labs: dict[int, np.ndarray], wcss: dict[int, float]) -> dict:
    """The cluster-validity indices of each partition (verified against Prism's own values for
    its partitions, E-cluster; Krzanowski-Lai excepted)."""
    n, p = z.shape
    iu = np.triu_indices(n, 1)
    dv = d[iu]
    nt = len(dv)
    total = ((z - z.mean(0)) ** 2).sum()
    tv = ((z - z.mean(0)) ** 2).sum(0)
    out: dict[int, dict] = {}
    for k, lab in labs.items():
        m: dict = {}
        if k < 2 or k >= n:
            out[k] = m
            continue
        cent = np.array([z[lab == j].mean(0) for j in range(k)])
        w, b = wcss[k], total - wcss[k]
        m["calinskiHarabasz"] = (b / (k - 1)) / (w / (n - k))
        s = np.array([math.sqrt((((z[lab == j] - cent[j]) ** 2).sum(1)).mean()) for j in range(k)])
        cd = squareform(pdist(cent))
        m["daviesBouldin"] = float(np.mean([max((s[i] + s[j]) / cd[i, j] for j in range(k) if j != i)
                                            for i in range(k)]))
        same = (lab[:, None] == lab[None])[iu]
        dw, db = dv[same], dv[~same]
        nw, nb = len(dw), len(db)
        srt = np.sort(dv)
        m["cIndex"] = float((dw.sum() - srt[:nw].sum()) / (srt[-nw:].sum() - srt[:nw].sum())) if nw else 0.0
        bg = np.array([sum((lab == j).sum() * (cent[j, v] - z[:, v].mean()) ** 2 for j in range(k)) for v in range(p)])
        m["ratkowsky"] = float(math.sqrt(np.mean(bg / tv) / k))
        m["ballHall"] = w / k
        sb = np.sort(db)
        minus = float(np.searchsorted(sb, dw, "left").sum())  # a between pair closer than a within pair
        plus = float((nb - np.searchsorted(sb, dw, "right")).sum())
        m["gamma"] = (plus - minus) / (plus + minus) if plus + minus else 0.0
        m["gplus"] = 2 * minus / (nt * (nt - 1))
        m["tau"] = (plus - minus) / (nt * (nt - 1) / 2)
        diam = max(d[np.ix_(lab == j, lab == j)].max() for j in range(k))
        sep = min(d[np.ix_(lab == i, lab == j)].min() for i in range(k) for j in range(k) if i != j)
        m["dunn"] = sep / diam if diam else 0.0
        m["ptbiserial"] = float((db.mean() - dw.mean()) * math.sqrt(nw * nb / nt ** 2) / dv.std(ddof=1)) if nw else 0.0
        if k + 1 in wcss:
            m["hartigan"] = (w / wcss[k + 1] - 1) * (n - k - 1)
        m["mcclain"] = float(dw.mean() / db.mean()) if nw else 0.0
        if k + 1 in labs:
            l2 = labs[k + 1]
            s2 = (l2[:, None] == l2[None])[iu]
            den = dv[s2].mean() - dw.mean() if nw else 0.0
            m["frey"] = float((dv[~s2].mean() - db.mean()) / den) if den else math.inf
        if k - 1 in wcss and k + 1 in wcss:  # the usual definition (not Prism's: not verified)
            def diff(q):
                return (q - 1) ** (2 / p) * wcss[q - 1] - q ** (2 / p) * wcss[q]
            m["krzanowskiLai"] = abs(diff(k) / diff(k + 1)) if diff(k + 1) else math.inf
        out[k] = m
    return out


def _silhouette(d: np.ndarray, lab: np.ndarray, k: int) -> float:
    if k < 2:
        return 0.0
    n = len(lab)
    s = np.zeros(n)
    for i in range(n):
        own = lab == lab[i]
        if own.sum() == 1:
            continue
        a = d[i, own].sum() / (own.sum() - 1)
        b = min(d[i, lab == j].mean() for j in range(k) if j != lab[i])
        s[i] = (b - a) / max(a, b) if max(a, b) else 0.0
    return float(s.mean())


# metric -> (results key, rule): max, min, or Prism's difference rules (verified on its template)
OPTIMAL = {"Ball-Hall": ("ballHall", "diff"), "C index": ("cIndex", "min"), "Calinski-Harabasz": ("calinskiHarabasz", "max"),
           "Davies-Bouldin": ("daviesBouldin", "min"), "Dunn": ("dunn", "max"), "Frey": ("frey", "frey"),
           "Gamma": ("gamma", "max"), "Gap": ("gap", "gap"), "Gplus": ("gplus", "min"), "Hartigan": ("hartigan", "diff"),
           "Krzanowski-Lai": ("krzanowskiLai", "max"), "McClain-Rao": ("mcclain", "min"),
           "Ptbiserial": ("ptbiserial", "max"), "Ratkowsky": ("ratkowsky", "max"), "Silhouette": ("silhouetteScore", "max"),
           "Tau": ("tau", "max"), "Trace W": ("wcss", "diff2")}


def _optimal(models: dict[int, dict]) -> dict:
    ks = sorted(k for k in models if k >= 2)

    def val(k, key):
        m = models.get(k, {})
        v = m["gap"]["statistic"] if key == "gap" and "gap" in m else m.get(key)
        return v if isinstance(v, (int, float)) and math.isfinite(v) else None

    metrics = {}
    for name, (key, rule) in OPTIMAL.items():
        vals = {k: val(k, key) for k in ks if val(k, key) is not None}
        if not vals:
            continue
        best = None
        if rule in ("max", "min"):
            best = (max if rule == "max" else min)(vals, key=lambda k: vals[k])
        elif rule == "diff":  # the largest drop from the level before
            drops = {k: vals[k - 1] - vals[k] for k in vals if k - 1 in vals}
            best = max(drops, key=lambda k: drops[k]) if drops else None
        elif rule == "diff2":  # the largest second difference
            sec = {k: vals[k - 1] + vals[k + 1] - 2 * vals[k] for k in vals if k - 1 in vals and k + 1 in vals}
            best = max(sec, key=lambda k: sec[k]) if sec else None
        elif rule == "frey":  # the first level whose index is below 1
            best = next((k for k in sorted(vals) if vals[k] < 1.0), None)
        elif rule == "gap":  # the smallest k with Gap(k) >= Gap(k+1) - sd(k+1)
            best = next((k for k in sorted(vals) if k + 1 in vals and
                         vals[k] >= vals[k + 1] - models[k + 1]["gap"]["sd"]), max(vals, key=lambda k: vals[k]))
        if best is not None:
            metrics[name] = {"clusterCount": best, "value": vals[best]}
    votes: dict[int, int] = {}
    for m in metrics.values():
        votes[m["clusterCount"]] = votes.get(m["clusterCount"], 0) + 1
    count = max(votes, key=lambda k: (votes[k], -k)) if votes else (ks[0] if ks else 1)
    return {"optimalClusterCount": count, "metrics": dict(sorted(metrics.items()))}


def k_means(params: dict, columns, titles: list[str]) -> dict:
    """K-means clustering. Prism starts each k from one random partition (its random seed), and it
    settles on a local optimum at times; Refract keeps the best of 25 starts, so its clusters can
    be better than Prism's (lower WCSS). Given the same partition every result matches Prism but the
    gap statistic (random reference data sets) and Krzanowski-Lai (E-cluster)."""
    data = params.get("data") or {}
    calc = params.get("calc") or {}
    idx = [v["col"]["idx"] for v in data.get("variables", [])]
    n_total = max((len(columns[i]) for i in idx), default=0)
    rows = [r for r in range(n_total) if all(r < len(columns[i]) and _number(columns[i][r]) is not None for i in idx)]
    if len(rows) < 2 or not idx:
        return {"status": {"error": "NOT_ENOUGH_DATA", "warning": []}}
    if (calc.get("distance") or {}).get("type", "EUCLIDIAN") != "EUCLIDIAN":
        raise NotImplementedError("K-means with a distance other than Euclidean")
    raw = np.array([[_number(columns[i][r]) for i in idx] for r in rows])
    z = _transform(raw, calc.get("transform", "STANDARDIZE"), 0)
    n = len(z)
    cc = calc.get("clusterCount") or {}
    lo, hi = max(1, int(cc.get("min", 1))), min(n - 1, int(cc.get("max", 8)))
    seed = int((calc.get("randomSeed") or {}).get("value", 1))
    max_iter = int(calc.get("maxIterCount", 10))
    labs, iters, wcss = {}, {}, {}
    for k in range(lo, hi + 2 if hi + 1 < n else hi + 1):  # one more level for the difference indices
        labs[k], iters[k] = kmeans(z, k, seed + k, max_iter=max_iter)
        wcss[k] = _wcss(z, [np.flatnonzero(labs[k] == j).tolist() for j in range(k)])
    d = squareform(pdist(z))
    metrics = _metrics(z, d, labs, wcss) if calc.get("clusterMetrics", True) else {}
    total = float(((z - z.mean(0)) ** 2).sum())
    gaps = _gap(z, range(lo, hi + 2 if hi + 1 < n else hi + 1), wcss, seed)
    names = [titles[i] for i in idx]
    models = {}
    for k in range(lo, hi + 1):
        lab = labs[k]
        cent = np.array([z[lab == j].mean(0) for j in range(k)])
        m = {"status": "VALID", "iterationCount": iters[k], "wcss": wcss[k],
             "percentOfTotalVariation": 100 * wcss[k] / total, "percentOfExplainedVariation": 100 * (1 - wcss[k] / total),
             "silhouetteScore": _silhouette(d, lab, k), "gap": gaps[k]}
        m.update(metrics.get(k, {}))
        anova = {}
        for v, i in enumerate(idx):
            ref = {"col": {"idx": i, "title": titles[i]}}
            if k < 2:
                anova[f"var{i}"] = {"id": ref, "value": {"fTest": {"status": "UNKNOWN"}}}
                continue
            ssb = float(sum((lab == j).sum() * (cent[j, v] - z[:, v].mean()) ** 2 for j in range(k)))
            ssw = float(sum(((z[lab == j, v] - cent[j, v]) ** 2).sum() for j in range(k)))
            f = (ssb / (k - 1)) / (ssw / (n - k)) if ssw > 0 else math.inf
            from scipy import stats as ss

            pv = float(ss.f.sf(f, k - 1, n - k)) if math.isfinite(f) else 0.0
            anova[f"var{i}"] = {"id": ref, "value": {"ss": ssb, "df": float(k - 1), "ms": ssb / (k - 1), "fTest": {
                "status": "VALID", "f": f, "dfNumerator": float(k - 1), "dfDenominator": float(n - k),
                "pValue": {"value": pv, "level": 0.05, "isSignificant": pv < 0.05,
                           "state": "P_VALUE_EQUAL"}}}}
        m["anovaTable"] = anova
        m["clusters"] = [{"points": [{"id": int(q), "distance": float(np.sqrt(((z[q] - cent[j]) ** 2).sum()))}
                                     for q in np.flatnonzero(lab == j)],
                          "variables": {f"var{i}": {"id": {"col": {"idx": i, "title": titles[i]}},
                                                    "value": {"mean": float(cent[j, v]),
                                                              "ss": float(((z[lab == j, v] - cent[j, v]) ** 2).sum()),
                                                              "n": int((lab == j).sum())}}
                                        for v, i in enumerate(idx)}} for j in range(k)]
        models[str(k)] = m
    out = {"status": {"error": "VALID", "warning": []}, "models": models,
           "dataSummary": {"variablesCount": len(idx), "rowsTotal": n_total, "rowsSkipped": n_total - n,
                           "rowsAnalyzed": n},
           "optimalClustering": _optimal({int(k): v for k, v in models.items()})}
    ks = list(range(lo, hi + 1))
    every = list(range(len(titles)))

    def cell(i, r):
        v = columns[i][r] if r < len(columns[i]) else None
        return v

    tables = {"Clustered data": {
        "columns": [*(titles[i] for i in every), *(f"{k} clusters" for k in ks)], "row_titles": None,
        "rows": [[*(cell(i, r) for i in every), *(f"Cluster {labs[k][q] + 1}" for k in ks)] for q, r in enumerate(rows)]}}
    graph = params.get("graph") or {}
    if graph.get("elbowPlot", True):
        tables["Elbow plot"] = {"columns": ["X", "WCSS"], "row_titles": None, "rows": [[float(k), wcss[k]] for k in ks]}
    if graph.get("silhouettePlot", True):
        tables["Silhouette plot"] = {"columns": ["X", "Silhouette score"], "row_titles": None,
                                     "rows": [[float(k), models[str(k)]["silhouetteScore"]] for k in ks]}
    if graph.get("gapPlot", True):
        tables["Gap statistics"] = {"columns": ["X", "log(W) expected", "log(W) observed", "Statistic", "SD"],
                                    "row_titles": None,
                                    "rows": [[float(k), gaps[k]["logWExpected"], gaps[k]["logWObserved"],
                                              gaps[k]["statistic"], gaps[k]["sd"]] for k in ks]}
    if calc.get("clusterMetrics", True):
        cols = [("Calinski-Harabasz", "calinskiHarabasz"), ("Davies-Bouldin", "daviesBouldin"), ("C index", "cIndex"),
                ("Silhouette", "silhouetteScore"), ("Gap", "gap"), ("Ratkowsky", "ratkowsky"), ("Ball-Hall", "ballHall"),
                ("Gamma", "gamma"), ("Gplus", "gplus"), ("Tau", "tau"), ("Dunn", "dunn"), ("Ptbiserial", "ptbiserial"),
                ("Hartigan", "hartigan"), ("McClain-Rao", "mcclain"), ("Frey", "frey"), ("Krzanowski-Lai", "krzanowskiLai")]

        def mv(k, key):
            m = models[str(k)]
            v = m["gap"]["statistic"] if key == "gap" else m.get(key) if k >= 2 else None
            return v if isinstance(v, (int, float)) and math.isfinite(v) else None
        tables["Cluster metrics"] = {"columns": ["X", *(c for c, _ in cols)], "row_titles": None,
                                     "rows": [[float(k), *(mv(k, key) for _, key in cols)] for k in ks]}
    if (params.get("report") or {}).get("transformedData"):
        tables["Standardized data"] = {"columns": names, "row_titles": None, "rows": z.tolist()}
    out["_tables"] = tables
    return out


def _gap(z: np.ndarray, ks, wcss: dict[int, float], seed: int, b: int = 20) -> dict[int, dict]:
    """The gap statistic: log W against reference data sets drawn uniformly over the range of
    each principal component and rotated back (Tibshirani's second method: Prism's expected
    log W for one cluster, 8.676, against 8.681 by this method; its random draws are not
    reproduced)."""
    rng = np.random.default_rng(seed)
    mean = z.mean(0)
    _, _, vt = np.linalg.svd(z - mean, full_matrices=False)
    zp = (z - mean) @ vt.T
    lo, hi = zp.min(0), zp.max(0)
    refs = [rng.uniform(lo, hi, size=zp.shape) @ vt + mean for _ in range(b)]
    out = {}
    for k in ks:
        logs = []
        for ref in refs:
            lab, _ = kmeans(ref, k, seed + k, starts=3)
            logs.append(math.log(max(_wcss(ref, [np.flatnonzero(lab == j).tolist() for j in range(k)]), 1e-300)))
        e = float(np.mean(logs))
        obs = math.log(max(wcss[k], 1e-300))
        out[k] = {"statistic": e - obs, "sd": float(np.std(logs) * math.sqrt(1 + 1 / b)), "logWObserved": obs,
                  "logWExpected": e}
    return out
