"""Main window: navigator, sheet area, toolbar and menus (docs/ui-spec.md §1, §2, §7)."""

from __future__ import annotations

import os

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QAction, QFont, QGuiApplication, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QMainWindow,
    QMenu,
    QMessageBox,
    QSplitter,
    QStackedWidget,
    QTreeWidget,
    QTreeWidgetItem,
)

from ..formats.pzfx_writer import PzfxUnsupported
from ..stats import catalog
from . import look
from .analyze import AnalyzeDialog, ParametersDialog
from .document import Document
from .layout_view import NativeLayoutView, PrismLayoutView
from .new_table import NewTableDialog
from .ribbon import Ribbon
from .views import GraphView, InfoView, Message, NativeGraphView, ResultView, TableSheet

SECTIONS = [("tables", "Data Tables"), ("infos", "Info"), ("results", "Results"), ("graphs", "Graphs"),
            ("layouts", "Layouts")]
APP_NAME = "Refract"
OPEN_FILTER = "Graph and statistics files (*.prism *.pzfx);;All files (*)"
PRISM_FILTER = "Prism project (*.prism)"
PZFX_FILTER = "Prism XML project (*.pzfx)"
ROLE = Qt.UserRole
NEW_ITEMS = {"Data Tables": "New Data Table…", "Results": "New Analysis…", "Graphs": "New Graph…",
             "Layouts": "New Layout…"}
ICON_OF = {"tables": "tables", "infos": "infos", "results": "results", "graphs": "graphs", "ngraphs": "graphs",
           "layouts": "layouts", "nlayouts": "layouts"}


