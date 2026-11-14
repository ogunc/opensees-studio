"""Assign Frame Point Load dialog — a concentrated load inside selected frame elements."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from opensees_studio.views.float_field import FloatField
from opensees_studio.views.screen_fit import FittedDialog

RELATIVE = "relative"
ABSOLUTE = "absolute"


class AssignPointElementLoadDialog(FittedDialog):
    """Modal dialog for a point load (Px, Py, Pz) at a distance along each element.

    Components are in the **element local frame** (local x / y / z axes). The
    distance is measured from end i, either as a fraction of the length
    (``RELATIVE``, 0..1) or in length units (``ABSOLUTE``).
    """

    def __init__(self, n_selected: int, ndm: int = 3, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Assign Frame Point Load")
        self._ndm = ndm
        self._build_ui(n_selected)

    def _build_ui(self, n_selected: int) -> None:
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"Apply to <b>{n_selected}</b> selected frame element(s)."))

        self._local = QCheckBox("Use local axes (Px, Py, Pz)")
        self._local.setToolTip(
            "Off: enter a global Fx / Fy / Fz vector; every member converts it to its "
            "own axes. On: enter the force directly in the element's local frame."
        )
        layout.addWidget(self._local)

        form = QFormLayout()
        self._fields: dict[str, FloatField] = {}
        for label in ("Px", "Py", "Pz"):
            field = FloatField()
            field.setRange(-1e12, 1e12)
            field.setSingleStep(1.0)
            field.setValue(0.0)
            self._fields[label] = field
            form.addRow(f"{label}:", field)

        self._mode = QComboBox()
        self._mode.addItem("Relative distance (x/L)", RELATIVE)
        self._mode.addItem("Absolute distance", ABSOLUTE)
        self._mode.currentIndexChanged.connect(self._on_mode_changed)
        form.addRow("Measured as:", self._mode)

        self._distance = FloatField()
        self._distance.setRange(0.0, 1.0)
        self._distance.setSingleStep(0.1)
        self._distance.setValue(0.5)
        self._distance.setToolTip("Distance from end i of each element")
        form.addRow("Distance from end i:", self._distance)
        layout.addLayout(form)

        self._note = QLabel()
        self._note.setWordWrap(True)
        layout.addWidget(self._note)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._local.toggled.connect(self._sync_mode)
        self._sync_mode()

    def _sync_mode(self) -> None:
        global_mode = not self._local.isChecked()
        for label, axis in (("Px", "x"), ("Py", "y"), ("Pz", "z")):
            self._fields[label].setToolTip(
                f"Force along global {axis.upper()}" if global_mode else f"Force along local {axis}"
            )
        if self._ndm == 2:
            # Global Y and local z are out of the X-Z plane.
            self._fields["Py"].setEnabled(not global_mode)
            self._fields["Pz"].setEnabled(global_mode)
        else:
            self._fields["Py"].setEnabled(True)
            self._fields["Pz"].setEnabled(True)
        self._note.setText(
            "<i>Global components (Fx, Fy, Fz) are converted to each member's local "
            "axes. The load goes into the active Plain pattern; if none exists a "
            "default pattern is created. Force- and displacement-based elements "
            "resolve a point load through their integration points: split the member "
            "at the load for exact end forces.</i>"
            if global_mode
            else "<i>Forces are in the element's local frame (Px, Py, Pz). The load "
            "goes into the active Plain pattern; if none exists a default pattern is "
            "created. Force- and displacement-based elements resolve a point load "
            "through their integration points: split the member at the load for exact "
            "end forces.</i>"
        )

    def _on_mode_changed(self) -> None:
        if self.mode() == RELATIVE:
            self._distance.setRange(0.0, 1.0)
            self._distance.setSingleStep(0.1)
        else:
            self._distance.setRange(0.0, 1e12)
            self._distance.setSingleStep(1.0)

    def _on_accept(self) -> None:
        if all(field.value() == 0.0 for field in self._fields.values()):
            QMessageBox.warning(self, "Assign Frame Point Load", "Enter a non-zero force.")
            return
        self.accept()

    def mode(self) -> str:
        """``RELATIVE`` or ``ABSOLUTE``."""
        return str(self._mode.currentData())

    def distance(self) -> float:
        return self._distance.value()

    def values(self) -> tuple[float, float, float]:
        """Return the legacy (Py, Pz, Px) local order."""
        return (
            self._fields["Py"].value(),
            self._fields["Pz"].value(),
            self._fields["Px"].value(),
        )

    def vector(self) -> tuple[float, float, float]:
        """Return (X or Px, Y or Py, Z or Pz) in the displayed order.

        A 2D model has no out-of-plane load: the disabled field is reported as
        zero even if it still holds a value from the other mode.
        """
        px = self._fields["Px"].value()
        py = self._fields["Py"].value()
        pz = self._fields["Pz"].value()
        if self._ndm == 2:
            if self._local.isChecked():
                pz = 0.0
            else:
                py = 0.0
        return (px, py, pz)

    def is_local(self) -> bool:
        """True when the entered values are element-local components."""
        return self._local.isChecked()

    def set_local(self, local: bool) -> None:
        """Set the mode without a click (tests and scripted use)."""
        self._local.setChecked(local)
