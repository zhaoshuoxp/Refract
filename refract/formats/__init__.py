"""File-format layer. `open_document` dispatches on magic bytes, not the
extension (.pzt can be XML, ZIP or legacy binary; prismbinder §1)."""

from __future__ import annotations

from ..model.document import Graph, Project


def sniff(data: bytes) -> str:
    if data[:4] == b"PK\x03\x04":
        return "prism"
    if data[:8] == b"PCFFGRA4":
        return "pcff"
    head = data[:64].lstrip(b"\xef\xbb\xbf").lstrip()
    if head.startswith(b"<"):
        return "pzfx"
    return "unknown"


def open_document(path_or_bytes: str | bytes) -> Project:
    if isinstance(path_or_bytes, bytes):
        data = path_or_bytes
    else:
        with open(path_or_bytes, "rb") as f:
            data = f.read()
    kind = sniff(data)
    if kind == "prism":
        from .prism_reader import read_prism
        return read_prism(data)
    if kind == "pzfx":
        from .pzfx_reader import read_pzfx
        return read_pzfx(data)
    if kind == "pcff":
        p = Project("pzf")
        p.graphs.append(Graph("<legacy PZF>", [], data))
        p.warnings.append("legacy binary (.pzf / old .pzt): tables are inside the PCFF blob and are not read yet")
        return p
    raise ValueError("not a Prism document")
