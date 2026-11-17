"""The New Data Table dialog (docs/ui-spec.md §6), also the window that
starts a new project: the table kinds on the left; on the right what the
kind is for, a drawn preview of its table layout with a small graph, whether
to start empty or from our sample data, and the kind's own options (how Y
values are entered, replicates, subcolumns). The wording and the previews
are our own."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..model import templates as T
from . import look

HEADINGS = {
    "xy": "XY tables: every point has an X value and one or more Y values",
    "column": "Column tables: one grouping factor, each group in its own column",
    "grouped": "Grouped tables: two grouping factors, one across the columns and one down the rows",
    "contingency": "Contingency tables: counts of subjects, groups in rows and outcomes in columns",
    "survival": "Survival tables: one row per subject, with its time and whether the event happened",
    "parts_of_whole": "Parts of whole tables: each row is one part of a whole",
    "multivariable": "Multiple variables tables: one row per subject, one column per variable",
    "nested": "Nested tables: groups made of subgroups, each subgroup measured several times",
}
ERROR_FORMATS = ["y_sd_n", "y_sd", "y_se"]  # "values computed elsewhere", in the Values list
ERROR_NAMES = {"y_sd_n": "Mean, SD and N", "y_sd": "Mean and SD", "y_se": "Mean and SEM"}

# preview: the column headings of the table sketch, and the graph drawn beside it
SKETCH = {
    "xy": (["X", "Group A", "Group B"], ["Time", "Control", "Treated"], "xy"),
    "column": (["Group A", "Group B"], ["Control", "Treated"], "bars"),
    "grouped": (["Group A", "Group B"], ["Control", "Treated"], "grouped"),
    "contingency": (["Outcome A", "Outcome B"], ["Disease", "No disease"], "counts"),
    "survival": (["X", "Group A", "Group B"], ["Days", "Standard", "New"], "survival"),
    "parts_of_whole": (["A"], ["Share"], "pie"),
    "multivariable": (["Variable A", "Variable B", "Variable C"], ["Age", "Dose", "Response"], "bubbles"),
    "nested": (["Group A", "Group B"], ["Control", "Treated"], "nested"),
}
ROWS = {"grouped": ["Wild type", "Mutant"], "contingency": ["Exposed", "Not exposed"],
        "parts_of_whole": ["Part 1", "Part 2"]}
PURPLE, BLUE = QColor("#7b2a8c"), QColor("#1f63b4")


def preview(key: str, dark: bool = False) -> QPixmap:
    """A drawing of the kind's table layout and a small graph (our own)."""
    heads, names, graph = SKETCH[key]
    W, H = 640, 170
    pm = QPixmap(W * 2, H * 2)
    pm.setDevicePixelRatio(2)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor("#ffffff"))
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(QRectF(0, 0, W, H), 8, 8)
    grid = QColor("#b7bcc4")
    ink = QColor("#202329")
    faint = QColor("#9aa0a8")
    small = QFont("Helvetica")
    small.setPixelSize(11)
    # table: a kind column, then one block per data set
    x0, y0, rh = 14, 14, 26
    col0 = 120
    sub = 2 if key in ("xy", "grouped", "nested") else 1
    widths = [64 if h == "X" else 56 * sub for h in heads]
    total = col0 + sum(widths)
    p.setFont(small)
    p.setPen(QPen(grid, 1))
    rows = 5
    for r in range(rows + 1):
        p.drawLine(QPointF(x0, y0 + r * rh), QPointF(x0 + total, y0 + r * rh))
    x = x0
    for w in [col0] + widths:
        p.drawLine(QPointF(x, y0), QPointF(x, y0 + rows * rh))
        x += w
    p.drawLine(QPointF(x, y0), QPointF(x, y0 + rows * rh))
    p.setPen(ink)
    p.drawText(QRectF(x0, y0, col0, rh), Qt.AlignCenter, "Table format")
    blue = QColor("#2459c4")
    p.setPen(blue)
    p.drawText(QRectF(x0, y0 + rh, col0, rh), Qt.AlignCenter, T.kind(key).label)
    x = x0 + col0
    for h, n, w in zip(heads, names, widths, strict=True):
        p.setPen(faint)
        p.drawText(QRectF(x, y0, w, rh), Qt.AlignCenter, h)
        p.setPen(ink)
        p.drawText(QRectF(x, y0 + rh, w, rh), Qt.AlignCenter, n)
        if sub > 1 and h != "X":
            p.setPen(QPen(grid, 1))
            p.drawLine(QPointF(x + w / 2, y0 + 2 * rh), QPointF(x + w / 2, y0 + rows * rh))
            p.setPen(faint)
            lab = ("A" if h.endswith("A") else "B")
            for k in range(sub):
                txt = f"{'Sub' if key == 'nested' else lab + ':Y'}{k + 1}"
                p.drawText(QRectF(x + k * w / 2, y0 + 2 * rh, w / 2, rh), Qt.AlignCenter, txt)
        x += w
    labels = ROWS.get(key, ["Row 1", "Row 2"])
    for r, lab in enumerate(labels):
        p.setPen(faint)
        p.drawText(QRectF(x0 + 4, y0 + (3 + r) * rh, col0 - 8, rh), Qt.AlignVCenter | Qt.AlignLeft,
                   f"{r + 1}   {lab}")
    # the graph
    gx, gy, gw, gh = x0 + total + 26, 18.0, W - (x0 + total + 26) - 18, H - 44.0
    _mini_graph(p, graph, QRectF(gx, gy, gw, gh), ink)
    p.end()
    return pm


