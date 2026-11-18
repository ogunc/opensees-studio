"""Joint patterns: define them, and give the selected joints their values.

- :class:`JointPatternsDialog` — Define → Joint Patterns: add, rename and delete
  patterns, and read or edit each node's value in a table.
- :class:`AssignJointPatternDialog` — Assign → Joint → Joint Pattern Values: the
  SAP2000 form. The values of the selected joints come from ``A·x + B·y + C·z +
  D`` or from a free surface and a unit weight (hydrostatic), are filtered
  (all, zero the negative ones, zero the positive ones) and added to, replace or
  delete what the pattern held. The range of the values it will assign is shown
  before OK.

Both return the whole new pattern list; the host applies it in one undoable
command. What the values do is :mod:`opensees_studio.core.joint_patterns`.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QComboBox,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QRadioButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from opensees_studio.core import Project
from opensees_studio.core.help import TOPIC_PROPERTY
from opensees_studio.core.joint_patterns import (
    ACTIONS,
    RESTRICTIONS,
    JointPattern,
    assign,
    hydrostatic_values,
    plane_values,
    restrict,
)
from opensees_studio.views.float_field import FloatField
from opensees_studio.views.screen_fit import FittedDialog, MessageArea

NEW_PATTERN = -1


def _next_id(patterns: list[JointPattern]) -> int:
    return max((p.id for p in patterns), default=0) + 1


# ──────────────────────────── Define → Joint Patterns ────────────────────────────
class JointPatternsDialog(FittedDialog):
    """Add, rename and delete joint patterns; read and edit their values."""

    def __init__(self, project: Project, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Joint Patterns")
        self.setProperty(TOPIC_PROPERTY, "define.joint_patterns")
        self._project = project
        self._patterns = [p.model_copy(deep=True) for p in project.joint_patterns]
        self._used = {
            load.joint_pattern_id
            for pattern in project.load_patterns
            for load in getattr(pattern, "surface_loads", [])
            if load.joint_pattern_id is not None
        }
        self._filling = False
        self._build_ui()
        self._fill_list()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        intro = QLabel(
            "A joint pattern is a value at each node. A surface load that varies by it "
            "applies, at each corner of a shell, its multiplier times the pattern's value. "
            "Give the selected joints their values with Assign → Joint → Joint Pattern Values."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        row = QHBoxLayout()
        left = QVBoxLayout()
        self._list = QListWidget()
        self._list.currentRowChanged.connect(self._fill_table)
        self._list.itemChanged.connect(self._renamed)
        left.addWidget(self._list)
        buttons = QHBoxLayout()
        self._add = QPushButton("Add")
        self._add.clicked.connect(self._add_pattern)
        self._delete = QPushButton("Delete")
        self._delete.clicked.connect(self._delete_pattern)
        buttons.addWidget(self._add)
        buttons.addWidget(self._delete)
        left.addLayout(buttons)
        row.addLayout(left, 1)
        self._table = QTableWidget(0, 2)
        self._table.setHorizontalHeaderLabels(["Node", "Value"])
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.itemChanged.connect(self._value_edited)
        row.addWidget(self._table, 2)
        layout.addLayout(row)
        self._message = MessageArea()
        layout.addWidget(self._message)
        box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        layout.addWidget(box)

    # ── list ──
    def _fill_list(self, select: int = 0) -> None:
        self._filling = True
        self._list.clear()
        for pattern in self._patterns:
            item = QListWidgetItem(pattern.name or f"Pattern {pattern.id}")
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
            item.setData(Qt.ItemDataRole.UserRole, pattern.id)
            self._list.addItem(item)
        self._filling = False
        if self._patterns:
            self._list.setCurrentRow(min(select, len(self._patterns) - 1))
        self._fill_table(self._list.currentRow())

    def _add_pattern(self) -> None:
        pid = _next_id(self._patterns)
        self._patterns.append(JointPattern(id=pid, name=f"PATTERN{pid}"))
        self._fill_list(len(self._patterns) - 1)

    def _delete_pattern(self) -> None:
        row = self._list.currentRow()
        if row < 0:
            return
        pattern = self._patterns[row]
        if pattern.id in self._used:
            self._message.show_message(
                f"'{pattern.name}' carries a surface load: remove the load first.", "warning"
            )
            return
        del self._patterns[row]
        self._fill_list(row)

    def _renamed(self, item: QListWidgetItem) -> None:
        if self._filling:
            return
        row = self._list.row(item)
        name = item.text().strip()
        if not name:
            return
        self._patterns[row] = self._patterns[row].model_copy(update={"name": name})

    # ── values ──
    def _fill_table(self, row: int) -> None:
        self._filling = True
        self._table.setRowCount(0)
        if 0 <= row < len(self._patterns):
            values = self._patterns[row].values
            self._table.setRowCount(len(values))
            for k, (node_id, value) in enumerate(sorted(values.items())):
                node = QTableWidgetItem(str(node_id))
                node.setFlags(node.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self._table.setItem(k, 0, node)
                self._table.setItem(k, 1, QTableWidgetItem(f"{value:.6g}"))
            count = len(values)
            self._message.show_message(
                f"{count} node(s) with a value; every other node counts as zero."
                if count
                else "No values yet: select joints and use Assign → Joint → Joint Pattern Values."
            )
        self._delete.setEnabled(0 <= row < len(self._patterns))
        self._filling = False

    def _value_edited(self, item: QTableWidgetItem) -> None:
        if self._filling or item.column() != 1:
            return
        row = self._list.currentRow()
        node_item = self._table.item(item.row(), 0)
        if row < 0 or node_item is None:
            return
        try:
            value = float(item.text())
        except ValueError:
            self._message.show_message(f"'{item.text()}' is not a number.", "error")
            return
        node_id = int(node_item.text())
        self._patterns[row] = assign(self._patterns[row], {node_id: value}, "replace")

    def patterns(self) -> list[JointPattern]:
        return list(self._patterns)


# ──────────────────────────── Assign → Joint → Joint Pattern Values ────────────────────────────
class AssignJointPatternDialog(FittedDialog):
    """Give the selected joints a joint pattern's values, the way SAP2000 does."""

    def __init__(
        self, project: Project, node_ids: list[int], parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Assign Joint Pattern Values")
        self.setProperty(TOPIC_PROPERTY, "assign.joint_pattern")
        self._project = project
        self._coords = {n.id: n.coords for n in project.nodes if n.id in set(node_ids)}
        self._build_ui()
        self._update()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"{len(self._coords)} selected joint(s)."))
        form = QFormLayout()
        self.pattern = QComboBox()
        for pattern in self._project.joint_patterns:
            self.pattern.addItem(pattern.name or f"Pattern {pattern.id}", pattern.id)
        self.pattern.addItem("(new pattern)", NEW_PATTERN)
        self.new_name = QLineEdit(f"PATTERN{_next_id(list(self._project.joint_patterns))}")
        form.addRow("Pattern:", self.pattern)
        form.addRow("New pattern name:", self.new_name)
        layout.addLayout(form)

        plane_box = QGroupBox()
        plane_layout = QFormLayout(plane_box)
        self.by_plane = QRadioButton("X, Y, Z multipliers:  value = A·x + B·y + C·z + D")
        plane_layout.addRow(self.by_plane)
        self.a, self.b, self.c, self.d = (FloatField() for _ in range(4))
        for label, field, unit in (
            ("A", self.a, "1 / length"),
            ("B", self.b, "1 / length"),
            ("C", self.c, "1 / length"),
            ("D", self.d, "unitless"),
        ):
            field.setRange(-1e15, 1e15)
            field.setValue(0.0)
            plane_layout.addRow(f"{label} ({unit}):", field)
        self.d.setValue(1.0)
        layout.addWidget(plane_box)

        water_box = QGroupBox()
        water_layout = QFormLayout(water_box)
        self.by_depth = QRadioButton(
            "Z coordinate at zero pressure and weight per unit volume (hydrostatic)"
        )
        water_layout.addRow(self.by_depth)
        self.z_zero, self.weight, self.added = FloatField(), FloatField(), FloatField()
        for field in (self.z_zero, self.weight, self.added):
            field.setRange(-1e15, 1e15)
            field.setValue(0.0)
        water_layout.addRow("Z at zero pressure:", self.z_zero)
        water_layout.addRow("Weight per unit volume:", self.weight)
        water_layout.addRow("Added uniform value per unit area:", self.added)
        layout.addWidget(water_box)
        # The two methods sit in different boxes: only a group makes them exclusive.
        self._methods = QButtonGroup(self)
        self._methods.addButton(self.by_plane)
        self._methods.addButton(self.by_depth)
        self.by_depth.setChecked(True)
        if self._coords:
            self.z_zero.setValue(max(float(c[2]) for c in self._coords.values()))

        options = QFormLayout()
        self.restriction = QComboBox()
        for label, key in RESTRICTIONS:
            self.restriction.addItem(label, key)
        self.restriction.setCurrentIndex(1)  # zero negative values: no suction above the water
        self.action = QComboBox()
        for label, action in ACTIONS:
            self.action.addItem(label, action)
        options.addRow("Restriction:", self.restriction)
        options.addRow("Existing values:", self.action)
        layout.addLayout(options)

        self.preview = MessageArea()
        layout.addWidget(self.preview)
        box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        layout.addWidget(box)

        for widget in (self.a, self.b, self.c, self.d, self.z_zero, self.weight, self.added):
            widget.valueChanged.connect(self._update)
        for combo in (self.pattern, self.restriction, self.action):
            combo.currentIndexChanged.connect(self._update)
        self.by_plane.toggled.connect(self._update)

    def computed(self) -> dict[int, float]:
        """The values the selected joints get, before they are merged with the pattern's."""
        if self.by_plane.isChecked():
            raw = plane_values(
                self._coords, self.a.value(), self.b.value(), self.c.value(), self.d.value()
            )
        else:
            raw = hydrostatic_values(
                self._coords, self.z_zero.value(), self.weight.value(), self.added.value()
            )
        return restrict(raw, self.restriction.currentData())

    def _update(self) -> None:
        plane = self.by_plane.isChecked()
        for widget in (self.a, self.b, self.c, self.d):
            widget.setEnabled(plane)
        for widget in (self.z_zero, self.weight, self.added):
            widget.setEnabled(not plane)
        self.new_name.setEnabled(self.pattern.currentData() == NEW_PATTERN)
        if self.action.currentData() == "delete":
            self.preview.show_message(
                f"The selected joints' values will be removed from the pattern "
                f"({len(self._coords)} joint(s))."
            )
            return
        values = list(self.computed().values())
        if not values:
            self.preview.show_message("No joint selected.", "warning")
            return
        self.preview.show_message(
            f"Values from {min(values):.6g} to {max(values):.6g} on {len(values)} joint(s)."
        )

    def patterns(self) -> list[JointPattern]:
        """The whole pattern list with the chosen one updated (or added)."""
        patterns = list(self._project.joint_patterns)
        chosen = self.pattern.currentData()
        if chosen == NEW_PATTERN:
            pid = _next_id(patterns)
            name = self.new_name.text().strip() or f"PATTERN{pid}"
            patterns.append(JointPattern(id=pid, name=name))
            chosen = pid
        index = next(k for k, p in enumerate(patterns) if p.id == chosen)
        patterns[index] = assign(patterns[index], self.computed(), self.action.currentData())
        return patterns

    def pattern_name(self) -> str:
        if self.pattern.currentData() == NEW_PATTERN:
            return self.new_name.text().strip()
        return self.pattern.currentText()
