"""Vector icons for the ribbon, the tool palette and the snap bar.

The application ships no image assets, so every icon is drawn with ``QPainter``
at load time and cached. Keeping them in one module is what lets the ribbon, the
left-hand tool palette and the snap bar show the **same** glyph for the same
idea (a frame member, a shell, a midpoint snap).

Call :func:`icon_for` with a name from :data:`ICONS`; unknown names fall back to
a neutral dot so a caller can never end up with an empty button.
"""

from __future__ import annotations

from functools import cache

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap

#: Icon names → a short description (also used by tests and tooltips).
ICONS: dict[str, str] = {
    "select": "Select",
    "node": "Draw node",
    "frame": "Frame member",
    "truss": "Truss member",
    "shell": "Shell",
    "measure": "Measure distance",
    "midpoint": "Snap to midpoint",
    "perpendicular": "Snap perpendicular",
    "member": "Snap to member",
    "fixed": "Fixed restraint",
    "pinned": "Pinned restraint",
    "roller": "Roller restraint",
    "free": "Free joint",
    "file": "File",
    "edit": "Edit",
    "grid": "Grid",
    "load": "Load",
    "support": "Support",
    "run": "Run",
    "design": "Design",
    "result": "Result",
    "view": "View",
    "help": "Help",
    "material": "Material",
    "section": "Section",
    "time": "Time series",
    "pattern": "Load pattern",
    "joint": "Joint",
    "area": "Area load",
    "connection": "Connection",
    "calc": "Calculation",
    "more": "More",
    "menus": "Menus",
}

#: The size every icon is drawn at; Qt scales it down for the small buttons.
SIZE = 24

_INK = "#1f2937"
_ACCENT = "#1d4ed8"


