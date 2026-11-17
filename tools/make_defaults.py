"""Build refract/stats/defaults.json: a starting parameter set per analysis
class for analyses created in the user interface (docs/ui-spec.md §6).

Usage: .venv/bin/python tools/make_defaults.py

The sets come from analyses Prism itself wrote into our own probe documents
(corpus/seeds, corpus/auto: generated data, no research data), so every key
Prism expects is present. Data-set references keep only their index (the
writer fills in title and uid, refract.formats.analysis_writer), free text is
dropped, and the options a new analysis should start from are set below.
"""

from __future__ import annotations

import copy
import glob
import json
import os
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)

from refract.formats.zipio import ZipArchive

SEEDS = {  # class -> seed file in corpus/seeds
    "ONE_WAY_ANOVA": "oneway_tukey_params.json",
    "TWO_WAY_ANOVA": "twoway_params.json",
    "ONE_SAMPLE_TESTS": "one_sample_tests_params.json",
    "NORMALITY_TESTS": "normality_tests_params.json",
    "CORRELATION": "correlation_params.json",
    "SIMPLE_LINEAR_REGRESSION": "simple_linear_regression_params.json",
    "SURVIVAL": "survival_params.json",
    "CONTINGENCY_TABLE": "contingency_table_params.json",
    "MULTIPLE_TWO_SAMPLE_TESTS": "multi_t_params.json",
    # the analyses the dialog offers since phase 8 (parameters Prism wrote, local corpus/seeds)
    "FREQUENCY_DISTRIBUTION": "frequency_distribution_params.json",
    "IDENTIFY_OUTLIERS": "identify_outliers_params.json",
    "BLAND_ALTMAN": "bland_altman_params.json",
    "ROC_CURVE": "roc_curve_params.json",
    "AREA_UNDER_CURVE": "area_under_curve_params.json",
    "SIMPLE_LOGISTIC_REGRESSION": "simple_logistic_regression_params.json",
    "NESTED_T_TEST": "nested_t_test_params.json",
    "ONE_WAY_NESTED_ANOVA": "one_way_nested_anova_params.json",
    "MULTIPLE_LINEAR_REGRESSION": "multiple_linear_regression_params.json",
    "MULTIPLE_LOGISTIC_REGRESSION": "multiple_logistic_regression_params.json",
    "MULTIPLE_COX_REGRESSION": "cox_regression_params.json",
    "PCA": "pca_params.json",
    "MULTI_FACTOR_ANOVA": "multi_factor_anova_params.json",
    # phase 8b: Prism's own parameters from the reference analyses made on Refract's sample tables
    "MULTIPLE_COMPARISONS": "p_values_params.json",
    "DEMING_REGRESSION": "deming_params.json",
    "SMOOTH_CURVE": "smooth_curve_params.json",
    "INTERPOLATION": "interpolation_params.json",
    "NONLINEAR_REGRESSION": "nonlinear_params.json",
    # tables made from tables (refract.stats.transforms, checked by tools/table_parity.py)
    "NORMALIZE": "normalize_params.json",
    "TRNSFORM": "transform_params.json",
    "REMOVE_BASELINE": "remove_baseline_params.json",
    "ROW_STATISTICS": "row_statistics_params.json",
    "TRANSPOSE": "transpose_params.json",
    "FIT_SPLINE_LOWESS": "fit_spline_params.json",
    "FRACTION_OF_TOTAL": "fraction_of_total_params.json",
    "PRUNE_ROWS": "prune_rows_params.json",
    "SELECT_TRANSFORM": "select_transform_params.json",
    "CHI2": "observed_expected_params.json",
    "EXTRACT_REARRANGE": "extract_rearrange_params.json",  # Prism's re-save of our probe (corpus/auto/er2)
    "HIERARCHICAL_CLUSTERING": "hclustering_params.json",  # Prism's re-saves of our probe (corpus/auto/clu1)
    "K_MEANS_CLUSTERING": "k_means_params.json",
    # the third reference set (corpus/manual/analysis_reference3_清单.md)
    "THREE_WAY_ANOVA": "three_way_params.json",
    "DESCRIPTIVE_STATISTICS": "mv_descriptive_params.json",
}
# parts the dialog builds from the table analysed (refract.stats.catalog.build): dropped, so that nothing of
# the documents the seeds came from (variable names, levels) is shipped
DROP = {"BLAND_ALTMAN": ("data",), "ROC_CURVE": ("data",), "PCA": ("data",),
        "MULTIPLE_LINEAR_REGRESSION": ("model",), "MULTIPLE_LOGISTIC_REGRESSION": ("model",),
        "MULTIPLE_COX_REGRESSION": ("model",), "MULTI_FACTOR_ANOVA": ("model", "postTests"),
        "INTERPOLATION": ("model",), "NONLINEAR_REGRESSION": ("model",),
        "SELECT_TRANSFORM": ("transforms",), "EXTRACT_REARRANGE": ("dataArrangement",),
        "HIERARCHICAL_CLUSTERING": ("data",), "K_MEANS_CLUSTERING": ("data",)}  # the model: refract.stats.equations
