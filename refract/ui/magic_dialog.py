"""The Magic dialog (Graph ▸ Magic, docs/ui-spec.md §3.4): pick the graph or
saved style template to copy from (thumbnails of the project's graphs and
the templates, each template previewed on the graph being changed), then
which parts of its look to copy (refract.render.magic)."""

from __future__ import annotations

import json

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QListView,
    QListWidget,
    QListWidgetItem,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..render import formatting, magic, qt
from . import look

THUMB = QSize(210, 160)
TEMPLATES_KEY = "magic/templates"


def templates() -> dict[str, dict]:
    try:
        v = json.loads(look.setting(TEMPLATES_KEY, "{}") or "{}")
    except (TypeError, ValueError):
        return {}
    return v if isinstance(v, dict) else {}


def save_template(name: str, style: dict) -> None:
    t = templates()
    t[name] = magic.template(style)
    look.set_setting(TEMPLATES_KEY, json.dumps(t))


def delete_template(name: str) -> None:
    t = templates()
    t.pop(name, None)
    look.set_setting(TEMPLATES_KEY, json.dumps(t))


def thumbnail(g) -> QIcon:
    lay = qt.layout(g)
    k = min(THUMB.width() / lay.width, THUMB.height() / lay.height) * 2
    img = qt.to_image(g, k, lay=lay)
    pm = QPixmap(THUMB.width() * 2, THUMB.height() * 2)
    pm.fill(Qt.white)
    from PySide6.QtGui import QPainter

    p = QPainter(pm)
    p.drawImage((pm.width() - img.width()) // 2, (pm.height() - img.height()) // 2, img)
    p.end()
    pm.setDevicePixelRatio(2)
    return QIcon(pm)


class MagicDialog(QDialog):
    """examples: [(label, graph, style dict)] from the project; the target
    graph is previewed with each saved template applied."""

    def __init__(self, target, target_fmt: dict, examples: list[tuple[str, object, dict]], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Magic: Make This Graph Look Like Another")
        self.resize(900, 620)
        self.target, self.target_fmt = target, target_fmt
        self.examples: list[tuple[str, dict]] = []
        self.pages = QStackedWidget()
        # step 1: the example
        first = QWidget()
        v = QVBoxLayout(first)
        v.addWidget(QLabel("Step 1 of 2. Choose the graph whose look this graph should take, "
                           "or a saved style template."))
        self.jump = QComboBox()
        self.jump.addItems(["Graphs in this project", "Saved style templates"])
        self.jump.currentIndexChanged.connect(self._fill)
        row = QHBoxLayout()
        row.addWidget(QLabel("Show"))
        row.addWidget(self.jump)
        row.addStretch(1)
        v.addLayout(row)
        self.list = QListWidget()
        self.list.setViewMode(QListView.IconMode)
        self.list.setIconSize(THUMB)
        self.list.setResizeMode(QListView.Adjust)
        self.list.setMovement(QListView.Static)
        self.list.setSpacing(10)
        self.list.setWordWrap(True)
        self.list.itemDoubleClicked.connect(lambda _i: self._next())
        self.list.currentRowChanged.connect(self._update_buttons)
        v.addWidget(self.list, 1)
        self.pages.addWidget(first)
        # step 2: what to copy
        second = QWidget()
        v2 = QVBoxLayout(second)
        self.step2 = QLabel()
        v2.addWidget(self.step2)
        self.parts: dict[str, QCheckBox] = {}
        for key, label in magic.PARTS.items():
            cb = QCheckBox(label)
            cb.setChecked(key in magic.DEFAULT_PARTS)
            self.parts[key] = cb
            v2.addWidget(cb)
        self.scope = QComboBox()
        self.scope.addItems(["This graph", "Every graph of this kind in the project"])
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Change"))
        row2.addWidget(self.scope)
        row2.addStretch(1)
        v2.addSpacing(10)
        v2.addLayout(row2)
        v2.addStretch(1)
        self.pages.addWidget(second)
        self.buttons = QDialogButtonBox()
        self.back = self.buttons.addButton("<< Back", QDialogButtonBox.ActionRole)
        self.next = self.buttons.addButton("Next >>", QDialogButtonBox.AcceptRole)
        self.buttons.addButton(QDialogButtonBox.Cancel)
        self.back.clicked.connect(self._back)
        self.next.clicked.disconnect()
        self.next.clicked.connect(self._next)
        self.buttons.rejected.connect(self.reject)
        outer = QVBoxLayout(self)
        outer.addWidget(self.pages, 1)
        outer.addWidget(self.buttons)
        self._project = examples
        self._fill(0)

    def _fill(self, which: int) -> None:
        self.list.clear()
        self.examples = []
        if which == 0:
            for label, g, style in self._project:
                self._add(label, thumbnail(g), style)
        else:
            for name, style in sorted(templates().items()):
                preview = formatting.apply(self._copy_target(), magic.match(self.target_fmt, self.target, style,
                                                                             magic.DEFAULT_PARTS))
                self._add(name, thumbnail(preview), style)
        if self.list.count():
            self.list.setCurrentRow(0)
        self._update_buttons()

    def _copy_target(self):
        import copy

        return copy.deepcopy(self.target)

    def _add(self, label: str, icon: QIcon, style: dict) -> None:
        it = QListWidgetItem(icon, label)
        it.setSizeHint(QSize(THUMB.width() + 16, THUMB.height() + 44))
        self.list.addItem(it)
        self.examples.append((label, style))

    def _update_buttons(self, *_a) -> None:
        on_first = self.pages.currentIndex() == 0
        self.back.setEnabled(not on_first)
        self.next.setText("Next >>" if on_first else "OK")
        self.next.setEnabled(not on_first or self.list.currentRow() >= 0)

    def _next(self) -> None:
        if self.pages.currentIndex() == 0:
            if self.list.currentRow() < 0:
                return
            self.step2.setText(f"Step 2 of 2. Copy from “{self.examples[self.list.currentRow()][0]}”:")
            self.pages.setCurrentIndex(1)
            self._update_buttons()
        else:
            self.accept()

    def _back(self) -> None:
        self.pages.setCurrentIndex(0)
        self._update_buttons()

    def choice(self) -> tuple[dict, list[str], bool]:
        """(example style, parts to copy, every graph of this kind)."""
        style = self.examples[self.list.currentRow()][1]
        return style, [k for k, cb in self.parts.items() if cb.isChecked()], self.scope.currentIndex() == 1
