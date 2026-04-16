"""Forms for analysis case parameters.

Same pattern as material/section forms: a tiny widget per case type,
exposing ``populate(case)`` and ``read(id)``. Pattern selection uses
a multi-select list filtered to the project's existing patterns.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from opensees_studio.core import (
    AnalysisCase,
    LoadPattern,
    ModalCase,
    PushoverCase,
    StaticCase,
    TransientCase,
)


# ─────────────────────────── helpers ───────────────────────────
def _spin(default: float = 0.0, *, decimals: int = 6,
          minimum: float = -1e15, maximum: float = 1e15,
          step: float = 1.0) -> QDoubleSpinBox:
    sb = QDoubleSpinBox()
    sb.setRange(minimum, maximum)
    sb.setDecimals(decimals)
    sb.setSingleStep(step)
    sb.setValue(default)
    return sb


def _int_spin(default: int = 1, minimum: int = 1, maximum: int = 1000000) -> QSpinBox:
    sb = QSpinBox()
    sb.setRange(minimum, maximum)
    sb.setValue(default)
    return sb


def _make_pattern_picker(patterns: list[LoadPattern]) -> QListWidget:
    """A multi-select list of pattern ids (their labels)."""
    lst = QListWidget()
    lst.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
    lst.setMaximumHeight(120)
    for p in patterns:
        item = QListWidgetItem(f"#{p.id}  {p.name or '(unnamed)'}  [{p.type}]")
        item.setData(Qt.ItemDataRole.UserRole, p.id)
        lst.addItem(item)
    return lst


def _selected_pattern_ids(picker: QListWidget) -> list[int]:
    return [item.data(Qt.ItemDataRole.UserRole) for item in picker.selectedItems()]


def _select_pattern_ids(picker: QListWidget, ids: list[int]) -> None:
    wanted = set(ids)
    for i in range(picker.count()):
        item = picker.item(i)
        if item.data(Qt.ItemDataRole.UserRole) in wanted:
            item.setSelected(True)


# ─────────────────────────── base ───────────────────────────
class CaseFormBase(QWidget):
    type_label: str = "Analysis case"

    def __init__(self, patterns: list[LoadPattern], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._case_id: int | None = None
        self._patterns = patterns
        self._layout = QFormLayout(self)
        self._name_edit = QLineEdit()
        self._layout.addRow("Name:", self._name_edit)

    def populate(self, case: AnalysisCase) -> None:
        self._case_id = case.id
        self._name_edit.setText(case.name)
        self._populate_specific(case)

    def _populate_specific(self, case: AnalysisCase) -> None: ...

    def read(self, case_id: int | None = None) -> AnalysisCase:
        cid = self._case_id if self._case_id is not None else case_id
        if cid is None:
            raise ValueError("Case id required.")
        return self._read_specific(cid)

    def _read_specific(self, case_id: int) -> AnalysisCase:
        raise NotImplementedError


# ─────────────────────────── Static ───────────────────────────
_STATIC_SYSTEMS = ["BandGeneral", "BandSPD", "ProfileSPD", "SparseGeneral", "UmfPack", "FullGeneral"]
_CONSTRAINTS = ["Plain", "Lagrange", "Penalty", "Transformation"]
_INTEGRATORS_STATIC = ["LoadControl", "DisplacementControl", "ArcLength"]
_ALGORITHMS = ["Linear", "Newton", "ModifiedNewton", "KrylovNewton", "BFGS", "Broyden"]
_TESTS = ["NormDispIncr", "NormUnbalance", "EnergyIncr", "RelativeNormDispIncr"]


class StaticCaseForm(CaseFormBase):
    type_label = "Static — linear or nonlinear pushover"

    def __init__(self, patterns: list[LoadPattern], parent: QWidget | None = None) -> None:
        super().__init__(patterns, parent)
        self._patterns_picker = _make_pattern_picker(patterns)
        self._n_steps = _int_spin(1)
        self._lf = _spin(1.0, decimals=4, minimum=-1e6, maximum=1e6, step=0.1)
        self._system = self._combo(_STATIC_SYSTEMS, "BandGeneral")
        self._constraints = self._combo(_CONSTRAINTS, "Plain")
        self._integrator = self._combo(_INTEGRATORS_STATIC, "LoadControl")
        self._algorithm = self._combo(_ALGORITHMS, "Linear")
        self._test = self._combo(_TESTS, "NormDispIncr")
        self._tol = _spin(1e-8, decimals=12, minimum=1e-15, step=1e-9)
        self._max_iter = _int_spin(25)

        self._layout.addRow(QLabel("<b>Patterns to apply (multi-select):</b>"))
        self._layout.addRow(self._patterns_picker)
        self._layout.addRow("Steps:", self._n_steps)
        self._layout.addRow("Load factor / step:", self._lf)
        self._layout.addRow("System:", self._system)
        self._layout.addRow("Constraints:", self._constraints)
        self._layout.addRow("Integrator:", self._integrator)
        self._layout.addRow("Algorithm:", self._algorithm)
        self._layout.addRow("Test:", self._test)
        self._layout.addRow("Tolerance:", self._tol)
        self._layout.addRow("Max iterations:", self._max_iter)

    @staticmethod
    def _combo(items: list[str], default: str) -> QComboBox:
        cb = QComboBox()
        cb.addItems(items)
        cb.setCurrentText(default)
        return cb

    def _populate_specific(self, c: StaticCase) -> None:
        _select_pattern_ids(self._patterns_picker, c.pattern_ids)
        self._n_steps.setValue(c.n_steps)
        self._lf.setValue(c.load_factor_increment)
        self._system.setCurrentText(c.system)
        self._constraints.setCurrentText(c.constraints)
        self._integrator.setCurrentText(c.integrator)
        self._algorithm.setCurrentText(c.algorithm)
        self._test.setCurrentText(c.test)
        self._tol.setValue(c.tolerance)
        self._max_iter.setValue(c.max_iter)

    def _read_specific(self, cid: int) -> StaticCase:
        return StaticCase(
            id=cid, name=self._name_edit.text(),
            pattern_ids=_selected_pattern_ids(self._patterns_picker) or [1],
            n_steps=self._n_steps.value(),
            load_factor_increment=self._lf.value(),
            system=self._system.currentText(),
            constraints=self._constraints.currentText(),
            integrator=self._integrator.currentText(),
            algorithm=self._algorithm.currentText(),
            test=self._test.currentText(),
            tolerance=self._tol.value(),
            max_iter=self._max_iter.value(),
        )


# ─────────────────────────── Modal ───────────────────────────
class ModalCaseForm(CaseFormBase):
    type_label = "Modal — eigenvalue analysis"

    def __init__(self, patterns: list[LoadPattern], parent: QWidget | None = None) -> None:
        super().__init__(patterns, parent)
        self._n_modes = _int_spin(3)
        self._solver = QComboBox()
        self._solver.addItems(["genBandArpack", "fullGenLapack", "symmBandLapack"])
        self._layout.addRow("Number of modes:", self._n_modes)
        self._layout.addRow("Solver:", self._solver)
        self._layout.addRow(QLabel(
            "<i>The runner auto-falls back to fullGenLapack for very small models.</i>"
        ))

    def _populate_specific(self, c: ModalCase) -> None:
        self._n_modes.setValue(c.n_modes)
        self._solver.setCurrentText(c.solver)

    def _read_specific(self, cid: int) -> ModalCase:
        return ModalCase(
            id=cid, name=self._name_edit.text(),
            n_modes=self._n_modes.value(),
            solver=self._solver.currentText(),
        )


# ─────────────────────────── Transient ───────────────────────────
_INTEGRATORS_TRANSIENT = ["Newmark", "HHT", "CentralDifference", "TRBDF2"]


class TransientCaseForm(CaseFormBase):
    type_label = "Transient — direct-integration time history"

    def __init__(self, patterns: list[LoadPattern], parent: QWidget | None = None) -> None:
        super().__init__(patterns, parent)
        self._patterns_picker = _make_pattern_picker(patterns)
        self._dt = _spin(0.01, decimals=8, minimum=1e-12, step=1e-3)
        self._n_steps = _int_spin(1000, minimum=1, maximum=10_000_000)
        self._system = QComboBox(); self._system.addItems(_STATIC_SYSTEMS)
        self._constraints = QComboBox(); self._constraints.addItems(_CONSTRAINTS)
        self._integrator = QComboBox(); self._integrator.addItems(_INTEGRATORS_TRANSIENT)
        self._gamma = _spin(0.5, decimals=4, minimum=0.0, maximum=1.0, step=0.01)
        self._beta = _spin(0.25, decimals=4, minimum=0.0, maximum=1.0, step=0.01)
        self._algorithm = QComboBox(); self._algorithm.addItems(_ALGORITHMS); self._algorithm.setCurrentText("Newton")
        self._test = QComboBox(); self._test.addItems(_TESTS)
        self._tol = _spin(1e-6, decimals=12, minimum=1e-15, step=1e-7)
        self._max_iter = _int_spin(25)

        self._layout.addRow(QLabel("<b>Patterns to apply (multi-select):</b>"))
        self._layout.addRow(self._patterns_picker)
        self._layout.addRow("dt:", self._dt)
        self._layout.addRow("Number of steps:", self._n_steps)
        self._layout.addRow("System:", self._system)
        self._layout.addRow("Constraints:", self._constraints)
        self._layout.addRow("Integrator:", self._integrator)
        self._layout.addRow("Newmark γ:", self._gamma)
        self._layout.addRow("Newmark β:", self._beta)
        self._layout.addRow("Algorithm:", self._algorithm)
        self._layout.addRow("Test:", self._test)
        self._layout.addRow("Tolerance:", self._tol)
        self._layout.addRow("Max iterations:", self._max_iter)

    def _populate_specific(self, c: TransientCase) -> None:
        _select_pattern_ids(self._patterns_picker, c.pattern_ids)
        self._dt.setValue(c.dt); self._n_steps.setValue(c.n_steps)
        self._system.setCurrentText(c.system)
        self._constraints.setCurrentText(c.constraints)
        self._integrator.setCurrentText(c.integrator)
        self._gamma.setValue(c.integrator_params[0])
        self._beta.setValue(c.integrator_params[1])
        self._algorithm.setCurrentText(c.algorithm)
        self._test.setCurrentText(c.test)
        self._tol.setValue(c.tolerance)
        self._max_iter.setValue(c.max_iter)

    def _read_specific(self, cid: int) -> TransientCase:
        return TransientCase(
            id=cid, name=self._name_edit.text(),
            pattern_ids=_selected_pattern_ids(self._patterns_picker) or [1],
            dt=self._dt.value(), n_steps=self._n_steps.value(),
            system=self._system.currentText(),
            constraints=self._constraints.currentText(),
            integrator=self._integrator.currentText(),
            integrator_params=(self._gamma.value(), self._beta.value()),
            algorithm=self._algorithm.currentText(),
            test=self._test.currentText(),
            tolerance=self._tol.value(),
            max_iter=self._max_iter.value(),
        )


class PushoverCaseForm(CaseFormBase):
    type_label = "Pushover — monotonic displacement-controlled"

    def __init__(self, patterns: list[LoadPattern], parent: QWidget | None = None) -> None:
        super().__init__(patterns, parent)
        self._patterns_picker = _make_pattern_picker(patterns)
        self._control_node = _int_spin(1, minimum=1)
        self._control_dof = _int_spin(1, minimum=1, maximum=6)
        self._target = _spin(0.1, decimals=6, minimum=-1e6, maximum=1e6, step=0.001)
        self._step = _spin(0.001, decimals=8, minimum=1e-12, step=1e-4)
        self._base_nodes = QLineEdit()
        self._base_nodes.setPlaceholderText("comma-separated node ids (leave blank for all supports)")
        self._system = QComboBox(); self._system.addItems(_STATIC_SYSTEMS)
        self._constraints = QComboBox(); self._constraints.addItems(_CONSTRAINTS)
        self._algorithm = QComboBox(); self._algorithm.addItems(_ALGORITHMS)
        self._algorithm.setCurrentText("Newton")
        self._test = QComboBox(); self._test.addItems(_TESTS)
        self._tol = _spin(1e-6, decimals=12, minimum=1e-15, step=1e-7)
        self._max_iter = _int_spin(25)

        self._layout.addRow(QLabel("<b>Patterns (applied as reference):</b>"))
        self._layout.addRow(self._patterns_picker)
        self._layout.addRow("Control node:", self._control_node)
        self._layout.addRow("Control DOF:", self._control_dof)
        self._layout.addRow("Target displacement:", self._target)
        self._layout.addRow("Step size:", self._step)
        self._layout.addRow("Base nodes:", self._base_nodes)
        self._layout.addRow("System:", self._system)
        self._layout.addRow("Constraints:", self._constraints)
        self._layout.addRow("Algorithm:", self._algorithm)
        self._layout.addRow("Test:", self._test)
        self._layout.addRow("Tolerance:", self._tol)
        self._layout.addRow("Max iterations:", self._max_iter)

    def _populate_specific(self, c: PushoverCase) -> None:
        _select_pattern_ids(self._patterns_picker, c.pattern_ids)
        self._control_node.setValue(c.control_node)
        self._control_dof.setValue(c.control_dof)
        self._target.setValue(c.target_disp)
        self._step.setValue(c.step_size)
        self._base_nodes.setText(", ".join(str(n) for n in c.base_nodes))
        self._system.setCurrentText(c.system)
        self._constraints.setCurrentText(c.constraints)
        self._algorithm.setCurrentText(c.algorithm)
        self._test.setCurrentText(c.test)
        self._tol.setValue(c.tolerance)
        self._max_iter.setValue(c.max_iter)

    def _read_specific(self, cid: int) -> PushoverCase:
        txt = self._base_nodes.text().strip()
        base_ids = [int(x) for x in txt.replace(",", " ").split() if x] if txt else []
        return PushoverCase(
            id=cid, name=self._name_edit.text(),
            pattern_ids=_selected_pattern_ids(self._patterns_picker) or [1],
            control_node=self._control_node.value(),
            control_dof=self._control_dof.value(),
            target_disp=self._target.value(),
            step_size=self._step.value(),
            base_nodes=base_ids,
            system=self._system.currentText(),
            constraints=self._constraints.currentText(),
            algorithm=self._algorithm.currentText(),
            test=self._test.currentText(),
            tolerance=self._tol.value(),
            max_iter=self._max_iter.value(),
        )


# ─────────────────────────── registry ───────────────────────────
FORM_REGISTRY: dict[str, type[CaseFormBase]] = {
    "Static": StaticCaseForm,
    "Modal": ModalCaseForm,
    "Transient": TransientCaseForm,
    "Pushover": PushoverCaseForm,
}


def form_for(case: AnalysisCase, patterns: list[LoadPattern]) -> CaseFormBase:
    cls = FORM_REGISTRY[case.type]
    form = cls(patterns)
    form.populate(case)
    return form
