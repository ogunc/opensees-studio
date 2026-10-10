"""Shell contour dock — pick a field, a step and a scale; the canvas paints it.

Exposes three signals the host wires to the renderer:

- ``changed(field_key, step, scale, show_directions)`` — anything the user
  moved. The host owns the renderer, so the view never draws by itself.
- ``unitsChanged()`` — the display units changed, so the colour bar's title has
  to be rebuilt with a new label.
- ``closed()`` — the user is done; the host tears the overlay down.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from opensees_studio.core.units import UnitConverter
from opensees_studio.services.shell_fields import SHELL_FIELDS, field_by_key
from opensees_studio.views.float_field import FloatField

#: Group order in the picker, and the separator between groups.
_GROUP_ORDER = ("Deformation", "Membrane", "Bending", "Shear")


class ShellContourView(QWidget):
    """Controls for the shell contour overlay."""

    changed = Signal(str, int, float, bool)  # field, step, scale, directions
    unitsChanged = Signal()
    closed = Signal()

    def __init__(self, n_steps: int = 1, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._converter = UnitConverter()
        self._n_steps = max(1, n_steps)
        self._build_ui()

    # ── public API ──────────────────────────────────────────────────
    def set_units(self, converter: UnitConverter) -> None:
        """Remember the project's display units; the colour bar is rebuilt."""
        self._converter = converter
        self.unitsChanged.emit()

    @property
    def converter(self) -> UnitConverter:
        return self._converter

    @property
    def target_units(self):  # type: ignore[no-untyped-def]
        """The unit system the numbers are shown in."""
        return self._converter.target

    def current_field(self) -> str:
        return self._field.currentData() or SHELL_FIELDS[0].key

    def current_step(self) -> int:
        """0-based step index; the last step is the default."""
        return int(self._step.value()) - 1

    def current_scale(self) -> float:
        return float(self._scale.value())

    def directions_wanted(self) -> bool:
        return self._directions.isChecked() and field_by_key(self.current_field()).direction

    def emit_changed(self) -> None:
        """Ask the host to paint the current selection."""
        self.changed.emit(
            self.current_field(),
            self.current_step(),
            self.current_scale(),
            self.directions_wanted(),
        )

    # ── UI ──────────────────────────────────────────────────────────
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.addWidget(QLabel("<b>Shell Contours</b>"))
        root.addWidget(
            QLabel(
                "<i>A colour map of the shell faces. Deformations warp the mesh; "
                "forces and moments are painted on the undeformed shape, with the "
                "principal direction drawn when the field is a principal one.</i>",
            ),
        )

        group = QGroupBox("Field", self)
        form = QFormLayout(group)
        self._field = QComboBox()
        for group_name in _GROUP_ORDER:
            fields = [field for field in SHELL_FIELDS if field.group == group_name]
            if not fields:
                continue
            for index, field in enumerate(fields):
                self._field.addItem(
                    f"{group_name}: {field.label}" if index == 0 else field.label, field.key
                )
            self._field.insertSeparator(self._field.count())
        self._field.currentIndexChanged.connect(self._on_field_changed)
        form.addRow("Show:", self._field)

        self._step = QSpinBox()
        self._step.setRange(1, self._n_steps)
        self._step.setValue(self._n_steps)  # the last step, like every other view
        self._step.setToolTip("Step of the analysis to read (the last one by default).")
        self._step.valueChanged.connect(lambda _v: self.emit_changed())
        form.addRow("Step:", self._step)

        self._scale = FloatField()
        self._scale.setRange(0.0, 1e6)
        self._scale.setValue(0.0)
        self._scale.setToolTip(
            "Deformation scale. 0 paints the undeformed model; use the deformed "
            "shape's suggested factor to see both at once.",
        )
        self._scale.valueChanged.connect(lambda _v: self.emit_changed())
        form.addRow("Scale:", self._scale)

        self._directions = QCheckBox("Draw principal directions")
        self._directions.setToolTip(
            "One segment per element, along its major principal axis; its length "
            "is the spread between the two principal values.",
        )
        self._directions.setEnabled(field_by_key(self.current_field()).direction)
        self._directions.toggled.connect(lambda _v: self.emit_changed())
        form.addRow("", self._directions)
        root.addWidget(group)

        info = QLabel(
            "Values are the section stress resultants OpenSees reports, per unit "
            "length: membrane forces and shear in force/length, bending in "
            "moment/length. They are averaged over the element's gauss points and "
            "onto the nodes, so the picture is continuous across elements.",
        )
        info.setWordWrap(True)
        root.addWidget(info)

        self._back = QPushButton("Back to model")
        self._back.clicked.connect(self.closed.emit)
        root.addWidget(self._back)
        root.addStretch(1)

    # ── slots ───────────────────────────────────────────────────────
    def _on_field_changed(self, _index: int) -> None:
        field = field_by_key(self.current_field())
        self._directions.setEnabled(field.direction)
        if not field.direction:
            self._directions.setChecked(False)
        # A deformation field is the one that wants a scale; keep 0 meaningful.
        self._scale.setEnabled(field.kind == "deformation")
        if field.kind != "deformation":
            self._scale.blockSignals(True)
            self._scale.setValue(0.0)
            self._scale.blockSignals(False)
        self.emit_changed()
