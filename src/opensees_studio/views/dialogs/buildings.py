"""Building dialogs: storeys, mass source, rigid diaphragm and rigid link.

Each dialog edits a copy and hands back plain core models (``storeys()``,
``mass_source()``, ``diaphragm()``, ``link()``); the main window wraps the
result in an undoable command. Values that do not parse are refused in the
dialog's message area, never accepted silently.
"""

from __future__ import annotations

from typing import Literal, cast

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from opensees_studio.core import (
    MassSource,
    MassSourcePattern,
    Node,
    PlainLoadPattern,
    Project,
    RigidDiaphragm,
    RigidLink,
    Storey,
)
from opensees_studio.core.diaphragms import (
    constrained_node_ids,
    diaphragm_problems,
    diaphragms_supported,
)
from opensees_studio.core.mass_source import diaphragm_centre_of_mass, total_translational_mass
from opensees_studio.core.storeys import storeys_from_grid
from opensees_studio.views.screen_fit import FittedDialog, MessageArea


def _buttons(dialog: FittedDialog) -> QDialogButtonBox:
    box = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
        parent=dialog,
    )
    box.accepted.connect(dialog.accept)
    box.rejected.connect(dialog.reject)
    return box


# ─────────────────────────── Define → Storeys ───────────────────────────
class StoreysDialog(FittedDialog):
    """Name and elevation of every floor; can fill itself from a system's Z grid lines."""

    def __init__(self, project: Project, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Define Storeys")
        self._project = project
        self._ids: list[int] = []
        self._result: list[Storey] = []
        root = QVBoxLayout(self)
        axis = "Z"  # the elevation axis of every model (core.plane)
        root.addWidget(
            QLabel(
                f"Floor levels, by elevation along {axis}. The levels below the lowest "
                "storey are the base; drift ratios divide by the distance to the level below."
            )
        )
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Name", f"Elevation ({axis})"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        root.addWidget(self.table)

        row = QHBoxLayout()
        self.add_button = QPushButton("Add")
        self.add_button.clicked.connect(self._on_add)
        self.remove_button = QPushButton("Remove")
        self.remove_button.clicked.connect(self._on_remove)
        row.addWidget(self.add_button)
        row.addWidget(self.remove_button)
        row.addStretch(1)
        self.system_combo = QComboBox()
        for system in project.coord_systems:
            self.system_combo.addItem(system.name, system.name)
        self.from_grid_button = QPushButton("From Z grid lines")
        self.from_grid_button.setToolTip(
            "One storey per Z grid line of the chosen system, the lowest line being the base."
        )
        self.from_grid_button.clicked.connect(self._on_from_grid)
        row.addWidget(self.system_combo)
        row.addWidget(self.from_grid_button)
        root.addLayout(row)

        self.message = MessageArea()
        root.addWidget(self.message)
        root.addWidget(_buttons(self))
        for storey in sorted(project.storeys, key=lambda s: s.elevation):
            self._append(storey.id, storey.name, storey.elevation)

    def _append(self, storey_id: int, name: str, elevation: float) -> None:
        r = self.table.rowCount()
        self.table.insertRow(r)
        self.table.setItem(r, 0, QTableWidgetItem(name))
        self.table.setItem(r, 1, QTableWidgetItem(repr(float(elevation))))
        self._ids.append(storey_id)

    def _next_id(self) -> int:
        used = set(self._ids)
        return max(used, default=0) + 1

    def _on_add(self) -> None:
        top = 0.0
        for r in range(self.table.rowCount()):
            item = self.table.item(r, 1)
            try:
                top = max(top, float(item.text())) if item is not None else top
            except ValueError:
                continue
        self._append(self._next_id(), f"Story{self.table.rowCount() + 1}", top + 3.0)

    def _on_remove(self) -> None:
        rows = sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True)
        for r in rows:
            self.table.removeRow(r)
            del self._ids[r]

    def _on_from_grid(self) -> None:
        name = self.system_combo.currentData()
        system = next(s for s in self._project.coord_systems if s.name == name)
        storeys = storeys_from_grid(system, first_id=1)
        if not storeys:
            self.message.show_message(
                f"System '{name}' has fewer than two Z grid lines.", "warning"
            )
            return
        # Keep the ids of the storeys already there, so diaphragms keep theirs.
        old = list(self._ids)
        self.table.setRowCount(0)
        self._ids = []
        for k, storey in enumerate(storeys):
            storey_id = old[k] if k < len(old) else max([*old, *self._ids, 0]) + 1
            self._append(storey_id, storey.name, storey.elevation)
        self.message.clear_message()

    def storeys(self) -> list[Storey]:
        """The storeys as typed (raises ``ValueError`` on a bad row)."""
        out: list[Storey] = []
        for r in range(self.table.rowCount()):
            name_item, elevation_item = self.table.item(r, 0), self.table.item(r, 1)
            name = name_item.text().strip() if name_item else ""
            try:
                elevation = float(elevation_item.text()) if elevation_item else float("nan")
            except ValueError:
                raise ValueError(f"Row {r + 1}: the elevation is not a number.") from None
            if elevation != elevation:
                raise ValueError(f"Row {r + 1}: the elevation is missing.")
            out.append(Storey(id=self._ids[r], name=name or f"Story{r + 1}", elevation=elevation))
        elevations = [s.elevation for s in out]
        if len(set(elevations)) != len(elevations):
            raise ValueError("Two storeys have the same elevation.")
        return sorted(out, key=lambda s: s.elevation)

    def accept(self) -> None:
        try:
            self._result = self.storeys()
        except ValueError as exc:
            self.message.show_message(str(exc), "error")
            return
        super().accept()


