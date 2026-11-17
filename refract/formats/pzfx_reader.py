"""Read a .pzfx (or XML .pzt) document into the document model.

Data tables and info sheets are XML. Graphs, analyses and formatting live in
<Template>: base64 of a zlib stream holding the same PCFF binary that bundles
keep in graphs/*/data.bin. It is exposed as Project.graphs[0].blob, unparsed.
Namespaces are optional in real files (prismbinder §6), so elements are
matched by local name. XSLT-wrapped sample files are found by searching for
the GraphPadPrismFile element anywhere in the tree.
"""

from __future__ import annotations

import base64
import re
import xml.etree.ElementTree as ET
import zlib

from ..model.document import DataSet, DataTable, Graph, InfoSheet, Project

YFORMAT = {
    "replicates": "y_replicates", "SD": "y_sd", "SE": "y_se", "CV": "y_cv",
    "SDN": "y_sd_n", "SEN": "y_se_n", "CVN": "y_cv_n", "low-high": "y_high_low",
    "upper-lower-limits": "y_high_low", "text": "text",
}
KIND = {"XY": "xy", "OneWay": "column", "TwoWay": "grouped", "Contingency": "contingency",
        "Survival": "survival", "PartsOfWhole": "parts_of_whole"}
EXT_KIND = {"MultipleVariables": "multivariable", "Nested": "nested"}


_LONE_CR = re.compile(r"\r(?!\n)")


def parse_xml(text: str) -> ET.Element:
    """Parse Prism XML keeping a cell's line break: Prism writes it as a lone
    CR inside the element (and "\r" in bundle CSV), which an XML parser would
    turn into LF."""
    return ET.fromstring(_LONE_CR.sub("&#13;", text))


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _kids(e: ET.Element, name: str) -> list[ET.Element]:
    return [c for c in e if _local(c.tag) == name]


def _kid(e: ET.Element, *names: str) -> ET.Element | None:
    """First child with any of these local names, in preference order.
    (Never `a or b` on Elements: a childless Element is falsy.)"""
    for name in names:
        k = _kids(e, name)
        if k:
            return k[0]
    return None


# Classic Symbol-font letters -> Unicode Greek (titles like TGF<Font Face="Symbol">b</Font>1)
SYMBOL_FONT = dict(zip(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIKLMNOPQRSTUWXYZ",
    "αβχδεφγηιϕκλμνοπθρστυϖωξψζΑΒΧΔΕΦΓΗΙΚΛΜΝΟΠΘΡΣΤΥΩΞΨΖ", strict=True))


def _rich_text(e: ET.Element, symbol: bool = False) -> str:
    """Text of an element, mapping runs in the Symbol font to Unicode."""
    out = []
    if e.text:
        out.append("".join(SYMBOL_FONT.get(ch, ch) for ch in e.text) if symbol else e.text)
    for c in e:
        face = (c.get("Face") or "").lower() if _local(c.tag) == "Font" else ""
        out.append(_rich_text(c, symbol or face == "symbol"))
        if c.tail:
            out.append("".join(SYMBOL_FONT.get(ch, ch) for ch in c.tail) if symbol else c.tail)
    return "".join(out)


def _text(e: ET.Element | None) -> str | None:
    if e is None:
        return None
    return _rich_text(e).replace("\r\n", "\n").strip("\r\n")


def _subcolumns(col: ET.Element) -> tuple[list[list[str]], dict[tuple[int, int], set[str]]]:
    subs, attrs = [], {}
    for si, sc in enumerate(_kids(col, "Subcolumn")):
        cells = []
        for ri, d in enumerate(_kids(sc, "d")):
            cells.append("".join(d.itertext()))
            if d.get("Excluded") == "1":
                attrs.setdefault((si, ri), set()).add("EXCLUDED")
        subs.append(cells)
    return subs, attrs


def _decimals(col: ET.Element | None, kind: str) -> int | None:
    """A column's display decimals (0-15). Multiple-variables columns can
    carry other numbers there (hundreds), and 0 on integer or text columns,
    which Prism leaves to the values."""
    d = col.get("Decimals") if col is not None else None
    if d is None or not d.isdigit() or int(d) > 15 or (kind == "multivariable" and int(d) == 0):
        return None
    return int(d)


MV_TYPE = {"continues": "continuous", "categorical": "categorical", "label": "label"}


