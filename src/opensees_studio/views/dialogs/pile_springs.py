"""Assign → Frame → Pile Soil Springs: p-y, t-z and q-z springs along a pile.

The selected members are the pile. Enter its diameter, the elevation of the
ground and the soil layers (depths below the ground); the window previews what
:func:`core.piles.pile_springs` builds, and OK adds the ground joints, the
spring materials and the zero-length elements in one undo step.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import (
    QComboBox,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from opensees_studio.core.help import TOPIC_PROPERTY
from opensees_studio.core.piles import PileSpec, PileSprings, SoilLayer, pile_springs
from opensees_studio.core.units import (
    UnitSystem,
    force_scale,
    labels_for,
    length_scale,
    stress_scale,
)
from opensees_studio.views.float_field import FloatField
from opensees_studio.views.screen_fit import FittedDialog, MessageArea

COLUMNS = ("Top", "Bottom", "Soil", "γ' effective", "su (clay)", "φ° (sand)", "k (sand)")


class PileSpringsDialog(FittedDialog):
    """Diameter, ground level, the soil layers, and a preview of the springs."""

    def __init__(self, project: Any, element_ids: set[int], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Assign Pile Soil Springs")
        self.setProperty(TOPIC_PROPERTY, "assign.pile_springs")
        self._project = project
        self._element_ids = set(element_ids)
        self._result: PileSprings | None = None
        units = project.meta.units
        labels = labels_for(units)
        self._kpa = stress_scale(UnitSystem.SI_M_N, units) * 1e3
        self._kn_m3 = (
            force_scale(UnitSystem.SI_M_N, units)
            * 1e3
            / length_scale(UnitSystem.SI_M_N, units) ** 3
        )
        layout = QVBoxLayout(self)
        intro = QLabel(
            "The selected members are the pile. Every joint of it below the ground gets "
            "lateral p-y springs (Matlock clay / API sand), a t-z shaft spring and, at the "
            "tip, a q-z spring, each tied to a fixed ground joint at the same point. Depths "
            f"are below the ground level, in {labels.length}."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        form = QFormLayout()
        self._diameter = self._field(0.6 * length_scale(UnitSystem.SI_M_N, units))
        form.addRow(f"Pile diameter [{labels.length}]:", self._diameter)
        self._ground = self._field(0.0, minimum=-1e9)
        form.addRow(f"Ground level, Z [{labels.length}]:", self._ground)
        layout.addLayout(form)
        self._table = QTableWidget(0, len(COLUMNS))
        self._table.setHorizontalHeaderLabels(list(COLUMNS))
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._table.setMinimumHeight(150)
        self._table.itemChanged.connect(self._refresh)
        layout.addWidget(self._table)
        row = QHBoxLayout()
        add = QPushButton("Add layer")
        add.clicked.connect(self._add_default_layer)
        remove = QPushButton("Remove layer")
        remove.clicked.connect(self._remove_layer)
        row.addWidget(add)
        row.addWidget(remove)
        row.addStretch(1)
        layout.addLayout(row)
        units_note = QLabel(
            f"<i>γ' and k in {labels.force}/{labels.length}³, su in {labels.stress}. Below the "
            "water table use the submerged γ'. Typical k (API RP 2A): about 5 to 40 MN/m³ for "
            "loose to dense sand.</i>"
        )
        units_note.setWordWrap(True)
        layout.addWidget(units_note)
        self._message = MessageArea()
        layout.addWidget(self._message)
        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)
        layout.addWidget(self._buttons)
        self.add_layer(
            SoilLayer(
                top=0.0,
                bottom=30.0 * length_scale(UnitSystem.SI_M_N, units),
                kind="clay",
                unit_weight=8.0 * self._kn_m3,
                su=40.0 * self._kpa,
                k=24e3 * self._kn_m3,
            )
        )

    def _field(self, value: float, *, minimum: float = 1e-12) -> FloatField:
        field = FloatField()
        field.setRange(minimum, 1e18)
        field.setValue(value)
        field.valueChanged.connect(self._refresh)
        return field

    # ── layers ──────────────────────────────────────────────────────
    def add_layer(self, layer: SoilLayer) -> None:
        self._table.blockSignals(True)
        row = self._table.rowCount()
        self._table.insertRow(row)
        kind = QComboBox()
        kind.addItems(["clay", "sand"])
        kind.setCurrentText(layer.kind)
        kind.currentIndexChanged.connect(self._refresh)
        values = (layer.top, layer.bottom, None, layer.unit_weight, layer.su, layer.phi, layer.k)
        for column, value in enumerate(values):
            if column == 2:
                self._table.setCellWidget(row, column, kind)
            else:
                self._table.setItem(row, column, QTableWidgetItem(f"{value:g}"))
        self._table.blockSignals(False)
        self._refresh()

    def _add_default_layer(self) -> None:
        bottom = 0.0
        for row in range(self._table.rowCount()):
            bottom = max(bottom, self._number(row, 1))
        self.add_layer(
            SoilLayer(
                top=bottom,
                bottom=bottom + 10.0,
                kind="sand",
                unit_weight=10.0 * self._kn_m3,
                phi=32.0,
                k=24e3 * self._kn_m3,
            )
        )

    def _remove_layer(self) -> None:
        row = self._table.currentRow()
        if row >= 0 and self._table.rowCount() > 1:
            self._table.removeRow(row)
            self._refresh()

    def _number(self, row: int, column: int) -> float:
        item = self._table.item(row, column)
        try:
            return float(item.text()) if item is not None else 0.0
        except ValueError:
            return float("nan")

    def layers(self) -> tuple[SoilLayer, ...]:
        out = []
        for row in range(self._table.rowCount()):
            widget = self._table.cellWidget(row, 2)
            kind = widget.currentText() if isinstance(widget, QComboBox) else "clay"
            out.append(
                SoilLayer(
                    top=self._number(row, 0),
                    bottom=self._number(row, 1),
                    kind=kind,  # type: ignore[arg-type]
                    unit_weight=self._number(row, 3),
                    su=self._number(row, 4),
                    phi=self._number(row, 5),
                    k=self._number(row, 6),
                )
            )
        return tuple(out)

    # ── result ──────────────────────────────────────────────────────
    def springs(self) -> PileSprings | None:
        return self._result

    def _refresh(self) -> None:
        ok = self._buttons.button(QDialogButtonBox.StandardButton.Ok)
        self._result = None
        try:
            spec = PileSpec(
                diameter=self._diameter.value(),
                ground_level=self._ground.value(),
                layers=self.layers(),
                stress_unit=self._kpa,
            )
            project = self._project
            self._result = pile_springs(
                project,
                self._element_ids,
                spec,
                first_node_id=project.next_node_id(),
                first_material_id=project.next_material_id(),
                first_element_id=project.next_element_id(),
            )
        except ValueError as exc:
            self._message.show_message(str(exc), "error")
            ok.setEnabled(False)
            return
        self._message.show_message(" ".join(self._result.notes), "info")
        ok.setEnabled(bool(self._result.elements))
