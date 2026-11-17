"""E-ui-analyses: analyses created the way the Analyze dialog creates them
(refract.ui.document.Document.add_analysis + save) must open in Prism and be
computed by it, and Prism's values must match Refract's.

Usage:
  .venv/bin/python tools/ui_analysis_probe.py make <out_dir> <data.prism> [<contingency.prism>]
  .venv/bin/python -I tools/prism_auto.py <out_dir>/prism <out_dir>/*.prism --no-png
  .venv/bin/python tools/ui_analysis_probe.py compare <out_dir>
"""

from __future__ import annotations

import json
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

# (table kind, catalog key, option values, data sets or None)
CASES = [
    ("column", "column_stats", {}, None),
    ("column", "t_test", {"design": "UNPAIRED_T_TEST"}, [0, 1]),
    ("column", "t_test", {"design": "WELCH_T_TEST"}, [0, 2]),
    ("column", "t_test", {"design": "MANN_WHITNEY_TEST"}, [1, 2]),
    ("column", "t_test", {"design": "PAIRED_T_TEST"}, [0, 1]),
    ("column", "one_way", {"compare": "ALL_VS_ALL", "test": "TUKEY"}, None),
    ("column", "one_way", {"compare": "CONTROL_VS_ALL", "test": "DUNNET", "control": 1}, None),
    ("column", "one_way", {"design": "KRUSKAL_WALLIS_TEST", "compare": "ALL_VS_ALL", "test": "DUNN"}, None),
    ("column", "one_way", {"design": "BROWN_FORSYTHE_ANOVA", "compare": "ALL_VS_ALL", "test": "GAMES_HOWELL"}, None),
    ("column", "one_way", {"compare": "ALL_VS_ALL", "test": "FDR"}, None),
    ("column", "one_sample", {"design": "ONE_SAMPLE_T_TEST", "mu": 20.0}, None),
    ("column", "one_sample", {"design": "WILCOXON_SIGNED_RANK_TEST", "mu": 20.0}, None),
    ("column", "normality", {}, None),
    ("grouped", "two_way", {}, None),
    ("grouped", "two_way", {"compare": "COMPARE_CELLS_BY_COLUMNS_WITHIN_ROWS_SEPARATE_FAMILIES",
                            "test": "BONFERRONI_SIDAK"}, None),
    ("grouped", "two_way", {"design": "REPEATED_MEASURES_BY_COLS", "compare": "COMPARE_ROWS"}, None),
    ("grouped", "multiple_t", {}, [0, 1]),
    ("xy", "linear", {}, None),
    ("xy", "correlation", {"design": "NONPARAMETRIC"}, None),
    ("survival", "survival", {}, None),
    ("contingency", "contingency", {}, None),
    ("contingency", "contingency", {"method": "CHI_SQUARE_TEST"}, None),
]


def make(out: str, data: str, ct: str | None) -> int:
    from refract.render import qt
    from refract.ui.document import Document

    qt.ensure_app()
    os.makedirs(out, exist_ok=True)
    made = {}
    for src, name in ((data, "ui_data"), (ct, "ui_ct")):
        if not src:
            continue
        doc = Document.open(src)
        kinds = {t.kind: t for t in doc.project.tables if not t.is_result}
        from refract.stats import catalog

        titles = []
        for kind, key, values, sets in CASES:
            if kind not in kinds:
                continue
            a = doc.add_analysis(kinds[kind], catalog.by_key(key), values, sets)
            titles.append(a.title)
        path = os.path.join(out, f"{name}.prism")
        doc.save(path)
        made[path] = titles
        print(f"{path}: {len(titles)} analyses")
    with open(os.path.join(out, "cases.json"), "w") as f:
        json.dump(made, f, indent=1)
    return 0


def compare(out: str) -> int:
    from refract.formats import open_document
    from refract.stats import inputs as I

    with open(os.path.join(out, "cases.json")) as f:
        made = json.load(f)
    bad = 0
    for path, titles in made.items():
        stem = os.path.splitext(os.path.basename(path))[0]
        resaved = os.path.join(out, "prism", stem, "resaved.prism")
        if not os.path.exists(resaved):
            print(f"{stem}: no re-save from Prism")
            bad += 1
            continue
        p = open_document(resaved)
        by_title = {a.title: a for a in p.analyses}
        for t in titles:
            a = by_title.get(t)
            if a is None:
                print(f"  MISSING  {t}")
                bad += 1
                continue
            stored = a.results.get("content") or {}
            err = (stored.get("status") or {}).get("error")
            ours = I.recompute(p, a)
            d = [x for x in I.compare(stored, ours) if x.stored is not None and x.ours is not None]
            ag = sum(x.agrees for x in d)
            flag = "ok " if d and ag == len(d) and err == "VALID" else "DIFF"
            bad += flag != "ok "
            print(f"  {flag} {ag:4d}/{len(d):4d}  status={err}  {t}")
            for x in [x for x in d if not x.agrees][:3]:
                print(f"         {x.path}: Prism {x.stored!r} Refract {x.ours!r}")
    return 1 if bad else 0


if __name__ == "__main__":
    if sys.argv[1] == "make":
        raise SystemExit(make(sys.argv[2], sys.argv[3], sys.argv[4] if len(sys.argv) > 4 else None))
    raise SystemExit(compare(sys.argv[2]))
