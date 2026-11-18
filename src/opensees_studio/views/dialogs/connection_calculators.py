"""Design → Base Plate & Anchors and Design → Bolted Connection: two calculators.

* :class:`BasePlateDialog` — a column base plate after AISC Design Guide 1 with
  the anchor rods after ACI 318-19 Chapter 17 (:mod:`core.design.base_plate`).
  The demands can come from the reaction of the selected support in a solved
  case.
* :class:`BoltedConnectionDialog` — prying action of a tee or end plate and the
  most loaded bolt of an eccentrically loaded group (:mod:`core.design.bolt_groups`).

Both compute as the inputs change and keep nothing in the project.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import (
    QComboBox,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from opensees_studio.core.design.base_plate import BasePlate, check_base_plate
from opensees_studio.core.design.bolt_groups import eccentric_bolt_group, prying_action
from opensees_studio.core.help import TOPIC_PROPERTY
from opensees_studio.core.units import (
    UnitSystem,
    force_scale,
    labels_for,
    length_scale,
    stress_scale,
)
from opensees_studio.services.results import StaticResults
from opensees_studio.views.float_field import FloatField
from opensees_studio.views.screen_fit import FittedDialog, MessageArea


def _field(value: float, *, minimum: float = 0.0) -> FloatField:
    field = FloatField()
    field.setRange(minimum, 1e18)
    field.setValue(value)
    return field


class BasePlateDialog(FittedDialog):
    """Column, plate, concrete, rods and demands; the checks update as you type."""

    def __init__(
        self,
        project: Any,
        results: dict[int, Any],
        node_id: int | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Base Plate & Anchors (AISC DG1, ACI 318-19 Ch. 17)")
        self.setProperty(TOPIC_PROPERTY, "design.base_plate")
        self._project = project
        self._results = results
        self._node_id = node_id
        units = project.meta.units
        lab = labels_for(units)
        mm = length_scale(UnitSystem.SI_MM_N, units)
        mpa = stress_scale(UnitSystem.SI_MM_N, units)
        newton = force_scale(UnitSystem.SI_MM_N, units)
        self._factors = (mpa, mm, newton)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        L, S, F = lab.length, lab.stress, lab.force
        self._d = _field(308 * mm)
        self._bf = _field(305 * mm)
        self._n = _field(450 * mm)
        self._b = _field(400 * mm)
        self._tp = _field(25 * mm)
        self._fy = _field(250 * mpa)
        self._fc = _field(25 * mpa)
        self._a2 = _field(4 * 450 * 400 * mm * mm)
        self._rod_d = _field(24 * mm)
        self._futa = _field(400 * mpa)
        self._rods_t = _field(2, minimum=1)
        self._rods = _field(4, minimum=1)
        self._f = _field(170 * mm)
        self._s = _field(250 * mm)
        self._ca = _field(300 * mm)
        self._hef = _field(400 * mm)
        self._pu = _field(0.0, minimum=-1e18)
        self._mu = _field(0.0, minimum=-1e18)
        self._vu = _field(0.0, minimum=-1e18)
        rows = [
            (f"Column depth d [{L}]:", self._d),
            (f"Column flange width bf [{L}]:", self._bf),
            (f"Plate length N (along d) [{L}]:", self._n),
            (f"Plate width B [{L}]:", self._b),
            (f"Plate thickness tp [{L}]:", self._tp),
            (f"Plate Fy [{S}]:", self._fy),
            (f"Concrete f'c [{S}]:", self._fc),
            (f"Supporting concrete area A2 [{L}²]:", self._a2),
            (f"Rod diameter [{L}]:", self._rod_d),
            (f"Rod futa [{S}]:", self._futa),
            ("Rods on the tension side:", self._rods_t),
            ("Rods in all:", self._rods),
            (f"Rod line offset f from the centre [{L}]:", self._f),
            (f"Rod spacing along B [{L}]:", self._s),
            (f"Rod edge distance ca [{L}]:", self._ca),
            (f"Rod embedment hef [{L}]:", self._hef),
            (f"Pu, compression + [{F}]:", self._pu),
            (f"Mu [{F}·{L}]:", self._mu),
            (f"Vu [{F}]:", self._vu),
        ]
        for label, widget in rows:
            form.addRow(label, widget)
            widget.valueChanged.connect(self._refresh)
        layout.addLayout(form)
        self._case = QComboBox()
        for cid, result in results.items():
            if isinstance(result, StaticResults):
                self._case.addItem(f"Case {result.case_name or cid}", cid)
        load = QPushButton("Demands from the selected support")
        load.setEnabled(node_id is not None and self._case.count() > 0)
        load.clicked.connect(self._load_reaction)
        form.addRow("Case:", self._case)
        form.addRow(load)
        self._summary = QLabel()
        self._summary.setWordWrap(True)
        layout.addWidget(self._summary)
        self._message = MessageArea()
        layout.addWidget(self._message)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._refresh()

    def plate(self) -> BasePlate:
        mpa, mm, newton = self._factors
        return BasePlate(
            d=self._d.value(),
            bf=self._bf.value(),
            n_length=self._n.value(),
            b_width=self._b.value(),
            tp=self._tp.value(),
            fy=self._fy.value(),
            fc=self._fc.value(),
            a2=self._a2.value() or None,
            rods_tension=int(self._rods_t.value()),
            rods_total=int(self._rods.value()),
            rod_diameter=self._rod_d.value(),
            rod_futa=self._futa.value(),
            rod_offset=self._f.value(),
            rod_spacing=self._s.value(),
            edge_distance=self._ca.value(),
            embedment=self._hef.value(),
            mpa=mpa,
            mm=mm,
            newton=newton,
        )

    def _load_reaction(self) -> None:
        cid = self._case.currentData()
        result = self._results.get(cid)
        if self._node_id is None or not isinstance(result, StaticResults):
            return
        reaction = result.node_reaction.get(self._node_id)
        if reaction is None:
            self._message.show_message(
                "The selected joint has no reaction in that case.", "warning"
            )
            return
        row = reaction[-1]
        ndm = self._project.ndm
        vertical = row[1] if ndm == 2 else row[2]
        shear = abs(row[0]) if ndm == 2 else (row[0] ** 2 + row[1] ** 2) ** 0.5
        moment = abs(row[2]) if ndm == 2 else max(abs(row[3]), abs(row[4]))
        self._pu.setValue(float(vertical))
        self._mu.setValue(float(moment))
        self._vu.setValue(float(shear))

    def _refresh(self) -> None:
        try:
            result = check_base_plate(
                self.plate(), pu=self._pu.value(), mu=self._mu.value(), vu=self._vu.value()
            )
        except (ValueError, ZeroDivisionError) as exc:
            self._message.show_message(str(exc), "error")
            return
        lines = [f"{c.name}: <b>{c.ratio:.3f}</b> ({c.reference}) {c.value}" for c in result.checks]
        if result.eccentricity:
            lines.append(
                f"e = {result.eccentricity:.4g}, bearing length Y = {result.bearing_length:.4g}"
            )
        if result.anchor_tension:
            lines.append(f"Anchor tension T = {result.anchor_tension:.4g}")
        self._summary.setText("<br>".join(lines) or "Enter the demands.")
        governing = result.governing
        if governing is None:
            self._message.show_message(" ".join(result.notes) or "No demand yet.", "info")
        else:
            level = "error" if governing.ratio > 1.0 else "info"
            self._message.show_message(
                f"Governing: {governing.name}, ratio {governing.ratio:.3f}. "
                + " ".join(result.notes),
                level,
            )

    def governing_ratio(self) -> float:
        result = check_base_plate(
            self.plate(), pu=self._pu.value(), mu=self._mu.value(), vu=self._vu.value()
        )
        return result.governing.ratio if result.governing else 0.0


class BoltedConnectionDialog(FittedDialog):
    """Prying action of a flange, and the most loaded bolt of an eccentric group."""

    def __init__(self, project: Any, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Bolted Connection (prying, bolt group)")
        self.setProperty(TOPIC_PROPERTY, "design.bolted_connection")
        units = project.meta.units
        lab = labels_for(units)
        mm = length_scale(UnitSystem.SI_MM_N, units)
        mpa = stress_scale(UnitSystem.SI_MM_N, units)
        kn = force_scale(UnitSystem.SI_MM_N, units) * 1e3
        L, S, F = lab.length, lab.stress, lab.force
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("<b>Prying action</b> (AISC Manual Part 9)"))
        prying = QFormLayout()
        self._t = _field(16 * mm)
        self._fu = _field(450 * mpa)
        self._b_dim = _field(40 * mm)
        self._a_dim = _field(40 * mm)
        self._db = _field(20 * mm)
        self._hole = _field(22 * mm)
        self._pitch = _field(80 * mm)
        self._bolt_t = _field(150 * kn)
        self._demand = _field(80 * kn)
        for label, widget in (
            (f"Flange thickness t [{L}]:", self._t),
            (f"Flange Fu [{S}]:", self._fu),
            (f"b, bolt line to stem face [{L}]:", self._b_dim),
            (f"a, bolt line to edge [{L}]:", self._a_dim),
            (f"Bolt diameter db [{L}]:", self._db),
            (f"Hole d' [{L}]:", self._hole),
            (f"Tributary width p per bolt [{L}]:", self._pitch),
            (f"Bolt available tension φrn [{F}]:", self._bolt_t),
            (f"Tension per bolt Tu [{F}]:", self._demand),
        ):
            prying.addRow(label, widget)
            widget.valueChanged.connect(self._refresh)
        layout.addLayout(prying)
        layout.addWidget(QLabel("<b>Eccentric bolt group</b> (elastic method)"))
        group = QFormLayout()
        self._bolts = QLineEdit("0,0; 0,75; 0,150")
        self._bolts.setToolTip(f"x,y of each bolt [{L}], separated by semicolons")
        self._bolts.textChanged.connect(self._refresh)
        self._px = _field(0.0, minimum=-1e18)
        self._py = _field(200 * kn, minimum=-1e18)
        self._ex = _field(100 * mm, minimum=-1e18)
        self._ey = _field(75 * mm, minimum=-1e18)
        self._bolt_v = _field(90 * kn)
        group.addRow(f"Bolts x,y; … [{L}]:", self._bolts)
        for label, widget in (
            (f"Px [{F}]:", self._px),
            (f"Py [{F}]:", self._py),
            (f"Load at x [{L}]:", self._ex),
            (f"Load at y [{L}]:", self._ey),
            (f"Bolt available shear (min of J3.6, J3.10) [{F}]:", self._bolt_v),
        ):
            group.addRow(label, widget)
            widget.valueChanged.connect(self._refresh)
        layout.addLayout(group)
        self._summary = QLabel()
        self._summary.setWordWrap(True)
        layout.addWidget(self._summary)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._refresh()

    def _bolt_positions(self) -> list[tuple[float, float]]:
        out = []
        for chunk in self._bolts.text().split(";"):
            if chunk.strip():
                x, y = (float(v) for v in chunk.split(","))
                out.append((x, y))
        return out

    def _refresh(self) -> None:
        lines = []
        try:
            p = prying_action(
                t=self._t.value(),
                fu=self._fu.value(),
                b=self._b_dim.value(),
                a=self._a_dim.value(),
                db=self._db.value(),
                hole=self._hole.value(),
                pitch=self._pitch.value(),
                bolt_tension=self._bolt_t.value(),
                demand=self._demand.value(),
            )
            lines.append(
                f"Prying: Q = {p.q:.3f}, available B·Q = {p.available:.4g}, ratio "
                f"<b>{p.ratio(self._demand.value()):.3f}</b>; tc = {p.tc:.4g}, "
                f"t for no prying = {p.t_no_prying:.4g}"
            )
        except ValueError as exc:
            lines.append(f"Prying: {exc}")
        try:
            g = eccentric_bolt_group(
                self._bolt_positions(),
                px=self._px.value(),
                py=self._py.value(),
                ex=self._ex.value(),
                ey=self._ey.value(),
            )
            lines.append(
                f"Bolt group: the most loaded bolt (#{g.governing + 1}) takes {g.max_force:.4g}, "
                f"ratio <b>{g.ratio(self._bolt_v.value()):.3f}</b>"
            )
        except ValueError as exc:
            lines.append(f"Bolt group: {exc}")
        self._summary.setText("<br>".join(lines))
