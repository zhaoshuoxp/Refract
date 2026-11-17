"""An open document: the project, its source bytes, the undo stack and what
has changed since it was opened or saved (docs/ui-spec.md §2, §4, §5)."""

from __future__ import annotations

import copy
import os

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QUndoCommand, QUndoStack

from ..formats import analysis_writer as AW
from ..formats import bundle_builder as BB
from ..formats import native_graphs as NG
from ..formats import open_document
from ..formats import prism_writer as PW
from ..formats import pzfx_writer as XW
from ..formats.prism_writer import save_project
from ..formats.zipio import ZipArchive
from ..model.document import (
    Analysis,
    DataSet,
    DataTable,
    LayoutItem,
    NativeGraph,
    NativeLayout,
    Project,
    to_number,
)
from ..render import native
from ..stats import catalog
from ..stats import inputs as INP


class Document(QObject):
    """Holds one project. `tableEdited(table)` fires after every change to a
    data table (edits, undo and redo alike); `sheetsChanged` when sheets are
    added or removed; `analysisChanged(analysis)` when an analysis's results
    computed here changed (its data or its parameters were edited)."""

    tableEdited = Signal(object)
    modifiedChanged = Signal(bool)
    sheetsChanged = Signal()
    analysisChanged = Signal(object)
    nativeGraphChanged = Signal(object)  # a Refract graph's options changed
    layoutChanged = Signal(object)  # a Refract layout's page or items changed
    prismGraphChanged = Signal(int)  # the formatting of a graph from the file changed (its index)

    def __init__(self, project: Project, path: str | None = None, source: bytes | None = None):
        super().__init__()
        self.project = project
        self.path = path
        self.source = source
        self.archive = ZipArchive.from_bytes(source) if source and project.source_format == "prism" else None
        self.undo = QUndoStack(self)
        self.undo.cleanChanged.connect(self._clean_changed)
        self.edited: set[int] = set()  # id() of the tables edited since opening (graphs then autoscale)
        self.created: dict[int, tuple[DataTable, list[int] | None]] = {}  # id(analysis) -> its data, for new ones
        self.new_tables: dict[int, DataTable] = {}  # id -> tables created here
        self.tables_written: dict[int, str] = {}  # id(new table) -> its sheet uid in self.source
        self.written: dict[int, str] = {}  # id(new analysis) -> its uid in self.source once saved
        self.written_content: dict[str, dict] = {}  # uid -> parameter content saved under it
        self._results: dict[int, dict] = {}  # id(analysis) -> results computed here
        # Refract graph uid -> its Prism copy in the bundle (removed when the graph goes)
        self.prism_copies = {g.uid: g.prism_uid for g in project.native_graphs if g.prism_uid}
        # Refract graph uid -> the survival analysis written for its Prism copy (removed with it)
        self.prism_companions = {g.uid: g.prism_analysis for g in project.native_graphs if g.prism_analysis}
        self.last_report: list[str] = []  # what the last save could not write for Prism
        # formatting of graphs from the file (level A): overrides by graph uid, what the
        # source holds of them, and each blob as opened (every save patches from it)
        self.prism_formats: dict[str, dict] = {}
        self.prism_formats_written: dict[str, dict] = {}
        self.original_blobs = {g.uid: g.blob for g in project.graphs if g.uid and g.blob}
        # parameter content of the stored analyses as last saved (edits are written back)
        self.saved_params = {a.uid: copy.deepcopy(a.parameters.get("content")) for a in project.analyses if a.uid}
        self.tableEdited.connect(self._recompute_for)
        # ng -> its starting format (the default colour scheme, set by the window); None: none
        self.new_graph_format = None
        # what was taken from Prism on opening (graphs changed or deleted there; refract.render.prism_sync)
        self.sync_report: list[str] = self._sync_from_prism()

    def _clean_changed(self, clean: bool) -> None:
        self.modifiedChanged.emit(not clean)

    @classmethod
    def new(cls) -> Document:
        """An empty project (an info sheet, no tables), not yet saved."""
        b = BB.BundleBuilder()
        b.add_info()
        data = b.build().to_bytes()
        return cls(open_document(data), None, data)

    @classmethod
    def open(cls, path: str) -> Document:
        with open(path, "rb") as f:
            data = f.read()
        return cls(open_document(data), path, data)

    @property
    def name(self) -> str:
        return os.path.basename(self.path) if self.path else "Untitled"

    @property
    def modified(self) -> bool:
        return not self.undo.isClean()

    def can_save(self) -> bool:
        """.prism sources take every edit; .pzfx sources their table edits in
        place (save_pzfx), anything else after Save As .prism (convert)."""
        return self.project.source_format in ("prism", "pzfx") and self.source is not None

    @property
    def is_pzfx(self) -> bool:
        return self.project.source_format == "pzfx"

    def pzfx_blockers(self) -> list[str]:
        """What a .pzfx file cannot hold of this document (it keeps graphs,
        analyses and layouts in a binary part Refract does not write)."""
        out = []
        live = {id(t) for t in self.project.tables}
        if any(k in live for k in self.new_tables):
            out.append("data tables made in Refract")
        if any(id(a) in self.created for a in self.project.analyses):
            out.append("analyses made in Refract")
        if self.project.native_graphs:
            out.append("graphs made in Refract")
        if self.project.native_layouts:
            out.append("layouts made in Refract")
        return out

    def convert_loss(self) -> list[str]:
        """What Save As .prism leaves behind of a .pzfx source: Prism's
        graphs, analyses and layouts live in its binary Template."""
        if not self.is_pzfx:
            return []
        out = []
        if self.project.graphs:
            out.append("Prism's graphs, analyses and layouts of the .pzfx file: they are stored in a binary part "
                       "Refract cannot convert yet")
        if len(self.project.infos) > 1:
            out.append(f"info sheets after the first ({len(self.project.infos) - 1})")
        return out

    def save(self, path: str | None = None) -> list[str]:
        """Write the edits into the original bundle (everything else stays
        byte-identical). Returns the bundle entries that were rewritten. A
        .pzfx source is saved in place to a .pzfx target (table edits only,
        PzfxUnsupported otherwise) and converted for a .prism one."""
        if not self.can_save():
            raise NotImplementedError("saving is supported for .prism and .pzfx files")
        target = path or self.path
        if not target:
            raise ValueError("a new project needs a file name (Save As)")
        if self.is_pzfx:
            if target.lower().endswith(".pzfx"):
                return self._save_pzfx(target)
            self._convert_to_prism()
        out, touched = save_project(self.source, self.project, None)
        out, more = self._write_tables(out)
        touched += more
        out, more = self._write_analyses(out)  # before the graphs: a survival graph may plot one of them
        touched += more
        out, more = self._write_prism_graphs(out)
        touched += more
        out, more = self._write_prism_formats(out)
        touched += more
        self._record_prism_bases(out)
        out, more = self._write_native_graphs(out)
        touched += more
        with open(target, "wb") as f:
            f.write(out)
        self.source, self.path = out, target
        self.archive = ZipArchive.from_bytes(out)
        self.undo.setClean()
        return touched

    def _save_pzfx(self, target: str) -> list[str]:
        blockers = self.pzfx_blockers()
        if blockers:
            raise XW.PzfxUnsupported("a .pzfx file holds edits to its data tables only; "
                                     + ", ".join(blockers) + " need Save As .prism")
        out, touched = XW.save_pzfx(self.source, self.project)
        with open(target, "wb") as f:
            f.write(out)
        self.source, self.path = out, target
        self.last_report = []
        self.undo.setClean()
        return touched

    def _convert_to_prism(self) -> None:
        """Turn this .pzfx document into a .prism one: a new bundle with the
        first info sheet; every data table becomes a new table, inserted by
        the save that follows (cells as typed, excluded values kept)."""
        info = self.project.infos[0] if self.project.infos else None
        b = BB.BundleBuilder(creator_name="Refract")
        if info is not None:
            b.add_info(info.title or "Project info 1", info.constants, info.notes)
        else:
            b.add_info()
        for t in self.project.tables:  # check everything first: a refused save changes nothing
            if t.is_result:
                continue
            if t.data_format != "y_replicates" and t.data_format not in BB.SUBCOLS:
                raise XW.PzfxUnsupported(f"{t.title}: its data format ({t.data_format}) cannot be written to .prism yet")
            xs = t.x.subcolumns[0] if t.x is not None and t.x.subcolumns else []
            if any(c.strip() and to_number(c) is None for c in xs):
                raise XW.PzfxUnsupported(f"{t.title}: X values that are not numbers (e.g. times) cannot be "
                                         "written to .prism yet")
        self.source = b.build().to_bytes()
        self.archive = ZipArchive.from_bytes(self.source)
        self.project.source_format = "prism"
        self.project.graphs = []  # the Template: not carried over (convert_loss)
        for t in self.project.tables:
            if not t.is_result:
                t.table_uid = None
                self.new_tables[id(t)] = t
        self.original_blobs = {}
        self.sheetsChanged.emit()

    def _write_tables(self, out: bytes) -> tuple[bytes, list[str]]:
        """Tables created here: inserted into the bundle (their later edits are
        then saved like any other table's), removed again when undone."""
        live = {id(t) for t in self.project.tables}
        add = [t for k, t in self.new_tables.items() if k in live and k not in self.tables_written]
        drop = [k for k in self.tables_written if k not in live]
        if not (add or drop):
            return out, []
        arc = ZipArchive.from_bytes(out)
        touched: list[str] = []
        for k in drop:
            BB.remove_table(arc, self.tables_written.pop(k))
            PW.forget(self.new_tables[k])
            touched.append("data/")
        for t in add:
            uid = PW.insert_new_table(arc, t)
            self.tables_written[id(t)] = uid
            touched.append(f"data/sheets/{uid}/")
        return arc.to_bytes(), touched + ["document.json"]

    def add_table(self, table: DataTable, with_graph: bool = True, graph_style: str | None = None) -> DataTable:
        """A new data table at the end of the data tables, with its graph (as
        Prism makes one); one undo step. graph_style "" leaves the graph's
        type to be chosen (the window's new tables: Change Graph Type)."""
        names = {t.title for t in self.project.tables}
        base, n = table.title, 2
        while table.title in names:
            table.title, n = f"{base} ({n})", n + 1
        self.new_tables[id(table)] = table
        ng = native.default_for(table) if with_graph else None
        if ng is not None and graph_style is not None:
            ng.style = graph_style
        if ng is not None and self.new_graph_format is not None:
            ng.format = self.new_graph_format(ng) or {}
        self.undo.beginMacro(f"New table: {table.title}")
        self.undo.push(_AddTable(self, table))
        if ng is not None:
            self.undo.push(_AddNative(self, ng))
        self.undo.endMacro()
        return table

    # ------------------------------------------------------ Refract graphs
    def add_native_graph(self, table: DataTable, title: str | None = None,
                         style: str | None = None) -> NativeGraph | None:
        ng = native.default_for(table)
        if ng is None:
            return None
        if style is not None:
            ng.style = style
        if self.new_graph_format is not None:
            ng.format = self.new_graph_format(ng) or {}
        names = {g.title for g in self.project.graphs} | {g.title for g in self.project.native_graphs}
        base = title or table.title
        ng.title, n = base, 2
        while ng.title in names:
            ng.title, n = f"{base} ({n})", n + 1
        self.undo.push(_AddNative(self, ng))
        return ng

    def set_native_options(self, ng: NativeGraph, **options) -> bool:
        before = {k: getattr(ng, k) for k in options}
        if before == options:
            return False
        self.undo.push(_NativeOptions(self, ng, before, dict(options)))
        return True

    def _prism_signature(self, ng: NativeGraph, source: str | None = None) -> str:
        """What the Prism copy is written from; `source`: the analysis whose
        results it plots, when it reuses the table's own (survival)."""
        import json as _json

        t = ng.table
        d = {"title": ng.format.get("title", ng.title), "style": ng.style, "error": ng.error,
             "format": ng.format, "table": t.sheet_uid, "sets": [d.uid for d in t.datasets]}
        if source:
            d["analysis"] = source
        return _json.dumps(d, sort_keys=True)

    def _sync_from_prism(self) -> list[str]:
        """Keep each Refract graph and its Prism graph one graph (refract.
        render.prism_sync): a graph deleted in Prism goes, one changed there
        takes the changes. Returns what was done, in words."""
        from ..render import prism_sync as PSY

        report: list[str] = []
        if not self.project.native_graphs:
            return report
        index = {g.uid: i for i, g in enumerate(self.project.graphs) if g.uid}
        keep = []
        for ng in self.project.native_graphs:
            if not ng.prism_uid:
                keep.append(ng)
                continue
            i = index.get(ng.prism_uid)
            if i is None:  # deleted in Prism
                report.append(f"{ng.title}: deleted in Prism, so deleted here too")
                self.prism_copies.pop(ng.uid, None)
                continue
            keep.append(ng)
            if not ng.prism_base:
                continue
            now = PSY.summary(self.project, i)
            if now is None or now == ng.prism_base:
                continue
            took = PSY.apply(ng, ng.prism_base, now)
            ng.prism_base = now
            ng.prism_sig = self._prism_signature(ng, ng.prism_analysis)  # Prism's graph stays as Prism left it
            if took:
                report.append(f"{ng.title}: changed in Prism; taken here: " + ", ".join(took))
        self.project.native_graphs[:] = keep
        return report

    def _write_mv_graph(self, arc, ng, gtype, exists: bool, report: list[str]) -> str | None:
        """A bubble or scatter graph of a Multiple-variables table written as
        Prism's MV graph (refract.formats.mv_writer); the new sheet's uid."""
        from ..formats import graph_transplant as GT
        from ..formats import mv_writer as MW
        from ..render import graph_types as GTY
        from ..render import qt as Q

        if gtype.key not in ("mv_bubble", "mv_scatter"):
            report.append(f"{ng.title}: graph type \u201c{gtype.label}\u201d is not written as a Prism graph "
                          "(Prism's graphs of a Multiple-variables table are bubble and scatter graphs); Refract keeps it")
            return None
        g = native.graph(self.project, ng, self.results, self.source_of)
        names = [n for n, _ in GTY.variables(ng.table)]
        nums = [i for i, (_, numeric) in enumerate(GTY.variables(ng.table)) if numeric]
        opts = ng.options or {}

        def pick(key, default):
            v = opts.get(key)
            return names.index(v) if v in names else default

        x = pick("x", nums[0] if nums else 0)
        y = pick("y", nums[1] if len(nums) > 1 else x)
        color = pick("color", None) if opts.get("color") else None
        size = pick("size", None) if opts.get("size") and gtype.key == "mv_bubble" else None
        shown = [s for s in g.series if s.xs]
        colors = {s.title: s.fill for s in shown} if color is not None else {}
        single = shown[0].fill if shown else (0, 0, 0, 255)
        left, top, right, bottom = Q.layout(g).plot
        numeric = color is not None and GTY.variables(ng.table)[color][1]
        graph = MW.graph_json(ng.table, ng.format.get("title", ng.title), x, y, color, size, colors, single,
                              Q.resolve_axes(g), (right - left, bottom - top),
                              (GTY.BUBBLE_SMALLEST, GTY.BUBBLE_LARGEST) if size is not None
                              else (shown[0].symbol_size if shown else 6.0, 0.0), numeric)
        if exists:
            GT.remove_graph(arc, ng.prism_uid)
        return MW.add_graph(arc, ng.format.get("title", ng.title), graph)

    def _record_prism_bases(self, out: bytes) -> None:
        """Each Prism copy as just saved, summarised (prism_sync.summary): a
        later difference is a change made in Prism."""
        from ..render import prism_sync as PSY

        copies = [ng for ng in self.project.native_graphs if ng.prism_uid]
        if not copies:
            return
        p = open_document(out)
        index = {g.uid: i for i, g in enumerate(p.graphs) if g.uid}
        for ng in copies:
            i = index.get(ng.prism_uid)
            ng.prism_base = PSY.summary(p, i) if i is not None else None

    def _write_prism_graphs(self, out: bytes) -> tuple[bytes, list[str]]:
        """Refract's graphs written as Prism graphs (seed and patch, PLAN §2.4
        level B), so Prism shows them; rewritten when their options or data
        sets change (data edits Prism redraws by itself). What cannot be
        written is collected in self.last_report."""
        from ..formats import graph_patch as GP
        from ..formats import graph_transplant as GT
        from ..formats import seeds
        from ..formats import survival_writer as SW
        from ..formats.pcff import fonts as FT
        from ..formats.pcff import skeleton as SK
        from ..render import qt as Q

        report = self.last_report = []
        tables = {id(t) for t in self.project.tables}
        live = {g.uid: g for g in self.project.native_graphs if id(g.table) in tables and g.table.sheet_uid}
        lib = seeds.library()
        arc = ZipArchive.from_bytes(out)
        touched: list[str] = []
        for nguid, puid in list(self.prism_copies.items()):
            if nguid in live:
                continue
            if arc.has(f"graphs/{puid}/sheet.json"):
                GT.remove_graph(arc, puid)
                touched.append(f"graphs/{puid}/")
            companion = self.prism_companions.pop(nguid, None)
            if companion and arc.has(f"analyses/{companion}/sheet.json"):
                SW.remove_analysis(arc, companion)
                touched.append(f"analyses/{companion}/")
            del self.prism_copies[nguid]
        companions = set(self.prism_companions.values())
        from ..render import graph_types as GTY

        for ng in live.values():
            gtype = GTY.resolve(ng.table.kind, ng.style)
            pstyle, pnote = GTY.prism_style(gtype)
            if gtype is None:
                report.append(f"{ng.title}: not written as a Prism graph (no graph type chosen yet)")
                continue
            if gtype.family != ng.table.kind:
                pstyle, pnote = "default", f"graph type \u201c{gtype.label}\u201d (Prism shows its default graph)"
            choice = GTY.plot_option(gtype, ng.error)
            # the plot choice itself where Prism has it (centre and error bars, whiskers), else SD / SEM
            perror = choice if choice in GP.PLOT_CHOICES else {"mean_sem": "sem"}.get(choice or "", "sd")
            own = None  # the table's own survival analysis, plotted in place of a companion
            if ng.table.kind == "survival":
                found = SW.find_analysis(arc, ng.table, companions)
                own = found[0] if found else None
            sig = self._prism_signature(ng, own)
            exists = bool(ng.prism_uid) and arc.has(f"graphs/{ng.prism_uid}/sheet.json")
            if exists and ng.prism_sig == sig:
                continue
            if ng.table.kind == "multivariable":  # Prism's MV graphs are JSON, not a PCFF blob (E-mv)
                uid = self._write_mv_graph(arc, ng, gtype, exists, report)
                if uid is not None:
                    ng.prism_uid, ng.prism_sig = uid, sig
                    self.prism_copies[ng.uid] = uid
                    touched.append(f"graphs/{uid}/")
                continue
            seed = lib.get(ng.table.kind)
            built = ng.table.kind in SK.WRITTEN_KINDS and SK.available() and os.environ.get("REFRACT_GRAPHS") != "seed"
            typed = seeds.type_seed(gtype.key) if pstyle == "seed" else \
                seeds.type_seed(GTY.BORROWED[gtype.key][0]) if gtype.key in GTY.BORROWED else None
            side = GTY.BORROWED[gtype.key][1] if typed is not None and gtype.key in GTY.BORROWED else None
            if side is not None:  # a near type's seed, the plot written on it
                pstyle, pnote = "default", None
            heat = GTY.is_heat(gtype)
            if heat and gtype.key != GTY.HEAT_SEED:  # one heat map seed, Prism's default colours (E-heat)
                typed = seeds.type_seed(GTY.HEAT_SEED)
                pstyle = "default"
                pnote = f"heat map colours \u201c{gtype.label}\u201d (Prism draws viridis)" if typed is not None else \
                    f"graph type \u201c{gtype.label}\u201d (Prism shows its default graph: no seed found)"
            if pstyle == "seed":  # written from Prism's own graph of the type (E-types)
                pstyle = "default"
                if typed is None:
                    pnote = f"graph type \u201c{gtype.label}\u201d (Prism shows its default graph: no seed found)"
                elif choice not in GP.PLOT_CODES or gtype.tab == "Box and violin":
                    perror = None  # the seed's own plot choice stays
            if typed is not None:
                seed, built = typed, False
            elif built:  # level C: Refract's own skeleton; Prism builds the rest (E-levelc)
                seed = SK.seed(ng.table.kind, ng.format.get("title", ng.title), len(ng.table.datasets),
                               SK.needs_plots(pstyle, perror, ng.format) or GTY.is_horizontal(gtype))
            if seed is None:
                why = "no seed graph file found (see refract/formats/seeds.py)" if not lib else \
                    f"Refract cannot write graphs of {ng.table.kind} tables for Prism yet"
                report.append(f"{ng.title}: not written as a Prism graph ({why}); Refract keeps it")
                continue
            g = native.graph(self.project, ng, self.results, self.source_of)
            rx, ry = Q.resolve_axes(g)
            notes: list[str] = []

            fmt = ng.format
            if ("width" in fmt) != ("height" in fmt):  # one length set: the other is Prism's default,
                left, top, right, bottom = Q.layout(g).plot  # not the seed's (E-layoutfix)
                fmt = {"width": round((right - left) / 72, 2), "height": round((bottom - top) / 72, 2), **fmt}

            if pnote:
                notes.append(pnote)
            horizontal = GTY.is_horizontal(gtype)
            if pstyle == "stacked_h":  # the parts' bar on its side: its chart kind says so (0x80D6 +20)
                horizontal = False
            elif horizontal and ng.table.kind not in GTY.HORIZONTAL_KINDS and typed is None:  # kept on its side
                horizontal = False
                notes.append(f"graph type \u201c{gtype.label}\u201d (Prism shows it upright)")

            family = "pie" if ng.table.kind == "parts_of_whole" else g.family  # a stacked bar is a pie's kin

            def patch(ch, ng=ng, g=g, rx=rx, ry=ry, notes=notes, seed=seed, built=built, fmt=fmt, pstyle=pstyle,
                      perror=perror, horizontal=horizontal, typed=typed, family=family, side=side, heat=heat):
                if heat:  # its caches sized for the table; Prism computes the cells (E-heat)
                    GP.fit_heat(ch, max((len(sc) for ds in ng.table.datasets for sc in ds.subcolumns), default=0),
                                len(ng.table.datasets))
                elif (built or typed is not None) and g.extent() and family != "pie":  # the seed's caches are its own
                    GP.write_ranges(ch, g.family, g.extent(), rx, ry, horizontal)
                notes += GP.apply(ch, fmt, family, len(seed.y_fens), rx, ry, pstyle, perror,
                                  fonts=lambda name, bold: FT.index(arc, name, bold, touched), measure=Q.note_size)
                GP.set_horizontal(ch, horizontal)
                if side is not None:
                    GP.on_side(ch, side)

            if exists:
                GT.remove_graph(arc, ng.prism_uid)
            if ng.prism_analysis and arc.has(f"analyses/{ng.prism_analysis}/sheet.json"):
                SW.remove_analysis(arc, ng.prism_analysis)
                touched.append(f"analyses/{ng.prism_analysis}/")
            ng.prism_analysis = None
            plotted = ng.table.sheet_uid
            self.prism_companions.pop(ng.uid, None)
            if seed.kind == "survival":  # Prism's survival graph plots a survival analysis's results
                reuse = SW.proportions_of(arc, ng.table, companions) if own else None
                if reuse is not None:  # the table's own analysis (it stays listed)
                    plotted = reuse[1]
                    touched.append(f"analyses/{reuse[0]}/")
                else:
                    ng.prism_analysis, plotted = SW.add_companion(arc, ng.table)
                    self.prism_companions[ng.uid] = ng.prism_analysis
                    companions.add(ng.prism_analysis)  # never taken for another graph's own analysis
                    touched.append(f"analyses/{ng.prism_analysis}/")
            uid = GT.transplant(arc, seed, plotted, ng.format.get("title", ng.title), patch=patch)
            if g.significance:
                notes.append("significance stars (Prism can add them: Analyze ▸ pairwise comparisons on the graph)")
            if exists:
                notes.append("its earlier Prism copy was replaced (changes made to it in Prism are lost)")
            if notes:
                report.append(f"{ng.title}: " + "; ".join(notes))
            ng.prism_uid, ng.prism_sig = uid, sig
            self.prism_copies[ng.uid] = uid
            touched.append(f"graphs/{uid}/")
        return (arc.to_bytes(), touched + ["document.json"]) if touched else (out, [])

    # ------------------------------------- formatting graphs from the file
    def prism_format(self, index: int) -> dict:
        g = self.project.graphs[index]
        return self.prism_formats.get(g.uid, {}) if g.uid else {}

    def set_prism_format(self, index: int, fmt: dict) -> bool:
        g = self.project.graphs[index]
        if not g.uid or self.prism_format(index) == fmt:
            return False
        self.undo.push(_PrismFormat(self, index, copy.deepcopy(self.prism_format(index)), copy.deepcopy(fmt)))
        return True

    def prism_graph(self, index: int):
        """A graph from the file as Refract draws it, with its formatting applied."""
        from ..render import formatting, from_prism

        edited = any(id(t) in self.edited for t in from_prism.source_tables(self.project, index, self.archive))
        g = from_prism.graph(self.project, index, self.archive, use_cached=not edited)
        return formatting.apply(g, self.prism_format(index))

    def _write_prism_formats(self, out: bytes) -> tuple[bytes, list[str]]:
        """Formatting of graphs from the file patched into their own blobs
        (PLAN §2.4 level A), always from the blob as opened, so undoing a
        change and saving restores the original bytes."""
        from ..formats import graph_patch as GP
        from ..formats.pcff import fonts as FT
        from ..formats.pcff.walker import parse, serialize
        from ..render import qt as Q

        uids = set(self.prism_formats) | set(self.prism_formats_written)
        changed = [u for u in uids if self.prism_formats.get(u, {}) != self.prism_formats_written.get(u, {})]
        if not changed:
            return out, []
        arc = ZipArchive.from_bytes(out)
        touched = []
        by_uid = {g.uid: i for i, g in enumerate(self.project.graphs) if g.uid}
        for uid in changed:
            i = by_uid.get(uid)
            name = f"graphs/{uid}/data.bin"
            if i is None or uid not in self.original_blobs or not arc.has(name):
                continue
            fmt = self.prism_formats.get(uid, {})
            blob = self.original_blobs[uid]
            if fmt:
                ch = parse(blob)
                gr = self.prism_graph(i)
                rx, ry = Q.resolve_axes(gr)
                notes = GP.apply(ch, fmt, gr.family, 10 ** 6, rx, ry,
                                 fonts=lambda name, bold: FT.index(arc, name, bold, touched), measure=Q.note_size)
                if notes:
                    self.last_report.append(f"{self.project.graphs[i].title}: " + "; ".join(notes))
                blob = serialize(ch)
            arc.put(name, blob)
            touched.append(name)
            self.prism_formats_written[uid] = copy.deepcopy(fmt)
        return arc.to_bytes(), touched

    def prism_copy_uids(self) -> set[str]:
        """Prism graphs that are copies of Refract's graphs (not listed separately)."""
        return {g.prism_uid for g in self.project.native_graphs if g.prism_uid}

    def prism_companion_uids(self) -> set[str]:
        """Analyses written only for those copies to plot (survival graphs): not listed."""
        return {g.prism_analysis for g in self.project.native_graphs if g.prism_analysis}

    def _write_native_graphs(self, out: bytes) -> tuple[bytes, list[str]]:
        tables = {id(t) for t in self.project.tables}
        graphs = [g for g in self.project.native_graphs if id(g.table) in tables and g.table.sheet_uid]
        arc = ZipArchive.from_bytes(out)
        touched = [NG.ENTRY] if NG.write(arc, graphs) else []
        if NG.write_layouts(arc, self.project.native_layouts):
            touched.append(NG.LAYOUTS)
        return (arc.to_bytes(), touched) if touched else (out, [])

    # ----------------------------------------------------------- layouts
    def graph_refs(self) -> list[tuple[str, str]]:
        """Every graph a layout can place: (reference, title)."""
        copies = self.prism_copy_uids()
        out = [(f"prism:{g.uid}", g.title) for g in self.project.graphs if g.uid and g.uid not in copies]
        return out + [(f"refract:{g.uid}", g.title) for g in self.project.native_graphs]

    def graph_for(self, ref: str):
        """The Graph a layout item refers to, from the current data; None if gone."""

        kind, _, uid = ref.partition(":")
        if kind == "prism":
            i = next((i for i, g in enumerate(self.project.graphs) if g.uid == uid), None)
            if i is None:
                return None
            return self.prism_graph(i)
        ng = next((g for g in self.project.native_graphs if g.uid == uid), None)
        return None if ng is None else native.graph(self.project, ng, self.results, self.source_of)

    def add_layout(self, title: str | None = None, refs: list[str] | None = None, cols: int | None = None,
                   width: float = 612.0, height: float = 792.0, items: list[LayoutItem] | None = None) -> NativeLayout:
        """A new Refract layout with these graphs arranged in a grid (or the
        given items); one undo step."""
        from ..render import page as PG

        names = {x.title for x in self.project.layouts} | {x.title for x in self.project.native_layouts}
        n = 1
        while f"Layout {n}" in names:
            n += 1
        nl = NativeLayout(title or f"Layout {n}", width, height)
        if items is not None:
            nl.items = items
        else:
            nl.items = [LayoutItem(r, *box) for r, box in zip(refs or [], PG.grid(len(refs or []), width, height, cols),
                                                                 strict=True)]
        self.undo.push(_AddLayout(self, nl))
        return nl

    def set_layout(self, nl: NativeLayout, label: str = "Change layout", **changes) -> bool:
        """Replace the layout's page size, title or items (one undo step)."""
        before = {k: copy.deepcopy(getattr(nl, k)) for k in changes}
        if before == changes:
            return False
        self.undo.push(_LayoutChange(self, nl, label, before, copy.deepcopy(changes)))
        return True

    def arrange_layout(self, nl: NativeLayout, cols: int | None = None) -> bool:
        from ..render import page as PG

        boxes = PG.grid(len(nl.items), nl.width, nl.height, cols)
        return self.set_layout(nl, "Arrange graphs",
                               items=[LayoutItem(it.graph, *b) for it, b in zip(nl.items, boxes, strict=True)])

    def copy_prism_layout(self, index: int) -> NativeLayout:
        """A Refract layout with the graphs of a Prism layout where Prism places them."""
        from ..render import prism_layout as PL

        lay = self.project.layouts[index]
        by_fen = {g.fen: g for g in self.project.graphs if g.fen is not None and g.uid}
        items = []
        for obj in PL.placed(lay.blob or b""):
            g = by_fen.get(obj.fen)
            if g is None:
                continue
            x0, y0, x1, y1 = obj.frame
            items.append(LayoutItem(f"prism:{g.uid}", x0, y0, x1 - x0, y1 - y0))
        width = max([612.0] + [it.x + it.w + 36 for it in items])
        height = max([792.0] + [it.y + it.h + 36 for it in items])
        return self.add_layout(f"{lay.title} (Refract)", width=width, height=height, items=items)

    def next_table_title(self) -> str:
        names = {t.title for t in self.project.tables}
        n = 1
        while f"Data {n}" in names:
            n += 1
        return f"Data {n}"

    def _write_analyses(self, out: bytes) -> tuple[bytes, list[str]]:
        """Analyses created here: added to the bundle with their parameters
        (Prism computes their results when it opens the file), updated when
        their parameters changed, removed when they were undone."""
        live = {id(a): a for a in self.project.analyses if id(a) in self.created}
        todo_add = [a for k, a in live.items() if k not in self.written]
        todo_set = [a for k, a in live.items() if k in self.written
                    and self.written_content.get(self.written[k]) != a.parameters["content"]]
        todo_del = [k for k in self.written if k not in live]
        todo_set += [a for a in self.project.analyses if id(a) not in self.created and a.uid in self.saved_params
                     and a.parameters.get("content") != self.saved_params[a.uid]]
        if not (todo_add or todo_set or todo_del):
            return out, []
        arc = ZipArchive.from_bytes(out)
        touched: list[str] = []
        for k in todo_del:
            uid = self.written.pop(k)
            AW.remove_analysis(arc, uid)
            self.written_content.pop(uid, None)
            touched.append(f"analyses/{uid}/")
        for a in todo_set:
            uid = self.written.get(id(a), a.uid)
            AW.set_parameters(arc, uid, copy.deepcopy(a.parameters["content"]))
            if id(a) in self.written:
                self.written_content[uid] = copy.deepcopy(a.parameters["content"])
            else:
                self.saved_params[uid] = copy.deepcopy(a.parameters["content"])
                a.results = {}  # emptied in the file too: Prism recomputes it on open
            touched.append(f"analyses/{uid}/parameters.json")
        for a in todo_add:
            t, objs = self.created[id(a)]
            uids = None if objs is None else [d.uid for d in objs if any(d is x for x in t.datasets)]
            uid = AW.add_analysis(arc, a.analysis_class, copy.deepcopy(a.parameters["content"]), t.sheet_uid,
                                  uids, a.title)
            a.uid = uid
            self.written[id(a)] = uid
            self.written_content[uid] = copy.deepcopy(a.parameters["content"])
            touched.append(f"analyses/{uid}/")
        return arc.to_bytes(), touched + (["document.json"] if todo_add or todo_del else [])

    # ----------------------------------------------------------- analyses
    def is_new(self, a: Analysis) -> bool:
        """Created in this session (its results are computed here)."""
        return id(a) in self.created

    def stored_is_current(self, a: Analysis) -> bool:
        """Prism's stored results still describe the data and parameters."""
        if self.is_new(a) or not a.results.get("content"):
            return False
        src = self.source_of(a)
        if src is not None and id(src[0]) in self.edited:
            return False
        return a.parameters.get("content") == self.saved_params.get(a.uid)

    def source_of(self, a: Analysis) -> tuple[DataTable, list[int] | None] | None:
        """The table an analysis reads and its data sets' current indices (None: all)."""
        if id(a) in self.created:
            t, objs = self.created[id(a)]
            if objs is None:
                return t, None
            return t, [i for o in objs for i, d in enumerate(t.datasets) if d is o]
        return INP.source(self.project, a)

    def results(self, a: Analysis) -> dict:
        """The analysis computed by Refract from the current data (cached until
        its table or parameters change); {"error": message} when it cannot be."""
        r = self._results.get(id(a))
        if r is None:
            src = self.source_of(a)
            try:
                if src is None:
                    raise ValueError("the analysed data table was not found")
                r = INP.run(a.analysis_class, a.parameters.get("content", {}), *src)
            except Exception as e:  # noqa: BLE001 - shown in the results sheet
                r = {"error": f"{type(e).__name__}: {e}" if not isinstance(e, NotImplementedError)
                     else f"not computed by Refract yet ({e})"}
            self._results[id(a)] = r
        return r

    def _recompute_for(self, table: DataTable) -> None:
        for a in self.project.analyses:
            src = self.source_of(a)
            if src is not None and src[0] is table:
                self._results.pop(id(a), None)
                self.analysisChanged.emit(a)

    def add_analysis(self, table: DataTable, choice: catalog.Choice, values: dict,
                     sets: list[int] | None = None) -> Analysis:
        """A new analysis of data sets `sets` (None: all) of table; one undo step."""
        content = catalog.build(choice, values, table, sets)
        cls = choice.analysis_class
        params = {"@class": "AnalysisParameters", "$id": AW.SCHEMA[cls], "version": AW.VERSION.get(cls, "0.0.0"),
                  "content": content}
        idx = list(range(len(table.datasets))) if sets is None else sets
        title = choice.title(table.title, values)
        names = {x.title for x in self.project.analyses}
        base, n = title, 2
        while title in names:
            title, n = f"{base} ({n})", n + 1
        a = Analysis(title, cls, params, {}, [table.sheet_uid] if table.sheet_uid else [],
                     [table.datasets[i].uid for i in idx if table.datasets[i].uid])
        self.created[id(a)] = (table, None if sets is None else [table.datasets[i] for i in sets])
        self.undo.push(_AddAnalysis(self, a))
        return a

    def set_parameters(self, a: Analysis, choice: catalog.Choice, values: dict) -> None:
        src = self.source_of(a)
        table, sets = (src[0], src[1]) if src is not None else (None, None)
        self.undo.push(_SetParameters(self, a, catalog.build(choice, values, table, sets)))

    def _parameters_changed(self, a: Analysis) -> None:
        self._results.pop(id(a), None)
        self.analysisChanged.emit(a)

    # ------------------------------------------------------------ editing
    # Every change is one undo step: the table's cells, cell metadata and row
    # count are captured before and after it (docs/ui-spec.md §4).
    def change(self, table: DataTable, label: str, fn) -> bool:
        before = _state(table)
        fn()
        after = _state(table)
        if _same(before, after):
            return False
        self.undo.push(_Change(self, table, label, before, after))
        return True

    def set_cell(self, table: DataTable, ds: DataSet, sub: int, row: int, text: str) -> None:
        self.set_cells(table, [(ds, sub, row, text)], f"Edit {table.title} row {row + 1}")

    def set_cells(self, table: DataTable, cells: list[tuple[DataSet, int, int, str]], label: str = "Paste") -> bool:
        """Cells [(data set, subcolumn, row, text)], as typed; the table grows to hold them."""

        def fn():
            for ds, sub, row, text in cells:
                col = ds.subcolumns[sub]
                if row >= len(col):
                    col.extend([""] * (row + 1 - len(col)))
                col[row] = text
                if text and row >= table.n_rows:
                    table.n_rows = row + 1

        return self.change(table, label, fn)

    def insert_rows(self, table: DataTable, at: int, n: int = 1) -> bool:
        def fn():
            for ds in _sets(table):
                for col in ds.subcolumns:
                    if at < len(col):
                        col[at:at] = [""] * n
                for name in META:
                    setattr(ds, name, {(s, r + n if r >= at else r): v for (s, r), v in getattr(ds, name).items()})
            if at < table.n_rows:
                table.n_rows += n

        return self.change(table, f"Insert {n} row(s)", fn)

    def delete_rows(self, table: DataTable, rows: set[int]) -> bool:
        gone = sorted(r for r in rows if r < table.n_rows)

        def fn():
            for ds in _sets(table):
                for col in ds.subcolumns:
                    col[:] = [v for r, v in enumerate(col) if r not in rows]
                for name in META:
                    setattr(ds, name, {(s, r - sum(1 for g in gone if g < r)): v
                                       for (s, r), v in getattr(ds, name).items() if r not in rows})
            table.n_rows -= len(gone)

        return self.change(table, f"Delete {len(gone)} row(s)", fn) if gone else False

    def set_excluded(self, table: DataTable, cells: list[tuple[DataSet, int, int]], excluded: bool) -> bool:
        """Exclude (or include again) values: kept in the table, left out of
        analyses and graphs, shown in blue italics; saved as Prism stores them."""

        def fn():
            for ds, sub, row in cells:
                names = ds.cell_attributes.setdefault((sub, row), set())
                if excluded and ds.subcolumns[sub][row:row + 1] not in ([], [""]):
                    names.add("EXCLUDED")
                else:
                    names.discard("EXCLUDED")
                if not names:
                    del ds.cell_attributes[(sub, row)]

        return self.change(table, "Exclude" if excluded else "Include", fn)

    def _restore(self, table: DataTable, state) -> None:
        n_rows, title, datasets, sets = state
        renamed = table.title != title
        table.n_rows, table.title, table.datasets = n_rows, title, list(datasets)
        for ds, ds_title, subs, *meta in sets:
            ds.title = ds_title
            ds.subcolumns = copy.deepcopy(subs)
            for name, v in zip(META, meta, strict=True):
                setattr(ds, name, copy.deepcopy(v))
        self.edited.add(id(table))
        self.tableEdited.emit(table)
        if renamed:
            self.sheetsChanged.emit()

    # ------------------------------------------------- data sets and titles
    def add_dataset(self, table: DataTable, at: int | None = None, title: str | None = None) -> DataSet | None:
        """A new, empty data set (column group) at position `at` (None: last)."""
        if table.kind == "nested":
            return None  # its subcolumn titles are per data set (not handled yet)
        at = len(table.datasets) if at is None else max(0, min(at, len(table.datasets)))
        n = table.subcolumns_per_dataset
        names = {d.title for d in table.datasets}
        if title is None:
            k = len(table.datasets)
            title = f"Data Set-{_letter(k)}"
            while title in names:
                k += 1
                title = f"Data Set-{_letter(k)}"
        ds = DataSet(title, [[""] * table.n_rows for _ in range(n)], format=table.data_format)
        self.change(table, f"Insert data set {title}", lambda: table.datasets.insert(at, ds))
        return ds

    def delete_datasets(self, table: DataTable, sets: list[DataSet]) -> bool:
        """Remove data sets (at least one stays)."""
        if table.kind == "nested":
            return False
        keep = [d for d in table.datasets if not any(d is x for x in sets)]
        if not keep or len(keep) == len(table.datasets):
            return False

        def fn():
            table.datasets[:] = keep

        return self.change(table, f"Delete {len(table.datasets) - len(keep)} data set(s)", fn)

    def rename_dataset(self, table: DataTable, ds: DataSet, title: str) -> bool:
        return self.change(table, f"Rename data set {title}", lambda: setattr(ds, "title", title))

    def rename_table(self, table: DataTable, title: str) -> bool:
        title = title.strip()
        if not title or any(t is not table and t.title == title for t in self.project.tables):
            return False
        return self.change(table, f"Rename table {title}", lambda: setattr(table, "title", title))


