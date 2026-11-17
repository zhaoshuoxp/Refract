"""Multiple comparisons after one-way ANOVA, with Prism's result keys.

Prism enum (statistical.test) -> method:
  ordinary ANOVA, all pairs:   TUKEY, NEWMAN_KEULS, BONFERRONI_SIDAK, HOLM_SIDAK
  ordinary ANOVA, vs control:  DUNNET, BONFERRONI_SIDAK, HOLM_SIDAK
  multipleComparisons.type:    FDR (two-stage BKY q-values), NO_CORRECTION (Fisher LSD)
  Brown-Forsythe/Welch ANOVA:  GAMES_HOWELL, DUNNET_T3, TAMHANE_T2
  Kruskal-Wallis / Friedman:   DUNN
  repeated measures:           per-comparison SE from paired differences, df = n - 1
                               (sphericity assumed: pooled residual MS, df = (k-1)(n-1))
Mean differences are group i minus group j (swapDirection = false).
"""

from __future__ import annotations

import math

import numpy as np
from scipy import stats

from . import distributions as D
from .one_way import clean_groups, complete_rows


def _p(value: float, alpha: float) -> dict:
    return {"value": float(min(1.0, value)), "level": alpha, "isSignificant": bool(value < alpha), "state": "P_VALUE_EQUAL"}


def pairs(k: int, design: str, control: int = 0, selected: list[tuple[int, int]] | None = None
          ) -> list[tuple[int, int]]:
    if design == "SELECTED_VS_SELECTED":  # the pairs chosen, each lower index first (E-stats8)
        return [(min(a, b), max(a, b)) for a, b in (selected or []) if a != b and 0 <= a < k and 0 <= b < k]
    if design == "CONTROL_VS_ALL":
        return [(control, j) for j in range(k) if j != control]
    return [(i, j) for i in range(k) for j in range(i + 1, k)]


def _sidak(p: float, m: int) -> float:
    return 1 - (1 - p) ** m  # naive form, as Prism (differs from -expm1(m*log1p(-p)) by ~1e-16)


def _holm_sidak(ps: list[float]) -> list[float]:
    m = len(ps)
    order = np.argsort(ps)
    adj = [0.0] * m
    running = 0.0
    for rank, i in enumerate(order):
        running = max(running, _sidak(ps[i], m - rank))
        adj[i] = min(1.0, running)
    return adj


def _bky_qvalues(ps: list[float], q: float = 0.05) -> list[float]:
    """Prism's two-stage BKY q-values: the Benjamini-Hochberg adjusted P times
    m0/m * (1 + Q), where m0 = m - (rejections of stage 1, BH at Q/(1+Q)) for
    the chosen discovery level Q (verified against Prism 11, all-pairs designs)."""
    m = len(ps)
    order = sorted(range(m), key=lambda i: ps[i])
    bh = [0.0] * m
    running = 1.0
    for rank in range(m - 1, -1, -1):
        i = order[rank]
        running = min(running, ps[i] * m / (rank + 1))
        bh[i] = running
    r1 = sum(1 for v in bh if v <= q / (1 + q))
    m0 = m - r1 or m  # all rejected at stage 1: Prism uses m0 = m (two-way, verified)
    return [min(1.0, v * m0 / m * (1 + q)) for v in bh]


