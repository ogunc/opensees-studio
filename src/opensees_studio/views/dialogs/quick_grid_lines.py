"""Quick Grid Lines form — SAP2000's fast grid generator.

Asks for the number of grid lines, equal spacing, and the first line's
coordinate along each axis. On accept, returns three flat ordinate
lists that the caller converts into :class:`GridLine` records.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)


class QuickGridLinesDialog(QDialog):
    """Three parallel (n, spacing, first_coord) inputs — one per axis."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Quick Grid Lines")
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.addWidget(QLabel(
            "<b>Quick-define a regular (Cartesian) grid.</b><br>"
            "Each axis: number of lines, equal spacing, first line coordinate."
        ))

        self._x_n, self._x_s, self._x_f = self._axis_group("X Grid Data", root)
        self._y_n, self._y_s, self._y_f = self._axis_group("Y Grid Data", root)
        self._z_n, self._z_s, self._z_f = self._axis_group("Z Grid Data", root)

        # Sensible defaults.
        self._x_n.setValue(3); self._x_s.setValue(6.0); self._x_f.setValue(0.0)
        self._y_n.setValue(3); self._y_s.setValue(6.0); self._y_f.setValue(0.0)
        self._z_n.setValue(2); self._z_s.setValue(3.0); self._z_f.setValue(0.0)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _axis_group(
        self, title: str, parent_layout: QVBoxLayout,
    ) -> tuple[QSpinBox, QDoubleSpinBox, QDoubleSpinBox]:
        box = QGroupBox(title)
        row = QHBoxLayout(box)

        n = QSpinBox(); n.setRange(0, 200); n.setValue(3)
        s = QDoubleSpinBox(); s.setRange(0.0, 1e6); s.setDecimals(4)
        s.setSingleStep(0.5); s.setValue(1.0)
        f = QDoubleSpinBox(); f.setRange(-1e6, 1e6); f.setDecimals(4)
        f.setSingleStep(0.5); f.setValue(0.0)

        row.addWidget(QLabel("Number of lines:"))
        row.addWidget(n)
        row.addWidget(QLabel("Spacing:"))
        row.addWidget(s)
        row.addWidget(QLabel("First coord:"))
        row.addWidget(f)
        parent_layout.addWidget(box)
        return n, s, f

    def ordinates(self) -> tuple[list[float], list[float], list[float]]:
        """Return (xs, ys, zs) — flat lists of ordinate values."""
        def axis(n: QSpinBox, s: QDoubleSpinBox, f: QDoubleSpinBox) -> list[float]:
            return [f.value() + i * s.value() for i in range(n.value())]
        return (
            axis(self._x_n, self._x_s, self._x_f),
            axis(self._y_n, self._y_s, self._y_f),
            axis(self._z_n, self._z_s, self._z_f),
        )
