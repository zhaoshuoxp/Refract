"""Start the desktop app: `refract gui [FILE]` or `python -m refract.ui [FILE]`
(the packaged app runs this too: tools/packaging/refract_app.py).

Files come from the command line (Windows "Open with", a terminal) or, on
macOS, as file-open events: Finder sends one when a document is opened with
Refract, including the one that launched it, which can arrive before the
window exists. Those are kept until the window is up.
"""

from __future__ import annotations

import sys


def _application_class():
    from PySide6.QtCore import QEvent
    from PySide6.QtWidgets import QApplication

    class Application(QApplication):
        def __init__(self, args):
            super().__init__(args)
            self.window = None
            self.pending: list[str] = []

        def event(self, e):
            if e.type() == QEvent.FileOpen and e.file():
                self.open_file(e.file())
                return True
            return super().event(e)

        def open_file(self, path: str) -> None:
            if self.window is None:
                self.pending.append(path)
            else:
                self.window.open_request(path)

        def attach(self, window) -> None:
            self.window = window
            for path in self.pending:
                window.open_request(path)
            self.pending.clear()

    return Application


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    argv = [a for a in argv if not a.startswith("-psn_")]  # macOS process serial number (old launchers)
    from ..render import qt

    qt.prepare_qt()
    from .. import about
    from . import look
    from .main_window import MainWindow

    app = _application_class()([sys.argv[0], *argv])
    app.setApplicationName(about.APP_NAME)
    app.setApplicationVersion(about.VERSION)
    app.setWindowIcon(look.app_icon())
    w = MainWindow()
    if argv:
        app.open_file(argv[0])
    w.show()
    app.attach(w)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
