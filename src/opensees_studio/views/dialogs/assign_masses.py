"""Assign Masses dialog — set translational (+ rotational) mass on selected nodes.

SAP2000 parity: the Assign → Joint → Masses menu item accumulates the
entered values onto each selected node. We follow the simpler "replace"
semantics (set the mass on each selected node to these values) because
it maps cleanly onto our existing :class:`SetMassCommand`.
"""

from __future__ import annotations

import contextlib

from PySide6.QtWidgets import (
    QCheckBox,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from opensees_studio.core.modal import dof_indices
from opensees_studio.views.float_field import FloatField
from opensees_studio.views.screen_fit import FittedDialog


class AssignMassesDialog(FittedDialog):
    """Modal dialog: enter translational + rotational mass components."""

    def __init__(
        self,
        n_selected: int,
        ndf: int = 6,
        parent: QWidget | None = None,
        *,
        ndm: int = 3,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Assign Masses")
        self._active = dof_indices(ndm, ndf)
        self._build_ui(n_selected)

    def _build_ui(self, n_selected: int) -> None:
        root = QVBoxLayout(self)
        root.addWidget(
            QLabel(
                f"Assign mass values to <b>{n_selected}</b> selected node(s).",
            )
        )

        form = QFormLayout()
        fields = ("_mx", "_my", "_mz", "_mxx", "_myy", "_mzz")
        labels = ("Ux", "Uy", "Uz", "Rx (Ixx)", "Ry (Iyy)", "Rz (Izz)")
        for i, (name, label) in enumerate(zip(fields, labels, strict=True)):
            field = self._spin()
            setattr(self, name, field)
            if i in self._active:
                form.addRow(f"{label}:", field)
        root.addLayout(form)

        self._xy_link = QCheckBox("Tie translation Y to X (lumped horizontal mass)")
        self._xy_link.toggled.connect(self._on_xy_link)
        root.addWidget(self._xy_link)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    @staticmethod
    def _spin() -> FloatField:
        sb = FloatField()
        sb.setRange(0.0, 1e15)
        sb.setSingleStep(100.0)
        sb.setValue(0.0)
        return sb

    def _on_xy_link(self, checked: bool) -> None:
        if checked:
            self._my.setValue(self._mx.value())
            self._mx.valueChanged.connect(self._my.setValue)
        else:
            with contextlib.suppress(RuntimeError, TypeError):
                self._mx.valueChanged.disconnect(self._my.setValue)

    def mass_vector(self) -> tuple[float, float, float, float, float, float]:
        """Return the 6-tuple (Mx, My, Mz, Mxx, Myy, Mzz)."""
        return (
            self._mx.value(),
            self._my.value(),
            self._mz.value(),
            self._mxx.value(),
            self._myy.value(),
            self._mzz.value(),
        )
