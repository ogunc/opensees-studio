"""Coord System Location and Orientation form — SAP2000 parity.

Opened from the Define Grid System Data form via "Locate System Origin".
Edits only the origin (X, Y, Z) and Euler rotation (about X, Y, Z) of a
coordinate system, leaving its grid data unchanged.
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
    QVBoxLayout,
    QWidget,
)


class CoordSystemLocationOrientationDialog(QDialog):
    """Just origin + XYZ Euler rotation in degrees."""

    def __init__(
        self,
        origin: tuple[float, float, float] = (0.0, 0.0, 0.0),
        rotation_deg: tuple[float, float, float] = (0.0, 0.0, 0.0),
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Coord System Location and Orientation")
        self._build_ui()
        self._set_values(origin, rotation_deg)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.addWidget(QLabel(
            "Enter the system's origin and orientation relative to <b>Global</b>. "
            "Rotations are XYZ Euler angles in degrees."
        ))

        origin_box = QGroupBox("Origin (world units)")
        of = QFormLayout(origin_box)
        self._ox = self._spin(); of.addRow("X:", self._ox)
        self._oy = self._spin(); of.addRow("Y:", self._oy)
        self._oz = self._spin(); of.addRow("Z:", self._oz)
        root.addWidget(origin_box)

        rot_box = QGroupBox("Rotation about axes (degrees)")
        rf = QFormLayout(rot_box)
        self._rx = self._rot_spin(); rf.addRow("about X:", self._rx)
        self._ry = self._rot_spin(); rf.addRow("about Y:", self._ry)
        self._rz = self._rot_spin(); rf.addRow("about Z:", self._rz)
        root.addWidget(rot_box)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    @staticmethod
    def _spin() -> QDoubleSpinBox:
        sb = QDoubleSpinBox()
        sb.setRange(-1e9, 1e9)
        sb.setDecimals(6)
        sb.setSingleStep(0.5)
        return sb

    @staticmethod
    def _rot_spin() -> QDoubleSpinBox:
        sb = QDoubleSpinBox()
        sb.setRange(-360.0, 360.0)
        sb.setDecimals(3)
        sb.setSingleStep(1.0)
        return sb

    def _set_values(
        self,
        origin: tuple[float, float, float],
        rotation_deg: tuple[float, float, float],
    ) -> None:
        self._ox.setValue(origin[0])
        self._oy.setValue(origin[1])
        self._oz.setValue(origin[2])
        self._rx.setValue(rotation_deg[0])
        self._ry.setValue(rotation_deg[1])
        self._rz.setValue(rotation_deg[2])

    def location(self) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
        """Return ((origin_x, y, z), (rot_x, y, z))."""
        return (
            (self._ox.value(), self._oy.value(), self._oz.value()),
            (self._rx.value(), self._ry.value(), self._rz.value()),
        )
