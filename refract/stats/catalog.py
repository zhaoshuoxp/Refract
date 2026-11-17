"""The analyses offered for new analysis sheets (docs/ui-spec.md §6), their
options and how the chosen options are written into Prism's parameter
vocabulary. Labels are our own wording.

A new analysis starts from `defaults.json` (parameter sets Prism wrote in our
probe documents, built by tools/make_defaults.py); `apply` then sets the
options the dialog shows.
"""

from __future__ import annotations

import copy
import json
import os
from dataclasses import dataclass, field
from typing import Any

from . import equations as EQ

with open(os.path.join(os.path.dirname(__file__), "defaults.json")) as _f:
    DEFAULTS: dict[str, dict] = json.load(_f)


@dataclass
class Field:
    key: str
    label: str
    # choice | float | bool | control (a data set of the analysis) | tests (post-test method) |
    # pairs (pairs of the analysis's data sets, by their index among them) | text |
    # variable (a data set of the table, by its index: a Multiple-variables table's variable)
    kind: str
    options: list[tuple[str, str]] = field(default_factory=list)
    default: Any = None


@dataclass
class Choice:
    key: str
    label: str
    analysis_class: str
    kinds: set[str]  # table kinds it applies to
    min_sets: int = 1
    max_sets: int | None = None
    fields: list[Field] = field(default_factory=list)
    short: str = ""  # sheet title prefix

    def title(self, table_title: str, values: dict | None = None) -> str:
        name = self.short or self.label
        if values and self.key in ("t_test", "mv_t"):
            name = T_SHORT[values.get("design", "UNPAIRED_T_TEST")]
        return f"{name} of {table_title}"


T_DESIGNS = [
    ("UNPAIRED_T_TEST", "Unpaired t test"), ("WELCH_T_TEST", "Unpaired t test with Welch's correction"),
    ("PAIRED_T_TEST", "Paired t test"), ("RATIO_PAIRED_T_TEST", "Ratio paired t test"),
    ("MANN_WHITNEY_TEST", "Mann-Whitney test"), ("WILCOXON_TEST", "Wilcoxon matched-pairs signed rank test"),
    ("KOLMOGOROV_SMIRNOV_TEST", "Kolmogorov-Smirnov test"),
]
T_SHORT = {"UNPAIRED_T_TEST": "Unpaired t test", "WELCH_T_TEST": "Welch's t test", "PAIRED_T_TEST": "Paired t test",
           "RATIO_PAIRED_T_TEST": "Ratio paired t test", "MANN_WHITNEY_TEST": "Mann-Whitney test",
           "WILCOXON_TEST": "Wilcoxon test", "KOLMOGOROV_SMIRNOV_TEST": "Kolmogorov-Smirnov test"}
ONE_WAY_DESIGNS = [
    ("ORDINARY_ANOVA", "Ordinary one-way ANOVA"), ("BROWN_FORSYTHE_ANOVA", "Brown-Forsythe and Welch ANOVA"),
    ("REPEATED_MEASURES_ANOVA", "Repeated measures (matched rows; mixed model if values are missing)"),
    ("KRUSKAL_WALLIS_TEST", "Kruskal-Wallis test"), ("FRIEDMAN_TEST", "Friedman test (matched rows)"),
]
TWO_WAY_DESIGNS = [
    ("ORDINARY_ANOVA", "Ordinary two-way ANOVA (no matching)"),
    ("REPEATED_MEASURES_BY_ROWS", "Repeated measures: matched across a row"),
    ("REPEATED_MEASURES_BY_COLS", "Repeated measures: matched within a column (subcolumns)"),
    ("REPEATED_MEASURES_BY_BOTH_FACTORS", "Repeated measures: matched by both factors"),
]
COMPARE = [("NONE", "No multiple comparisons"), ("ALL_VS_ALL", "Compare every mean with every other"),
           ("CONTROL_VS_ALL", "Compare each mean with a control"),
           ("SELECTED_VS_SELECTED", "Compare selected pairs of columns")]
TWO_WAY_COMPARE = [
    ("NO_TESTS", "No multiple comparisons"),
    ("COMPARE_COLUMNS", "Column means (main column effect)"),
    ("COMPARE_ROWS", "Row means (main row effect)"),
    ("COMPARE_CELLS_BY_COLUMNS_WITHIN_ROWS_SEPARATE_FAMILIES", "Within each row, compare the columns"),
    ("COMPARE_CELLS_BY_COLUMNS_WITHIN_ROWS_SINGLE_FAMILY", "Within each row, compare the columns (one family)"),
    ("COMPARE_CELLS_BY_ROWS_WITHIN_COLUMNS_SEPARATE_FAMILIES", "Within each column, compare the rows"),
    ("COMPARE_CELLS", "Every cell mean with every other"),
]
TEST_NAMES = {
    "TUKEY": "Tukey", "NEWMAN_KEULS": "Newman-Keuls", "BONFERRONI_SIDAK": "Šídák", "HOLM_SIDAK": "Holm-Šídák",
    "DUNNET": "Dunnett", "GAMES_HOWELL": "Games-Howell", "DUNNET_T3": "Dunnett T3", "TAMHANE_T2": "Tamhane T2",
    "DUNN": "Dunn", "FISHER_LSD": "Fisher's LSD (no correction)", "FDR": "False discovery rate (two-stage step-up)",
}


def post_tests(analysis_class: str, design: str, compare: str) -> list[str]:
    """The multiple-comparison methods the engine offers for that design."""
    if analysis_class == "ONE_WAY_ANOVA":
        if compare == "NONE":
            return []
        if design == "BROWN_FORSYTHE_ANOVA":
            return ["GAMES_HOWELL", "DUNNET_T3", "TAMHANE_T2"]
        if design in ("KRUSKAL_WALLIS_TEST", "FRIEDMAN_TEST"):
            return ["DUNN"]
        if compare == "CONTROL_VS_ALL":
            return ["DUNNET", "BONFERRONI_SIDAK", "HOLM_SIDAK", "FISHER_LSD", "FDR"]
        if compare == "SELECTED_VS_SELECTED":
            return ["BONFERRONI_SIDAK", "HOLM_SIDAK", "FISHER_LSD", "FDR"]
        return ["TUKEY", "BONFERRONI_SIDAK", "HOLM_SIDAK", "FISHER_LSD", "FDR"]
    if analysis_class == "TWO_WAY_ANOVA":
        return [] if compare == "NO_TESTS" else ["TUKEY", "BONFERRONI_SIDAK", "HOLM_SIDAK", "FISHER_LSD", "FDR"]
    return []


ALPHA = Field("alpha", "Significance level (alpha)", "float", default=0.05)
Y_FUNCS = [("", "None"), ("Y*K", "Y = Y * K"), ("Y+K", "Y = Y + K"), ("Y-K", "Y = Y - K"), ("Y/K", "Y = Y / K"),
           ("Y^2", "Y = Y squared"), ("Y^K", "Y = Y ^ K"), ("LOG10(Y)", "Y = log10(Y)"), ("LN(Y)", "Y = ln(Y)"),
           ("LOG2(Y)", "Y = log2(Y)"), ("10^Y", "Y = 10 ^ Y"), ("EXP(Y)", "Y = e ^ Y"), ("2^Y", "Y = 2 ^ Y"),
           ("1/Y", "Y = 1 / Y"), ("SQRT(Y)", "Y = square root of Y"), ("LOGIT(Y)", "Y = logit(Y)"),
           ("PROBIT(Y)", "Y = probit(Y)"), ("ABS(Y)", "Y = |Y|"), ("K-Y", "Y = K - Y"), ("K/Y", "Y = K / Y"),
           ("Y*X", "Y = Y * X"), ("Y/X", "Y = Y / X"), ("Y-X", "Y = Y - X"), ("Y+X", "Y = Y + X")]
X_FUNCS = [("", "None"), ("X*K", "X = X * K"), ("X^2", "X = X squared"), ("LOG10(X)", "X = log10(X)"),
           ("LN(X)", "X = ln(X)"), ("LOG2(X)", "X = log2(X)"), ("1/X", "X = 1 / X"), ("SQRT(X)", "X = square root of X"),
           ("K-X", "X = K - X")]
