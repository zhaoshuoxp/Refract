"""Write table edits back into a .pzfx (XML) document, in place.

Only the <Table> elements whose content changed are rewritten; every other
byte of the file stays as it was, including <Template> (Prism's graphs,
analyses and layouts, as compressed binary) and the info sheets. Inside a
rewritten table the parts that did not change are copied verbatim: the
table's start tag, a title whose text is unchanged (it can hold font
markup), floating notes, each column's start tag and unchanged cells.

The XML layout follows what Prism writes (one element per line, the file's
own line ending): `<d>` per cell, `<d/>` for an empty one, `Excluded="1"` on
excluded values, trailing empty cells left out (reader pads them back).

What it cannot write is refused with PzfxUnsupported, so nothing is lost
silently: tables made in Refract (a .pzfx keeps its sheets' links in the
binary Template), tables that are gone, and edits to Multiple-variables
columns whose cells carry Prism's type and category bookkeeping
(CellType, CategoryDictionary).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from xml.sax.saxutils import escape

from ..model.document import DataSet, DataTable, Project
from .pzfx_reader import _local, parse_xml, read_table


class PzfxUnsupported(ValueError):
    """An edit a .pzfx file cannot hold (save as .prism instead)."""


_TAG = re.compile(rb"<(/?)([A-Za-z_][\w.:-]*)([^>]*?)(/?)>|<!--.*?-->|<\?.*?\?>", re.DOTALL)


@dataclass
class _Node:
    name: str
    start: int  # offset of "<"
    end: int  # offset after the closing ">"
    tag_end: int  # offset after the start tag's ">"


def _children(buf: bytes, start: int, end: int) -> list[_Node]:
    """The elements directly inside buf[start:end] (the content of one element)."""
    out: list[_Node] = []
    depth, cur = 0, None
    for m in _TAG.finditer(buf, start, end):
        if m.group(2) is None:  # comment or processing instruction
            continue
        closing, name, selfclose = m.group(1) == b"/", m.group(2).decode(), m.group(4) == b"/"
        if closing:
            depth -= 1
            if depth == 0 and cur is not None:
                cur.end = m.end()
                out.append(cur)
                cur = None
            continue
        if depth == 0:
            cur = _Node(_local(name), m.start(), m.end(), m.end())
            if selfclose:
                out.append(cur)
                cur = None
                continue
        if not selfclose:
            depth += 1
    return out


def _tables(buf: bytes) -> dict[str, tuple[int, int]]:
    """Table ID -> (start, end) byte span of its element."""
    out = {}
    for m in re.finditer(rb"<(Table|HugeTable)\b[^>]*\bID=\"([^\"]*)\"[^>]*>.*?</\1>", buf, re.DOTALL):
        out[m.group(2).decode()] = (m.start(), m.end())
    return out


def _cells_equal(a: DataSet | None, b: DataSet | None, n_rows: int) -> bool:
    if (a is None) != (b is None):
        return False
    if a is None:
        return True
    if (a.title or None) != (b.title or None) or len(a.subcolumns) != len(b.subcolumns):
        return False
    for sa, sb in zip(a.subcolumns, b.subcolumns, strict=True):
        pa, pb = sa + [""] * (n_rows - len(sa)), sb + [""] * (n_rows - len(sb))
        if pa[:n_rows] != pb[:n_rows] or any(c for c in pa[n_rows:] + pb[n_rows:]):
            return False
    ex = lambda d: {k for k, v in d.cell_attributes.items() if "EXCLUDED" in v}
    return ex(a) == ex(b)


def table_changed(orig: DataTable, t: DataTable) -> bool:
    if orig.title != t.title or len(orig.datasets) != len(t.datasets):
        return True
    n = max(orig.n_rows, t.n_rows)
    pairs = [(orig.row_titles, t.row_titles), (orig.x, t.x), *zip(orig.datasets, t.datasets, strict=True)]
    return not all(_cells_equal(a, b, n) for a, b in pairs)


class _Writer:
    def __init__(self, buf: bytes, nl: bytes):
        self.buf, self.nl = buf, nl

    def raw(self, node: _Node) -> bytes:
        return self.buf[node.start:node.end]

    def title(self, node: _Node | None, old: str | None, new: str | None) -> bytes:
        if node is not None and (old or None) == (new or None):
            return self.raw(node)
        return b"<Title>" + escape(new or "").encode() + b"</Title>"

    def start_tag(self, node: _Node | None, default: bytes, subcolumns: int | None) -> bytes:
        tag = self.buf[node.start:node.tag_end] if node is not None else default
        if tag.endswith(b"/>"):
            tag = tag[:-2].rstrip() + b">"
        if subcolumns is not None:
            if re.search(rb'\bSubcolumns="\d+"', tag):
                tag = re.sub(rb'\bSubcolumns="\d+"', b'Subcolumns="%d"' % subcolumns, tag)
            else:
                tag = tag[:-1] + b' Subcolumns="%d">' % subcolumns
        return tag

    def column(self, node: _Node | None, default_tag: bytes, old: DataSet | None, new: DataSet,
               subcolumns_attr: bool, titled: bool) -> bytes:
        """One column element (RowTitlesColumn, XColumn, YColumn ...)."""
        kids = _children(self.buf, node.tag_end, node.end) if node is not None else []
        name = (node.name if node is not None else re.match(rb"<(\w+)", default_tag).group(1).decode()).encode()
        parts = [self.start_tag(node, default_tag, len(new.subcolumns) if subcolumns_attr else None)]
        title_node = next((k for k in kids if k.name == "Title"), None)
        if titled or title_node is not None:
            parts.append(self.title(title_node, old.title if old else None, new.title))
        subs = [k for k in kids if k.name == "Subcolumn"]
        parts += [self.raw(k) for k in kids if k.name not in ("Title", "Subcolumn")]  # e.g. CategoryDictionary
        empty_style = next((self.raw(k) for k in subs if k.end == k.tag_end), b"<Subcolumn></Subcolumn>")
        for si, cells in enumerate(new.subcolumns):
            sub = subs[si] if si < len(subs) else None
            olds = _children(self.buf, sub.tag_end, sub.end) if sub is not None and sub.end != sub.tag_end else []
            last = max((r for r, c in enumerate(cells) if c != "" or new.is_excluded(si, r)), default=-1)
            if last < 0:
                parts.append(empty_style if sub is None or sub.end != sub.tag_end else self.raw(sub))
                continue
            lines = [b"<Subcolumn>"]
            for r in range(last + 1):
                text, excl = cells[r] if r < len(cells) else "", new.is_excluded(si, r)
                o = olds[r] if r < len(olds) else None
                if (o is not None and old is not None and si < len(old.subcolumns) and r < len(old.subcolumns[si])
                        and old.subcolumns[si][r] == text and old.is_excluded(si, r) == excl):
                    lines.append(self.raw(o))
                    continue
                if o is not None and b"CellType=" in self.buf[o.start:o.tag_end]:
                    raise PzfxUnsupported("a typed (Multiple variables) cell was edited")
                if not text and not excl:
                    lines.append(b"<d/>")
                else:
                    lines.append((b'<d Excluded="1">' if excl else b"<d>") + escape(text).encode() + b"</d>")
            lines.append(b"</Subcolumn>")
            parts.append(self.nl.join(lines))
        parts.append(b"</" + name + b">")
        return self.nl.join(parts)


def _is_typed(buf: bytes, node: _Node) -> bool:
    head = buf[node.start:node.tag_end]
    return b"MVType=" in head or b"<CategoryDictionary" in buf[node.start:node.end]


def write_table(buf: bytes, span: tuple[int, int], t: DataTable, nl: bytes) -> bytes:
    """The new bytes of one <Table> element holding table t."""
    start, end = span
    elem = parse_xml(buf[start:end].decode("utf-8"))
    orig = read_table(elem)
    w = _Writer(buf, nl)
    head = re.match(rb"<[^>]*>", buf[start:end]).end() + start
    kids = _children(buf, head, end)
    by = {}
    for k in kids:
        by.setdefault(k.name, []).append(k)
    ycols = by.get("YColumn", [])
    rt = (by.get("RowTitlesColumn") or [None])[0]
    xc = (by.get("XColumn") or by.get("XAdvancedColumn") or [None])[0]
    if orig.kind == "multivariable":
        for i, (a, b) in enumerate(zip(orig.datasets, t.datasets, strict=False)):
            if i < len(ycols) and _is_typed(buf, ycols[i]) and not _cells_equal(a, b, max(orig.n_rows, t.n_rows)):
                raise PzfxUnsupported(f"{t.title}: a Multiple variables column with typed or category cells was edited")
    cols = ("RowTitlesColumn", "XColumn", "XAdvancedColumn", "YColumn")
    default_y = buf[ycols[-1].start:ycols[-1].tag_end] if ycols else b'<YColumn Width="81" Decimals="0" Subcolumns="1">'

    def y(i: int) -> bytes:
        node = ycols[i] if i < len(ycols) else None
        if node is None and orig.kind == "multivariable" and b"MVType=" in default_y:
            raise PzfxUnsupported(f"{t.title}: a new Multiple variables column")
        old = orig.datasets[i] if i < len(orig.datasets) else None
        return w.column(node, default_y, old, t.datasets[i], subcolumns_attr=True, titled=True)

    def rows() -> bytes:
        return w.column(rt, b'<RowTitlesColumn Width="81">', orig.row_titles, t.row_titles,
                        subcolumns_attr=False, titled=False)

    # the children in their own order, columns replaced by the model's; data
    # sets beyond the file's go after its last one, new row titles first
    out = [buf[start:head]]
    if not any(k.name == "Title" for k in kids):
        out.append(w.title(None, None, t.title))
    first_col = next((i for i, k in enumerate(kids) if k.name in cols), len(kids))
    last_y = max((i for i, k in enumerate(kids) if k.name == "YColumn"), default=len(kids) - 1)
    yi = 0
    for i, k in enumerate(kids):
        if i == first_col and rt is None and t.row_titles is not None:
            out.append(rows())
        if k.name == "Title":
            out.append(w.title(k, orig.title, t.title))
        elif k.name == "RowTitlesColumn":
            if t.row_titles is not None:
                out.append(rows())
        elif k.name in ("XColumn", "XAdvancedColumn"):
            if t.x is not None:
                out.append(w.column(k, b"", orig.x, t.x, subcolumns_attr=b"Subcolumns=" in buf[k.start:k.tag_end],
                                    titled=True))
        elif k.name == "YColumn":
            if yi < len(t.datasets):
                out.append(y(yi))
            yi += 1
        else:  # floating notes and anything not modelled stay as they are
            out.append(w.raw(k))
        if i == last_y:
            while yi < len(t.datasets):
                out.append(y(yi))
                yi += 1
    if t.x is not None and xc is None:
        raise PzfxUnsupported(f"{t.title}: an X column the file does not have")
    if first_col == len(kids) and rt is None and t.row_titles is not None:
        out.append(rows())
    while yi < len(t.datasets):
        out.append(y(yi))
        yi += 1
    out.append(b"</" + re.match(rb"<(\w+)", buf[start:end]).group(1) + b">")
    return nl.join(out)


def save_pzfx(src: bytes, project: Project, out_path: str | None = None) -> tuple[bytes, list[str]]:
    """Apply the project's table edits onto the source .pzfx bytes. Returns the
    new bytes and the IDs of the rewritten tables."""
    spans = _tables(src)
    nl = b"\r\n" if b"\r\n" in src[:4096] else b"\n"
    live = {t.table_uid for t in project.tables if not t.is_result}
    for t in project.tables:
        if not t.is_result and t.table_uid not in spans:
            raise PzfxUnsupported(f"{t.title}: a table made in Refract")
    gone = [tid for tid in spans if tid not in live]
    if gone:
        raise PzfxUnsupported(f"tables removed: {', '.join(gone)}")
    edits = []
    for t in project.tables:
        if t.is_result:
            continue
        s, e = spans[t.table_uid]
        orig = read_table(parse_xml(src[s:e].decode("utf-8")))
        if table_changed(orig, t):
            edits.append((s, e, write_table(src, (s, e), t, nl), t.table_uid))
    out = src
    for s, e, new, _ in sorted(edits, reverse=True):
        out = out[:s] + new + out[e:]
    if out_path:
        with open(out_path, "wb") as f:
            f.write(out)
    return out, [tid for *_, tid in sorted(edits)]
