"""The toolbar under the menu bar (docs/ui-spec.md §1): commands in labelled
groups (File, Sheet, Undo, Clipboard, Analysis, Change, Text, Draw, Export,
Help), each group a small grid of icon buttons, as scientific graphing
programs lay out their toolbars. The buttons are the window's own QActions
(menus and toolbar share state); a few groups hold widgets (the Text
group's font controls)."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QGridLayout,
    QLabel,
    QLayout,
    QSizePolicy,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

ICON = QSize(24, 24)  # two rows of buttons per group, the groups side by side


class Group(QWidget):
    """A labelled block of buttons: `rows` of QActions or widgets (None: a gap)."""

    def __init__(self, title: str, rows: list[list], parent=None):
        super().__init__(parent)
        self.setObjectName("ribbonGroup")
        v = QVBoxLayout(self)
        v.setContentsMargins(8, 2, 8, 2)
        v.setSpacing(2)
        label = QLabel(title)
        label.setObjectName("ribbonLabel")
        label.setAlignment(Qt.AlignHCenter)
        v.addWidget(label)
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(3)
        grid.setVerticalSpacing(3)
        self.buttons: dict[str, QToolButton] = {}
        for r, row in enumerate(rows):
            c = 0
            for item in row:
                if item is None:
                    c += 1
                    continue
                if isinstance(item, QAction):
                    b = QToolButton()
                    b.setDefaultAction(item)
                    b.setAutoRaise(True)
                    b.setIconSize(ICON)
                    b.setToolButtonStyle(Qt.ToolButtonIconOnly)
                    if item.menu() is not None:
                        b.setPopupMode(QToolButton.InstantPopup)
                    self.buttons[item.text()] = b
                    w = b
                else:
                    w = item
                span = w.property("span") or 1
                grid.addWidget(w, r, c, 1, span)
                c += span
        v.addLayout(grid)
        v.addStretch(1)


class _Flow(QLayout):
    """Groups left to right, wrapping onto further rows when the window is narrower than they are
    (nothing hidden behind an overflow button)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.items: list = []
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item) -> None:
        self.items.append(item)

    def count(self) -> int:
        return len(self.items)

    def itemAt(self, i):
        return self.items[i] if 0 <= i < len(self.items) else None

    def takeAt(self, i):
        return self.items.pop(i) if 0 <= i < len(self.items) else None

    def expandingDirections(self):
        return Qt.Orientations(0)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, w: int) -> int:
        return self._place(QRect(0, 0, w, 0), move=False)

    def setGeometry(self, r) -> None:
        super().setGeometry(r)
        self._place(r, move=True)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        w = max((it.minimumSize().width() for it in self.items), default=0)
        h = max((it.sizeHint().height() for it in self.items), default=0)
        return QSize(w, h)

    def _place(self, r, move: bool) -> int:
        x, y, row_h = r.x(), r.y(), 0
        for it in self.items:
            hint = it.sizeHint()
            if x + hint.width() > r.right() + 1 and x > r.x():  # the next row
                x, y, row_h = r.x(), y + row_h + 2, 0
            if move:
                it.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width()
            row_h = max(row_h, hint.height())
        return y + row_h - r.y()


class _Host(QWidget):
    """The toolbar's one widget: every group, wrapped to the window's width."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.flow = _Flow(self)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

    def resizeEvent(self, e) -> None:
        h = self.flow.heightForWidth(self.width())
        if h != self.minimumHeight():
            self.setMinimumHeight(h)
        super().resizeEvent(e)

    def sizeHint(self) -> QSize:
        return QSize(200, self.flow.heightForWidth(max(self.width(), 200)))

    def minimumSizeHint(self) -> QSize:
        return QSize(100, self.flow.minimumSize().height())


class Ribbon(QToolBar):
    def __init__(self, parent=None):
        super().__init__("Toolbar", parent)
        self.setObjectName("ribbon")
        self.setMovable(False)
        self.setFloatable(False)
        self.groups: dict[str, Group] = {}
        self.host = _Host(self)
        self.addWidget(self.host)

    def add_group(self, title: str, rows: list[list]) -> Group:
        g = Group(title, rows, self.host)
        if self.groups:
            sep = QWidget(self.host)
            sep.setObjectName("ribbonSep")
            sep.setFixedWidth(1)
            sep.setMinimumHeight(40)
            self.host.flow.addWidget(sep)
        self.host.flow.addWidget(g)
        self.groups[title] = g
        return g