CORR_FIELDS = [Field("design", "Coefficient", "choice", [("PARAMETRIC", "Pearson"), ("NONPARAMETRIC", "Spearman")],
                     "PARAMETRIC"),
               Field("one_tailed", "One-tailed P values", "bool", default=False),
               Field("complete", "Only rows with every value", "bool", default=False),
               Field("level", "Confidence level (%)", "float", default=95.0)]
P_METHODS = [("BENJAMINI_KRIEGER_YEKUTIELI", "False discovery rate: two-stage step-up (Benjamini, Krieger, Yekutieli)"),
             ("BENJAMINI_HOCHBERG", "False discovery rate: Benjamini and Hochberg"),
             ("BENJAMINI_YEKUTIELI", "False discovery rate: Benjamini and Yekutieli"),
             ("HOLM_SIDAK", "Holm-Šídák"), ("BONFERRONI_SIDAK", "Šídák")]

CATALOG: list[tuple[str, list[Choice]]] = [
    ("Column analyses", [
        Choice("column_stats", "Descriptive statistics", "COLUMN_STATISTICS", {"column", "xy", "grouped"},
               fields=[Field("level", "Confidence level (%)", "float", default=95.0)], short="Descriptive statistics"),
        Choice("t_test", "t test or nonparametric comparison of two columns", "T_TESTS_AND_NONPARAMETRIC",
               {"column", "xy", "grouped"}, 2, 2, [Field("design", "Test", "choice", T_DESIGNS, "UNPAIRED_T_TEST"), ALPHA]),
        Choice("one_way", "One-way ANOVA or nonparametric comparison of three or more columns", "ONE_WAY_ANOVA",
               {"column", "xy", "grouped"}, 3, None,
               [Field("design", "Design", "choice", ONE_WAY_DESIGNS, "ORDINARY_ANOVA"),
                Field("compare", "Multiple comparisons", "choice", COMPARE, "ALL_VS_ALL"),
                Field("test", "Method", "tests", default="TUKEY"),
                Field("control", "Control column", "control", default=0),
                Field("pairs", "Pairs to compare", "pairs", default=None), ALPHA], short="One-way ANOVA"),
        Choice("one_sample", "One-sample t test or Wilcoxon signed-rank test", "ONE_SAMPLE_TESTS", {"column", "xy", "grouped"},
               fields=[Field("design", "Test", "choice", [("ONE_SAMPLE_T_TEST", "One-sample t test"),
                                                           ("WILCOXON_SIGNED_RANK_TEST", "Wilcoxon signed-rank test")],
                             "ONE_SAMPLE_T_TEST"),
                       Field("mu", "Hypothetical value", "float", default=0.0), ALPHA], short="One-sample test"),
        Choice("normality", "Normality tests", "NORMALITY_TESTS", {"column", "xy", "grouped"},
               fields=[Field("andersonDarling", "Anderson-Darling", "bool", default=True),
                       Field("dAgostinoPearson", "D'Agostino-Pearson omnibus", "bool", default=True),
                       Field("shaproWilks", "Shapiro-Wilk", "bool", default=True),
                       Field("kolmogorovSmirnov", "Kolmogorov-Smirnov", "bool", default=True), ALPHA]),
        Choice("frequency", "Frequency distribution (histogram)", "FREQUENCY_DISTRIBUTION", {"column", "xy", "grouped"},
               fields=[Field("cumulative", "Cumulative frequency distribution", "bool", default=False),
                       Field("tabulate", "Tabulate", "choice", [("VALUE_COUNT", "Number of values"),
                                                                ("RELATIVE_PERCENTAGES", "Relative frequency (%)"),
                                                                ("RELATIVE_FRACTIONS", "Relative frequency (fraction)")],
                             "VALUE_COUNT"),
                       Field("bin", "Bin width (0: automatic)", "float", default=0.0)],
               short="Frequency distribution"),
        Choice("outliers", "Identify outliers", "IDENTIFY_OUTLIERS", {"column", "xy", "grouped"},
               fields=[Field("method", "Method", "choice", [("ROUT", "ROUT"),
                                                             ("GRUBBS_SINGLE", "Grubbs (find one outlier)"),
                                                             ("GRUBBS_MULTIPLE", "Iterative Grubbs")], "ROUT"),
                       Field("q", "ROUT: Q (%)", "float", default=1.0),
                       Field("grubbs_alpha", "Grubbs: alpha", "float", default=0.05)], short="Outliers"),
        Choice("bland_altman", "Bland-Altman comparison of two methods", "BLAND_ALTMAN", {"column"}, 2, 2,
               [Field("calc", "Calculate", "choice", [("A_MINUS_B", "Difference (A - B)"),
                                                      ("B_MINUS_A", "Difference (B - A)"),
                                                      ("A_DIV_B", "Ratio (A / B)"), ("B_DIV_A", "Ratio (B / A)")],
                      "A_MINUS_B")], short="Bland-Altman"),
        Choice("roc", "ROC curve (controls first, then patients)", "ROC_CURVE", {"column"}, 2, 2,
               [Field("ci", "Confidence interval", "choice", [("WILSON_BROWN", "Wilson/Brown"),
                                                             ("CLOPPER_PEARSON", "Clopper-Pearson")],
                      "WILSON_BROWN"),
                Field("as", "Report results as", "choice", [("PERCENTAGE", "Percentages"), ("FRACTION", "Fractions")],
                      "PERCENTAGE"),
                Field("level", "Confidence level (%)", "float", default=95.0)], short="ROC curve"),
        Choice("corr_matrix", "Correlation matrix (every pair of columns)", "CORRELATION", {"column", "grouped"}, 2,
               None,
               CORR_FIELDS, short="Correlation matrix"),
        Choice("observed_expected", "Compare observed distribution with expected (one column of counts)", "CHI2",
               {"column", "parts_of_whole"}, 1, 1,
               [Field("expected", "Expected values, one per row (comma separated)", "text", default=""),
                Field("as", "Expected values are", "choice", [("COUNTS", "Counts"), ("PERCENTAGES", "Percentages")],
                      "PERCENTAGES"),
                Field("test", "Test", "choice", [("CHI_SQUARE_TEST", "Chi-square"),
                                                  ("BINOMIAL_TEST", "Binomial (two rows only)")], "CHI_SQUARE_TEST"),
                Field("ci", "Binomial: interval method", "choice",
                      [("CI_PROPORTION_METHOD_WILSON_BROWN", "Wilson/Brown"),
                       ("CI_PROPORTION_METHOD_CLOPPER_PEARSON", "Clopper-Pearson")],
                      "CI_PROPORTION_METHOD_WILSON_BROWN")], short="Observed vs expected"),
        Choice("p_values", "Analyze a stack of P values (one column)", "MULTIPLE_COMPARISONS", {"column"}, 1, 1,
               [Field("method", "Correction", "choice", P_METHODS, "BENJAMINI_KRIEGER_YEKUTIELI"),
                Field("q", "False discovery rate Q (%)", "float", default=1.0), ALPHA], short="P values"),
    ]),
    ("Grouped analyses", [
        Choice("three_way", "Three-way ANOVA (data sets A, B, C, D: two column factors; the rows: the third)",
               "THREE_WAY_ANOVA", {"grouped"}, 4, 4,
               [Field("means", "Report the means", "bool", default=False)], short="Three-way ANOVA"),
        Choice("two_way", "Two-way ANOVA (or mixed model)", "TWO_WAY_ANOVA", {"grouped"}, 1, None,
               [Field("design", "Design", "choice", TWO_WAY_DESIGNS, "ORDINARY_ANOVA"),
                Field("interaction", "Include the interaction term", "bool", default=True),
                Field("compare", "Multiple comparisons", "choice", TWO_WAY_COMPARE, "COMPARE_COLUMNS"),
                Field("test", "Method", "tests", default="TUKEY"), ALPHA], short="Two-way ANOVA"),
        Choice("multiple_t", "A two-sample test on every row", "MULTIPLE_TWO_SAMPLE_TESTS", {"grouped"}, 2, 2,
               [Field("design", "Test", "choice", [
                   ("MULTIPLE_UNPAIRED_TWO_SAMPLE_EQUAL_SD_TESTS", "Unpaired t tests, equal SD"),
                   ("MULTIPLE_UNPAIRED_TWO_SAMPLE_UNEQUAL_SD_TESTS", "Unpaired t tests, Welch"),
                   ("MULTIPLE_PAIRED_TWO_SAMPLE_TESTS", "Paired t tests"),
                   ("MULTIPLE_MANN_WHITNEY_TESTS", "Mann-Whitney tests"),
                   ("MULTIPLE_WILCOXON_TESTS", "Wilcoxon tests")], "MULTIPLE_UNPAIRED_TWO_SAMPLE_EQUAL_SD_TESTS"),
                Field("correction", "Multiple comparisons", "choice", [
                    ("FDR", "False discovery rate (two-stage step-up)"), ("STATISTICAL", "Holm-Šídák"),
                    ("NO_CORRECTION", "No correction")], "FDR")], short="Multiple t tests"),
    ]),
    ("XY analyses", [
        Choice("linear", "Simple linear regression", "SIMPLE_LINEAR_REGRESSION", {"xy"}, short="Linear regression"),
        Choice("correlation", "Correlation (X with each Y, or every pair of Y data sets)", "CORRELATION", {"xy"},
               fields=[Field("pairs", "Correlate", "choice", [("CONTROL_VS_ALL", "X with each Y data set"),
                                                              ("ALL_VS_ALL", "Every pair of Y data sets")],
                             "CONTROL_VS_ALL"), *CORR_FIELDS], short="Correlation"),
        Choice("nonlinear", "Nonlinear regression (curve fit)", "NONLINEAR_REGRESSION", {"xy"},
               fields=[Field("equation", "Model", "choice", EQ.LABELS, "log_4p"),
                       Field("level", "Confidence level (%)", "float", default=95.0)], short="Nonlinear fit"),
        Choice("interpolate", "Interpolate a standard curve (rows with a Y and no X are the unknowns)",
               "INTERPOLATION", {"xy"},
               fields=[Field("equation", "Model", "choice", EQ.STANDARD_CURVES, "line")], short="Interpolated"),
        Choice("spline", "Fit spline / LOWESS (a curve through or among the points)", "FIT_SPLINE_LOWESS", {"xy"},
               fields=[Field("type", "Curve", "choice", [("LOWESS", "LOWESS"), ("CUBIC_SPLINE", "Cubic spline"),
                                                         ("AKIMA_SPLINE", "Akima spline"),
                                                         ("SMOOTHING_SPLINE", "Smoothing spline")], "LOWESS"),
                       Field("resolution", "LOWESS smoothing", "choice", [("FINE", "Fine"), ("MEDIUM", "Medium"),
                                                                           ("COARSE", "Coarse")], "MEDIUM"),
                       Field("knots", "Smoothing spline: number of knots (fewer: smoother)", "float", default=4.0)],
               short="Spline"),
        Choice("deming", "Deming (Model II) linear regression", "DEMING_REGRESSION", {"xy"},
               fields=[Field("sd", "Errors of X and Y", "choice", [("EQUAL_SD", "Same SD for X and Y"),
                                                                   ("DIFFERENT_SD", "Different SDs (enter them)")],
                             "EQUAL_SD"),
                       Field("xsd", "SD of X errors", "float", default=1.0),
                       Field("ysd", "SD of Y errors", "float", default=1.0),
                       Field("reps", "Replicates", "choice", [("INDIVIDUAL", "Each replicate is a point"),
                                                              ("AVERAGE", "The mean of each row")], "INDIVIDUAL")],
               short="Deming regression"),
        Choice("smooth", "Smooth, differentiate or integrate a curve", "SMOOTH_CURVE", {"xy"},
               fields=[Field("what", "Compute", "choice", [("CURVE", "Smoothed curve"),
                                                           ("FIRST_DERIVATIVE", "First derivative"),
                                                           ("SECOND_DERIVATIVE", "Second derivative"),
                                                           ("INTEGRAL", "Integral")], "CURVE"),
                       Field("smooth", "Smooth (derivatives and integral)", "bool", default=True),
                       Field("neighbors", "Neighbours on each side", "float", default=4.0),
                       Field("order", "Smoothing polynomial", "choice", [("0", "Zero order (moving average)"),
                                                                         ("2", "Second order")], "2"),
                       Field("y0", "Integral: Y at the first X", "float", default=0.0)], short="Smoothed"),
        Choice("auc", "Area under curve", "AREA_UNDER_CURVE", {"xy"},
               fields=[Field("baseline", "Baseline (Y =)", "float", default=0.0),
                       Field("positive", "Positive peaks only", "bool", default=True)], short="Area under curve"),
        Choice("logistic", "Simple logistic regression (Y is 0 or 1)", "SIMPLE_LOGISTIC_REGRESSION", {"xy"}, 1, 1,
               [Field("level", "Confidence level (%)", "float", default=95.0)], short="Simple logistic regression"),
    ]),
    ("Nested analyses", [
        Choice("nested_t", "Nested t test", "NESTED_T_TEST", {"nested"}, 2, 2, [ALPHA], short="Nested t test"),
        Choice("nested_one_way", "Nested one-way ANOVA", "ONE_WAY_NESTED_ANOVA", {"nested"}, 3, None,
               short="Nested one-way ANOVA"),
    ]),
    ("Multiple variables analyses", [
        Choice("select", "Select and transform variables", "SELECT_TRANSFORM", {"multivariable"},
               fields=[Field("defs", "New variables (comma separated; A, B, C... are the variables; e.g. log(B))",
                             "text", default=""),
                       Field("first", "First row (0: all rows)", "float", default=0.0),
                       Field("last", "Last row (0: all rows)", "float", default=0.0)], short="Selected"),
        Choice("extract", "Extract and rearrange (a grouped or column table of one variable)", "EXTRACT_REARRANGE",
               {"multivariable"}, fields=[
                   Field("fmt", "New table", "choice", [("GROUPED", "Grouped table (row and column factors)"),
                                                        ("COLUMN", "Column table (a column per group)")], "GROUPED"),
                   Field("y", "Values (response variable)", "variable", default=0),
                   Field("rows", "Row factor (grouped) or groups (column table)", "variable", default=1),
                   Field("cols", "Column factor (grouped table)", "variable", default=2),
                   Field("prefix", "Titles name the variable (Factor = \"level\")", "bool", default=False)],
               short="Extract and rearrange"),
        Choice("mv_corr", "Correlation matrix (the chosen numeric variables)", "CORRELATION", {"multivariable"}, 2,
               None, CORR_FIELDS, short="Correlation matrix"),
        Choice("mv_linear", "Multiple linear regression (the other chosen variables predict it)",
               "MULTIPLE_LINEAR_REGRESSION", {"multivariable"}, 2, None,
               [Field("y", "Dependent variable", "variable", default=0)], short="Multiple linear regression"),
        Choice("mv_logistic", "Multiple logistic regression (an outcome of two values)",
               "MULTIPLE_LOGISTIC_REGRESSION", {"multivariable"}, 2, None,
               [Field("y", "Outcome variable", "variable", default=0)], short="Multiple logistic regression"),
        Choice("cox", "Cox proportional hazards regression", "MULTIPLE_COX_REGRESSION", {"multivariable"}, 3, None,
               [Field("time", "Time variable", "variable", default=0),
                Field("event", "Event variable (1 event, 0 censored)", "variable", default=1)],
               short="Cox regression"),
        Choice("pca", "Principal component analysis (the chosen numeric variables)", "PCA", {"multivariable"}, 2,
               None, [Field("method", "Components to keep", "choice", [
                   ("KAISER_RULE", "Eigenvalue > 1 (Kaiser)"), ("PARALLEL_ANALYSIS", "Parallel analysis"),
                   ("SPECIFIC_NUMBER", "A number of them")], "KAISER_RULE"),
                   Field("components", "Number of components", "float", default=2.0)], short="PCA"),
        Choice("mv_desc", "Descriptive statistics (each numeric variable)", "DESCRIPTIVE_STATISTICS", {"multivariable"},
               fields=[Field("level", "Confidence level (%)", "float", default=95.0),
                       Field("more", "Also the median's CI, harmonic and quadratic means", "bool", default=False)],
               short="Descriptive statistics"),
        Choice("mv_t", "t test or nonparametric test (a response compared between the two levels of a factor)",
               "T_TESTS_AND_NONPARAMETRIC", {"multivariable"}, fields=[
                   Field("design", "Test", "choice", T_DESIGNS, "UNPAIRED_T_TEST"), ALPHA,
                   Field("y", "Response variable", "variable", default=2),
                   Field("factor", "Factor (two levels)", "variable", default=1),
                   Field("subject", "Subject (paired tests: rows of a subject are matched)", "variable", default=0)]),
        Choice("mv_nonlinear", "Nonlinear regression (a curve per level of a factor)", "NONLINEAR_REGRESSION",
               {"multivariable"}, fields=[
                   Field("equation", "Model", "choice", EQ.LABELS, "log_4p"),
                   Field("level", "Confidence level (%)", "float", default=95.0),
                   Field("x", "X variable", "variable", default=0), Field("y", "Response variable", "variable", default=2),
                   Field("factor", "Factor (a curve per level)", "variable", default=1)], short="Nonlinear fit"),
        Choice("mv_survival", "Kaplan-Meier survival (a curve per level of a factor)", "SURVIVAL", {"multivariable"},
               fields=[Field("x", "Time variable", "variable", default=1),
                       Field("y", "Event variable (1 event, 0 censored)", "variable", default=2),
                       Field("factor", "Group (a curve per level)", "variable", default=0),
                       Field("post", "Compare the curves in pairs (log-rank, Holm-Šídák)", "choice", [
                           ("NO_TESTS", "No pairwise comparisons"), ("CONTROL_VS_ALL", "Each with the first group"),
                           ("ALL_VS_ALL", "Every pair")], "NO_TESTS")], short="Survival"),
        Choice("hclust", "Hierarchical clustering (the chosen numeric variables; a text variable names the rows)",
               "HIERARCHICAL_CLUSTERING", {"multivariable"}, 2, None, [
                   Field("linkage", "Linkage", "choice", [("GROUP_AVERAGE", "Average (UPGMA)"),
                                                          ("COMPLETE", "Complete (furthest neighbour)")],
                         "GROUP_AVERAGE"),
                   Field("transform", "Transform first", "choice", [
                       ("STANDARDIZE", "Standardize each variable"), ("NONE", "None"),
                       ("ROW_CENTER", "Center each row")], "STANDARDIZE"),
                   Field("clusters", "Number of clusters (0: none)", "float", default=3.0),
                   Field("columns", "Cluster the variables too", "bool", default=False)],
               short="Hierarchical clustering"),
        Choice("kmeans", "K-means clustering (the chosen numeric variables)", "K_MEANS_CLUSTERING", {"multivariable"},
               2, None, [Field("min", "Fewest clusters", "float", default=1.0),
                         Field("max", "Most clusters", "float", default=8.0),
                         Field("transform", "Transform first", "choice", [("STANDARDIZE", "Standardize each variable"),
                                                                          ("NONE", "None")], "STANDARDIZE")],
               short="K-means clustering"),
        Choice("nway", "Multifactor ANOVA (the chosen text variables are its factors)", "MULTI_FACTOR_ANOVA",
               {"multivariable"}, 2, None, [Field("y", "Response variable", "variable", default=0)],
               short="Multifactor ANOVA"),
    ]),
    ("Data manipulations", [
        Choice("transform", "Transform (a function of X or Y)", "TRNSFORM", {"xy", "grouped", "column"},
               fields=[Field("y", "Y function", "choice", Y_FUNCS, "LOG10(Y)"),
                       Field("x", "X function (XY tables)", "choice", X_FUNCS, ""),
                       Field("k", "K", "float", default=1.0)], short="Transform"),
        Choice("normalize", "Normalize (each data set to 0 % and 100 %)", "NORMALIZE", {"xy", "grouped", "column"},
               fields=[Field("zero", "0 % is", "choice", [("SMALLEST", "The smallest value"),
                                                         ("FIRST", "The first value"),
                                                         ("CUSTOM", "The value below")], "SMALLEST"),
                       Field("zero_value", "0 %: value", "float", default=0.0),
                       Field("hundred", "100 % is", "choice", [("LARGEST", "The largest value"),
                                                              ("LAST", "The last value"),
                                                              ("SUM_OF_VALUES", "The sum of the values"),
                                                              ("CUSTOM", "The value below")], "LARGEST"),
                       Field("hundred_value", "100 %: value", "float", default=100.0),
                       Field("fractions", "Report fractions (not percentages)", "bool", default=False)],
               short="Normalized"),
        Choice("baseline", "Remove baseline (a baseline column or row)", "REMOVE_BASELINE", {"xy", "grouped"},
               fields=[Field("where", "Baseline", "choice", [
                   ("EVERY_OTHER_COLUMN_2_4_6", "Columns B, D, F... are the baselines of A, C, E..."),
                   ("EVERY_OTHER_COLUMN_1_3_5", "Columns A, C, E... are the baselines of B, D, F..."),
                   ("FIRST_ROW", "The first row"), ("LAST_ROW", "The last row")], "EVERY_OTHER_COLUMN_2_4_6"),
                   Field("expr", "Compute", "choice", [("DIFFERENCE", "Difference"), ("RATIO", "Ratio"),
                                                       ("PERCENT", "Percent of baseline"),
                                                       ("PERCENTAGE_DIFFERENCE", "Percent difference")], "DIFFERENCE")],
               short="Baseline removed"),
        Choice("row_stats", "Row statistics (each row across the data sets)", "ROW_STATISTICS",
               {"xy", "grouped", "column"},
               fields=[Field("stat", "Compute", "choice", [
                   ("MEAN_WITH_SD", "Mean, SD and N"), ("MEAN_WITH_SEM", "Mean, SEM and N"),
                   ("MEAN_WITH_CV", "Mean, %CV and N"), ("MEAN_WITH_CI", "Mean with confidence interval"),
                   ("SUM", "Sum"), ("MEDIAN", "Median"), ("MEDIAN_WITH_RANGE", "Median with range"),
                   ("MEDIAN_WITH_QUARTILES", "Median with quartiles"),
                   ("MEDIAN_WITH_PERCENTILES", "Median with percentiles")], "MEAN_WITH_SD"),
                   Field("per_set", "Each data set across its replicates (not the whole row)", "bool", default=False),
                   Field("level", "Confidence level (%)", "float", default=95.0)], short="Row statistics"),
        Choice("transpose", "Transpose X and Y (rows become data sets)", "TRANSPOSE", {"xy"}, short="Transposed"),
        Choice("fraction", "Fraction of total", "FRACTION_OF_TOTAL", {"column", "grouped", "parts_of_whole", "xy"},
               fields=[Field("of", "Divide each value by", "choice", [("COLUMN", "Its column total"),
                                                                     ("ROW", "Its row total"),
                                                                     ("GRAND", "The grand total"),
                                                                     ("ALL", "All three (a summary)")], "COLUMN"),
                       Field("pct", "Report percentages (not fractions)", "bool", default=False),
                       Field("ci", "Confidence intervals (counts)", "bool", default=False),
                       Field("method", "Interval method", "choice", [("WILSON_BROWN", "Wilson/Brown"),
                                                                     ("CLOPPER_PEARSON", "Clopper-Pearson")],
                             "WILSON_BROWN"),
                       Field("level", "Confidence level (%)", "float", default=95.0)], short="Fraction of total"),
        Choice("prune", "Prune rows (keep an X range, or average rows)", "PRUNE_ROWS", {"xy"},
               fields=[Field("mode", "Prune by", "choice", [("RANGE", "Keeping only the rows in an X range"),
                                                            ("PAIRS", "Averaging every two rows"),
                                                            ("GROUPS", "Averaging every K rows")], "RANGE"),
                       Field("from", "Keep X from", "float", default=None),
                       Field("to", "Keep X to", "float", default=None),
                       Field("n", "K (rows averaged)", "float", default=3.0),
                       Field("above", "Average only rows with X above the threshold", "bool", default=False),
                       Field("threshold", "Threshold X", "float", default=0.0)], short="Pruned"),
    ]),
    ("Survival analyses", [
        Choice("survival", "Kaplan-Meier survival curves and comparisons", "SURVIVAL", {"survival"},
               short="Survival"),
    ]),
    ("Contingency analyses", [
        Choice("contingency", "Test of association", "CONTINGENCY_TABLE", {"contingency"}, 2, None,
               [Field("method", "Test", "choice", [("FISHER_EXACT_TEST", "Fisher's exact test"),
                                                   ("CHI_SQUARE_TEST", "Chi-square test")], "FISHER_EXACT_TEST"),
                ALPHA], short="Contingency"),
    ]),
]


