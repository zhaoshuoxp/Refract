"""Phase 7 packaging (tools/packaging): the file association never takes over
the default application, the non-affiliation notice, package data, licenses,
the About box and Help, file-open events, and the self-test."""

import os
import re
import sys
import types

import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..")
PKG = os.path.join(ROOT, "tools", "packaging")
sys.path.insert(0, PKG)


def test_version_and_names():
    import refract
    from refract import about

    assert re.fullmatch(r"\d+\.\d+\.\d+", refract.__version__)
    assert about.VERSION == refract.__version__
    # PLAN §1.4: our own product name; the other product is named only to say what we open
    for text in (about.APP_NAME, about.BUNDLE_ID, about.SUMMARY):
        assert "prism" not in text.lower().replace(".prism", "") and "graphpad" not in text.lower()
    assert "not affiliated" in about.NOTICE and "trademarks of GraphPad" in about.NOTICE
    assert about.NOTICE in about.about_text()
    # PLAN §7 item 2: GPL-3.0-or-later, the text in LICENSE and the package metadata
    assert about.LICENSE == "GPL-3.0-or-later" and about.LICENSE_NOTICE in about.about_text()
    with open(os.path.join(ROOT, "LICENSE"), encoding="utf-8") as f:
        text = f.read()
    assert "GNU GENERAL PUBLIC LICENSE" in text and "Version 3, 29 June 2007" in text
    with open(os.path.join(ROOT, "pyproject.toml"), encoding="utf-8") as f:
        assert 'license = "GPL-3.0-or-later"' in f.read()


def test_cli_version(capsys):
    from refract import about, cli

    with pytest.raises(SystemExit):
        cli.main(["--version"])
    assert capsys.readouterr().out.strip() == f"{about.APP_NAME} {about.VERSION}"


def test_macos_plist_is_an_alternate_handler_only():
    from plist import info_plist

    from refract import about

    p = info_plist("14.4")
    assert p["CFBundleIdentifier"] == about.BUNDLE_ID and p["CFBundleShortVersionString"] == about.VERSION
    assert p["LSMinimumSystemVersion"] == "14.4"
    docs = p["CFBundleDocumentTypes"]
    assert {d["LSItemContentTypes"][0] for d in docs} == {t[2] for t in about.DOCUMENT_TYPES}
    assert all(d["LSHandlerRank"] == "Alternate" for d in docs)  # never the default
    # imported, not exported: the file types are not ours to define
    assert "UTExportedTypeDeclarations" not in p
    exts = {e for t in p["UTImportedTypeDeclarations"] for e in t["UTTypeTagSpecification"]["public.filename-extension"]}
    assert exts == {"prism", "pzfx"}


def test_windows_installer_never_sets_the_default():
    with open(os.path.join(PKG, "refract.iss"), encoding="utf-8") as f:
        lines = [ln for ln in f if ln.startswith("Root:")]
    for ext in (".prism", ".pzfx"):
        keys = [ln for ln in lines if f'Subkey: "Software\\Classes\\{ext}' in ln]
        assert keys and all("OpenWithProgids" in ln for ln in keys), keys
        assert not any(f'Subkey: "Software\\Classes\\{ext}"' in ln for ln in lines)  # its default value
    assert any("SupportedTypes" in ln and ".prism" in ln for ln in lines)


def test_spec_ships_every_package_data_file():
    with open(os.path.join(PKG, "refract.spec"), encoding="utf-8") as f:
        spec = f.read()
    shipped = re.findall(r'os\.path\.join\(ROOT, ((?:"[^"]+", )*"[^"]+")\)', spec)
    shipped = [os.path.join(*re.findall(r'"([^"]+)"', s)) for s in shipped]
    for dirpath, dirs, files in os.walk(os.path.join(ROOT, "refract")):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for f in files:
            if f.endswith((".py", ".pyc")):
                continue
            rel = os.path.relpath(os.path.join(dirpath, f), ROOT)
            assert any(rel == s or rel.startswith(s + os.sep) for s in shipped), f"{rel} not in refract.spec datas"


def test_licenses(tmp_path):
    from collect_licenses import collect

    files = collect(str(tmp_path))
    assert "NOTICE.txt" in files and "Python/LICENSE.txt" in files
    assert any(f.startswith("NumPy/") for f in files) and any(f.startswith("SciPy/") for f in files)
    lgpl = (tmp_path / "Qt-PySide6" / "LGPL-3.0.txt").read_text()
    assert "GNU LESSER GENERAL PUBLIC LICENSE" in lgpl and "Version 3" in lgpl
    assert "GNU GENERAL PUBLIC LICENSE" in (tmp_path / "Qt-PySide6" / "GPL-3.0.txt").read_text()
    with open(os.path.join(ROOT, "LICENSE"), encoding="utf-8") as f:
        assert (tmp_path / "Refract" / "LICENSE.txt").read_text() == f.read()


