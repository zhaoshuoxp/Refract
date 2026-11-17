"""Colour schemes (Graph ▸ Color Scheme): Refract's own, the palettes of
RColorBrewer and ggsci (refract.render.palette_library), and the user's own
schemes, kept in the preferences: new, edited, started from any other
scheme, or imported from pasted text or a file of hex codes; and the scheme
new graphs start with (refract.render.schemes)."""

from __future__ import annotations

import json

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import (
    QColorDialog,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

from ..render import schemes
from . import look

CUSTOM_KEY, DEFAULT_KEY, RECENT_KEY = "colors/custom", "colors/default", "colors/recent"


def custom() -> dict[str, list[str]]:
    try:
        v = json.loads(look.setting(CUSTOM_KEY, "{}") or "{}")
    except (TypeError, ValueError):
        return {}
    return {k: list(c) for k, c in v.items() if isinstance(c, list)} if isinstance(v, dict) else {}


def save_custom(name: str, colors: list[str]) -> None:
    c = custom()
    c[name] = colors
    look.set_setting(CUSTOM_KEY, json.dumps(c))


def delete_custom(name: str) -> None:
    c = custom()
    c.pop(name, None)
    look.set_setting(CUSTOM_KEY, json.dumps(c))


def rename_custom(old: str, new: str, colors: list[str]) -> None:
    """Save an edited scheme: under its new name, the old one gone."""
    c = custom()
    if old != new:
        c.pop(old, None)
    c[new] = colors
    look.set_setting(CUSTOM_KEY, json.dumps(c))


def all_schemes() -> dict[str, list[str]]:
    return {**schemes.BUILT_IN, **schemes.library_schemes(), **custom()}


def default_scheme() -> str | None:
    name = look.setting(DEFAULT_KEY, "") or None
    return name if name in all_schemes() else None


def recent() -> list[str]:
    v = look.setting(RECENT_KEY, [])
    names = [v] if isinstance(v, str) else list(v or [])
    return [n for n in names if n in all_schemes()]


def used(name: str) -> None:
    look.set_setting(RECENT_KEY, ([name] + [n for n in recent() if n != name])[:5])


def swatch(colors: list[str], w: int = 84, h: int = 14) -> QIcon:
    pm = QPixmap(w, h)
    pm.fill(Qt.transparent)
    from PySide6.QtGui import QPainter

    p = QPainter(pm)
    n = max(1, min(len(colors), 6))
    cw = w / n
    for i, c in enumerate(colors[:n]):
        p.fillRect(int(i * cw) + 1, 1, int(cw) - 2, h - 2, QColor(c))
    p.end()
    return QIcon(pm)


def swatch_pixmap(colors: list[str], w: int = 168, h: int = 22) -> QPixmap:
    """A scheme's colours as large boxes (for the Color Scheme menu)."""
    from PySide6.QtGui import QPainter

    dpr = 2
    pm = QPixmap(w * dpr, h * dpr)
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    n = max(1, min(len(colors), 8))
    cw = w / n
    p.setPen(QColor(0, 0, 0, 60))
    for i, c in enumerate(colors[:n]):
        p.setBrush(QColor(c))
        p.drawRoundedRect(int(i * cw) + 1, 1, int(cw) - 3, h - 3, 3, 3)
    p.end()
    return pm


def scheme_row(menu, name: str, colors: list[str], on_pick, label: str | None = None):
    """A menu entry showing the scheme's name (or `label`) beside its colours,
    large enough to tell them apart (a plain menu icon is 16 px)."""
    from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget, QWidgetAction

    w = QWidget()
    w.setObjectName("schemeRow")
    w.setAttribute(Qt.WA_StyledBackground)
    h = QHBoxLayout(w)
    h.setContentsMargins(10, 3, 10, 3)
    sw = QLabel()
    sw.setPixmap(swatch_pixmap(colors))
    name_l = QLabel(label or name)
    h.addWidget(sw)
    h.addSpacing(8)
    h.addWidget(name_l, 1)
    act = QWidgetAction(menu)
    act.setDefaultWidget(w)
    act.setText(name)

    def press(_e, act=act):
        menu_top = menu
        while menu_top.parent() is not None and hasattr(menu_top.parent(), "close") and \
                menu_top.parent().__class__.__name__ == "QMenu":
            menu_top = menu_top.parent()
        menu_top.close()
        on_pick(name)

    w.mousePressEvent = press
    act.triggered.connect(lambda: on_pick(name))
    menu.addAction(act)
    return act


class DefineSchemeDialog(QDialog):
    """A new scheme, or an edited one (`editing`: the name of the user's
    scheme being changed). Its colours can start from any scheme, be pasted
    as text or read from a file of hex codes, and be added, changed, removed
    and reordered."""

    def __init__(self, colors: list[str], name: str = "", parent=None, editing: str | None = None):
        super().__init__(parent)
        from PySide6.QtWidgets import QComboBox

        self.editing = editing
        self.setWindowTitle("Edit Color Scheme" if editing else "New Color Scheme")
        self.resize(460, 420)
        self.name = QLineEdit(name or editing or "My colors")
        self.start = QComboBox()
        self.start.addItem("(keep these colours)")
        for n in all_schemes():
            self.start.addItem(swatch(all_schemes()[n]), n)
        self.start.currentIndexChanged.connect(self._start_from)
        self.list = QListWidget()
        for c in colors or ["#1f5fd6", "#e0352b"]:
            self._add(c)
        self.list.itemDoubleClicked.connect(self._change)
        buttons = QVBoxLayout()
        for label, fn in (("Add Color…", self._add_new), ("Change…", lambda: self._change(self.list.currentItem())),
                          ("Remove", lambda: self.list.takeItem(self.list.currentRow())),
                          ("Move Up", lambda: self._move(-1)), ("Move Down", lambda: self._move(1)),
                          ("Paste Colors…", self._paste), ("Import From File…", self._import_file)):
            b = QPushButton(label)
            b.clicked.connect(fn)
            buttons.addWidget(b)
        buttons.addStretch(1)
        row = QHBoxLayout()
        row.addWidget(self.list, 1)
        row.addLayout(buttons)
        form = QFormLayout()
        form.addRow("Name", self.name)
        form.addRow("Start from", self.start)
        ok = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        ok.accepted.connect(self.accept)
        ok.rejected.connect(self.reject)
        v = QVBoxLayout(self)
        v.addLayout(form)
        v.addLayout(row, 1)
        v.addWidget(ok)

    def colors(self) -> list[str]:
        return [self.list.item(i).data(Qt.UserRole) for i in range(self.list.count())]

    def set_colors(self, colors: list[str]) -> None:
        self.list.clear()
        for c in colors:
            self._add(c)

    def _start_from(self, i: int) -> None:
        if i > 0:
            name = self.start.itemText(i)
            self.set_colors(all_schemes()[name])
            if not self.editing and self.name.text() in ("", "My colors"):
                self.name.setText(f"{name} (mine)")

    def _paste(self) -> None:
        from PySide6.QtWidgets import QInputDialog

        text, ok = QInputDialog.getMultiLineText(self, "Paste Colors",
                                                 "Hex codes in any layout (#6F91B8 #A9CBE3 …):")
        cols = schemes.parse_colors(text) if ok else []
        if cols:
            self.set_colors(cols)

    def _import_file(self, path: str | None = None) -> bool:
        """Colours from a file of hex codes (any text: a list, CSS, an R
        vector, a GIMP palette); the scheme takes the file's name."""
        import os

        from PySide6.QtWidgets import QFileDialog, QMessageBox

        if path is None:
            path, _ = QFileDialog.getOpenFileName(self, "Import Colors", "", "Colour lists (*.txt *.csv *.json *.gpl "
                                                  "*.css *.R *.hex);;All files (*)")
        if not path:
            return False
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                cols = schemes.parse_colors(f.read())
        except OSError as e:
            QMessageBox.warning(self, "Import Colors", str(e))
            return False
        if not cols:
            QMessageBox.information(self, "Import Colors", "No hex colour codes (#RRGGBB) in that file.")
            return False
        self.set_colors(cols)
        if self.name.text() in ("", "My colors"):
            self.name.setText(os.path.splitext(os.path.basename(path))[0])
        return True

    def _add(self, c: str) -> None:
        it = QListWidgetItem(swatch([c], 40, 16), c)
        it.setData(Qt.UserRole, c)
        self.list.addItem(it)

    def _add_new(self) -> None:
        c = QColorDialog.getColor(QColor("#808080"), self, "Add Color")
        if c.isValid():
            self._add(c.name())

    def _change(self, it) -> None:
        if it is None:
            return
        c = QColorDialog.getColor(QColor(it.data(Qt.UserRole)), self, "Change Color")
        if c.isValid():
            it.setData(Qt.UserRole, c.name())
            it.setText(c.name())
            it.setIcon(swatch([c.name()], 40, 16))

    def _move(self, d: int) -> None:
        r = self.list.currentRow()
        if r < 0 or not 0 <= r + d < self.list.count():
            return
        it = self.list.takeItem(r)
        self.list.insertItem(r + d, it)
        self.list.setCurrentRow(r + d)

    def scheme(self) -> tuple[str, list[str]]:
        return self.name.text().strip() or "My colors", self.colors()
