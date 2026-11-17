"""Add an analysis sheet to a .prism bundle.

Prism recomputes analyses on open from parameters.json (phase-0 E3 and the
recalculation batch), so a new analysis needs only its sheet, parameters,
constants and an empty results object. Prism writes the results and result
views itself when it saves.
"""

from __future__ import annotations

import string

from . import bundle as B
from .bundle_builder import new_token, new_uid
from .zipio import ZipArchive

SCHEMA = {
    "T_TESTS_AND_NONPARAMETRIC": "analyses/two_sample_tests/parameters.schema.json",
    "ONE_SAMPLE_TESTS": "analyses/one_sample_tests/parameters.schema.json",
    "COLUMN_STATISTICS": "analyses/column_statistics/parameters.schema.json",
    "FREQUENCY_DISTRIBUTION": "analyses/frequency_distribution/parameters.schema.json",
    "TWO_WAY_ANOVA": "analyses/two_way_anova/parameters.schema.json",
    "MULTI_FACTOR_ANOVA": "analyses/n_way_anova/parameters.schema.json",
    "ONE_WAY_ANOVA": "analyses/one_way_anova/parameters.schema.json",
    "MULTIPLE_TWO_SAMPLE_TESTS": "analyses/multiple_two_sample_tests/parameters.schema.json",
    "NORMALITY_TESTS": "analyses/normality_tests/parameters.schema.json",
    "DESCRIPTIVE_STATISTICS": "analyses/descriptive_statistics/parameters.schema.json",
    "SURVIVAL": "analyses/survival/parameters.schema.json",
    "CORRELATION": "analyses/correlation/parameters.schema.json",
    "SIMPLE_LINEAR_REGRESSION": "analyses/simple_linear_regression/parameters.schema.json",
    "NONLINEAR_REGRESSION": "analyses/nonlinear_regression/parameters.schema.json",
    "CONTINGENCY_TABLE": "analyses/contingency/parameters.schema.json",
    "NORMALIZE": "analyses/normalize/parameters.schema.json",
    "TRNSFORM": "analyses/transform/parameters.schema.json",
    "REMOVE_BASELINE": "analyses/remove_baseline/parameters.schema.json",
    "ROW_STATISTICS": "analyses/row_statistics/parameters.schema.json",
    "TRANSPOSE": "analyses/transpose/parameters.schema.json",
    "FRACTION_OF_TOTAL": "analyses/fraction_of_total/parameters.schema.json",
    "CHI2": "analyses/compare_observed_distribution_with_expected/parameters.schema.json",
    "PRUNE_ROWS": "analyses/prune_rows/parameters.schema.json",
    "SELECT_TRANSFORM": "analyses/select_transform/parameters.schema.json",
    "BLAND_ALTMAN": "analyses/bland_altman/parameters.schema.json",
    "IDENTIFY_OUTLIERS": "analyses/identify_outliers/parameters.schema.json",
    "MULTIPLE_COX_REGRESSION": "analyses/cox_regression/parameters.schema.json",
    "SIMPLE_LOGISTIC_REGRESSION": "analyses/simple_logistic_regression/parameters.schema.json",
    "FIT_SPLINE_LOWESS": "analyses/fit_spline/parameters.schema.json",
    "ROC_CURVE": "analyses/roc_curve/parameters.schema.json",
    "AREA_UNDER_CURVE": "analyses/area_under_curve/parameters.schema.json",
    "PCA": "analyses/pca/parameters.schema.json",
    "MULTIPLE_LINEAR_REGRESSION": "analyses/multiple_linear_regression/parameters.schema.json",
    "MULTIPLE_LOGISTIC_REGRESSION": "analyses/multiple_logistic_regression/parameters.schema.json",
    "ONE_WAY_NESTED_ANOVA": "analyses/nested_one_way_anova/parameters.schema.json",
    "NESTED_T_TEST": "analyses/nested_t_test/parameters.schema.json",
    "MULTIPLE_COMPARISONS": "analyses/analyze_stack_of_p_values/parameters.schema.json",
    "DEMING_REGRESSION": "analyses/deming_regression/parameters.schema.json",
    "INTERPOLATION": "analyses/interpolation/parameters.schema.json",
    "SMOOTH_CURVE": "analyses/smooth/parameters.schema.json",
    "HIERARCHICAL_CLUSTERING": "analyses/hclustering/parameters.schema.json",
    "K_MEANS_CLUSTERING": "analyses/k_means/parameters.schema.json",
    "EXTRACT_REARRANGE": "analyses/extract_rearrange/parameters.schema.json",
    "THREE_WAY_ANOVA": "analyses/three_way_anova/parameters.schema.json",
}


