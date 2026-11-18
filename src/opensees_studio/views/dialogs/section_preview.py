"""A cross-section drawing for the section wizards: outlines, holes, bars, centroid.

Local z runs to the right and local y up, so a beam section reads the way it is
drawn on paper (depth up). The aspect ratio is locked: a circle is round.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QPolygonF
from PySide6.QtWidgets import QGraphicsEllipseItem, QGraphicsPolygonItem

from opensees_studio.core.sections.geometry import Point, Region, outline
from opensees_studio.views.plot_style import style_plot

SOLID_FILL = (150, 150, 150, 170)
HOLE_FILL = (30, 30, 30, 255)
EDGE = "#e8e8e8"
BAR_FILL = "#e15759"
CORE_PEN = "#f0ad4e"
SELECTED_PEN = "#5bc0de"


def _polygon(x: np.ndarray, y: np.ndarray, pen: Any, brush: Any) -> QGraphicsPolygonItem:
    """A filled polygon in data coordinates (pyqtgraph curves fill only to a level)."""
    item = QGraphicsPolygonItem(
        QPolygonF([QPointF(float(a), float(b)) for a, b in zip(x, y, strict=True)])
    )
    # Width 0 is a one-pixel hairline. Any other width would be taken in model
    # units by the item's bounding box and throw the auto-range off.
    pen.setWidthF(0.0)
    item.setPen(pen)
    item.setBrush(brush)
    return item


def _closed(points: Sequence[Point]) -> tuple[np.ndarray, np.ndarray]:
    """Plot coordinates (z across, y up) of a closed outline."""
    ys = [p[0] for p in points] + [points[0][0]]
    zs = [p[1] for p in points] + [points[0][1]]
    return np.asarray(zs, dtype=float), np.asarray(ys, dtype=float)


class SectionPreview(pg.PlotWidget):  # type: ignore[misc]
    """The drawing; call :meth:`clear` then the ``draw_*`` methods."""

    def __init__(self) -> None:
        super().__init__()
        style_plot(self)
        self.setAspectLocked(True)
        self.setLabel("bottom", "z")
        self.setLabel("left", "y")
        self.setMinimumSize(320, 320)

    def draw_regions(self, regions: Sequence[Region], *, selected: int | None = None) -> None:
        """Solids first, then holes on top, so a hole reads as empty."""
        order = sorted(range(len(regions)), key=lambda k: regions[k].hole)
        for k in order:
            region = regions[k]
            x, y = _closed(outline(region))
            fill = HOLE_FILL if region.hole else SOLID_FILL
            self.addItem(_polygon(x, y, pg.mkPen(EDGE), pg.mkBrush(*fill)))
        if selected is not None and 0 <= selected < len(regions):
            x, y = _closed(outline(regions[selected]))
            self.addItem(pg.PlotCurveItem(x, y, pen=pg.mkPen(SELECTED_PEN, width=3)))

    def draw_outline(self, points: Sequence[Point], *, dashed: bool = True) -> None:
        x, y = _closed(points)
        style = Qt.PenStyle.DashLine if dashed else Qt.PenStyle.SolidLine
        self.addItem(pg.PlotCurveItem(x, y, pen=pg.mkPen(CORE_PEN, width=1, style=style)))

    def draw_bars(self, centres: Sequence[Point], diameter: float) -> None:
        """Bars at their true size (``diameter`` in model units)."""
        r = diameter / 2.0
        pen = pg.mkPen("#ffffff")
        pen.setWidthF(0.0)
        for y, z in centres:
            item = QGraphicsEllipseItem(z - r, y - r, 2 * r, 2 * r)
            item.setPen(pen)
            item.setBrush(pg.mkBrush(BAR_FILL))
            self.addItem(item)

    def draw_centroid(self, y: float, z: float) -> None:
        self.plot(
            [z],
            [y],
            pen=None,
            symbol="+",
            symbolSize=16,
            symbolBrush=None,
            symbolPen=pg.mkPen("#ff4040", width=2),
        )

    def fit(self) -> None:
        """Frame everything drawn."""
        self.getViewBox().autoRange(padding=0.12)

    def resizeEvent(self, event: Any) -> None:
        """Keep the section framed when the dialog opens or is resized."""
        super().resizeEvent(event)
        if getattr(self, "plotItem", None) is not None:
            self.fit()

    def draw_points(self, points: Sequence[Point]) -> None:
        """Vertices of a polygon being entered."""
        if not points:
            return
        self.plot(
            [p[1] for p in points],
            [p[0] for p in points],
            pen=pg.mkPen(SELECTED_PEN, style=Qt.PenStyle.DotLine),
            symbol="o",
            symbolSize=6,
            symbolBrush=SELECTED_PEN,
        )