META = ("cell_attributes", "cell_alignments", "cell_text_formats")


def _sets(t: DataTable) -> list[DataSet]:
    """The table's data sets holding cells (rows move together in all of them)."""
    return [*([t.row_titles] if t.row_titles else []), *([t.x] if t.x is not None and t.x.generated is None else []),
            *t.datasets]


def _state(t: DataTable):
    """Everything an edit can change: rows, the table title, which data sets
    it has (in order), and each data set's title, cells and cell metadata."""
    return (t.n_rows, t.title, list(t.datasets),
            [(ds, ds.title, copy.deepcopy(ds.subcolumns), *(copy.deepcopy(getattr(ds, m)) for m in META))
             for ds in _sets(t)])


def _same(a, b) -> bool:
    return (a[0] == b[0] and a[1] == b[1] and [id(d) for d in a[2]] == [id(d) for d in b[2]]
            and len(a[3]) == len(b[3])
            and all(x[0] is y[0] and x[1:] == y[1:] for x, y in zip(a[3], b[3], strict=True)))


def _drop(items: list, obj) -> None:
    """Remove obj itself (list.remove would compare dataclasses by value)."""
    for i, x in enumerate(items):
        if x is obj:
            del items[i]
            return


def _letter(i: int) -> str:
    s, i = "", i + 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