def adjust_family(raw: list, method: str, mc_type: str, alpha: float, k: int, means, prs: list,
                  lam=None, discovery_level: float = 0.05, q_level_quirk: bool = True,
                  individual: bool = False) -> tuple[dict, str, int]:
    """Apply a multiple-comparison method to one family.

    raw: [(i, j, diff, se, |t|, df, two-sided P)] in Prism's pair order; k =
    number of means in the family (studentized range); means indexed like i, j
    (Newman-Keuls ordering); lam: Dunnett correlation factors per pair.
    q_level_quirk: one-way ANOVA's Q/100 q-value level (two-way has none);
    individual: also report the unadjusted P (two-way ANOVA does).
    Returns (tests keyed by (i, j), method name, FDR discovery count)."""
    tests: dict = {}
    m = len(raw)
    level = 100 * (1 - alpha)
    disc = 0
    ql = discovery_level / 100 if q_level_quirk else discovery_level
    if mc_type == "NO_CORRECTION":
        for i, j, diff, se, t, df, p in raw:
            tc = stats.t.ppf(1 - alpha / 2, df)
            tests[(i, j)] = {"status": "VALID", "meansDifference": diff, "meansDifferenceSE": se,
                             "meansDifferenceCI": {"lower": diff - tc * se, "upper": diff + tc * se, "level": level},
                             "statistic": t, "df": df, "pValueIndividual": _p(p, alpha)}
        name = "No correction"
    elif mc_type == "FDR":
        qs = _bky_qvalues([r[6] for r in raw], discovery_level)
        disc = 0
        for (i, j, diff, se, t, df, p), q in zip(raw, qs, strict=True):
            # Prism 11 stores the q-value level divided by 100 (0.05 -> 0.0005)
            # and evaluates isDiscovery against that stored level, while
            # discoveryCount uses the real level (reproduced as observed)
            tests[(i, j)] = {"status": "VALID", "meansDifference": diff, "meansDifferenceSE": se, "statistic": t, "df": df,
                             "pValueIndividual": _p(p, alpha),
                             "qValue": {"value": float(q), "level": ql, "isDiscovery": bool(q <= ql)}}
            disc = disc + (q <= discovery_level)
        name = "Two-stage step-up FDR method (Benjamini, Krieger, and Yekutieli)"
    elif method in ("TUKEY", "GAMES_HOWELL"):
        for i, j, diff, se, t, df, _ in raw:
            q = t * math.sqrt(2)
            p = D.tukey_sf(q, k, df)
            qc = D.qtukey(1 - alpha, k, df) / math.sqrt(2)
            stat = q if method == "TUKEY" else t
            tests[(i, j)] = {"status": "VALID", "meansDifference": diff, "meansDifferenceSE": se,
                             "meansDifferenceCI": {"lower": diff - qc * se, "upper": diff + qc * se, "level": level},
                             "statistic": stat, "df": df, "pValueAdjusted": _p(p, alpha)}
        name = "Tukey" if method == "TUKEY" else "Games-Howell"
    elif method == "NEWMAN_KEULS":
        # q = t*sqrt(2) referred to the studentized range for r = number of
        # means spanned by the pair in rank order (r = 2: plain t test)
        # Step-down: a range is tested only if both ranges one mean wider
        # that contain it were tested and significant. Untested pairs get
        # statistic "undefined", P = 1 and the plain t interval, as Prism.
        pos = {int(g_): p_ for p_, g_ in enumerate(np.argsort(means, kind="stable"))}
        by_range = {}
        for row in raw:
            a, b = sorted((pos[row[0]], pos[row[1]]))
            by_range[(a, b)] = row
        sig_tested: dict[tuple[int, int], bool] = {}
        for r in range(k, 1, -1):
            for a in range(k - r + 1):
                b = a + r - 1
                parents = [pr for pr in ((a - 1, b), (a, b + 1)) if pr[0] >= 0 and pr[1] < k]
                tested = all(sig_tested.get(pr, False) for pr in parents)
                i, j, diff, se, t, df, _ = by_range[(a, b)]
                if tested:
                    q = t * math.sqrt(2)
                    p = D.tukey_sf(q, r, df)
                    qc = D.qtukey(1 - alpha, r, df) / math.sqrt(2)
                    sig_tested[(a, b)] = p < alpha
                    stat, pv = q, p
                else:
                    qc = stats.t.ppf(1 - alpha / 2, df)
                    sig_tested[(a, b)] = False
                    stat, pv = "undefined", 1.0
                tests[(i, j)] = {"status": "VALID", "meansDifference": diff, "meansDifferenceSE": se,
                                 "meansDifferenceCI": {"lower": diff - qc * se, "upper": diff + qc * se, "level": level},
                                 "statistic": stat, "df": df, "pValueAdjusted": _p(pv, alpha)}
        tests = {pr: tests[pr] for pr in prs}
        name = "Newman-Keuls"
    elif method in ("BONFERRONI_SIDAK", "TAMHANE_T2"):
        ac = 1 - (1 - alpha) ** (1 / m)
        for i, j, diff, se, t, df, p in raw:
            tc = stats.t.ppf(1 - ac / 2, df)
            tests[(i, j)] = {"status": "VALID", "meansDifference": diff, "meansDifferenceSE": se,
                             "meansDifferenceCI": {"lower": diff - tc * se, "upper": diff + tc * se, "level": level},
                             "statistic": t, "df": df, "pValueAdjusted": _p(_sidak(p, m), alpha)}
        name = "Bonferroni-Šídák" if method == "BONFERRONI_SIDAK" else "Tamhane T2"
    elif method == "HOLM_SIDAK":
        adj = _holm_sidak([r[6] for r in raw])
        for (i, j, diff, se, t, df, _), a in zip(raw, adj, strict=True):
            tests[(i, j)] = {"status": "VALID", "meansDifference": diff, "meansDifferenceSE": se, "statistic": t, "df": df,
                             "pValueAdjusted": _p(a, alpha)}
        name = "Holm-Šídák"
    elif method == "DUNNET_T3":
        for i, j, diff, se, t, df, _ in raw:
            # Prism evaluates T3 at the Welch df rounded to the nearest integer,
            # and reports no CI when the adjusted P is exactly 1
            dfi = float(math.floor(df + 0.5))
            p = D.smm_sf(t, m, dfi)
            if p >= 1.0:
                ci = {"lower": "undefined", "upper": "undefined", "level": level}
            else:
                c = D.smm_crit(alpha, m, dfi)
                ci = {"lower": diff - c * se, "upper": diff + c * se, "level": level}
            tests[(i, j)] = {"status": "VALID", "meansDifference": diff, "meansDifferenceSE": se,
                             "meansDifferenceCI": ci, "statistic": t, "df": df, "pValueAdjusted": _p(p, alpha)}
        name = "Dunnett T3"
    elif method == "DUNNET":
        crit: dict[float, float] = {}  # per df (pairs of a mixed-model fit have their own df)
        for i, j, diff, se, t, df, _ in raw:
            if df not in crit:
                crit[df] = D.dunnett_crit(alpha, lam, df)
            c = crit[df]
            tests[(i, j)] = {"status": "VALID", "meansDifference": diff, "meansDifferenceSE": se,
                             "meansDifferenceCI": {"lower": diff - c * se, "upper": diff + c * se, "level": level},
                             "statistic": t, "df": df, "pValueAdjusted": _p(D.dunnett_sf(t, lam, df), alpha)}
        name = "Dunnett"
    else:
        raise NotImplementedError(method)
    if individual:
        for i, j, *_rest, p in raw:
            t = tests[(i, j)]
            if "pValueIndividual" not in t:
                keys = list(t)
                pos = keys.index("pValueAdjusted") if "pValueAdjusted" in keys else len(keys)
                items = list(t.items())
                items.insert(pos, ("pValueIndividual", _p(p, alpha)))
                tests[(i, j)] = dict(items)
    return tests, name, disc


