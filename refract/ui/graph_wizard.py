"""Change Graph Type (Graph ▸ Change Graph Type, and the first look at a new
table's graph sheet; docs/ui-spec.md §3.4): the families the table can be
drawn as, the family's types in tabs as thumbnails, the type's options, an
option to make the choice the default, and a preview of this table drawn as
the chosen type, redrawn at every change (refract.render.graph_types)."""

from __future__ import annotations

import copy
import json

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon, QImage, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListView,
    QListWidget,
    QListWidgetItem,
    QRadioButton,
    QTabBar,
    QVBoxLayout,
    QWidget,
)

from ..model import templates as T
from ..render import graph_types as GT
from ..render import native, qt
from . import look, type_icons

THUMB = QSize(type_icons.W, type_icons.H)
DEFAULT_KEY = "graph/defaults"  # family -> {"style", "error", "options"}
_THUMBS: dict[str, QIcon] = {}
DEMO = {"xy": "xy", "column": "column", "grouped": "grouped", "contingency": "contingency", "survival": "survival",
        "parts_of_whole": "parts_of_whole", "nested": "nested", "multivariable": "multivariable"}


def user_defaults() -> dict:
    try:
        v = json.loads(look.setting(DEFAULT_KEY, "{}") or "{}")
    except (TypeError, ValueError):
        return {}
    return v if isinstance(v, dict) else {}


def default_choice(kind: str) -> tuple[str, str | None, dict]:
    """(type, plot option, options) a new graph of a table kind starts with."""
    d = user_defaults().get(kind) or {}
    gt = GT.BY_KEY.get(d.get("style", ""))
    if gt is None or gt.family not in GT.FAMILIES.get(kind, [kind]):
        gt = GT.BY_KEY[GT.DEFAULTS[kind]]
        return gt.key, GT.plot_option(gt, None), {}
    return gt.key, GT.plot_option(gt, d.get("error")), dict(d.get("options") or {})