class _PrismFormat(QUndoCommand):
    def __init__(self, doc: Document, index: int, before: dict, after: dict):
        super().__init__(f"Format graph: {doc.project.graphs[index].title}")
        self.doc, self.index, self.before, self.after = doc, index, before, after

    def _apply(self, fmt: dict) -> None:
        uid = self.doc.project.graphs[self.index].uid
        if fmt:
            self.doc.prism_formats[uid] = copy.deepcopy(fmt)
        else:
            self.doc.prism_formats.pop(uid, None)
        self.doc.prismGraphChanged.emit(self.index)

    def redo(self) -> None:
        self._apply(self.after)

    def undo(self) -> None:
        self._apply(self.before)


class _AddLayout(QUndoCommand):
    def __init__(self, doc: Document, nl: NativeLayout):
        super().__init__(f"New layout: {nl.title}")
        self.doc, self.nl = doc, nl

    def redo(self) -> None:
        self.doc.project.native_layouts.append(self.nl)
        self.doc.sheetsChanged.emit()

    def undo(self) -> None:
        _drop(self.doc.project.native_layouts, self.nl)
        self.doc.sheetsChanged.emit()


class _LayoutChange(QUndoCommand):
    def __init__(self, doc: Document, nl: NativeLayout, label: str, before: dict, after: dict):
        super().__init__(label)
        self.doc, self.nl, self.before, self.after = doc, nl, before, after

    def _apply(self, values: dict) -> None:
        for k, v in values.items():
            setattr(self.nl, k, copy.deepcopy(v))
        self.doc.layoutChanged.emit(self.nl)
        if "title" in values:
            self.doc.sheetsChanged.emit()

    def redo(self) -> None:
        self._apply(self.after)

    def undo(self) -> None:
        self._apply(self.before)


