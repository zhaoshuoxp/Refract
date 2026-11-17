"""New data tables (docs/ui-spec.md §6): the table kinds, the data formats
each accepts, and sample data to start from. The descriptions and the sample
numbers are our own."""

from __future__ import annotations

from dataclasses import dataclass

from .document import DataSet, DataTable, subcolumns_for

FORMAT_NAMES = {
    "y_single": "One value per cell",
    "y_replicates": "Replicate values side by side",
    "y_sd_n": "Mean, SD and N",
    "y_sd": "Mean and SD",
    "y_se": "Mean and SEM",
}


@dataclass
class Kind:
    key: str
    label: str
    description: str
    formats: list[str]
    sets: int  # data sets of an empty table
    set_word: str = "Data sets"
    x: bool = False  # has an X column
    row_titles: bool = True
    replicates: bool = True  # the replicate count applies


KINDS = [
    Kind("xy", "XY", "X is a number (dose, time, concentration); each data set is a Y measured at each X. "
         "For curves, regression and correlation.", ["y_single", "y_replicates", "y_sd_n", "y_sd", "y_se"], 2, x=True),
    Kind("column", "Column", "Each column is a group; one factor. For t tests, one-way ANOVA and "
         "descriptive statistics.", ["y_single", "y_sd_n", "y_sd", "y_se"], 3, "Groups (columns)", replicates=False),
    Kind("grouped", "Grouped", "Two factors: rows are one, data sets the other, with replicates side by side. "
         "For two-way ANOVA and multiple t tests.", ["y_replicates", "y_single", "y_sd_n", "y_sd", "y_se"], 2),
    Kind("contingency", "Contingency", "Counts of subjects: rows are groups, columns are outcomes. "
         "For Fisher's exact and chi-square tests.", ["y_single"], 2, "Outcomes (columns)", replicates=False),
    Kind("survival", "Survival", "One row per subject: the time in X, and 1 (event) or 0 (censored) in the "
         "column of its group. For Kaplan-Meier curves.", ["y_single"], 2, "Groups", x=True, replicates=False),
    Kind("parts_of_whole", "Parts of whole", "Values that add up to a whole, one per row. For pie charts and "
         "fractions of total.", ["y_single"], 1, replicates=False),
    Kind("multivariable", "Multiple variables", "One row per observation, one column per variable "
         "(numbers or text categories). For multiple regression and PCA.", ["y_single"], 3, "Variables",
         row_titles=False, replicates=False),
    Kind("nested", "Nested", "Groups with subgroups: each data set is a group, each subcolumn a subgroup. "
         "For nested t tests and nested one-way ANOVA.", ["y_replicates"], 2, "Groups", row_titles=False),
]


def kind(key: str) -> Kind:
    return next(k for k in KINDS if k.key == key)


# ------------------------------------------------------------- sample data
def _txt(v) -> str:
    return "" if v is None else (str(int(v)) if isinstance(v, float) and v.is_integer() else str(v))


SAMPLES: dict[str, dict] = {
    "xy": {"x_title": "Time (h)", "x": [0, 2, 4, 8, 12, 24],
           "sets": {"Control": [[10.2, 14.8, 21.5, 33.0, 41.7, 48.9], [9.6, 15.9, 20.1, 35.2, 40.3, 50.4],
                                [11.0, 13.7, 22.8, 31.9, 43.5, 47.2]],
                    "Treated": [[10.4, 12.1, 15.0, 19.8, 24.6, 30.1], [9.9, 12.8, 14.2, 21.0, 23.3, 31.7],
                                [10.8, 11.6, 16.3, 18.9, 25.8, 29.4]]}},
    "column": {"sets": {"Vehicle": [[4.1, 3.8, 4.6, 5.0, 4.3, 3.9]], "Low dose": [[5.2, 4.9, 5.8, 6.1, 5.5, 4.7]],
                        "High dose": [[6.9, 7.4, 6.2, 7.8, 7.1, 6.6]]}},
    "grouped": {"rows": ["Wild type", "Mutant A", "Mutant B"],
                "sets": {"Untreated": [[12, 18, 25], [14, 17, 23], [11, 20, 27]],
                         "Treated": [[30, 22, 26], [33, 21, 29], [28, 24, 24]]}},
    "contingency": {"rows": ["Exposed", "Not exposed"],
                    "sets": {"Disease": [[42, 18]], "No disease": [[58, 82]]}},
    "survival": {"x_title": "Days", "groups": {
        "Standard": [(14, 1), (25, 1), (31, 0), (40, 1), (52, 1), (60, 0), (71, 1), (90, 0)],
        "New treatment": [(22, 1), (38, 0), (47, 1), (66, 1), (75, 0), (88, 1), (90, 0), (90, 0)]}},
    "parts_of_whole": {"rows": ["Protein", "Fat", "Carbohydrate", "Water"], "sets": {"Composition": [[21, 9, 48, 22]]}},
    "multivariable": {"sets": {"Age": [[34, 51, 47, 29, 62, 55, 40, 38]],
                               "Dose": [[10, 20, 20, 10, 30, 30, 20, 10]],
                               "Response": [[2.1, 4.0, 3.6, 1.8, 5.9, 5.1, 3.3, 2.4]],
                               "Sex": [["F", "M", "F", "M", "F", "M", "M", "F"]]}},
    "nested": {"sets": {"Control": [[5.1, 4.8, 5.3, 4.9], [6.0, 5.7, 6.2, 5.8], [4.6, 4.9, 4.4, 4.7]],
                        "Treated": [[7.2, 6.9, 7.5, 7.0], [6.4, 6.6, 6.1, 6.8], [7.9, 8.1, 7.6, 7.7]]}},
}


