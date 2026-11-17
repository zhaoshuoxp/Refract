"""Creating analyses (docs/ui-spec.md §6): the catalog's parameter sets, the
inputs taken from tables, the Analyze and parameter dialogs, results that
follow data edits, and saving analyses into the bundle."""

import json
import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from refract.model.document import DataSet, DataTable, Project
from refract.render import qt
from refract.stats import catalog
from refract.stats import inputs as INP

ROOT = os.path.join(os.path.dirname(__file__), "..")
SAMPLE = os.path.join(ROOT, "corpus", "manual", "batch5_samples.prism")


@pytest.fixture(scope="module", autouse=True)
def app(tmp_path_factory):
    os.environ["REFRACT_SETTINGS"] = str(tmp_path_factory.mktemp("settings") / "refract.ini")
    return qt.ensure_app()


def _column():
    sets = [DataSet("Ctrl", [["10", "12", "11", "13", "9"]], uid="u0"),
            DataSet("Low", [["14", "15", "13", "16", ""]], uid="u1"),
            DataSet("High", [["20", "22", "19", "21", "23"]], uid="u2")]
    t = DataTable("T", "column", "y_single", sets, 5, sheet_uid="s0")
    return Project("prism", tables=[t]), t


def test_every_choice_builds_and_reads_back():
    for _group, choices in catalog.CATALOG:
        for c in choices:
            assert c.analysis_class in catalog.DEFAULTS
            v = catalog.initial(c)
            content = catalog.build(c, v)
            assert catalog.options_of(c, content) == v, c.key
    c = catalog.by_key("one_way")
    v = {**catalog.initial(c), "design": "KRUSKAL_WALLIS_TEST", "compare": "ALL_VS_ALL", "test": "TUKEY"}
    content = catalog.build(c, v)  # Tukey does not follow a rank test: Dunn instead
    assert content["postTests"]["pairwiseTests"]["multipleComparisons"]["statistical"]["test"] == "DUNN"
    none = catalog.build(c, {**v, "compare": "NONE"})
    assert none["postTests"]["type"] == "NO_TESTS"


def test_defaults_hold_no_data_set_names():
    def refs(d):
        if isinstance(d, dict):
            for k, v in d.items():
                if k in ("col", "row") and isinstance(v, dict):
                    yield v
                yield from refs(v)
        elif isinstance(d, list):
            for v in d:
                yield from refs(v)

    for content in catalog.DEFAULTS.values():
        assert all(set(r) <= {"idx"} for r in refs(content))  # the writer fills in titles and uids


def test_gather_columns_and_entered_means():
    _p, t = _column()
    i = INP.gather("ONE_WAY_ANOVA", t)
    assert i.titles == ["Ctrl", "Low", "High"] and i.columns[1] == [14.0, 15.0, 13.0, 16.0]  # trailing blank dropped
    t.datasets[0].cell_attributes[(0, 1)] = {"EXCLUDED"}
    assert INP.gather("T_TESTS_AND_NONPARAMETRIC", t, [0, 2]).columns[0] == [10.0, None, 11.0, 13.0, 9.0]
    sd = DataTable("G", "grouped", "y_sd_n", [DataSet("A", [["1", "2"], ["0.1", "0.2"], ["3", "3"]])], 2)
    assert INP.gather("TWO_WAY_ANOVA", sd).columns == [[[1.0, 2.0]]]  # the means only
    with pytest.raises(NotImplementedError):
        INP.gather("PLOT_FUNCTION", t)
    mv = DataTable("M", "multivariable", "y_single", [DataSet("Age", [["30", "41"]]), DataSet("Sex", [["F", " M"]])], 2)
    assert INP.gather("PCA", mv).columns == [[30.0, 41.0], ["F", "M"]]  # every variable: numbers, or texts


def test_add_analysis_follows_edits_and_undo():
    from refract.ui.document import Document

    project, t = _column()
    doc = Document(project)
    changed = []
    doc.sheetsChanged.connect(lambda: changed.append("sheets"))
    doc.analysisChanged.connect(lambda a: changed.append(a.title))
    a = doc.add_analysis(t, catalog.by_key("t_test"), {"design": "WELCH_T_TEST"}, [0, 2])
    assert a.title == "Welch's t test of T" and project.analyses == [a] and changed == ["sheets"]
    assert a.input_datasets == ["u0", "u2"] and doc.is_new(a)
    t0 = doc.results(a)["welchTTestModel"]["welchTTest"]["t"]
    doc.set_cell(t, t.datasets[2], 0, 0, "40")  # the analysed data changed: recomputed
    assert changed[-1] == a.title and doc.results(a)["welchTTestModel"]["welchTTest"]["t"] != t0
    doc.set_parameters(a, catalog.by_key("t_test"), {"design": "MANN_WHITNEY_TEST"})
    assert "mannWhitneyTestModel" in doc.results(a)
    b = doc.add_analysis(t, catalog.by_key("t_test"), {"design": "WELCH_T_TEST"}, [0, 1])
    assert b.title == "Welch's t test of T (2)"
    doc.undo.undo()
    doc.undo.undo()
    assert project.analyses == [a] and "welchTTestModel" in doc.results(a)
    doc.undo.undo()
    doc.undo.undo()
    assert project.analyses == [] and not doc.modified


def test_errors_are_reported_not_raised():
    from refract.ui.document import Document

    project, t = _column()
    doc = Document(project)
    a = doc.add_analysis(t, catalog.by_key("t_test"), {}, [0])  # needs two columns
    assert set(doc.results(a)) == {"error"}


def test_analyze_dialog_checks_the_data_sets():
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QDialogButtonBox

    from refract.ui.analyze import AnalyzeDialog, ParametersDialog

    _p, t = _column()
    d = AnalyzeDialog(t)
    ok = d.buttons.button(QDialogButtonBox.Ok)
    assert d.choice().key == "column_stats" and ok.isEnabled()
    d.select("t_test")
    assert not ok.isEnabled() and "exactly 2" in d.note.text()
    d.set_checked([0, 2])
    assert ok.isEnabled() and d.selected_sets() == [0, 2]
    d.select("two_way")  # a grouped analysis: not for a column table
    assert d.choice() is None or d.choice().key != "two_way"
    disabled = [d.tree.topLevelItem(1).child(k).isDisabled() for k in range(d.tree.topLevelItem(1).childCount())]
    assert all(disabled)
    assert d.tree.topLevelItem(0).child(0).flags() & Qt.ItemIsEnabled

    p = ParametersDialog(catalog.by_key("one_way"), t, [0, 1, 2])
    assert p.widgets["test"].count() == 5 and not p.widgets["control"].isEnabled()
    p.set_value("design", "KRUSKAL_WALLIS_TEST")
    assert [p.widgets["test"].itemData(k) for k in range(p.widgets["test"].count())] == ["DUNN"]
    p.set_value("design", "ORDINARY_ANOVA")
    p.set_value("compare", "CONTROL_VS_ALL")
    assert p.widgets["control"].isEnabled() and p.value("test") == "DUNNET"
    p.set_value("control", 2)
    v = p.values()
    assert v["control"] == 2 and v["compare"] == "CONTROL_VS_ALL"
    again = ParametersDialog(catalog.by_key("one_way"), t, [0, 1, 2], v)
    assert again.values() == v