def test_source_archive_has_the_source_and_nothing_else(tmp_path):
    import tarfile

    from collect_licenses import SOURCE_PATHS, source_archive

    from refract import about

    dst = tmp_path / "src.tar.gz"
    files = source_archive(str(dst))
    top = f"refract-{about.VERSION}/"
    with tarfile.open(dst) as tar:
        names = tar.getnames()
    assert names == [top + f for f in files]
    for need in ("LICENSE", "pyproject.toml", "refract/about.py", "tools/packaging/refract.spec",
                 "refract/formats/seed_graphs/index.json"):
        assert need in files
    # only what builds the app: no docs, tests, corpus or other tools, and no
    # Prism files (the shipped seed graphs are .pcff structures, PLAN §7 item 7)
    assert all(any(f == p or f.startswith(p + "/") for p in SOURCE_PATHS) for f in files)
    assert not any(f.startswith(("docs/", "tests/", "corpus/")) or f.endswith((".prism", ".pzfx")) for f in files)


def test_guide_text():
    from refract import about

    with open(os.path.join(ROOT, "refract", "ui", "guide.md"), encoding="utf-8") as f:
        guide = f.read()
    assert about.NOTICE in guide and about.LICENSE_NOTICE in guide and about.SOURCE_NOTE in guide
    assert "LSHandlerRank" not in guide  # written for users


# ------------------------------------------------------------------ Qt parts
@pytest.fixture(scope="module")
def app(tmp_path_factory):
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ["REFRACT_SETTINGS"] = str(tmp_path_factory.mktemp("settings") / "refract.ini")
    from refract.render import qt

    return qt.ensure_app()


def test_icon(app):
    from refract.ui import app_icon

    img = app_icon.image(64)
    assert img.width() == 64
    assert img.pixelColor(32, 32).alpha() == 255 and img.pixelColor(0, 0).alpha() == 0  # tile with a margin
    assert not app_icon.icon().isNull()
    # a light and a dark variant (the tile: pale or deep blue), and a full-bleed layer for Icon Composer
    light, dark = app_icon.image(64).pixelColor(10, 32), app_icon.image(64, dark=True).pixelColor(10, 32)
    assert light.lightness() > 180 and dark.lightness() < 90
    assert app_icon.image(64, bleed=True).pixelColor(0, 0).alpha() == 255
    assert not app_icon.icon(dark=True).isNull()
    from plist import info_plist

    assert info_plist("14.4")["CFBundleIconName"] == "AppIcon"


def test_help_menu_about_and_guide(app, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from refract import about
    from refract.ui import help_view
    from refract.ui.main_window import MainWindow

    w = MainWindow()
    menus = {m.title().replace("&", ""): m for m in (a.menu() for a in w.menuBar().actions()) if m}
    texts = [a.text() for a in menus["Help"].actions()]
    assert texts == ["Refract User Guide", "About Refract"]
    shown = {}
    monkeypatch.setattr(QMessageBox, "exec", lambda self: shown.update(text=self.text(), info=self.informativeText()))
    w.show_about()
    assert about.VERSION in shown["text"] and "not affiliated" in shown["info"]
    assert about.LICENSE in shown["info"] and "WITHOUT ANY WARRANTY" in shown["info"]
    from PySide6.QtWidgets import QTextBrowser

    d = help_view.show(w)
    assert "Data tables" in d.findChild(QTextBrowser).toPlainText()  # rendered Markdown
    assert help_view.show(w) is d  # one guide window
    d.close()
    w.close()


def test_file_open_events_wait_for_the_window():
    pytest.importorskip("PySide6")
    from refract.ui import app as A

    cls = A._application_class()
    opened = []
    fake = types.SimpleNamespace(window=None, pending=[])
    cls.open_file(fake, "/a.prism")  # Finder's event can come before the window exists
    assert opened == [] and fake.pending == ["/a.prism"]
    win = types.SimpleNamespace(open_request=opened.append)
    cls.attach(fake, win)
    assert opened == ["/a.prism"] and fake.pending == []
    cls.open_file(fake, "/b.pzfx")  # later ones go straight to the window
    assert opened == ["/a.prism", "/b.pzfx"]


def test_open_request_of_the_open_file_does_not_reload(app, tmp_path):
    from refract.model import templates as T
    from refract.ui.document import Document
    from refract.ui.main_window import MainWindow

    doc = Document.new()
    doc.add_table(T.make("column", "C", sample=True))
    path = str(tmp_path / "c.prism")
    doc.save(path)
    w = MainWindow()
    w.open_request(path)
    first = w.doc
    assert first is not None and first.path == path
    w.open_request(path)
    assert w.doc is first
    w.close()


def test_selftest(app, tmp_path, capsys):
    from refract.selftest import run

    assert run(str(tmp_path)) == 0
    report = (tmp_path / "selftest.txt").read_text()
    assert "FAIL" not in report and report.strip().splitlines()[-1].startswith("passed")
    assert (tmp_path / "selftest.prism").exists()