def choices_for(kind: str) -> list[Choice]:
    return [c for _, cs in CATALOG for c in cs if kind in c.kinds]


def by_key(key: str) -> Choice:
    return next(c for _, cs in CATALOG for c in cs if c.key == key)


def initial(choice: Choice) -> dict[str, Any]:
    return {f.key: f.default for f in choice.fields}


def _mc(mc: dict, test: str, alpha: float) -> None:
    """multipleComparisons block for a chosen method."""
    if test == "FDR":
        mc["type"] = "FDR"
    elif test == "FISHER_LSD":
        mc["type"] = "NO_CORRECTION"
        mc.setdefault("noCorrection", {}).setdefault("options", {})["significanceLevel"] = alpha
    else:
        mc["type"] = "STATISTICAL"
        st = mc.setdefault("statistical", {})
        st["test"] = test
        st.setdefault("options", {})["significanceLevel"] = alpha


def _ref(t, i: int) -> dict:
    """A data set named by its index in the table (refract.formats.analysis_writer fills in its uid)."""
    return {"col": {"idx": int(i), "title": (t.datasets[i].title or "") if t is not None else ""}}


def _info(t, i: int, columns) -> dict:
    """A variable's entry in variableInfo: continuous, or categorical with its levels (first: reference)."""
    vals = columns[i]
    if any(isinstance(x, str) for x in vals):
        levels = list(dict.fromkeys(str(x) for x in vals if x not in (None, "")))
        return {"variable": _ref(t, i), "variableType": "CATEGORICAL", "referenceLevelType": "AUTO_FIRST_LEVEL",
                "referenceLevelValue": levels[0] if levels else "", "levelCount": len(levels),
                "levelOrderType": "VISUAL"}
    return {"variable": _ref(t, i), "variableType": "CONTINUOUS"}


