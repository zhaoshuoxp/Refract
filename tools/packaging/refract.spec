# PyInstaller spec for Refract (macOS .app and Windows folder build).
# Run through tools/packaging/build_macos.sh or build_windows.ps1, which set:
#   REFRACT_MIN_MACOS   LSMinimumSystemVersion (the highest minos of the bundled binaries)
#   REFRACT_ICON_DIR    where make_icon.py wrote Refract.icns / Refract.ico
#   REFRACT_TARGET_ARCH macOS only; default: this Python's (releases are arm64 only)
import os
import sys

HERE = os.path.dirname(os.path.abspath(SPEC))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)

from plist import info_plist  # noqa: E402

ICONS = os.environ.get("REFRACT_ICON_DIR", os.path.join(ROOT, "build", "icons"))
MAC = sys.platform == "darwin"

# package data read at run time next to the modules (seeds, analysis defaults, guide)
datas = [
    (os.path.join(ROOT, "refract", "formats", "seed_graphs"), "refract/formats/seed_graphs"),
    (os.path.join(ROOT, "refract", "stats", "defaults.json"), "refract/stats"),
    (os.path.join(ROOT, "refract", "ui", "guide.md"), "refract/ui"),
]

# Qt parts Refract does not use (it needs QtCore, QtGui, QtWidgets, QtSvg and the
# platform, style, image-format and icon-engine plugins)
EXCLUDES = ["tkinter", "PySide6.QtNetwork", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtOpenGL",
            "PySide6.QtDBus", "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtDesigner", "PySide6.QtUiTools",
            "PySide6.QtHelp", "PySide6.QtXml", "PySide6.QtConcurrent", "PySide6.QtPrintSupport",
            "pytest", "IPython", "matplotlib", "PIL", "pypdfium2"]

a = Analysis(
    [os.path.join(HERE, "refract_app.py")],
    pathex=[ROOT],
    datas=datas,
    hiddenimports=["refract.formats.pcff.skeleton_data"],
    excludes=EXCLUDES,
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Refract",
    console=False,
    argv_emulation=False,  # file-open events reach Qt directly (refract.ui.app)
    target_arch=os.environ.get("REFRACT_TARGET_ARCH") or None,
    icon=os.path.join(ICONS, "Refract.icns" if MAC else "Refract.ico"),
    codesign_identity=None,  # signed afterwards by build_macos.sh
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="Refract", upx=False)
if MAC:
    app = BUNDLE(
        coll,
        name="Refract.app",
        icon=os.path.join(ICONS, "Refract.icns"),
        bundle_identifier=None,  # set by info_plist
        info_plist=info_plist(os.environ.get("REFRACT_MIN_MACOS", "13.0")),
    )
