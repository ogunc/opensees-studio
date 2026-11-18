"""Define → Grid Wizard: a whole grid from a few numbers, Cartesian or radial.

Per axis: how many lines, the spacing, where the first one is and how the lines
are named (A, B, C … / 1, 2, 3 … / X1, X2 …). A cylindrical (radial) grid asks
for rings (radii), radial lines (angles in degrees) and levels. The preview
lists the lines before anything is created; the result is a plain
:class:`CoordinateGridSystem` the main window adds, or puts in place of an
existing system's grid, as one undo step.
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
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from opensees_studio.core.geometry import (
    CoordinateGridSystem,
    CoordinateSystem,
    GridSystem,
    regular_grid_lines,
)
from opensees_studio.views.float_field import FloatField
from opensees_studio.views.screen_fit import FittedDialog, MessageArea

ID_STYLES = ("Letters", "Numbers", "Axis")
_ID_STYLE_LABELS = {"Letters": "A, B, C …", "Numbers": "1, 2, 3 …", "Axis": "X1, X2 …"}
NEW_SYSTEM = ""
"""``target()`` for "create a new coordinate system"."""

#: (axis prefix, row label, count, spacing, first, id style) per type and row.
_DEFAULTS = {
    "Cartesian": (
        ("X", "X lines", 4, 6.0, 0.0, "Letters"),
        ("Y", "Y lines", 3, 6.0, 0.0, "Numbers"),
        ("Z", "Z levels", 3, 3.0, 0.0, "Axis"),
    ),
    "Cylindrical": (
        ("R", "Rings (radius)", 3, 5.0, 5.0, "Axis"),
        ("T", "Radial lines (angle, deg)", 8, 45.0, 0.0, "Numbers"),
        ("Z", "Z levels", 3, 3.0, 0.0, "Axis"),
    ),
}


class GridWizardDialog(FittedDialog):
    """Build a regular Cartesian or cylindrical grid from counts and spacings."""

    def __init__(
        self,
        existing: list[CoordinateGridSystem],
        ndm: int = 3,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Grid Wizard")
        self._ndm = ndm
        self._names = [cs.name for cs in existing]
        root = QVBoxLayout(self)

        top = QFormLayout()
        self.target_combo = QComboBox()
        self.target_combo.addItem("New coordinate system", NEW_SYSTEM)
        for name in self._names:
            self.target_combo.addItem(f"Replace the grid of '{name}'", name)
        if self._names and all(
            not (cs.grid.x_grid_lines or cs.grid.y_grid_lines or cs.grid.z_grid_lines)
            for cs in existing[:1]
        ):
            # An empty Global grid (a new project) is the obvious one to fill.
            self.target_combo.setCurrentIndex(1)
        self.name_edit = QLineEdit(self._unique("GRID"))
        self.type_combo = QComboBox()
        self.type_combo.addItems(["Cartesian", "Cylindrical"])
        if ndm == 2:
            self.type_combo.setEnabled(False)
            self.type_combo.setToolTip("A 2D model lives in the X-Z plane: Cartesian only.")
        top.addRow("Put it in:", self.target_combo)
        top.addRow("New system name:", self.name_edit)
        top.addRow("Grid type:", self.type_combo)
        root.addLayout(top)

        origin_box = QGroupBox("Origin of a new system")
        origin_row = QGridLayout(origin_box)
        self.origin = [FloatField(), FloatField(), FloatField()]
        for k, (axis_name, field) in enumerate(zip("XYZ", self.origin, strict=True)):
            field.setRange(-1e9, 1e9)
            origin_row.addWidget(QLabel(f"{axis_name}:"), 0, 2 * k)
            origin_row.addWidget(field, 0, 2 * k + 1)
        root.addWidget(origin_box)
        self._origin_box = origin_box

        lines_box = QGroupBox("Lines")
        grid = QGridLayout(lines_box)
        for col, title in enumerate(("", "Number", "Spacing", "First at", "Names")):
            grid.addWidget(QLabel(f"<b>{title}</b>"), 0, col)
        self.row_labels: list[QLabel] = []
        self.counts: list[QSpinBox] = []
        self.spacings: list[FloatField] = []
        self.firsts: list[FloatField] = []
        self.styles: list[QComboBox] = []
        for row in range(3):
            label = QLabel()
            count = QSpinBox()
            count.setRange(0, 500)
            spacing = FloatField()
            spacing.setRange(-1e9, 1e9)
            first = FloatField()
            first.setRange(-1e9, 1e9)
            style = QComboBox()
            for key in ID_STYLES:
                style.addItem(_ID_STYLE_LABELS[key], key)
            widgets: tuple[QWidget, ...] = (label, count, spacing, first, style)
            for col, widget in enumerate(widgets):
                grid.addWidget(widget, row + 1, col)
            self.row_labels.append(label)
            self.counts.append(count)
            self.spacings.append(spacing)
            self.firsts.append(first)
            self.styles.append(style)
        root.addWidget(lines_box)

        label_box = QGroupBox("Labels")
        label_form = QFormLayout(label_box)
        self.show_labels = QCheckBox("Show grid labels")
        self.show_labels.setChecked(True)
        self.label_content = QComboBox()
        self.label_content.addItems(["ID", "ID + coordinate", "Coordinate"])
        self.label_position = QComboBox()
        self.label_position.addItems(["Start", "End", "Both"])
        self.label_position.setCurrentText("Both")
        label_form.addRow(self.show_labels)
        label_form.addRow("Content:", self.label_content)
        label_form.addRow("Position:", self.label_position)
        root.addWidget(label_box)

        self.preview = QLabel()
        self.preview.setWordWrap(True)
        root.addWidget(self.preview)
        self.message = MessageArea()
        root.addWidget(self.message)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self.type_combo.currentTextChanged.connect(self._load_defaults)
        self.target_combo.currentIndexChanged.connect(self._on_target_changed)
        for count in self.counts:
            count.valueChanged.connect(self._update_preview)
        for field in (*self.spacings, *self.firsts):
            field.valueChanged.connect(self._update_preview)
        for combo in (*self.styles, self.label_content):
            combo.currentIndexChanged.connect(self._update_preview)
        self._load_defaults(self.type_combo.currentText())
        self._on_target_changed()

    def _unique(self, base: str) -> str:
        name, k = base, 1
        while name in self._names:
            k += 1
            name = f"{base}{k}"
        return name

    def _load_defaults(self, kind: str) -> None:
        for row, (_axis, label, count, spacing, first, style) in enumerate(_DEFAULTS[kind]):
            self.row_labels[row].setText(label + ":")
            self.counts[row].setValue(0 if (self._ndm == 2 and row == 1) else count)
            self.spacings[row].setValue(spacing)
            self.firsts[row].setValue(first)
            self.styles[row].setCurrentIndex(ID_STYLES.index(style))
        if self._ndm == 2:
            # Y is out of the plane of a 2D model.
            for widget in (self.counts[1], self.spacings[1], self.firsts[1], self.styles[1]):
                widget.setEnabled(False)
        self._update_preview()

    def _on_target_changed(self) -> None:
        new = self.target() == NEW_SYSTEM
        self.name_edit.setEnabled(new)
        self._origin_box.setEnabled(new)

    def target(self) -> str:
        """The system whose grid is replaced, or :data:`NEW_SYSTEM`."""
        return str(self.target_combo.currentData())

    def _axes(self) -> tuple[str, str, str]:
        return tuple(a[0] for a in _DEFAULTS[self.type_combo.currentText()])  # type: ignore[return-value]

    def grid_system(self) -> GridSystem:
        """The grid as set (raises ``ValueError`` on an impossible one)."""
        kind = self.type_combo.currentText()
        per_axis = [
            regular_grid_lines(
                self.counts[k].value(),
                float(self.spacings[k].value()),
                float(self.firsts[k].value()),
                axis=self._axes()[k],
                id_style=str(self.styles[k].currentData()),
            )
            for k in range(3)
        ]
        for k, lines in enumerate(per_axis):
            if len(lines) > 1 and float(self.spacings[k].value()) == 0.0:
                raise ValueError(f"{self.row_labels[k].text()} the spacing cannot be 0.")
        if kind == "Cylindrical":
            if any(ln.ordinate < 0.0 for ln in per_axis[0]):
                raise ValueError("Rings: a radius cannot be negative.")
            angles = [ln.ordinate for ln in per_axis[1]]
            if angles and max(angles) - min(angles) >= 360.0 - 1e-9:
                raise ValueError("Radial lines: more than a full turn (lower the number).")
        if not any(per_axis):
            raise ValueError("Ask for at least one line.")
        location = self.label_position.currentText()
        per_axis = [
            [ln.model_copy(update={"bubble_loc": location}) for ln in lines] for lines in per_axis
        ]
        return GridSystem.model_validate(
            {
                "x_grid_lines": per_axis[0],
                "y_grid_lines": per_axis[1],
                "z_grid_lines": per_axis[2],
                "system_type": kind,
                "show_labels": self.show_labels.isChecked(),
                "label_content": self.label_content.currentText(),
            }
        )

    def system(self) -> CoordinateGridSystem:
        """A new coordinate system holding the grid (its origin as typed)."""
        return CoordinateGridSystem(
            name=self.name_edit.text().strip() or self._unique("GRID"),
            coord=CoordinateSystem(origin=tuple(float(f.value()) for f in self.origin)),  # type: ignore[arg-type]
            grid=self.grid_system(),
        )

    def _update_preview(self) -> None:
        try:
            grid = self.grid_system()
        except ValueError as exc:
            self.preview.setText(f"<span style='color:#b00'>{exc}</span>")
            return
        parts = []
        for k, lines in enumerate((grid.x_grid_lines, grid.y_grid_lines, grid.z_grid_lines)):
            if lines:
                shown = ", ".join(f"{ln.id}={ln.ordinate:g}" for ln in lines[:6])
                more = f" … ({len(lines)} lines)" if len(lines) > 6 else ""
                parts.append(f"<b>{self.row_labels[k].text()}</b> {shown}{more}")
        self.preview.setText("<br>".join(parts))

    def accept(self) -> None:
        try:
            self.grid_system()
        except ValueError as exc:
            self.message.show_message(str(exc), "error")
            return
        super().accept()
