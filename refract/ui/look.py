"""Visual details: icons drawn here (no third-party artwork), the window
style sheet, the start page and recent files (docs/ui-spec.md §1, §2)."""

from __future__ import annotations

import os

from PySide6.QtCore import QPointF, QRectF, QSettings, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QGuiApplication,
    QIcon,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

# Two palettes, chosen from the system's colour scheme (and switched when it
# changes): every colour the window sets is taken from here, never fixed in a
# widget, so text and backgrounds always come from the same palette.
LIGHT = {
    "window": "#f3f4f6", "panel": "#f7f8fa", "bar": "#eceef1", "line": "#d9dce1", "hover": "#dfe3e8",
    "text": "#1d2026", "muted": "#5c636e", "faint": "#9aa0a8", "selected": "#d6e6fa", "selected_text": "#000000",
    "card": "#ffffff", "canvas": "#e4e6ea", "grid": "#d4d4d4", "cell_selected": "#cfe3fb",
    "row_title": "#f6f6f0", "excluded": "#0000e6", "ink": "#464c56", "accent": "#266ec4",
    "accent_soft": "#a0c4ee", "folder": "#fad678", "list_hover": "#eef3fb", "base": "#ffffff",
    "bad": "#b3261e",
}
DARK = {
    "window": "#1e1f22", "panel": "#232428", "bar": "#2b2d31", "line": "#3a3d43", "hover": "#3a3d43",
    "text": "#e6e7ea", "muted": "#a7acb4", "faint": "#6f747c", "selected": "#2f4a6e", "selected_text": "#ffffff",
    "card": "#2b2d31", "canvas": "#18191b", "grid": "#3d4046", "cell_selected": "#2f4a6e",
    "row_title": "#2a2b2f", "excluded": "#7fb2ff", "ink": "#c9cdd3", "accent": "#5a9cf0",
    "accent_soft": "#3f6ea8", "folder": "#d9b257", "list_hover": "#33363b", "base": "#1b1c1f",
    "bad": "#ff8a80",
}


def is_dark() -> bool:
    forced = os.environ.get("REFRACT_THEME")  # tests and users: "dark" or "light"
    if forced in ("dark", "light"):
        return forced == "dark"
    app = QGuiApplication.instance()
    if app is None:
        return False
    scheme = QGuiApplication.styleHints().colorScheme()
    if scheme != Qt.ColorScheme.Unknown:
        return scheme == Qt.ColorScheme.Dark
    return QGuiApplication.palette().window().color().lightness() < 128


def colors() -> dict[str, str]:
    return DARK if is_dark() else LIGHT


def color(name: str) -> QColor:
    return QColor(colors()[name])


