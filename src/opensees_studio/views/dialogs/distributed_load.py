"""Assign Distributed Load dialog — uniform line-load for selected elements."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from opensees_studio.views.float_field import FloatField
from opensees_studio.views.screen_fit import FittedDialog


class AssignDistributedLoadDialog(FittedDialog):
    """Modal dialog for a uniform distributed load on the selected frames.

    Global X/Y/Z is the default; each member receives the projection of that
    vector on its own local axes when the command runs. Ticking **Use local
    axes** keeps the direct wx / wy / wz entry for callers who think in the
    element frame.
    """

    def __init__(self, n_selected: int, ndm: int = 3, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Assign Distributed Load")
        self._ndm = ndm
        self._build_ui(n_selected)

    def _build_ui(self, n_selected: int) -> None:
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"Apply to <b>{n_selected}</b> selected element(s)."))

        self._local = QCheckBox("Use local axes (wx, wy, wz)")
        self._local.setToolTip(
            "Off: enter global Fx / Fy / Fz; every member converts them to its own axes. "
            "On: enter the load directly in the element's local frame."
        )
        layout.addWidget(self._local)

        form = QFormLayout()
        self._labels: dict[str, QLabel] = {}
        self._spinboxes: dict[str, FloatField] = {}
        for key in ("wx", "wy", "wz"):
            sb = FloatField()
            sb.setRange(-1e12, 1e12)
            sb.setSingleStep(1.0)
            sb.setValue(0.0)
            label = QLabel()
            self._labels[key] = label
            self._spinboxes[key] = sb
            form.addRow(label, sb)
        layout.addLayout(form)

        self._note = QLabel()
        self._note.setWordWrap(True)
        layout.addWidget(self._note)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._local.toggled.connect(self._sync_mode)
        self._sync_mode()

    def _sync_mode(self) -> None:
        global_mode = not self._local.isChecked()
        for key, axis in (("wx", "x"), ("wy", "y"), ("wz", "z")):
            label = self._labels[key]
            label.setText(f"{'F' if global_mode else 'w'}{axis}:")
            self._spinboxes[key].setToolTip(
                f"Force per unit length along global {axis.upper()}"
                if global_mode
                else f"Force per unit length along local {axis}"
            )
        if self._ndm == 2:
            # Global Y and local z are out of the X-Z plane.
            self._spinboxes["wy"].setEnabled(not global_mode)
            self._spinboxes["wz"].setEnabled(global_mode)
        else:
            self._spinboxes["wy"].setEnabled(True)
            self._spinboxes["wz"].setEnabled(True)
        self._note.setText(
            "<i>Global components (Fx, Fy, Fz) are converted to each member's local "
            "axes when the load is applied. The load goes into the active Plain "
            "pattern; if none exists a default pattern is created.</i>"
            if global_mode
            else "<i>Components are in the element's local frame (wx, wy, wz). "
            "The load goes into the active Plain pattern; if none exists a default "
            "pattern is created.</i>"
        )

    def is_local(self) -> bool:
        """True when the entered values are element-local components."""
        return self._local.isChecked()

    def values(self) -> tuple[float, float, float]:
        """Return (X or wx, Y or wy, Z or wz) in the displayed order.

        A 2D model has no out-of-plane load: the disabled field is reported as
        zero even if it still holds a value from the other mode.
        """
        wx = self._spinboxes["wx"].value()
        wy = self._spinboxes["wy"].value()
        wz = self._spinboxes["wz"].value()
        if self._ndm == 2:
            if self._local.isChecked():
                wz = 0.0
            else:
                wy = 0.0
        return (wx, wy, wz)

    def set_local(self, local: bool) -> None:
        """Set the mode without a click (tests and scripted use)."""
        self._local.setChecked(local)
