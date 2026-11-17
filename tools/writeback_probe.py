"""E-writeback: Refract's graphs written as Prism graphs on save (seed and
patch: refract.formats.graph_transplant, graph_patch), opened and exported
by Prism, compared with Refract's own drawing; the re-saved file reopened
in Refract.

Usage:
  .venv/bin/python tools/writeback_probe.py make <out_dir>        (make-survival, make-pie, make-axes, make-pairs,
      make-styles: E-survival, E-pie, E-axes, E-pairs)
  .venv/bin/python -I tools/prism_auto.py <out_dir>/prism <out_dir>/writeback.prism
  .venv/bin/python tools/writeback_probe.py compare <out_dir>
"""

from __future__ import annotations

import json
import os
import sys

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def make(out: str) -> int:
    from refract.model import templates as T
    from refract.render import qt
    from refract.stats import catalog
    from refract.ui.document import Document

    qt.ensure_app()
    os.makedirs(out, exist_ok=True)
    doc = Document.new()
    col = doc.add_table(T.make("column", "Column default", sample=True))
    grp = doc.add_table(T.make("grouped", "Grouped coloured", sample=True))
    xy = doc.add_table(T.make("xy", "XY log", sample=True))
    bars = doc.add_table(T.make("column", "Column bars", sample=True))
    g = {ng.table.title: ng for ng in doc.project.native_graphs}
    doc.set_native_options(g["Grouped coloured"], format={
        "y": {"min": 0.0, "max": 50.0, "tick": 10.0}, "sets": {"0": {"fill": "#e07a5f"}, "1": {"fill": "#3d85c6"}}})
    doc.set_native_options(g["XY log"], format={"y": {"log": True}, "sets": {"0": {"color": "#d1495b"}}})
    doc.add_analysis(bars, catalog.by_key("one_way"), {"compare": "ALL_VS_ALL", "test": "TUKEY"})
    doc.set_native_options(g["Column bars"], style="bars", error="sem")
    path = os.path.join(out, "writeback.prism")
    doc.save(path)
    info = {ng.table.title: {"refract": ng.uid, "prism": ng.prism_uid} for ng in doc.project.native_graphs}
    with open(os.path.join(out, "cases.json"), "w") as f:
        json.dump({"graphs": info, "report": doc.last_report}, f, indent=1)
    for t in (col, grp, xy, bars):
        print(t.title, "->", info[t.title]["prism"])
    print("report:")
    for r in doc.last_report:
        print("  ", r)
    return 0


def make_survival(out: str) -> int:
    """Survival graphs with 1, 2, 3 and 7 groups (the shipped seed plots 6),
    one formatted, beside a column graph."""
    from refract.model import templates as T
    from refract.render import qt
    from refract.ui.document import Document

    qt.ensure_app()
    os.makedirs(out, exist_ok=True)
    doc = Document.new()
    doc.add_table(T.make("column", "Column default", sample=True))
    made = {}
    for title, n in (("Surv one", 1), ("Surv default", 2), ("Surv three", 3), ("Surv seven", 7),
                     ("Surv formatted", 2)):
        t = doc.add_table(T.make("survival", title, sample=True))
        while len(t.datasets) > n:
            doc.delete_datasets(t, [t.datasets[-1]])
        k = 0
        while len(t.datasets) < n:  # each extra group: six subjects of its own, on new rows
            ds = doc.add_dataset(t, title=f"Group {len(t.datasets) + 1}")
            start = t.n_rows
            subj = [(4 + 3 * k + 9 * j, 0 if j == 5 else 1) for j in range(6)]
            doc.set_cells(t, [(t.x, 0, start + j, str(tm)) for j, (tm, _c) in enumerate(subj)]
                          + [(ds, 0, start + j, str(c)) for j, (_tm, c) in enumerate(subj)])
            k += 1
        made[title] = t
    g = {ng.table.title: ng for ng in doc.project.native_graphs}
    doc.set_native_options(g["Surv formatted"], format={
        "y": {"min": 0.0, "max": 100.0, "tick": 25.0}, "x": {"min": 0.0, "max": 100.0, "tick": 20.0},
        "sets": {"0": {"color": "#d1495b"}}})
    path = os.path.join(out, "writeback.prism")
    doc.save(path)
    info = {ng.table.title: {"refract": ng.uid, "prism": ng.prism_uid, "analysis": ng.prism_analysis}
            for ng in doc.project.native_graphs}
    with open(os.path.join(out, "cases.json"), "w") as f:
        json.dump({"graphs": info, "report": doc.last_report}, f, indent=1)
    for t, c in info.items():
        print(t, "->", c["prism"], c["analysis"] or "")
    print("report:", doc.last_report)
    return 0