# parameters.json "version" Prism 11.1 writes per class (local corpus). Older
# versions are migrated on open, and a migration can change meaning:
# MULTIPLE_TWO_SAMPLE_TESTS 0.0.0 swaps EQUAL_SD and UNEQUAL_SD (verified).
VERSION = {
    "T_TESTS_AND_NONPARAMETRIC": "0.0.1",
    "ONE_WAY_ANOVA": "0.0.1",
    "TWO_WAY_ANOVA": "0.0.1",
    "MULTIPLE_TWO_SAMPLE_TESTS": "0.0.1",
    "REMOVE_BASELINE": "0.0.1",
    "SURVIVAL": "0.0.2",
    "MULTIPLE_COX_REGRESSION": "0.1.0",
    "MULTIPLE_LINEAR_REGRESSION": "0.1.0",
    "MULTIPLE_LOGISTIC_REGRESSION": "0.1.0",
    "ONE_WAY_NESTED_ANOVA": "0.0.1",
    "NESTED_T_TEST": "0.0.1",
    "EXTRACT_REARRANGE": "0.0.1",
    "THREE_WAY_ANOVA": "0.0.1",
}


# sheet.json minRequiredVersion Prism writes for analyses added in later versions (local corpus)
MIN_VERSION = {"HIERARCHICAL_CLUSTERING": (10, 3, 0, 0), "K_MEANS_CLUSTERING": (10, 3, 0, 0)}


def _fill_control(content: dict, inputs: list[dict]) -> None:
    """Point postTests...controlID at the input data set with that idx
    (uid and title must name a real data set, or Prism resets the post tests)."""
    try:
        col = content["postTests"]["pairwiseTests"]["pairwiseDesign"]["controlID"]["col"]
    except (KeyError, TypeError):
        return
    i = col.get("idx", 0)
    if 0 <= i < len(inputs):
        col.update(idx=i, title=inputs[i]["title"], uid=inputs[i]["uid"])


def _fill_x_control(content: dict, table: dict, set_title) -> None:
    """CORRELATION: a pairwise control with col idx -1 is the X data set, and
    the selected pair must name real data sets (as Prism writes them)."""
    pd_ = content.get("pairwiseDesign")
    if not isinstance(pd_, dict) or "xDataSet" not in table:
        return
    xu = table["xDataSet"]
    x_ref = {"idx": -1, "title": set_title(xu), "uid": xu}
    col = pd_.get("controlID", {}).get("col")
    if isinstance(col, dict) and col.get("idx") == -1:
        pd_["controlID"]["col"] = dict(x_ref)
    if "selectedPairID" in pd_ and table.get("dataSets"):
        y0 = table["dataSets"][0]
        pd_["selectedPairID"] = [{"col": dict(x_ref)}, {"col": {"idx": 0, "title": set_title(y0), "uid": y0}}]


def _fill_col_refs(content, uids: list[str], set_title) -> None:
    """Complete every data-set reference {"col": {"idx": i, ...}} (i >= 0) in
    the parameters with that data set's title and uid (Prism resets
    references that do not name a real data set)."""
    if isinstance(content, dict):
        col = content.get("col")
        if isinstance(col, dict) and isinstance(col.get("idx"), int) and 0 <= col["idx"] < len(uids) \
                and "uid" not in col:  # the post-test control is already resolved (_fill_control)
            u = uids[col["idx"]]
            col.update(title=set_title(u), uid=u)
        for v in content.values():
            _fill_col_refs(v, uids, set_title)
    elif isinstance(content, list):
        for v in content:
            _fill_col_refs(v, uids, set_title)