def _outcomes(columns, i: int) -> tuple[dict, dict]:
    levels = list(dict.fromkeys(_level(x) for x in columns[i] if x not in (None, "")))
    if all(x in ("0", "1") for x in levels):
        levels = ["0", "1"]
    a, b = (levels + ["", ""])[:2]
    return {"value": a, "label": a}, {"value": b, "label": b}


def _level(x) -> str:
    return str(int(x)) if isinstance(x, float) and x.is_integer() else str(x)


def _model(t, sets: list[int], y: int, columns, intercept: bool) -> tuple[list, list]:
    """modelDef (the intercept, then each predictor as a main effect) and variableInfo."""
    preds = [i for i in sets if i != y]
    model_def = ([{"componentType": "INTERCEPT", "variables": []}] if intercept else []) + \
        [{"componentType": "ADDITIVE", "variables": [_ref(t, i)]} for i in preds]
    return model_def, [_info(t, i, columns) for i in [y, *preds]]


MV_OF = {"mv_t": "t_test", "mv_nonlinear": "nonlinear", "mv_survival": "survival"}  # the same analysis of a table


def _design(choice: Choice, v: dict, table) -> dict:
    ref = (lambda i: _ref(table, int(i))) if table is not None else (lambda i: {"col": {"idx": int(i)}})
    vd: dict = {"responseList": [ref(v["y"])], "factorList": [ref(v["factor"])]}
    if "x" in v:
        vd["x"] = ref(v["x"])
    if choice.key == "mv_t" and str(v.get("design", "")).startswith(("PAIRED", "RATIO_PAIRED", "WILCOXON")):
        vd["subject"] = ref(v["subject"])
    return vd