def _need_sample():
    if not os.path.exists(SAMPLE):
        pytest.skip("Prism sample not present")


def test_window_analyze_and_results_sheet():
    _need_sample()
    from refract.ui.document import Document
    from refract.ui.main_window import MainWindow
    from refract.ui.views import ResultView

    w = MainWindow(Document.open(SAMPLE))

    def stored():
        return next(it for it in w.sheet_items() if it.data(0, 0x0100) == ("results", 0))

    w.nav.setCurrentItem(stored())
    v = w.current_view()
    assert v.tab_names() == ["Summary", "Hazard ratios", "Data summary", "Compare (37/37)", "All values", "Parameters"]
    assert v.source.isVisibleTo(v) and v.source.currentData() == "stored" and "37 of 37" in v.info.text()
    v.source.setCurrentIndex(1)  # Refract's results instead of Prism's stored ones
    assert v.tab_names()[0] == "Summary" and v.source.currentData() == "refract"
    summary = v.page("Summary")
    rows = [summary.item(r, 0).text().strip() for r in range(summary.rowCount()) if summary.item(r, 0)]
    assert rows[:3] == ["Analysis", "Table analyzed", "Data sets analyzed"] and "P value" in rows
    summary.selectAll()
    summary.copy()
    from PySide6.QtWidgets import QApplication

    assert "Table analyzed\tSurvival: Two groups" in QApplication.clipboard().text()
    assert w.a_analyze.isEnabled()  # analyses the table the result reads
    col = w.doc.project.tables[1]
    a = w.analyze(col, "one_way", {"compare": "ALL_VS_ALL", "test": "TUKEY"})
    v = w.current_view()
    assert isinstance(v, ResultView) and v.analysis is a and not v.source.isVisibleTo(v)
    assert v.tab_names() == ["Summary", "ANOVA table", "Multiple comparisons", "Descriptive statistics",
                             "All values", "Parameters"]
    assert w.nav.topLevelItem(2).text(0) == "Results  (2)"
    assert w.a_params.isEnabled()
    surv = w.doc.project.tables[3]
    w.doc.set_cell(surv, surv.datasets[0], 0, 0, "0")  # the stored survival results are now out of date
    w.nav.setCurrentItem(stored())
    assert "Compare" not in " ".join(w.current_view().tab_names())
    assert "changed since" in w.current_view().info.text() and not w.current_view().source.isVisibleTo(w.current_view())
    w.doc.undo.undo()
    w.doc.undo.undo()  # the new analysis goes again
    assert w.nav.topLevelItem(2).text(0) == "Results  (1)"


def test_analyses_saved_into_the_bundle(tmp_path):
    _need_sample()
    from refract.formats import open_document
    from refract.formats.zipio import ZipArchive
    from refract.ui.document import Document

    doc = Document.open(SAMPLE)
    col = doc.project.tables[1]
    a = doc.add_analysis(col, catalog.by_key("one_way"),
                         {"compare": "CONTROL_VS_ALL", "test": "DUNNET", "control": 1}, [0, 1, 2])
    out = tmp_path / "a.prism"
    touched = doc.save(str(out))
    assert "document.json" in touched and a.uid
    z = ZipArchive.open(str(out))
    sheet = json.loads(z.read(f"analyses/{a.uid}/sheet.json"))
    assert sheet["analysisClass"] == "ONE_WAY_ANOVA" and sheet["title"] == a.title
    params = json.loads(z.read(f"analyses/{a.uid}/parameters.json"))["content"]
    ctl = params["postTests"]["pairwiseTests"]["pairwiseDesign"]["controlID"]["col"]
    assert ctl["idx"] == 1 and ctl["title"] == "Placebo" and ctl["uid"] == col.datasets[1].uid
    again = open_document(str(out))
    b = next(x for x in again.analyses if x.uid == a.uid)
    assert INP.source(again, b)[0].title == col.title  # Refract computes it after reopening too
    assert "ordinaryAnovaModel" in INP.recompute(again, b)
    # parameter edits of a stored analysis are written back; its stale results emptied
    stored = doc.project.analyses[0]
    doc.set_parameters(stored, catalog.by_key("survival"), {})
    stored.parameters["content"]["calc"]["ciLevel"] = 90.0
    touched = doc.save(str(out))
    assert touched == [f"analyses/{stored.uid}/parameters.json"]
    z = ZipArchive.open(str(out))
    assert json.loads(z.read(f"analyses/{stored.uid}/parameters.json"))["content"]["calc"]["ciLevel"] == 90.0
    assert json.loads(z.read(f"analyses/{stored.uid}/results.json")) == {"@class": "AnalysisResults"}
    doc.undo.undo()  # back to the original parameters
    doc.undo.undo()  # and the new analysis removed again
    doc.save(str(out))
    names = ZipArchive.open(str(out)).names()
    assert not any(n.startswith(f"analyses/{a.uid}/") for n in names)
    assert a.uid not in json.loads(ZipArchive.open(str(out)).read("document.json"))["sheets"]["analyses"]


