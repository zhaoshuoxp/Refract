"""Qt model of a data table: row titles, X, then each data set's subcolumns,
with the stored text shown as is and excluded values in blue italics
(docs/ui-spec.md §3.1)."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QFont

from ..model.document import REPLICATE_FORMATS, DataSet, DataTable
from . import look

# subcolumn labels of the entered-statistics formats (data set title above them)
FORMAT_LABELS = {
    "y_sd": ["Mean", "SD"], "y_se": ["Mean", "SEM"], "y_cv": ["Mean", "%CV"],
    "y_sd_n": ["Mean", "SD", "N"], "y_se_n": ["Mean", "SEM", "N"], "y_cv_n": ["Mean", "%CV", "N"],
    "y_plus_minus": ["Mean", "+Error", "-Error"], "y_high_low": ["Mean", "Upper", "Lower"],
}
EXTRA_ROWS = 20  # empty rows below the data, ready for typing (the grid grows as they fill)
GROUP_ROLE = Qt.UserRole + 1


@dataclass
class Column:
    ds: DataSet
    sub: int
    gid: int  # columns of one data set share it (one header cell over them)
    title: str  # the header's top row
    label: str  # the header's bottom row (subcolumn)
    editable: bool = True

    @property
    def group(self) -> str:  # legacy two-line form
        return self.title


def _letters(i: int) -> str:
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def columns(t: DataTable) -> list[Column]:
    out: list[Column] = []
    if t.row_titles is not None:
        out.append(Column(t.row_titles, 0, -1, "", "Row title"))
    if t.x is not None and t.x.generated is None:
        for k in range(len(t.x.subcolumns)):
            out.append(Column(t.x, k, -2, t.x.title or "X", "X" if len(t.x.subcolumns) == 1 else f"X{k + 1}"))
    n = t.subcolumns_per_dataset
    for i, ds in enumerate(t.datasets):
        title = f"{_letters(i)}: {ds.title}" if ds.title else _letters(i)
        if t.data_format in REPLICATE_FORMATS:
            labels = [f"Y{k + 1}" for k in range(n)] if n > 1 else ["Y"]
        else:
            labels = FORMAT_LABELS.get(t.data_format, [""] * n)
        for k in range(min(n, len(ds.subcolumns))):
            out.append(Column(ds, k, i, title, labels[k] if k < len(labels) else ""))
    return out


class TableModel(QAbstractTableModel):
    def __init__(self, doc, table: DataTable, read_only: bool = False):
        super().__init__()
        self.doc, self.table, self.read_only = doc, table, read_only
        self.cols = columns(table)
        doc.tableEdited.connect(self._edited)

    def _edited(self, table) -> None:
        if table is self.table:
            self.beginResetModel()
            self.cols = columns(self.table)  # data sets may have been added, removed or renamed
            self.endResetModel()

    # --------------------------------------------------------------- shape
    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: B008 - Qt API
        return 0 if parent.isValid() else self.table.n_rows + (0 if self.read_only else EXTRA_ROWS)

    def columnCount(self, parent=QModelIndex()) -> int:  # noqa: B008
        return 0 if parent.isValid() else len(self.cols)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Vertical:
            return str(section + 1) if role == Qt.DisplayRole else None
        c = self.cols[section]
        if role == Qt.DisplayRole:
            return c.label
        if role == GROUP_ROLE:  # (group number, title): the header's top row spans a group
            return c.gid, c.title
        return None

    # ---------------------------------------------------------------- data
    def text(self, row: int, col: int) -> str:
        c = self.cols[col]
        cells = c.ds.subcolumns[c.sub] if c.sub < len(c.ds.subcolumns) else []
        return cells[row] if row < len(cells) else ""

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        r, k = index.row(), index.column()
        c = self.cols[k]
        if role in (Qt.DisplayRole, Qt.EditRole):
            return self.text(r, k)
        excluded = c.ds.is_excluded(c.sub, r)
        if role == Qt.ForegroundRole and excluded:
            return look.color("excluded")
        if role == Qt.FontRole and excluded:
            f = QFont()
            f.setItalic(True)
            return f
        if role == Qt.BackgroundRole and c.ds.role == "RT":
            return look.color("row_title")
        if role == Qt.TextAlignmentRole:
            return int((Qt.AlignLeft if c.ds.role == "RT" else Qt.AlignRight) | Qt.AlignVCenter)
        return None

    def flags(self, index):
        f = Qt.ItemIsSelectable | Qt.ItemIsEnabled
        if not self.read_only and self.cols[index.column()].editable:
            f |= Qt.ItemIsEditable
        return f

    def setData(self, index, value, role=Qt.EditRole) -> bool:
        if role != Qt.EditRole or self.read_only or not index.isValid():
            return False
        c = self.cols[index.column()]
        self.doc.set_cell(self.table, c.ds, c.sub, index.row(), str(value))
        return True