# ─────────────────────────── Define → Mass Source ───────────────────────────
class MassSourceDialog(FittedDialog):
    """Self weight and load patterns (with factors) that become nodal mass."""

    def __init__(self, project: Project, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Define Mass Source")
        self._project = project
        source = project.mass_source
        root = QVBoxLayout(self)

        self.group = QGroupBox("Derive mass from weight (W / g)")
        self.group.setCheckable(True)
        self.group.setChecked(source is not None)
        source = source or MassSource()
        inner = QVBoxLayout(self.group)
        self.self_mass = QCheckBox("Element self mass (frames and shells with a unit weight)")
        self.self_mass.setChecked(source.element_self_mass)
        inner.addWidget(self.self_mass)

        inner.addWidget(QLabel("Load patterns (downward loads, scaled by the factor):"))
        plain = [p for p in project.load_patterns if isinstance(p, PlainLoadPattern)]
        factors = {e.pattern_id: e.factor for e in source.patterns}
        self.patterns = QTableWidget(len(plain), 2)
        self.patterns.setHorizontalHeaderLabels(["Pattern", "Factor"])
        self.patterns.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._pattern_ids: list[int] = []
        for r, pattern in enumerate(plain):
            item = QTableWidgetItem(f"#{pattern.id} {pattern.name}".strip())
            item.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            item.setCheckState(
                Qt.CheckState.Checked if pattern.id in factors else Qt.CheckState.Unchecked
            )
            self.patterns.setItem(r, 0, item)
            self.patterns.setItem(r, 1, QTableWidgetItem(repr(factors.get(pattern.id, 1.0))))
            self._pattern_ids.append(pattern.id)
        inner.addWidget(self.patterns)

        self.vertical = QCheckBox("Also on the vertical translation")
        self.vertical.setChecked(source.include_vertical)
        inner.addWidget(self.vertical)
        self.lump = QCheckBox(
            "Lump each diaphragm's mass and rotational inertia at its retained node"
        )
        self.lump.setChecked(source.lump_at_diaphragms)
        inner.addWidget(self.lump)
        root.addWidget(self.group)

        self.total = QLabel()
        root.addWidget(self.total)
        self.message = MessageArea()
        root.addWidget(self.message)
        root.addWidget(_buttons(self))
        for signal in (
            self.group.toggled,
            self.self_mass.toggled,
            self.vertical.toggled,
            self.lump.toggled,
        ):
            signal.connect(self._refresh)
        self.patterns.itemChanged.connect(self._refresh)
        self._refresh()

    def mass_source(self) -> MassSource | None:
        """The mass source as set (``None`` = typed nodal masses only)."""
        if not self.group.isChecked():
            return None
        entries: list[MassSourcePattern] = []
        for r, pattern_id in enumerate(self._pattern_ids):
            check, value = self.patterns.item(r, 0), self.patterns.item(r, 1)
            if check is None or value is None or check.checkState() != Qt.CheckState.Checked:
                continue
            try:
                factor = float(value.text())
            except ValueError:
                raise ValueError(f"The factor of pattern {pattern_id} is not a number.") from None
            if factor < 0.0:
                raise ValueError(f"The factor of pattern {pattern_id} is negative.")
            entries.append(MassSourcePattern(pattern_id=pattern_id, factor=factor))
        return MassSource(
            element_self_mass=self.self_mass.isChecked(),
            patterns=entries,
            include_vertical=self.vertical.isChecked(),
            lump_at_diaphragms=self.lump.isChecked(),
        )

    def _refresh(self, *_args: object) -> None:
        try:
            source = self.mass_source()
        except ValueError as exc:
            self.message.show_message(str(exc), "error")
            return
        preview = self._project.model_copy(update={"mass_source": source})
        mx, my, mz = total_translational_mass(preview)
        self.total.setText(f"Total mass: X {mx:.6g}, Y {my:.6g}, Z {mz:.6g}")
        twice = (
            source is not None
            and source.element_self_mass
            and any(
                p.self_weight
                for p in self._project.load_patterns
                if isinstance(p, PlainLoadPattern)
                and p.id in {e.pattern_id for e in source.patterns}
            )
        )
        if twice:
            self.message.show_message(
                "A chosen pattern carries self weight and element self mass is on: "
                "the self weight counts twice.",
                "warning",
            )
        else:
            self.message.clear_message()

    def accept(self) -> None:
        try:
            self.mass_source()
        except ValueError as exc:
            self.message.show_message(str(exc), "error")
            return
        super().accept()


# ─────────────────────────── Assign → Joint → Diaphragm ───────────────────────────
_PERP = (("Z (horizontal floor)", 3), ("X", 1), ("Y", 2))


class AssignDiaphragmDialog(FittedDialog):
    """A rigid diaphragm over the selected joints or a whole storey."""

    def __init__(
        self, project: Project, selected_nodes: list[int], parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Assign Rigid Diaphragm")
        self._project = project
        self._selected = sorted(selected_nodes)
        root = QVBoxLayout(self)
        root.addWidget(
            QLabel(
                "Make a floor rigid in its plane (OpenSees <code>rigidDiaphragm</code>). "
                "The joints follow the retained node in the two in-plane translations "
                "and the in-plane rotation."
            )
        )
        form = QFormLayout()
        self.name = QLineEdit(f"D{project.next_diaphragm_id()}")
        form.addRow("Name:", self.name)

        self.by_storey = QRadioButton("Every joint of storey")
        self.by_selection = QRadioButton(f"The {len(self._selected)} selected joint(s)")
        group = QButtonGroup(self)
        group.addButton(self.by_storey)
        group.addButton(self.by_selection)
        self.storey_combo = QComboBox()
        for storey in sorted(project.storeys, key=lambda s: s.elevation):
            self.storey_combo.addItem(f"{storey.name} ({storey.elevation:g})", storey.id)
        storey_row = QHBoxLayout()
        storey_row.addWidget(self.by_storey)
        storey_row.addWidget(self.storey_combo, 1)
        form.addRow("Joints:", storey_row)
        form.addRow("", self.by_selection)
        self.perp = QComboBox()
        for label, value in _PERP:
            self.perp.addItem(label, value)
        form.addRow("Perpendicular axis:", self.perp)

        self.retained_new = QRadioButton("New node at the centre of mass")
        self.retained_existing = QRadioButton("Existing node")
        retained_group = QButtonGroup(self)
        retained_group.addButton(self.retained_new)
        retained_group.addButton(self.retained_existing)
        self.retained_combo = QComboBox()
        for nid in self._selected:
            self.retained_combo.addItem(f"Node {nid}", nid)
        self.retained_new.setChecked(True)
        form.addRow("Retained node:", self.retained_new)
        existing_row = QHBoxLayout()
        existing_row.addWidget(self.retained_existing)
        existing_row.addWidget(self.retained_combo, 1)
        form.addRow("", existing_row)
        root.addLayout(form)

        self.message = MessageArea()
        root.addWidget(self.message)
        root.addWidget(_buttons(self))

        if project.storeys:
            self.by_storey.setChecked(True)
        else:
            self.by_selection.setChecked(True)
            self.by_storey.setEnabled(False)
        self.by_selection.setEnabled(len(self._selected) >= 2)
        self.retained_existing.setEnabled(bool(self._selected))
        for button in (
            self.by_storey,
            self.by_selection,
            self.retained_new,
            self.retained_existing,
        ):
            button.toggled.connect(self._sync)
        self._sync()
        self._diaphragm: tuple[RigidDiaphragm, Node | None] | None = None

    def _sync(self, *_args: object) -> None:
        storey = self.by_storey.isChecked()
        self.storey_combo.setEnabled(storey)
        if storey:
            self.perp.setCurrentIndex(0)
        self.perp.setEnabled(not storey)
        self.retained_combo.setEnabled(self.retained_existing.isChecked())
        if not diaphragms_supported(self._project):
            self.message.show_message(
                "Rigid diaphragms need a 3D model with 6 DOF per node.", "error"
            )

    def _members(self, retained: int | None) -> tuple[int, ...]:
        """The joints the diaphragm will constrain (a storey's resolved now).

        ``None`` stands for a retained node that does not exist yet; the
        reserved id 999999 is never a model node.
        """
        if self.by_storey.isChecked():
            probe = RigidDiaphragm(
                id=1,
                retained_node=retained or 999999,
                storey_id=int(self.storey_combo.currentData()),
            )
            return constrained_node_ids(self._project, probe)
        return tuple(n for n in self._selected if n != retained)

    def diaphragm(self) -> tuple[RigidDiaphragm, Node | None]:
        """The diaphragm and, when the retained node is new, that node (``ValueError`` if bad)."""
        project = self._project
        if not diaphragms_supported(project):
            raise ValueError("Rigid diaphragms need a 3D model with 6 DOF per node.")
        perp = int(self.perp.currentData())
        new_node: Node | None = None
        if self.retained_existing.isChecked():
            retained = int(self.retained_combo.currentData())
        else:
            members = self._members(None)
            if not members:
                raise ValueError("The diaphragm has no joints.")
            centre = diaphragm_centre_of_mass(project, members, perp)
            retained = project.next_node_id()
            new_node = Node(id=retained, name=f"{self.name.text().strip()} CM", coords=centre)
        name = self.name.text().strip()
        diaphragm_id = project.next_diaphragm_id()
        if self.by_storey.isChecked():
            diaphragm = RigidDiaphragm(
                id=diaphragm_id,
                name=name,
                retained_node=retained,
                storey_id=int(self.storey_combo.currentData()),
            )
            if not self._members(retained):
                raise ValueError("The storey has no free joint to constrain.")
        else:
            members = self._members(retained)
            if not members:
                raise ValueError("Select at least one joint besides the retained node.")
            diaphragm = RigidDiaphragm(
                id=diaphragm_id,
                name=name,
                perp_dirn=cast(Literal[1, 2, 3], perp),
                retained_node=retained,
                constrained_nodes=members,
            )
        preview = project.model_copy(
            update={
                "nodes": [*project.nodes, *([new_node] if new_node else [])],
                "diaphragms": [*project.diaphragms, diaphragm],
            }
        )
        problems = [p for p in diaphragm_problems(preview) if p not in diaphragm_problems(project)]
        if problems:
            raise ValueError(problems[0])
        return diaphragm, new_node

    def accept(self) -> None:
        try:
            self._diaphragm = self.diaphragm()
        except ValueError as exc:
            self.message.show_message(str(exc), "error")
            return
        super().accept()


# ─────────────────────────── Assign → Joint → Rigid Link ───────────────────────────
class AssignRigidLinkDialog(FittedDialog):
    """``rigidLink beam`` or ``bar`` between the two selected joints."""

    def __init__(self, selected_nodes: list[int], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Assign Rigid Link")
        root = QVBoxLayout(self)
        root.addWidget(
            QLabel(
                "<b>beam</b>: the constrained node follows the retained one as a rigid body "
                "(translations with the lever arm, and rotations).<br>"
                "<b>bar</b>: only the translations are tied."
            )
        )
        form = QFormLayout()
        self.kind = QComboBox()
        self.kind.addItem("beam", "beam")
        self.kind.addItem("bar", "bar")
        form.addRow("Type:", self.kind)
        self.retained = QComboBox()
        self.constrained = QComboBox()
        for nid in selected_nodes:
            self.retained.addItem(f"Node {nid}", nid)
            self.constrained.addItem(f"Node {nid}", nid)
        if len(selected_nodes) >= 2:
            self.constrained.setCurrentIndex(1)
        form.addRow("Retained node:", self.retained)
        form.addRow("Constrained node:", self.constrained)
        root.addLayout(form)
        self.message = MessageArea()
        root.addWidget(self.message)
        root.addWidget(_buttons(self))

    def link(self) -> RigidLink:
        retained, constrained = (
            int(self.retained.currentData()),
            int(self.constrained.currentData()),
        )
        if retained == constrained:
            raise ValueError("Retained and constrained node must be different.")
        return RigidLink(
            kind=self.kind.currentData(), retained_node=retained, constrained_node=constrained
        )

    def accept(self) -> None:
        try:
            self.link()
        except ValueError as exc:
            self.message.show_message(str(exc), "error")
            return
        super().accept()