def test_new_dialog_analyses_computed_from_tables():
    """The analyses the dialog offers since phase 8 are built from the table
    analysed (the data sets they name, a Multiple-variables table's
    variables and their kinds) and computed (E-stats8: each matched Prism
    value for value on the sample tables, the multifactor ANOVA aside)."""
    from refract.model import templates as T
    from refract.ui.document import Document

    doc = Document.new()
    col = doc.add_table(T.make("column", "C", sample=True), with_graph=False)
    xy = doc.add_table(T.make("xy", "X", sample=True), with_graph=False)
    nest = doc.add_table(T.make("nested", "N", sample=True), with_graph=False)
    mv = doc.add_table(T.make("multivariable", "MV", sample=True), with_graph=False)
    plan = [(col, "frequency", {}, None), (col, "outliers", {}, None), (col, "bland_altman", {}, [0, 2]),
            (col, "roc", {}, [0, 1]), (xy, "auc", {}, None), (nest, "nested_t", {}, [0, 1]),
            (mv, "mv_linear", {"y": 2}, None), (mv, "pca", {}, [0, 1, 2]), (mv, "nway", {"y": 2}, None),
            (mv, "extract", {"fmt": "COLUMN", "y": 0, "rows": 3}, None)]
    for t, key, vals, sets in plan:
        a = doc.add_analysis(t, catalog.by_key(key), vals, sets)
        r = doc.results(a)
        assert "error" not in r and r["status"]["error"] == "VALID", (key, r)
    c = doc.project.analyses
    ba = next(a for a in c if a.analysis_class == "BLAND_ALTMAN").parameters["content"]["data"]
    assert ba["methodAID"]["col"]["idx"] == 0 and ba["methodBID"]["col"]["idx"] == 2  # the chosen data sets
    lin = next(a for a in c if a.analysis_class == "MULTIPLE_LINEAR_REGRESSION").parameters["content"]["model"]
    assert lin["dependentVariable"]["col"]["idx"] == 2 and len(lin["modelDef"]) == 4  # intercept and 3 predictors
    assert [v["variableType"] for v in lin["variableInfo"]] == ["CONTINUOUS", "CONTINUOUS", "CONTINUOUS",
                                                                "CATEGORICAL"]
    nw = next(a for a in c if a.analysis_class == "MULTI_FACTOR_ANOVA").parameters["content"]["model"]
    assert [v["id"]["col"]["idx"] for v in nw["predictor"]["variables"]] == [3]  # the text variable is the factor


def test_phase8b_dialog_analyses_computed_from_tables():
    """The analyses added in phase 8b (E-stats8b: each matched Prism on generated tables): correlation
    matrices, a stack of P values, Deming regression, smoothing, curve fits and standard curves."""
    from refract.model import templates as T
    from refract.ui.document import Document

    doc = Document.new()
    col = doc.add_table(T.make("column", "C", sample=True), with_graph=False)
    xy = doc.add_table(T.make("xy", "X", sample=True), with_graph=False)
    mv = doc.add_table(T.make("multivariable", "MV", sample=True), with_graph=False)
    plan = [(col, "corr_matrix", {}, None), (col, "corr_matrix", {"design": "NONPARAMETRIC"}, None),
            (col, "p_values", {}, [0]), (col, "frequency", {"tabulate": "RELATIVE_PERCENTAGES"}, None),
            (mv, "mv_corr", {}, None), (xy, "correlation", {"pairs": "ALL_VS_ALL"}, None),
            (xy, "deming", {}, None), (xy, "smooth", {"what": "FIRST_DERIVATIVE"}, None),
            (xy, "nonlinear", {"equation": "line"}, None), (xy, "interpolate", {}, None)]
    for t, key, vals, sets in plan:
        a = doc.add_analysis(t, catalog.by_key(key), vals, sets)
        r = doc.results(a)
        assert "error" not in r and r["status"]["error"] == "VALID", (key, r)
    mats = [doc.results(a) for a in doc.project.analyses if a.analysis_class == "CORRELATION"]
    assert "Pearson r" in mats[0]["_tables"] and "Spearman r" in mats[1]["_tables"]
    assert "Pearson r" in mats[3]["_tables"]  # an XY table's every pair of Y data sets
    # a Multiple-variables table: its text variable is left out, the others keep their indices
    mvr = mats[2]["pearsonTestModel"]
    assert set(mvr) == {"col0", "col1", "col2"}


def test_correlation_matrix_values():
    import numpy as np
    from scipy import stats as ss

    from refract.stats import xy_basic as XB

    rnd = np.random.default_rng(1)
    a, b, c = (list(rnd.normal(size=12)) for _ in range(3))
    b[3] = None
    out = XB.correlation_matrix({"experimentalDesign": "PARAMETRIC", "options": {}}, [a, b, c], ["A", "B", "C"])
    m = out["pearsonTestModel"]
    assert m["col0"]["value"]["col0"]["value"]["status"] == "PERFECT_LINE"
    assert m["col0"]["value"]["col0"]["value"]["n"] == 12 and m["col1"]["value"]["col1"]["value"]["n"] == 11
    keep = [i for i in range(12) if b[i] is not None]
    r, p = ss.pearsonr([a[i] for i in keep], [b[i] for i in keep])
    ab = m["col0"]["value"]["col1"]["value"]
    assert abs(ab["r"] - r) < 1e-12 and abs(ab["pValue"]["value"] - p) < 1e-10 and ab["n"] == 11
    t = out["_tables"]
    assert t["Pearson r"]["rows"][1][0] == t["Pearson r"]["rows"][0][1] and t["P values"]["rows"][0][0] is None
    assert t["Confidence interval of r"]["rows"][0][1].count(" to ") == 1
    one = XB.correlation_matrix({"options": {"pValueTailType": "P_VALUE_ONE_TAILED",
                                             "excludeIncompleteRows": True}}, [a, b, c], ["A", "B", "C"])
    oc = one["pearsonTestModel"]["col0"]["value"]["col2"]["value"]
    assert oc["n"] == 11  # only the rows where every variable has a value
    assert XB._ci_text({"lower": -0.0084, "upper": 0.0444}) == "-0.008400 to 0.04440"


def test_deming_line_table_layout():
    from refract.stats import deming as DM

    x = [1.0, 2.0, 3.0, 4.0, 6.0, 9.0]
    one = DM.deming({}, x, [[1.1, 2.3, 2.9, 4.2, 6.1, 8.8]], ["A"])["_tables"]["Line"]
    assert len(one["rows"]) == 101 and one["rows"][0][0] == 1.0 and one["rows"][-1][0] == 9.0
    two = DM.deming({}, x, [[1.1, 2.3, 2.9, 4.2, 6.1, 8.8], [None, 5.0, 4.1, 3.2, 1.9, None]], ["A", "B"])
    line = two["_tables"]["Line"]["rows"]
    assert len(line) == 201  # one X series over every data set, 200 segments for more than one
    assert line[0][2] is None and line[-1][2] is None and line[100][2] is not None  # B: only over its own X
    assert two["models"]["col1"]["value"]["dataSummary"]["xValues"] == 5  # the rows up to its last value
    assert two["models"]["col1"]["value"]["dataSummary"]["pointsSkipped"] == 1


