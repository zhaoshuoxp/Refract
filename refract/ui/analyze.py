"""The Analyze dialog (pick an analysis and the data sets it reads) and the
parameter dialog of each analysis (docs/ui-spec.md §6). The choices and their
options come from refract.stats.catalog."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..model.document import DataTable
from ..stats import catalog
from ..stats.catalog import TEST_NAMES, Choice, Field

KIND_NAMES = {"column": "Column", "grouped": "Grouped", "xy": "XY", "survival": "Survival",
              "contingency": "Contingency", "parts_of_whole": "Parts of whole", "multivariable": "Multiple variables",
              "nested": "Nested"}
COMPARISON_TAB = {"compare", "test", "control", "pairs"}  # fields shown on the "Multiple comparisons" tab


def _set_label(t: DataTable, i: int) -> str:
    from .table_model import _letters

    ds = t.datasets[i]
    return f"{_letters(i)}: {ds.title}" if ds.title else _letters(i)


class AnalyzeDialog(QDialog):
    """Which analysis, of which data sets of `table`."""

    def __init__(self, table: DataTable, parent=None):
        super().__init__(parent)
        self.table = table
        self.setWindowTitle("Analyze Data")
        self.resize(860, 460)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setMinimumWidth(500)
        self.tree.itemDoubleClicked.connect(self._double_clicked)  # bound methods, not lambdas holding self
        self.tree.currentItemChanged.connect(self._changed)
        first = None
        for group, choices in catalog.CATALOG:
            sec = QTreeWidgetItem(self.tree, [group])
            f = sec.font(0)
            f.setBold(True)
            sec.setFont(0, f)
            sec.setFlags(Qt.ItemIsEnabled)
            for c in choices:
                it = QTreeWidgetItem(sec, [c.label])
                it.setData(0, Qt.UserRole, c.key)
                if table.kind not in c.kinds:
                    it.setDisabled(True)
                    it.setToolTip(0, f"Needs a {' or '.join(KIND_NAMES.get(k, k) for k in sorted(c.kinds))} table")
                elif first is None:
                    first = it
            sec.setExpanded(True)
        self.sets = QListWidget()
        for i in range(len(table.datasets)):
            it = QListWidgetItem(_set_label(table, i))
            it.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            it.setCheckState(Qt.Checked)
            self.sets.addItem(it)
        self.sets.itemChanged.connect(self._validate)
        self.note = QLabel()
        self.note.setObjectName("muted")
        self.note.setWordWrap(True)
        right = QVBoxLayout()
        right.addWidget(QLabel(f"Data table: <b>{table.title}</b> ({KIND_NAMES.get(table.kind, table.kind)})"))
        right.addWidget(QLabel("Analyze these data sets:"))
        right.addWidget(self.sets, 1)
        right.addWidget(self.note)
        row = QHBoxLayout()
        row.addWidget(self.tree, 3)
        row.addLayout(right, 2)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        v = QVBoxLayout(self)
        v.addLayout(row, 1)
        v.addWidget(self.buttons)
        if first is not None:
            self.tree.setCurrentItem(first)
        self._validate()

    def _double_clicked(self, item, _column) -> None:
        if item.data(0, Qt.UserRole) and not item.isDisabled():
            self.accept()

    def choice(self) -> Choice | None:
        it = self.tree.currentItem()
        key = it.data(0, Qt.UserRole) if it is not None and not it.isDisabled() else None
        return catalog.by_key(key) if key else None

    def select(self, key: str) -> None:
        for i in range(self.tree.topLevelItemCount()):
            sec = self.tree.topLevelItem(i)
            for k in range(sec.childCount()):
                if sec.child(k).data(0, Qt.UserRole) == key:
                    self.tree.setCurrentItem(sec.child(k))

    def selected_sets(self) -> list[int]:
        return [i for i in range(self.sets.count()) if self.sets.item(i).checkState() == Qt.Checked]

    def set_checked(self, sets: list[int]) -> None:
        for i in range(self.sets.count()):
            self.sets.item(i).setCheckState(Qt.Checked if i in sets else Qt.Unchecked)

    def _changed(self, *_a) -> None:
        self._validate()

    def _validate(self, *_a) -> None:
        c = self.choice()
        ok, msg = c is not None, ""
        if c is None:
            msg = "No analysis of this kind of table is available yet." if self.tree.currentItem() is None else \
                "Choose an analysis."
        else:
            n = len(self.selected_sets())
            if n < c.min_sets or (c.max_sets is not None and n > c.max_sets):
                need = f"exactly {c.min_sets}" if c.min_sets == c.max_sets else \
                    f"at least {c.min_sets}" if c.max_sets is None else f"{c.min_sets} to {c.max_sets}"
                ok, msg = False, f"This analysis needs {need} data set(s); {n} selected."
        self.note.setText(msg)
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(ok)


class ParametersDialog(QDialog):
    """The options of one analysis, on tabs."""

    def __init__(self, choice: Choice, table: DataTable, sets: list[int], values: dict | None = None, parent=None):
        super().__init__(parent)
        self.choice, self.table, self.sets = choice, table, sets
        self.setWindowTitle(f"Parameters: {choice.short or choice.label}")
        self.widgets: dict[str, QWidget] = {}
        v = {**catalog.initial(choice), **(values or {})}
        tabs = QTabWidget()
        forms: dict[str, QFormLayout] = {}

        def form(name: str) -> QFormLayout:
            if name not in forms:
                page = QWidget()
                forms[name] = QFormLayout(page)
                forms[name].setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
                tabs.addTab(page, name)
            return forms[name]

        main = form("Options")
        if not choice.fields:
            main.addRow(QLabel("This analysis has no options here yet; Prism's defaults are used."))
        for f in choice.fields:
            w = self._widget(f, v.get(f.key))
            self.widgets[f.key] = w
            (form("Multiple comparisons") if f.key in COMPARISON_TAB else main).addRow(
                f.label if f.kind != "bool" else "", w)
        for key in ("design", "compare"):
            w = self.widgets.get(key)
            if isinstance(w, QComboBox):
                w.currentIndexChanged.connect(self._refill_tests)
        self._refill_tests(selected=v.get("test"))
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(f"<b>{choice.label}</b>"))
        lay.addWidget(tabs, 1)
        lay.addWidget(buttons)
        self.resize(520, 320)

    def _widget(self, f: Field, value) -> QWidget:
        if f.kind == "choice":
            w = QComboBox()
            for key, label in f.options:
                w.addItem(label, key)
            w.setCurrentIndex(max(0, w.findData(value)))
            return w
        if f.kind == "tests":
            return QComboBox()
        if f.kind == "control":
            w = QComboBox()
            for k, i in enumerate(self.sets):
                w.addItem(_set_label(self.table, i), k)  # the index among the analysed data sets
            w.setCurrentIndex(max(0, w.findData(value)))
            return w
        if f.kind == "pairs":  # pairs of the analysed data sets, each a checkable row
            w = QListWidget()
            chosen = {tuple(sorted(p)) for p in (value or [])}
            for a in range(len(self.sets)):
                for b in range(a + 1, len(self.sets)):
                    it = QListWidgetItem(f"{_set_label(self.table, self.sets[a])}  vs  "
                                         f"{_set_label(self.table, self.sets[b])}")
                    it.setData(Qt.UserRole, [a, b])
                    it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
                    it.setCheckState(Qt.Checked if (a, b) in chosen or (not chosen and (a, b) == (0, 1))
                                     else Qt.Unchecked)
                    w.addItem(it)
            w.setMinimumHeight(110)
            return w
        if f.kind == "variable":  # a variable of the table, by its index
            w = QComboBox()
            for i in range(len(self.table.datasets)):
                w.addItem(_set_label(self.table, i), i)
            w.setCurrentIndex(max(0, w.findData(value)))
            return w
        if f.kind == "text":
            w = QLineEdit(str(value or ""))
            if f.key == "defs" and not value:  # every variable, as it is
                w.setText(", ".join(chr(65 + i) for i in range(len(self.table.datasets))))
            return w
        if f.kind == "bool":
            w = QCheckBox(f.label)
            w.setChecked(bool(value))
            return w
        w = QDoubleSpinBox()
        w.setDecimals(4)
        w.setRange(-1e9, 1e9)
        if f.key == "alpha":
            w.setRange(0.0001, 0.5)
            w.setSingleStep(0.01)
        elif f.key == "level":
            w.setRange(50, 99.99)
        if value is None and f.key in ("from", "to") and self.table.x is not None:  # the table's X range
            xs = [q for q in self.table.x_values() if q is not None]
            value = (min(xs) if f.key == "from" else max(xs)) if xs else 0.0
        w.setValue(float(value if value is not None else 0))
        return w

    def _refill_tests(self, *_a, selected: str | None = None) -> None:
        w = self.widgets.get("test")
        if not isinstance(w, QComboBox):
            return
        keep = selected or w.currentData()
        design = self.value("design")
        compare = self.value("compare")
        tests = catalog.post_tests(self.choice.analysis_class, design, compare)
        w.blockSignals(True)
        w.clear()
        for t in tests:
            w.addItem(TEST_NAMES.get(t, t), t)
        w.setCurrentIndex(max(0, w.findData(keep)))
        w.setEnabled(bool(tests))
        w.blockSignals(False)
        ctl = self.widgets.get("control")
        if ctl is not None:
            ctl.setEnabled(compare == "CONTROL_VS_ALL")
        pairs = self.widgets.get("pairs")
        if pairs is not None:
            pairs.setEnabled(compare == "SELECTED_VS_SELECTED")

    def value(self, key: str):
        w = self.widgets.get(key)
        if isinstance(w, QComboBox):
            return w.currentData()
        if isinstance(w, QCheckBox):
            return w.isChecked()
        if isinstance(w, QDoubleSpinBox):
            return w.value()
        if isinstance(w, QLineEdit):
            return w.text()
        if isinstance(w, QListWidget):
            return [w.item(k).data(Qt.UserRole) for k in range(w.count()) if w.item(k).checkState() == Qt.Checked]
        return None

    def set_value(self, key: str, value) -> None:
        w = self.widgets[key]
        if isinstance(w, QComboBox):
            w.setCurrentIndex(max(0, w.findData(value)))
        elif isinstance(w, QCheckBox):
            w.setChecked(bool(value))
        elif isinstance(w, QLineEdit):
            w.setText(str(value or ""))
        elif isinstance(w, QListWidget):
            chosen = {tuple(sorted(p)) for p in (value or [])}
            for k in range(w.count()):
                w.item(k).setCheckState(Qt.Checked if tuple(w.item(k).data(Qt.UserRole)) in chosen else Qt.Unchecked)
        else:
            w.setValue(float(value))

    def values(self) -> dict:
        return {f.key: self.value(f.key) for f in self.choice.fields}
