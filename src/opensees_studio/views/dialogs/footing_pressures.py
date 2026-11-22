"""Design → Footing Pressure Plan: the soil pressure under every footing, in plan.

Every saved footing (isolated and combined) is drawn to scale in the global X-Y
plane, filled with the service pressure of the alternative with the largest
q,max on one colour scale shared by all of them, with the pedestals or columns
on top and each footing's q,max and load set beside it. The colour bar is in
the project's stress unit and runs from the lowest to the highest pressure of
all footings (from zero when they are nearly uniform).
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QRectF
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from opensees_studio.core.help import TOPIC_PROPERTY
from opensees_studio.core.units import labels_for
from opensees_studio.services.footings import FootingReport, pressure_grid
from opensees_studio.views.dialogs.design_basis import _ok_cancel
from opensees_studio.views.screen_fit import FittedDialog

COLORMAP = "turbo"


class FootingPressuresDialog(FittedDialog):
    """The pressure under every footing on a shared colour scale."""

    def __init__(
        self, project: Any, reports: list[FootingReport], parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Footing Pressure Plan")
        self.setProperty(TOPIC_PROPERTY, "design.footing_pressures")
        self.resize(900, 700)
        units = project.meta.units
        lab = labels_for(units)
        layout = QVBoxLayout(self)
        self._plot = pg.PlotWidget()
        self._plot.setAspectLocked(True)
        self._plot.showGrid(x=True, y=True, alpha=0.2)
        self._plot.setLabel("bottom", f"X [{lab.length}]")
        self._plot.setLabel("left", f"Y [{lab.length}]")
        layout.addWidget(self._plot, 1)

        grids = [(r, pressure_grid(r, units)) for r in reports]
        top = max((float(g[2].max()) for _r, g in grids if g is not None), default=0.0)
        low = min((float(g[2].min()) for _r, g in grids if g is not None), default=0.0)
        if top - low < 0.05 * top:
            low = 0.0  # nearly uniform everywhere: scale from zero so the colour reads as a level
        self.q_top, self.q_low = top, low
        cmap = pg.colormap.get(COLORMAP)
        self.images: list[pg.ImageItem] = []
        for report, grid in grids:
            cx, cy, length, width = report.plan
            rect = QRectF(cx - length / 2.0, cy - width / 2.0, length, width)
            if grid is not None and top > 0.0:
                _xs, _ys, q = grid
                image = pg.ImageItem(np.asarray(q, dtype=float), axisOrder="col-major")
                image.setLookupTable(cmap.getLookupTable(nPts=256))
                image.setLevels((low, top))
                image.setRect(rect)
                self._plot.addItem(image)
                self.images.append(image)
            outline = pg.PlotDataItem(
                [rect.left(), rect.right(), rect.right(), rect.left(), rect.left()],
                [rect.top(), rect.top(), rect.bottom(), rect.bottom(), rect.top()],
                pen=pg.mkPen("k", width=1.5),
            )
            self._plot.addItem(outline)
            for x, y, c_x, c_y in report.footprints:
                self._plot.addItem(
                    pg.PlotDataItem(
                        [x - c_x / 2, x + c_x / 2, x + c_x / 2, x - c_x / 2, x - c_x / 2],
                        [y - c_y / 2, y - c_y / 2, y + c_y / 2, y + c_y / 2, y - c_y / 2],
                        pen=pg.mkPen("w", width=1.2),
                        fillLevel=None,
                    )
                )
            text = report.label + (
                f"\nq,max = {report.q_max:.4g} {lab.stress}" if report.pressure is not None else
                "\nno service pressure"
            )  # fmt: skip
            label = pg.TextItem(text, color=(240, 240, 240), anchor=(0.5, 0.0))
            label.setPos(cx, cy - width / 2.0)
            self._plot.addItem(label)
        if top > 0.0:
            bar = pg.ColorBarItem(
                values=(low, top), colorMap=cmap, label=f"q [{lab.stress}]", interactive=False
            )
            bar.setImageItem(self.images, insert_in=self._plot.getPlotItem())
        summary = QLabel(
            f"{len(reports)} footing(s); largest service pressure {top:.4g} {lab.stress}. "
            "Each footing shows the service alternative with its largest pressure."
            if reports
            else "No footing: define them in Design → Footings first."
        )
        summary.setWordWrap(True)
        layout.addWidget(summary)
        layout.addWidget(_ok_cancel(self))
