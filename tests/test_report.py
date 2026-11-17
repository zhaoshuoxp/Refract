"""Results laid out for reading (refract.stats.report): number and P value
formats, labels, and the pages built from the shape of the results."""

from refract.stats import engine
from refract.stats import report as R

S = R.Style()


def test_numbers_follow_the_output_settings():
    assert [R.number(v, S) for v in (2.0098, 0.025401, 21.029, 10.0225, 3.0, 10577.3, 0.0000123)] == \
        ["2.010", "0.02540", "21.03", "10.02", "3.000", "10577", "1.230e-05"]
    assert R.number(8.0, S, "df") == "8" and R.number(5.374, S, "df") == "5.374" and R.number(5.0, S, "n1") == "5"
    assert R.number(True, S) == "Yes" and R.number("undefined", S) == "Undefined"
    six = R.Style.of({"output": {"significantDigitCount": 6, "pValueStyle": {"type": "P_VALUE_STYLE_FULL",
                                                                             "decimalDigitCount": 6}}})
    assert R.number(21.02933, six) == "21.0293" and R.p_text(6.06713e-05, six) == "6.06713e-05"


def test_p_values_and_stars():
    assert [R.p_text(p, S) for p in (0.66008, 0.0065190, 0.00004, 0.99999)] == ["0.6601", "0.0065", "<0.0001", ">0.9999"]
    assert [R.stars(p, S) for p in (0.2, 0.04, 0.009, 0.0009, 0.00009)] == ["ns", "*", "**", "***", "****"]
    apa = R.Style(p_style="P_VALUE_STYLE_APA")
    assert R.p_text(0.0123, apa) == ".012" and R.p_text(0.0002, apa) == "<.001" and R.stars(0.00009, apa) == "***"


def test_labels():
    assert R.label("unpairedTTestModel") == "Unpaired t test"
    assert R.label("mannWhitneyTest") == "Mann-Whitney test"
    assert R.label("logrankMantelCoxTest") == "Log-rank Mantel-Cox test"
    assert R.label("meanSE") == "SEM" and R.label("firstQuartile") == "25% percentile"
    assert R.ci_label("meansDifferenceCI", {"lower": 1, "upper": 2, "level": 95.0}) == "95% CI of difference"
    assert R.enum_text("CI_RELATIVE_RISK_METHOD_KOOPMAN") == "Koopman"
    assert R.enum_text("TOO_FEW_POINTS") == "Too few points"


def _pages(cls, params, cols, titles, x=None):
    res = engine.compute(cls, params, cols, titles, x_values=x)
    return res, {p.name: p for p in R.build(res, params, [("Table analyzed", "T")])}


def _rows(page):
    """label -> cells of the first row with that label (later blocks reuse labels)."""
    out = {}
    for t in page.tables:
        for r in t.rows:
            out.setdefault(r.label, r.cells)
    return out


A = [3.0, 3.2, 3.9, 4.2, 4.3]
B = [2.3, 2.7, 4.5, 5.1, 5.2]
C = [4.2, 5.05, 6.4, 7.7, 7.8]


def test_t_test_summary():
    res, pages = _pages("T_TESTS_AND_NONPARAMETRIC", {"experimentalDesign": "UNPAIRED_T_TEST"}, [A, B], ["A", "B"])
    m = res["unpairedTTestModel"]
    rows = _rows(pages["Summary"])
    assert rows["Table analyzed"] == ["T"]
    assert rows["t, df"] == [f"t={R.number(m['unpairedTTest']['t'], S)}, df=8"]
    assert rows["P value"] == [R.p_text(m["unpairedTTest"]["pValue"]["value"], S)]
    assert rows["P value summary"] == ["ns"] and rows["Significant (P < 0.05)?"] == ["No"]
    ci = m["differenceOfMeans"]["confidenceIntervalOfDifference"]
    assert rows["95% CI of difference"] == [f"{R.number(ci['lower'], S)} to {R.number(ci['upper'], S)}"]
    assert rows["F (DFn, DFd)"][0].endswith(" (4, 4)")


def test_one_way_pages():
    params = {"experimentalDesign": "ORDINARY_ANOVA", "postTests": {"type": "PAIRWISE_TESTS", "pairwiseTests": {
        "pairwiseDesign": {"type": "ALL_VS_ALL"}, "multipleComparisons": {"type": "STATISTICAL",
                                                                         "statistical": {"test": "TUKEY"}}}}}
    res, pages = _pages("ONE_WAY_ANOVA", params, [A, B, C], ["Untreated", "Placebo", "Treated"])
    assert list(pages) == ["Summary", "ANOVA table", "Multiple comparisons", "Descriptive statistics"]
    f = res["ordinaryAnovaModel"]["anovaTable"]["colFactor"]["fTest"]
    assert _rows(pages["Summary"])["F (DFn, DFd)"] == [f"{R.number(f['f'], S)} (2, 12)"]
    anova = pages["ANOVA table"].tables[0]
    assert [r.label for r in anova.rows] == ["Between columns", "Residual", "Total"]
    assert anova.rows[0].cells[anova.columns.index("P value")] == R.p_text(f["pValue"]["value"], S)
    comp = pages["Multiple comparisons"].tables[-1]
    assert [r.label for r in comp.rows] == ["Untreated vs. Placebo", "Untreated vs. Treated", "Placebo vs. Treated"]
    assert {"Mean difference", "95% CI of difference", "Adjusted P value", "Summary", "Significant?"} <= set(comp.columns)
    desc = pages["Descriptive statistics"].tables[0]
    assert desc.columns == ["Untreated", "Placebo", "Treated"]
    assert _rows(pages["Descriptive statistics"])["Mean"] == ["3.720", "3.960", "6.230"]


def test_data_sets_side_by_side_align_by_path():
    """Rows of nested blocks with the same label stay apart (slope, intercepts)."""
    _res, pages = _pages("SIMPLE_LINEAR_REGRESSION", {}, [[[45, 56, 76, 81, 99, 97]], [[34, 41, 52, 63, 72, 78]]],
                         ["C", "T"], x=[0, 6, 12, 24, 48, 72])
    t = pages["Fits"].tables[0]
    assert t.columns == ["C", "T"]
    values = [r.cells for r in t.rows if r.label == "Value"]
    assert len(values) == 3 and len({v[0] for v in values}) == 3  # slope, Y intercept, X intercept


def test_text_export():
    _res, pages = _pages("COLUMN_STATISTICS", {}, [[1.0, 2.0, 3.0]], ["A"])
    assert "Mean\t2.000" in R.text(list(pages.values())).replace("  ", "")