def thumbnail(gt: GT.GraphType) -> QIcon:
    """The type drawn on our sample data, cropped to its plot (no words)."""
    if gt.key in _THUMBS:
        return _THUMBS[gt.key]
    t = T.make(DEMO[gt.family], "", sample=True)
    opts = {"color": "Sex", "size": "Dose"} if gt.family == "multivariable" else {}
    g = GT.make(t, gt, gt.plots[0][0] if gt.plots else None, "", opts)
    g.legend = False
    g.x_axis.title = g.y_axis.title = ""
    k = 2.0
    lay = qt.layout(g)
    img = qt.to_image(g, k, lay=lay)
    left, top, right, bottom = lay.plot
    if g.family == "pie":
        crop = img
    else:
        if g.heatmap is not None:
            right = lay.width - 4
        crop = img.copy(int((left - 3) * k), int((top - 4) * k), int((right - left + 8) * k), int((bottom - top + 7) * k))
    pm = QPixmap(THUMB.width() * 2, THUMB.height() * 2)
    pm.fill(Qt.white)
    from PySide6.QtGui import QPainter

    p = QPainter(pm)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    scaled = crop.scaled(pm.width() - 12, pm.height() - 12, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    p.drawImage((pm.width() - scaled.width()) // 2, (pm.height() - scaled.height()) // 2, scaled)
    p.end()
    pm.setDevicePixelRatio(2)
    _THUMBS[gt.key] = QIcon(pm)
    return _THUMBS[gt.key]


class GraphTypeDialog(QDialog):
    def __init__(self, doc, ng, parent=None, first: bool = False):
        super().__init__(parent)
        self.setWindowTitle("Choose a Graph Type" if first else "Change Graph Type")
        self.setObjectName("graphWizard")
        self.resize(820, 860)
        self.doc, self.ng = doc, ng
        t = ng.table
        start = GT.resolve(t.kind, ng.style)
        if start is None:
            key, plot, opts = default_choice(t.kind)
            start, self.plot0, self.options = GT.BY_KEY[key], plot, opts
        else:
            self.plot0, self.options = GT.plot_option(start, ng.error), dict(ng.options)
        self.family = QComboBox()
        for f in GT.FAMILIES.get(t.kind, [t.kind]):
            self.family.addItem(GT.FAMILY_NAMES[f], f)
        self.tabs = QTabBar()
        self.tabs.setExpanding(False)
        self.types = QListWidget()
        self.types.setViewMode(QListView.IconMode)
        self.types.setFlow(QListView.LeftToRight)
        self.types.setWrapping(False)
        self.types.setIconSize(THUMB)
        self.types.setMovement(QListView.Static)
        self.types.setSpacing(6)
        self.types.setFixedHeight(THUMB.height() + 46)
        self.types.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.types.setObjectName("typeStrip")
        c = look.colors()  # the icons are drawn in the palette: the strip takes it too
        self.types.setStyleSheet(
            f"QListWidget#typeStrip {{ background: {c['panel']}; border: 1px solid {c['line']}; border-radius: 8px; }}"
            "QListWidget#typeStrip::item { border: 2px solid transparent; border-radius: 10px; padding: 4px; }"
            f"QListWidget#typeStrip::item:hover {{ background: {c['hover']}; }}"
            f"QListWidget#typeStrip::item:selected {{ background: {c['bar']}; border: 2px solid {c['accent']}; }}")
        self.setStyleSheet(look.style())
        self.name = QLabel()
        f = self.name.font()
        f.setBold(True)
        self.name.setFont(f)
        self.prism_note = QLabel()  # what Prism will show of this type (graph_types.in_prism)
        self.prism_note.setObjectName("prismNote")
        self.plot = QComboBox()
        self.plot_label = QLabel("Plot:")
        # survival options
        self.surv = QWidget()
        sg = QGridLayout(self.surv)
        sg.setContentsMargins(0, 0, 0, 0)
        self.fractions = QRadioButton("Fractions")
        self.percents = QRadioButton("Percents")
        grp = QButtonGroup(self.surv)
        grp.addButton(self.fractions)
        grp.addButton(self.percents)
        (self.fractions if self.options.get("scale") == "fraction" else self.percents).setChecked(True)
        self.err_none = QRadioButton("None")
        self.err_se, self.err_ci = QRadioButton("SE"), QRadioButton("95% CI")
        {"se": self.err_se, "ci": self.err_ci}.get(self.options.get("error"), self.err_none).setChecked(True)
        self.err_se.setToolTip("Plus and minus the standard error (Greenwood)")
        self.err_ci.setToolTip("The 95% confidence interval (asymmetrical, as the survival analysis reports it)")
        eg = QButtonGroup(self.surv)
        for b in (self.err_none, self.err_se, self.err_ci):
            eg.addButton(b)
            b.toggled.connect(self._changed)
        err_se, err_ci = self.err_se, self.err_ci
        sg.addWidget(QLabel("Show results as:"), 0, 0)
        sg.addWidget(self.fractions, 1, 0)
        sg.addWidget(self.percents, 2, 0)
        sg.addWidget(QLabel("Error bars:"), 0, 1)
        sg.addWidget(self.err_none, 1, 1)
        sg.addWidget(err_se, 2, 1)
        sg.addWidget(err_ci, 3, 1)
        # multiple-variables options
        self.mv = QWidget()
        mf = QFormLayout(self.mv)
        mf.setContentsMargins(0, 0, 0, 0)
        names = [n for n, _ in GT.variables(t)] if t.kind == "multivariable" else []
        self.mv_boxes = {}
        for key, label, none in (("x", "X axis variable:", False), ("y", "Y axis variable:", False),
                                 ("color", "Color by:", True), ("size", "Symbol size (area) by:", True),
                                 ("lines", "Connecting lines (group) by:", True)):
            cb = QComboBox()
            if none:
                cb.addItem("(none)", "")
            for n in names:
                cb.addItem(n, n)
            if self.options.get(key):
                cb.setCurrentIndex(max(0, cb.findData(self.options[key])))
            elif not none and names:
                nums = [n for n, numeric in GT.variables(t) if numeric] or names
                cb.setCurrentIndex(cb.findData(nums[min(len(nums) - 1, 0 if key == "x" else 1)]))
            cb.currentIndexChanged.connect(self._changed)
            mf.addRow(label, cb)
            self.mv_boxes[key] = cb
        self.default = QCheckBox()
        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumHeight(380)
        self.preview.setObjectName("graphPreview")
        self.preview.setStyleSheet("QLabel#graphPreview { background: white; border-radius: 6px; }")
        top = QHBoxLayout()
        top.addStretch(1)
        top.addWidget(QLabel("Graph family:"))
        top.addWidget(self.family)
        top.addStretch(1)
        opts = QHBoxLayout()
        opts.addWidget(self.plot_label)
        opts.addWidget(self.plot)
        opts.addStretch(1)
        v = QVBoxLayout(self)
        v.addLayout(top)
        v.addWidget(self.tabs, 0, Qt.AlignHCenter)
        v.addWidget(self.types)
        v.addWidget(self.name)
        v.addWidget(self.prism_note)
        v.addLayout(opts)
        v.addWidget(self.surv)
        v.addWidget(self.mv)
        v.addWidget(self.default)
        v.addWidget(self.preview, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        v.addWidget(buttons)
        self.family.currentIndexChanged.connect(self._family_changed)
        self.tabs.currentChanged.connect(self._fill_types)
        self.types.currentRowChanged.connect(self._type_changed)
        self.plot.currentIndexChanged.connect(self._changed)
        for b in (self.fractions, self.percents):
            b.toggled.connect(self._changed)
        self._start = start
        self.family.setCurrentIndex(max(0, self.family.findData(start.family)))
        self._family_changed()

    # ---------------------------------------------------------------- state
    def _family_changed(self, *_a) -> None:
        fam = self.family.currentData()
        self.tabs.blockSignals(True)
        while self.tabs.count():
            self.tabs.removeTab(0)
        tabs = GT.tabs_for(fam)
        for name in tabs:
            if name:
                self.tabs.addTab(name)
        self.tabs.setVisible(any(tabs))
        want = self._start.tab if self._start.family == fam else tabs[0]
        self.tabs.setCurrentIndex(max(0, [x for x in tabs if x].index(want)) if want in tabs and want else 0)
        self.tabs.blockSignals(False)
        self._fill_types()

    def _tab(self) -> str:
        fam = self.family.currentData()
        tabs = [x for x in GT.tabs_for(fam) if x]
        return tabs[self.tabs.currentIndex()] if tabs and self.tabs.currentIndex() >= 0 else ""

    def _fill_types(self, *_a) -> None:
        fam, tab = self.family.currentData(), self._tab()
        self.types.blockSignals(True)
        self.types.clear()
        self._listed = [t for t in GT.types_for(fam) if t.tab == tab]
        for gt in self._listed:
            it = QListWidgetItem(type_icons.icon(gt.key), "")
            it.setToolTip(gt.label)
            it.setSizeHint(QSize(THUMB.width() + 14, THUMB.height() + 14))
            self.types.addItem(it)
        keys = [t.key for t in self._listed]
        self.types.setCurrentRow(keys.index(self._start.key) if self._start.key in keys else 0)
        self.types.blockSignals(False)
        self._type_changed()

    def chosen(self) -> GT.GraphType:
        r = self.types.currentRow()
        return self._listed[r] if 0 <= r < len(self._listed) else self._start

    def _type_changed(self, *_a) -> None:
        gt = self.chosen()
        self.name.setText(gt.label)
        self.prism_note.setText(GT.in_prism(gt, self.ng.table.kind))
        self.plot.blockSignals(True)
        self.plot.clear()
        for k, label in gt.plots:
            self.plot.addItem(label, k)
        keep = self.plot0 if gt.key == self._start.key else None
        self.plot.setCurrentIndex(max(0, self.plot.findData(keep)) if keep else 0)
        self.plot.blockSignals(False)
        self.plot.setVisible(bool(gt.plots))
        self.plot_label.setVisible(bool(gt.plots))
        self.surv.setVisible(gt.family == "survival")
        self.mv.setVisible(gt.family == "multivariable")
        self.mv_boxes["size"].setEnabled(gt.key == "mv_bubble")
        self.mv_boxes["color"].setEnabled(gt.key in ("mv_bubble", "mv_scatter"))
        self.mv_boxes["lines"].setEnabled(gt.key.startswith("mv_before_after"))
        cat = gt.key in GT.MV_AS_COLUMN  # X: a category there
        mf = self.mv.layout()
        mf.labelForField(self.mv_boxes["x"]).setText("X axis variable (categories):" if cat else "X axis variable:")
        self.default.setText(f"Make “{gt.label}” the default for {GT.FAMILY_NAMES[gt.family]} tables")
        self.default.setVisible(gt.family == self.ng.table.kind)
        self._changed()

    def result_options(self) -> dict:
        gt = self.chosen()
        out = {}
        if gt.family == "survival" and self.fractions.isChecked():
            out["scale"] = "fraction"
        if gt.family == "survival" and not self.err_none.isChecked():
            out["error"] = "se" if self.err_se.isChecked() else "ci"
        if gt.family == "multivariable":
            for k, cb in self.mv_boxes.items():
                if cb.currentData():
                    out[k] = cb.currentData()
        return out

    def choice(self) -> tuple[str, str | None, dict]:
        gt = self.chosen()
        return gt.key, (self.plot.currentData() if gt.plots else None), self.result_options()

    def _changed(self, *_a) -> None:
        key, plot, options = self.choice()
        ng = copy.copy(self.ng)
        ng.style, ng.error, ng.options = key, plot or "", options
        try:
            g = native.graph(self.doc.project, ng, self.doc.results, self.doc.source_of)
        except NotImplementedError as e:
            self.preview.setText(f"Cannot draw this yet: {e}")
            return
        lay = qt.layout(g)
        w, h = max(self.preview.width(), 400) - 20, max(self.preview.height(), 380) - 20
        k = min(w / lay.width, h / lay.height, 1.7)
        dpr = self.devicePixelRatioF()
        img: QImage = qt.to_image(g, k * dpr, lay=lay)
        img.setDevicePixelRatio(dpr)
        self.preview.setPixmap(QPixmap.fromImage(img))

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        if hasattr(self, "_listed"):
            self._changed()


def run_wizard(window, view, first: bool = False) -> bool:
    """Open the dialog for the Refract graph `view` shows; apply the choice
    (one undo step), and keep it as the default when asked."""
    d = GraphTypeDialog(window.doc, view.ng, window, first)
    if not window._exec(d):
        return False
    key, plot, options = d.choice()
    if d.default.isChecked() and d.default.isVisible():
        defaults = user_defaults()
        defaults[view.ng.table.kind] = {"style": key, "error": plot, "options": options}
        look.set_setting(DEFAULT_KEY, json.dumps(defaults))
    return window.doc.set_native_options(view.ng, style=key, error=plot or "", options=options)
