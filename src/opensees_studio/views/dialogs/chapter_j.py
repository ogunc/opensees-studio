"""Design → Connection Checks: AISC 360 Chapter J limit states."""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from opensees_studio.core.aisc import SOURCE_UNITS
from opensees_studio.core.design.chapter_j_model import ChapterJCheck
from opensees_studio.core.help import TOPIC_PROPERTY
from opensees_studio.core.units import force_scale, length_scale, stress_scale
from opensees_studio.views.float_field import FloatField
from opensees_studio.views.screen_fit import FittedDialog, scroll_area

_TYPES = (
    ("Fillet weld (J2.4)", "fillet_weld"),
    ("Bolt shear (J3.1)", "bolt_shear"),
    ("Bolt tension (J3.1)", "bolt_tension"),
    ("Bolt bearing/tearout (J3.6)", "bolt_bearing"),
    ("Slip-critical (J3.4)", "slip_critical"),
    ("Plate shear yielding (J4.3)", "plate_shear_yielding"),
    ("Plate shear rupture (J4.4)", "plate_shear_rupture"),
    ("Block shear (J4.5)", "block_shear"),
    ("Bearing strength (J7.1)", "bearing_strength"),
    ("Concrete bearing (J8)", "concrete_bearing"),
    ("Groove-welded splice (J6)", "splice"),
    ("Flange local bending (J10.1)", "flange_local_bending"),
    ("Web local yielding (J10.2)", "web_local_yielding"),
    ("Web local crippling (J10.3)", "web_local_crippling"),
    ("Web sidesway buckling (J10.4)", "web_sidesway_buckling"),
    ("Web compression buckling (J10.5)", "web_compression_buckling"),
)

_J10_TYPES = (
    "flange_local_bending",
    "web_local_yielding",
    "web_local_crippling",
    "web_sidesway_buckling",
    "web_compression_buckling",
)