def _mini_graph(p: QPainter, kind: str, r: QRectF, ink: QColor) -> None:
    axis = QPen(ink, 1.4)
    if kind != "pie":
        p.setPen(axis)
        p.drawLine(r.bottomLeft(), r.topLeft())
        p.drawLine(r.bottomLeft(), r.bottomRight())

    def X(f):
        return r.left() + f * r.width()

    def Y(f):
        return r.bottom() - f * r.height()

    p.setPen(Qt.NoPen)
    if kind == "xy":
        for c, ys in ((PURPLE, (0.25, 0.4, 0.5, 0.62, 0.7)), (BLUE, (0.3, 0.55, 0.7, 0.8, 0.88))):
            for i, y in enumerate(ys):
                p.setPen(QPen(c, 1.2))
                p.drawLine(QPointF(X(0.1 + i * 0.2), Y(y - 0.07)), QPointF(X(0.1 + i * 0.2), Y(y + 0.07)))
                p.setPen(Qt.NoPen)
                p.setBrush(c)
                p.drawEllipse(QPointF(X(0.1 + i * 0.2), Y(y)), 3.2, 3.2)
    elif kind in ("bars", "counts"):
        for i, (c, h) in enumerate(((PURPLE, 0.4), (BLUE, 0.8)) if kind == "bars" else
                                   ((PURPLE, 0.85), (BLUE, 0.75), (PURPLE, 0.12), (BLUE, 0.2))):
            p.setBrush(c)
            w = 0.22 if kind == "bars" else 0.13
            x = (0.2 + i * 0.45) if kind == "bars" else (0.12 + i * 0.16 + (0.2 if i > 1 else 0))
            p.drawRect(QRectF(X(x), Y(h), w * r.width(), h * r.height()))
    elif kind == "grouped":
        for i, (c, h) in enumerate(((PURPLE, 0.25), (BLUE, 0.6), (PURPLE, 0.45), (BLUE, 0.85))):
            p.setBrush(c)
            p.drawRect(QRectF(X(0.12 + i * 0.17 + (0.12 if i > 1 else 0)), Y(h), 0.14 * r.width(), h * r.height()))
    elif kind == "survival":
        for c, pts in ((PURPLE, (1.0, 0.82, 0.66, 0.55, 0.4, 0.3)), (BLUE, (1.0, 0.92, 0.84, 0.72, 0.66, 0.58))):
            path = QPainterPath(QPointF(X(0), Y(pts[0] * 0.95)))
            for i, y in enumerate(pts[1:], 1):
                path.lineTo(X(i * 0.16), Y(pts[i - 1] * 0.95))
                path.lineTo(X(i * 0.16), Y(y * 0.95))
            path.lineTo(X(1.0), Y(pts[-1] * 0.95))
            p.setPen(QPen(c, 1.8))
            p.setBrush(Qt.NoBrush)
            p.drawPath(path)
    elif kind == "pie":
        side = min(r.width(), r.height())
        box = QRectF(r.center().x() - side / 2, r.center().y() - side / 2, side, side)
        p.setBrush(PURPLE)
        p.drawPie(box, 90 * 16, -230 * 16)
        p.setBrush(BLUE)
        p.drawPie(box, -140 * 16, -130 * 16)
    elif kind == "bubbles":
        import random

        rnd = random.Random(4)
        for i in range(22):
            fx = rnd.random() * 0.85 + 0.05
            fy = min(0.95, max(0.05, fx * 0.8 + rnd.random() * 0.25))
            c = QColor(PURPLE if i % 2 else BLUE)
            c.setAlpha(200)
            p.setBrush(c)
            p.drawEllipse(QPointF(X(fx), Y(fy)), 2 + rnd.random() * 5, 2 + rnd.random() * 5)
    elif kind == "nested":
        for g, c in enumerate((PURPLE, BLUE)):
            for s in range(3):
                base = (0.25 if g == 0 else 0.6) + (s - 1) * 0.08
                for k in range(3):
                    p.setBrush(c)
                    p.drawEllipse(QPointF(X(0.1 + g * 0.48 + s * 0.13 + (k % 2 - 0.5) * 0.02), Y(base + (k - 1) * 0.06)),
                                  2.8, 2.8)