def test_interpolation_standard_curve():
    from refract.stats import equations as EQ
    from refract.stats import interpolation as IP

    params = {"model": EQ.model("line", [0]), "diagnostics": {"runsTest": True}}
    x = [0.0, 1.0, 2.0, 4.0, 8.0, None, None, None]
    y = [0.06, 0.14, 0.26, 0.44, 0.86, 0.5, 1.1, -0.5]
    out = IP.interpolate(params, x, [[y]], ["A"], "y_single")
    fit = out["models"]["col0"]["value"]
    b, a = fit["parameters"]["Slope"]["estimate"], fit["parameters"]["YIntercept"]["estimate"]
    rows = out["_tables"]["Interpolated X values"]["rows"]
    assert abs(rows[0][0] - (0.5 - a) / b) < 1e-9
    assert rows[1][0] is not None and rows[1][0] > 8  # extrapolated up to half the range beyond the standards
    assert rows[2][0] is None  # below zero, with every standard X at least zero: not reported
    assert fit["runsTest"]["status"] == "VALID" and out["dataSummary"]["col0"]["value"]["yValuesAnalyzed"] == 5
    assert IP.limits([2.0, 32.0]) == (0.0, 47.0) and IP.limits([-10.0, 10.0]) == (-20.0, 20.0)
    # replicates: the replicates test, and the unknowns read off one by one and as row means
    rep = IP.interpolate(params, x[:6], [[y[:6], [v + 0.01 for v in y[:6]]]], ["A"], "y_replicates")
    m = rep["models"]["col0"]["value"]
    assert m["replicatesTest"]["status"] == "VALID" and "runsTest" not in m
    assert len(rep["_tables"]["Interpolated  X replicates"]["rows"]) == 2
    assert len(rep["_tables"]["Interpolated X mean values"]["rows"]) == 1
    # a curve through every point: Prism's perfect fit, no SE
    perfect = IP.interpolate(params, [0.0, 1.0, 2.0, 3.0], [[[1.0, 3.0, 5.0, 7.0]]], ["A"], "y_single")
    pm = perfect["models"]["col0"]["value"]
    assert pm["status"] == "PERFECT_FIT" and "se" not in pm["parameters"]["Slope"]
    assert pm["runsTest"]["status"] == "INVALID"


def test_stack_of_p_values_and_smoothing():
    import numpy as np

    from refract.stats import p_values as PV
    from refract.stats import smooth as SM

    ps = [0.001, 0.008, 0.039, 0.041, 0.042, 0.06, 0.074, 0.205, 0.212, 0.216]
    bh = PV.stack({"multipleComparisons": {"type": "FDR", "fdr": {"test": "BENJAMINI_HOCHBERG",
                                                                  "options": {"discoveryLevel": 5.0}}}}, [ps])
    q = [bh["rows"][f"row{i}"]["value"]["qValue"]["value"] for i in range(len(ps))]
    want = np.minimum.accumulate((np.array(ps) * len(ps) / np.arange(1, len(ps) + 1))[::-1])[::-1]
    assert np.allclose(q, want) and bh["summary"]["discoveryCount"] == 2
    hs = PV.stack({"multipleComparisons": {"type": "STATISTICAL", "statistical": {"test": "HOLM_SIDAK"}}}, [ps])
    assert hs["rows"]["row0"]["value"]["pValueAdjusted"]["value"] == 1 - (1 - 0.001) ** 10
    x = [float(i) for i in range(12)]
    y = [v * v for v in x]
    out = SM.smooth_curve({"calc": {"type": "FIRST_DERIVATIVE", "smoothing": {"enabled": False}}}, x, [y], ["A"])
    rows = out["_tables"]["X Y coordinates"]["rows"]  # differences between neighbours, at the midpoints
    assert [r[0] for r in rows] == [v + 0.5 for v in x[:-1]] and [r[1] for r in rows] == [2 * v + 1 for v in x[:-1]]


def test_phase8c_dialog_options_and_tables():
    """Phase 8c (E-stats8c, each matched Prism): fitted curve tables, Deming with replicates, selected pairs in
    one-way ANOVA and the tables made from tables (transform, normalize, baseline, row statistics, transpose)."""
    from refract.model import templates as T
    from refract.ui.document import Document

    doc = Document.new()
    col = doc.add_table(T.make("column", "C", sample=True), with_graph=False)
    xy = doc.add_table(T.make("xy", "X", sample=True), with_graph=False)
    grp = doc.add_table(T.make("grouped", "G", sample=True), with_graph=False)
    fit = doc.results(doc.add_analysis(xy, catalog.by_key("nonlinear"), {"equation": "line"}))
    curve = fit["_tables"]["Curve"]
    assert len(curve["rows"]) == 1000 and curve["columns"][0] == "X"
    std = doc.results(doc.add_analysis(xy, catalog.by_key("interpolate"), {}))
    t0 = std["_tables"]["Curve"]["columns"][1]
    assert std["_tables"]["Curve"]["columns"][1:4] == [t0, f"{t0} (+)", f"{t0} (-)"]  # Y with its confidence band
    a = doc.add_analysis(col, catalog.by_key("one_way"), {"compare": "SELECTED_VS_SELECTED", "pairs": [[0, 2]],
                                                          "test": "HOLM_SIDAK"})
    pd_ = a.parameters["content"]["postTests"]["pairwiseTests"]["pairwiseDesign"]
    assert pd_["type"] == "SELECTED_VS_SELECTED" and [[p["col"]["idx"] for p in q] for q in pd_["selectedPairIDList"]] \
        == [[0, 2]]
    tests = doc.results(a)["ordinaryAnovaModel"]["multipleComparisons"]["tests"]
    assert list(tests) == ["col0"] and list(tests["col0"]["value"]) == ["col2"]
    for t, key, vals in [(xy, "transform", {}), (xy, "normalize", {"fractions": True}), (grp, "baseline", {}),
                         (grp, "row_stats", {"stat": "MEDIAN"}), (xy, "transpose", {}), (xy, "deming", {"reps": "AVERAGE"})]:
        r = doc.results(doc.add_analysis(t, catalog.by_key(key), vals))
        assert "error" not in r and r["status"]["error"] == "VALID", (key, r)
    norm = next(doc.results(a) for a in doc.project.analyses if a.analysis_class == "NORMALIZE")["_tables"]["Result"]
    vals = [v for row in norm["rows"] for v in row[1:] if v is not None]
    assert min(vals) == 0.0 and max(vals) == 1.0  # fractions of each data set's range


def test_deming_replicates():
    from refract.stats import deming as DM

    x = [1.0, 2.0, 3.0, 5.0, 8.0]
    reps = [[1.2, 2.1, 3.3, 4.8, 8.1], [0.9, 2.2, None, 5.1, 7.7]]
    ind = DM.deming({"data": {"handleReplicatesAs": "INDIVIDUAL"}}, x, [reps], ["A"])["models"]["col0"]["value"]
    avg = DM.deming({"data": {"handleReplicatesAs": "AVERAGE"}}, x, [reps], ["A"])["models"]["col0"]["value"]
    assert ind["dataSummary"] == {"xValues": 10, "yReplicates": 2, "pointsAnalyzed": 9, "pointsSkipped": 1}
    assert avg["dataSummary"] == {"xValues": 5, "yReplicates": 1, "pointsAnalyzed": 5, "pointsSkipped": 0}
    two = DM.deming({}, x, [reps, reps], ["A", "B"])["_tables"]["Line"]["rows"]
    assert len(two) == 101  # data sets with replicates: 100 segments