def make_pie(out: str) -> int:
    """Pies (E-pie): fewer and more rows than the seed's slices, two data sets
    (Prism's pie plots the first), a blank and a zero value, no row titles;
    beside a column graph."""
    from refract.model import templates as T
    from refract.render import qt
    from refract.ui.document import Document

    qt.ensure_app()
    os.makedirs(out, exist_ok=True)
    doc = Document.new()
    doc.add_table(T.make("column", "Column default", sample=True))
    doc.add_table(T.make("parts_of_whole", "Pie default", sample=True))
    cases = {"Pie three": ([5, 3, 2], True, 1), "Pie fifteen": ([15 - i for i in range(15)], True, 1),
             "Pie two sets": ([4, 3, 2, 1], True, 2), "Pie blanks": (["6", "", "0", "3", "1"], True, 1),
             "Pie no titles": ([3, 2, 2, 1], False, 1)}
    for title, (vals, titles, n_sets) in cases.items():
        t = doc.add_table(T.make("parts_of_whole", title))
        while len(t.datasets) < n_sets:
            doc.add_dataset(t, title=f"Set {len(t.datasets) + 1}")
        cells = [(t.datasets[0], 0, r, str(v)) for r, v in enumerate(vals)]
        if n_sets > 1:
            cells += [(t.datasets[1], 0, r, str(len(vals) - r)) for r in range(len(vals))]
        if titles:
            cells += [(t.row_titles, 0, r, f"Part {chr(65 + r)}") for r in range(len(vals))]
        doc.set_cells(t, cells)
    doc.add_table(T.make("parts_of_whole", "Donut", sample=True))  # E-donut
    doc.set_native_options(doc.project.native_graphs[-1], style="donut")
    path = os.path.join(out, "writeback.prism")
    doc.save(path)
    info = {ng.table.title: {"refract": ng.uid, "prism": ng.prism_uid} for ng in doc.project.native_graphs}
    with open(os.path.join(out, "cases.json"), "w") as f:
        json.dump({"graphs": info, "report": doc.last_report}, f, indent=1)
    for t, c in info.items():
        print(t, "->", c["prism"])
    print("report:", doc.last_report)
    return 0


def make_axes(out: str) -> int:
    """Titles, text sizes, label angle and symbols (E-axes)."""
    from refract.model import templates as T
    from refract.render import qt
    from refract.ui.document import Document

    qt.ensure_app()
    os.makedirs(out, exist_ok=True)
    doc = Document.new()
    for kind, title in (("xy", "XY titled"), ("column", "Column titled"), ("grouped", "Grouped no points"),
                        ("survival", "Survival titled"), ("xy", "XY plain")):
        doc.add_table(T.make(kind, title, sample=True))
    g = {ng.table.title: ng for ng in doc.project.native_graphs}
    doc.set_native_options(g["XY titled"], format={
        "title": "Custom XY", "title_size": 20,
        "x": {"title": "Alpha (min)", "title_size": 16, "label_size": 14},
        "y": {"title": "Signal (a.u.)", "label_size": 9},
        "sets": {"0": {"symbol": "diamond", "size": 9.5}, "1": {"symbol": "triangle", "size": 4.74}}})
    doc.set_native_options(g["Column titled"], format={
        "y": {"title": "Response"}, "x": {"angle": 90, "label_size": 9},
        "sets": {"0": {"symbol": "square"}, "2": {"symbol": "triangle_down", "size": 7.9}}})
    doc.set_native_options(g["Grouped no points"], format={
        "y": {"title": "Value", "title_size": 10}, "sets": {"0": {"points": False}, "1": {"points": False}}})
    doc.set_native_options(g["Survival titled"], format={
        "x": {"title": "Months"}, "y": {"title": "Surviving (%)"}})
    path = os.path.join(out, "writeback.prism")
    doc.save(path)
    info = {ng.table.title: {"refract": ng.uid, "prism": ng.prism_uid, "analysis": ng.prism_analysis}
            for ng in doc.project.native_graphs}
    with open(os.path.join(out, "cases.json"), "w") as f:
        json.dump({"graphs": info, "report": doc.last_report}, f, indent=1)
    print("report:", doc.last_report)
    return 0