class MainWindow(QMainWindow):
    def __init__(self, doc: Document | None = None):
        super().__init__()
        self.doc: Document | None = None
        self.views: dict[tuple[str, int], object] = {}
        self.stale: set[int] = set()  # graph indices to rebuild before showing
        self.by_family = look.setting("navigator/families", False)  # group the navigator by data table
        self._select_after = None  # navigator entry to show after the sheets change
        self._last_item = None  # the last sheet shown from the navigator
        self.new_graph_style = ""  # new tables' graphs wait for their type ("default": Prism's; tests, scripts)

        self.nav = QTreeWidget()
        self.nav.setObjectName("navigator")
        self.nav.setHeaderHidden(True)
        self.nav.setMinimumWidth(190)
        self.nav.setIndentation(14)
        self.nav.setIconSize(QSize(18, 18))
        self.nav.currentItemChanged.connect(self._show_item)
        self.nav.itemClicked.connect(self._nav_clicked)
        self.stack = QStackedWidget()
        split = QSplitter()
        split.addWidget(self.nav)
        split.addWidget(self.stack)
        split.setStretchFactor(1, 1)
        split.setSizes([220, 900])
        self.setCentralWidget(split)
        self._actions()
        self.a_families.setChecked(self.by_family)
        self.apply_theme()
        QGuiApplication.styleHints().colorSchemeChanged.connect(self.apply_theme)
        self.resize(1200, 780)
        self.set_document(doc)

    # ------------------------------------------------------------- actions
    def apply_theme(self, *_args) -> None:
        """Style sheet, icons and drawn colours from the current light or dark
        palette; called again whenever the system colour scheme changes."""
        self.setStyleSheet(look.style())
        app = QApplication.instance()
        if app is not None:  # the icon of the theme (the Dock's own follows the system: the asset catalog)
            app.setWindowIcon(look.app_icon())
        for a in self.findChildren(QAction):
            kind = a.property("icon_kind")
            if kind:
                a.setIcon(look.icon(kind))
        for i in range(self.nav.topLevelItemCount()):
            sec = self.nav.topLevelItem(i)
            sec.setForeground(0, look.color("muted"))
            for k in range(sec.childCount()):
                ref = sec.child(k).data(0, ROLE)
                if ref:
                    sec.child(k).setIcon(0, look.icon(ICON_OF[ref[0]]))
        for k in range(self.stack.count()):
            w = self.stack.widget(k)
            if isinstance(w, look.StartPage):
                w.refresh()
            w.update()
            if hasattr(w, "viewport"):
                w.viewport().update()

    def _action(self, text, slot, keys=None, icon=None) -> QAction:
        a = QAction(text, self)
        if icon:
            a.setIcon(look.icon(icon))
            a.setProperty("icon_kind", icon)
        if isinstance(keys, list):
            a.setShortcuts([QKeySequence(k) for k in keys])
        elif keys:
            a.setShortcut(QKeySequence(keys))
        a.triggered.connect(slot)
        return a

    def _actions(self) -> None:
        self.a_new = self._action("New Project…", self.new_project_dialog, QKeySequence.New, "new_project")
        self.a_new_table = self._action("New Data Table…", self.new_table_dialog, "Ctrl+T", "new_table")
        self.a_new_table.setIconText("New Table")
        self.a_open = self._action("Open…", self.open_dialog, QKeySequence.Open, "open")
        self.a_save = self._action("Save", self.save, QKeySequence.Save, "save")
        self.a_save_as = self._action("Save As…", self.save_as_dialog, QKeySequence.SaveAs, "save_as")
        self.a_close = self._action("Close", self.close_document, QKeySequence.Close)
        self.a_report = self._action("Prism Compatibility Report…", self.show_report)
        self.a_export = self._action("Export Graph…", self.export_dialog, "Ctrl+E", "export")
        self.a_undo = self._action("Undo", self.undo, QKeySequence.Undo, "undo")
        self.a_redo = self._action("Redo", self.redo, ["Ctrl+Shift+Z", "Ctrl+Y"],
                                   "redo")
        self.a_analyze = self._action("Analyze…", self.analyze_dialog, "Ctrl+Shift+A", "analyze")
        self.a_params = self._action("Change Parameters…", self.change_shown_parameters, "Ctrl+Shift+P", "params")
        self.a_rename_table = self._action("Rename Table…", self.rename_table_dialog)
        self.a_new_graph = self._action("New Graph of This Table", self.new_graph, "Ctrl+G", "new_graph")
        self.a_format_graph = self._action("Format Graph…", self.format_graph_dialog, "Ctrl+Shift+G", "format_graph")
        self.a_format_axes = self._action("Format Axes…", self.format_axes_dialog, "Ctrl+Shift+X", "format_axes")
        self.a_new_layout = self._action("New Layout", self.new_layout, "Ctrl+L", "new_layout")
        self.a_magic = self._action("Magic: Match Another Graph…", self.magic_dialog, "Ctrl+Shift+M", "magic")
        self.a_graph_type = self._action("Change Graph Type…", self.graph_type_dialog, "Ctrl+Shift+T", "graph_type")
        self.a_template = self._action("Save Style as Template…", self.save_style_template)
        self.a_colors = self._action("Color Scheme", lambda: None, None, "colors")
        self.colors_menu = QMenu("Color Scheme", self)
        self.colors_menu.aboutToShow.connect(self._fill_colors_menu)
        self.a_colors.setMenu(self.colors_menu)
        self.a_add_text = self._action("Add Text", self.add_text, None, "text_box")
        self.a_tools = {}  # drawing tools: drag on the graph to draw (Escape or a second click: select again)
        from ..render.shape_kinds import KINDS, LABELLED
        from . import color_menu

        tools = [(k, lab) for k, (_g, lab) in KINDS.items()] + [(f"{k}:text", f"{KINDS[k][1]} with text")
                                                                for k in LABELLED]
        for kind, label in tools:
            a = self._action(label, lambda _c=False, k=kind: self._choose_tool(k))
            base, _, lab = kind.partition(":")
            a.setIcon(color_menu.shape_icon(base, bool(lab)))
            a.setIconText(label)
            a.setCheckable(True)
            self.a_tools[kind] = a
        self.a_tools["bracket:text"].setText("Add Significance Bracket (Bracket with Text)")
        self.a_tools["bracket:text"].setIconText("Significance bracket")
        self.a_cut = self._action("Cut", lambda: self._clipboard("cut"), QKeySequence.Cut, "cut")
        self.a_copy = self._action("Copy", lambda: self._clipboard("copy"), QKeySequence.Copy, "copy")
        self.a_paste = self._action("Paste", lambda: self._clipboard("paste"), QKeySequence.Paste, "paste")
        for a in (self.a_cut, self.a_copy, self.a_paste):
            a.setShortcutContext(Qt.WidgetShortcut)  # the grid's own shortcuts stay in charge
        self.a_copy_graph = self._action("Copy Graph", self.copy_graph, None, "copy_graph")
        self.a_print = self._action("Print…", self.print_sheet, QKeySequence.Print, "print")
        self.a_bold = self._action("Bold", lambda: self._text_style(bold=self.a_bold.isChecked()), "Ctrl+B", "bold")
        self.a_italic = self._action("Italic", lambda: self._text_style(italic=self.a_italic.isChecked()), "Ctrl+I",
                                     "italic")
        self.a_underline = self._action("Underline", lambda: self._text_style(underline=self.a_underline.isChecked()),
                                        "Ctrl+U", "underline")
        for a in (self.a_bold, self.a_italic, self.a_underline):
            a.setCheckable(True)
        self.a_bigger = self._action("Larger Text", lambda: self._text_size(+1), "Ctrl+Shift+.", "bigger")
        self.a_smaller = self._action("Smaller Text", lambda: self._text_size(-1), "Ctrl+Shift+,", "smaller")
        self.a_families = self._action("Group Sheets by Family", self.toggle_families)
        self.a_families.setCheckable(True)
        self.a_prev = self._action("Previous Sheet", self.previous_sheet, "Ctrl+PgUp", "prev")
        self.a_next = self._action("Next Sheet", self.next_sheet, "Ctrl+PgDown", "next")
        self.a_about = self._action(f"About {APP_NAME}", self.show_about)
        self.a_about.setMenuRole(QAction.MenuRole.AboutRole)  # macOS: in the application menu
        self.a_guide = self._action(f"{APP_NAME} User Guide", self.show_guide, QKeySequence.HelpContents, "guide")
        m = self.menuBar().addMenu("&File")
        m.addAction(self.a_new)
        m.addAction(self.a_new_table)
        m.addSeparator()
        m.addAction(self.a_open)
        self.recent_menu = m.addMenu("Open Recent")
        self.recent_menu.aboutToShow.connect(self._fill_recent)
        for a in (None, self.a_save, self.a_save_as, self.a_close, None, self.a_export, self.a_print, self.a_report):
            m.addSeparator() if a is None else m.addAction(a)
        m = self.menuBar().addMenu("&Edit")
        for a in (self.a_undo, self.a_redo, None, self.a_cut, self.a_copy, self.a_paste, None, self.a_copy_graph):
            m.addSeparator() if a is None else m.addAction(a)
        self.table_menu = self.menuBar().addMenu("&Table")  # the shown grid's own actions
        m = self.menuBar().addMenu("&Analysis")
        m.addAction(self.a_analyze)
        m.addAction(self.a_params)
        m = self.menuBar().addMenu("&Graph")
        m.addAction(self.a_new_graph)
        m.addAction(self.a_graph_type)
        m.addSeparator()
        m.addAction(self.a_format_graph)
        m.addAction(self.a_format_axes)
        m.addAction(self.a_colors)
        m.addAction(self.a_magic)
        m.addAction(self.a_template)
        m.addSeparator()
        for a in (self.a_bold, self.a_italic, self.a_underline, self.a_bigger, self.a_smaller):
            m.addAction(a)
        m.addSeparator()
        m.addAction(self.a_new_layout)
        m.addSeparator()
        m.addAction(self.a_export)
        self.draw_menu = self.menuBar().addMenu("&Draw")
        self._fill_draw_menu(self.draw_menu)
        m = self.menuBar().addMenu("&View")
        m.addAction(self.a_families)
        m.addSeparator()
        m.addAction(self.a_prev)
        m.addAction(self.a_next)
        m = self.menuBar().addMenu("&Help")
        m.addAction(self.a_guide)
        m.addAction(self.a_about)
        self._ribbon()

    def _ribbon(self) -> None:
        """The toolbar: commands in labelled groups (refract.ui.ribbon)."""
        from ..render import formatting

        rb = Ribbon(self)
        self.font_box = QComboBox()
        self.font_box.setEditable(True)
        self.font_box.addItems(formatting.FONTS)
        self.font_box.setMinimumWidth(110)
        self.font_box.setToolTip("Font of the selected text")
        self.font_box.textActivated.connect(lambda f: self._text_style(family=f))
        self.size_box = QComboBox()
        self.size_box.setEditable(True)
        self.size_box.addItems([str(s) for s in (6, 7, 8, 9, 10, 11, 12, 14, 16, 18, 20, 24, 28, 36)])
        self.size_box.setFixedWidth(58)
        self.size_box.setToolTip("Size of the selected text (points)")
        self.size_box.textActivated.connect(self._size_chosen)
        # each group two rows deep, the groups side by side (as Prism's toolbar): one row across the window
        rb.add_group("File", [[self.a_new, self.a_open], [self.a_save]])
        rb.add_group("Sheet", [[self.a_new_table, self.a_new_graph, self.a_new_layout], [self.a_prev, self.a_next]])
        rb.add_group("Undo", [[self.a_undo], [self.a_redo]])
        rb.add_group("Clipboard", [[self.a_cut, self.a_copy], [self.a_paste, self.a_copy_graph]])
        rb.add_group("Analysis", [[self.a_analyze], [self.a_params]])
        rb.add_group("Change", [[self.a_graph_type, self.a_format_graph, self.a_format_axes],
                                [self.a_colors, self.a_magic]])
        self.font_box.setProperty("span", 3)
        self.size_box.setProperty("span", 2)
        rb.add_group("Text", [[self.font_box, self.size_box],
                              [self.a_bold, self.a_italic, self.a_underline, self.a_bigger, self.a_smaller]])
        self.a_shapes = self._action("More Shapes and Lines", lambda: None, None, None)
        from . import color_menu

        self.a_shapes.setIcon(color_menu.shape_icon("ellipse"))
        self.a_shapes.setMenu(self._palette_menu())
        rb.add_group("Draw", [[self.a_add_text, self.a_tools["line"], self.a_tools["arrow"]],
                              [self.a_tools["bracket:text"], self.a_tools["rect"], self.a_shapes]])
        rb.add_group("Export", [[self.a_export], [self.a_print]])
        rb.add_group("Help", [[self.a_guide]])
        self.addToolBar(rb)
        self.ribbon = rb
        self._text_controls(None)

    # ------------------------------------------------------------ document
    def set_document(self, doc: Document | None) -> None:
        if self.doc is not None:
            self.doc.deleteLater()
        self.doc = doc
        self.views.clear()
        while self.stack.count():
            w = self.stack.widget(0)
            self.stack.removeWidget(w)
            w.deleteLater()
        self.stale.clear()
        self.nav.clear()
        if doc is None:
            self.statusBar().clearMessage()
            start = look.StartPage()
            start.openRequested.connect(self.open_dialog)
            start.newRequested.connect(self.new_project_dialog)
            start.recentRequested.connect(self.open_recent)
            self.stack.addWidget(start)
        else:
            doc.new_graph_format = self._default_graph_format
            doc.modifiedChanged.connect(self._modified_changed)
            doc.tableEdited.connect(self._table_edited)
            doc.sheetsChanged.connect(self._sheets_changed)
            doc.analysisChanged.connect(self._analysis_changed)
            doc.nativeGraphChanged.connect(self._native_changed)
            doc.prismGraphChanged.connect(self._prism_graph_changed)
            doc.undo.canUndoChanged.connect(self.a_undo.setEnabled)
            doc.undo.canRedoChanged.connect(self.a_redo.setEnabled)
            self._fill_table_menu(None)
            self.a_export.setEnabled(False)
            self._fill_navigator()  # shows the first sheet (and fills the Table menu for it)
            if doc.project.warnings:
                self.statusBar().showMessage(f"{len(doc.project.warnings)} reading warning(s): {doc.project.warnings[0]}")
        self.a_undo.setEnabled(False)
        self.a_redo.setEnabled(False)
        for a in (self.a_save, self.a_save_as, self.a_close):
            a.setEnabled(doc is not None)
        if doc is None:
            self.a_analyze.setEnabled(False)
            self.a_params.setEnabled(False)
            self.a_new_graph.setEnabled(False)
            self.a_format_graph.setEnabled(False)
            self.a_format_axes.setEnabled(False)
        if doc is None:
            self.a_export.setEnabled(False)
            self._fill_table_menu(None)
        self.nav.setVisible(doc is not None)
        self._update_title()

    def _fill_navigator(self, select=None) -> None:
        """The sheets by kind (Data Tables, Info, Results, Graphs, Layouts), or
        by family: each data table with the analyses and graphs that use it."""
        self.nav.clear()
        bold = QFont()
        bold.setBold(True)
        first = wanted = None
        for label, entries in (self._families() if self.by_family else self._sections()):
            sec = QTreeWidgetItem(self.nav, [f"{label}  ({len(entries)})"])
            sec.setFont(0, bold)
            sec.setForeground(0, look.color("muted"))
            sec.setFlags(Qt.ItemIsEnabled)
            sec.setData(0, ROLE + 1, label)
            for k, i, title in entries:
                it = QTreeWidgetItem(sec, [title or "(untitled)"])
                it.setIcon(0, look.icon(ICON_OF[k]))
                it.setToolTip(0, (title or "") + ("  (made in Refract)" if k in ("ngraphs", "nlayouts") else ""))
                it.setData(0, ROLE, (k, i))
                first = first or it
                if select == (k, i):
                    first = wanted = it
            new = NEW_ITEMS.get(label)
            if new is not None and not self.by_family:
                it = QTreeWidgetItem(sec, [new])
                it.setData(0, ROLE + 2, label)
                it.setForeground(0, look.color("muted"))
                f = it.font(0)
                f.setItalic(True)
                it.setFont(0, f)
                it.setIcon(0, look.icon("plus"))
            sec.setExpanded(True)
        if first is not None:
            self.nav.setCurrentItem(wanted or first)

    def _entries(self) -> dict[str, list[tuple[str, int, str]]]:
        p = self.doc.project
        copies = self.doc.prism_copy_uids()  # Prism graphs written from Refract's: listed once, as Refract's
        companions = self.doc.prism_companion_uids()  # and the analyses written for them to plot
        return {
            "tables": [("tables", i, t.title) for i, t in enumerate(p.tables) if not t.is_result],
            "infos": [("infos", i, x.title) for i, x in enumerate(p.infos)],
            "results": [("results", i, a.title) for i, a in enumerate(p.analyses) if a.uid not in companions],
            "graphs": [("graphs", i, g.title) for i, g in enumerate(p.graphs) if g.uid not in copies]
            + [("ngraphs", i, g.title) for i, g in enumerate(p.native_graphs)],
            "layouts": [("layouts", i, g.title) for i, g in enumerate(p.layouts)]
            + [("nlayouts", i, x.title) for i, x in enumerate(p.native_layouts)],
        }

    def _sections(self):
        e = self._entries()
        return [(label, e[key]) for key, label in SECTIONS]

    def _families(self):
        """One family per data table; Info first, then the families, sheets
        that belong to no table, and the layouts (they mix families)."""
        from ..render import from_prism

        p = self.doc.project
        e = self._entries()
        out = [("Info", e["infos"])]
        used: set[tuple[str, int]] = set()
        for _k, ti, title in e["tables"]:
            t = p.tables[ti]
            members = [("tables", ti, title)]
            for _k2, ai, at in e["results"]:
                src = self.doc.source_of(p.analyses[ai])
                if src is not None and src[0] is t:
                    members.append(("results", ai, at))
            for k2, gi, gt in e["graphs"]:
                if k2 == "graphs":
                    try:
                        mine = any(x is t for x in from_prism.source_tables(p, gi, self.doc.archive))
                    except Exception:  # noqa: BLE001 - a graph Refract cannot read belongs to no family
                        mine = False
                else:
                    mine = p.native_graphs[gi].table is t
                if mine:
                    members.append((k2, gi, gt))
            used.update((k, i) for k, i, _ in members)
            out.append((title or "(untitled)", members))
        rest = [x for key in ("results", "graphs") for x in e[key] if (x[0], x[1]) not in used]
        if rest:
            out.append(("Other sheets", rest))
        out.append(("Layouts", e["layouts"]))
        return out

    def _modified_changed(self, _modified: bool) -> None:
        self._update_title()

    def _update_title(self) -> None:
        name = self.doc.name if self.doc else ""
        star = "*" if self.doc is not None and self.doc.modified else ""
        self.setWindowTitle(f"{APP_NAME} — {name}{star}" if self.doc else APP_NAME)

    def sheet_items(self) -> list[QTreeWidgetItem]:
        out = []
        for i in range(self.nav.topLevelItemCount()):
            sec = self.nav.topLevelItem(i)
            out += [sec.child(k) for k in range(sec.childCount()) if sec.child(k).data(0, ROLE)]
        return out

    # slots: bound methods, never lambdas holding self (they crash Qt's teardown)
    def undo(self) -> None:
        if self.doc is not None:
            self.doc.undo.undo()

    def redo(self) -> None:
        if self.doc is not None:
            self.doc.undo.redo()

    def previous_sheet(self) -> None:
        self.step(-1)

    def next_sheet(self) -> None:
        self.step(1)

    def step(self, d: int) -> None:
        items = self.sheet_items()
        if items:
            cur = self.nav.currentItem()
            k = items.index(cur) if cur in items else -1
            self.nav.setCurrentItem(items[max(0, min(len(items) - 1, k + d))])

    # --------------------------------------------------------------- views
    def _view(self, key: str, i: int):
        v = self.views.get((key, i))
        if v is None:
            p = self.doc.project
            if key == "tables":
                v = TableSheet(self.doc, p.tables[i])
            elif key == "infos":
                v = InfoView(p.infos[i])
            elif key == "results":
                v = ResultView(self.doc, p.analyses[i])
            elif key == "graphs":
                v = GraphView(self.doc, i)
            elif key == "ngraphs":
                v = NativeGraphView(self.doc, p.native_graphs[i])
            elif key == "layouts":
                v = PrismLayoutView(self.doc, i)
            elif key == "nlayouts":
                v = NativeLayoutView(self.doc, p.native_layouts[i])
            else:
                v = Message(f"Unknown sheet {key}")
            self.views[(key, i)] = v
            self.stack.addWidget(v)
        if key == "graphs" and i in self.stale:
            v.refresh()
            self.stale.discard(i)
        return v

    def _nav_clicked(self, item, _col=0) -> None:
        """The navigator's "New …" entries, and its Results heading: with the
        table shown and no analysis of it yet, Analyze opens by itself."""
        if self.doc is None or item is None:
            return
        new = item.data(0, ROLE + 2)
        if new:
            back = self._last_item
            {"Data Tables": self.new_table_dialog, "Results": self.analyze_dialog, "Graphs": self.new_graph,
             "Layouts": self.new_layout}[new]()
            if self.nav.currentItem() is item and back is not None:
                self.nav.setCurrentItem(back)
            return
        if item.data(0, ROLE + 1) == "Results":
            t = self._analyzed_table()
            if t is not None and not any((self.doc.source_of(a) or (None,))[0] is t for a in self.doc.project.analyses):
                self.analyze_dialog()

    def _show_item(self, item, _prev=None) -> None:
        if item is not None and item.data(0, ROLE + 2):
            return  # a "New …" entry: handled on click
        if item is not None and item.data(0, ROLE):
            self._last_item = item
        ref = item.data(0, ROLE) if item is not None else None
        if not ref or self.doc is None:
            return
        v = self._view(*ref)
        self.stack.setCurrentWidget(v)
        self._update_actions(v)
        kind = {"tables": "Data table", "infos": "Info", "results": "Results", "graphs": "Graph",
                "ngraphs": "Graph made in Refract", "layouts": "Layout (preview)", "nlayouts": "Layout made in Refract"}
        self.statusBar().showMessage(f"{self.doc.name} · {kind[ref[0]]}")

    def _update_actions(self, v) -> None:
        """The commands that depend on the shown sheet: run when a sheet is
        shown and whenever the shown graph is redrawn (its type chosen, ...)."""
        if v is not self.current_view():
            return
        self.a_export.setEnabled(hasattr(v, "export") and getattr(v, "graph", None) is not None)
        self.a_new_graph.setEnabled(self._analyzed_table() is not None)
        for a in (self.a_format_graph, self.a_format_axes, self.a_magic, self.a_template, self.a_colors,
                  self.a_add_text, self.a_copy_graph, self.a_print, *self.a_tools.values()):
            a.setEnabled(self._shown_native() is not None)
        self._tool_changed(getattr(v, "tool", None))
        self._text_controls(v if isinstance(v, GraphView) else None)
        self.a_graph_type.setEnabled(isinstance(v, NativeGraphView))
        self.a_analyze.setEnabled(self._analyzed_table() is not None)
        self.a_params.setEnabled(isinstance(v, ResultView) and v.params_button.isEnabled())
        self._fill_table_menu(v if isinstance(v, TableSheet) else None)

    def current_view(self):
        return self.stack.currentWidget()

    # ------------------------------------------------------------ analyses
    def _analyzed_table(self):
        """The data table the Analyze command works on: the one shown, the one
        the shown analysis reads, or the one the shown Refract graph plots."""
        v = self.current_view()
        if isinstance(v, TableSheet) and not v.read_only:
            return v.table
        if isinstance(v, ResultView):
            src = self.doc.source_of(v.analysis)
            return src[0] if src else None
        if isinstance(v, NativeGraphView):
            return v.ng.table
        return None

    def analyze(self, table, key: str, values: dict | None = None, sets: list[int] | None = None):
        """Create the analysis and show its results sheet."""
        choice = catalog.by_key(key)
        all_sets = sets is None or list(sets) == list(range(len(table.datasets)))
        self._select_after = ("results", len(self.doc.project.analyses))
        a = self.doc.add_analysis(table, choice, values or {}, None if all_sets else list(sets))
        self.statusBar().showMessage(f"Added {a.title}")
        return a

    def analyze_dialog(self) -> None:
        table = self._analyzed_table()
        if table is None:
            return
        d = AnalyzeDialog(table, self)
        if not d.exec():
            return
        choice, sets = d.choice(), d.selected_sets()
        p = ParametersDialog(choice, table, sets, parent=self)
        if p.exec():
            self.analyze(table, choice.key, p.values(), sets)

    def rename_table_dialog(self) -> None:
        from PySide6.QtWidgets import QInputDialog

        v = self.current_view()
        if not isinstance(v, TableSheet) or v.read_only:
            return
        title, ok = QInputDialog.getText(self, "Rename Table", "Title:", text=v.table.title)
        if ok and not self.doc.rename_table(v.table, title):
            QMessageBox.information(self, APP_NAME, "That title is empty or already used by another table.")

    def change_shown_parameters(self) -> None:
        self.change_parameters(None)

    def change_parameters(self, analysis=None) -> None:
        v = self.current_view()
        a = analysis or (v.analysis if isinstance(v, ResultView) else None)
        choice = catalog.for_class(a.analysis_class) if a is not None else None
        src = self.doc.source_of(a) if a is not None else None
        if choice is None or src is None:
            return
        t, sets = src
        sets = list(range(len(t.datasets))) if sets is None else sets
        p = ParametersDialog(choice, t, sets, catalog.options_of(choice, a.parameters.get("content", {})), self)
        if p.exec():
            self.doc.set_parameters(a, choice, p.values())

    def _sheets_changed(self) -> None:
        cur = self.nav.currentItem()
        ref = cur.data(0, ROLE) if cur is not None else None
        tables = self.doc.project.tables
        for key in [k for k in self.views if k[0] == "tables"
                    and (k[1] >= len(tables) or getattr(self.views[k], "table", None) is not tables[k[1]])]:
            w = self.views.pop(key)
            self.stack.removeWidget(w)
            w.deleteLater()
        for key in [k for k in self.views if k[0] in ("results", "ngraphs", "nlayouts")]:  # indices may have moved
            w = self.views.pop(key)
            self.stack.removeWidget(w)
            w.deleteLater()
        want, self._select_after = self._select_after or ref, None
        for key, lst in (("results", self.doc.project.analyses), ("ngraphs", self.doc.project.native_graphs),
                         ("nlayouts", self.doc.project.native_layouts)):
            n = len(lst)
            if want and want[0] == key and want[1] >= n:
                want = (key, n - 1) if n else None
        self._fill_navigator(select=want)

    # ---------------------------------------------------- Refract graphs
    def new_graph(self) -> None:
        t = self._analyzed_table()
        if t is None:
            return
        n = len(self.doc.project.native_graphs)
        self._select_after = ("ngraphs", n)
        ng = self.doc.add_native_graph(t, style="")  # the new sheet asks for its type
        if ng is None:
            self._select_after = None
            self.statusBar().showMessage(f"Refract cannot graph {t.kind} tables yet")

    # ------------------------------------------------------- formatting
    def _exec(self, dialog) -> bool:
        """Run a modal dialog (tests replace this to answer it)."""
        return bool(dialog.exec())

    def _shown_native(self):
        """The shown graph view that can be formatted (Refract's graphs and graphs from the file)."""
        v = self.current_view()
        return v if isinstance(v, GraphView) and v.graph is not None and v.graph.family != "pie" else None

    def format_graph_dialog(self, set_index: int | None = None, page: str = "sets") -> bool:
        from .format_graph import FormatGraphDialog

        v = self._shown_native()
        if v is None:
            return False
        d = FormatGraphDialog(v.current_format(), v.graph, v.canvas.lay, set_index, page, self)
        if not self._exec(d):
            return False
        return v.set_format(d.result_format())

    def format_axes_dialog(self, axis: str = "y") -> bool:
        from .format_graph import FormatAxesDialog

        v = self._shown_native()
        if v is None:
            return False
        d = FormatAxesDialog(v.current_format(), v.graph, v.canvas.lay, axis if axis in ("x", "y") else "y", self)
        if not self._exec(d):
            return False
        return v.set_format(d.result_format())

    def format_object(self, kind: str, index: int | None = None) -> bool:
        """Double-click on a graph object: the dialog and page that format it."""
        if kind in ("x", "y"):
            return self.format_axes_dialog(kind)
        if kind == "set":
            return self.format_graph_dialog(index, "sets")
        return self.format_graph_dialog(None, "graph")

    # ------------------------------------------------- text, colours, magic
    def _graph_view(self):
        v = self.current_view()
        return v if isinstance(v, GraphView) and v.canvas is not None else None

    def _text_controls(self, view) -> None:
        """The Text group follows the selected text object of the shown graph."""
        state = view.text_state() if view is not None and view is self._graph_view() else None
        on = state is not None
        for w in (self.font_box, self.size_box):
            w.setEnabled(on)
        for a in (self.a_bold, self.a_italic, self.a_underline, self.a_bigger, self.a_smaller):
            a.setEnabled(on)
        if not on:
            for a in (self.a_bold, self.a_italic, self.a_underline):
                a.setChecked(False)
            return
        self.font_box.setCurrentText(state["family"])
        self.size_box.setCurrentText(f"{state['size']:g}")
        for a, k in ((self.a_bold, "bold"), (self.a_italic, "italic"), (self.a_underline, "underline")):
            a.setChecked(bool(state[k]))

    def _text_style(self, **values) -> bool:
        v = self._graph_view()
        if v is None or v.selected_text() is None:
            return False
        return v.change_text(v.selected_text(), **values)

    def _size_chosen(self, text: str) -> None:
        try:
            size = float(text)
        except ValueError:
            return
        if 2 <= size <= 200:
            self._text_style(size=size)

    def _text_size(self, d: int) -> bool:
        v = self._graph_view()
        state = v.text_state() if v is not None else None
        if state is None:
            return False
        steps = [6, 7, 8, 9, 10, 11, 12, 14, 16, 18, 20, 24, 28, 36, 48, 72]
        s = state["size"]
        nxt = next((x for x in steps if x > s + 0.01), s + 2) if d > 0 else \
            next((x for x in reversed(steps) if x < s - 0.01), max(2, s - 1))
        return self._text_style(size=nxt)

    def add_text(self) -> str | None:
        v = self._graph_view()
        return v.add_text() if v is not None else None

    def _choose_tool(self, kind: str) -> None:
        """A drawing tool for the shown graph; choosing it again goes back to selecting."""
        v = self._graph_view()
        if v is None:
            self._tool_changed(None)
            return
        v.set_tool(None if v.tool == kind else kind)

    def _fill_draw_menu(self, m) -> None:
        """Draw (menu bar): text boxes, shapes, lines and lines with text, as Prism's Draw palette."""
        from ..render.shape_kinds import KINDS, LABELLED

        m.addAction(self.a_add_text)
        m.addSection("Shapes")
        for k, (grp, _l) in KINDS.items():
            if grp == "Shapes":
                m.addAction(self.a_tools[k])
        m.addSection("Lines")
        for k, (grp, _l) in KINDS.items():
            if grp == "Lines":
                m.addAction(self.a_tools[k])
        m.addSection("Lines with Text")
        for k in LABELLED:
            m.addAction(self.a_tools[f"{k}:text"])

    def _palette_menu(self):
        """The toolbar's palette: every drawing tool as an icon, in Shapes, Lines and Lines with text."""
        from PySide6.QtCore import QSize
        from PySide6.QtWidgets import (
            QGridLayout,
            QLabel,
            QToolButton,
            QVBoxLayout,
            QWidget,
            QWidgetAction,
        )

        from ..render.shape_kinds import KINDS, LABELLED

        menu = QMenu(self)
        box = QWidget()
        v = QVBoxLayout(box)
        v.setContentsMargins(10, 6, 10, 8)
        sections = [("Shapes", [k for k, (g, _l) in KINDS.items() if g == "Shapes"]),
                    ("Lines", [k for k, (g, _l) in KINDS.items() if g == "Lines"]),
                    ("Lines with text", [f"{k}:text" for k in LABELLED])]
        for title, keys in sections:
            lab = QLabel(title)
            lab.setObjectName("muted")
            v.addWidget(lab)
            grid = QGridLayout()
            grid.setSpacing(2)
            for n, k in enumerate(keys):
                b = QToolButton()
                b.setDefaultAction(self.a_tools[k])
                b.setIconSize(QSize(26, 26))
                b.setAutoRaise(True)
                b.setToolButtonStyle(Qt.ToolButtonIconOnly)
                b.clicked.connect(menu.close)
                grid.addWidget(b, n // 6, n % 6)
            v.addLayout(grid)
        act = QWidgetAction(menu)
        act.setDefaultWidget(box)
        menu.addAction(act)
        return menu

    def _tool_changed(self, tool: str | None) -> None:
        for k, a in self.a_tools.items():
            a.setChecked(k == tool)

    def _fill_colors_menu(self) -> None:
        from . import schemes_dialog as SD

        m = self.colors_menu
        m.clear()
        v = self._graph_view()
        recent = SD.recent()
        if recent:
            sub = m.addMenu("Recently Used")
            for name in recent:
                SD.scheme_row(sub, name, SD.all_schemes()[name], self.apply_scheme)
        m.addSeparator()
        from ..render import schemes

        for name, colors in schemes.BUILT_IN.items():
            SD.scheme_row(m, name, colors, self.apply_scheme)
        m.addSeparator()
        for pkg, groups in schemes.LIBRARY.items():  # one submenu per package, one level more per group
            pm = m.addMenu(pkg)
            for group, pals in groups.items():
                gm = pm.addMenu(group)
                for pal, colors in pals.items():
                    SD.scheme_row(gm, schemes.library_name(pkg, pal), colors, self.apply_scheme, label=pal)
        yours = m.addMenu("Your Schemes")
        custom = SD.custom()
        for name, colors in custom.items():
            SD.scheme_row(yours, name, colors, self.apply_scheme)
        if custom:
            yours.addSeparator()
        yours.addAction("New Color Scheme…", self.define_scheme)
        yours.addAction("Customize an Existing Scheme…", lambda: self.define_scheme(start=True))
        yours.addAction("Import Colors…", lambda: self.define_scheme(import_file=True))
        if custom:
            ed = yours.addMenu("Edit")
            for name in custom:
                ed.addAction(name, lambda n=name: self.edit_scheme(n))
            dele = yours.addMenu("Delete")
            for name in custom:
                dele.addAction(name, lambda n=name: SD.delete_custom(n))
        m.addSeparator()
        m.addAction("Set the Default Color Scheme…", self.default_scheme_dialog)
        m.addSeparator()
        for label, key in (("Background Color…", "background"), ("Plotting Area Color…", "plot_fill"),
                           ("Axes Color…", "axis_color")):
            m.addAction(label, lambda k=key: self.pick_color(k))
        m.addAction("Reset Background, Plotting Area and Axes", self.reset_colors)
        for a in m.actions():
            a.setEnabled(v is not None or a.text().startswith(("Set the",)) or a.menu() is not None)
            if a.__class__.__name__ == "QWidgetAction" and a.defaultWidget() is not None:
                a.defaultWidget().setEnabled(a.isEnabled())

    def graph_type_dialog(self) -> bool:
        """Change Graph Type (refract.ui.graph_wizard) for the shown Refract graph."""
        from .graph_wizard import run_wizard

        v = self.current_view()
        if not isinstance(v, NativeGraphView):
            return False
        return run_wizard(self, v)

    def _default_graph_format(self, ng) -> dict | None:
        """A new Refract graph's colours from the default colour scheme."""
        from . import schemes_dialog as SD

        name = SD.default_scheme()
        if name is None:
            return None
        colors = SD.all_schemes()[name]
        bars = ng.table.kind == "grouped" or ng.style == "bars"
        return {"scheme": name, "sets": {str(i): ({"fill": c} if bars else {"fill": c, "color": c})
                                         for i, c in ((i, colors[i % len(colors)])
                                                      for i in range(len(ng.table.datasets)))}}

    def apply_scheme(self, name: str) -> bool:
        from ..render import schemes
        from . import schemes_dialog as SD

        v = self._graph_view()
        colors = SD.all_schemes().get(name)
        if v is None or not colors:
            return False
        SD.used(name)
        fmt = schemes.apply(v.current_format(), v.graph, colors)
        fmt["scheme"] = name  # the scheme element colours are chosen from first (refract.ui.color_menu)
        return v.set_format(fmt)

    def define_scheme(self, start: bool = False, import_file: bool = False) -> str | None:
        """A new scheme of the user's (from the shown graph's colours, another
        scheme or a file); applied to the shown graph. Returns its name."""
        from ..render import schemes
        from . import schemes_dialog as SD

        v = self._graph_view()
        d = SD.DefineSchemeDialog(schemes.colors_of(v.graph) if v is not None else [], parent=self)
        if start:
            from PySide6.QtCore import QTimer

            QTimer.singleShot(0, d.start.showPopup)  # the list of schemes to start from, once shown
        if import_file and not d._import_file():
            return None
        return self._save_scheme(d)

    def edit_scheme(self, name: str) -> str | None:
        from . import schemes_dialog as SD

        colors = SD.custom().get(name)
        if colors is None:
            return None
        return self._save_scheme(SD.DefineSchemeDialog(colors, name, parent=self, editing=name))

    def _save_scheme(self, d) -> str | None:
        from . import schemes_dialog as SD

        if not self._exec(d):
            return None
        name, colors = d.scheme()
        if not colors:
            return None
        SD.rename_custom(d.editing or name, name, colors)
        if self._graph_view() is not None:
            self.apply_scheme(name)
        return name

    def default_scheme_dialog(self) -> None:
        from PySide6.QtWidgets import QInputDialog

        from . import schemes_dialog as SD

        names = ["(none: Prism's defaults)"] + list(SD.all_schemes())
        cur = SD.default_scheme()
        name, ok = QInputDialog.getItem(self, "Default Color Scheme", "New graphs start with:", names,
                                        names.index(cur) if cur in names else 0, False)
        if ok:
            look.set_setting(SD.DEFAULT_KEY, "" if name == names[0] else name)

    def pick_color(self, key: str) -> bool:
        from PySide6.QtGui import QColor
        from PySide6.QtWidgets import QColorDialog

        v = self._graph_view()
        if v is None:
            return False
        cur = v.current_format().get(key) or ("#ffffff" if key != "axis_color" else "#000000")
        c = QColorDialog.getColor(QColor(cur), self, "Color")
        if not c.isValid():
            return False
        fmt = dict(v.current_format())
        fmt[key] = c.name()
        return v.set_format(fmt)

    def reset_colors(self) -> bool:
        v = self._graph_view()
        if v is None:
            return False
        fmt = {k: x for k, x in v.current_format().items() if k not in ("background", "plot_fill", "axis_color")}
        return v.set_format(fmt)

    def _magic_examples(self, target_view) -> list[tuple[str, object, dict]]:
        """The project's other graphs that can be drawn, with their styles."""
        from ..render import magic, native
        from ..render import qt as Q

        out = []
        p = self.doc.project
        copies = self.doc.prism_copy_uids()
        for i, g in enumerate(p.graphs):
            if g.uid in copies or (isinstance(target_view, GraphView) and not isinstance(target_view, NativeGraphView)
                                   and target_view.index == i):
                continue
            try:
                gr = self.doc.prism_graph(i)
            except Exception:  # noqa: BLE001, S112 - graphs Refract cannot draw are not offered
                continue
            if gr.family == "pie":
                continue
            out.append((g.title or "(untitled)", gr, magic.style_of(gr, Q.layout(gr))))
        for ng in p.native_graphs:
            if isinstance(target_view, NativeGraphView) and target_view.ng is ng:
                continue
            try:
                gr = native.graph(p, ng, self.doc.results, self.doc.source_of)
            except Exception:  # noqa: BLE001, S112
                continue
            if gr.family == "pie":
                continue
            out.append((ng.title + " (Refract)", gr, magic.style_of(gr, Q.layout(gr))))
        return out

    def magic_dialog(self) -> bool:
        from ..render import magic
        from .magic_dialog import MagicDialog

        v = self._graph_view()
        if v is None or v.graph is None or v.graph.family == "pie":
            return False
        d = MagicDialog(v.graph, v.current_format(), self._magic_examples(v), self)
        if not self._exec(d):
            return False
        style, parts, every = d.choice()
        targets = [v] if not every else [x for x in self._all_graph_views() if x.graph is not None
                                         and x.graph.family == v.graph.family]
        self.doc.undo.beginMacro("Magic")
        try:
            for t in targets:
                t.set_format(magic.match(t.current_format(), t.graph, style, parts))
        finally:
            self.doc.undo.endMacro()
        return True

    def save_style_template(self) -> bool:
        from PySide6.QtWidgets import QInputDialog

        from ..render import magic
        from .magic_dialog import save_template

        v = self._graph_view()
        if v is None or v.graph is None:
            return False
        name, ok = QInputDialog.getText(self, "Save Style Template", "Name of the template:",
                                        text=v.graph.title or "My style")
        if not ok or not name.strip():
            return False
        save_template(name.strip(), magic.style_of(v.graph, v.canvas.lay))
        self.statusBar().showMessage(f"Saved the style template \u201c{name.strip()}\u201d (Graph \u25b8 Magic)", 8000)
        return True

    def _all_graph_views(self):
        """A view for every graph of the project (made when missing)."""
        p = self.doc.project
        copies = self.doc.prism_copy_uids()
        for i, g in enumerate(p.graphs):
            if g.uid not in copies:
                v = self._view("graphs", i)
                if isinstance(v, GraphView):
                    yield v
        for i in range(len(p.native_graphs)):
            v = self._view("ngraphs", i)
            if isinstance(v, GraphView):
                yield v

    def _clipboard(self, what: str) -> None:
        v = self.current_view()
        if isinstance(v, TableSheet):
            v.actions_[what].trigger()
        elif isinstance(v, GraphView) and what == "copy":
            self.copy_graph()

    def copy_graph(self) -> bool:
        """The shown graph on the clipboard as a picture (300 dpi)."""
        from PySide6.QtWidgets import QApplication

        from ..render import qt as Q

        v = self.current_view()
        g = getattr(v, "graph", None)
        if g is None or not isinstance(v, GraphView):
            return False
        lay = Q.layout(g)
        img = Q.to_image(g, 300 / 72, lay=lay, margins=Q.overflow(g, lay))  # with objects beyond the graph's box
        QApplication.clipboard().setImage(img)
        self.statusBar().showMessage("Graph copied as a picture", 5000)
        return True

    def print_sheet(self) -> bool:
        """Print the shown graph on its page (as the sheet shows it)."""
        from PySide6.QtPrintSupport import QPrintDialog, QPrinter

        from ..render import qt as Q

        v = self.current_view()
        if not isinstance(v, GraphView) or v.graph is None:
            return False
        printer = QPrinter(QPrinter.HighResolution)
        if QPrintDialog(printer, self).exec() != QPrintDialog.Accepted:
            return False
        from PySide6.QtGui import QPainter

        p = QPainter(printer)
        r = printer.pageRect(QPrinter.DevicePixel)
        lay = v.canvas.lay
        k = min(r.width() / lay.width, r.height() / lay.height, printer.resolution() / 72)
        p.translate(r.x() + (r.width() - lay.width * k) / 2, r.y() + (r.height() - lay.height * k) / 2)
        p.scale(k, k)
        Q.draw(p, v.graph, lay)
        p.end()
        return True

    def _native_views(self, table=None):
        for (k, _i), v in list(self.views.items()):
            if k == "ngraphs" and (table is None or v.ng.table is table):
                yield v

    def _native_changed(self, ng) -> None:
        for v in self._native_views():
            if v.ng is ng:
                v.refresh()
                self._update_actions(v)
        self._refresh_layouts()

    def _prism_graph_changed(self, index: int) -> None:
        v = self.views.get(("graphs", index))
        if v is not None:
            v.refresh()
            self._update_actions(v)
        self._refresh_layouts()

    def _refresh_layouts(self) -> None:
        """Layouts show their graphs from the current data and formats."""
        for (k, _i), v in list(self.views.items()):
            if k in ("layouts", "nlayouts"):
                v.refresh()

    # ------------------------------------------------------------ layouts
    def new_layout(self) -> None:
        """A Refract layout, with the shown graph on it when one is shown."""
        v = self.current_view()
        refs = []
        if isinstance(v, NativeGraphView):
            refs = [f"refract:{v.ng.uid}"]
        elif isinstance(v, GraphView) and v.index >= 0 and self.doc.project.graphs[v.index].uid:
            refs = [f"prism:{self.doc.project.graphs[v.index].uid}"]
        self._select_after = ("nlayouts", len(self.doc.project.native_layouts))
        self.doc.add_layout(refs=refs)

    def copy_prism_layout(self, index: int) -> None:
        self._select_after = ("nlayouts", len(self.doc.project.native_layouts))
        self.doc.copy_prism_layout(index)

    def toggle_families(self, on: bool | None = None) -> None:
        """Group the navigator by family (the checkable action passes its new state)."""
        self.by_family = self.a_families.isChecked() if on is None else bool(on)
        self.a_families.setChecked(self.by_family)
        look.set_setting("navigator/families", self.by_family)
        if self.doc is not None:
            cur = self.nav.currentItem()
            self._fill_navigator(select=cur.data(0, ROLE) if cur is not None else None)

    def _analysis_changed(self, a) -> None:
        src = self.doc.source_of(a) if self.doc is not None else None
        for v in self._native_views(src[0] if src else None):
            v.refresh()
        self._refresh_layouts()

    def _table_edited(self, table) -> None:
        from ..render import from_prism

        for v in self._native_views(table):
            v.refresh()
        self._refresh_layouts()

        for i in range(len(self.doc.project.graphs)):
            if any(t is table for t in from_prism.source_tables(self.doc.project, i, self.doc.archive)):
                v = self.views.get(("graphs", i))
                if v is not None and v is self.current_view():
                    v.refresh()
                else:
                    self.stale.add(i)

    # --------------------------------------------------------------- files
    def maybe_save(self) -> bool:
        """True when it is fine to drop the current document."""
        if self.doc is None or not self.doc.modified:
            return True
        r = QMessageBox.question(self, APP_NAME, f"Save changes to {self.doc.name}?",
                                 QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
        if r == QMessageBox.Save:
            return self.save()
        return r == QMessageBox.Discard

    def open_path(self, path: str) -> None:
        self.set_document(Document.open(path))
        look.add_recent(path)

    def open_recent(self, path: str) -> None:
        if not self.maybe_save():
            return
        try:
            self.open_path(path)
        except Exception as e:  # noqa: BLE001 - show any reading failure
            QMessageBox.warning(self, APP_NAME, f"Cannot open {os.path.basename(path)}:\n{e}")

    def close_document(self) -> None:
        if self.maybe_save():
            self.set_document(None)

    def _fill_recent(self) -> None:
        self.recent_menu.clear()
        files = look.recent_files()
        for f in files:
            a = self.recent_menu.addAction(os.path.basename(f))
            a.setData(f)
            a.setToolTip(f)
            a.triggered.connect(self._recent_chosen)
        if not files:
            self.recent_menu.addAction("(none)").setEnabled(False)

    def _recent_chosen(self) -> None:
        a = self.sender()
        if a is not None:
            self.open_recent(a.data())

    def _fill_table_menu(self, grid) -> None:
        self.table_menu.clear()
        if grid is None:
            self.table_menu.addAction("(no data table shown)").setEnabled(False)
            return
        from .grid import GROUPS

        for group in GROUPS:
            for k in group:
                self.table_menu.addAction(grid.actions_[k])
            self.table_menu.addSeparator()
        self.table_menu.addAction(self.a_rename_table)

    def open_request(self, path: str) -> None:
        """A file the system asks to open (Finder "Open With", a document dropped
        on the Dock icon; refract.ui.app)."""
        if self.doc is not None and self.doc.path and os.path.abspath(self.doc.path) == os.path.abspath(path):
            self.raise_()
            return
        self.open_recent(path)

    def show_about(self) -> None:
        from .. import about

        box = QMessageBox(self)
        box.setWindowTitle(f"About {APP_NAME}")
        box.setText(f"<b>{APP_NAME}</b> {about.VERSION}<br>{about.SUMMARY}")
        box.setInformativeText(about.NOTICE
                               + f"<br><br>{about.COPYRIGHT}. License: {about.LICENSE}. "
                               + about.LICENSE_NOTICE + " " + about.SOURCE_NOTE
                               + "<br><br>Includes: "
                               + ", ".join(f"{n} ({lic})" for n, lic in about.COMPONENTS))
        box.setIconPixmap(look.app_icon().pixmap(64, 64))
        box.exec()

    def show_guide(self) -> None:
        from . import help_view

        help_view.show(self)

    def open_dialog(self) -> None:
        if not self.maybe_save():
            return
        path, _ = QFileDialog.getOpenFileName(self, "Open", "", OPEN_FILTER)
        if path:
            try:
                self.open_path(path)
            except Exception as e:  # noqa: BLE001 - show any reading failure
                QMessageBox.warning(self, APP_NAME, f"Cannot open {os.path.basename(path)}:\n{e}")

    # ---------------------------------------------------------- new tables
    def new_table(self, table) -> None:
        """Add the table to the open project (or a new one) and show it."""
        if self.doc is None:
            self.set_document(Document.new())
        tables = self.doc.project.tables
        self._select_after = ("tables", max((i for i, t in enumerate(tables) if not t.is_result), default=-1) + 1)
        self.doc.add_table(table, graph_style=self.new_graph_style)  # "": its graph sheet asks how to graph it
        self.statusBar().showMessage(f"Added {table.title}")

    def new_table_dialog(self) -> None:
        title = self.doc.next_table_title() if self.doc is not None else "Data 1"
        d = NewTableDialog(title, self, new_project=self.doc is None)
        if d.exec():
            self.new_table(d.table())
        elif d.opened:
            self.open_dialog()

    def new_project(self, table) -> None:
        self.set_document(Document.new())
        self.new_table(table)

    def new_project_dialog(self) -> None:
        if not self.maybe_save():
            return
        d = NewTableDialog("Data 1", self, new_project=True)
        if d.exec():
            self.new_project(d.table())
        elif d.opened:
            self.open_dialog()

    def save(self) -> bool:
        if self.doc is None:
            return False
        if self.doc.path is None:
            return self.save_as_dialog()
        if not self.doc.can_save():
            QMessageBox.information(self, APP_NAME, "Saving is supported for .prism and .pzfx files.")
            return False
        if self.doc.is_pzfx and self.doc.path.lower().endswith(".pzfx") and self.doc.pzfx_blockers():
            return self._offer_prism(PzfxUnsupported("; ".join(self.doc.pzfx_blockers())))
        return self._save_to(None)

    def _save_to(self, path: str | None) -> bool:
        try:
            touched = self.doc.save(path)
        except PzfxUnsupported as e:
            return self._offer_prism(e)
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, APP_NAME, f"Saving failed:\n{e}")
            return False
        self._saved_message(touched)
        if path:
            look.add_recent(path)
        self._update_title()
        return True

    def _offer_prism(self, why: Exception) -> bool:
        """A .pzfx file cannot hold this edit: offer Save As .prism."""
        r = QMessageBox.question(
            self, APP_NAME,
            f"{self.doc.name} can't hold this as a .pzfx file:\n{why}\n\nSave a .prism copy instead?",
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Save)
        return r == QMessageBox.StandardButton.Save and self.save_as_dialog(prism_only=True)

    def _saved_message(self, touched: list[str]) -> None:
        written = sum(1 for g in self.doc.project.native_graphs if g.prism_uid)
        msg = f"Saved {self.doc.name} ({len(touched)} entries rewritten"
        msg += f"; {written} Refract graph(s) also written as Prism graphs)" if written else ")"
        if self.doc.last_report:
            msg += f" — {len(self.doc.last_report)} note(s) for Prism: File ▸ Prism Compatibility Report"
        self.statusBar().showMessage(msg, 15000)

    def report_text(self) -> str:
        if self.doc is None or not self.doc.last_report:
            return "Everything in the last save is shown in Prism as in Refract (or nothing was saved yet)."
        return "What Prism will show differently from Refract:\n\n" + "\n".join(f"• {r}" for r in self.doc.last_report)

    def show_report(self) -> None:
        QMessageBox.information(self, "Prism Compatibility Report", self.report_text())

    def save_as_dialog(self, prism_only: bool = False) -> bool:
        if self.doc is None or not self.doc.can_save():
            return False if self.doc is None else self.save()
        base = os.path.splitext(self.doc.path)[0] if self.doc.path else ""
        if self.doc.is_pzfx and not prism_only:
            filters = f"{PZFX_FILTER};;{PRISM_FILTER}"
            start = base + ".pzfx" if base else ""
        else:
            filters, start = PRISM_FILTER, (base + ".prism" if base else "")
        path, chosen = QFileDialog.getSaveFileName(self, "Save As", start, filters)
        if not path:
            return False
        ext = ".pzfx" if chosen == PZFX_FILTER else ".prism"
        if not path.lower().endswith((".prism", ".pzfx")):
            path += ext
        if self.doc.is_pzfx and path.lower().endswith(".prism") and not self.confirm_convert():
            return False
        return self._save_to(path)

    def confirm_convert(self) -> bool:
        """Before a .pzfx document is saved as .prism: say what stays behind."""
        loss = self.doc.convert_loss()
        if not loss:
            return True
        text = ("The .prism file will hold the data tables, the info sheet and what you made in Refract. "
                "Not carried over:\n\n" + "\n".join(f"• {x}" for x in loss)
                + f"\n\n{self.doc.name} itself is not changed.")
        r = QMessageBox.question(self, "Save As .prism", text,
                                 QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Cancel,
                                 QMessageBox.StandardButton.Save)
        return r == QMessageBox.StandardButton.Save

    def export_dialog(self) -> None:
        v = self.current_view()
        if not hasattr(v, "export") or getattr(v, "graph", None) is None:
            return
        name = v.nl.title if isinstance(v, NativeLayoutView) else (
            self.doc.project.layouts[v.index].title if isinstance(v, PrismLayoutView) else v.graph.title)
        path, _ = QFileDialog.getSaveFileName(self, "Export", f"{name or 'graph'}.pdf",
                                              "PDF (*.pdf);;SVG (*.svg);;PNG, 300 dpi (*.png)")
        if path:
            v.export(path)
            self.statusBar().showMessage(f"Exported {os.path.basename(path)}")

    def closeEvent(self, e) -> None:
        if self.maybe_save():
            e.accept()
        else:
            e.ignore()