def test_spline_and_lowess():
    import numpy as np
    from scipy import interpolate

    from refract.stats import spline as SPL

    x = [float(i) for i in range(1, 13)]
    y = [2.1, 3.9, 6.2, 7.8, 9.1, 9.0, 8.2, 7.1, 6.8, 7.4, 8.9, 11.2]
    out = SPL.fit_spline({"calc": {"curve": {"type": "CUBIC_SPLINE"}}}, x, [y], ["A"])["_tables"]["Curve"]["rows"]
    assert len(out) == 48 and out[0][0] == 1.0 and out[-1][0] == 12.0  # 4 points per data row
    nat = interpolate.CubicSpline(x, y, bc_type="natural")
    assert max(abs(r[1] - nat(r[0])) for r in out) < 1e-12
    # LOWESS: tricube-weighted lines over a window of a fraction of the X range, joined by straight lines
    med = SPL.fit_spline({"calc": {"curve": {"type": "LOWESS", "resolution": "MEDIUM"}}}, x, [y], ["A"])
    at_data = SPL._lowess(np.array(x), np.array(y), 1.1)
    rows = med["_tables"]["Curve"]["rows"]
    assert abs(rows[0][1] - at_data[0]) < 1e-12 and abs(rows[-1][1] - at_data[-1]) < 1e-12
    # few points: Prism draws the cubic spline instead
    few = SPL.fit_spline({"calc": {"curve": {"type": "LOWESS", "resolution": "COARSE"}}}, x[:9], [y[:9]], ["A"])
    cub = SPL.fit_spline({"calc": {"curve": {"type": "CUBIC_SPLINE"}}}, x[:9], [y[:9]], ["A"])
    assert few["_tables"]["Curve"]["rows"] == cub["_tables"]["Curve"]["rows"]
    # a data set's curve only over its own X range
    part = SPL.fit_spline({"calc": {"curve": {"type": "CUBIC_SPLINE"}}}, x, [y, [None, *y[1:10], None, None]], ["A", "B"])
    pr = part["_tables"]["Curve"]["rows"]
    assert pr[0][2] is None and pr[-1][2] is None and pr[20][2] is not None


def test_fraction_prune_select():
    """E-stats8d (each matched Prism): fraction of total, prune rows, select and transform."""
    from refract.stats import transforms as TR

    t = {"title": "N", "x": None, "rows": ["a", "b"], "sets": [{"title": "A", "subs": [[12.0, 30.0]]},
                                                            {"title": "B", "subs": [[8.0, None]]}]}
    col = TR.fraction_of_total({"calc": {"type": "COLUMN"}}, t)["sets"]
    assert col[0]["subs"][0] == [12 / 42, 30 / 42] and col[1]["subs"][0] == [1.0, None]
    row = TR.fraction_of_total({"calc": {"type": "ROW"}, "options": {"reportResultsAs": "PERCENTAGES"}}, t)["sets"]
    assert row[0]["subs"][0][0] == 60.0 and row[1]["subs"][0][0] == 40.0
    grand = TR.fraction_of_total({"calc": {"type": "GRAND", "ci": {"calculate": True}}}, t)
    assert grand["format"] == "y_high_low" and len(grand["sets"][0]["subs"]) == 3
    summary = TR.fraction_of_total({"calc": {"type": "ALL"}}, t)
    assert summary["format"] == "text" and summary["rows"][0] == "Data analyzed"
    assert TR._g4(0.078125) == "0.07813" and TR._g4(47.0) == "47.00" and TR._g4(0.0) == "0.000"
    xy = {"title": "XY", "x": [0.0, 1.0, 2.0, 3.0, 4.0], "rows": None,
          "sets": [{"title": "A", "subs": [[1.0, 2.0, 3.0, None, 5.0]]}]}
    rng = TR.prune_rows({"calc": {"pruneByRange": True, "xRangeToKeep": {"from": 1.0, "to": 3.0}}}, xy)
    assert rng["x"] == [1.0, 2.0, 3.0] and rng["sets"][0]["subs"][0] == [2.0, 3.0, None]
    pairs = TR.prune_rows({"calc": {"pruneByRange": False, "averageType": "EVERY_OTHER_ROW", "n": 7}}, xy)
    assert pairs["x"] == [0.5, 2.5] and pairs["sets"][0]["subs"][0] == [1.5, 3.0]  # the last row left over
    thr = TR.prune_rows({"calc": {"pruneByRange": False, "averageType": "EVERY_NTH_ROW", "n": 2,
                                  "averageOnly": {"greaterThan": True, "xThreshold": 1.0}}}, xy)
    assert thr["x"] == [0.0, 1.0, 2.5]
    # replicates: a group whose last row is blank is blank (Prism)
    rep = dict(xy, sets=[{"title": "A", "subs": [[1.0, None, 3.0, 4.0, 5.0], [1.0, 2.0, 3.0, 4.0, 5.0]]}])
    rp = TR.prune_rows({"calc": {"pruneByRange": False, "averageType": "EVERY_OTHER_ROW"}}, rep)
    assert rp["sets"][0]["subs"][0] == [None, 3.5]
    mv = {"title": "MV", "x": None, "rows": None, "sets": [{"title": "Age", "subs": [[10.0, 100.0, 1000.0]]},
                                                         {"title": "Sex", "subs": [["F", "M", "F"]]}]}
    st = TR.select_transform({"transforms": [{"title": "log", "definition": "log(A)", "enabled": True},
                                             {"title": "Sex", "definition": "B", "enabled": True},
                                             {"title": "x", "definition": "A", "enabled": False}],
                              "rowFilters": {"range": {"from": 2, "to": 3}}}, mv)
    assert [s["title"] for s in st["sets"]] == ["log", "Sex"]
    assert st["sets"][0]["subs"][0] == [2.0, 3.0] and st["sets"][1]["subs"][0] == ["M", "F"]