class NewTableDialog(QDialog):
    """Choose the table kind and how its values are entered. With
    new_project the dialog is the start window (and offers to open a file)."""

    openRequested = Signal()

    def __init__(self, title: str = "Data 1", parent=None, new_project: bool = False):
        super().__init__(parent)
        self.setWindowTitle("Welcome to Refract" if new_project else "New Data Table")
        self.setObjectName("newTable")
        self.resize(1000, 640)
        self.kinds = QListWidget()
        self.kinds.setObjectName("kindList")
        self.kinds.setIconSize(QSize(18, 18))
        head = QListWidgetItem("NEW TABLE")
        head.setFlags(Qt.NoItemFlags)
        self.kinds.addItem(head)
        for k in T.KINDS:
            it = QListWidgetItem(k.label)
            it.setData(Qt.UserRole, k.key)
            self.kinds.addItem(it)
        if new_project:
            gap = QListWidgetItem("")
            gap.setFlags(Qt.NoItemFlags)
            self.kinds.addItem(gap)
            head = QListWidgetItem("OPEN")
            head.setFlags(Qt.NoItemFlags)
            self.kinds.addItem(head)
            it = QListWidgetItem("Open a File…")
            it.setData(Qt.UserRole, "open")
            self.kinds.addItem(it)
        for i in range(self.kinds.count()):
            it = self.kinds.item(i)
            if not it.flags() & Qt.ItemIsSelectable:
                f = it.font()
                f.setBold(True)
                f.setPointSizeF(f.pointSizeF() * 0.9)
                it.setFont(f)
                it.setForeground(look.color("accent"))
        self.kinds.setFixedWidth(220)
        self.kinds.currentRowChanged.connect(self._kind_changed)
        self.kinds.itemDoubleClicked.connect(self._double_clicked)
        # right side
        self.heading = QLabel()
        self.heading.setObjectName("newTableHeading")
        self.heading.setWordWrap(True)
        f = self.heading.font()
        f.setBold(True)
        f.setPointSizeF(f.pointSizeF() * 1.25)
        self.heading.setFont(f)
        self.picture = QLabel()
        self.picture.setMinimumHeight(170)
        self.about = QLabel()
        self.about.setWordWrap(True)
        self.about.setObjectName("muted")
        # data table: empty or sample
        self.empty = QRadioButton("Start with an empty table, to type or paste values into")
        self.sample = QRadioButton("Start with sample data, to try the analyses and graphs")
        self.empty.setChecked(True)
        self.start = QButtonGroup(self)
        self.start.addButton(self.empty)
        self.start.addButton(self.sample)
        self.sample.toggled.connect(self._update)
        # options (shown per kind)
        self.x_numbers = QRadioButton("Numbers")
        self.x_numbers.setChecked(True)
        self.x_errors = QRadioButton("Numbers with error values (horizontal error bars)")
        self.x_dates = QRadioButton("Dates")
        self.x_times = QRadioButton("Elapsed times")
        self.x_group = QButtonGroup(self)
        for b in (self.x_numbers, self.x_errors, self.x_dates, self.x_times):
            self.x_group.addButton(b)
        for b in (self.x_errors, self.x_dates, self.x_times):
            b.setEnabled(False)
            b.setToolTip("Not available yet: X values are numbers")
        self.y_single = QRadioButton("One Y value for each point")
        self.y_stacked = QRadioButton("Replicate values, one below the other in each column")
        self.y_paired = QRadioButton("Paired or repeated measures: one subject per row")
        self.y_reps = QRadioButton("Enter")
        self.replicates = QSpinBox()
        self.replicates.setRange(1, 64)
        self.replicates.setValue(3)
        self.reps_label = QLabel("replicate values side by side, in subcolumns")
        self.y_errors = QRadioButton("Mean and error values computed elsewhere")
        self.errors = QComboBox()
        for fmt in ERROR_FORMATS:
            self.errors.addItem(ERROR_NAMES[fmt], fmt)
        self.errors_label = QLabel("Values:")
        self.y_group = QButtonGroup(self)
        for b in (self.y_single, self.y_stacked, self.y_paired, self.y_reps, self.y_errors):
            self.y_group.addButton(b)
            b.toggled.connect(self._update)
        self.errors.currentIndexChanged.connect(self._update)
        self.surv_days = QRadioButton("Times as numbers (days, months, ...)")
        self.surv_days.setChecked(True)
        self.surv_dates = QRadioButton("A start and an end date for each subject")
        self.surv_dates.setEnabled(False)
        self.surv_dates.setToolTip("Not available yet")
        QButtonGroup(self).addButton(self.surv_days)
        self.nested_label = QLabel("Subcolumns (subgroups) in each group:")
        self.nested_help = QLabel("Each subcolumn is one subgroup; each row in it one measurement of that subgroup.")
        self.nested_help.setObjectName("muted")
        self.nested_help.setWordWrap(True)
        self.only_empty = QLabel("The table starts empty; there are no options for this kind.")
        self.only_empty.setObjectName("muted")
        self.sets = QSpinBox()
        self.sets.setRange(1, 52)
        self.sets_label = QLabel("Data sets")
        self.title = QLineEdit(title)
        self.x_label = QLabel("X:")
        self.y_label = QLabel("Y:")
        opts = QGridLayout()
        opts.setColumnStretch(2, 1)
        opts.setVerticalSpacing(6)
        r = 0
        opts.addWidget(self.x_label, r, 0, Qt.AlignTop)
        for b in (self.x_numbers, self.x_errors, self.x_dates, self.x_times):
            opts.addWidget(b, r, 1, 1, 3)
            r += 1
        opts.addWidget(self.y_label, r, 0, Qt.AlignTop)
        for b in (self.y_single, self.y_stacked, self.y_paired):
            opts.addWidget(b, r, 1, 1, 3)
            r += 1
        reps = QHBoxLayout()
        reps.addWidget(self.y_reps)
        reps.addWidget(self.nested_label)
        reps.addWidget(self.replicates)
        reps.addWidget(self.reps_label)
        reps.addStretch(1)
        opts.addLayout(reps, r, 1, 1, 3)
        r += 1
        opts.addWidget(self.y_errors, r, 1, 1, 3)
        r += 1
        err = QHBoxLayout()
        err.addSpacing(24)
        err.addWidget(self.errors_label)
        err.addWidget(self.errors)
        err.addStretch(1)
        opts.addLayout(err, r, 1, 1, 3)
        r += 1
        for b in (self.surv_days, self.surv_dates):
            opts.addWidget(b, r, 1, 1, 3)
            r += 1
        opts.addWidget(self.nested_help, r, 1, 1, 3)
        r += 1
        opts.addWidget(self.only_empty, r, 1, 1, 3)
        r += 1
        more = QHBoxLayout()
        more.addWidget(self.sets_label)
        more.addWidget(self.sets)
        more.addSpacing(18)
        more.addWidget(QLabel("Table name"))
        more.addWidget(self.title, 1)
        right = QVBoxLayout()
        right.setContentsMargins(18, 10, 18, 6)
        right.addWidget(self.heading)
        right.addSpacing(6)
        right.addWidget(self.picture)
        right.addWidget(self.about)
        right.addSpacing(8)
        right.addWidget(self._section("Data table"))
        right.addWidget(self.empty)
        right.addWidget(self.sample)
        right.addSpacing(8)
        right.addWidget(self._section("Options"))
        right.addLayout(opts)
        right.addStretch(1)
        right.addLayout(more)
        box = QWidget()
        box.setLayout(right)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.kinds)
        row.addWidget(box, 1)
        self.cancel = QPushButton("Cancel")
        self.cancel.clicked.connect(self.reject)
        self.create = QPushButton("Create")
        self.create.setDefault(True)
        self.create.setObjectName("primary")
        self.create.clicked.connect(self._create)
        self.guide = QPushButton("Guide")
        self.guide.setToolTip("Data tables in the Refract User Guide")
        self.guide.clicked.connect(self._guide)
        bottom = QHBoxLayout()
        bottom.setContentsMargins(14, 8, 14, 10)
        bottom.addWidget(self.guide)
        bottom.addStretch(1)
        bottom.addWidget(self.cancel)
        bottom.addWidget(self.create)
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        v.addLayout(row, 1)
        v.addWidget(line)
        v.addLayout(bottom)
        self.opened = False
        self._last = "xy"
        self.kinds.setCurrentRow(1)

    @staticmethod
    def _section(text: str) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        lab = QLabel(text + ":")
        f = lab.font()
        f.setBold(True)
        lab.setFont(f)
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setObjectName("muted")
        h.addWidget(lab)
        h.addWidget(line, 1)
        return w

    # ------------------------------------------------------------- state
    def _double_clicked(self, item) -> None:
        if item.data(Qt.UserRole):
            self._create()

    def _create(self) -> None:
        if self.kinds.currentItem() is not None and self.kinds.currentItem().data(Qt.UserRole) == "open":
            self.opened = True
            self.openRequested.emit()
            self.reject()
            return
        self.accept()

    def _guide(self) -> None:
        from . import help_view

        help_view.show(self.parent() or self)

    def kind(self) -> T.Kind:
        key = self.kinds.currentItem().data(Qt.UserRole) if self.kinds.currentItem() is not None else None
        return T.kind(key if key in {k.key for k in T.KINDS} else self._last)

    def select(self, key: str) -> None:
        for i in range(self.kinds.count()):
            if self.kinds.item(i).data(Qt.UserRole) == key:
                self.kinds.setCurrentRow(i)

    def data_format(self) -> str:
        k = self.kind()
        if len(k.formats) == 1:
            return k.formats[0]
        if self.y_errors.isChecked():
            fmt = self.errors.currentData()
            return fmt if fmt in k.formats else k.formats[0]
        if self.y_reps.isChecked() and "y_replicates" in k.formats:
            return "y_replicates"
        return "y_single" if "y_single" in k.formats else k.formats[0]

    def set_format(self, fmt: str) -> None:
        if fmt == "y_replicates":
            self.y_reps.setChecked(True)
        elif fmt in ERROR_FORMATS:
            self.y_errors.setChecked(True)
            self.errors.setCurrentIndex(max(0, self.errors.findData(fmt)))
        else:
            (self.y_stacked if self.kind().key == "column" else self.y_single).setChecked(True)
        self._update()

    def _kind_changed(self, _row: int) -> None:
        it = self.kinds.currentItem()
        key = it.data(Qt.UserRole) if it is not None else None
        if key == "open":
            self.heading.setText("Open a project file")
            self.picture.clear()
            self.about.setText("Open a .prism or .pzfx file. Recent files are under File ▸ Open Recent.")
            self.create.setText("Open…")
            for w in self._option_widgets():
                w.setVisible(False)
            return
        if key is None:
            return
        self._last = key
        self.create.setText("Create")
        k = T.kind(key)
        self.heading.setText(HEADINGS[key])
        self.picture.setPixmap(preview(key))
        self.about.setText(k.description)
        self.sets.setValue(k.sets)
        self.sets_label.setText(k.set_word)
        # the options this kind takes
        xy = key == "xy"
        show = {self.x_label: xy, self.x_numbers: xy, self.x_errors: xy, self.x_dates: xy, self.x_times: xy,
                self.y_label: key in ("xy", "grouped", "column"),
                self.y_single: key in ("xy", "grouped"), self.y_stacked: key == "column",
                self.y_paired: key == "column",
                self.y_reps: key in ("xy", "grouped", "nested"), self.replicates: key in ("xy", "grouped", "nested"),
                self.reps_label: key in ("xy", "grouped"),
                self.y_errors: key in ("xy", "grouped", "column"), self.errors: key in ("xy", "grouped", "column"),
                self.errors_label: key in ("xy", "grouped", "column"),
                self.surv_days: key == "survival", self.surv_dates: key == "survival",
                self.nested_label: key == "nested", self.nested_help: key == "nested",
                self.only_empty: key in ("contingency", "parts_of_whole", "multivariable")}
        for w, on in show.items():
            w.setVisible(on)
        for w in (self.sets, self.sets_label, self.title, self.empty, self.sample):
            w.setVisible(True)
        self.y_reps.setText("" if key == "nested" else "Enter")
        if key == "nested":
            self.y_reps.setVisible(False)
        self.set_format(k.formats[0])
        if key == "column":
            self.y_stacked.setChecked(True)

    def _option_widgets(self) -> list[QWidget]:
        return [self.x_label, self.x_numbers, self.x_errors, self.x_dates, self.x_times, self.y_label, self.y_single,
                self.y_stacked, self.y_paired, self.y_reps, self.replicates, self.reps_label, self.y_errors,
                self.errors, self.errors_label, self.surv_days, self.surv_dates, self.nested_label, self.nested_help,
                self.only_empty, self.sets, self.sets_label, self.title, self.empty, self.sample]

    def _update(self, *_a) -> None:
        k = self.kind()
        fmt = self.data_format()
        self.replicates.setEnabled(k.key == "nested" or fmt == "y_replicates")
        self.errors.setEnabled(self.y_errors.isChecked())
        self.sets.setEnabled(not self.sample.isChecked())
        self.replicates.setToolTip("Subcolumns (subgroups) per group" if k.key == "nested" else
                                   "Replicate values per point")

    def table(self):
        return T.make(self.kind().key, self.title.text().strip() or "Data", self.data_format(),
                      self.replicates.value(), self.sets.value(), self.sample.isChecked())
