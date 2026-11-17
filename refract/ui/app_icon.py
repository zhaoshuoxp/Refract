"""Refract's application icon, drawn in code (PLAN §1.4: our own artwork).

A rounded square in deep blue, lit from the top, with a light ray that bends
as it enters a glass slab, followed by three rising coloured bars:
refraction turned into a bar chart (design "D", chosen 2026-11-17).
Two variants follow the system theme: LIGHT (a pale tile, a dark ray) and
DARK (the deep blue tile, a white ray). tools/packaging/make_icon.py renders
them into an asset catalog (macOS switches the Dock and Finder icon with the
theme), .icns and .ico files; icon() gives the window icon of the theme in use.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QIcon,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)

SIZES = (16, 32, 64, 128, 256, 512, 1024)
LIGHT = {"tile": ("#fbfcff", "#d9e3f4"), "top": 150, "slab": ((40, 80, 170, 40), (40, 80, 170, 14)),
         "edge": (30, 70, 150, 120), "ray": "#1d3a78", "bars": ("#f5a524", "#f0564a", "#2a9fe8")}
DARK = {"tile": ("#24458a", "#0c1838"), "top": 40, "slab": ((255, 255, 255, 70), (150, 200, 255, 25)),
        "edge": (255, 255, 255, 110), "ray": "#ffffff", "bars": ("#ffb547", "#ff6f61", "#7ad3ff")}
BARS = DARK["bars"]  # amber, coral, sky


def paint(p: QPainter, s: float, dark: bool = False, bleed: bool = False) -> None:
    """The icon in a square of side `s` (macOS keeps ~10% margin around the tile), light or dark;
    bleed: the artwork over the whole square, unmasked (an Icon Composer layer: macOS masks it)."""
    pal = DARK if dark else LIGHT
    p.setRenderHint(QPainter.Antialiasing)
    m = 0.0 if bleed else s * 0.098
    tile = QRectF(m, m, s - 2 * m, s - 2 * m)
    path = QPainterPath()
    path.addRoundedRect(tile, 0.0 if bleed else tile.width() * 0.225, 0.0 if bleed else tile.width() * 0.225)
    g = QLinearGradient(tile.topLeft(), tile.bottomRight())
    g.setColorAt(0, QColor(pal["tile"][0]))
    g.setColorAt(1, QColor(pal["tile"][1]))
    p.fillPath(path, g)
    hl = QLinearGradient(tile.topLeft(), QPointF(tile.left(), tile.top() + tile.height() * 0.5))
    hl.setColorAt(0, QColor(255, 255, 255, pal["top"]))  # a soft top light
    hl.setColorAt(1, QColor(255, 255, 255, 0))
    p.fillPath(path, hl)
    p.setClipPath(path)
    w, x0, y0 = tile.width(), tile.left(), tile.top()

    def at(fx: float, fy: float) -> QPointF:
        return QPointF(x0 + fx * w, y0 + fy * w)

    # the glass slab: a pale rounded block with a thin edge
    slab = QPainterPath()
    slab.addRoundedRect(QRectF(at(0.28, 0.18), at(0.50, 0.84)), s * 0.03, s * 0.03)
    sg = QLinearGradient(at(0.28, 0), at(0.50, 0))
    sg.setColorAt(0, QColor(*pal["slab"][0]))
    sg.setColorAt(1, QColor(*pal["slab"][1]))
    p.fillPath(slab, sg)
    p.setPen(QPen(QColor(*pal["edge"]), max(0.5, s * 0.006)))
    p.drawPath(slab)
    # the ray: steep in the air, shallower inside the glass
    p.setPen(QPen(QColor(pal["ray"]), max(1.0, s * 0.032), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    ray = QPainterPath(at(0.06, 0.24))
    ray.lineTo(at(0.28, 0.46))
    ray.lineTo(at(0.50, 0.56))
    p.drawPath(ray)
    # leaving the glass: three rising bars, each lit from above
    p.setPen(Qt.NoPen)
    for k, (h, c) in enumerate(zip((0.22, 0.38, 0.56), pal["bars"], strict=True)):
        left = 0.57 + k * 0.125
        rect = QRectF(at(left, 0.82 - h), at(left + 0.095, 0.82))
        bg = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        bg.setColorAt(0, QColor(c))
        bg.setColorAt(1, QColor(c).darker(125))
        bar = QPainterPath()
        bar.addRoundedRect(rect, s * 0.018, s * 0.018)
        p.fillPath(bar, bg)
    p.setClipping(False)


def image(size: int, dark: bool = False, bleed: bool = False) -> QImage:
    img = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    paint(p, size, dark, bleed)
    p.end()
    return img


def icon(dark: bool | None = None) -> QIcon:
    """The window icon; dark None: the variant of the theme in use (refract.ui.look.is_dark)."""
    if dark is None:
        from . import look

        dark = look.is_dark()
    ic = QIcon()
    for n in SIZES[:5]:
        ic.addPixmap(QPixmap.fromImage(image(n, dark)))
    return ic
