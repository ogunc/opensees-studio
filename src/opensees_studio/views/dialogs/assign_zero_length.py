"""Assign → Joint → Zero-Length Element: one uniaxial material per global DOF.

The two joints sit at the same point; the element's deformation is their
relative displacement or rotation. Every ticked DOF carries one material, in
the order of the ticks, exactly as OpenSees' ``zeroLength`` expects.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialogButtonBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from opensees_studio.core import Project, ZeroLengthElement
from opensees_studio.core.help import TOPIC_PROPERTY
from opensees_studio.core.materials.library import is_uniaxial
from opensees_studio.core.plane import dof_labels
from opensees_studio.views.screen_fit import FittedDialog, MessageArea


class AssignZeroLengthDialog(FittedDialog):
    """Pick the DOFs and their materials for a zero-length element."""

    def __init__(
        self, project: Project, nodes: tuple[int, int], parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Assign Zero-Length Element")
        self.setProperty(TOPIC_PROPERTY, "assign.zero_length")
        self._project = project
        self._nodes = nodes
        self._materials = [m for m in project.materials if is_uniaxial(m)]
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.addWidget(
            QLabel(
                f"Connect joints <b>{self._nodes[0]}</b> and "
                f"<b>{self._nodes[1]}</b> with an OpenSees "
                "<code>zeroLength</code> element. The two joints must share "
                "the same coordinates."
            )
        )

        box = QGroupBox("Global DOFs and their materials")
        grid = QGridLayout(box)
        labels = dof_labels(self._project.ndm, self._project.ndf)
        self.dof_checks: dict[int, QCheckBox] = {}
        self.dof_materials: dict[int, QComboBox] = {}
        for dof, label in enumerate(labels, start=1):
            check = QCheckBox(f"{dof}  {label}")
            check.setChecked(dof == 1)
            combo = QComboBox()
            for material in self._materials:
                combo.addItem(
                    f"#{material.id} {material.name or material.type} [{material.type}]",
                    material.id,
                )
            combo.setEnabled(check.isChecked() and bool(self._materials))
            if self._materials:
                check.toggled.connect(combo.setEnabled)
            grid.addWidget(check, dof - 1, 0)
            grid.addWidget(combo, dof - 1, 1)
            self.dof_checks[dof] = check
            self.dof_materials[dof] = combo
        root.addWidget(box)

        form = QFormLayout()
        self.do_rayleigh = QCheckBox("Stiffness-proportional Rayleigh damping (-doRayleigh)")
        form.addRow(self.do_rayleigh)
        root.addLayout(form)

        self.message = MessageArea()
        root.addWidget(self.message)
        if not self._materials:
            self.message.show_message(
                "Define a uniaxial material first (Material Library).", "warning"
            )

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def build_element(self, element_id: int) -> ZeroLengthElement:
        """The element as typed (raises ``ValueError`` on a bad entry)."""
        if not self._materials:
            raise ValueError("Define a uniaxial material first.")
        dofs = tuple(dof for dof, check in self.dof_checks.items() if check.isChecked())
        if not dofs:
            raise ValueError("Tick at least one DOF.")
        material_ids = tuple(int(self.dof_materials[dof].currentData()) for dof in dofs)
        return ZeroLengthElement(
            id=element_id,
            nodes=self._nodes,
            material_ids=material_ids,
            dofs=dofs,
            do_rayleigh=self.do_rayleigh.isChecked(),
        )

    def accept(self) -> None:
        try:
            self.build_element(1)
        except ValueError as exc:
            self.message.show_message(str(exc), "error")
            return
        super().accept()