def test_extract_rearrange():
    """E-extract (matched Prism 11.1 cell for cell, 15 cases): a Multiple-variables table rearranged as a
    grouped table (levels in first-appearance order, each cell's values as replicates, blank responses left
    out) or a column table (a column per group, or the response alone)."""
    from refract.stats import transforms as TR

    age = ["Mid", "Old", "Mid", "Mid", "Young", "Young", "Old", "Young", "Mid", "Old", "Mid", "Old", "Young", "Mid",
           "Old", "Old", "Old"]
    tr = ["Run", "Lift", "Run", "Lift", "Lift", "Run", "Run", "Run", "Run", "Run", "Run", "Run", "Lift", "Run",
          "Lift", "Run", "Run"]
    vo = [49.0, 36.9, 23.5, 30.7, None, 31.2, 52.4, 28.0, 55.5, 55.2, 22.2, 35.2, 39.7, 20.9, 37.0, 56.3, 24.5]
    mv = {"title": "MV", "x": None, "rows": None,
          "sets": [{"title": "Subj", "subs": [[f"s{i}" for i in range(17)]]}, {"title": "Age", "subs": [age]},
                   {"title": "Train", "subs": [tr]}, {"title": "VO2", "subs": [vo]}]}

    def ref(i):
        return {"col": {"idx": i}}

    g = TR.extract_rearrange({"resultTableFormat": "GROUPED", "dataArrangement": {
        "responseVariable": ref(3), "rowFactorVariable": ref(1), "columnFactorVariable": ref(2)}}, mv)
    assert g["kind"] == "grouped" and g["rows"] == ["Mid", "Old", "Young"] and g["replicates"] == 5
    assert [s["title"] for s in g["sets"]] == ["Run", "Lift"]
    lift = g["sets"][1]["subs"]  # Prism: replicate k holds each row's k-th value
    assert lift[0] == [30.7, 36.9, 39.7] and lift[1] == [None, 37.0, None] and lift[2] == [None, None, None]
    p = TR.extract_rearrange({"resultTableFormat": "GROUPED", "includeVarNamePrefix": True, "dataArrangement": {
        "responseVariable": ref(3), "rowFactorVariable": ref(1), "columnFactorVariable": ref(2)}}, mv)
    assert p["rows"][0] == 'Age = "Mid"' and p["sets"][0]["title"] == 'Train = "Run"'
    c = TR.extract_rearrange({"resultTableFormat": "COLUMN", "dataArrangement": {
        "responseVariable": ref(3), "groupingVariable": ref(1)}}, mv)
    assert [s["title"] for s in c["sets"]] == ["Mid", "Old", "Young"]
    assert c["sets"][2]["subs"][0] == [31.2, 28.0, 39.7, None, None, None, None]  # padded to the largest group
    one = TR.extract_rearrange({"resultTableFormat": "COLUMN", "rowTitles": {"type": "VARIABLE", "variable": ref(0)},
                                "dataArrangement": {"responseVariable": ref(3), "columnFactorVariable": ref(1)}}, mv)
    assert len(one["sets"]) == 1 and len(one["sets"][0]["subs"][0]) == 16 and one["rows"][4] == "s5"


def test_observed_vs_expected():
    """E-stats8e (matched Prism): chi-square and binomial goodness of fit."""
    from scipy import stats

    from refract.stats import observed_expected as OE

    def params(exp, kind="COUNTS", test="CHI_SQUARE_TEST"):
        key = "expectedCount" if kind == "COUNTS" else "expectedPercentage"
        return {"data": {"datasetID": {"col": {"idx": 0}}, "expectedValuesType": kind},
                "calc": {"test": test, "outcomes": [{key: e} for e in exp]}}

    r = OE.observed_expected(params([33, 33, 34]), [[18.0, 55.0, 27.0]])
    chi = (18 - 33) ** 2 / 33 + (55 - 33) ** 2 / 33 + (27 - 34) ** 2 / 34
    assert abs(r["chiSquareTest"]["chiSquared"] - chi) < 1e-12 and r["chiSquareTest"]["df"] == 2.0
    assert r["status"]["error"] == "VALID"
    pct = OE.observed_expected(params([25, 50, 25], "PERCENTAGES"), [[18.0, 55.0, 27.0]])
    assert pct["outcomes"]["row1"]["value"]["expectedCount"] == 50.0
    off = OE.observed_expected(params([30, 30, 30]), [[18.0, 55.0, 27.0]])
    assert off["status"]["error"] == "INVALID_PARAMETER_EXPECTED_COUNTS"  # still computed, as Prism
    b = OE.observed_expected(params([30, 70], "PERCENTAGES", "BINOMIAL_TEST"), [[33.0, 17.0]])
    assert abs(b["binomialTest"]["pValueTwoTailed"]["value"] - stats.binomtest(33, 50, 0.3).pvalue) < 1e-15
    assert b["outcomes"]["row0"]["value"]["ciOfObserved"]["lower"] < 66 < b["outcomes"]["row0"]["value"]["ciOfObserved"]["upper"]


def test_column_analyses_on_xy_and_grouped_tables():
    """E-kinds (matched Prism): Prism runs the column analyses on XY and grouped tables, each row's
    replicates averaged; a t test there adds each group's descriptive statistics."""
    from refract.model import templates as T
    from refract.ui.document import Document

    doc = Document.new()
    xy = doc.add_table(T.make("xy", "X", sample=True), with_graph=False)
    grp = doc.add_table(T.make("grouped", "G", sample=True), with_graph=False)
    for key in ("column_stats", "one_way", "one_sample", "normality", "frequency", "outliers"):
        assert {"xy", "grouped"} <= catalog.by_key(key).kinds
    a = doc.add_analysis(grp, catalog.by_key("column_stats"), {})
    r = doc.results(a)
    t = grp
    rows = t.n_rows
    means = [sum(v) / len(v) for v in ([t.values(0, k)[r] for k in range(t.subcolumns_per_dataset)
                                         if r < len(t.values(0, k)) and t.values(0, k)[r] is not None]
                                        for r in range(rows)) if v]
    assert abs(r["samples"]["col0"]["value"]["descriptiveStatistics"]["mean"] - sum(means) / len(means)) < 1e-12
    tt = doc.results(doc.add_analysis(xy, catalog.by_key("t_test"), {"design": "PAIRED_T_TEST"}, [0, 1]))
    assert set(tt["descriptiveStatistics"]) == {"col0", "col1", "differences"}


def _clusters(seed=4, n=7):
    """Three groups in three variables, and a label."""
    import random

    rnd = random.Random(seed)
    cent = [(2, 10, 5), (8, 3, 6), (5, 6, 12)]
    rows = [(f"r{i + 1}", *[c + rnd.gauss(0, 0.8) for c in cent[i % 3]]) for i in range(3 * n)]
    return [[r[0] for r in rows], *([r[j] for r in rows] for j in (1, 2, 3))], ["Name", "V1", "V2", "V3"]


