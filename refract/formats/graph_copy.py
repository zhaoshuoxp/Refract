"""Duplicate a data table together with its graphs, the way Prism's own
DuplicateFamily does.

The rules were learned by having Prism run `DuplicateFamily` on four documents
(bar/grouped, column, parts-of-whole pie, XY with a curve fit) and diffing the
results. `family_copy_blob` reproduces Prism's copied graph blob byte for byte
on all single-graph families tested (tools/emulate_dupfamily.py,
tests/test_formats_corpus.py); only the instance UUID and name differ, by design.

Allocation (per namespace, from the maximum of the *defining* field over every
graph in the document):
  plot ids (0x8028+0), text ids (0x802b+0), axis-settings ids (0x8025+0) and the
  pie namespaces: sequential from max + 2, in ascending order of the old ids.
  Referencing fields follow their target: axis -> text, obj2a -> axis settings.
  Data-set fields (plotted set, row-title set, slots, legend) follow the data-set
  fenID map of the copied table.
  graph sheet fenID: max + 2.  data sheet fenID: max + 1.
  data-set fenIDs: max + 1, sequential: Y data sets in order, then row titles, then X.
Families spanning several graphs, or including analyses, are not supported yet.
In Prism's own output the second graph of such a family continues at +1.
"""

from __future__ import annotations

import struct

from . import bundle as B
from .bundle_builder import new_token, new_uid
from .pcff import idmap
from .pcff.walker import Chunk, parse, serialize
from .zipio import ZipArchive

DEFINING = {"plot": 0x8028, "text": 0x802B, "axset": 0x8025}
COUNTED = ("slice", "pie", "pie2", "pie3", "pdata")  # namespaces whose maximum comes from their fields
# a heat map's blocks that name its graph by fenID (E-heat: left at the seed's, Prism quit drawing the copy)
HEAT_GRAPH_FEN = (0x80F4, 0x00F8)


def _u16(p: bytes, o: int) -> int:
    return struct.unpack_from("<H", p, o)[0]


def doc_maxima(blobs: list[bytes]) -> dict[str, int]:
    m = {k: -1 for k in (*DEFINING, *COUNTED, "slot14")}
    for b in blobs:
        if b[:8] != b"PCFFGRA4":
            continue
        ch = parse(b)
        ids = idmap.collect_ids(ch)
        for ns in COUNTED:
            if ids.get(ns):
                m[ns] = max(m[ns], max(ids[ns]))
        for c in ch:
            for ns, tag in DEFINING.items():
                if c.tag == tag and c.payload:
                    m[ns] = max(m[ns], _u16(c.payload, 0))
            if c.tag == 0x0014 and c.payload:
                n = struct.unpack_from("<I", c.payload, 0)[0]
                for v in struct.unpack_from(f"<{n}I", c.payload, 4):
                    m["slot14"] = max(m["slot14"], v)
    # a pie's plot names its pie data (0x009C +141 = 0x80D6 +4): counted apart, they parted beside a heat map
    # (whose 0x009C +141 count too) and Prism drew the pie blank (E-heat); Prism's own copies of the older
    # pies number their chart ids ("pie") apart (DuplicateFamily of a parts-of-whole graph)
    m["slice"] = m["pdata"] = max(m["slice"], m["pdata"])
    return m


