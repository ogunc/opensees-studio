"""View → Grid Line View: pick a grid line by its label and a window around it.

The list holds every line of every coordinate system ("Global: X A (6)"); the
window is how far either side of the line an object may sit and still be shown
(50 mm by default, in the model's length unit).
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from opensees_studio.core import Project
from opensees_studio.core.grid_view import (
    GridLineRef,
    default_window,
    grid_lines,
    objects_on_line,
)
from opensees_studio.core.units import labels_for
from opensees_studio.views.float_field import FloatField
from opensees_studio.views.screen_fit import FittedDialog


class GridLineViewDialog(FittedDialog):
    """Choose the grid line and the window either side of it."""

    def __init__(
        self,
        project: Project,
        *,
        current: str | None = None,
        window: float | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Grid Line View")
        self._project = project
        self._lines = grid_lines(project)
        root = QVBoxLayout(self)
        root.addWidget(
            QLabel(
                "Show only the joints and elements lying on one grid line (plane, ring or radial line)."
            )
        )
        form = QFormLayout()
        self.line_combo = QComboBox()
        for ref in self._lines:
            self.line_combo.addItem(ref.label, ref.label)
        if current is not None and (index := self.line_combo.findData(current)) >= 0:
            self.line_combo.setCurrentIndex(index)
        unit = labels_for(project.meta.units).length
        self.window_field = FloatField()
        self.window_field.setRange(0.0, 1e12)
        self.window_field.setValue(
            window if window is not None else default_window(project.meta.units)
        )
        form.addRow("Grid line:", self.line_combo)
        form.addRow(f"Window either side [{unit}]:", self.window_field)
        root.addLayout(form)
        self.count = QLabel()
        root.addWidget(self.count)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        root.addWidget(self.buttons)
        self.line_combo.currentIndexChanged.connect(self._update_count)
        self.window_field.valueChanged.connect(self._update_count)
        self._update_count()

    def line(self) -> GridLineRef | None:
        index = self.line_combo.currentIndex()
        return self._lines[index] if 0 <= index < len(self._lines) else None

    def tolerance(self) -> float:
        return float(self.window_field.value())

    def _update_count(self) -> None:
        ref = self.line()
        ok = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        if ref is None:
            self.count.setText("The model has no grid lines: define a grid first.")
            ok.setEnabled(False)
            return
        nodes, elements = objects_on_line(self._project, ref, self.tolerance())
        self.count.setText(f"{len(nodes)} joint(s) and {len(elements)} element(s) on this line.")
        ok.setEnabled(True)