def test_hierarchical_clustering():
    """E-cluster (matched Prism's two clustering templates, every value and cell): average/complete
    linkage of standardized or row-centred data, Prism's node order within a merge, its cluster order
    of a cut, cophenetic correlation, WCSS and the result tables."""
    import numpy as np
    from scipy.cluster import hierarchy as H
    from scipy.spatial.distance import pdist

    from refract.stats import clustering as CL

    cols, titles = _clusters()
    p = {"data": {"inputType": "ROWS", "variables": [{"col": {"idx": i}} for i in (1, 2, 3)],
                  "label": {"type": "VARIABLE", "variable": {"col": {"idx": 0}}}},
         "calc": {"columnTransform": "STANDARDIZE", "rowTransform": "NONE", "distance": {"type": "EUCLIDIAN"},
                  "linkage": "GROUP_AVERAGE"},
         "defineClusters": {"rows": {"method": "NUMBER_OF_CLUSTERS", "clusterCount": 3}},
         "report": {"distanceMatrix": True, "mergeMap": True, "copheneticDistanceMatrix": True,
                    "copheneticCorrelation": True, "outputFullMatrix": True},
         "graph": {"plots": ["DENDROGRAM", "ELBOW_PLOT"]}}
    r = CL.hierarchical(p, cols, titles)
    x = np.array(cols[1:]).T
    z = (x - x.mean(0)) / x.std(0, ddof=1)
    link = H.linkage(pdist(z), "average")
    rows = r["rows"]
    n = len(z)
    assert np.allclose([m["distance"] for m in rows["dendrogram"]], link[:, 2], rtol=1e-12, atol=0)
    assert rows["dendrogram"][0]["cluster"] == {"id": n, "label": "Cluster 1"}
    assert abs(rows["copheneticCorrelation"] - H.cophenet(link, pdist(z))[0]) < 1e-12
    # the three groups are found, every row in one
    groups = [sorted(q["idx"] for q in c["points"]) for c in rows["clusters"]]
    assert sorted(i for g in groups for i in g) == list(range(n)) and all(len({i % 3 for i in g}) == 1 for g in groups)
    # WCSS of one cluster: (n - 1) x variables for standardized data
    assert abs(rows["clusteringDetails"][0]["wcss"] - (n - 1) * 3) < 1e-9
    assert set(r["_tables"]) == {"Elbow plot (rows)", "Clustered data (rows)", "Distance matrix (rows)",
                                 "Cophenetic distances (rows)", "Merge map (rows)"}
    # Prism's order (verified 42/42): the new cluster takes the later slot, node1 is the earlier one
    active = list(range(n))
    for j, m in enumerate(rows["dendrogram"]):
        pa, pb = sorted((active.index(m["node1"]["id"]), active.index(m["node2"]["id"])))
        assert (active[pa], active[pb]) == (m["node1"]["id"], m["node2"]["id"])
        active[pb] = n + j
        del active[pa]
    both = CL.hierarchical({**p, "data": {**p["data"], "inputType": "ROWS_COLUMNS"},
                            "calc": {**p["calc"], "linkage": "COMPLETE", "columnTransform": "NONE",
                                     "rowTransform": "CENTER"}}, cols, titles)
    assert len(both["columns"]["dendrogram"]) == 2 and both["dataSummary"]["columnsAnalyzed"] == 3


def test_k_means():
    """E-cluster: k-means (the best of several starts), with the validity indices Prism reports
    (each matched Prism's values for Prism's own partitions but Krzanowski-Lai) and its rules for
    the optimal number of clusters."""
    import itertools

    from refract.stats import clustering as CL

    cols, titles = _clusters(n=8)
    p = {"data": {"variables": [{"col": {"idx": i}} for i in (1, 2, 3)]},
         "calc": {"transform": "STANDARDIZE", "distance": {"type": "EUCLIDIAN"}, "clusterCount": {"min": 1, "max": 5},
                  "randomSeed": {"value": 7}, "clusterMetrics": True},
         "graph": {"elbowPlot": True, "silhouettePlot": True, "gapPlot": True}}
    r = CL.k_means(p, cols, titles)
    m = r["models"]
    w = [m[str(k)]["wcss"] for k in range(1, 6)]
    assert all(a >= b - 1e-9 for a, b in itertools.pairwise(w)) and abs(w[0] - 23 * 3) < 1e-9
    k3 = m["3"]
    assert abs(k3["ballHall"] - k3["wcss"] / 3) < 1e-12
    n = 24
    assert abs(k3["calinskiHarabasz"] - ((w[0] - w[2]) / 2) / (w[2] / (n - 3))) < 1e-9
    assert abs(k3["hartigan"] - (w[2] / w[3] - 1) * (n - 3 - 1)) < 1e-9
    assert r["optimalClustering"]["optimalClusterCount"] == 3
    assert sorted(len(c["points"]) for c in k3["clusters"]) == [8, 8, 8]
    assert {"Clustered data", "Elbow plot", "Silhouette plot", "Gap statistics", "Cluster metrics"} <= set(r["_tables"])


def test_multiple_variables_designs():
    """E-mv (matched Prism's own templates, every value): a t test, curve fit or survival analysis of
    a Multiple-variables table is the analysis of the table Prism builds from the variables, its groups
    named by the factor's level."""
    from refract.model.document import DataSet, DataTable

    subj = [f"p{i}" for i in range(6)] * 2
    trt = ["Before"] * 6 + ["After"] * 6
    bp = ["140", "135", "150", "128", "145", "139", "132", "130", "141", "125", "138", "131"]
    mv = DataTable("TT", "multivariable", "y_single",
                   [DataSet("Subject", [subj[:6] + subj[6:][::-1]]), DataSet("Trt", [trt]),
                    DataSet("BP", [bp[:6] + bp[6:][::-1]])], 12)
    c = catalog.build(catalog.by_key("mv_t"), {"design": "PAIRED_T_TEST"}, mv)
    r = INP.run("T_TESTS_AND_NONPARAMETRIC", c, mv)
    col = DataTable("C", "column", "y_single", [DataSet("Before", [bp[:6]]), DataSet("After", [bp[6:]])], 6)
    plain = INP.run("T_TESTS_AND_NONPARAMETRIC", {**c, "variableDesign": None}, col)
    # rows are matched by subject, whatever their order in the table
    assert abs(r["pairedTTestModel"]["pairedTTest"]["t"] - plain["pairedTTestModel"]["pairedTTest"]["t"]) < 1e-12
    eff = r["pairedTTestModel"]["effectSizes"]
    m = r["pairedTTestModel"]["meanOfDifferences"]
    assert abs(eff["cohenD"] - m["mean"] / m["stdDeviationOfDifferences"]) < 1e-12
    assert abs(eff["hedgesG"] - eff["cohenD"] * (1 - 3 / (4 * 5 - 1))) < 1e-12
    ds = r["descriptiveStatistics"]
    assert ds["sample1"]["id"]["var"]["factorList"][0]["value"] == "After"  # Prism: the second level first
    assert "effectSizes" not in plain["pairedTTestModel"]  # a column table's t test reports none (Prism)
    grp = [g for g in ("Ctl", "A", "B") for _ in range(6)]
    time = ["3", "8", "12", "20", "25", "30", "2", "4", "6", "9", "11", "15", "10", "18", "26", "33", "40", "45"]
    ev = ["1", "1", "0", "1", "1", "0"] * 3
    sv = DataTable("SV", "multivariable", "y_single", [DataSet("Grp", [grp]), DataSet("Time", [time]),
                                                       DataSet("Event", [ev])], 18)
    c = catalog.build(catalog.by_key("mv_survival"), {"post": "CONTROL_VS_ALL"}, sv)
    r = INP.run("SURVIVAL", c, sv)
    mc = r["multipleComparisons"]
    assert mc["comparisonCount"] == 2 and mc["method"] == "Holm-Šídák"
    first = next(iter(mc["tests"].values()))
    assert first["id"]["var"]["factorList"][0]["value"] == "Ctl"
    assert all(v["value"]["sample1"]["value"]["n"] == 4 for v in first["value"].values())  # n: the events