def _build_mv(choice: Choice, v: dict, table) -> dict[str, Any]:
    """A Multiple-variables table's t test, curve fit or survival analysis (Prism's variableDesign):
    the parameters of the same analysis of the table Prism builds from the variables."""
    from .inputs import mv_design

    inner = by_key(MV_OF[choice.key])
    vd = _design(choice, v, table)
    shaped = mv_design(choice.analysis_class, {"variableDesign": vd, "experimentalDesign": v.get("design")}, table) \
        if table is not None else None
    c = build(inner, {f.key: v[f.key] for f in inner.fields if f.key in v}, shaped)
    if choice.key == "mv_t":  # Prism's own sample reports them
        c["report"] = {**(c.get("report") or {}), "effectSizes": True}
    if choice.key == "mv_survival" and v.get("post", "NO_TESTS") != "NO_TESTS" and table is not None:
        levels = shaped.mv_design["levels"] if shaped is not None else []
        pt = c.setdefault("postTests", {})
        pt["type"] = "PAIRWISE_TESTS"
        pw = pt.setdefault("pairwiseTests", {})
        control = {"var": {"response": vd["responseList"][0]["col"], "factorList": [
            {"var": vd["factorList"][0]["col"], "value": levels[0] if levels else ""}]}}
        pw["pairwiseDesign"] = {"type": v["post"], "controlID": control, "selectedPairIDList": []}
        mc = pw.setdefault("multipleComparisons", {})
        mc["type"] = "STATISTICAL"
        mc["statistical"] = {**(mc.get("statistical") or {}), "test": "HOLM_SIDAK",
                             "report": {"adjustedPValues": False}}
    return {"variableDesign": vd, **c}


