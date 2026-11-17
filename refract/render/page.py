"""A page of placed graphs (layouts, docs/ui-spec.md §3.5): each graph drawn
by refract.render.qt at its own scale, its page's top-left corner at (x, y).
Lengths in points; exported like single graphs (PDF, SVG, PNG)."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from . import qt
from .model import Graph
from .style import DEFAULT, Style


@dataclass
class Placement:
    graph: Graph
    x: float  # page points: where the graph's own page starts
    y: float
    k: float = 1.0  # scale of the graph
    lay: qt.Layout | None = None
    key: object = None  # what the placement stands for (the layout item it came from)

    def __post_init__(self):
        if self.lay is None:
            self.lay = qt.layout(self.graph)

    @property
    def box(self) -> tuple[float, float, float, float]:
        return self.x, self.y, self.x + self.lay.width * self.k, self.y + self.lay.height * self.k


@dataclass
class Page:
    width: float
    height: float
    items: list[Placement] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)  # objects that could not be drawn


def fit(g: Graph, x: float, y: float, w: float, h: float, key=None) -> Placement:
    """The graph scaled to fit the box (w x h), centred in it."""
    lay = qt.layout(g)
    k = min(w / lay.width, h / lay.height) if lay.width and lay.height else 1.0
    return Placement(g, x + (w - lay.width * k) / 2, y + (h - lay.height * k) / 2, k, lay, key)


def draw(p, page: Page, st: Style = DEFAULT) -> None:
    for it in page.items:
        p.save()
        p.translate(it.x, it.y)
        p.scale(it.k, it.k)
        qt.draw(p, it.graph, it.lay, st)
        p.restore()


def item_at(page: Page, x: float, y: float) -> int | None:
    """The topmost placement whose box holds the page point."""
    for i in range(len(page.items) - 1, -1, -1):
        x0, y0, x1, y1 = page.items[i].box
        if x0 <= x <= x1 and y0 <= y <= y1:
            return i
    return None


def to_image(page: Page, k: float, st: Style = DEFAULT):
    from PySide6.QtGui import QColor, QImage, QPainter

    qt.ensure_app()
    img = QImage(max(1, math.ceil(page.width * k)), max(1, math.ceil(page.height * k)), QImage.Format_ARGB32)
    img.setDotsPerMeterX(round(72 / 0.0254))
    img.setDotsPerMeterY(round(72 / 0.0254))
    img.fill(QColor(255, 255, 255))
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.TextAntialiasing)
    p.scale(k, k)
    draw(p, page, st)
    p.end()
    return img


def to_png(page: Page, path: str, dpi: float = 300) -> None:
    img = to_image(page, dpi / 72)
    img.setDotsPerMeterX(round(dpi / 0.0254))
    img.setDotsPerMeterY(round(dpi / 0.0254))
    if not img.save(path):
        raise OSError(f"cannot write {path}")


def to_pdf(page: Page, path: str) -> None:
    from PySide6.QtCore import QMarginsF, QSizeF
    from PySide6.QtGui import QPageLayout, QPageSize, QPainter, QPdfWriter

    qt.ensure_app()
    w = QPdfWriter(path)
    w.setResolution(72)
    w.setPageSize(QPageSize(QSizeF(page.width, page.height), QPageSize.Point))
    w.setPageMargins(QMarginsF(0, 0, 0, 0), QPageLayout.Point)
    w.setCreator("Refract")
    p = QPainter(w)
    p.setRenderHint(QPainter.Antialiasing)
    draw(p, page)
    p.end()


def to_svg(page: Page, path: str) -> None:
    from PySide6.QtCore import QRectF, QSize
    from PySide6.QtGui import QPainter
    from PySide6.QtSvg import QSvgGenerator

    qt.ensure_app()
    gen = QSvgGenerator()
    gen.setFileName(path)
    gen.setResolution(72)
    gen.setSize(QSize(math.ceil(page.width), math.ceil(page.height)))
    gen.setViewBox(QRectF(0, 0, page.width, page.height))
    p = QPainter(gen)
    p.setRenderHint(QPainter.Antialiasing)
    draw(p, page)
    p.end()


def export(page: Page, path: str) -> None:
    low = path.lower()
    if low.endswith(".pdf"):
        to_pdf(page, path)
    elif low.endswith(".svg"):
        to_svg(page, path)
    else:
        to_png(page, path)


def native_page(nl, graph_of) -> Page:
    """A Refract layout (refract.model.document.NativeLayout) as a page:
    graph_of(ref) gives the Graph of a layout item's reference, or None."""
    pg = Page(nl.width, nl.height)
    for i, it in enumerate(nl.items):
        try:
            g = graph_of(it.graph)
        except NotImplementedError as e:
            pg.notes.append(f"item {i + 1}: {e}")
            continue
        if g is None:
            pg.notes.append(f"item {i + 1}: its graph is gone")
            continue
        pg.items.append(fit(g, it.x, it.y, it.w, it.h, key=i))
    return pg


def grid(n: int, width: float, height: float, cols: int | None = None, margin: float = 36.0,
         gap: float = 18.0) -> list[tuple[float, float, float, float]]:
    """Boxes (x, y, w, h) for n graphs in rows of `cols` (default: about square)."""
    if n <= 0:
        return []
    cols = cols or max(1, math.ceil(math.sqrt(n)))
    rows = math.ceil(n / cols)
    w = (width - 2 * margin - (cols - 1) * gap) / cols
    h = min(w * 0.8, (height - 2 * margin - (rows - 1) * gap) / rows)
    return [(margin + (i % cols) * (w + gap), margin + (i // cols) * (h + gap), w, h) for i in range(n)]