def test_three_way_anova():
    """E-three-way (matched Prism 11.1, 7 cases): Type III sums of squares of an unbalanced
    2 x 2 x 2 design (generated data; Prism's values), the % of the total variation, and
    the means (unweighted means of the cell means)."""
    from refract.stats.three_way import three_way

    def col(*subs):
        return [[None if v == "" else float(v) for v in s] for s in subs]
    cols = [col(["12.78", "15.37"], ["11.26", "14.07"], ["12.25", ""], ["13.23", ""], ["11.45", "13.26"]),
            col(["", ""], ["18.72", ""], ["", ""], ["15.58", "14"], ["12.87", "15.47"]),
            col(["8.78", ""], ["", "10.72"], ["", "9.78"], ["7.26", "10.65"], ["11.13", ""]),
            col(["7.8", "14.51"], ["13.6", "11.14"], ["13.81", "15.1"], ["11.23", ""], ["13.19", "10.39"])]
    r = three_way({"report": {"means": True}}, cols, list("ABCD"), ["R1", "R2"])
    t = r["ordinaryAnovaModel"]["anovaTable"]
    prism = {"rowFactor": (4.218527964205825, 1.144462937512944), "colABCDFactor": (65.30405440715883, 17.716623090441505),
             "rowFactorVsColACBDFactor": (4.919740313199099, 1.3346979084692816),
             "rowFactorVsColABCDFactorVsColACBDFactor": (2.6390335570469787, 0.7159549782578749)}
    for k, (ss, f) in prism.items():
        assert abs(t[k]["ss"] - ss) < 1e-9 and abs(t[k]["fTest"]["f"] - f) < 1e-9
    assert t["residual"]["df"] == 20.0 and abs(t["colABCDFactor"]["variation"] - 37.2459112989723) < 1e-9
    assert r["ordinaryAnovaModel"]["dataSummary"] == {"rowCount": 2, "isBalancedDesign": False}
    m = r["ordinaryAnovaModel"]["means"]
    cells = [v["value"] for a in m["cells"].values() for b in a["value"].values() for v in b["value"].values()]
    assert abs(m["total"] - sum(cells) / len(cells)) < 1e-12
    one = three_way({}, [[[1.0, 2.0]] for _ in range(4)], list("ABCD"))
    assert one["status"]["error"] == "INVALID_DATA_TABLE_FORMAT_NO_REPLICATES"


def test_smoothing_spline():
    """E-spline2 (matched Prism, 38 curves): a natural cubic regression spline with Harrell's knots
    (3 to 7 knots), evenly spaced percentiles (8 or more), a straight line with 2."""
    import numpy as np

    from refract.stats import spline as SP

    x = np.arange(20.0)
    y = np.sin(x / 4) + 0.05 * x
    at = np.linspace(0, 19, 80)
    line = SP.smoothing_spline(x, y, at, 2)
    b = np.polyfit(x, y, 1)
    assert np.allclose(line, np.polyval(b, at))
    assert np.allclose(SP._knots(x, 3), np.quantile(x, [.1, .5, .9], method="weibull"))
    assert np.allclose(SP._knots(x, 8)[[0, -1]], [0, 19])
    # natural: linear beyond the outer knots
    k5 = SP._knots(x, 5)
    out = at[at > k5[-1]]
    v = SP.smoothing_spline(x, y, out, 5)
    assert np.allclose(np.diff(v, 2), 0, atol=1e-9)
    assert np.isnan(SP.smoothing_spline(x[:10], y[:10], at, 10)).all()  # 10 knots on 10 points: none (Prism)
    assert not np.isnan(SP.smoothing_spline(x[:6], y[:6], at[:5], 6)).any()  # 6 on 6: drawn (Prism)


def test_descriptive_statistics_extras():
    """E-mv: a Multiple-variables table's descriptive statistics (matched Prism, 117 values): Tukey's
    fences, the median's exact CI at its own level, harmonic and quadratic means with CIs."""
    from refract.stats import engine

    a = [3.1, 4.7, 2.01, 8.7, 5.5, 6.2, 3.3, 7.9, 4.4, 5.0, 6.8]
    r = engine.compute("DESCRIPTIVE_STATISTICS", {"options": {"confidenceLevel": 95.0}, "calc": {
        "medianCI": True, "harmonicMean": True, "harmonicMeanCI": True, "quadraticMean": True,
        "quadraticMeanCI": True}}, [a, ["x", "y"] * 5 + ["x"]], ["A", "G"])
    s = r["samples"]
    assert list(s) == ["col0"]  # the text variable is not described
    v = s["col0"]["value"]
    assert v["medianCI"]["level"] == 98.828125 and v["medianCI"]["lower"] == 3.1  # n = 11: the 2nd values
    assert abs(v["harmonicMean"] - len(a) / sum(1 / q for q in a)) < 1e-12
    assert abs(v["quadraticMean"] - (sum(q * q for q in a) / len(a)) ** 0.5) < 1e-12
    q1, q3 = v["firstQuartile"], v["thirdQuartile"]
    assert v["iqr"] == {"iqr": q3 - q1, "q1MinusIQR": q1 - 1.5 * (q3 - q1), "q3PlusIQR": q3 + 1.5 * (q3 - q1)}
