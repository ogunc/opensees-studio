"""Mesh the model: a target size, a scope, and the automatic joins.

The dialog is a form over :func:`opensees_studio.core.mesh.auto_mesh`, and it
shows the plan before applying it — how many elements and nodes it will add and
how many it will replace — because the difference between "1 bar split in three"
and "1,240 elements" is one keystroke in the size field.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from opensees_studio.core.help import TOPIC_PROPERTY
from opensees_studio.core.mesh import COINCIDENT_TOLERANCE, MeshError, MeshPlan, auto_mesh
from opensees_studio.core.project import Project
from opensees_studio.views.float_field import FloatField
from opensees_studio.views.screen_fit import FittedDialog, MessageArea


def _default_size(project: Project, ids: set[int] | None) -> float:
    """A tenth of the model (or of the selection), which is a sane first guess."""
    elements = [
        element for element in project.elements if ids is None or element.id in ids
    ] or project.elements
    points = [
        node.coords
        for element in elements
        for node in (project.node(node_id) for node_id in element.nodes)
    ] or [node.coords for node in project.nodes]
    if not points:
        return 1.0
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    zs = [point[2] for point in points]
    diagonal = (
        float((max(xs) - min(xs)) ** 2 + (max(ys) - min(ys)) ** 2 + (max(zs) - min(zs)) ** 2) ** 0.5
    )
    tenth = diagonal / 10.0
    return tenth if tenth > 1e-6 else 1e-6


class MeshDialog(FittedDialog):
    """Choose the mesh size and what to do, and see what it will cost."""

    def __init__(
        self,
        project: Project,
        *,
        selected_element_ids: set[int] | None = None,
        has_selection: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._project = project
        self._selected = set(selected_element_ids or ())
        self.setWindowTitle("Mesh")
        self.setProperty(TOPIC_PROPERTY, "edit.mesh")
        self._build_ui(has_selection)
        self._refresh()

    # ── ui ──────────────────────────────────────────────────────────
    def _build_ui(self, has_selection: bool) -> None:
        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(
                "Subdivide members and shells, and join the mesh up. <i>Bars longer than the "
                "target become equal pieces, shells larger than the target are subdivided "
                "m×n, and the joins split a bar where a node or another bar lies on it.</i>"
            )
        )
        form = QFormLayout()

        self._size = FloatField()
        self._size.setRange(1e-9, 1e9)
        self._size.setSingleStep(1.0)
        self._size.setValue(_default_size(self._project, self._selected if has_selection else None))
        self._size.setToolTip("Longest edge a piece may have, in project units.")
        self._size.valueChanged.connect(self._refresh)
        form.addRow("Target size:", self._size)

        self._scope_selection = QRadioButton("Selection")
        self._scope_all = QRadioButton("Entire model")
        self._scope_selection.setEnabled(has_selection)
        (self._scope_selection if has_selection else self._scope_all).setChecked(True)
        self._scope_selection.toggled.connect(self._refresh)
        self._scope_all.toggled.connect(self._refresh)
        form.addRow("Mesh:", self._scope_selection)
        form.addRow("", self._scope_all)

        self._shells = QCheckBox("Subdivide shells and quads")
        self._bars = QCheckBox("Split bars longer than the target")
        self._nodes = QCheckBox("Split bars at nodes lying on them")
        self._crossings = QCheckBox("Split bars where they cross each other")
        for box in (self._shells, self._bars, self._nodes, self._crossings):
            box.setChecked(True)
            box.toggled.connect(self._refresh)
            form.addRow("", box)

        self._tolerance = FloatField()
        self._tolerance.setRange(0.0, 1e9)
        self._tolerance.setDecimals(8)
        self._tolerance.setValue(COINCIDENT_TOLERANCE)
        self._tolerance.setToolTip(
            "A node closer than this to a bar counts as lying on it, and two bars closer "
            "than this count as crossing."
        )
        self._tolerance.valueChanged.connect(self._refresh)
        form.addRow("Tolerance:", self._tolerance)
        layout.addLayout(form)

        self._summary = MessageArea()
        layout.addWidget(self._summary)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self._ok.setText("Mesh")

    # ── the plan ────────────────────────────────────────────────────
    def scope_ids(self) -> set[int] | None:
        """The element ids to mesh: the selection, or None for the whole model."""
        if self._scope_selection.isChecked():
            return set(self._selected)
        return None

    def plan(self) -> MeshPlan:
        """The mesh this form describes (recomputed on every change)."""
        return self._plan

    def _refresh(self, *_: object) -> None:
        try:
            self._plan = auto_mesh(
                self._project,
                self.scope_ids(),
                target_size=self._size.value(),
                bars=self._bars.isChecked(),
                shells=self._shells.isChecked(),
                at_nodes=self._nodes.isChecked(),
                at_crossings=self._crossings.isChecked(),
                tolerance=self._tolerance.value(),
            )
        except MeshError as exc:
            self._summary.show_message(str(exc), level="error")
            self._ok.setEnabled(False)
            return
        if self._plan.is_empty:
            self._summary.show_message("Nothing to mesh with these settings.", level="warning")
            self._ok.setEnabled(False)
            return
        self._summary.show_message(self._plan.summary())
        self._ok.setEnabled(True)