KEEP_MODEL = {"MULTIPLE_LINEAR_REGRESSION": ("regressionType", "weighting", "updateAutoReferenceLevels"),
              "MULTIPLE_LOGISTIC_REGRESSION": ("updateAutoReferenceLevels",),
              "MULTIPLE_COX_REGRESSION": ("treatUndefinedValuesAs", "tiesMethod", "updateAutoReferenceLevels")}
FROM_PROBES = {"COLUMN_STATISTICS", "T_TESTS_AND_NONPARAMETRIC"}  # first one in corpus/auto/*/prism/*/resaved.prism

START = {  # path -> value every new analysis of the class starts from
    "COLUMN_STATISTICS": {
        "calc/descriptiveStatistics/mean": True, "calc/descriptiveStatistics/minMaxRange": True,
        "calc/descriptiveStatistics/median": True, "calc/descriptiveStatistics/sum": False,
        "calc/descriptiveStatistics/geometricMean": False, "calc/descriptiveStatistics/geometricMeanCI": False,
    },
    "T_TESTS_AND_NONPARAMETRIC": {"experimentalDesign": "UNPAIRED_T_TEST", "options/significanceLevel": 0.05,
                                  "report/descriptiveStatistics": False, "report/effectSizes": False},
    "ONE_WAY_ANOVA": {"experimentalDesign": "ORDINARY_ANOVA"},
    "TWO_WAY_ANOVA": {"experimentalDesign": "ORDINARY_ANOVA"},
    "ONE_SAMPLE_TESTS": {"experimentalDesign": "ONE_SAMPLE_T_TEST", "calc/hypotheticalValue": 0.0},
    "CHI2": {"calc/outcomes": []},  # built from the table analysed
    "K_MEANS_CLUSTERING": {"report/anovaTable": False, "report/distances": False,  # as Prism's own sample
                           "report/initialCentroids": False},
}


def _set(d: dict, path: str, v) -> None:
    *head, last = path.split("/")
    for h in head:
        d = d.setdefault(h, {})
    d[last] = v


def clean(d):
    """Drop titles and uids of data-set and row references."""
    if isinstance(d, dict):
        out = {}
        for k, v in d.items():
            if k in ("col", "row") and isinstance(v, dict) and "idx" in v:
                out[k] = {"idx": v["idx"]}
            else:
                out[k] = clean(v)
        return out
    if isinstance(d, list):
        return [clean(v) for v in d]
    return d


def from_probes(cls: str) -> dict:
    for f in sorted(glob.glob(os.path.join(ROOT, "corpus", "auto", "*", "prism", "*", "resaved.prism"))):
        z = ZipArchive.open(f)
        doc = json.loads(z.read("document.json"))
        for a in doc["sheets"].get("analyses", []):
            if json.loads(z.read(f"analyses/{a}/sheet.json"))["analysisClass"] == cls:
                c = json.loads(z.read(f"analyses/{a}/parameters.json"))["content"]
                if "variableDesign" not in c:  # a Multiple-variables table's version: not the column one
                    return c
    raise KeyError(cls)


def main() -> int:
    out = {}
    for cls in sorted(set(SEEDS) | FROM_PROBES):
        if cls in SEEDS:
            with open(os.path.join(ROOT, "corpus", "seeds", SEEDS[cls])) as f:
                c = json.load(f)
        else:
            c = from_probes(cls)
        c = clean(copy.deepcopy(c))
        model = {k: c["model"][k] for k in KEEP_MODEL.get(cls, ()) if k in c.get("model", {})}
        for k in DROP.get(cls, ()):
            c.pop(k, None)
        if model:
            c["model"] = model
        for path, v in START.get(cls, {}).items():
            _set(c, path, v)
        out[cls] = c
    path = os.path.join(ROOT, "refract", "stats", "defaults.json")
    with open(path, "w") as f:
        json.dump(out, f, indent=1, sort_keys=False)
        f.write("\n")
    print(f"wrote {len(out)} classes to {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
