"""JSON in the two layouts Prism writes (prismbinder docs/format §4).

- Most entries: tab indent, ": " separator, no trailing newline.
- data/tables/*/content.json: four-space indent plus a trailing newline.

Python's json already writes integral floats with a decimal point (``95.0``),
keeps key order, and leaves non-ASCII raw when ensure_ascii=False.
These helpers are for documents we synthesise. Editing an existing entry
should change as few bytes as possible (see bundle.py).
"""

from __future__ import annotations

import json
from typing import Any


def dumps(obj: Any) -> bytes:
    return json.dumps(obj, indent="\t", ensure_ascii=False).encode("utf-8")


def dumps_storage(obj: Any) -> bytes:
    return (json.dumps(obj, indent=4, ensure_ascii=False) + "\n").encode("utf-8")


def loads(data: bytes) -> Any:
    return json.loads(data.decode("utf-8"))