class _AddNative(QUndoCommand):
    def __init__(self, doc: Document, ng: NativeGraph):
        super().__init__(f"New graph: {ng.title}")
        self.doc, self.ng = doc, ng

    def redo(self) -> None:
        self.doc.project.native_graphs.append(self.ng)
        self.doc.sheetsChanged.emit()

    def undo(self) -> None:
        _drop(self.doc.project.native_graphs, self.ng)
        self.doc.sheetsChanged.emit()


class _NativeOptions(QUndoCommand):
    def __init__(self, doc: Document, ng: NativeGraph, before: dict, after: dict):
        super().__init__(f"Format graph: {ng.title}")
        self.doc, self.ng, self.before, self.after = doc, ng, before, after

    def _apply(self, values: dict) -> None:
        for k, v in values.items():
            setattr(self.ng, k, v)
        self.doc.nativeGraphChanged.emit(self.ng)

    def redo(self) -> None:
        self._apply(self.after)

    def undo(self) -> None:
        self._apply(self.before)


class _AddTable(QUndoCommand):
    def __init__(self, doc: Document, t: DataTable):
        super().__init__(f"New table: {t.title}")
        self.doc, self.t = doc, t

    def redo(self) -> None:
        tables = self.doc.project.tables
        last = max((i for i, x in enumerate(tables) if not x.is_result), default=-1)
        tables.insert(last + 1, self.t)  # after the other data tables (result tables stay last)
        self.doc.sheetsChanged.emit()

    def undo(self) -> None:
        _drop(self.doc.project.tables, self.t)
        self.doc.sheetsChanged.emit()


