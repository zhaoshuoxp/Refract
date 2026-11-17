"""Help > User Guide: the guide shipped inside the package (refract/ui/guide.md),
shown as rendered Markdown, so it works without a network or browser."""

from __future__ import annotations

import os

from PySide6.QtWidgets import QDialog, QTextBrowser, QVBoxLayout

GUIDE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "guide.md")
_OPEN: list[QDialog] = []


def text() -> str:
    with open(GUIDE, encoding="utf-8") as f:
        return f.read()


def show(parent=None) -> QDialog:
    if _OPEN:
        _OPEN[0].raise_()
        _OPEN[0].activateWindow()
        return _OPEN[0]
    d = QDialog(parent)
    d.setWindowTitle("Refract User Guide")
    b = QTextBrowser(d)
    b.setOpenExternalLinks(True)
    b.setMarkdown(text())
    lay = QVBoxLayout(d)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.addWidget(b)
    d.resize(720, 760)
    d.finished.connect(lambda *_: _OPEN.clear())
    _OPEN.append(d)
    d.show()
    return d
