"""Assign EqualDOF dialog."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from opensees_studio.core import EqualDOFConstraint
from opensees_studio.core.plane import dof_labels
from opensees_studio.views.screen_fit import FittedDialog


class AssignEqualDOFDialog(FittedDialog):
    """Choose retained/constrained node and constrained DOFs."""

    def __init__(
        self,
        selected_nodes: list[int],
        ndf: int,
        parent: QWidget | None = None,
        *,
        ndm: int | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Assign EqualDOF")
        self._selected_nodes = selected_nodes
        self._ndf = ndf
        # Without ndm, ndf 2 and 3 mean a 2D model (the X-Z plane, core.plane).
        self._ndm = ndm if ndm is not None else (3 if ndf == 6 else 2)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(
                "Tie selected nodes together in chosen DOFs using OpenSees <code>equalDOF</code>.",
            )
        )

        form = QFormLayout()

        self._retained_cb = QComboBox()
        self._constrained_cb = QComboBox()
        for nid in self._selected_nodes:
            self._retained_cb.addItem(f"Node {nid}", nid)
            self._constrained_cb.addItem(f"Node {nid}", nid)
        if len(self._selected_nodes) >= 2:
            self._constrained_cb.setCurrentIndex(1)

        form.addRow("Retained node:", self._retained_cb)
        form.addRow("Constrained node:", self._constrained_cb)
        layout.addLayout(form)

        dof_form = QFormLayout()
        self._dof_boxes: list[QCheckBox] = []
        active_labels = dof_labels(self._ndm, self._ndf)
        for i, label in enumerate(active_labels, start=1):
            cb = QCheckBox(label)
            if self._ndm == 2 and self._ndf == 3 and label in ("Uz", "Ry"):
                cb.setChecked(True)
            self._dof_boxes.append(cb)
            dof_form.addRow(f"DOF {i}:", cb)
        layout.addLayout(dof_form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def constraint(self) -> EqualDOFConstraint:
        retained = int(self._retained_cb.currentData())
        constrained = int(self._constrained_cb.currentData())
        if retained == constrained:
            raise ValueError("Retained and constrained node must be different.")
        if self._ndf == 2:
            dof_ids = (1, 2)
        elif self._ndf == 3:
            map_ids = [1, 2, 3]
            dof_ids = tuple(map_ids[i] for i, cb in enumerate(self._dof_boxes) if cb.isChecked())
        else:
            map_ids = [1, 2, 3, 4, 5, 6]
            dof_ids = tuple(map_ids[i] for i, cb in enumerate(self._dof_boxes) if cb.isChecked())
        if not dof_ids:
            raise ValueError("Select at least one DOF.")
        return EqualDOFConstraint(
            retained_node=retained,
            constrained_node=constrained,
            dofs=dof_ids,
        )