def build(choice: Choice, values: dict[str, Any], table=None, sets: list[int] | None = None) -> dict[str, Any]:
    """Parameter content for a new analysis with these option values;
    table and sets (data-set indices; None: all): the data analysed, which
    the analyses naming data sets or variables need."""
    v = {**initial(choice), **values}
    k = choice.key
    if k in MV_OF:
        return _build_mv(choice, v, table)
    c = copy.deepcopy(DEFAULTS[choice.analysis_class])
    alpha = float(v.get("alpha") or 0.05)
    sets = list(range(len(table.datasets))) if table is not None and sets is None else (sets or [])
    if k in ("mv_linear", "mv_logistic", "cox", "pca", "nway", "hclust", "kmeans") and table is not None:
        from .inputs import gather

        columns = gather(choice.analysis_class, table).columns
    else:
        columns = []
    if k == "column_stats":
        c.setdefault("options", {})["confidenceLevel"] = float(v["level"])
    elif k == "t_test":
        c["experimentalDesign"] = v["design"]
        c.setdefault("options", {})["significanceLevel"] = alpha
    elif k == "one_way":
        c["experimentalDesign"] = v["design"]
        pt = c.setdefault("postTests", {})
        pw = pt.setdefault("pairwiseTests", {})
        tests = post_tests("ONE_WAY_ANOVA", v["design"], v["compare"])
        if not tests:
            pt["type"] = "NO_TESTS"
        else:
            pt["type"] = "PAIRWISE_TESTS"
            pd_ = pw.setdefault("pairwiseDesign", {})
            pd_["type"] = v["compare"]
            pd_["controlID"] = {"col": {"idx": int(v.get("control") or 0)}}
            if v["compare"] == "SELECTED_VS_SELECTED":  # indices among the analysed data sets, lower first
                chosen = [sorted((int(a), int(b))) for a, b in (v.get("pairs") or [])] or [[0, 1]]
                pd_["selectedPairIDList"] = [[{"col": {"idx": a}}, {"col": {"idx": b}}] for a, b in chosen]
            _mc(pw.setdefault("multipleComparisons", {}), v["test"] if v["test"] in tests else tests[0], alpha)
    elif k == "one_sample":
        c["experimentalDesign"] = v["design"]
        c.setdefault("calc", {})["hypotheticalValue"] = float(v["mu"])
        c.setdefault("options", {})["significanceLevel"] = alpha
    elif k == "normality":
        tests = c.setdefault("calc", {}).setdefault("tests", {})
        for name in ("andersonDarling", "dAgostinoPearson", "shaproWilks", "kolmogorovSmirnov"):
            tests[name] = bool(v[name])
        c.setdefault("options", {})["significanceLevel"] = alpha
    elif k == "two_way":
        c["experimentalDesign"] = v["design"]
        c.setdefault("options", {})["includeInteractionTerm"] = bool(v["interaction"])
        pt = c.setdefault("postTests", {})
        pw = pt.setdefault("pairwiseTests", {})
        pw["meansDesignType"] = v["compare"]
        tests = post_tests("TWO_WAY_ANOVA", v["design"], v["compare"])
        pt["type"] = "PAIRWISE_TESTS" if tests else "NO_TESTS"
        if tests:
            pw.setdefault("pairwiseDesign", {})["type"] = "ALL_VS_ALL"
            _mc(pw.setdefault("multipleComparisons", {}), v["test"] if v["test"] in tests else tests[0], alpha)
    elif k == "multiple_t":
        c["test"] = v["design"]
        mc = c.setdefault("multipleComparisons", {})
        mc["type"] = v["correction"]
        if v["correction"] == "FDR":
            mc.setdefault("fdr", {})["test"] = "BENJAMINI_KRIEGER_YEKUTIELI"
            mc["fdr"].setdefault("options", {})["discoveryLevel"] = 0.01
        elif v["correction"] == "STATISTICAL":
            mc.setdefault("statistical", {})["test"] = "HOLM_SIDAK"
    elif k in ("correlation", "corr_matrix", "mv_corr"):
        c["experimentalDesign"] = v["design"]
        opt = c.setdefault("options", {})
        opt.update(confidenceLevel=float(v["level"]), excludeIncompleteRows=bool(v["complete"]),
                   pValueTailType="P_VALUE_ONE_TAILED" if v["one_tailed"] else "P_VALUE_TWO_TAILED")
        if k != "correlation" or v["pairs"] == "ALL_VS_ALL":  # every pair (Prism names two data sets anyway)
            first = sets[0] if sets else 0
            pair = [first, sets[1] if len(sets) > 1 else first]
            c["pairwiseDesign"] = {"type": "ALL_VS_ALL", "controlID": _ref(table, first) if table is not None else
                                   {"col": {"idx": first}},
                                   "selectedPairID": ([{"col": {"idx": -1}}, _ref(table, first)] if k == "correlation"
                                                      else [_ref(table, i) if table is not None else {"col": {"idx": i}}
                                                            for i in pair])}
    elif k == "p_values":
        mc = c.setdefault("multipleComparisons", {})
        if v["method"].startswith("BENJAMINI"):
            mc["type"] = "FDR"
            f = mc.setdefault("fdr", {})
            f["test"] = v["method"]
            f.setdefault("options", {})["discoveryLevel"] = float(v["q"])
        else:
            mc["type"] = "STATISTICAL"
            st = mc.setdefault("statistical", {})
            st["test"] = v["method"]
            st.setdefault("options", {})["significanceLevel"] = alpha
    elif k in ("nonlinear", "interpolate"):
        c["model"] = EQ.model(v["equation"], sets or [0])
        if k == "nonlinear":
            c.setdefault("confidence", {})["confidenceLevel"] = float(v["level"])
    elif k == "transform":
        sf = c.setdefault("calc", {}).setdefault("standardFunction", {})
        c["calc"]["transformType"] = "STANDARD"
        sf["xTransform"] = {**sf.get("xTransform", {}), "enabled": bool(v["x"]), "function": v["x"] or "X*K",
                            "k": float(v["k"])}
        sf["yTransform"] = {**sf.get("yTransform", {}), "enabled": bool(v["y"]), "function": v["y"] or "Y*K",
                            "kSameForAll": True, "k": float(v["k"]), "kList": []}
    elif k == "normalize":
        calc = c.setdefault("calc", {})
        calc["value_0"] = {**calc.get("value_0", {}), "defineAs": v["zero"],
                           "customValue": float(v["zero_value"]) if v["zero"] == "CUSTOM" else 0.0}
        calc["value_100"] = {**calc.get("value_100", {}), "defineAs": v["hundred"],
                             "customValue": float(v["hundred_value"]) if v["hundred"] == "CUSTOM" else "undefined"}
        c.setdefault("options", {})["reportResultsAs"] = "FRACTIONS" if v["fractions"] else "PERCENTAGES"
    elif k == "baseline":
        data = c.setdefault("data", {})
        if v["where"] in ("FIRST_ROW", "LAST_ROW"):
            data["baselineType"] = "BASELINE_ROW"
            data.setdefault("rowBaseline", {})["type"] = v["where"]
        else:
            data["baselineType"] = "BASELINE_COLUMN"
            data.setdefault("columnBaseline", {})["type"] = v["where"]
        c.setdefault("calc", {})["expression"] = v["expr"]
    elif k == "row_stats":
        c.setdefault("calc", {})["statistics"] = v["stat"]
        c.setdefault("data", {})["scope"] = "COLUMN" if v["per_set"] else "TABLE"
        c.setdefault("options", {})["confidenceLevel"] = float(v["level"])
    elif k == "three_way":
        c.setdefault("report", {})["means"] = bool(v["means"])
        c["experimentalDesign"] = "ORDINARY_ANOVA"
    elif k == "mv_desc":
        c.setdefault("options", {})["confidenceLevel"] = float(v["level"])
        calc = c.setdefault("calc", {})
        for name in ("medianCI", "harmonicMean", "harmonicMeanCI", "quadraticMean", "quadraticMeanCI"):
            calc[name] = bool(v["more"])
    elif k == "spline":
        cv = c.setdefault("calc", {}).setdefault("curve", {})
        cv.update(type=v["type"], resolution=v["resolution"], knotCount=max(2, int(v.get("knots") or 4)))
        if table is not None and table.x is not None:  # Prism: 4 curve points per data row
            cv["segmentCount"] = 4 * sum(1 for q in table.x_values() if q is not None)
    elif k == "observed_expected":
        i = sets[0] if sets else 0
        c.setdefault("data", {})["datasetID"] = _ref(table, i) if table is not None else {"col": {"idx": i}}
        c["data"]["expectedValuesType"] = v["as"]
        calc = c.setdefault("calc", {})
        calc["test"], calc["ciMethod"] = v["test"], v["ci"]
        obs = [x for x in (table.values(i, 0) if table is not None else []) if x is not None]
        nums = []
        for q in str(v.get("expected") or "").replace(";", ",").split(","):
            try:
                nums.append(float(q))
            except ValueError:
                pass
        if len(nums) < len(obs):  # not given: equal shares
            nums = [100 / len(obs) if v["as"] == "PERCENTAGES" else sum(obs) / len(obs)] * len(obs) if obs else []
        tot = sum(obs) or 1.0
        rows = table.row_titles.subcolumns[0] if table is not None and table.row_titles is not None and \
            table.row_titles.subcolumns else []
        calc["outcomes"] = [{"rowIdx": r + 1, "rowTitle": rows[r] if r < len(rows) else "", "observedCount": float(o),
                             "expectedCount": (tot * e / 100) if v["as"] == "PERCENTAGES" else float(e),
                             "observedPercentage": 100 * o / tot,
                             "expectedPercentage": float(e) if v["as"] == "PERCENTAGES" else 100 * e / tot}
                            for r, (o, e) in enumerate(zip(obs, nums, strict=False))]
    elif k == "fraction":
        calc = c.setdefault("calc", {})
        calc["type"] = v["of"]
        calc["ci"] = {**calc.get("ci", {}), "calculate": bool(v["ci"]), "method": v["method"],
                      "level": float(v["level"])}
        c.setdefault("options", {})["reportResultsAs"] = "PERCENTAGES" if v["pct"] else "FRACTIONS"
    elif k == "prune":
        calc = c.setdefault("calc", {})
        calc["pruneByRange"] = v["mode"] == "RANGE"
        xs = [q for q in (table.x_values() if table is not None and table.x is not None else []) if q is not None]
        lo = float(v["from"]) if v.get("from") is not None else (min(xs) if xs else 0.0)
        hi = float(v["to"]) if v.get("to") is not None else (max(xs) if xs else 0.0)
        calc["xRangeToKeep"] = {"from": lo, "to": hi}
        calc["averageType"] = "EVERY_OTHER_ROW" if v["mode"] == "PAIRS" else "EVERY_NTH_ROW"
        calc["n"] = max(2, int(v["n"]))
        calc["averageOnly"] = {"greaterThan": bool(v["above"]), "xThreshold": float(v["threshold"])}
    elif k == "select":
        n = len(table.datasets) if table is not None else 0
        letters = [chr(65 + i) for i in range(n)]
        defs = [q.strip() for q in str(v.get("defs") or "").split(",") if q.strip()] or letters
        c["transforms"] = [{"title": (_ref(table, letters.index(dd.upper()))["col"]["title"]
                                      if dd.upper() in letters else dd),
                            "definition": dd, "enabled": True, "variableIdx": i, "parameter": "undefined",
                            "variableViewIdx": i} for i, dd in enumerate(defs)]
        a, b = int(v.get("first") or 0), int(v.get("last") or 0)
        c["rowFilters"] = {"range": {"from": a, "to": b} if a > 0 and b > 0 else {"from": -1, "to": -1},
                           "variableValue": [], "variableVariable": []}
    elif k == "extract":
        c["resultTableFormat"] = v["fmt"]
        c["includeVarNamePrefix"] = bool(v["prefix"])
        ref = (lambda i: _ref(table, int(i))) if table is not None else (lambda i: {"col": {"idx": int(i)}})
        c["dataArrangement"] = ({"responseVariable": ref(v["y"]), "rowFactorVariable": ref(v["rows"]),
                                 "columnFactorVariable": ref(v["cols"])} if v["fmt"] == "GROUPED" else
                                {"responseVariable": ref(v["y"]), "groupingVariable": ref(v["rows"])})
    elif k == "deming":
        m = c.setdefault("model", {})
        m.update(sdType=v["sd"], xSD=float(v["xsd"]), ySD=float(v["ysd"]))
        c.setdefault("data", {})["handleReplicatesAs"] = v["reps"]
    elif k == "smooth":
        calc = c.setdefault("calc", {})
        calc["type"], calc["integralY0"] = v["what"], float(v["y0"])
        calc["smoothing"] = {**calc.get("smoothing", {}), "enabled": bool(v["smooth"]) or v["what"] == "CURVE",
                             "neighborCount": max(1, int(v["neighbors"])), "polynomialOrder": int(v["order"])}
    elif k == "contingency":
        c.setdefault("calc", {})["method"] = v["method"]
        c.setdefault("options", {})["significanceLevel"] = alpha
    elif k == "frequency":
        calc = c.setdefault("calc", {})
        calc["distributionType"] = "CUMULATIVE_FREQUENCY" if v["cumulative"] else "FREQUENCY"
        calc["tabulate"] = v["tabulate"]
        bw = float(v.get("bin") or 0.0)
        calc["binWidth"] = {**calc.get("binWidth", {}), "type": "BIN_WIDTH" if bw > 0 else "AUTO_BINS",
                            **({"value": bw} if bw > 0 else {})}
    elif k == "outliers":
        calc = c.setdefault("calc", {})
        calc["method"], calc["q"], calc["alpha"] = v["method"], float(v["q"]), float(v["grubbs_alpha"])
    elif k == "bland_altman":
        c["data"] = {"methodAID": _ref(table, sets[0]), "methodBID": _ref(table, sets[1])} if len(sets) >= 2 else \
            c.get("data", {})
        c.setdefault("calc", {})["type"] = v["calc"]
    elif k == "roc":
        if len(sets) >= 2:
            c["data"] = {"controlID": _ref(table, sets[0]), "patientID": _ref(table, sets[1])}
        opt = c.setdefault("options", {})
        opt.update(confidenceMethod=v["ci"], reportResultsAs=v["as"], confidenceLevel=float(v["level"]))
    elif k == "auc":
        base = c.setdefault("calc", {}).setdefault("baseline", {})
        base.update(useSpecificValue=True, value=float(v["baseline"]))
        c["calc"].setdefault("peak", {})["calcPositivePeaksOnly"] = bool(v["positive"])
    elif k == "logistic":
        c.setdefault("options", {})["confidenceLevel"] = float(v["level"])
    elif k == "nested_t":
        c.setdefault("options", {})["significanceLevel"] = alpha
    elif k in ("mv_linear", "mv_logistic") and table is not None:
        y = int(v["y"])
        m = c.setdefault("model", {})
        m["dependentVariable"] = _ref(table, y)
        m["modelDef"], m["variableInfo"] = _model(table, sets, y, columns, intercept=True)
        if k == "mv_logistic":
            m["variableInfo"][0] = {**m["variableInfo"][0], "variableType": "CATEGORICAL",
                                    "referenceLevelType": "AUTO_FIRST_LEVEL"}
            m["outcome0"], m["outcome1"] = _outcomes(columns, y)
            m["variableInfo"][0].update(referenceLevelValue=m["outcome0"]["value"], levelCount=2,
                                        levelOrderType="VISUAL")
    elif k == "cox" and table is not None:
        ti, ei = int(v["time"]), int(v["event"])
        m = c.setdefault("model", {})
        m["timeVariable"], m["dependentVariable"] = _ref(table, ti), _ref(table, ei)
        m["outcome0"], m["outcome1"] = _outcomes(columns, ei)
        preds = [i for i in sets if i not in (ti, ei)]
        m["modelDef"] = [{"componentType": "ADDITIVE", "variables": [_ref(table, i)]} for i in preds]
        o0 = m["outcome0"]["value"]
        m["variableInfo"] = [{"variable": _ref(table, ti), "variableType": "CONTINUOUS"},
                             {"variable": _ref(table, ei), "variableType": "CATEGORICAL",
                              "referenceLevelType": "AUTO_FIRST_LEVEL", "referenceLevelValue": o0, "levelCount": 2,
                              "levelOrderType": "VISUAL"}, *[_info(table, i, columns) for i in preds]]
    elif k == "pca":
        if table is not None:
            nums = [i for i in sets if not any(isinstance(x, str) for x in columns[i])]
            c.setdefault("data", {})["variables"] = [_ref(table, i) for i in nums]
        calc = c.setdefault("calc", {})
        calc["method"], calc["componentCount"] = v["method"], int(v["components"])
    elif k in ("hclust", "kmeans"):
        if table is not None:
            nums = [i for i in sets if not any(isinstance(x, str) for x in columns[i])]
            texts = [i for i in sets if i not in nums]
            data = {"variables": [_ref(table, i) for i in nums]}
            if k == "hclust":
                data = {"inputType": "ROWS_COLUMNS" if v["columns"] else "ROWS", **data,
                        "label": {"type": "VARIABLE", "variable": _ref(table, texts[0])} if texts else
                        {"type": "NO", "variable": None}}
            c["data"] = data
        calc = c.setdefault("calc", {})
        if k == "hclust":
            calc["linkage"] = v["linkage"]
            calc["columnTransform"] = "NONE" if v["transform"] != "STANDARDIZE" else "STANDARDIZE"
            calc["rowTransform"] = "CENTER" if v["transform"] == "ROW_CENTER" else "NONE"
            n = int(v["clusters"] or 0)
            dc = c.setdefault("defineClusters", {})
            dc["rows"] = {**dc.get("rows", {}), "method": "NUMBER_OF_CLUSTERS" if n > 0 else "NONE",
                          "clusterCount": max(n, 2)}
        else:
            lo = max(1, int(v["min"] or 1))
            calc["transform"] = v["transform"]
            calc["clusterCount"] = {"min": lo, "max": max(lo, int(v["max"] or lo))}
    elif k == "nway" and table is not None:
        y = int(v["y"])
        factors = [i for i in sets if i != y and any(isinstance(x, str) for x in columns[i])]
        import itertools

        terms = [[]] + [list(cb) for r in range(1, len(factors) + 1)
                        for cb in itertools.combinations(range(len(factors)), r)]
        m = c.setdefault("model", {})
        m["response"] = {"variable": {"id": _ref(table, y)}, "definition": ""}
        m["predictor"] = {"variables": [{"id": _ref(table, i), "effectType": "FIXED"} for i in factors],
                          "definition": [[{"varIdx": j, "varID": _ref(table, factors[j])} for j in term]
                                         for term in terms]}
        c["postTests"] = {"type": "NO_TESTS"}
    return c