def style() -> str:
    """The window's style sheet in the current palette."""
    return """
QMainWindow {{ background: {window}; }}
QTreeWidget#navigator {{ background: {panel}; color: {text}; border: none; border-right: 1px solid {line};
                         font-size: 13px; }}
QTreeWidget#navigator::item {{ height: 24px; padding-left: 2px; }}
QTreeWidget#navigator::item:selected {{ background: {selected}; color: {selected_text}; }}
QToolBar {{ background: {bar}; border-bottom: 1px solid {line}; spacing: 2px; padding: 2px 6px; }}
QToolButton {{ padding: 3px 8px; border-radius: 4px; color: {text}; }}
QToolButton:disabled {{ color: {faint}; }}
QToolButton:hover {{ background: {hover}; }}
QStatusBar {{ background: {bar}; color: {muted}; }}
QTabWidget::pane {{ border: 1px solid {line}; }}
QTreeWidget#results {{ font-size: 13px; }}
QTableView {{ gridline-color: {grid}; selection-background-color: {cell_selected};
              selection-color: {selected_text}; }}
QWidget#zoombar {{ background: {bar}; border-bottom: 1px solid {line}; }}
QWidget#zoombar QLabel {{ color: {text}; }}
QLabel#muted, QLabel#message {{ color: {muted}; }}
QLabel#message {{ padding: 24px; }}
QFrame#card {{ background: {card}; border: 1px solid {line}; border-radius: 10px; }}
QFrame#card QLabel {{ color: {text}; }}
QFrame#card QLabel#muted {{ color: {muted}; }}
QListWidget#recent {{ border: none; background: {card}; color: {text}; }}
QListWidget#recent::item {{ padding: 4px; }}
QListWidget#recent::item:hover {{ background: {list_hover}; }}
QListWidget#recent::item:selected {{ background: {selected}; color: {selected_text}; }}
QDialog#newTable QListWidget#kindList {{ background: {panel}; border: none; border-right: 1px solid {line};
                                        font-size: 14px; padding-top: 10px; }}
QDialog#newTable QListWidget#kindList::item {{ height: 28px; padding-left: 14px; color: {text}; }}
QDialog#newTable QListWidget#kindList::item:selected {{ background: {selected}; color: {selected_text}; }}
QPushButton#primary {{ background: {accent}; color: white; border-radius: 5px; padding: 5px 18px; }}
QToolBar#ribbon {{ padding: 1px 4px; spacing: 0px; }}
QToolBar#ribbon QToolButton {{ padding: 3px; border-radius: 4px; }}
QToolBar#ribbon QToolButton::menu-indicator {{ image: none; width: 0px; }}
QToolBar#ribbon QToolButton:checked {{ background: {selected}; }}
QWidget#ribbonSep {{ background: {line}; margin: 4px 2px; }}
QLabel#ribbonLabel {{ color: {muted}; font-size: 11px; }}
QToolBar#ribbon QComboBox {{ font-size: 13px; min-height: 24px; }}
QWidget#schemeRow {{ border-radius: 4px; }}
QWidget#schemeRow:hover {{ background: {hover}; }}
QWidget#schemeRow QLabel {{ color: {text}; font-size: 13px; }}
""".format(**colors())


STYLE = style  # older name


def _pix(draw) -> QIcon:
    """A 20-unit drawing at 4x (sharp at the toolbar's larger size too)."""
    pm = QPixmap(80, 80)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.scale(4, 4)
    draw(p)
    p.end()
    pm.setDevicePixelRatio(2)
    return QIcon(pm)


def _pen(p: QPainter, c: QColor, w: float = 1.4) -> None:
    pen = QPen(c, w)
    pen.setJoinStyle(Qt.RoundJoin)
    pen.setCapStyle(Qt.RoundCap)
    p.setPen(pen)


