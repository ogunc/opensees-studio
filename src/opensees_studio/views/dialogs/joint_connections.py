"""Design → Connections by Joint: every member end, its topology and its connection.

One row per member end (:mod:`services.joint_connections`): the joint, the end,
what it frames into, the connection that fits it (from the topology, whether
the end is released, and the seismic system), and for a shear tab the governing
ratio over the design load sets. The shear tab of the selected rows is edited
below. Nothing is stored until OK, which keeps the shear tabs in
``Project.design`` with one undoable command.
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

from opensees_studio.core.design.joints import SHEAR_TAB
from opensees_studio.core.design.settings import DesignSettings
from opensees_studio.core.design.shear_tab import BOLT_GRADES, ShearTabDesign
from opensees_studio.core.design.steel_grades import STEEL_GRADES
from opensees_studio.core.help import TOPIC_PROPERTY
from opensees_studio.core.units import labels_for
from opensees_studio.services.joint_connections import (
    ConnectionResult,
    connection_report,
    default_tab,
)
from opensees_studio.services.steel_design import shape_in_units
from opensees_studio.views.dialogs.design_basis import _ok_cancel
from opensees_studio.views.float_field import FloatField
from opensees_studio.views.screen_fit import FittedDialog

_COLUMNS = ["Node", "End", "Member", "Topology", "Connection", "Status", "Ratio", "Vu", "Governing"]
_LENGTHS = (
    ("bolt_diameter", "Bolt diameter"),
    ("spacing", "Bolt spacing s"),
    ("edge_vertical", "Vertical edge distance Lev"),
    ("edge_horizontal", "Horizontal edge distance Leh"),
    ("weld_to_bolts", "Weld to bolt line a"),
    ("tp", "Plate thickness tp"),
    ("weld_leg", "Weld leg w"),
)


class JointConnectionsDialog(FittedDialog):
    """The connections of the frame and the shear tabs of its simple beam ends."""

    def __init__(
        self, project: Any, results: dict[int, Any], parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._project = project
        self._results = results
        self._settings = project.design or DesignSettings()
        self.setWindowTitle("Connections by Joint")
        self.setProperty(TOPIC_PROPERTY, "design.joint_connections")
        self._tabs: dict[tuple[int, str], ShearTabDesign] = {
            (t.element_id, t.end): t for t in self._settings.shear_tabs
        }
        layout = QVBoxLayout(self)
        intro = QLabel(
            "Every member end, classified by what it frames into. A beam end whose major "
            "moment is released takes a shear tab, checked here over the design load sets; "
            "the other connections are designed in the dialog named."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self._table = QTableWidget(0, len(_COLUMNS))
        self._table.setHorizontalHeaderLabels(_COLUMNS)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.itemSelectionChanged.connect(self._show_selected)
        layout.addWidget(self._table)

        lab = labels_for(project.meta.units)
        form = QFormLayout()
        self._bolts = QSpinBox()
        self._bolts.setRange(2, 12)
        form.addRow("Bolts in the row n:", self._bolts)
        self._bolt_grade = QComboBox()
        for key, (label, _fnv) in BOLT_GRADES.items():
            self._bolt_grade.addItem(label, key)
        form.addRow("Bolt grade:", self._bolt_grade)
        self._fields: dict[str, FloatField] = {}
        for key, label in _LENGTHS:
            widget = FloatField()
            widget.setRange(1e-9, 1e18)
            form.addRow(f"{label} [{lab.length}]:", widget)
            self._fields[key] = widget
        self._plate_grade = QComboBox()
        for key, grade in STEEL_GRADES.items():
            self._plate_grade.addItem(grade.label, key)
        form.addRow("Plate steel:", self._plate_grade)
        self._fexx = FloatField()
        self._fexx.setRange(1e-9, 1e18)
        form.addRow(f"Weld metal Fexx [{lab.stress}]:", self._fexx)
        layout.addLayout(form)
        row = QHBoxLayout()
        self._apply = QPushButton("Apply to the selected shear tabs")
        self._apply.clicked.connect(self.apply_to_selected)
        row.addWidget(self._apply)
        row.addStretch(1)
        layout.addLayout(row)
        self._summary = QLabel()
        self._summary.setWordWrap(True)
        layout.addWidget(self._summary)
        layout.addWidget(_ok_cancel(self))
        self.run_check()

    # ── table ────────────────────────────────────────────────────────
    def run_check(self) -> list[ConnectionResult]:
        self._rows = connection_report(
            self._project, self._results, self._settings, tabs=self._tabs
        )
        self._table.setRowCount(len(self._rows))
        for r, result in enumerate(self._rows):
            c = result.connection
            values = [
                str(c.node_id),
                f"{c.element_id} {c.end}",
                c.member_role,
                c.topology + (" (simple)" if c.simple else ""),
                c.suggested,
                result.status,
                f"{result.ratio:.3f}" if result.status in ("OK", "NG") else "",
                f"{result.vu:.4g}" if result.status in ("OK", "NG") else "",
                result.governing,
            ]
            for col, text in enumerate(values):
                item = QTableWidgetItem(text)
                if result.status == "NG":
                    item.setForeground(QBrush(QColor("#c0392b")))
                if result.notes:
                    item.setToolTip("\n".join(result.notes))
                self._table.setItem(r, col, item)
        self._table.resizeColumnsToContents()
        tabs = [x for x in self._rows if x.status in ("OK", "NG")]
        failing = sum(1 for x in tabs if x.status == "NG")
        self._summary.setText(
            f"{len(self._rows)} connection(s); {len(tabs)} shear tab(s) checked, "
            f"{failing} over the limit."
        )
        return self._rows

    def _selected_tabs(self) -> list[ConnectionResult]:
        rows = sorted({index.row() for index in self._table.selectedIndexes()})
        return [self._rows[r] for r in rows if self._rows[r].connection.suggested == SHEAR_TAB]

    def _tab_of(self, result: ConnectionResult) -> ShearTabDesign | None:
        key = result.connection.key
        if key in self._tabs:
            return self._tabs[key]
        try:
            beam = shape_in_units(
                result.beam_shape, self._project.meta.units, self._settings.built_up_by_name()
            )
        except (KeyError, ValueError):
            return None
        return default_tab(result.connection, beam, self._project.meta.units)  # type: ignore[arg-type]

    def _show_selected(self) -> None:
        selected = self._selected_tabs()
        enabled = bool(selected)
        self._apply.setEnabled(enabled)
        if not enabled:
            return
        tab = self._tab_of(selected[0])
        if tab is None:
            return
        self._bolts.setValue(tab.bolts)
        self._bolt_grade.setCurrentIndex(self._bolt_grade.findData(tab.bolt_grade))
        for key, widget in self._fields.items():
            widget.setValue(float(getattr(tab, key)))
        self._plate_grade.setCurrentIndex(self._plate_grade.findData(tab.plate_grade))
        self._fexx.setValue(tab.fexx)

    def apply_to_selected(self) -> None:
        values: dict[str, Any] = {k: w.value() for k, w in self._fields.items()}
        values.update(
            bolts=self._bolts.value(),
            bolt_grade=self._bolt_grade.currentData(),
            plate_grade=self._plate_grade.currentData(),
            fexx=self._fexx.value(),
        )
        for result in self._selected_tabs():
            tab = self._tab_of(result)
            if tab is not None:
                self._tabs[result.connection.key] = tab.model_copy(update=values)
        self.run_check()

    def settings(self) -> DesignSettings:
        """The design settings with every shear tab that differs from its starting one."""
        units = self._project.meta.units
        kept: list[ShearTabDesign] = []
        for result in self._rows:
            key = result.connection.key
            if key not in self._tabs or not result.beam_shape:
                continue
            beam = shape_in_units(result.beam_shape, units, self._settings.built_up_by_name())
            if self._tabs[key] != default_tab(result.connection, beam, units):  # type: ignore[arg-type]
                kept.append(self._tabs[key])
        return self._settings.model_copy(update={"shear_tabs": kept})
