"""Edit → Merge Joints and Edit → Divide Frames at Joints.

Two repairs for a model that looks joined on screen and is not: joints a hair
apart that should be one (Merge Joints), and joints that lie inside a frame or
truss without being one of its ends (Divide Frames at Joints). Both show what
they will do before they do it; the geometry lives in ``core.duplicates``,
``core.mesh`` and ``core.connectivity``.
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

from opensees_studio.core.connectivity import check_connectivity
from opensees_studio.core.duplicates import default_tolerance, find_node_clusters
from opensees_studio.core.help import TOPIC_PROPERTY
from opensees_studio.core.mesh import MeshPlan, auto_mesh
from opensees_studio.core.project import Project
from opensees_studio.views.float_field import FloatField
from opensees_studio.views.screen_fit import FittedDialog, MessageArea

#: Merge Joints proposes a thousandth of the model's size (a drawing a few
#: millimetres off on a 10 m frame), a thousand times the duplicates check's.
MERGE_TOLERANCE_FACTOR = 1000.0


class _ScopedDialog(FittedDialog):
    """Tolerance, a selection-or-model scope, a live summary and an OK button."""

    def __init__(
        self,
        project: Project,
        *,
        title: str,
        topic: str,
        intro: str,
        scope_label: str,
        selected: set[int],
        tolerance: float,
        ok_text: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._project = project
        self._selected = set(selected)
        self.setWindowTitle(title)
        self.setProperty(TOPIC_PROPERTY, topic)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(intro))
        self.form = QFormLayout()

        self._tolerance = FloatField()
        self._tolerance.setRange(0.0, 1e9)
        self._tolerance.setValue(tolerance)
        self._tolerance.valueChanged.connect(self._refresh)
        self.form.addRow("Tolerance:", self._tolerance)

        self._scope_selection = QRadioButton(f"Selected {scope_label} ({len(selected)})")
        self._scope_all = QRadioButton("Entire model")
        self._scope_selection.setEnabled(bool(selected))
        (self._scope_selection if selected else self._scope_all).setChecked(True)
        self._scope_selection.toggled.connect(self._refresh)
        self.form.addRow("Apply to:", self._scope_selection)
        self.form.addRow("", self._scope_all)
        layout.addLayout(self.form)

        self._summary = MessageArea()
        layout.addWidget(self._summary)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self._ok.setText(ok_text)

    def tolerance(self) -> float:
        return self._tolerance.value()

    def scope_ids(self) -> set[int] | None:
        """The selected ids, or None for the whole model."""
        return set(self._selected) if self._scope_selection.isChecked() else None

    def _refresh(self, *_: object) -> None:
        raise NotImplementedError


class MergeJointsDialog(_ScopedDialog):
    """Merge joints closer than a tolerance; the lowest id stays."""

    def __init__(
        self, project: Project, *, selected_nodes: set[int], parent: QWidget | None = None
    ) -> None:
        super().__init__(
            project,
            title="Merge Joints",
            topic="edit.merge_joints",
            intro=(
                "Joints closer than the tolerance become one. <i>The lowest id stays; "
                "elements, loads, constraints, masses and restraints move to it, and "
                "members that end up repeated are removed.</i>"
            ),
            scope_label="joints",
            selected=selected_nodes,
            tolerance=default_tolerance(project) * MERGE_TOLERANCE_FACTOR,
            ok_text="Merge",
            parent=parent,
        )
        self._refresh()

    def _refresh(self, *_: object) -> None:
        tolerance = self.tolerance()
        if tolerance <= 0.0:
            self._summary.show_message("The tolerance must be positive.", level="error")
            self._ok.setEnabled(False)
            return
        mergeable, exempt = find_node_clusters(
            self._project, tolerance=tolerance, node_ids=self.scope_ids()
        )
        removed = sum(len(c.duplicate_ids) for c in mergeable)
        lines = []
        if mergeable:
            lines.append(f"{len(mergeable)} group(s) of joints merge; {removed} joint(s) go.")
        if exempt:
            lines.append(
                f"{len(exempt)} group(s) left alone: "
                + "; ".join(f"{c.summary()}" for c in exempt[:3])
                + (" …" if len(exempt) > 3 else "")
            )
        if not mergeable:
            lines.insert(0, "No joints within the tolerance.")
            self._summary.show_message("\n".join(lines), level="warning")
            self._ok.setEnabled(False)
            return
        self._summary.show_message("\n".join(lines))
        self._ok.setEnabled(True)


class DivideFramesDialog(_ScopedDialog):
    """Split frames and trusses at the joints that lie inside them."""

    def __init__(
        self, project: Project, *, selected_elements: set[int], parent: QWidget | None = None
    ) -> None:
        super().__init__(
            project,
            title="Divide Frames at Joints",
            topic="edit.divide_frames",
            intro=(
                "Split every frame and truss at the joints lying inside it, so a member "
                "that only looks connected becomes connected. <i>Loads follow the pieces; "
                "one undo step.</i>"
            ),
            scope_label="members",
            selected=selected_elements,
            tolerance=default_tolerance(project) * MERGE_TOLERANCE_FACTOR,
            ok_text="Divide",
            parent=parent,
        )
        self._crossings = QCheckBox("Also split members where they cross each other")
        self._crossings.setChecked(True)
        self._crossings.toggled.connect(self._refresh)
        self.form.addRow("", self._crossings)
        self._plan = MeshPlan()
        self._refresh()

    def plan(self) -> MeshPlan:
        return self._plan

    def _refresh(self, *_: object) -> None:
        if not hasattr(self, "_crossings"):
            return  # still building
        self._plan = auto_mesh(
            self._project,
            self.scope_ids(),
            target_size=1.0,
            bars=False,
            shells=False,
            at_nodes=True,
            at_crossings=self._crossings.isChecked(),
            tolerance=self.tolerance(),
        )
        report = check_connectivity(self._project, tolerance=self.tolerance())
        notes = []
        if report.loose_joints:
            notes.append(
                f"{len(report.loose_joints)} loose joint(s) on no element (Select → Loose Joints)."
            )
        if report.joints_on_shell_edges:
            notes.append(
                f"{len(report.joints_on_shell_edges)} joint(s) on a shell edge, not at a corner: "
                "subdivide those shells with Edit → Mesh (Select → Joints on Shell Edges)."
            )
        if self._plan.is_empty:
            self._summary.show_message(
                "\n".join(["No joint lies inside a member.", *notes]), level="warning"
            )
            self._ok.setEnabled(False)
            return
        self._summary.show_message("\n".join([self._plan.summary(), *notes]))
        self._ok.setEnabled(True)