class ChapterJDialog(FittedDialog):
    """Lists, adds, edits and removes AISC 360 Chapter J checks."""

    def __init__(self, project: Any, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._project = project
        self._items = [check.model_copy() for check in project.chapter_j_checks]
        self._unit_l = length_scale(SOURCE_UNITS, project.meta.units)
        self._unit_s = stress_scale(SOURCE_UNITS, project.meta.units)
        self._unit_f = force_scale(SOURCE_UNITS, project.meta.units)
        self.setWindowTitle("Connection Checks - AISC 360 Chapter J")
        self.setProperty(TOPIC_PROPERTY, "design.chapter_j")
        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(
                "One AISC 360 Chapter J limit state per row. Only the fields used "
                "by the selected check are read; the demand is Vu or Tu."
            )
        )
        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["Check", "Name", "Type", "Demand"])
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setMinimumHeight(120)
        self._table.itemSelectionChanged.connect(self._load_selected)
        layout.addWidget(self._table)

        form = QFormLayout()
        self._name = QLineEdit()
        form.addRow("Name:", self._name)
        self._type = QComboBox()
        for label, key in _TYPES:
            self._type.addItem(label, key)
        self._type.currentIndexChanged.connect(self._update_fields)
        form.addRow("Check type:", self._type)
        self._demand = FloatField()
        self._demand.setRange(1e-9, 1e12)
        form.addRow("Demand Vu / Tu:", self._demand)
        layout.addLayout(form)

        groups = QWidget()
        groups_layout = QVBoxLayout(groups)
        groups_layout.setContentsMargins(0, 0, 0, 0)

        self._weld_group = QGroupBox("Fillet weld (J2.4)")
        weld = QFormLayout(self._weld_group)
        self._fexx = FloatField()
        self._fexx.setRange(1e-6, 1e9)
        self._fexx.setValue(70.0 * self._unit_s)
        weld.addRow("Fexx:", self._fexx)
        self._weld_leg = FloatField()
        self._weld_leg.setRange(1e-6, 1e9)
        self._weld_leg.setValue(0.25 * self._unit_l)
        weld.addRow("Weld leg:", self._weld_leg)
        self._weld_length = FloatField()
        self._weld_length.setRange(1e-6, 1e9)
        self._weld_length.setValue(10.0 * self._unit_l)
        weld.addRow("Weld length:", self._weld_length)
        self._weld_both = QCheckBox("Both sides")
        self._weld_both.setChecked(True)
        weld.addRow("Sides:", self._weld_both)
        self._filler_thickness = FloatField()
        self._filler_thickness.setRange(1e-9, 1e9)
        self._filler_thickness.setValue(0.0)
        weld.addRow("Filler thickness (J5):", self._filler_thickness)
        self._filler_transfers = QCheckBox("The filler transfers force")
        weld.addRow("Filler:", self._filler_transfers)
        groups_layout.addWidget(self._weld_group)

        self._bolt_group = QGroupBox("Bolts (J3.1 / J3.6)")
        bolt = QFormLayout(self._bolt_group)
        self._fn = FloatField()
        self._fn.setRange(1e-6, 1e9)
        self._fn.setValue(54.0 * self._unit_s)
        bolt.addRow("Fnv / Fnt:", self._fn)
        self._bolt_diameter = FloatField()
        self._bolt_diameter.setRange(1e-6, 1e9)
        self._bolt_diameter.setValue(0.75 * self._unit_l)
        bolt.addRow("Bolt diameter:", self._bolt_diameter)
        self._bolt_count = FloatField()
        self._bolt_count.setRange(1.0, 1e6)
        self._bolt_count.setValue(4.0)
        bolt.addRow("Bolt count:", self._bolt_count)
        self._fu = FloatField()
        self._fu.setRange(1e-6, 1e9)
        self._fu.setValue(65.0 * self._unit_s)
        bolt.addRow("Fu (bearing):", self._fu)
        self._thickness = FloatField()
        self._thickness.setRange(1e-6, 1e9)
        self._thickness.setValue(0.5 * self._unit_l)
        bolt.addRow("Plate thickness:", self._thickness)
        self._edge = FloatField()
        self._edge.setRange(1e-6, 1e9)
        self._edge.setValue(1.5 * self._unit_l)
        bolt.addRow("Edge distance:", self._edge)
        self._hole = FloatField()
        self._hole.setRange(1e-6, 1e9)
        self._hole.setValue(0.8125 * self._unit_l)
        bolt.addRow("Hole diameter:", self._hole)
        self._deformation = QCheckBox("Deformation is a design consideration")
        self._deformation.setChecked(True)
        bolt.addRow("Bearing:", self._deformation)
        self._bolt_filler = FloatField()
        self._bolt_filler.setRange(1e-9, 1e9)
        self._bolt_filler.setValue(0.0)
        bolt.addRow("Filler thickness (J5.2):", self._bolt_filler)
        groups_layout.addWidget(self._bolt_group)

        self._slip_group = QGroupBox("Slip-critical (J3.4)")
        slip = QFormLayout(self._slip_group)
        self._mu = FloatField()
        self._mu.setRange(1e-6, 1.0)
        self._mu.setValue(0.3)
        slip.addRow("Slip coefficient mu:", self._mu)
        self._tb = FloatField()
        self._tb.setRange(1e-6, 1e12)
        self._tb.setValue(28.0 * self._unit_f)
        slip.addRow("Pretension Tb:", self._tb)
        self._slip_planes = FloatField()
        self._slip_planes.setRange(1.0, 1e6)
        self._slip_planes.setValue(1.0)
        slip.addRow("Slip planes:", self._slip_planes)
        self._hole_type = QComboBox()
        self._hole_type.addItem("Standard", "standard")
        self._hole_type.addItem("Oversized", "oversized")
        self._hole_type.addItem("Long-slotted", "long_slotted")
        slip.addRow("Hole type:", self._hole_type)
        groups_layout.addWidget(self._slip_group)

        self._plate_group = QGroupBox("Plate and block shear (J4.3 / J4.4 / J4.5)")
        plate = QFormLayout(self._plate_group)
        self._fy = FloatField()
        self._fy.setRange(1e-6, 1e9)
        self._fy.setValue(50.0 * self._unit_s)
        plate.addRow("Fy:", self._fy)
        self._agv = FloatField()
        self._agv.setRange(1e-9, 1e12)
        self._agv.setValue(6.0 * self._unit_l**2)
        plate.addRow("Agv:", self._agv)
        self._anv = FloatField()
        self._anv.setRange(1e-9, 1e12)
        self._anv.setValue(4.375 * self._unit_l**2)
        plate.addRow("Anv:", self._anv)
        self._ant = FloatField()
        self._ant.setRange(1e-9, 1e12)
        self._ant.setValue(1.0 * self._unit_l**2)
        plate.addRow("Ant:", self._ant)
        self._uniform = QCheckBox("Uniform tension (Ubs = 1.0)")
        self._uniform.setChecked(True)
        plate.addRow("Block shear:", self._uniform)
        self._apb = FloatField()
        self._apb.setRange(1e-9, 1e12)
        self._apb.setValue(2.0 * self._unit_l**2)
        plate.addRow("Projected bearing area Apb:", self._apb)
        self._fc = FloatField()
        self._fc.setRange(1e-9, 1e12)
        self._fc.setValue(4.0 * self._unit_s)
        plate.addRow("Concrete f'c:", self._fc)
        self._a1 = FloatField()
        self._a1.setRange(1e-9, 1e12)
        self._a1.setValue(100.0 * self._unit_l**2)
        plate.addRow("Concrete A1:", self._a1)
        self._a2 = FloatField()
        self._a2.setRange(1e-9, 1e12)
        self._a2.setValue(0.0)
        plate.addRow("Concrete A2 (0 = full area):", self._a2)
        self._splice_nominal = FloatField()
        self._splice_nominal.setRange(1e-9, 1e12)
        self._splice_nominal.setValue(1000.0 * self._unit_f)
        plate.addRow("Splice nominal strength:", self._splice_nominal)
        groups_layout.addWidget(self._plate_group)

        self._j10_group = QGroupBox("Concentrated forces (J10.1 / J10.2 / J10.3 / J10.4 / J10.5)")
        j10 = QFormLayout(self._j10_group)
        self._j10_fy = FloatField()
        self._j10_fy.setRange(1e-6, 1e9)
        self._j10_fy.setValue(50.0 * self._unit_s)
        j10.addRow("Fyf / Fyw:", self._j10_fy)
        self._j10_tf = FloatField()
        self._j10_tf.setRange(1e-6, 1e9)
        self._j10_tf.setValue(0.5 * self._unit_l)
        j10.addRow("Flange thickness tf:", self._j10_tf)
        self._j10_tw = FloatField()
        self._j10_tw.setRange(1e-6, 1e9)
        self._j10_tw.setValue(0.3 * self._unit_l)
        j10.addRow("Web thickness tw:", self._j10_tw)
        self._j10_bf = FloatField()
        self._j10_bf.setRange(1e-6, 1e9)
        self._j10_bf.setValue(6.0 * self._unit_l)
        j10.addRow("Flange width bf:", self._j10_bf)
        self._j10_h = FloatField()
        self._j10_h.setRange(1e-6, 1e9)
        self._j10_h.setValue(12.0 * self._unit_l)
        j10.addRow("Clear web height h:", self._j10_h)
        self._j10_d = FloatField()
        self._j10_d.setRange(1e-6, 1e9)
        self._j10_d.setValue(14.0 * self._unit_l)
        j10.addRow("Member depth d:", self._j10_d)
        self._j10_k = FloatField()
        self._j10_k.setRange(1e-6, 1e9)
        self._j10_k.setValue(1.0 * self._unit_l)
        j10.addRow("Fillet k:", self._j10_k)
        self._j10_lb = FloatField()
        self._j10_lb.setRange(1e-6, 1e9)
        self._j10_lb.setValue(2.0 * self._unit_l)
        j10.addRow("Bearing length lb / unbraced Lb:", self._j10_lb)
        self._j10_end = FloatField()
        self._j10_end.setRange(1e-6, 1e9)
        self._j10_end.setValue(20.0 * self._unit_l)
        j10.addRow("Distance to end:", self._j10_end)
        self._j10_e = FloatField()
        self._j10_e.setRange(1e-6, 1e12)
        self._j10_e.setValue(29000.0 * self._unit_s)
        j10.addRow("Elastic modulus E:", self._j10_e)
        self._j10_qf = FloatField()
        self._j10_qf.setRange(1e-6, 1e6)
        self._j10_qf.setValue(1.0)
        j10.addRow("Chord-stress Qf:", self._j10_qf)
        self._j10_mr = FloatField()
        self._j10_mr.setRange(1e-9, 1e18)
        self._j10_mr.setValue(1000.0 * self._unit_f * self._unit_l)
        j10.addRow("Required moment Mr:", self._j10_mr)
        self._j10_sx = FloatField()
        self._j10_sx.setRange(1e-9, 1e18)
        self._j10_sx.setValue(100.0 * self._unit_l**3)
        j10.addRow("Section modulus Sx:", self._j10_sx)
        self._j10_restrained = QCheckBox("Compression flange restrained against rotation")
        self._j10_restrained.setChecked(True)
        j10.addRow("Sidesway:", self._j10_restrained)
        groups_layout.addWidget(self._j10_group)
        groups_layout.addStretch(1)
        layout.addWidget(scroll_area(groups, vertical_only=True), 1)

        row = QHBoxLayout()
        add = QPushButton("Add")
        add.clicked.connect(self._add)
        update = QPushButton("Update selected")
        update.clicked.connect(self._update)
        remove = QPushButton("Remove selected")
        remove.clicked.connect(self._remove)
        row.addWidget(add)
        row.addWidget(update)
        row.addWidget(remove)
        row.addStretch(1)
        layout.addLayout(row)

        self._summary = QLabel()
        self._summary.setWordWrap(True)
        layout.addWidget(self._summary)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._refresh()
        self._update_fields()

    def _update_fields(self) -> None:
        kind = str(self._type.currentData())
        self._weld_group.setEnabled(kind == "fillet_weld")
        self._bolt_group.setEnabled(kind in ("bolt_shear", "bolt_tension", "bolt_bearing"))
        self._slip_group.setEnabled(kind == "slip_critical")
        self._plate_group.setEnabled(
            kind
            in (
                "plate_shear_yielding",
                "plate_shear_rupture",
                "block_shear",
                "bearing_strength",
                "concrete_bearing",
                "splice",
            )
        )
        self._j10_group.setEnabled(kind in _J10_TYPES)
        self._summary.setText(
            "Only the fields used by the selected check are read. "
            "The report shows the nominal, available and ratio."
        )

    def _next_id(self) -> int:
        used = {item.id for item in self._items}
        return max(used, default=0) + 1

    def _candidate(self) -> ChapterJCheck:
        kind = str(self._type.currentData())
        is_j10 = kind in _J10_TYPES
        filler = (
            self._filler_thickness.value()
            if kind == "fillet_weld"
            else self._bolt_filler.value()
            if kind == "bolt_shear"
            else 0.0
        )
        return ChapterJCheck(
            id=self._next_id(),
            name=self._name.text().strip(),
            check_type=self._type.currentData(),
            demand=self._demand.value(),
            fexx=self._fexx.value(),
            weld_leg=self._weld_leg.value(),
            weld_length=self._weld_length.value(),
            weld_both_sides=self._weld_both.isChecked(),
            filler_thickness=filler or None,
            filler_transfers_force=self._filler_transfers.isChecked(),
            fn=self._fn.value(),
            bolt_diameter=self._bolt_diameter.value(),
            bolt_count=int(self._bolt_count.value()),
            fu=self._fu.value(),
            thickness=self._thickness.value(),
            edge_distance=self._edge.value(),
            hole_diameter=self._hole.value(),
            deformation=self._deformation.isChecked(),
            mu=self._mu.value(),
            tb=self._tb.value(),
            slip_planes=int(self._slip_planes.value()),
            hole_type=self._hole_type.currentData(),
            fy=self._j10_fy.value() if is_j10 else self._fy.value(),
            agv=self._agv.value(),
            anv=self._anv.value(),
            ant=self._ant.value(),
            uniform_tension=self._uniform.isChecked(),
            apb=self._apb.value(),
            fc=self._fc.value(),
            a1=self._a1.value(),
            a2=self._a2.value() or None,
            splice_nominal=self._splice_nominal.value(),
            flange_thickness=self._j10_tf.value() if is_j10 else None,
            web_thickness=self._j10_tw.value() if is_j10 else None,
            flange_width=self._j10_bf.value() if is_j10 else None,
            clear_web_height=self._j10_h.value() if is_j10 else None,
            member_depth=self._j10_d.value() if is_j10 else None,
            fillet_k=self._j10_k.value() if is_j10 else None,
            bearing_length=self._j10_lb.value() if is_j10 else None,
            distance_to_end=self._j10_end.value() if is_j10 else None,
            elastic_modulus=self._j10_e.value() if is_j10 else None,
            chord_factor=self._j10_qf.value() if is_j10 else 1.0,
            required_moment=self._j10_mr.value() if is_j10 else None,
            section_modulus=self._j10_sx.value() if is_j10 else None,
            flange_restrained=self._j10_restrained.isChecked() if is_j10 else True,
        )

    def _add(self) -> None:
        self._items.append(self._candidate())
        self._refresh()

    def _update(self) -> None:
        row = self._table.currentRow()
        if row < 0:
            return
        candidate = self._candidate()
        candidate.id = self._items[row].id
        self._items[row] = candidate
        self._refresh()

    def _remove(self) -> None:
        row = self._table.currentRow()
        if row >= 0:
            del self._items[row]
            self._refresh()

    def _refresh(self) -> None:
        self._table.setRowCount(len(self._items))
        for row, item in enumerate(self._items):
            values = (item.id, item.name or "-", item.check_type, item.demand)
            for column, value in enumerate(values):
                self._table.setItem(row, column, QTableWidgetItem(str(value)))
        self._summary.setText(f"{len(self._items)} connection check(s).")

    def _load_selected(self) -> None:
        row = self._table.currentRow()
        if row < 0 or row >= len(self._items):
            return
        item = self._items[row]
        self._name.setText(item.name)
        index = self._type.findData(item.check_type)
        if index >= 0:
            self._type.setCurrentIndex(index)
        self._demand.setValue(item.demand)
        self._fexx.setValue(item.fexx or 70.0 * self._unit_s)
        self._weld_leg.setValue(item.weld_leg or 0.25 * self._unit_l)
        self._weld_length.setValue(item.weld_length or 10.0 * self._unit_l)
        self._weld_both.setChecked(item.weld_both_sides)
        self._filler_thickness.setValue(item.filler_thickness or 0.0)
        self._filler_transfers.setChecked(item.filler_transfers_force)
        self._fn.setValue(item.fn or 54.0 * self._unit_s)
        self._bolt_diameter.setValue(item.bolt_diameter or 0.75 * self._unit_l)
        self._bolt_count.setValue(float(item.bolt_count or 4))
        self._fu.setValue(item.fu or 65.0 * self._unit_s)
        self._thickness.setValue(item.thickness or 0.5 * self._unit_l)
        self._edge.setValue(item.edge_distance or 1.5 * self._unit_l)
        self._hole.setValue(item.hole_diameter or 0.8125 * self._unit_l)
        self._deformation.setChecked(item.deformation)
        self._bolt_filler.setValue(item.filler_thickness or 0.0)
        self._mu.setValue(item.mu or 0.3)
        self._tb.setValue(item.tb or 28.0 * self._unit_f)
        self._slip_planes.setValue(float(item.slip_planes or 1))
        index = self._hole_type.findData(item.hole_type)
        if index >= 0:
            self._hole_type.setCurrentIndex(index)
        self._fy.setValue(item.fy or 50.0 * self._unit_s)
        self._agv.setValue(item.agv or 6.0 * self._unit_l**2)
        self._anv.setValue(item.anv or 4.375 * self._unit_l**2)
        self._ant.setValue(item.ant or 1.0 * self._unit_l**2)
        self._uniform.setChecked(item.uniform_tension)
        self._apb.setValue(item.apb or 2.0 * self._unit_l**2)
        self._fc.setValue(item.fc or 4.0 * self._unit_s)
        self._a1.setValue(item.a1 or 100.0 * self._unit_l**2)
        self._a2.setValue(item.a2 or 0.0)
        self._splice_nominal.setValue(item.splice_nominal or 1000.0 * self._unit_f)
        self._j10_fy.setValue(item.fy or 50.0 * self._unit_s)
        self._j10_tf.setValue(item.flange_thickness or 0.5 * self._unit_l)
        self._j10_tw.setValue(item.web_thickness or 0.3 * self._unit_l)
        self._j10_bf.setValue(item.flange_width or 6.0 * self._unit_l)
        self._j10_h.setValue(item.clear_web_height or 12.0 * self._unit_l)
        self._j10_d.setValue(item.member_depth or 14.0 * self._unit_l)
        self._j10_k.setValue(item.fillet_k or 1.0 * self._unit_l)
        self._j10_lb.setValue(item.bearing_length or 2.0 * self._unit_l)
        self._j10_end.setValue(item.distance_to_end or 20.0 * self._unit_l)
        self._j10_e.setValue(item.elastic_modulus or 29000.0 * self._unit_s)
        self._j10_qf.setValue(item.chord_factor)
        self._j10_mr.setValue(item.required_moment or 1000.0 * self._unit_f * self._unit_l)
        self._j10_sx.setValue(item.section_modulus or 100.0 * self._unit_l**3)
        self._j10_restrained.setChecked(item.flange_restrained)
        self._update_fields()

    def checks(self) -> list[ChapterJCheck]:
        """The checks as the dialog shows them."""
        return [item.model_copy() for item in self._items]
