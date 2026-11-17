"""The data grid (docs/ui-spec.md §3.1): a two-row header (data set over its
subcolumns), editing, block copy and paste, rows, exclusion."""

from __future__ import annotations

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QAction, QKeySequence, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QHeaderView,
    QMenu,
    QStyle,
    QStyleOptionHeader,
    QTableView,
)

from ..model.document import DataTable
from .table_model import GROUP_ROLE, TableModel


class GroupHeader(QHeaderView):
    """Horizontal header: the top row names each data set once, across its
    subcolumns; the bottom row names the subcolumns."""

    def __init__(self, parent=None):
        super().__init__(Qt.Horizontal, parent)
        self.setSectionsClickable(True)
        self.setHighlightSections(True)

    def sizeHint(self) -> QSize:
        s = super().sizeHint()
        return QSize(s.width(), 2 * self.fontMetrics().height() + 12)

    def _cell(self, p: QPainter, rect: QRect, text: str, section: int, bold: bool = False) -> None:
        opt = QStyleOptionHeader()
        self.initStyleOption(opt)
        opt.rect, opt.text, opt.section = rect, text, section
        opt.textAlignment = Qt.AlignCenter
        opt.position = QStyleOptionHeader.Middle
        f = p.font()
        f.setBold(bold)
        p.setFont(f)
        self.style().drawControl(QStyle.CE_Header, opt, p, self)

    def paintEvent(self, _e) -> None:
        m = self.model()
        if m is None:
            return
        p = QPainter(self.viewport())
        h = self.viewport().height()
        top = h // 2
        n = m.columnCount()
        k = 0
        while k < n:  # top row: one cell per group
            gid, title = m.headerData(k, Qt.Horizontal, GROUP_ROLE)
            end = k
            while end + 1 < n and m.headerData(end + 1, Qt.Horizontal, GROUP_ROLE)[0] == gid:
                end += 1
            x0 = self.sectionViewportPosition(k)
            x1 = self.sectionViewportPosition(end) + self.sectionSize(end)
            self._cell(p, QRect(x0, 0, x1 - x0, top), title, k, bold=True)
            k = end + 1
        for k in range(n):  # bottom row
            x = self.sectionViewportPosition(k)
            self._cell(p, QRect(x, top, self.sectionSize(k), h - top), str(m.headerData(k, Qt.Horizontal)), k)
        p.end()


GROUPS = (("cut", "copy", "paste", "clear"), ("row_above", "row_below", "delete_rows"), ("exclude", "include"),
          ("add_set", "delete_sets", "rename_set"))  # menu sections