def icon(kind: str) -> QIcon:
    """Small line icons for the navigator sections and the toolbar, in the
    current palette (rebuild them when the colour scheme changes)."""
    INK, ACCENT, SOFT, PAPER = color("ink"), color("accent"), color("accent_soft"), color("card")
    GREY = color("muted")

    def table(p):
        _pen(p, INK)
        p.setBrush(PAPER)
        p.drawRoundedRect(QRectF(2.5, 3.5, 15, 13), 1.5, 1.5)
        p.fillRect(QRectF(3.2, 4.2, 13.6, 3.3), SOFT)
        for x in (7.5, 12.5):
            p.drawLine(QPointF(x, 3.5), QPointF(x, 16.5))
        for y in (7.5, 12):
            p.drawLine(QPointF(2.5, y), QPointF(17.5, y))

    def info(p):
        _pen(p, ACCENT, 1.5)
        p.drawEllipse(QPointF(10, 10), 7, 7)
        p.drawLine(QPointF(10, 9), QPointF(10, 14))
        p.setBrush(ACCENT)
        p.drawEllipse(QPointF(10, 6.2), 0.6, 0.6)

    def results(p):
        _pen(p, INK)
        p.setBrush(PAPER)
        p.drawRoundedRect(QRectF(4, 2.5, 12, 15), 1.5, 1.5)
        _pen(p, GREY, 1.2)
        for y in (6.5, 9.5, 12.5):
            p.drawLine(QPointF(6.5, y), QPointF(13.5, y))
        _pen(p, ACCENT, 1.6)
        p.drawLine(QPointF(6.5, 15), QPointF(10.5, 15))

    def graph(p):
        _pen(p, INK)
        p.drawLine(QPointF(3, 3), QPointF(3, 17))
        p.drawLine(QPointF(3, 17), QPointF(17.5, 17))
        p.setPen(Qt.NoPen)
        for x, h, c in ((5.5, 7, GREY), (9.5, 11, ACCENT), (13.5, 5, SOFT)):
            p.setBrush(c)
            p.drawRect(QRectF(x, 16.5 - h, 3, h))

    def layout(p):
        _pen(p, INK)
        p.setBrush(PAPER)
        p.drawRect(QRectF(3, 3, 14, 14))
        p.setBrush(SOFT)
        p.drawRect(QRectF(5, 5, 4.5, 4.5))
        p.drawRect(QRectF(10.5, 10.5, 4.5, 4.5))

    def open_(p):
        _pen(p, INK)
        path = QPainterPath(QPointF(2.5, 6))
        for x, y in ((2.5, 16), (16, 16), (17.5, 8.5), (8, 8.5), (6.5, 6), (2.5, 6)):
            path.lineTo(x, y)
        p.setBrush(color("folder"))
        p.drawPath(path)

    def save(p):
        _pen(p, INK)
        p.setBrush(PAPER)
        p.drawRoundedRect(QRectF(3, 3, 14, 14), 1.5, 1.5)
        p.setBrush(SOFT)
        p.drawRect(QRectF(6, 3, 8, 5))
        p.drawRect(QRectF(6, 11, 8, 6))

    def undo(p, mirror=False):
        if mirror:
            p.translate(20, 0)
            p.scale(-1, 1)
        _pen(p, INK, 1.6)
        path = QPainterPath(QPointF(6, 6))
        path.cubicTo(QPointF(12, 3), QPointF(18, 7), QPointF(15, 13))
        p.drawPath(path)
        p.drawLine(QPointF(6, 6), QPointF(6.5, 11))
        p.drawLine(QPointF(6, 6), QPointF(11, 5))

    def export(p):
        _pen(p, INK)
        p.setBrush(PAPER)
        p.drawRoundedRect(QRectF(3, 6, 11, 11), 1.5, 1.5)
        _pen(p, ACCENT, 1.6)
        p.drawLine(QPointF(8, 11), QPointF(16.5, 3))
        p.drawLine(QPointF(12, 3), QPointF(16.5, 3))
        p.drawLine(QPointF(16.5, 3), QPointF(16.5, 7.5))

    def analyze(p):
        _pen(p, INK, 1.4)
        p.setBrush(PAPER)
        p.drawRoundedRect(QRectF(2.5, 3.5, 11, 13), 1.5, 1.5)
        _pen(p, ACCENT, 1.7)
        path = QPainterPath(QPointF(11.5, 6.5))  # a sigma
        for x, y in ((5.5, 6.5), (9, 10), (5.5, 13.5), (11.5, 13.5)):
            path.lineTo(x, y)
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)
        _pen(p, INK, 1.6)
        p.drawEllipse(QPointF(14.5, 13), 2.6, 2.6)
        p.drawLine(QPointF(16.4, 14.9), QPointF(18.3, 16.8))

    def new_table(p):
        table(p)
        _pen(p, ACCENT, 1.8)
        p.setBrush(PAPER)
        p.drawEllipse(QPointF(15, 15), 4.2, 4.2)
        p.drawLine(QPointF(15, 12.8), QPointF(15, 17.2))
        p.drawLine(QPointF(12.8, 15), QPointF(17.2, 15))

    def plus(p, x=15, y=15):
        _pen(p, ACCENT, 1.8)
        p.setBrush(PAPER)
        p.drawEllipse(QPointF(x, y), 4.2, 4.2)
        p.drawLine(QPointF(x, y - 2.2), QPointF(x, y + 2.2))
        p.drawLine(QPointF(x - 2.2, y), QPointF(x + 2.2, y))

    def page(p):
        _pen(p, INK)
        p.setBrush(PAPER)
        path = QPainterPath(QPointF(4, 2.5))
        for x, y in ((12.5, 2.5), (16, 6), (16, 17.5), (4, 17.5), (4, 2.5)):
            path.lineTo(x, y)
        p.drawPath(path)

    def new_project(p):
        page(p)
        plus(p)

    def save_as(p):
        save(p)
        _pen(p, ACCENT, 1.6)
        p.drawLine(QPointF(11, 16), QPointF(17, 10))

    def new_graph(p):
        graph(p)
        plus(p, 15, 6)

    def new_layout(p):
        layout(p)
        plus(p)

    def arrow(p, left):
        _pen(p, ACCENT, 2.0)
        a, b = (13, 7) if left else (7, 13)
        p.drawLine(QPointF(a, 4), QPointF(b, 10))
        p.drawLine(QPointF(b, 10), QPointF(a, 16))

    def cut(p):
        _pen(p, INK, 1.5)
        p.drawEllipse(QPointF(6, 14.5), 2.6, 2.6)
        p.drawEllipse(QPointF(14, 14.5), 2.6, 2.6)
        p.drawLine(QPointF(7.5, 12.5), QPointF(14, 3))
        p.drawLine(QPointF(12.5, 12.5), QPointF(6, 3))

    def copy(p):
        _pen(p, INK)
        p.setBrush(PAPER)
        p.drawRoundedRect(QRectF(3, 3, 10, 11), 1.5, 1.5)
        p.drawRoundedRect(QRectF(7, 6.5, 10, 11), 1.5, 1.5)

    def paste(p):
        _pen(p, INK)
        p.setBrush(color("folder"))
        p.drawRoundedRect(QRectF(3.5, 4, 13, 14), 1.5, 1.5)
        p.setBrush(PAPER)
        p.drawRoundedRect(QRectF(7, 2.5, 6, 3.5), 1, 1)
        p.drawRect(QRectF(7.5, 8, 7, 8))

    def params(p):
        _pen(p, INK, 1.4)
        for y, x in ((5, 7), (10, 13), (15, 9)):
            p.drawLine(QPointF(3, y), QPointF(17, y))
            p.setBrush(ACCENT)
            p.drawEllipse(QPointF(x, y), 2.1, 2.1)

    def format_graph(p):
        graph(p)
        _pen(p, ACCENT, 2.2)
        p.drawLine(QPointF(11, 11), QPointF(17, 3))
        p.setBrush(ACCENT)
        p.drawEllipse(QPointF(10.5, 11.5), 1.6, 1.6)

    def format_axes(p):
        _pen(p, INK, 1.6)
        p.drawLine(QPointF(4, 3), QPointF(4, 16))
        p.drawLine(QPointF(4, 16), QPointF(17, 16))
        _pen(p, ACCENT, 1.4)
        for y in (5, 8.5, 12):
            p.drawLine(QPointF(2, y), QPointF(4, y))
        for x in (8, 12, 16):
            p.drawLine(QPointF(x, 16), QPointF(x, 18))

    def colors_(p):
        _pen(p, INK)
        p.setBrush(PAPER)
        p.drawEllipse(QPointF(10, 10), 7.5, 7)
        p.setPen(Qt.NoPen)
        for (x, y), c in zip(((6.5, 8), (10, 5.5), (13.5, 8), (12.5, 12.5)),
                             ("#e4572e", "#f3a712", "#29a745", "#2f6ecf"), strict=True):
            p.setBrush(QColor(c))
            p.drawEllipse(QPointF(x, y), 1.7, 1.7)

    def magic(p):
        _pen(p, INK, 2.0)
        p.drawLine(QPointF(4, 17), QPointF(13, 8))
        p.setPen(Qt.NoPen)
        p.setBrush(ACCENT)
        star = QPainterPath(QPointF(15, 2))
        for x, y in ((16, 5), (19, 5.5), (16.5, 7.2), (17.5, 10.3), (15, 8.5), (12.5, 10.3), (13.5, 7.2), (11, 5.5),
                     (14, 5)):
            star.lineTo(x, y)
        star.closeSubpath()
        p.drawPath(star)

    def glyph(p, ch, bold=False, italic=False, under=False, size=12.5):
        f = QFont("Helvetica")
        f.setPixelSize(int(size))
        f.setBold(bold)
        f.setItalic(italic)
        f.setUnderline(under)
        p.setFont(f)
        p.setPen(INK)
        p.drawText(QRectF(0, 0, 20, 19), Qt.AlignCenter, ch)

    def text_box(p):
        _pen(p, GREY, 1.0)
        p.setBrush(PAPER)
        p.drawRect(QRectF(2.5, 3.5, 15, 13))
        glyph(p, "T", True)

    def draw_line(p):
        _pen(p, INK, 1.6)
        p.drawLine(QPointF(4, 16), QPointF(16, 4))

    def draw_arrow(p):
        _pen(p, INK, 1.6)
        p.drawLine(QPointF(4, 16), QPointF(13.5, 6.5))
        p.setPen(Qt.NoPen)
        p.setBrush(INK)
        head = QPainterPath(QPointF(17, 3))
        head.lineTo(15.5, 10)
        head.lineTo(10, 4.5)
        head.closeSubpath()
        p.drawPath(head)

    def draw_rect(p):
        _pen(p, INK, 1.3)
        p.setBrush(SOFT)
        p.drawRect(QRectF(3, 5, 14, 10))

    def draw_ellipse(p):
        _pen(p, INK, 1.3)
        p.setBrush(SOFT)
        p.drawEllipse(QRectF(2.5, 4.5, 15, 11))

    def bigger(p):
        glyph(p, "A", True, size=14)
        _pen(p, ACCENT, 1.5)
        p.drawLine(QPointF(15, 4), QPointF(19, 4))
        p.drawLine(QPointF(17, 2), QPointF(17, 6))

    def smaller(p):
        glyph(p, "A", True, size=10)
        _pen(p, ACCENT, 1.5)
        p.drawLine(QPointF(15, 4), QPointF(19, 4))

    def print_(p):
        _pen(p, INK)
        p.setBrush(PAPER)
        p.drawRect(QRectF(6, 2.5, 8, 5))
        p.setBrush(SOFT)
        p.drawRoundedRect(QRectF(2.5, 7, 15, 7), 1.5, 1.5)
        p.setBrush(PAPER)
        p.drawRect(QRectF(6, 11.5, 8, 6))

    def copy_graph(p):
        copy(p)
        p.setPen(Qt.NoPen)
        for x, h in ((9, 4), (12, 7), (15, 5)):
            p.setBrush(ACCENT)
            p.drawRect(QRectF(x - 1, 16 - h, 2, h))

    def plus_only(p):
        plus(p, 10, 10)

    def graph_type(p):
        _pen(p, INK)
        p.setBrush(PAPER)
        p.drawRoundedRect(QRectF(2, 2, 7.5, 7.5), 1, 1)
        p.drawRoundedRect(QRectF(10.5, 2, 7.5, 7.5), 1, 1)
        p.drawRoundedRect(QRectF(2, 10.5, 7.5, 7.5), 1, 1)
        p.setBrush(SOFT)
        p.drawRoundedRect(QRectF(10.5, 10.5, 7.5, 7.5), 1, 1)
        p.setPen(Qt.NoPen)
        p.setBrush(ACCENT)
        p.drawRect(QRectF(4, 5.5, 1.5, 3))
        p.drawRect(QRectF(6.5, 4, 1.5, 4.5))
        p.drawEllipse(QPointF(14.2, 5.8), 1.4, 1.4)
        p.drawEllipse(QPointF(5.8, 14.2), 2.4, 2.4)

    def guide(p):
        _pen(p, ACCENT, 1.5)
        p.setBrush(PAPER)
        p.drawEllipse(QPointF(10, 10), 7.5, 7.5)
        glyph(p, "?", True, size=12)

    draw = {"tables": table, "infos": info, "results": results, "graphs": graph, "layouts": layout,
            "open": open_, "save": save, "analyze": analyze, "new_table": new_table, "undo": undo,
            "redo": lambda p: undo(p, True), "export": export, "new_project": new_project, "save_as": save_as,
            "new_graph": new_graph, "new_layout": new_layout, "prev": lambda p: arrow(p, True),
            "next": lambda p: arrow(p, False), "cut": cut, "copy": copy, "paste": paste, "params": params,
            "format_graph": format_graph, "format_axes": format_axes, "colors": colors_, "magic": magic,
            "text_box": text_box, "bold": lambda p: glyph(p, "B", True), "italic": lambda p: glyph(p, "I", italic=True),
            "underline": lambda p: glyph(p, "U", under=True), "bigger": bigger, "smaller": smaller, "print": print_,
            "copy_graph": copy_graph, "guide": guide, "graph_type": graph_type, "draw_line": draw_line,
            "draw_arrow": draw_arrow, "draw_rect": draw_rect, "draw_ellipse": draw_ellipse,
            "plus": plus_only}[kind]
    return _pix(draw)


