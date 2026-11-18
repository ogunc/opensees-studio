"""Define → Seismic Loads (Equivalent Lateral Force): base shear and storey forces.

The dialog takes the code coefficients, previews the base shear and the
storey forces of every direction asked for (see
:mod:`opensees_studio.core.equivalent_lateral`), and on OK writes one Plain
load pattern with a linear static case per direction — ``EQ X``, ``EQ Y`` and,
with accidental eccentricity, ``EQ X +e`` / ``EQ X -e`` … — as one undo step.
A pattern of that name already in the model (the combination generator's
empty ``EQ X``, or an earlier run) gets its nodal loads replaced instead, so
the cases and combinations that use it stay as they are.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import (
    QCheckBox,
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

from opensees_studio.commands import (
    AddAnalysisCasesCommand,
    AddLoadPatternCommand,
    AddTimeSeriesCommand,
    SetPatternNodalLoadsCommand,
)
from opensees_studio.core import NodalLoad, PlainLoadPattern, Project, make_load_cases
from opensees_studio.core.equivalent_lateral import (
    ASCE_PERIOD_SYSTEMS,
    CODE_LABELS,
    TBDY_PERIOD_SYSTEMS,
    ElfError,
    ElfParameters,
    ElfResult,
    approximate_period,
    building_height,
    equivalent_lateral_forces,
    length_in_metres,
    nodal_forces,
)
from opensees_studio.core.target_spectrum import TBDY_TL
from opensees_studio.viewmodels import ProjectViewModel
from opensees_studio.views.float_field import FloatField
from opensees_studio.views.screen_fit import FittedDialog, MessageArea

AXES = ("X", "Y")


def pattern_names(axis: str, eccentric: bool) -> list[tuple[str, int]]:
    """``(pattern name, eccentricity sign)`` written for one direction."""
    names = [(f"EQ {axis}", 0)]
    if eccentric:
        names += [(f"EQ {axis} +e", 1), (f"EQ {axis} -e", -1)]
    return names


def _field(value: float, lo: float = 0.0, hi: float = 1e6) -> FloatField:
    field = FloatField()
    field.setRange(lo, hi)
    field.setValue(value)
    return field


class SeismicLoadsDialog(FittedDialog):
    """Equivalent lateral force generator for ASCE 7-16 and TBDY 2018."""

    def __init__(self, vm: ProjectViewModel, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Seismic Loads (Equivalent Lateral Force)")
        self._vm = vm
        self.written: list[str] = []
        project = vm.project
        assert project is not None
        self._ndm = project.ndm
        layout = QVBoxLayout(self)
        intro = QLabel(
            "Base shear from the code formulas, shared between the storeys by height and "
            "weight (the masses the analysis uses). One load pattern and static case per "
            "direction; a pattern of the same name is refilled."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        form = QFormLayout()
        self.code = QComboBox()
        for key, label in CODE_LABELS.items():
            self.code.addItem(label, key)
        form.addRow("Code:", self.code)
        self.sds = _field(1.0)
        self.sd1 = _field(0.6)
        self.s1 = _field(0.0)
        self.tl = _field(TBDY_TL, 0.0, 100.0)
        self.r = _field(8.0, 0.01, 100.0)
        self.importance = _field(1.0, 0.01, 10.0)
        self.overstrength = _field(3.0, 0.01, 100.0)
        form.addRow("SDS (g):", self.sds)
        form.addRow("SD1 (g):", self.sd1)
        self._s1_label = QLabel("S1 (g, for Eq. 12.8-6):")
        form.addRow(self._s1_label, self.s1)
        form.addRow("TL (s):", self.tl)
        form.addRow("R:", self.r)
        self._importance_label = QLabel("Ie:")
        form.addRow(self._importance_label, self.importance)
        self._d_label = QLabel("D (overstrength):")
        form.addRow(self._d_label, self.overstrength)

        period_row = QHBoxLayout()
        self.period = _field(0.5, 0.0, 100.0)
        self.system = QComboBox()
        self.approximate = QPushButton("Approximate")
        self.approximate.setToolTip("The code's empirical period for the building height.")
        period_row.addWidget(self.period)
        period_row.addWidget(self.system)
        period_row.addWidget(self.approximate)
        form.addRow("Period T (s):", period_row)

        self.directions = {axis: QCheckBox(axis) for axis in AXES}
        direction_row = QHBoxLayout()
        for axis, box in self.directions.items():
            box.setChecked(axis == "X" or self._ndm == 3)
            direction_row.addWidget(box)
        if self._ndm == 2:
            self.directions["Y"].setEnabled(False)
            self.directions["Y"].setToolTip("A 2D model lives in the X-Z plane: X only.")
        form.addRow("Directions:", direction_row)
        self.eccentric = QCheckBox("Accidental eccentricity ±")
        self.ratio = _field(0.05, 0.0, 0.5)
        ecc_row = QHBoxLayout()
        ecc_row.addWidget(self.eccentric)
        ecc_row.addWidget(self.ratio)
        ecc_row.addWidget(QLabel("× floor extent"))
        if self._ndm == 2:
            self.eccentric.setEnabled(False)
            self.ratio.setEnabled(False)
        form.addRow(ecc_row)
        layout.addLayout(form)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Storey", "Height", "Weight", "Force"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.message = MessageArea(self)
        layout.addWidget(self.message)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self._on_ok)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._ok = buttons.button(QDialogButtonBox.StandardButton.Ok)

        self._prefill(project)
        self.code.currentIndexChanged.connect(self._on_code_changed)
        self.approximate.clicked.connect(self.fill_approximate_period)
        for widget in (
            self.sds, self.sd1, self.s1, self.tl, self.r, self.importance,
            self.overstrength, self.period, self.ratio,
        ):  # fmt: skip
            widget.valueChanged.connect(self.refresh)
        for box in (*self.directions.values(), self.eccentric):
            box.toggled.connect(self.refresh)
        self._on_code_changed()

    # ── inputs ───────────────────────────────────────────────────────
    def _prefill(self, project: Project) -> None:
        """SDS, SD1, S1 and TL of the project's design spectrum, when it has one."""
        for target in project.target_spectra:
            if target.kind in ("asce7_16", "tbdy2018") and target.sds and target.sd1:
                self.code.setCurrentIndex(self.code.findData(target.kind))
                self.sds.setValue(float(target.sds))
                self.sd1.setValue(float(target.sd1))
                if target.s1:
                    self.s1.setValue(float(target.s1))
                if target.tl:
                    self.tl.setValue(float(target.tl))
                break

    def code_key(self) -> str:
        return str(self.code.currentData())

    def _on_code_changed(self) -> None:
        asce = self.code_key() == "asce7_16"
        self._importance_label.setText("Ie:" if asce else "I:")
        self.s1.setEnabled(asce)
        self._s1_label.setEnabled(asce)
        self.overstrength.setEnabled(not asce)
        self._d_label.setEnabled(not asce)
        if not asce:
            self.tl.setValue(TBDY_TL)
        self.system.clear()
        systems: dict[str, Any] = ASCE_PERIOD_SYSTEMS if asce else TBDY_PERIOD_SYSTEMS
        for key, entry in systems.items():
            self.system.addItem(entry[0], key)
        self.refresh()

    def fill_approximate_period(self) -> None:
        project = self._vm.project
        if project is None:
            return
        try:
            period = approximate_period(
                self.code_key(),  # type: ignore[arg-type]
                str(self.system.currentData()),
                building_height(project),
                length_in_metres(project),
            )
        except ElfError as exc:
            self.message.show_message(str(exc), "error")
            return
        self.period.setValue(round(period, 4))

    def parameters(self) -> ElfParameters:
        return ElfParameters(
            code=self.code_key(),  # type: ignore[arg-type]
            period=self.period.value(),
            sds=self.sds.value(),
            sd1=self.sd1.value(),
            r=self.r.value(),
            importance=self.importance.value(),
            tl=self.tl.value(),
            s1=self.s1.value(),
            overstrength_d=self.overstrength.value(),
            eccentricity_ratio=self.ratio.value(),
        )

    def chosen_axes(self) -> list[str]:
        return [a for a, box in self.directions.items() if box.isChecked() and box.isEnabled()]

    # ── preview ──────────────────────────────────────────────────────
    def results(self) -> dict[str, ElfResult]:
        """One result per chosen direction; raises :class:`ElfError` on bad input."""
        project = self._vm.project
        assert project is not None
        params = self.parameters()
        return {
            axis: equivalent_lateral_forces(project, AXES.index(axis), params)
            for axis in self.chosen_axes()
        }

    def refresh(self) -> None:
        self.table.setRowCount(0)
        try:
            results = self.results()
        except (ElfError, ValueError) as exc:
            self.summary.setText("")
            self.message.show_message(str(exc), "error")
            self._ok.setEnabled(False)
            return
        if not results:
            self.message.show_message("Choose at least one direction.", "error")
            self._ok.setEnabled(False)
            return
        self.message.show_message("")
        self._ok.setEnabled(True)
        lines: list[str] = []
        for axis, result in results.items():
            for name, height, weight, force in result.table():
                row = self.table.rowCount()
                self.table.insertRow(row)
                for col, text in enumerate(
                    (f"{name} ({axis})", f"{height:.4g}", f"{weight:.6g}", f"{force:.6g}")
                ):
                    self.table.setItem(row, col, QTableWidgetItem(text))
            lines.append(
                f"{axis}: W = {result.total_weight:.6g}, V = {result.base_shear:.6g} "
                f"(V/W = {result.coefficient:.4g}). " + " ".join(result.notes)
            )
        self.summary.setText("\n".join(lines))

    # ── write ────────────────────────────────────────────────────────
    def _on_ok(self) -> None:
        try:
            names = self.apply()
        except (ElfError, ValueError) as exc:
            self.message.show_message(str(exc), "error")
            return
        self.written = names
        self.accept()

    def apply(self) -> list[str]:
        """Write the patterns (one undo step); returns their names."""
        project = self._vm.project
        assert project is not None
        results = self.results()
        eccentric = self.eccentric.isChecked() and self.eccentric.isEnabled()
        ratio = self.ratio.value()
        planned: list[tuple[str, list[NodalLoad]]] = []
        for axis, result in results.items():
            for name, sign in pattern_names(axis, eccentric):
                forces = nodal_forces(project, result, sign, ratio)
                loads = [NodalLoad(node_id=n, forces=f) for n, f in sorted(forces.items())]
                planned.append((name, loads))
        existing = {
            p.name: p for p in project.load_patterns if isinstance(p, PlainLoadPattern) and p.name
        }
        stack = self._vm.undo_stack
        stack.beginMacro(f"Seismic loads: {', '.join(n for n, _ in planned)}")
        try:
            new = [name for name, _ in planned if name not in existing]
            series, patterns, cases = make_load_cases(project, new)
            fresh = {p.name: p for p in patterns}
            for ts in series:
                self._vm.apply_command(AddTimeSeriesCommand(self._vm, ts))
            for name, loads in planned:
                if name in existing:
                    self._vm.apply_command(
                        SetPatternNodalLoadsCommand(self._vm, existing[name].id, loads)
                    )
                else:
                    pattern = fresh[name].model_copy(update={"nodal_loads": loads})
                    self._vm.apply_command(AddLoadPatternCommand(self._vm, pattern))
            if cases:
                self._vm.apply_command(AddAnalysisCasesCommand(self._vm, list(cases)))
        finally:
            stack.endMacro()
        return [name for name, _ in planned]
