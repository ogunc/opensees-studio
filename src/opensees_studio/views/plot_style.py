"""One readable style for every pyqtgraph plot.

Axes show real values: pyqtgraph's automatic SI prefix (a "x0.001" or
"(k)" multiplier folded into the axis label) is off everywhere. Tick
labels and axis labels use the application font size, and labels, ticks,
grid and legend text use light colours with enough contrast on the dark
plot background.
"""

from __future__ import annotations

from typing import Any

import pyqtgraph as pg
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

PLOT_BACKGROUND = "#1e1e1e"
AXIS_TEXT = "#e8e8e8"
AXIS_LINE = "#b0b0b0"
GRID_ALPHA = 0.35
TARGET_PEN = "#ffffff"
"""Target and reference curves (dashed white stays readable over every record colour)."""

_AXES = ("left", "bottom", "right", "top")


def plot_font() -> QFont:
    """The application font, used for ticks, axis labels and legends."""
    app = QApplication.instance()
    return QFont(app.font()) if app is not None else QFont()


def _font_size_css(font: QFont) -> str:
    size = font.pointSizeF()
    return f"{size:g}pt" if size > 0 else f"{font.pixelSize()}px"


def style_plot(plot: pg.PlotWidget) -> pg.PlotWidget:
    """Apply the readable style to ``plot`` (background, axes, fonts, grid)."""
    font = plot_font()
    plot.setBackground(PLOT_BACKGROUND)
    for name in _AXES:
        axis = plot.getAxis(name)
        axis.enableAutoSIPrefix(False)
        axis.setTickFont(font)
        axis.setPen(pg.mkPen(AXIS_LINE))
        axis.setTextPen(pg.mkPen(AXIS_TEXT))
        axis.labelStyle = {"color": AXIS_TEXT, "font-size": _font_size_css(font)}
        axis.label.setFont(font)
    plot.showGrid(x=True, y=True, alpha=GRID_ALPHA)
    return plot


def readable_plot() -> pg.PlotWidget:
    """A new :class:`pyqtgraph.PlotWidget` in the readable style."""
    return style_plot(pg.PlotWidget())


def axis_label(text: str, units: str | None = None) -> str:
    """``"text [units]"``: units are written out, never turned into an SI prefix."""
    return f"{text} [{units}]" if units else text


def add_legend(plot: pg.PlotWidget, offset: tuple[int, int] = (8, 8)) -> Any:
    """A legend in the plot's text colour and the application font size."""
    return plot.addLegend(
        offset=offset,
        labelTextColor=AXIS_TEXT,
        labelTextSize=_font_size_css(plot_font()),
    )