# ------------------------------------------------------------- recent files
MAX_RECENT = 8


def _settings() -> QSettings:
    path = os.environ.get("REFRACT_SETTINGS")  # tests: an ini file instead of the user's preferences
    return QSettings(path, QSettings.IniFormat) if path else QSettings("Refract", "Refract")


def setting(key: str, default=None):
    v = _settings().value(key, default)
    if isinstance(default, bool):
        return v in (True, "true", "1", 1)
    return v


def set_setting(key: str, value) -> None:
    _settings().setValue(key, value)


def recent_files() -> list[str]:
    v = _settings().value("recent", [])
    files = [v] if isinstance(v, str) else list(v or [])
    return [f for f in files if os.path.exists(f)]


def add_recent(path: str) -> None:
    files = [os.path.abspath(path)] + [f for f in recent_files() if f != os.path.abspath(path)]
    _settings().setValue("recent", files[:MAX_RECENT])


class StartPage(QWidget):
    """Shown with no document open: a new project, open a file, or one of the
    recent ones."""

    openRequested = Signal()
    newRequested = Signal()
    recentRequested = Signal(str)

    def __init__(self):
        super().__init__()
        card = QFrame()
        card.setObjectName("card")
        card.setFixedWidth(460)
        v = QVBoxLayout(card)
        v.setContentsMargins(28, 24, 28, 24)
        title = QLabel("Refract")
        f = QFont()
        f.setPointSize(24)
        f.setBold(True)
        title.setFont(f)
        sub = QLabel("Graphs and statistics; opens and saves .prism and .pzfx projects.")
        sub.setObjectName("muted")
        sub.setWordWrap(True)
        new = QPushButton("New project…")
        new.setIcon(icon("new_table"))
        new.setMinimumHeight(34)
        new.clicked.connect(self.newRequested)
        btn = QPushButton("Open a project…")
        btn.setIcon(icon("open"))
        btn.setMinimumHeight(34)
        btn.clicked.connect(self.openRequested)
        self.recent = QListWidget()
        self.recent.setObjectName("recent")
        self.recent.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.recent.setTextElideMode(Qt.ElideMiddle)
        self.recent.setIconSize(QSize(18, 18))
        self.recent.itemActivated.connect(self._activated)  # a bound method, not a lambda holding self
        self.recent_label = QLabel("Recent")
        self.recent_label.setObjectName("muted")
        self.recent_label.setContentsMargins(0, 10, 0, 0)
        for w in (title, sub, new, btn, self.recent_label, self.recent):
            v.addWidget(w)
        outer = QVBoxLayout(self)
        outer.addStretch(1)
        outer.addWidget(card, 0, Qt.AlignHCenter)
        outer.addStretch(2)
        self.refresh()

    def _activated(self, item) -> None:
        self.recentRequested.emit(item.data(Qt.UserRole))

    def refresh(self) -> None:
        self.recent.clear()
        files = recent_files()
        home = os.path.expanduser("~")
        for f in files:
            folder = os.path.dirname(f)
            folder = "~" + folder[len(home):] if folder.startswith(home) else folder
            it = QListWidgetItem(icon("tables"), f"{os.path.basename(f)}\n{folder}")
            it.setData(Qt.UserRole, f)
            it.setToolTip(f)
            it.setSizeHint(QSize(0, 44))
            self.recent.addItem(it)
        self.recent_label.setVisible(bool(files))
        self.recent.setVisible(bool(files))
        self.recent.setFixedHeight(min(len(files), MAX_RECENT) * 44 + 6)


def app_icon() -> QIcon:
    """Refract's own icon (refract.ui.app_icon)."""
    from . import app_icon as A

    return A.icon()
