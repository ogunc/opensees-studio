"""Define → Concrete Section Wizard: a reinforced concrete section from engineering inputs.

The numbers are in :mod:`core.sections.concrete`; this dialog collects the
inputs in the project's units, draws the section (concrete, the core inside the
bar centrelines, the bars at their true size) and lists what will be added. OK
hands back the materials and sections; the window adds them in one undo step.
"""

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
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from opensees_studio.core.sections.concrete import (
    CRACKED_FACTOR,
    ConcreteSection,
    ConcreteSectionSpec,
    bar_names,
    bar_positions,
    build_concrete_section,
)
from opensees_studio.core.sections.geometry import CircleRegion, circle_points, rectangle
from opensees_studio.core.units import UnitSystem, labels_for, length_scale, stress_scale
from opensees_studio.views.dialogs.section_preview import SectionPreview
from opensees_studio.views.float_field import FloatField
from opensees_studio.views.screen_fit import FittedDialog, MessageArea, scroll_area

_SHAPES = [
    ("Rectangle (column or beam)", "rect"),
    ("Circle (column)", "circ"),
    ("T-beam (flange on top)", "tee"),
    ("L-beam (edge beam)", "ell"),
]


def _defaults(units: UnitSystem) -> tuple[ConcreteSectionSpec, str]:
    """A 30 x 50 cm column in SI, a 12 x 24 in one in US units; and the bar system."""
    if units in (UnitSystem.US_IN_KIP, UnitSystem.US_FT_KIP):
        f, s = length_scale(UnitSystem.US_IN_KIP, units), stress_scale(UnitSystem.US_IN_KIP, units)
        spec = ConcreteSectionSpec(
            h=24 * f,
            b=12 * f,
            bf=48 * f,
            hf=5 * f,
            clear_cover=1.5 * f,
            bar="#8",
            tie="#4",
            tie_spacing=4 * f,
            fc=4.0 * s,
            fy=60.0 * s,
            fyh=60.0 * s,
            Es=29000.0 * s,
            units=units,
        )
        return spec, "US"
    f, s = length_scale(UnitSystem.SI_M_N, units), stress_scale(UnitSystem.SI_M_N, units)
    spec = ConcreteSectionSpec(
        h=0.5 * f,
        b=0.3 * f,
        bf=1.0 * f,
        hf=0.12 * f,
        clear_cover=0.04 * f,
        tie_spacing=0.10 * f,
        fc=30e6 * s,
        fy=420e6 * s,
        fyh=420e6 * s,
        Es=200e9 * s,
        units=units,
    )
    return spec, "metric"


