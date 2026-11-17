"""Write the license and notice files the packages ship (LICENSES/ beside the
app): Refract's notice (refract.about), its license and complete source
code, and the license texts of every bundled component, read from the build
environment where the wheels carry them. PySide6/Qt wheels carry none, so
the LGPL-3.0 text (the FSF's, verbatim copying permitted) is kept in
tools/packaging/licenses; the GPL-3.0 text is Refract's own LICENSE.

GPL-3.0 (Refract): every package carries the Corresponding Source, the files
needed to build it (SOURCE_PATHS, as committed in git), so the source always
travels with the binary. Nothing else from the repository is included: no
docs, tests or corpus files.

LGPL-3.0 (Qt, PySide6): the app loads Qt as separate shared libraries that
a user can replace; the source is available from the Qt Project and PySide.

  .venv-build/bin/python tools/packaging/collect_licenses.py OUT_DIR
"""

from __future__ import annotations

import glob
import io
import os
import shutil
import subprocess
import sys
import sysconfig
import tarfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, ROOT)

from refract import about

SOURCES = (
    "Qt: https://download.qt.io/official_releases/qt/ (and https://code.qt.io)\n"
    "PySide6 and Shiboken6: https://code.qt.io/cgit/pyside/pyside-setup.git\n")


# what it takes to build the packages: the package, the packaging tools, the
# project metadata, the license and the read-me
PALETTE_NOTICES = {
    "ColorBrewer": ("The RColorBrewer palettes in Refract's Color Scheme menu are the ColorBrewer colour "
                    "specifications and designs\ndeveloped by Cynthia Brewer (http://colorbrewer.org/), "
                    "Copyright (c) 2002 Cynthia Brewer, Mark Harrower,\nand The Pennsylvania State University, "
                    "licensed under the Apache License, Version 2.0 (LICENSE-2.0.txt).\nTaken from the R "
                    "package RColorBrewer (R/ColorBrewer.R): https://cran.r-project.org/package=RColorBrewer\n"),
    "ggsci": ("The ggsci palettes in Refract's Color Scheme menu are taken from the R package ggsci "
              "(R/palettes.R),\nCopyright (c) Nan Xiao and contributors, licensed under the GNU General Public "
              "License, version 3 or later\n(GPL-3.0.txt). https://github.com/nanxstats/ggsci\n"),
}
SOURCE_PATHS = ("refract", "tools/packaging", ".github/workflows/package.yml",
                "pyproject.toml", "LICENSE", "README.md")


def source_files() -> list[str]:
    """The committed files under SOURCE_PATHS (git ls-files), so local,
    ignored or untracked files never get in."""
    out = subprocess.run(["git", "-C", ROOT, "ls-files", "-z", "--", *SOURCE_PATHS],
                         check=True, capture_output=True).stdout.decode()
    files = sorted(f for f in out.split("\0") if f)
    if "LICENSE" not in files or not any(f.startswith("refract/") for f in files):
        raise SystemExit("source archive: run from a git checkout of Refract")
    return files


def source_archive(dst: str) -> list[str]:
    """Write refract-<version>-source.tar.gz of source_files() under a
    refract-<version>/ folder; reproducible (fixed times and owners)."""
    top = f"refract-{about.VERSION}"
    files = source_files()
    with tarfile.open(dst, "w:gz", format=tarfile.PAX_FORMAT) as tar:
        for f in files:
            with open(os.path.join(ROOT, f), "rb") as fh:
                data = fh.read()
            info = tarfile.TarInfo(f"{top}/{f}")
            info.size, info.mtime, info.mode = len(data), 0, 0o644
            info.uname = info.gname = ""
            tar.addfile(info, io.BytesIO(data))
    return files


def _dist_licenses(name: str) -> list[str]:
    site = sysconfig.get_paths()["purelib"]
    out = []
    for d in glob.glob(os.path.join(site, f"{name}-*.dist-info")):
        for pat in ("LICENSE*", "COPYING*", "licenses/**/*"):
            out += [f for f in glob.glob(os.path.join(d, pat), recursive=True) if os.path.isfile(f)]
    return sorted(set(out))


def collect(out: str) -> list[str]:
    os.makedirs(out, exist_ok=True)
    written = []

    def put(name: str, src: str | None = None, text: str | None = None) -> None:
        dst = os.path.join(out, name)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if src:
            shutil.copyfile(src, dst)
        else:
            with open(dst, "w", encoding="utf-8") as f:
                f.write(text)
        written.append(name)

    put("NOTICE.txt", text=about.about_text() + "\n")
    put("Refract/LICENSE.txt", os.path.join(ROOT, "LICENSE"))
    src = f"Refract/refract-{about.VERSION}-source.tar.gz"
    source_archive(os.path.join(out, src))
    written.append(src)
    py = os.path.join(sys.base_prefix, "lib", f"python{sys.version_info.major}.{sys.version_info.minor}", "LICENSE.txt")
    if not os.path.exists(py):
        py = os.path.join(sys.base_prefix, "LICENSE.txt")  # Windows layout
    put("Python/LICENSE.txt", py)
    for dist, folder in (("numpy", "NumPy"), ("scipy", "SciPy")):
        files = _dist_licenses(dist)
        if not files:
            raise SystemExit(f"no license files found for {dist}")
        base = os.path.commonpath([os.path.dirname(f) for f in files])
        for f in files:
            put(os.path.join(folder, os.path.relpath(f, base)), f)
    put("Qt-PySide6/LGPL-3.0.txt", os.path.join(HERE, "licenses", "LGPL-3.0.txt"))
    put("Qt-PySide6/GPL-3.0.txt", os.path.join(ROOT, "LICENSE"))  # the LGPL builds on it
    put("Qt-PySide6/SOURCE.txt", text="Refract uses Qt 6 and PySide6 under the LGPL-3.0. Their source code:\n" + SOURCES)
    # colour palettes (refract/render/palette_library.py, made by tools/make_palettes.py)
    put("ColorBrewer/LICENSE-2.0.txt", os.path.join(HERE, "licenses", "Apache-2.0.txt"))
    put("ColorBrewer/NOTICE.txt", text=PALETTE_NOTICES["ColorBrewer"])
    put("ggsci/NOTICE.txt", text=PALETTE_NOTICES["ggsci"])
    put("ggsci/GPL-3.0.txt", os.path.join(ROOT, "LICENSE"))
    return written


if __name__ == "__main__":
    files = collect(sys.argv[1])
    print(f"{len(files)} license files in {sys.argv[1]}")