def compare(groups, method: str, design: str = "ALL_VS_ALL", kind: str = "ordinary", mc_type: str = "STATISTICAL",
            alpha: float = 0.05, control: int = 0, titles: list[str] | None = None, ms_error: float | None = None,
            df_error: float | None = None, discovery_level: float = 0.05, ls_fit=None,
            selected: list[tuple[int, int]] | None = None) -> dict:
    """kind: ordinary | welch | kruskal | friedman | rm. Returns Prism's
    multipleComparisons block (tests keyed by (i, j) instead of hashes);
    selected: the pairs of a SELECTED_VS_SELECTED design."""
    k = len(groups)
    titles = titles or [chr(65 + i) for i in range(k)]
    prs = pairs(k, design, control, selected)
    m = len(prs)
    tests: dict[tuple[int, int], dict] = {}
    if kind in ("ordinary", "welch", "rm"):
        paired_stats: dict = {}
        if kind == "rm":
            nmax = max(len(c) for c in groups)
            x = np.array([[c[s] if s < len(c) and c[s] is not None else np.nan for c in groups] for s in range(nmax)], float)
            full = x if np.isnan(x).any() else None  # mixed-model fit: pairs use the subjects with both values
            if full is not None:
                x = complete_rows(groups) if len(complete_rows(groups)) else x[:0]
            g = [x[:, c] for c in range(k)]
        else:
            g = clean_groups(groups)
        if kind == "rm" and full is not None:
            means = np.nanmean(full, axis=0)
            ns = (~np.isnan(full)).sum(axis=0)
            if ls_fit is not None:  # sphericity assumed, mixed-model fit: LS means and covariance (verified)
                means = np.asarray(ls_fit[0], float)
        else:
            means = np.array([a.mean() for a in g])
            ns = np.array([len(a) for a in g])
        if kind == "ordinary" and ms_error is None:
            big_n = ns.sum()
            ms_error = float(sum(((a - a.mean()) ** 2).sum() for a in g) / (big_n - k))
            df_error = float(big_n - k)
        raw = []
        for i, j in prs:
            diff = float(means[i] - means[j])
            if kind == "ordinary":
                se = math.sqrt(ms_error * (1 / ns[i] + 1 / ns[j]))
                df = df_error
            elif kind == "welch":
                vi, vj = g[i].var(ddof=1) / ns[i], g[j].var(ddof=1) / ns[j]
                se = math.sqrt(vi + vj)
                df = (vi + vj) ** 2 / (vi ** 2 / (ns[i] - 1) + vj ** 2 / (ns[j] - 1))
            elif ls_fit is not None:
                cv = ls_fit[1]
                se = math.sqrt(cv[i, i] + cv[j, j] - 2 * cv[i, j])
                df = float(ls_fit[2])
            elif ms_error is not None:  # repeated measures, sphericity assumed: pooled residual MS
                se = math.sqrt(ms_error * 2 / ns[i])
                df = float(df_error)
            else:  # repeated measures (Geisser-Greenhouse): SD of the paired differences
                if kind == "rm" and full is not None:
                    ok = ~np.isnan(full[:, i]) & ~np.isnan(full[:, j])
                    a, b = full[ok, i], full[ok, j]
                    paired_stats[(i, j)] = ((float(a.mean()), int(ok.sum())), (float(b.mean()), int(ok.sum())))
                    d = a - b
                    diff = float(d.mean())
                else:
                    d = g[i] - g[j]
                se = float(d.std(ddof=1) / math.sqrt(len(d)))
                df = float(len(d) - 1)
            t = abs(diff) / se
            raw.append((i, j, diff, se, t, df, float(2 * stats.t.sf(t, df))))
        lam = None
        if method == "DUNNET" and mc_type == "STATISTICAL":
            if paired_stats:  # mixed-model fit: paired n of the pair vs the control's n (closest rule found;
                # exact for 4 of 10 parity sets, findings.md)
                lam = [math.sqrt(paired_stats.get((i, j), ((0, ns[j]), (0, ns[j])))[0][1]
                                 / (paired_stats.get((i, j), ((0, ns[j]), (0, ns[j])))[0][1] + ns[control])) for i, j in prs]
            else:
                lam = [math.sqrt(ns[j] / (ns[j] + ns[control])) for _, j in prs]
        tests, name, disc = adjust_family(raw, method, mc_type, alpha, k, means, prs, lam, discovery_level)
    elif kind in ("kruskal", "friedman"):
        if kind == "kruskal":
            g = clean_groups(groups)
            allv = np.concatenate(g)
            ranks = stats.rankdata(allv)
            idx = np.cumsum([0] + [len(a) for a in g])
            rbar = [ranks[idx[c]:idx[c + 1]].mean() for c in range(k)]
            ns = [len(a) for a in g]
            means = rbar
            big_n = len(allv)
            _, tc = np.unique(allv, return_counts=True)
            var = big_n * (big_n + 1) / 12 - float((tc ** 3 - tc).sum()) / (12 * (big_n - 1))
            for i, j in prs:
                diff = float(rbar[i] - rbar[j])
                z = abs(diff) / math.sqrt(var * (1 / ns[i] + 1 / ns[j]))
                p = 2 * stats.norm.sf(z)
                tests[(i, j)] = {"status": "VALID", "rankMeansDifference": diff, "statistic": z, "pValueAdjusted": _p(p * m, alpha)}
        else:
            x = complete_rows(groups)
            n = x.shape[0]
            r = np.apply_along_axis(stats.rankdata, 1, x)
            rbar = r.mean(axis=0)
            means, ns = rbar, [n] * k
            for i, j in prs:
                diff = float(rbar[i] - rbar[j])
                z = abs(diff) / math.sqrt(k * (k + 1) / (6 * n))
                p = 2 * stats.norm.sf(z)
                tests[(i, j)] = {"status": "VALID", "rankSumsDifference": diff, "statistic": z, "pValueAdjusted": _p(p * m, alpha)}
        name = "Dunn"
    else:
        raise ValueError(kind)
    # each comparison carries its two samples (mean, or mean rank for Dunn; n)
    ps = paired_stats if kind in ("ordinary", "welch", "rm") else {}
    for (i, j), t in tests.items():
        (m1, n1), (m2, n2) = ps.get((i, j), ((float(means[i]), int(ns[i])), (float(means[j]), int(ns[j]))))
        t["sample1"] = {"id": {"col": {"title": titles[i], "idx": i}}, "value": {"mean": m1, "n": n1}}
        t["sample2"] = {"id": {"col": {"title": titles[j], "idx": j}}, "value": {"mean": m2, "n": n2}}
    if mc_type == "FDR":
        return {"status": "VALID", "method": name, "comparisonCount": len(tests), "discoveryCount": int(disc), "tests": tests}
    sig = sum(1 for t in tests.values() if (t.get("pValueAdjusted") or t.get("pValueIndividual"))["isSignificant"])
    return {"status": "VALID", "method": name, "comparisonCount": len(tests), "significantCount": sig, "tests": tests}


def compact_letters(means: list[float], different: set[tuple[int, int]]) -> list[str]:
    """Compact letter display: groups sharing a letter do not differ (insert-and-absorb, Piepho 2004);
    letters A, B, ... from the largest mean down; each group's letters space-separated (E-stats8:
    Prism's one-way ANOVA, all pairs compared)."""
    k = len(means)
    cols: list[set[int]] = [set(range(k))]
    for i, j in sorted(different):
        nxt = []
        for c in cols:
            if i in c and j in c:
                nxt += [c - {i}, c - {j}]
            else:
                nxt.append(c)
        cols = [c for c in nxt if not any(c < o for o in nxt)]  # absorb columns inside another
        cols = [c for n_, c in enumerate(cols) if c not in cols[:n_]]
    order = sorted(range(k), key=lambda g: -means[g])
    rank = {g: r for r, g in enumerate(order)}
    cols.sort(key=lambda c: (min(rank[g] for g in c), sorted(rank[g] for g in c)))
    names = [chr(65 + n) if n < 26 else chr(65 + n // 26 - 1) + chr(65 + n % 26) for n in range(len(cols))]
    return [" ".join(nm for nm, c in zip(names, cols, strict=True) if g in c) for g in range(k)]