def _variable(col: ET.Element, kind: str) -> dict | None:
    """A Multiple variables column's MVType ("Manual|Categorical") and its
    category dictionary (ids in Prism's order)."""
    mv = col.get("MVType")
    if kind != "multivariable" or not mv:
        return None
    parts = [p.lower() for p in mv.split("|")]
    typ = next((MV_TYPE[p] for p in parts if p in MV_TYPE), None)
    if typ is None:
        return None
    out: dict = {"type": typ, "manual": "manual" in parts}
    cd = _kid(col, "CategoryDictionary")
    if cd is not None:
        out["categories"] = [(int(d.get("id", i)), "".join(d.itertext())) for i, d in enumerate(_kids(cd, "d"))]
    return out


def _pad(subs: list[list[str]], n: int) -> list[list[str]]:
    return [s + [""] * (n - len(s)) for s in subs]


def read_table(t: ET.Element) -> DataTable:
    kind = EXT_KIND.get(t.get("ExtTableType", ""), KIND.get(t.get("TableType", ""), t.get("TableType", "")))
    ycols = _kids(t, "YColumn")
    nsub = max((int(y.get("Subcolumns", "1")) for y in ycols), default=1)
    yf = t.get("YFormat")
    if yf:
        data_format = YFORMAT.get(yf, yf)
    else:
        data_format = "y_single" if nsub == 1 else "y_replicates"
    replicates = int(t.get("Replicates", nsub)) if data_format == "y_replicates" else 1
    parts: list[tuple[str, ET.Element]] = []
    rt = _kid(t, "RowTitlesColumn")
    xc = _kid(t, "XColumn", "XAdvancedColumn")
    raw_sets = []
    for y in ycols:
        subs, attrs = _subcolumns(y)
        raw_sets.append((_text(_kid(y, "Title")), subs, attrs, _decimals(y, kind), _variable(y, kind)))
    rt_subs = _subcolumns(rt)[0] if rt is not None else []
    x_subs, x_attrs = _subcolumns(xc) if xc is not None else ([], {})
    n_rows = max([len(s) for _, subs, *_ in raw_sets for s in subs] + [len(s) for s in rt_subs + x_subs] + [0])
    datasets = [DataSet(title, _pad(subs, n_rows), "Y", data_format, cell_attributes=attrs, decimals=dec,
                        variable=var) for title, subs, attrs, dec, var in raw_sets]
    row_titles = DataSet(None, _pad(rt_subs[:1] or [[]], n_rows), "RT", "text") if rt is not None else None
    x = DataSet(_text(_kid(xc, "Title")), _pad(x_subs, n_rows), "X", t.get("XFormat"), cell_attributes=x_attrs,
                decimals=_decimals(xc, kind)) if xc is not None else None
    del parts
    return DataTable(title=_text(_kid(t, "Title")) or "", kind=kind, data_format=data_format, datasets=datasets,
                     n_rows=n_rows, replicates=replicates, row_titles=row_titles, x=x, table_uid=t.get("ID"))


def read_pzfx(path_or_bytes: str | bytes) -> Project:
    if isinstance(path_or_bytes, bytes):
        raw = path_or_bytes
    else:
        with open(path_or_bytes, "rb") as f:
            raw = f.read()
    text = raw.decode("utf-8-sig", errors="replace")
    root = parse_xml(text)
    doc = root if _local(root.tag) == "GraphPadPrismFile" else next(
        (e for e in root.iter() if _local(e.tag) == "GraphPadPrismFile"), root)
    p = Project("pzfx")
    created = _kid(doc, "Created")
    if created is not None:
        mr = _kid(created, "MostRecentVersion", "OriginalVersion")
        if mr is not None:
            p.created_by = {"name": mr.get("CreatedByProgram"), "version": mr.get("CreatedByVersion")}
    by_id = {}
    for e in doc:
        if _local(e.tag) in ("Table", "HugeTable"):
            by_id[e.get("ID")] = e
    seq = _kid(doc, "TableSequence")
    order = [r.get("ID") for r in _kids(seq, "Ref")] if seq is not None else list(by_id)
    for tid in order:
        if tid in by_id:
            p.tables.append(read_table(by_id[tid]))
    for info in _kids(doc, "Info"):
        consts = [(_text(_kid(c, "Name")) or "", _text(_kid(c, "Value")) or "") for c in _kids(info, "Constant")]
        p.infos.append(InfoSheet(_text(_kid(info, "Title")) or "", consts, _text(_kid(info, "Notes")) or "", info.get("ID")))
    tpl = _kid(doc, "Template")
    if tpl is not None and (tpl.text or "").strip():
        try:
            blob = zlib.decompress(base64.b64decode(re.sub(r"\s+", "", tpl.text)))
            p.graphs.append(Graph("<Template>", [], blob))
        except Exception as ex:  # noqa: BLE001 - report, never throw on content
            p.warnings.append(f"Template not decodable: {ex}")
    return p
