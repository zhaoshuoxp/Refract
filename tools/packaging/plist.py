"""The macOS Info.plist entries of Refract.app (used by refract.spec, checked by
tests/test_packaging.py).

File association (PLAN phase 7): Refract lists .prism and .pzfx as documents
it can open with LSHandlerRank "Alternate", so it shows up under Finder's
"Open With" but never becomes their default application, whether or not
Prism is installed. The two file types are imported declarations
(UTImportedTypeDeclarations): where Prism is installed its own exported
declaration wins, elsewhere ours tells macOS what the extensions are.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

from refract import about


def info_plist(min_macos: str) -> dict:
    docs, types = [], []
    for ext, desc, uti, conforms in about.DOCUMENT_TYPES:
        docs.append({
            "CFBundleTypeName": desc,
            "CFBundleTypeRole": "Editor",
            "LSHandlerRank": "Alternate",
            "LSItemContentTypes": [uti],
        })
        types.append({
            "UTTypeIdentifier": uti,
            "UTTypeDescription": desc,
            "UTTypeConformsTo": list(conforms),
            "UTTypeTagSpecification": {"public.filename-extension": [ext]},
        })
    return {
        "CFBundleName": about.APP_NAME,
        "CFBundleDisplayName": about.APP_NAME,
        "CFBundleIdentifier": about.BUNDLE_ID,
        "CFBundleShortVersionString": about.VERSION,
        "CFBundleVersion": about.VERSION,
        "CFBundleDocumentTypes": docs,
        "UTImportedTypeDeclarations": types,
        "LSMinimumSystemVersion": min_macos,
        "LSApplicationCategoryType": "public.app-category.education",
        "NSHumanReadableCopyright": about.COPYRIGHT,
        "NSHighResolutionCapable": True,
        "NSRequiresAquaSystemAppearance": False,  # follows the system's dark mode
        "CFBundleIconName": "AppIcon",  # Assets.car: the light and dark icon (make_icon.py); else the .icns
        "NSPrincipalClass": "NSApplication",
    }