class _AddAnalysis(QUndoCommand):
    def __init__(self, doc: Document, a: Analysis):
        super().__init__(f"Analyze: {a.title}")
        self.doc, self.a = doc, a

    def redo(self) -> None:
        self.doc.project.analyses.append(self.a)
        self.doc.sheetsChanged.emit()

    def undo(self) -> None:
        _drop(self.doc.project.analyses, self.a)
        self.doc.sheetsChanged.emit()


class _SetParameters(QUndoCommand):
    def __init__(self, doc: Document, a: Analysis, content: dict):
        super().__init__(f"Change parameters: {a.title}")
        self.doc, self.a = doc, a
        self.before, self.after = copy.deepcopy(a.parameters["content"]), content

    def redo(self) -> None:
        self.a.parameters["content"] = copy.deepcopy(self.after)
        self.doc._parameters_changed(self.a)

    def undo(self) -> None:
        self.a.parameters["content"] = copy.deepcopy(self.before)
        self.doc._parameters_changed(self.a)


class _Change(QUndoCommand):
    def __init__(self, doc: Document, table: DataTable, label: str, before, after):
        super().__init__(label)
        self.doc, self.table, self.before, self.after = doc, table, before, after

    def redo(self) -> None:  # also the first push: the change is already made, this re-emits it
        self.doc._restore(self.table, self.after)

    def undo(self) -> None:
        self.doc._restore(self.table, self.before)