def family_copy_blob(src_blob: bytes, maxima: dict[str, int], fen_map: dict[int, int], gfen: int,
                     family_size: int = 1) -> list[Chunk]:
    ch = parse(src_blob)
    par = idmap.parents(ch)
    mine = idmap.collect_ids(ch)
    c15 = next((c for c in ch if c.tag == 0x0015), None)  # the plot list (a skeleton may have none)
    n15 = struct.unpack_from("<I", c15.payload, 0)[0] if c15 is not None else 0
    plot_ids = set(mine.get("plot", set())) | set(struct.unpack_from(f"<{n15}I", c15.payload, 4) if n15 else ())
    maps: dict[str, dict[int, int]] = {}
    # a heat map: its plots flagged so (0x009C +15 bit 0x02 with style 1, as from_prism reads it) and no pie
    # plot data (0x80D6); older pies have the heat map's 0x80F4 but not the flag
    heat = any(c.tag == 0x009C and c.payload and len(c.payload) > 133 and c.payload[15] & 0x02 and c.payload[133] == 1
               for c in ch) and not any(c.tag == 0x80D6 for c in ch)
    for ns in ("plot", "text", "axset", *COUNTED):
        vals = plot_ids if ns == "plot" else mine.get(ns, set())
        start = maxima[ns] + 2
        maps[ns] = {v: start + i for i, v in enumerate(sorted(vals))}
    maps["axis"] = maps["text"]
    maps["obj2a"] = maps["axset"]
    maps["dataset"] = dict(fen_map)
    for s, e in idmap.containers(ch, 0x8020) + idmap.containers(ch, 0x80FA):
        kids = [i for i in range(s + 1, e) if ch[i].payload is not None]
        fr = next((i for i in kids if ch[i].tag == idmap.FRAME[0] and len(ch[i].payload) >= idmap.FRAME[1] + 2), None)
        if fr is None:
            continue
        for tag, ns in idmap.FRAMED_PRIORITY:
            if any(ch[i].tag == tag for i in kids):
                old = _u16(ch[fr].payload, idmap.FRAME[1])
                if old in maps[ns]:
                    idmap._set_u16(ch[fr], idmap.FRAME[1], maps[ns][old])
                break
    for c, p in zip(ch, par, strict=True):
        if c.payload is None:
            continue
        for off, ns in list(idmap._fields(c, p)):
            old = _u16(c.payload, off)
            if old < idmap.NULL_FLOOR and old in maps.get(ns, {}):
                idmap._set_u16(c, off, maps[ns][old])
    for c in ch:  # plot containers' +26 counter goes up by one
        if c.tag == 0x8020 and c.payload and len(c.payload) >= 28 and _u16(c.payload, 0) == idmap.OBJ_PLOT:
            idmap._set_u16(c, 26, _u16(c.payload, 26) + 1)
    idmap.mark_copy_slots(ch)
    idmap.set_graph_fen(ch, gfen)
    if heat:  # the heat map's blocks name their graph by fenID too (0x80F4 +8, 0x00F8 +8; E-heat)
        for c in ch:
            if c.tag in HEAT_GRAPH_FEN and c.payload and len(c.payload) >= 10:
                idmap._set_u16(c, 8, gfen)
    idmap.map_survival_datasets(ch, fen_map)
    if not any(c.tag == 0x00F8 for c in ch):  # no pie objects: Prism clears this reference
        for c in ch:
            if c.tag == 0x009E and c.payload and len(c.payload) >= 68:
                p = bytearray(c.payload)
                struct.pack_into("<i", p, 64, -1)
                c.payload = bytes(p)
    if c15 is not None:
        pl = bytearray(c15.payload)
        for k in range(n15):
            v = struct.unpack_from("<I", pl, 4 + 4 * k)[0]
            struct.pack_into("<I", pl, 4 + 4 * k, maps["plot"].get(v, v))
        c15.payload = bytes(pl)
    for c in ch:
        if c.payload is None:
            continue
        if c.tag == 0x000A and len(c.payload) >= 300:
            idmap._set_u16(c, 18, 0x40)
            idmap._set_u16(c, 298, 0x40)
        elif c.tag == 0x0013 and len(c.payload) >= 28:
            idmap._set_u16(c, 26, 0)
        elif c.tag == 0x0014:
            p = bytearray(c.payload)
            k = struct.unpack_from("<I", p, 0)[0]
            for i in range(k):
                struct.pack_into("<I", p, 4 + 4 * i, maxima["slot14"] + family_size + i)
            c.payload = bytes(p)
        elif c.tag == 0x0091:
            p = bytearray(c.payload)
            k = struct.unpack_from("<I", p, 0)[0]
            for i in range(k):
                struct.pack_into("<I", p, 4 + 4 * i, 0)
            c.payload = bytes(p)
    return ch


# --------------------------------------------------------------- bundle level
def _graph_blobs(arc: ZipArchive, doc: dict) -> list[bytes]:
    out = []
    for kind in ("graphs", "layouts"):
        for g in doc["sheets"].get(kind, []):
            n = f"{kind}/{g}/data.bin"
            if arc.has(n):
                out.append(arc.read(n))
    return out