class ConcreteSectionDialog(FittedDialog):
    """Inputs, a live drawing and the summary of a reinforced concrete section."""

    def __init__(self, project: Any, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Concrete Section Wizard")
        self.resize(1000, 680)
        self._project = project
        self._units: UnitSystem = project.meta.units
        self._result: ConcreteSection | None = None
        spec, system = _defaults(self._units)
        self._build_ui(system)
        self._load(spec)
        self._refresh()

    # ── UI ──────────────────────────────────────────────────────────
    def _float(self, minimum: float = 0.0) -> FloatField:
        field = FloatField()
        field.setRange(minimum, 1e15)
        field.valueChanged.connect(self._refresh)
        return field

    def _int(self, minimum: int, default: int) -> QSpinBox:
        box = QSpinBox()
        box.setRange(minimum, 200)
        box.setValue(default)
        box.valueChanged.connect(self._refresh)
        return box

    def _build_ui(self, system: str) -> None:
        labels = labels_for(self._units)
        length, stress = labels.length, labels.stress
        root = QHBoxLayout(self)
        left = QWidget()
        form_root = QVBoxLayout(left)

        shape = QGroupBox("Shape")
        f = QFormLayout(shape)
        self._shape = QComboBox()
        for text, key in _SHAPES:
            self._shape.addItem(text, key)
        self._shape.currentIndexChanged.connect(self._on_shape)
        f.addRow("Shape:", self._shape)
        self._h = self._float()
        self._b = self._float()
        self._bf = self._float()
        self._hf = self._float()
        self._h_label = QLabel(f"Depth h (local y) [{length}]:")
        f.addRow(self._h_label, self._h)
        f.addRow(f"Width b (local z) [{length}]:", self._b)
        f.addRow(f"Flange width bf [{length}]:", self._bf)
        f.addRow(f"Flange thickness hf [{length}]:", self._hf)
        self._shape_form = f
        form_root.addWidget(shape)

        bars = QGroupBox("Reinforcement")
        f = QFormLayout(bars)
        self._system = QComboBox()
        self._system.addItem("Metric (φ mm)", "metric")
        self._system.addItem("US (#)", "US")
        self._system.setCurrentIndex(0 if system == "metric" else 1)
        self._system.currentIndexChanged.connect(self._on_system)
        f.addRow("Bar sizes:", self._system)
        self._bar = QComboBox()
        self._tie = QComboBox()
        self._bar.currentIndexChanged.connect(self._refresh)
        self._tie.currentIndexChanged.connect(self._refresh)
        f.addRow("Longitudinal bar:", self._bar)
        self._n_top = self._int(2, 3)
        self._n_bottom = self._int(2, 3)
        self._n_side = self._int(0, 1)
        self._n_bars = self._int(3, 8)
        f.addRow("Top bars:", self._n_top)
        f.addRow("Bottom bars:", self._n_bottom)
        f.addRow("Side bars (each face):", self._n_side)
        f.addRow("Bars around (circle):", self._n_bars)
        f.addRow("Ties / spiral:", self._tie)
        self._spacing = self._float()
        f.addRow(f"Tie spacing s [{length}]:", self._spacing)
        self._cover = self._float()
        f.addRow(f"Clear cover to ties [{length}]:", self._cover)
        self._bars_form = f
        form_root.addWidget(bars)

        mats = QGroupBox("Materials")
        f = QFormLayout(mats)
        self._fc = self._float()
        self._fy = self._float()
        self._fyh = self._float()
        self._es = self._float()
        f.addRow(f"f'c [{stress}]:", self._fc)
        f.addRow(f"fy, bars [{stress}]:", self._fy)
        f.addRow(f"fyh, ties [{stress}]:", self._fyh)
        f.addRow(f"Es [{stress}]:", self._es)
        self._confined = QCheckBox("Confined core (Mander)")
        self._confined.toggled.connect(self._refresh)
        f.addRow(self._confined)
        self._model = QComboBox()
        self._model.addItem("Concrete02 (Kent-Park, linear tension softening)", "Concrete02")
        self._model.addItem("ConcreteCM (Chang-Mander, Tsai envelope)", "ConcreteCM")
        self._model.currentIndexChanged.connect(self._refresh)
        f.addRow("Concrete law:", self._model)
        form_root.addWidget(mats)

        out = QGroupBox("Add to the project")
        f = QFormLayout(out)
        self._name = QLineEdit()
        self._name.setPlaceholderText("from the dimensions and bars")
        self._name.textChanged.connect(self._refresh)
        f.addRow("Name:", self._name)
        self._make_fiber = QCheckBox("Fiber section (nonlinear members)")
        self._make_fiber.setChecked(True)
        self._make_elastic = QCheckBox("Elastic section with cracked inertia")
        for box in (self._make_fiber, self._make_elastic):
            box.toggled.connect(self._refresh)
        f.addRow(self._make_fiber)
        f.addRow(self._make_elastic)
        self._role = QComboBox()
        self._role.addItem("Column (0.70 Ig)", "column")
        self._role.addItem("Beam (0.35 Ig)", "beam")
        self._role.currentIndexChanged.connect(self._on_role)
        f.addRow("Member:", self._role)
        self._factor = FloatField()
        self._factor.setRange(0.01, 1.0)
        self._factor.setValue(CRACKED_FACTOR["column"])
        self._factor.valueChanged.connect(self._refresh)
        f.addRow("I factor:", self._factor)
        form_root.addWidget(out)
        form_root.addStretch(1)
        root.addWidget(scroll_area(left, vertical_only=True), 2)

        right = QVBoxLayout()
        self._preview = SectionPreview()
        right.addWidget(self._preview, 1)
        self._summary = QLabel("")
        self._summary.setWordWrap(True)
        right.addWidget(self._summary)
        self._message = MessageArea()
        right.addWidget(self._message)
        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)
        right.addWidget(self._buttons)
        root.addLayout(right, 3)
        self._fill_bars()

    def _fill_bars(self) -> None:
        system = self._system.currentData()
        for combo in (self._bar, self._tie):
            combo.blockSignals(True)
            combo.clear()
            combo.addItems(bar_names(system))
            combo.blockSignals(False)

    def _load(self, spec: ConcreteSectionSpec) -> None:
        widgets = (self._h, self._b, self._bf, self._hf, self._spacing, self._cover)
        values = (spec.h, spec.b, spec.bf, spec.hf, spec.tie_spacing, spec.clear_cover)
        for widget, value in zip(widgets, values, strict=True):
            widget.blockSignals(True)
            widget.setValue(value)
            widget.blockSignals(False)
        for widget, value in zip(
            (self._fc, self._fy, self._fyh, self._es),
            (spec.fc, spec.fy, spec.fyh, spec.Es),
            strict=True,
        ):
            widget.blockSignals(True)
            widget.setValue(value)
            widget.blockSignals(False)
        self._bar.setCurrentText(spec.bar)
        self._tie.setCurrentText(spec.tie)
        self._confined.setChecked(spec.confined)
        self._model.setCurrentIndex(max(0, self._model.findData(spec.concrete_model)))
        self._on_shape()

    # ── reactions ───────────────────────────────────────────────────
    def _on_shape(self) -> None:
        kind = self._shape.currentData()
        flanged = kind in ("tee", "ell")
        for widget in (self._bf, self._hf):
            self._shape_form.setRowVisible(widget, flanged)
        self._shape_form.setRowVisible(self._b, kind != "circ")
        self._h_label.setText(
            f"{'Diameter' if kind == 'circ' else 'Depth h (local y)'} "
            f"[{labels_for(self._units).length}]:"
        )
        for counter in (self._n_top, self._n_bottom, self._n_side):
            self._bars_form.setRowVisible(counter, kind != "circ")
        self._bars_form.setRowVisible(self._n_bars, kind == "circ")
        if kind in ("tee", "ell"):
            self._role.setCurrentIndex(1)
        elif kind == "circ":
            self._role.setCurrentIndex(0)
        self._refresh()

    def _on_system(self) -> None:
        self._fill_bars()
        if self._system.currentData() == "US":
            self._bar.setCurrentText("#8")
            self._tie.setCurrentText("#4")
        else:
            self._bar.setCurrentText("φ20")
            self._tie.setCurrentText("φ10")
        self._refresh()

    def _on_role(self) -> None:
        self._factor.setValue(CRACKED_FACTOR[self._role.currentData()])
        self._refresh()

    # ── model ───────────────────────────────────────────────────────
    def spec(self) -> ConcreteSectionSpec:
        return ConcreteSectionSpec(
            shape=self._shape.currentData(),
            h=self._h.value(),
            b=self._b.value(),
            bf=self._bf.value(),
            hf=self._hf.value(),
            clear_cover=self._cover.value(),
            bar=self._bar.currentText(),
            tie=self._tie.currentText(),
            tie_spacing=self._spacing.value(),
            n_top=self._n_top.value(),
            n_bottom=self._n_bottom.value(),
            n_side=self._n_side.value(),
            n_bars=self._n_bars.value(),
            fc=self._fc.value(),
            fy=self._fy.value(),
            fyh=self._fyh.value(),
            Es=self._es.value(),
            confined=self._confined.isChecked(),
            concrete_model=self._model.currentData(),
            role=self._role.currentData(),
            units=self._units,
            name=self._name.text().strip(),
        )

    def built_section(self) -> ConcreteSection | None:
        """What OK adds: the materials and the sections (``None`` while the inputs are invalid)."""
        return self._result

    def _refresh(self) -> None:
        spec = self.spec()
        self._preview.clear()
        ok_button = self._buttons.button(QDialogButtonBox.StandardButton.Ok)
        wants = self._make_fiber.isChecked() or self._make_elastic.isChecked()
        self._factor.setEnabled(self._make_elastic.isChecked())
        self._role.setEnabled(self._make_elastic.isChecked())
        try:
            result = build_concrete_section(
                spec,
                material_id=self._project.next_material_id(),
                section_id=self._project.next_section_id(),
                fiber=self._make_fiber.isChecked(),
                elastic=self._make_elastic.isChecked(),
                cracked_factor=self._factor.value(),
            )
        except (ValueError, KeyError) as exc:
            self._result = None
            self._summary.setText("")
            self._message.show_message(str(exc), "error")
            ok_button.setEnabled(False)
            return
        self._result = result
        self._draw(spec, result)
        self._summary.setText(self._describe(spec, result))
        notes = list(result.notes)
        if not wants:
            notes.insert(0, "Tick the fiber or the elastic section (or both) to add something.")
        self._message.show_message(" ".join(notes), "warning" if not wants else "info")
        ok_button.setEnabled(wants)

    def _draw(self, spec: ConcreteSectionSpec, result: ConcreteSection) -> None:
        self._preview.draw_regions(spec.regions())
        c = spec.cover_to_bars
        if spec.shape == "circ":
            self._preview.draw_outline(circle_points(CircleRegion(0.0, 0.0, spec.h / 2 - c)))
        else:
            self._preview.draw_outline(rectangle(spec.b - 2 * c, spec.h - 2 * c).points)
        self._preview.draw_bars(bar_positions(spec), spec.bar_diameter)
        if result.properties is not None:
            self._preview.draw_centroid(result.properties.y_c, result.properties.z_c)
        self._preview.fit()

    def _describe(self, spec: ConcreteSectionSpec, result: ConcreteSection) -> str:
        labels = labels_for(self._units)
        props = result.properties
        assert props is not None
        parts = [
            f"<b>{spec.bar_count} {spec.bar}</b>: As = {spec.steel_area:.4g} {labels.length}², "
            f"ρ = {spec.steel_area / props.A:.2%} of Ag = {props.A:.4g} {labels.length}²",
            f"Gross Iz = {props.Iz:.4g}, Iy = {props.Iy:.4g} {labels.length}⁴; "
            f"Ec = {result.Ec:.4g} {labels.stress}",
        ]
        if result.confinement is not None:
            conf = result.confinement
            parts.append(
                f"Core (Mander): ρs = {conf.rho_s:.2%}, f'cc = {conf.fcc:.4g} {labels.stress} "
                f"({conf.fcc / spec.fc:.2f} f'c), εcc = {conf.eps_cc:.4f}, εcu = {conf.eps_cu:.4f}"
            )
        added = [f"material #{m.id} {m.name}" for m in result.materials]  # type: ignore[attr-defined]
        for section in (result.fiber, result.elastic):
            if section is not None:
                added.append(f"section #{section.id} {section.name}")
        parts.append("Adds " + ", ".join(added) + ".")
        return "<br>".join(parts)