def _pen(color: str, width: float = 1.8) -> QPen:
    pen = QPen(QColor(color))
    pen.setWidthF(width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return pen


def _draw(painter: QPainter, name: str, color: str) -> None:
    """Paint one glyph in a 24 x 24 box."""
    pen = _pen(color)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    s = float(SIZE)

    if name == "select":
        painter.drawPolygon(
            [QPointF(4, 3), QPointF(19, 12), QPointF(12, 14), QPointF(9, 21), QPointF(4, 3)]
        )
        return
    if name == "node":
        painter.setBrush(QColor(color))
        painter.drawEllipse(QPointF(s / 2, s / 2), 4.2, 4.2)
        return
    if name in {"frame", "member"}:
        painter.drawLine(QPointF(4, 20), QPointF(20, 5))
        painter.drawLine(QPointF(4, 5), QPointF(20, 20))
        return
    if name == "truss":
        painter.drawLine(QPointF(4, 20), QPointF(12, 4))
        painter.drawLine(QPointF(12, 4), QPointF(20, 20))
        painter.drawLine(QPointF(4, 20), QPointF(20, 20))
        return
    if name == "shell":
        painter.drawPolygon([QPointF(5, 8), QPointF(19, 6), QPointF(19, 18), QPointF(5, 20)])
        return
    if name == "measure":
        painter.drawLine(QPointF(4, 18), QPointF(20, 6))
        painter.drawLine(QPointF(4, 13), QPointF(4, 18))
        painter.drawLine(QPointF(9, 16), QPointF(9, 11))
        painter.drawLine(QPointF(14, 11), QPointF(14, 6))
        return
    if name == "midpoint":
        painter.drawLine(QPointF(4, 20), QPointF(20, 5))
        painter.setBrush(QColor("#f59e0b"))
        painter.drawEllipse(QPointF(12, 12), 3, 3)
        return
    if name == "perpendicular":
        painter.drawLine(QPointF(4, 20), QPointF(20, 20))
        painter.drawLine(QPointF(12, 20), QPointF(12, 5))
        painter.drawLine(QPointF(12, 16), QPointF(17, 16))
        painter.drawLine(QPointF(17, 16), QPointF(17, 20))
        return
    if name == "fixed":
        painter.drawLine(QPointF(12, 4), QPointF(12, 16))
        painter.drawLine(QPointF(4, 16), QPointF(20, 16))
        for x in (6, 10, 14, 18):
            painter.drawLine(QPointF(x, 16), QPointF(x - 2, 20))
        return
    if name == "pinned":
        painter.drawLine(QPointF(12, 4), QPointF(12, 15))
        painter.drawLine(QPointF(4, 20), QPointF(20, 20))
        painter.drawPolygon([QPointF(12, 15), QPointF(7, 20), QPointF(17, 20)])
        return
    if name == "roller":
        painter.drawLine(QPointF(12, 4), QPointF(12, 14))
        painter.drawLine(QPointF(5, 15), QPointF(19, 15))
        for x in (8, 12, 16):
            painter.drawEllipse(QPointF(x, 18), 1.8, 1.8)
        return
    if name == "free":
        painter.drawLine(QPointF(4, 20), QPointF(20, 5))
        painter.drawLine(QPointF(4, 20), QPointF(20, 20))
        return
    if name == "grid":
        for i in range(1, 4):
            painter.drawLine(QPointF(4 + i * 5, 4), QPointF(4 + i * 5, 20))
            painter.drawLine(QPointF(4, 4 + i * 5), QPointF(20, 4 + i * 5))
        return
    if name == "load":
        painter.drawLine(QPointF(12, 4), QPointF(12, 18))
        painter.drawLine(QPointF(7, 13), QPointF(12, 18))
        painter.drawLine(QPointF(17, 13), QPointF(12, 18))
        return
    if name == "support":
        painter.drawLine(QPointF(4, 18), QPointF(20, 18))
        painter.drawLine(QPointF(6, 18), QPointF(12, 6))
        painter.drawLine(QPointF(18, 18), QPointF(12, 6))
        return
    if name == "run":
        painter.drawPolygon([QPointF(8, 4), QPointF(20, 12), QPointF(8, 20)])
        return
    if name == "design":
        painter.drawLine(QPointF(4, 21), QPointF(20, 21))
        painter.drawLine(QPointF(7, 21), QPointF(7, 11))
        painter.drawLine(QPointF(17, 21), QPointF(17, 6))
        painter.drawLine(QPointF(7, 11), QPointF(17, 6))
        return
    if name == "result":
        painter.drawLine(QPointF(4, 5), QPointF(4, 20))
        painter.drawLine(QPointF(4, 20), QPointF(21, 20))
        painter.drawLine(QPointF(8, 20), QPointF(8, 14))
        painter.drawLine(QPointF(13, 20), QPointF(13, 10))
        painter.drawLine(QPointF(18, 20), QPointF(18, 6))
        return
    if name == "view":
        painter.drawEllipse(QPointF(12, 12), 3.2, 3.2)
        painter.drawArc(QRectF(2, 6, 20, 12), 20 * 16, 140 * 16)
        return
    if name == "help":
        painter.drawEllipse(QPointF(12, 12), 8, 8)
        painter.drawLine(QPointF(9, 9), QPointF(12, 12))
        painter.drawLine(QPointF(12, 12), QPointF(12, 16))
        painter.drawPoint(QPointF(12, 18))
        return
    if name == "material":
        painter.drawEllipse(QPointF(12, 12), 7, 7)
        painter.drawLine(QPointF(12, 5), QPointF(12, 19))
        return
    if name == "section":
        painter.drawRect(QRectF(5, 8, 14, 8))
        painter.drawLine(QPointF(9, 8), QPointF(9, 16))
        return
    if name == "time":
        painter.drawLine(QPointF(3, 14), QPointF(7, 8))
        painter.drawLine(QPointF(7, 8), QPointF(11, 16))
        painter.drawLine(QPointF(11, 16), QPointF(15, 6))
        painter.drawLine(QPointF(15, 6), QPointF(20, 13))
        return
    if name == "pattern":
        painter.drawRect(QRectF(5, 5, 14, 14))
        painter.drawLine(QPointF(5, 10), QPointF(19, 10))
        return
    if name == "joint":
        painter.drawLine(QPointF(3, 12), QPointF(21, 12))
        painter.drawEllipse(QPointF(12, 12), 3.4, 3.4)
        return
    if name == "area":
        painter.drawPolygon([QPointF(4, 18), QPointF(12, 14), QPointF(20, 18), QPointF(12, 21)])
        painter.drawLine(QPointF(12, 6), QPointF(12, 14))
        return
    if name == "connection":
        painter.drawRect(QRectF(4, 8, 7, 9))
        painter.drawRect(QRectF(13, 8, 7, 9))
        painter.drawLine(QPointF(11, 12), QPointF(13, 12))
        return
    if name == "calc":
        painter.drawRect(QRectF(6, 3, 12, 18))
        painter.drawLine(QPointF(9, 8), QPointF(15, 8))
        painter.drawLine(QPointF(9, 12), QPointF(15, 12))
        painter.drawLine(QPointF(9, 16), QPointF(13, 16))
        return
    if name in {"file", "edit", "more", "menus"}:
        painter.drawRect(QRectF(5, 3, 14, 18))
        if name == "edit":
            painter.drawLine(QPointF(8, 14), QPointF(16, 6))
        elif name == "more":
            for y in (8, 12, 16):
                painter.drawPoint(QPointF(12, y))
        elif name == "menus":
            for y in (7, 12, 17):
                painter.drawLine(QPointF(8, y), QPointF(16, y))
        return

    # Unknown name: a neutral dot, never an empty button.
    painter.setBrush(QColor(MUTED))
    painter.drawEllipse(QPointF(12, 12), 3, 3)


MUTED = "#6b7280"


@cache
def icon_for(name: str, color: str = _INK) -> QIcon:
    """The cached icon for ``name`` (a neutral dot when the name is unknown)."""
    pixmap = QPixmap(SIZE, SIZE)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    _draw(painter, name, color)
    painter.end()
    return QIcon(pixmap)


def icon_names() -> list[str]:
    """Every name :func:`icon_for` knows."""
    return sorted(ICONS)
