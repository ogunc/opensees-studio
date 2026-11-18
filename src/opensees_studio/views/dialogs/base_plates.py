"""Design → Base Plates: every column base checked over the design load sets.

One row per column base (:mod:`services.base_plates`): the column, the support
type the restraint gives (pinned → concentric, fixed → axial force and moment),
the plate, and the governing ratio with its check and load set. The plate and
rods of the selected rows are edited below; **Size tp** picks the thinnest
standard plate that passes. Nothing is stored until OK, which keeps the plates
in ``Project.design`` with one undoable command.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from opensees_studio.core.design.base_plate import ROD_GRADES, BasePlateDesign
from opensees_studio.core.design.settings import DesignSettings
from opensees_studio.core.design.steel_grades import STEEL_GRADES
from opensees_studio.core.help import TOPIC_PROPERTY
from opensees_studio.core.units import labels_for
from opensees_studio.services.base_plates import (
    BaseResult,
    ColumnBase,
    check_bases,
    column_bases,
    default_design,
    size_thickness,
)
from opensees_studio.views.dialogs.design_basis import _ok_cancel
from opensees_studio.views.float_field import FloatField
from opensees_studio.views.screen_fit import FittedDialog

_COLUMNS = ["Node", "Column", "Support", "N × B × tp", "Ratio", "Governing", "Load set"]
_LENGTHS = (
    ("n_length", "Plate length N (along d)"),
    ("b_width", "Plate width B"),
    ("tp", "Plate thickness tp"),
    ("rod_diameter", "Rod diameter"),
    ("rod_offset", "Rod line offset f"),
    ("rod_spacing", "Rod spacing along B"),
    ("edge_distance", "Rod edge distance ca"),
    ("embedment", "Rod embedment hef"),
)


class BasePlatesDialog(FittedDialog):
    """The column bases, their plates and the governing ratio of each."""

    def __init__(
        self, project: Any, results: dict[int, Any], parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._project = project
        self._results = results
        self._base_settings = project.design or DesignSettings()
        self.setWindowTitle("Base Plates (AISC DG1, ACI 318-19 Ch. 17)")
        self.setProperty(TOPIC_PROPERTY, "design.base_plates")
        units = project.meta.units
        self._bases: list[ColumnBase] = column_bases(project, self._base_settings)
        saved = {d.node_id: d for d in self._base_settings.base_plates}
        self._designs: dict[int, BasePlateDesign] = {
            b.node_id: saved.get(b.node_id) or default_design(b, units) for b in self._bases
        }
        layout = QVBoxLayout(self)
        intro = QLabel(
            "Every support with a column on it. A base whose rotations are free is checked "
            "concentric; a fixed one with its moment about the column's major axis. Every "
            "alternative of the design load sets is checked (the direct analysis cases when "
            "they exist)."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self._table = QTableWidget(len(self._bases), len(_COLUMNS))
        self._table.setHorizontalHeaderLabels(_COLUMNS)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.itemSelectionChanged.connect(self._show_selected)
        layout.addWidget(self._table)

        lab = labels_for(units)
        form = QFormLayout()
        self._fields: dict[str, FloatField] = {}
        for key, label in _LENGTHS:
            widget = FloatField()
            widget.setRange(1e-9, 1e18)
            form.addRow(f"{label} [{lab.length}]:", widget)
            self._fields[key] = widget
        self._fc = FloatField()
        self._fc.setRange(1e-9, 1e18)
        form.addRow(f"Concrete f'c [{lab.stress}]:", self._fc)
        self._a2 = FloatField()
        self._a2.setRange(1.0, 4.0)
        form.addRow("A2 / A1 (pier area over plate area):", self._a2)
        self._plate_grade = QComboBox()
        for key, grade in STEEL_GRADES.items():
            self._plate_grade.addItem(grade.label, key)
        form.addRow("Plate steel:", self._plate_grade)
        self._rod_grade = QComboBox()
        for key, (label, _futa) in ROD_GRADES.items():
            self._rod_grade.addItem(label, key)
        form.addRow("Rod grade:", self._rod_grade)
        self._rods_total = QSpinBox()
        self._rods_total.setRange(2, 32)
        form.addRow("Rods in all:", self._rods_total)
        self._rods_tension = QSpinBox()
        self._rods_tension.setRange(1, 16)
        form.addRow("Rods on the tension side:", self._rods_tension)
        layout.addLayout(form)
        buttons = QHBoxLayout()
        self._apply = QPushButton("Apply to the selected bases")
        self._apply.clicked.connect(self.apply_to_selected)
        self._size = QPushButton("Size tp of the selected bases")
        self._size.clicked.connect(self.size_selected)
        buttons.addWidget(self._apply)
        buttons.addWidget(self._size)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        self._summary = QLabel()
        self._summary.setWordWrap(True)
        layout.addWidget(self._summary)
        layout.addWidget(_ok_cancel(self))
        self.run_check()
        if self._bases:
            self._table.selectRow(0)

    # ── table ────────────────────────────────────────────────────────
    def run_check(self) -> list[BaseResult]:
        results = check_bases(
            self._project, self._results, self._base_settings, designs=self._designs
        )
        by_node = {r.node_id: r for r in results}
        for row, base in enumerate(self._bases):
            design = self._designs[base.node_id]
            result = by_node[base.node_id]
            values = [
                str(base.node_id),
                base.shape,
                base.support,
                f"{design.n_length:.4g} × {design.b_width:.4g} × {design.tp:.4g}",
                f"{result.ratio:.3f}" if result.status != "not checked" else "-",
                result.governing or result.status,
                result.load_set,
            ]
            for col, text in enumerate(values):
                item = QTableWidgetItem(text)
                if result.status == "NG":
                    item.setForeground(QBrush(QColor("#c0392b")))
                if result.notes:
                    item.setToolTip("\n".join(result.notes))
                self._table.setItem(row, col, item)
        self._table.resizeColumnsToContents()
        failing = sum(1 for r in results if r.status == "NG")
        self._summary.setText(
            f"{len(results)} column base(s), {failing} over the limit."
            if results
            else "No support with a column of an AISC I-shape, HSS or pipe."
        )
        self._last = results
        return results

    def _selected_nodes(self) -> list[int]:
        rows = sorted({index.row() for index in self._table.selectedIndexes()})
        return [self._bases[r].node_id for r in rows]

    def _show_selected(self) -> None:
        nodes = self._selected_nodes()
        if not nodes:
            return
        design = self._designs[nodes[0]]
        for key, widget in self._fields.items():
            widget.setValue(float(getattr(design, key)))
        self._fc.setValue(design.fc)
        self._a2.setValue(design.a2_ratio)
        self._plate_grade.setCurrentIndex(self._plate_grade.findData(design.plate_grade))
        self._rod_grade.setCurrentIndex(self._rod_grade.findData(design.rod_grade))
        self._rods_total.setValue(design.rods_total)
        self._rods_tension.setValue(design.rods_tension)

    def _form_values(self) -> dict[str, Any]:
        values: dict[str, Any] = {key: w.value() for key, w in self._fields.items()}
        values.update(
            fc=self._fc.value(),
            a2_ratio=self._a2.value(),
            plate_grade=self._plate_grade.currentData(),
            rod_grade=self._rod_grade.currentData(),
            rods_total=self._rods_total.value(),
            rods_tension=min(self._rods_tension.value(), self._rods_total.value()),
        )
        return values

    def apply_to_selected(self) -> None:
        values = self._form_values()
        for node in self._selected_nodes():
            self._designs[node] = self._designs[node].model_copy(update=values)
        self.run_check()

    def size_selected(self) -> None:
        settings = self._base_settings
        missing: list[int] = []
        for node in self._selected_nodes():
            tp = size_thickness(self._project, self._results, settings, self._designs[node])
            if tp is None:
                missing.append(node)
            else:
                self._designs[node] = self._designs[node].model_copy(update={"tp": tp})
        self.run_check()
        self._show_selected()
        if missing:
            self._summary.setText(
                self._summary.text() + f" No standard thickness up to 4 in passes at node(s) "
                f"{', '.join(map(str, missing))}: make the plate larger."
            )

    def designs(self) -> dict[int, BasePlateDesign]:
        return dict(self._designs)

    def settings(self) -> DesignSettings:
        """The design settings with the plates of every base (defaults stay unsaved)."""
        units = self._project.meta.units
        plates = [
            design
            for base in self._bases
            if (design := self._designs[base.node_id]) != default_design(base, units)
        ]
        return self._base_settings.model_copy(update={"base_plates": plates})