class TableSheet(QTableView):
    """A data table (editable) or a result table (read only)."""

    def __init__(self, doc, table: DataTable, read_only: bool = False):
        super().__init__()
        self.doc, self.table, self.read_only = doc, table, read_only
        self.model_ = TableModel(doc, table, read_only)
        self.setHorizontalHeader(GroupHeader(self))
        self.setModel(self.model_)
        self.setSelectionMode(QAbstractItemView.ContiguousSelection)
        hh = self.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.Interactive)
        hh.setMinimumSectionSize(56)
        hh.setDefaultSectionSize(84)
        vh = self.verticalHeader()
        vh.setDefaultSectionSize(22)
        vh.setDefaultAlignment(Qt.AlignRight | Qt.AlignVCenter)
        if table.row_titles is not None:
            self.setColumnWidth(0, 150)
        self.actions_: dict[str, QAction] = {}
        for key, text, keys, slot, editing in [
            ("cut", "Cut", QKeySequence.Cut, self.cut, True),
            ("copy", "Copy", QKeySequence.Copy, self.copy, False),
            ("paste", "Paste", QKeySequence.Paste, self.paste_clipboard, True),
            ("clear", "Clear", QKeySequence.Delete, self.clear, True),
            ("row_above", "Insert Row Above", "Ctrl+Shift+I", self.insert_above, True),
            ("row_below", "Insert Row Below", None, self.insert_below, True),
            ("delete_rows", "Delete Rows", "Ctrl+Shift+Backspace", self.delete_rows, True),
            ("exclude", "Exclude Values", "Ctrl+Shift+E", self.exclude_values, True),
            ("include", "Include Values", None, self.include_values, True),
            ("add_set", "Insert Data Set", "Ctrl+Shift+D", self.insert_dataset, True),
            ("delete_sets", "Delete Data Sets", None, self.delete_datasets, True),
            ("rename_set", "Rename Data Set…", None, self.rename_dataset, True),
        ]:
            a = QAction(text, self)
            if keys:
                a.setShortcut(QKeySequence(keys))
                a.setShortcutContext(Qt.WidgetWithChildrenShortcut)
            a.triggered.connect(slot)
            a.setEnabled(not (editing and read_only))
            self.addAction(a)
            self.actions_[key] = a
        hh.sectionDoubleClicked.connect(self._header_double_clicked)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)

    # ------------------------------------------------------------- helpers
    def selected_cells(self) -> list[tuple[int, int]]:
        idx = self.selectedIndexes() or ([self.currentIndex()] if self.currentIndex().isValid() else [])
        return sorted({(i.row(), i.column()) for i in idx})

    def _bounds(self):
        cells = self.selected_cells()
        if not cells:
            return None
        rows = [r for r, _ in cells]
        cols = [c for _, c in cells]
        return min(rows), max(rows), min(cols), max(cols)

    def _menu(self, pos) -> None:
        m = QMenu(self)
        for group in GROUPS:
            for k in group:
                m.addAction(self.actions_[k])
            m.addSeparator()
        m.exec(self.viewport().mapToGlobal(pos))

    # ------------------------------------------------------------- actions
    def copy(self) -> None:
        b = self._bounds()
        if b is None:
            return
        r0, r1, c0, c1 = b
        text = "\n".join("\t".join(self.model_.text(r, c) for c in range(c0, c1 + 1)) for r in range(r0, r1 + 1))
        QApplication.clipboard().setText(text + "\n")

    def cut(self) -> None:
        self.copy()
        self.clear()

    def paste_clipboard(self) -> bool:
        """The Paste action's slot (a triggered action passes `checked`, so the
        slot takes no arguments)."""
        return self.paste(QApplication.clipboard().text())

    def paste(self, text: str | None = None) -> bool:
        """A tab-separated block from the clipboard, from the current cell on;
        columns past the table's last one are dropped (reported in the status bar)."""
        if self.read_only:
            return False
        text = QApplication.clipboard().text() if text is None else text
        rows = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        while rows and rows[-1] == "":
            rows.pop()
        if not rows:
            return False
        cur = self.currentIndex()
        r0, c0 = (cur.row(), cur.column()) if cur.isValid() else (0, 0)
        cols = self.model_.cols
        cells, dropped = [], 0
        for i, line in enumerate(rows):
            for j, v in enumerate(line.split("\t")):
                c = c0 + j
                if c >= len(cols):
                    dropped += 1
                    continue
                if cols[c].editable:
                    cells.append((cols[c].ds, cols[c].sub, r0 + i, v.strip()))
        done = self.doc.set_cells(self.table, cells, f"Paste {len(rows)} row(s)")
        if dropped:
            self._status(f"Pasted; {dropped} value(s) beyond the last column were left out")
        return done

    def clear(self) -> None:
        cols = self.model_.cols
        cells = [(cols[c].ds, cols[c].sub, r, "") for r, c in self.selected_cells() if cols[c].editable]
        self.doc.set_cells(self.table, cells, "Clear")

    # slots: bound methods, never lambdas holding self (they crash Qt's teardown)
    def insert_above(self) -> None:
        self.insert_rows(False)

    def insert_below(self) -> None:
        self.insert_rows(True)

    def exclude_values(self) -> None:
        self.exclude(True)

    def include_values(self) -> None:
        self.exclude(False)

    def _current_sets(self) -> list:
        """The data sets (column groups) of the selected cells, in table order."""
        cols = self.model_.cols
        picked = {id(cols[c].ds) for _r, c in self.selected_cells() if cols[c].ds.role == "Y"}
        return [d for d in self.table.datasets if id(d) in picked]

    def insert_dataset(self) -> None:
        """A new data set after the selected one (or at the end)."""
        sets = self._current_sets()
        at = (max(self.table.datasets.index(d) for d in sets) + 1) if sets else None
        self.doc.add_dataset(self.table, at)

    def delete_datasets(self) -> None:
        self.doc.delete_datasets(self.table, self._current_sets())

    def rename_dataset(self, title: str | None = None, ds=None) -> bool:
        """Rename the selected data set; asks for the title when none is given."""
        if ds is None:
            sets = self._current_sets()
            if not sets:
                return False
            ds = sets[0]
        if not isinstance(title, str):
            from PySide6.QtWidgets import QInputDialog

            title, ok = QInputDialog.getText(self, "Rename Data Set", "Title:", text=ds.title or "")
            if not ok:
                return False
        return self.doc.rename_dataset(self.table, ds, title.strip())

    def _header_double_clicked(self, section: int) -> None:
        c = self.model_.cols[section]
        if c.ds.role == "Y" and not self.read_only:
            self.rename_dataset(None, c.ds)

    def insert_rows(self, below: bool) -> None:
        b = self._bounds()
        if b is None:
            return
        r0, r1, _c0, _c1 = b
        self.doc.insert_rows(self.table, r1 + 1 if below else r0, r1 - r0 + 1)

    def delete_rows(self) -> None:
        b = self._bounds()
        if b is not None:
            self.doc.delete_rows(self.table, set(range(b[0], b[1] + 1)))

    def exclude(self, flag: bool) -> None:
        cols = self.model_.cols
        cells = [(cols[c].ds, cols[c].sub, r) for r, c in self.selected_cells()
                 if cols[c].ds.role == "Y" and r < self.table.n_rows]
        self.doc.set_excluded(self.table, cells, flag)

    def keyPressEvent(self, e) -> None:
        if e.key() in (Qt.Key_Delete, Qt.Key_Backspace) and self.state() != QAbstractItemView.EditingState:
            if not self.read_only:
                self.clear()
            return
        super().keyPressEvent(e)

    def _status(self, msg: str) -> None:
        w = self.window()
        if hasattr(w, "statusBar"):
            w.statusBar().showMessage(msg, 6000)