def make_pairs(out: str) -> int:
    """Symbol size, minor ticks and a hidden legend (E-pairs)."""
    from refract.model import templates as T
    from refract.render import qt
    from refract.ui.document import Document

    qt.ensure_app()
    os.makedirs(out, exist_ok=True)
    doc = Document.new()
    for kind, title in (("xy", "XY sized"), ("xy", "XY no legend"), ("grouped", "Grouped no legend"),
                        ("column", "Column sized"), ("survival", "Survival minor")):
        doc.add_table(T.make(kind, title, sample=True))
    g = {ng.table.title: ng for ng in doc.project.native_graphs}
    doc.set_native_options(g["XY sized"], format={
        "x": {"minor": 2}, "y": {"minor": 5},
        "sets": {"0": {"size": 12.6}, "1": {"size": 3.2, "symbol": "circle"}}})
    doc.set_native_options(g["XY no legend"], format={"legend": False, "y": {"minor": 0}})
    doc.set_native_options(g["Grouped no legend"], format={"legend": False, "y": {"minor": 4}})
    doc.set_native_options(g["Column sized"], format={"y": {"minor": 4}, "sets": {"1": {"size": 11}}})
    doc.set_native_options(g["Survival minor"], format={"x": {"minor": 2}, "legend": False})
    path = os.path.join(out, "writeback.prism")
    doc.save(path)
    info = {ng.table.title: {"refract": ng.uid, "prism": ng.prism_uid, "analysis": ng.prism_analysis}
            for ng in doc.project.native_graphs}
    with open(os.path.join(out, "cases.json"), "w") as f:
        json.dump({"graphs": info, "report": doc.last_report}, f, indent=1)
    print("report:", doc.last_report)
    return 0


def make_styles(out: str) -> int:
    """Plot styles, SEM error bars, hidden individual values, fonts, axis
    lengths and the legend (E-pairs)."""
    from refract.model import templates as T
    from refract.render import qt
    from refract.ui.document import Document

    qt.ensure_app()
    os.makedirs(out, exist_ok=True)
    doc = Document.new()
    for kind, title in (("column", "Column bars SD"), ("column", "Column bars SEM"), ("column", "Column bars mixed"),
                        ("grouped", "Grouped bars only"), ("grouped", "Grouped SEM"), ("column", "Column means"),
                        ("xy", "XY Times wide"), ("grouped", "Grouped Georgia"), ("grouped", "Grouped means")):
        doc.add_table(T.make(kind, title, sample=True))
    g = {ng.table.title: ng for ng in doc.project.native_graphs}
    doc.set_native_options(g["Column bars SD"], style="bars")
    doc.set_native_options(g["Column bars SEM"], style="bars", error="sem")
    doc.set_native_options(g["Column bars mixed"], style="bars", format={"sets": {"1": {"points": False}}})
    doc.set_native_options(g["Grouped bars only"], format={"sets": {"0": {"points": False}, "1": {"points": False}}})
    doc.set_native_options(g["Grouped SEM"], error="sem")
    doc.set_native_options(g["Column means"], style="means")
    doc.set_native_options(g["Grouped means"], style="means", error="sem")
    doc.set_native_options(g["XY Times wide"], format={"font": "Times New Roman", "width": 4.0, "legend": False})
    doc.set_native_options(g["Grouped Georgia"], format={"font": "Georgia", "height": 2.5,
                                                         "y": {"title": "Counts", "minor": 2}})
    path = os.path.join(out, "writeback.prism")
    doc.save(path)
    info = {ng.table.title: {"refract": ng.uid, "prism": ng.prism_uid, "analysis": ng.prism_analysis}
            for ng in doc.project.native_graphs}
    with open(os.path.join(out, "cases.json"), "w") as f:
        json.dump({"graphs": info, "report": doc.last_report}, f, indent=1)
    print("report:", doc.last_report)
    return 0