def duplicate_family(arc: ZipArchive, data_sheet_uid: str, prefix: str = "Copy of ",
                     rows: list[list[str]] | None = None) -> tuple[str, list[str]]:
    """Copy a data table and every graph that plots only its data sets.
    `rows` optionally replaces the copied table's CSV cells (same shape), which
    turns the copy into "same graph, new data". Returns (new data sheet uid,
    new graph uids)."""
    doc = B.get_json(arc, "document.json")
    if any(u in doc["sheets"].get("analyses", []) for u in []):
        pass
    sheet = B.get_json(arc, f"data/sheets/{data_sheet_uid}/sheet.json")
    t = sheet["table"]
    role_ids = [("Y", u) for u in t["dataSets"]]
    if t.get("rowTitlesDataSet"):
        role_ids.append(("rowTitlesDataSet", t["rowTitlesDataSet"]))
    if t.get("xDataSet"):
        role_ids.append(("xDataSet", t["xDataSet"]))
    set_names = [n for n in arc.names() if n.startswith("data/sets/") and n.endswith(".json")]
    max_fen = max(B.get_json(arc, n)["fenID"] for n in set_names)
    uid_map: dict[str, str] = {}
    fen_map: dict[int, int] = {}
    for k, (_role, old) in enumerate(role_ids):
        ds = B.get_json(arc, f"data/sets/{old}.json")
        new = new_uid()
        uid_map[old] = new
        fen_map[ds["fenID"]] = max_fen + 1 + k
        ds["uid"] = new
        ds["fenID"] = max_fen + 1 + k
        B.put_json(arc, f"data/sets/{new}.json", ds)
    data_fens = [B.get_json(arc, f"data/sheets/{u}/sheet.json")["fenID"] for u in doc["sheets"]["data"]]
    s2, t2 = new_uid(), new_uid()
    old_table = t["uid"]
    sheet["uid"], sheet["fenID"] = s2, max(data_fens) + 1
    sheet["title"] = prefix + sheet["title"]
    sheet["isCustomTitle"] = True
    t["uid"] = t2
    t["dataSets"] = [uid_map[u] for u in t["dataSets"]]
    for role in ("rowTitlesDataSet", "xDataSet"):
        if t.get(role):
            t[role] = uid_map[t[role]]
    B.put_json(arc, f"data/sheets/{s2}/sheet.json", sheet)
    arc.put(f"data/tables/{t2}/content.json", arc.read(f"data/tables/{old_table}/content.json"))
    if rows is None:
        csv = arc.read(f"data/tables/{old_table}/data.csv")
    else:
        csv = ("\n".join(",".join(r) for r in rows) + "\n").encode("utf-8")
    arc.put(f"data/tables/{t2}/data.csv", csv)
    arc.put(f"data/tables/{t2}/data.dt", new_token().encode())

    src_sets = set(uid_map)
    family = [g for g in doc["sheets"].get("graphs", [])
              if arc.read(f"graphs/{g}/data.bin")[:8] == b"PCFFGRA4"
              and set(B.get_json(arc, f"graphs/{g}/sheet.json").get("inputDataSets", [])) <= src_sets
              and B.get_json(arc, f"graphs/{g}/sheet.json").get("inputDataSets")]
    maxima = doc_maxima(_graph_blobs(arc, doc))
    gfens = [B.get_json(arc, f"graphs/{g}/sheet.json")["fenID"] for g in doc["sheets"].get("graphs", [])]
    new_graphs = []
    for i, g in enumerate(family):
        gs = B.get_json(arc, f"graphs/{g}/sheet.json")
        gfen = max(gfens) + 2 + i
        ch = family_copy_blob(arc.read(f"graphs/{g}/data.bin"), maxima, fen_map, gfen, family_size=len(family))
        g2 = new_uid()
        title = prefix + gs["title"]
        idmap.set_graph_name(ch, title)
        idmap.new_instance_uuid(ch)
        gs.update(uid=g2, fenID=gfen, title=title, isCustomTitle=True,
                  inputDataSets=[uid_map[u] for u in gs["inputDataSets"]])
        B.put_json(arc, f"graphs/{g2}/sheet.json", gs)
        arc.put(f"graphs/{g2}/data.bin", serialize(ch))
        new_graphs.append((g2, title))
        maxima = doc_maxima(_graph_blobs(arc, doc) + [serialize(ch)])
        maxima = {k: v - 1 for k, v in maxima.items()}  # later graphs of one family continue at +1

    def upd(d):
        d["sheets"]["data"].append(s2)
        d["sheetAttributesMap"][s2] = {"title": sheet["title"]}
        for g2, title in new_graphs:
            d["sheets"]["graphs"].append(g2)
            d["sheetAttributesMap"][g2] = {"title": title}
    B.edit_json(arc, "document.json", upd)
    return s2, [g for g, _ in new_graphs]