def options_of(choice: Choice, content: dict) -> dict[str, Any]:
    """The dialog's option values read back from parameter content (to edit
    an existing analysis)."""
    v = initial(choice)
    k = choice.key
    if k in MV_OF:
        vd = content.get("variableDesign") or {}

        def idx(ref, d):
            return ((ref or {}).get("col") or {}).get("idx", d)
        v.update(options_of(by_key(MV_OF[k]), content))
        v.update(y=idx((vd.get("responseList") or [None])[0], v["y"]),
                 factor=idx((vd.get("factorList") or [None])[0], v["factor"]))
        if "x" in v:
            v["x"] = idx(vd.get("x"), v["x"])
        if "subject" in v:
            v["subject"] = idx(vd.get("subject"), v["subject"])
        if "post" in v:
            pt = content.get("postTests") or {}
            v["post"] = ((pt.get("pairwiseTests") or {}).get("pairwiseDesign") or {}).get("type", "NO_TESTS") \
                if pt.get("type") == "PAIRWISE_TESTS" else "NO_TESTS"
        return {f.key: v[f.key] for f in choice.fields}
    g = content.get
    opt = g("options", {}) or {}
    if "alpha" in v:
        v["alpha"] = opt.get("significanceLevel", v["alpha"])
    if k in ("t_test", "one_way", "one_sample", "two_way", "correlation"):
        v["design"] = g("experimentalDesign", v["design"])
    if k in ("column_stats", "correlation"):
        v["level"] = opt.get("confidenceLevel", v["level"])
    if k == "one_sample":
        v["mu"] = (g("calc", {}) or {}).get("hypotheticalValue", v["mu"])
    if k == "normality":
        for name, on in ((g("calc", {}) or {}).get("tests", {}) or {}).items():
            if name in v:
                v[name] = bool(on)
    if k in ("one_way", "two_way"):
        pt = g("postTests", {}) or {}
        pw = pt.get("pairwiseTests", {}) or {}
        mc = pw.get("multipleComparisons", {}) or {}
        if k == "one_way":
            v["compare"] = "NONE" if pt.get("type") != "PAIRWISE_TESTS" else \
                (pw.get("pairwiseDesign", {}) or {}).get("type", "ALL_VS_ALL")
            v["control"] = ((pw.get("pairwiseDesign", {}) or {}).get("controlID") or {}).get("col", {}).get("idx", 0)
        else:
            v["compare"] = pw.get("meansDesignType", "NO_TESTS") if pt.get("type") == "PAIRWISE_TESTS" else "NO_TESTS"
            v["interaction"] = opt.get("includeInteractionTerm", True)
        t = mc.get("type", "STATISTICAL")
        v["test"] = {"FDR": "FDR", "NO_CORRECTION": "FISHER_LSD"}.get(t) or mc.get("statistical", {}).get("test", "TUKEY")
        if t == "STATISTICAL":
            v["alpha"] = mc.get("statistical", {}).get("options", {}).get("significanceLevel", v["alpha"])
    if k == "multiple_t":
        v["design"] = g("test", v["design"])
        v["correction"] = (g("multipleComparisons", {}) or {}).get("type", v["correction"])
    if k == "contingency":
        v["method"] = (g("calc", {}) or {}).get("method", v["method"])
    calc = g("calc", {}) or {}
    if k == "frequency":
        v["cumulative"] = calc.get("distributionType") == "CUMULATIVE_FREQUENCY"
        bw = calc.get("binWidth", {}) or {}
        v["bin"] = float(bw.get("value", 0.0)) if bw.get("type") == "BIN_WIDTH" else 0.0
    if k == "outliers":
        v.update(method=calc.get("method", v["method"]), q=calc.get("q", v["q"]),
                 grubbs_alpha=calc.get("alpha", v["grubbs_alpha"]))
    if k == "bland_altman":
        v["calc"] = calc.get("type", v["calc"])
    if k == "roc":
        v.update(ci=opt.get("confidenceMethod", v["ci"]), level=opt.get("confidenceLevel", v["level"]))
        v["as"] = opt.get("reportResultsAs", v["as"])
    if k == "auc":
        v["baseline"] = (calc.get("baseline", {}) or {}).get("value", v["baseline"])
        v["positive"] = (calc.get("peak", {}) or {}).get("calcPositivePeaksOnly", v["positive"])
    if k == "logistic":
        v["level"] = opt.get("confidenceLevel", v["level"])
    m = g("model", {}) or {}
    if k in ("mv_linear", "mv_logistic"):
        v["y"] = ((m.get("dependentVariable") or {}).get("col") or {}).get("idx", v["y"])
    if k == "cox":
        v["time"] = ((m.get("timeVariable") or {}).get("col") or {}).get("idx", v["time"])
        v["event"] = ((m.get("dependentVariable") or {}).get("col") or {}).get("idx", v["event"])
    if k == "pca":
        v["method"] = calc.get("method", v["method"])
        v["components"] = float(calc.get("componentCount", v["components"]))
    if k == "hclust":
        v["linkage"] = calc.get("linkage", v["linkage"])
        v["transform"] = "ROW_CENTER" if calc.get("rowTransform") == "CENTER" else calc.get("columnTransform", "NONE")
        rows = ((g("defineClusters", {}) or {}).get("rows") or {})
        v["clusters"] = float(rows.get("clusterCount", 3)) if rows.get("method") == "NUMBER_OF_CLUSTERS" else 0.0
        v["columns"] = (g("data", {}) or {}).get("inputType") == "ROWS_COLUMNS"
    if k == "kmeans":
        cc = calc.get("clusterCount", {}) or {}
        v.update(min=float(cc.get("min", v["min"])), max=float(cc.get("max", v["max"])),
                 transform=calc.get("transform", v["transform"]))
    if k == "spline":
        cv = calc.get("curve", {}) or {}
        v.update(type=cv.get("type", v["type"]), resolution=cv.get("resolution", v["resolution"]),
                 knots=float(cv.get("knotCount", v["knots"])))
    if k == "three_way":
        v["means"] = bool((g("report", {}) or {}).get("means", False))
    if k == "mv_desc":
        v["level"] = opt.get("confidenceLevel", v["level"])
        v["more"] = bool(calc.get("medianCI") or calc.get("harmonicMean") or calc.get("quadraticMean"))
    if k == "extract":
        arr = g("dataArrangement", {}) or {}

        def idx(key, d):
            return ((arr.get(key) or {}).get("col") or {}).get("idx", d)
        v.update(fmt=g("resultTableFormat", v["fmt"]), prefix=bool(g("includeVarNamePrefix", v["prefix"])),
                 y=idx("responseVariable", v["y"]),
                 rows=idx("rowFactorVariable" if g("resultTableFormat") != "COLUMN" else "groupingVariable", v["rows"]),
                 cols=idx("columnFactorVariable", v["cols"]))
    if k == "nway":
        v["y"] = (((m.get("response") or {}).get("variable") or {}).get("id") or {}).get("col", {}).get("idx", v["y"])
    return v


def for_class(analysis_class: str) -> Choice | None:
    return next((c for _, cs in CATALOG for c in cs if c.analysis_class == analysis_class), None)


def describe(analysis_class: str, content: dict) -> str:
    """The analysis in words, e.g. "Welch's t test" (its design when the
    catalog knows it)."""
    c = for_class(analysis_class)
    if c is None:
        return analysis_class.replace("_", " ").capitalize()
    v = options_of(c, content)
    if c.key == "t_test":
        return T_SHORT.get(v["design"], c.label)
    design = next((f for f in c.fields if f.key == "design"), None)
    if design is not None:
        return dict(design.options).get(v["design"], c.label)
    return c.label
