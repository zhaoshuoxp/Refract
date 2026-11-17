"""Render Refract's icon (refract/ui/app_icon.py) for the packages:
build/icons/Refract.icns (macOS, via iconutil; the light variant),
build/icons/Assets.car (macOS asset catalog via Xcode's actool from an Icon
Composer icon: AppIcon in a light and a dark appearance, so Finder and the
Dock follow the system theme; skipped without Xcode) and build/icons/Refract.ico (Windows, Qt's ico writer).

  .venv-build/bin/python tools/packaging/make_icon.py [OUT_DIR]
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def catalog(A, out: str) -> None:
    """Assets.car (and AppIcon.icns) from an Icon Composer icon, AppIcon.icon: two full-bleed
    layers, the light one hidden in the dark appearance and the dark one in the light, so macOS
    shows the icon of the system theme (macOS 26; earlier versions use the light icon)."""
    import json

    if subprocess.run(["xcrun", "--find", "actool"], capture_output=True).returncode != 0:
        print("warning: no actool (Xcode); Assets.car not written: one icon for both themes")
        return
    work = os.path.join(out, "catalog")
    shutil.rmtree(work, ignore_errors=True)
    icon = os.path.join(work, "AppIcon.icon")
    os.makedirs(os.path.join(icon, "Assets"))
    A.image(1024, False, True).save(os.path.join(icon, "Assets", "light.png"))
    A.image(1024, True, True).save(os.path.join(icon, "Assets", "dark.png"))
    spec = {"groups": [{"layers": [
        {"image-name": "light.png", "name": "light", "hidden-specializations": [{"appearance": "dark", "value": True}]},
        {"image-name": "dark.png", "name": "dark",
         "hidden-specializations": [{"value": True}, {"appearance": "dark", "value": False}]}]}],
        "supported-platforms": {"squares": ["macOS"]}}
    with open(os.path.join(icon, "icon.json"), "w") as f:
        json.dump(spec, f, indent=1)
    subprocess.run(["xcrun", "actool", icon, "--compile", out, "--platform", "macosx",
                    "--minimum-deployment-target", "13.0", "--app-icon", "AppIcon", "--output-partial-info-plist",
                    os.path.join(work, "partial.plist")], check=True, capture_output=True)
    shutil.rmtree(work)


def main() -> int:
    out = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "build", "icons"))
    from refract.render import qt

    qt.ensure_app()  # offscreen, with Qt's plugins visible (qt.prepare_qt)
    from refract.ui import app_icon as A

    os.makedirs(out, exist_ok=True)
    if sys.platform == "darwin":
        iconset = os.path.join(out, "Refract.iconset")
        shutil.rmtree(iconset, ignore_errors=True)
        os.makedirs(iconset)
        for n in (16, 32, 128, 256, 512):
            A.image(n).save(os.path.join(iconset, f"icon_{n}x{n}.png"))
            A.image(2 * n).save(os.path.join(iconset, f"icon_{n}x{n}@2x.png"))
        subprocess.run(["iconutil", "-c", "icns", iconset, "-o", os.path.join(out, "Refract.icns")], check=True)
        shutil.rmtree(iconset)
        catalog(A, out)
    # .ico: Qt writes one image per file, so use the 256 px one (Windows scales it)
    if not A.image(256).save(os.path.join(out, "Refract.ico"), "ICO"):
        print("warning: this Qt has no ICO writer; Refract.ico not written")
    A.image(1024).save(os.path.join(out, "Refract.png"))
    A.image(1024, True).save(os.path.join(out, "Refract-dark.png"))
    print("icons in", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
