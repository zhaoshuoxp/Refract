"""Product facts shown in the About box, `refract --version` and the packages
(tools/packaging): name, version, the non-affiliation notice, Refract's
own license and the third-party components shipped with the app (PLAN §1.4, phase 7)."""

from __future__ import annotations

from . import __version__

APP_NAME = "Refract"
VERSION = __version__
BUNDLE_ID = "org.refract.app"
COPYRIGHT = "Copyright © 2026 the Refract authors"

# Refract's own license (PLAN §7 item 2, decided 2026-11-15); its text is LICENSE
LICENSE = "GPL-3.0-or-later"
LICENSE_NOTICE = (
    "Refract is free software: you can redistribute it and/or modify it under the "
    "terms of the GNU General Public License as published by the Free Software "
    "Foundation, either version 3 of the License, or (at your option) any later "
    "version. It is distributed WITHOUT ANY WARRANTY; without even the implied "
    "warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU "
    "General Public License for details.")
# where a package keeps the license text and the complete source code
# (tools/packaging/collect_licenses.py)
SOURCE_NOTE = ("The license text and Refract's complete source code are included "
               "with the app, in its LICENSES/Refract folder.")

# PLAN §1.4: say what the app opens, never use the other product's name as ours
NOTICE = (
    "Refract is an independent project. It is not affiliated with, endorsed by or "
    "sponsored by GraphPad Software, LLC or Dotmatics. GraphPad and Prism are "
    "trademarks of GraphPad Software, LLC; they are used here only to say which "
    "files Refract can open and save.")

SUMMARY = "Graphing and statistics for scientists. Opens and saves .prism and .pzfx files."

# (component, license): the libraries the packaged app ships. Their license
# texts are copied into the package (tools/packaging/collect_licenses.py).
COMPONENTS = (
    ("Python", "PSF License"),
    ("Qt 6 and PySide6", "LGPL-3.0"),
    ("NumPy", "BSD-3-Clause"),
    ("SciPy", "BSD-3-Clause"),
    ("ColorBrewer palettes (via RColorBrewer)", "Apache-2.0"),
    ("ggsci palettes", "GPL-3.0-or-later"),
)

# file types Refract opens; it registers as an alternative handler only, so it
# never becomes their default application (PLAN phase 7)
# (extension, description, macOS type identifier, the types it conforms to): the
# identifiers macOS reports for these files when Prism is installed (mdls
# kMDItemContentType on corpus files); Refract only imports them, so Prism's own
# declaration wins where Prism is installed
DOCUMENT_TYPES = (
    ("prism", "Prism project", "com.graphpad.prism.bundledocument", ("public.data", "public.composite-content")),
    ("pzfx", "Prism XML project", "com.graphpad.prism.xmldocument", ("public.xml",)),
)


def about_text() -> str:
    """Plain-text About information."""
    parts = [f"{APP_NAME} {VERSION}", SUMMARY, "", NOTICE, "",
             f"{COPYRIGHT}. License: {LICENSE}.", LICENSE_NOTICE, SOURCE_NOTE, "", "Includes:"]
    parts += [f"  {name} ({lic})" for name, lic in COMPONENTS]
    return "\n".join(parts)