def compare(out: str) -> int:
    import pypdfium2 as pdfium
    from image_compare import ssim
    from PIL import Image

    from refract.formats.pcff import fields as F
    from refract.formats.pcff import walker as W
    from refract.formats.zipio import ZipArchive
    from refract.render import native, qt
    from refract.ui.document import Document

    qt.ensure_app()
    with open(os.path.join(out, "cases.json")) as f:
        cases = json.load(f)["graphs"]
    resaved = os.path.join(out, "prism", "writeback", "resaved.prism")
    z = ZipArchive.open(resaved)
    order = json.loads(z.read("document.json"))["sheets"].get("graphs", [])
    doc = Document.open(resaved)
    bad = 0
    for title, c in cases.items():
        ok = c["prism"] in order
        bad += not ok
        if not ok:
            print(f"  DROPPED {title}")
            continue
        i = order.index(c["prism"]) + 1
        ch = W.parse(z.read(f"graphs/{c['prism']}/data.bin"))
        try:
            ys = F.AxisSettings.read(F.axis_settings(ch)[3])
            ym = F.AxisMode.read(F.axis_modes(ch)[1])
            axis = f"Y {'log ' if ys.log10 else ''}{ys.min:g}..{ys.max:g} tick {ys.major_tick:g} " \
                   f"(manual {bool(ym.flags & 0xC)}), "
        except IndexError:  # a pie: no axes; its slices and legend instead
            from refract.formats.pcff import propstore as P
            from refract.render import from_prism

            store = next((x for x in ch if x.tag == P.TAG and x.payload), None)
            fills = from_prism.slice_fills(P.decode_payload(store.payload)[0]) if store else []
            axis = f"slices {len(fills)}, legend {len(from_prism.legend_entries(ch))}, "
        ng = next(g for g in doc.project.native_graphs if g.uid == c["refract"])
        ours = os.path.join(out, f"refract_{i}.png")
        qt.to_png(native.graph(doc.project, ng, doc.results, doc.source_of), ours, dpi=144)
        a = np.asarray(Image.open(ours).convert("L"), float)
        b = np.asarray(pdfium.PdfDocument(os.path.join(out, "prism", "writeback", f"graph_{i}.pdf"))[0]
                       .render(scale=2).to_pil().convert("L"), float)

        def crop(x):
            yy, xx = np.nonzero(x < 245)
            return x[yy.min():yy.max() + 1, xx.min():xx.max() + 1]

        a, b = crop(a), crop(b)
        a = np.asarray(Image.fromarray(a.astype("uint8")).resize((b.shape[1], b.shape[0]), Image.LANCZOS), float)
        gs = json.loads(z.read(f"graphs/{c['prism']}/sheet.json"))
        extra = ""
        if c.get("analysis"):
            a_name = f"analyses/{c['analysis']}/sheet.json"
            views = json.loads(z.read(a_name)).get("resultSheets", []) if z.has(a_name) else None
            extra = f", analysis kept {views is not None} ({len(views or [])} views)"
        print(f"  {title:18s} graph_{i}: {axis}plots {len(gs.get('inputDataSets', []))} "
              f"(sets {len(ng.table.datasets)}){extra}, SSIM Refract vs Prism {ssim(a, b):.3f}")
    copies = doc.prism_copy_uids()
    listed = [g.title for g in doc.project.graphs if g.uid not in copies]
    companions = doc.prism_companion_uids()
    print("reopened in Refract: Refract graphs", len(doc.project.native_graphs), "| Prism copies hidden",
          len(copies), "| other Prism graphs listed", listed, "| analyses hidden", len(companions),
          "| analyses listed", [a.title for a in doc.project.analyses if a.uid not in companions])
    again = doc.save(os.path.join(out, "again.prism"))
    print("saving the re-saved file again rewrites graphs:", [n for n in again if n.startswith("graphs/")])
    return 1 if bad else 0


if __name__ == "__main__":
    if sys.argv[1] == "make":
        raise SystemExit(make(sys.argv[2]))
    if sys.argv[1] == "make-survival":
        raise SystemExit(make_survival(sys.argv[2]))
    if sys.argv[1] == "make-axes":
        raise SystemExit(make_axes(sys.argv[2]))
    if sys.argv[1] == "make-styles":
        raise SystemExit(make_styles(sys.argv[2]))
    if sys.argv[1] == "make-pairs":
        raise SystemExit(make_pairs(sys.argv[2]))
    if sys.argv[1] == "make-pie":
        raise SystemExit(make_pie(sys.argv[2]))
    raise SystemExit(compare(sys.argv[2]))