def add_analysis(arc: ZipArchive, analysis_class: str, content: dict, data_sheet_uid: str,
                 dataset_uids: list[str] | None = None, title: str | None = None,
                 schema_id: str | None = None) -> str:
    doc = B.get_json(arc, "document.json")
    sheet = B.get_json(arc, f"data/sheets/{data_sheet_uid}/sheet.json")
    t = sheet["table"]
    sets = dataset_uids if dataset_uids is not None else list(t["dataSets"])

    def set_title(u):
        j = B.get_json(arc, f"data/sets/{u}.json")
        ti = j.get("title")
        return ti.get("string") if isinstance(ti, dict) else (ti or "")

    inputs = [{"uid": u, "title": set_title(u), "idx": string.ascii_uppercase[t["dataSets"].index(u)]} for u in sets]
    _fill_control(content, inputs)
    _fill_x_control(content, t, set_title)
    _fill_col_refs(content, list(t["dataSets"]), set_title)
    fens = [B.get_json(arc, f"analyses/{a}/sheet.json")["fenID"] for a in doc["sheets"].get("analyses", [])
            if arc.has(f"analyses/{a}/sheet.json")]
    uid = new_uid()
    title = title or analysis_class.replace("_", " ").title()
    base = f"analyses/{uid}"
    B.put_json(arc, f"{base}/sheet.json", {
        "@class": "AnalysisSheet", "uid": uid, "fenID": (max(fens) + 1) if fens else 0, "title": title,
        "$id": "analyses/sheet.schema.json", "analysisClass": analysis_class, "isAllDataAnalyzed": dataset_uids is None,
        "minRequiredVersion": dict(zip(("major", "minor", "subminor", "build"), MIN_VERSION.get(analysis_class, (0, 0, 0, 0)))),
        "resultSheets": [], "inputDataSets": inputs,
        "inputSheets": [{"uid": data_sheet_uid, "title": sheet.get("title", "")}],
    })
    B.put_json(arc, f"{base}/parameters.json", {
        "@class": "AnalysisParameters", "$id": schema_id or SCHEMA[analysis_class], "version": VERSION.get(analysis_class, "0.0.0"), "content": content})
    arc.put(f"{base}/parameters.dt", new_token().encode())
    B.put_json(arc, f"{base}/results.json", {"@class": "AnalysisResults"})
    B.put_json(arc, f"{base}/constants.json", {"@class": "AnalysisConstants", "version": "0.0.0"})

    def upd(d):
        sheets = d["sheets"]
        if "analyses" not in sheets:
            d["sheets"] = {k: v for k, v in [("graphs", sheets.get("graphs"))] if v is not None} | {"analyses": []} | {
                k: v for k, v in sheets.items() if k != "graphs"}
        d["sheets"]["analyses"].append(uid)
        d["sheetAttributesMap"][uid] = {"title": title}
    B.edit_json(arc, "document.json", upd)
    return uid


def set_parameters(arc: ZipArchive, uid: str, content: dict) -> None:
    """Replace an analysis's parameter content (Prism recomputes on open) and
    empty its stored results so stale values are never shown."""
    base = f"analyses/{uid}"
    B.edit_json(arc, f"{base}/parameters.json", lambda p: p.__setitem__("content", content))
    arc.put(f"{base}/parameters.dt", new_token().encode())
    B.put_json(arc, f"{base}/results.json", {"@class": "AnalysisResults"})


def remove_analysis(arc: ZipArchive, uid: str) -> None:
    """Remove an analysis sheet added earlier (one with no result sheets)."""
    for n in [n for n in arc.names() if n.startswith(f"analyses/{uid}/")]:
        arc.remove(n)

    def upd(d):
        lst = d["sheets"].get("analyses", [])
        if uid in lst:
            lst.remove(uid)
        d.get("sheetAttributesMap", {}).pop(uid, None)
    B.edit_json(arc, "document.json", upd)
