"""Dialogs for area loads and imposed displacements (see :mod:`core.area_loads`).

- :class:`SurfaceLoadDialog` — Assign → Area → Surface Load on Shells.
- :class:`FloorLoadDialog` — Assign → Area → Floor Load to Frames: the bays the
  selected joints frame (found by :func:`core.area_loads.floor_panels`).
- :class:`ImposedDisplacementDialog` — Assign → Joint → Imposed Displacement.

Each picks a Plain load pattern; the host builds the loads and applies them in
one undoable command.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import (
    QComboBox,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from opensees_studio.core import FloorLoad, ImposedDisplacement, PlainLoadPattern, Project
from opensees_studio.core.plane import dof_labels
from opensees_studio.views.float_field import FloatField
from opensees_studio.views.screen_fit import FittedDialog

SURFACE_DIRECTIONS: list[tuple[str, str]] = [
    ("Global Z (gravity is negative)", "Z"),
    ("Shell normal (local 3)", "normal"),
    ("Global X", "X"),
    ("Global Y", "Y"),
]

FLOOR_DISTRIBUTIONS: list[tuple[str, str]] = [
    ("Two-way (45° yield lines)", "two_way"),
    ("One-way, slab spanning along X", "one_way_x"),
    ("One-way, slab spanning along Y", "one_way_y"),
]


def _pattern_combo(project: Project) -> QComboBox:
    combo = QComboBox()
    for pattern in project.load_patterns:
        if isinstance(pattern, PlainLoadPattern):
            combo.addItem(f"#{pattern.id} {pattern.name or 'Plain'}", pattern.id)
    if combo.count() == 0:
        combo.addItem("(a new pattern)", None)
    return combo


class _LoadDialog(FittedDialog):
    """A pattern picker, a form, OK / Cancel."""

    def __init__(self, title: str, intro: str, project: Project, parent: QWidget | None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self._project = project
        layout = QVBoxLayout(self)
        label = QLabel(intro)
        label.setWordWrap(True)
        layout.addWidget(label)
        self.form = QFormLayout()
        self.pattern = _pattern_combo(project)
        self.form.addRow("Load pattern:", self.pattern)
        layout.addLayout(self.form)
        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)
        layout.addWidget(self._buttons)

    def pattern_id(self) -> int | None:
        data = self.pattern.currentData()
        return None if data is None else int(data)


class SurfaceLoadDialog(_LoadDialog):
    def __init__(self, n_shells: int, project: Project, parent: QWidget | None = None) -> None:
        super().__init__(
            "Surface Load on Shells",
            f"A uniform pressure, force per area, on {n_shells} shell(s). It reaches the "
            "solver as consistent nodal forces.",
            project,
            parent,
        )
        self.value = FloatField()
        self.value.setRange(-1e12, 1e12)
        self.value.setValue(-1.0)
        self.direction = QComboBox()
        for label, key in SURFACE_DIRECTIONS:
            self.direction.addItem(label, key)
        self.form.addRow("Value (force / area):", self.value)
        self.form.addRow("Direction:", self.direction)

    def values(self) -> dict[str, Any]:
        return {"value": self.value.value(), "direction": str(self.direction.currentData())}


class FloorLoadDialog(_LoadDialog):
    def __init__(
        self,
        panels: list[tuple[int, int, int, int]],
        project: Project,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(
            "Floor Load to Frames",
            f"{len(panels)} floor bay(s) framed on all four sides by beams. The load acts "
            "downward and goes to the beams around each bay as trapezoidal loads.",
            project,
            parent,
        )
        self._panels = panels
        self.value = FloatField()
        self.value.setRange(0.0, 1e12)
        self.value.setValue(1.0)
        self.distribution = QComboBox()
        for label, key in FLOOR_DISTRIBUTIONS:
            self.distribution.addItem(label, key)
        self.form.addRow("Load (force / area, downward):", self.value)
        self.form.addRow("Distribution:", self.distribution)

    def loads(self) -> list[FloorLoad]:
        """One floor load per bay; a one-way span is turned into the bay's own edge."""
        coords = {n.id: n.coords for n in self._project.nodes}
        key = str(self.distribution.currentData())
        out: list[FloorLoad] = []
        for corners in self._panels:
            distribution = key
            if key != "two_way":
                a, b = coords[corners[0]], coords[corners[1]]
                along_x_12 = abs(b[0] - a[0]) >= abs(b[1] - a[1])
                wants_x = key == "one_way_x"
                distribution = "one_way_12" if along_x_12 == wants_x else "one_way_23"
            out.append(
                FloorLoad(nodes=corners, value=self.value.value(), distribution=distribution)  # type: ignore[arg-type]
            )
        return out


class ImposedDisplacementDialog(_LoadDialog):
    def __init__(self, n_nodes: int, project: Project, parent: QWidget | None = None) -> None:
        super().__init__(
            "Imposed Displacement",
            f"A static displacement imposed on {n_nodes} joint(s) — a support settlement. On "
            "a restrained DOF the support moves; on a free one the joint is held there for "
            "the cases that run this pattern.",
            project,
            parent,
        )
        self.dof = QComboBox()
        for k, label in enumerate(dof_labels(project.ndm, project.ndf), start=1):
            self.dof.addItem(f"{k} — {label}", k)
        vertical = next(
            (i for i in range(self.dof.count()) if self.dof.itemText(i).endswith("Uz")), 0
        )
        self.dof.setCurrentIndex(vertical)
        self.value = FloatField()
        self.value.setRange(-1e12, 1e12)
        self.value.setValue(-0.01)
        self.form.addRow("DOF:", self.dof)
        self.form.addRow("Value:", self.value)

    def loads(self, node_ids: list[int]) -> list[ImposedDisplacement]:
        dof = int(self.dof.currentData())
        return [ImposedDisplacement(node_id=n, dof=dof, value=self.value.value()) for n in node_ids]