def _summary(reps: list[list], fmt: str) -> list[list]:
    """Replicates -> entered statistics (mean, SD/SEM, N) per row."""
    import statistics as st

    rows = len(reps[0])
    out = [[], [], []]
    for r in range(rows):
        vals = [rep[r] for rep in reps if rep[r] is not None]
        m = st.mean(vals)
        sd = st.stdev(vals) if len(vals) > 1 else 0.0
        out[0].append(round(m, 3))
        out[1].append(round(sd / (len(vals) ** 0.5) if fmt == "y_se" else sd, 3))
        out[2].append(len(vals))
    return out[: subcolumns_for(fmt)]


def make(key: str, title: str, data_format: str | None = None, replicates: int = 3, n_sets: int | None = None,
         sample: bool = False) -> DataTable:
    """A new table of that kind: empty (n_sets data sets) or with sample data."""
    k = kind(key)
    fmt = data_format or k.formats[0]
    if fmt not in k.formats:
        raise ValueError(f"{k.label} tables do not take {fmt}")
    reps = replicates if fmt == "y_replicates" else 1
    s = SAMPLES[key] if sample else {}
    names: list[str]
    if key == "survival":
        names = list(s["groups"]) if sample else [f"Group {chr(65 + i)}" for i in range(n_sets or k.sets)]
    else:
        names = list(s["sets"]) if sample else [f"Data Set-{chr(65 + i)}" if key != "multivariable"
                                                else f"Variable {i + 1}" for i in range(n_sets or k.sets)]
    if not sample and key == "nested":
        names = [f"Group {chr(65 + i)}" for i in range(n_sets or k.sets)]
    if key == "nested":
        reps = len(s["sets"][names[0]]) if sample else max(1, replicates)
    nsub = subcolumns_for(fmt, reps)
    columns: list[list[list[str]]] = []
    x_cells: list[str] = []
    n_rows = 0
    if sample and key == "survival":
        groups = s["groups"]
        rows = [(t, g, code) for g, subj in groups.items() for t, code in subj]
        n_rows = len(rows)
        x_cells = [_txt(t) for t, _g, _c in rows]
        columns = [[[_txt(c) if g == name else "" for _t, g, c in rows]] for name in names]
    elif sample:
        for name in names:
            data = [list(v) for v in s["sets"][name]]
            if key in ("xy", "grouped"):
                if fmt == "y_single":
                    data = data[:1]
                elif fmt == "y_replicates":
                    data = (data * reps)[:reps]
                else:
                    data = _summary(data, fmt)
            elif key == "column" and fmt != "y_single":  # the column's values as mean / SD / N
                data = _column_summary(data[0], fmt)
            columns.append([[_txt(v) for v in sc] for sc in data])
            n_rows = max(n_rows, max(len(sc) for sc in data))
        if k.x:
            x_cells = [_txt(v) for v in s["x"]]
    else:
        columns = [[[] for _ in range(nsub)] for _ in names]
    for cols in columns:
        for sc in cols:
            sc.extend([""] * (n_rows - len(sc)))
    datasets = [DataSet(name, cols) for name, cols in zip(names, columns, strict=True)]
    row_titles = None
    if k.row_titles:
        rt = [str(v) for v in s.get("rows", [])] if sample else []
        rt = (rt + [""] * n_rows)[:n_rows]
        row_titles = DataSet(None, [rt], role="RT", format="text")
    x = None
    if k.x:
        x = DataSet(s.get("x_title") if sample else ("Time" if key == "survival" else "X"),
                    [(x_cells + [""] * n_rows)[:n_rows]], role="X", format="y_single")
    return DataTable(title, key, fmt, datasets, n_rows, replicates=reps, row_titles=row_titles, x=x)


def _column_summary(vals: list, fmt: str) -> list[list]:
    """A column group's values entered as one row of statistics."""
    import statistics as st

    m, sd, n = st.mean(vals), st.stdev(vals), len(vals)
    stats = [round(m, 3), round(sd / n ** 0.5 if fmt == "y_se" else sd, 3), n]
    return [[v] for v in stats[: subcolumns_for(fmt)]]
