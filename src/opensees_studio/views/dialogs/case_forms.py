"""Forms for analysis case parameters.

Same pattern as material/section forms: a tiny widget per case type,
exposing ``populate(case)`` and ``read(id)``. Pattern selection uses
a multi-select list filtered to the project's existing patterns.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QSpinBox,
    QWidget,
)

from opensees_studio.core import (
    NUMBERERS,
    SYSTEM_NOTES,
    SYSTEMS,
    AnalysisCase,
    LoadPattern,
    ModalCase,
    PushoverCase,
    ResponseSpectrumCase,
    StaticCase,
    TransientCase,
)
from opensees_studio.core.modal import (
    SOLVER_ARPACK,
    SOLVER_AUTO,
    SOLVER_DENSE,
    dense_eigen_max_free_dof,
)
from opensees_studio.views.float_field import FloatField


# ─────────────────────────── helpers ───────────────────────────
def _spin(
    default: float = 0.0,
    *,
    minimum: float = -1e15,
    maximum: float = 1e15,
    step: float = 1.0,
) -> FloatField:
    sb = FloatField()
    sb.setRange(minimum, maximum)
    sb.setSingleStep(step)
    sb.setValue(default)
    return sb


def _note(text: str) -> QLabel:
    """A word-wrapped hint row, so a long note never widens the form."""
    label = QLabel(text)
    label.setWordWrap(True)
    return label


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


def _make_analysis_picker(cases: list[AnalysisCase], *, only_static: bool = False) -> QListWidget:
    """A multi-select list of analysis-case ids (their labels)."""
    lst = QListWidget()
    lst.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
    lst.setMaximumHeight(120)
    for case in cases:
        if only_static and not isinstance(case, StaticCase):
            continue
        item = QListWidgetItem(f"#{case.id}  {case.name or '(unnamed)'}  [{case.type}]")
        item.setData(Qt.ItemDataRole.UserRole, case.id)
        lst.addItem(item)
    return lst


def _selected_pattern_ids(picker: QListWidget) -> list[int]:
    return [item.data(Qt.ItemDataRole.UserRole) for item in picker.selectedItems()]


def _select_pattern_ids(picker: QListWidget, ids: list[int]) -> None:
    wanted = set(ids)
    present = {picker.item(i).data(Qt.ItemDataRole.UserRole) for i in range(picker.count())}
    for pid in ids:
        if pid not in present:
            item = QListWidgetItem(f"#{pid} [Missing pattern]")
            item.setData(Qt.ItemDataRole.UserRole, pid)
            picker.addItem(item)
    for i in range(picker.count()):
        item = picker.item(i)
        item.setSelected(item.data(Qt.ItemDataRole.UserRole) in wanted)


def _selected_case_ids(picker: QListWidget) -> list[int]:
    return [item.data(Qt.ItemDataRole.UserRole) for item in picker.selectedItems()]


def _select_case_ids(picker: QListWidget, ids: list[int]) -> None:
    wanted = set(ids)
    for i in range(picker.count()):
        item = picker.item(i)
        if item.data(Qt.ItemDataRole.UserRole) in wanted:
            item.setSelected(True)


# ─────────────────────────── base ───────────────────────────
class CaseFormBase(QWidget):
    type_label: str = "Analysis case"

    def __init__(
        self,
        patterns: list[LoadPattern],
        analyses: list[AnalysisCase],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._case_id: int | None = None
        self._patterns = patterns
        self._analyses = analyses
        self._layout = QFormLayout(self)
        self._name_edit = QLineEdit()
        self._layout.addRow("Name:", self._name_edit)

    def populate(self, case: AnalysisCase) -> None:
        self._case_id = case.id
        self._name_edit.setText(case.name)
        self._populate_specific(case)

    def _update_algorithm_args(self) -> None:
        offered = self._algorithm.currentText() in ("Newton", "ModifiedNewton")
        self._algorithm_args.setEnabled(offered)
        if not offered:
            self._algorithm_args.setCurrentIndex(0)

    def _populate_specific(self, case: AnalysisCase) -> None: ...

    def read(self, case_id: int | None = None) -> AnalysisCase:
        cid = self._case_id if self._case_id is not None else case_id
        if cid is None:
            raise ValueError("Case id required.")
        return self._read_specific(cid)

    def _read_specific(self, case_id: int) -> AnalysisCase:
        raise NotImplementedError


# ─────────────────────────── Static ───────────────────────────
class _SolverRows:
    """Numberer and system rows shared by the stepped case forms."""

    def __init__(self, layout: QFormLayout) -> None:
        self.numberer = QComboBox()
        self.numberer.addItems(list(NUMBERERS))
        self.numberer.setCurrentText("RCM")
        self.system = QComboBox()
        for name in SYSTEMS:
            self.system.addItem(name)
            note = SYSTEM_NOTES.get(name)
            if note:
                self.system.setItemData(
                    self.system.count() - 1, f"{name}: {note}", Qt.ItemDataRole.ToolTipRole
                )
        self.system.setCurrentText("BandGeneral")
        layout.addRow("Numberer:", self.numberer)
        layout.addRow("System:", self.system)

    def populate(self, case: StaticCase | TransientCase | PushoverCase) -> None:
        self.numberer.setCurrentText(case.numberer)
        if self.system.findText(case.system) < 0:
            # A solver a file names but this build does not offer: show it as stored.
            self.system.addItem(case.system)
        self.system.setCurrentText(case.system)

    def values(self) -> dict[str, object]:
        return {"numberer": self.numberer.currentText(), "system": self.system.currentText()}


_CONSTRAINTS = ["Plain", "Lagrange", "Penalty", "Transformation"]
_INTEGRATORS_STATIC = ["LoadControl", "DisplacementControl", "ArcLength"]
_ALGORITHMS = ["Linear", "Newton", "ModifiedNewton", "KrylovNewton", "BFGS", "Broyden"]
_TESTS = ["NormDispIncr", "NormUnbalance", "EnergyIncr", "RelativeNormDispIncr"]


class StaticCaseForm(CaseFormBase):
    type_label = "Static — linear or nonlinear pushover"

    def __init__(
        self,
        patterns: list[LoadPattern],
        analyses: list[AnalysisCase],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(patterns, analyses, parent)
        self._patterns_picker = _make_pattern_picker(patterns)
        self._n_steps = _int_spin(1)
        self._lf = _spin(1.0, minimum=-1e6, maximum=1e6, step=0.1)
        self._constraints = self._combo(_CONSTRAINTS, "Plain")
        self._integrator = self._combo(_INTEGRATORS_STATIC, "LoadControl")
        self._algorithm = self._combo(_ALGORITHMS, "Linear")
        self._test = self._combo(_TESTS, "NormDispIncr")
        self._tol = _spin(1e-8, minimum=1e-15, step=1e-9)
        self._max_iter = _int_spin(25)

        self._layout.addRow(QLabel("<b>Patterns to apply (multi-select):</b>"))
        self._layout.addRow(self._patterns_picker)
        self._layout.addRow("Steps:", self._n_steps)
        self._layout.addRow("Load factor / step:", self._lf)
        self._solver = _SolverRows(self._layout)
        self._layout.addRow("Constraints:", self._constraints)
        self._layout.addRow("Integrator:", self._integrator)
        self._algorithm_args = QComboBox()
        self._algorithm_args.addItems(["Current tangent", "Initial tangent (-initial)"])
        self._algorithm.currentTextChanged.connect(self._update_algorithm_args)
        self._update_algorithm_args()
        algorithm_row = QHBoxLayout()
        algorithm_row.addWidget(self._algorithm)
        algorithm_row.addWidget(self._algorithm_args)
        self._layout.addRow("Algorithm:", algorithm_row)
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
        self._solver.populate(c)
        self._constraints.setCurrentText(c.constraints)
        self._integrator.setCurrentText(c.integrator)
        self._algorithm.setCurrentText(c.algorithm)
        self._algorithm_args.setCurrentIndex(1 if c.algorithm_args else 0)
        self._test.setCurrentText(c.test)
        self._tol.setValue(c.tolerance)
        self._max_iter.setValue(c.max_iter)

    def _read_specific(self, cid: int) -> StaticCase:
        return StaticCase(
            id=cid,
            name=self._name_edit.text(),
            pattern_ids=_selected_pattern_ids(self._patterns_picker) or [1],
            n_steps=self._n_steps.value(),
            load_factor_increment=self._lf.value(),
            **self._solver.values(),  # type: ignore[arg-type]
            constraints=self._constraints.currentText(),
            integrator=self._integrator.currentText(),
            algorithm=self._algorithm.currentText(),
            algorithm_args=("-initial",) if self._algorithm_args.currentIndex() == 1 else (),
            test=self._test.currentText(),
            tolerance=self._tol.value(),
            max_iter=self._max_iter.value(),
        )


# ─────────────────────────── Modal ───────────────────────────
class ModalCaseForm(CaseFormBase):
    type_label = "Modal — eigenvalue analysis"

    def __init__(
        self,
        patterns: list[LoadPattern],
        analyses: list[AnalysisCase],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(patterns, analyses, parent)
        self._n_modes = _int_spin(3)
        self._solver = QComboBox()
        threshold = dense_eigen_max_free_dof()
        self._solver.addItem(f"Auto (fullGenLapack at or below {threshold} free DOF)", SOLVER_AUTO)
        self._solver.addItem("genBandArpack (ARPACK, iterative)", SOLVER_ARPACK)
        self._solver.addItem("fullGenLapack (dense, deterministic)", SOLVER_DENSE)
        self._layout.addRow("Number of modes:", self._n_modes)
        self._layout.addRow("Solver:", self._solver)
        self._layout.addRow(
            _note(
                "<i>Auto gives history-independent results: dense below the threshold, "
                "ARPACK above it as the first eigen call of a fresh process. ARPACK falls "
                "back to fullGenLapack for very small models.</i>"
            )
        )

    def _populate_specific(self, c: ModalCase) -> None:
        self._n_modes.setValue(c.n_modes)
        index = self._solver.findData(c.solver)
        if index < 0:
            # A stored name this build does not offer (symmBandLapack is refused
            # at run time): show it so the user sees what the case asks for.
            self._solver.addItem(f"{c.solver} (not offered, refused at run time)", c.solver)
            index = self._solver.count() - 1
        self._solver.setCurrentIndex(index)

    def _read_specific(self, cid: int) -> ModalCase:
        return ModalCase(
            id=cid,
            name=self._name_edit.text(),
            n_modes=self._n_modes.value(),
            solver=str(self._solver.currentData()),
        )


# ─────────────────────────── Transient ───────────────────────────
_INTEGRATORS_TRANSIENT = ["Newmark", "HHT", "CentralDifference", "TRBDF2"]


class TransientCaseForm(CaseFormBase):
    type_label = "Transient — direct-integration time history"

    def __init__(
        self,
        patterns: list[LoadPattern],
        analyses: list[AnalysisCase],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(patterns, analyses, parent)
        self._patterns_picker = _make_pattern_picker(patterns)
        self._preload_picker = _make_analysis_picker(analyses, only_static=True)
        self._remove_patterns_picker = _make_pattern_picker(patterns)
        self._dt = _spin(0.01, minimum=1e-12, step=1e-3)
        self._n_steps = _int_spin(1000, minimum=1, maximum=10_000_000)
        self._constraints = QComboBox()
        self._constraints.addItems(_CONSTRAINTS)
        self._integrator = QComboBox()
        self._integrator.addItems(_INTEGRATORS_TRANSIENT)
        self._gamma = _spin(0.5, minimum=0.0, maximum=1.0, step=0.01)
        self._beta = _spin(0.25, minimum=0.0, maximum=1.0, step=0.01)
        self._algorithm = QComboBox()
        self._algorithm.addItems(_ALGORITHMS)
        self._algorithm.setCurrentText("Newton")
        self._test = QComboBox()
        self._test.addItems(_TESTS)
        self._tol = _spin(1e-6, minimum=1e-15, step=1e-7)
        self._max_iter = _int_spin(25)
        self._alpha_m = _spin(0.0, minimum=0.0, maximum=1e12, step=1e-4)
        self._beta_k = _spin(0.0, minimum=0.0, maximum=1e12, step=1e-6)
        self._mode1_damping = _spin(0.0, minimum=0.0, maximum=1.0, step=0.01)

        self._layout.addRow(QLabel("<b>Patterns to apply (multi-select):</b>"))
        self._layout.addRow(self._patterns_picker)
        self._layout.addRow(QLabel("<b>Preload static cases (optional):</b>"))
        self._layout.addRow(self._preload_picker)
        self._layout.addRow(
            _note(
                "<i>Run these Static cases first, then hold them constant via "
                "loadConst -time 0.0 before the transient starts.</i>"
            )
        )
        self._layout.addRow(QLabel("<b>Patterns to remove after preload (optional):</b>"))
        self._layout.addRow(self._remove_patterns_picker)
        self._layout.addRow("dt:", self._dt)
        self._layout.addRow("Number of steps:", self._n_steps)
        self._solver = _SolverRows(self._layout)
        self._layout.addRow("Constraints:", self._constraints)
        self._layout.addRow("Integrator:", self._integrator)
        self._layout.addRow("Newmark γ:", self._gamma)
        self._layout.addRow("Newmark β:", self._beta)
        self._algorithm_args = QComboBox()
        self._algorithm_args.addItems(["Current tangent", "Initial tangent (-initial)"])
        self._algorithm.currentTextChanged.connect(self._update_algorithm_args)
        self._update_algorithm_args()
        algorithm_row = QHBoxLayout()
        algorithm_row.addWidget(self._algorithm)
        algorithm_row.addWidget(self._algorithm_args)
        self._layout.addRow("Algorithm:", algorithm_row)
        self._layout.addRow("Test:", self._test)
        self._layout.addRow("Tolerance:", self._tol)
        self._layout.addRow("Max iterations:", self._max_iter)
        self._layout.addRow("Rayleigh αM:", self._alpha_m)
        self._layout.addRow("Rayleigh βK:", self._beta_k)
        self._layout.addRow("Mode-1 damping ratio:", self._mode1_damping)
        self._layout.addRow(
            _note(
                "<i>If mode-1 damping is > 0, the runner computes βK = 2ζ/√λ1 "
                "after preload and uses it instead of the manual βK value.</i>"
            )
        )

    def _populate_specific(self, c: TransientCase) -> None:
        _select_pattern_ids(self._patterns_picker, c.pattern_ids)
        _select_case_ids(self._preload_picker, c.preload_case_ids)
        _select_pattern_ids(self._remove_patterns_picker, c.remove_patterns)
        self._dt.setValue(c.dt)
        self._n_steps.setValue(c.n_steps)
        self._solver.populate(c)
        self._constraints.setCurrentText(c.constraints)
        self._integrator.setCurrentText(c.integrator)
        self._gamma.setValue(c.integrator_params[0])
        self._beta.setValue(c.integrator_params[1])
        self._algorithm.setCurrentText(c.algorithm)
        self._algorithm_args.setCurrentIndex(1 if c.algorithm_args else 0)
        self._test.setCurrentText(c.test)
        self._tol.setValue(c.tolerance)
        self._max_iter.setValue(c.max_iter)
        self._alpha_m.setValue(c.rayleigh_alpha_m)
        self._beta_k.setValue(c.rayleigh_beta_k)
        self._mode1_damping.setValue(c.rayleigh_mode1_damping or 0.0)

    def _read_specific(self, cid: int) -> TransientCase:
        mode1_damping = self._mode1_damping.value()
        return TransientCase(
            id=cid,
            name=self._name_edit.text(),
            pattern_ids=_selected_pattern_ids(self._patterns_picker) or [1],
            preload_case_ids=_selected_case_ids(self._preload_picker),
            remove_patterns=_selected_pattern_ids(self._remove_patterns_picker),
            dt=self._dt.value(),
            n_steps=self._n_steps.value(),
            **self._solver.values(),  # type: ignore[arg-type]
            constraints=self._constraints.currentText(),
            integrator=self._integrator.currentText(),
            integrator_params=(self._gamma.value(), self._beta.value()),
            algorithm=self._algorithm.currentText(),
            algorithm_args=("-initial",) if self._algorithm_args.currentIndex() == 1 else (),
            test=self._test.currentText(),
            tolerance=self._tol.value(),
            max_iter=self._max_iter.value(),
            rayleigh_alpha_m=self._alpha_m.value(),
            rayleigh_beta_k=self._beta_k.value(),
            rayleigh_mode1_damping=mode1_damping if mode1_damping > 0.0 else None,
        )


class PushoverCaseForm(CaseFormBase):
    type_label = "Pushover — monotonic displacement-controlled"

    def __init__(
        self,
        patterns: list[LoadPattern],
        analyses: list[AnalysisCase],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(patterns, analyses, parent)
        self._patterns_picker = _make_pattern_picker(patterns)
        self._control_node = _int_spin(1, minimum=1)
        self._control_dof = _int_spin(1, minimum=1, maximum=6)
        self._target = _spin(0.1, minimum=-1e6, maximum=1e6, step=0.001)
        self._step = _spin(0.001, minimum=1e-12, step=1e-4)
        self._base_nodes = QLineEdit()
        self._base_nodes.setPlaceholderText(
            "comma-separated node ids (leave blank for all supports)"
        )
        self._constraints = QComboBox()
        self._constraints.addItems(_CONSTRAINTS)
        self._algorithm = QComboBox()
        self._algorithm.addItems(_ALGORITHMS)
        self._algorithm.setCurrentText("Newton")
        self._test = QComboBox()
        self._test.addItems(_TESTS)
        self._tol = _spin(1e-6, minimum=1e-15, step=1e-7)
        self._max_iter = _int_spin(25)

        self._layout.addRow(QLabel("<b>Patterns (applied as reference):</b>"))
        self._layout.addRow(self._patterns_picker)
        self._layout.addRow("Control node:", self._control_node)
        self._layout.addRow("Control DOF:", self._control_dof)
        self._layout.addRow("Target displacement:", self._target)
        self._layout.addRow("Step size:", self._step)
        self._layout.addRow("Base nodes:", self._base_nodes)
        self._solver = _SolverRows(self._layout)
        self._layout.addRow("Constraints:", self._constraints)
        self._algorithm_args = QComboBox()
        self._algorithm_args.addItems(["Current tangent", "Initial tangent (-initial)"])
        self._algorithm.currentTextChanged.connect(self._update_algorithm_args)
        self._update_algorithm_args()
        algorithm_row = QHBoxLayout()
        algorithm_row.addWidget(self._algorithm)
        algorithm_row.addWidget(self._algorithm_args)
        self._layout.addRow("Algorithm:", algorithm_row)
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
        self._solver.populate(c)
        self._constraints.setCurrentText(c.constraints)
        self._algorithm.setCurrentText(c.algorithm)
        self._algorithm_args.setCurrentIndex(1 if c.algorithm_args else 0)
        self._test.setCurrentText(c.test)
        self._tol.setValue(c.tolerance)
        self._max_iter.setValue(c.max_iter)

    def _read_specific(self, cid: int) -> PushoverCase:
        txt = self._base_nodes.text().strip()
        base_ids = [int(x) for x in txt.replace(",", " ").split() if x] if txt else []
        return PushoverCase(
            id=cid,
            name=self._name_edit.text(),
            pattern_ids=_selected_pattern_ids(self._patterns_picker) or [1],
            control_node=self._control_node.value(),
            control_dof=self._control_dof.value(),
            target_disp=self._target.value(),
            step_size=self._step.value(),
            base_nodes=base_ids,
            **self._solver.values(),  # type: ignore[arg-type]
            constraints=self._constraints.currentText(),
            algorithm=self._algorithm.currentText(),
            algorithm_args=("-initial",) if self._algorithm_args.currentIndex() == 1 else (),
            test=self._test.currentText(),
            tolerance=self._tol.value(),
            max_iter=self._max_iter.value(),
        )


class ResponseSpectrumCaseForm(CaseFormBase):
    type_label = "Response Spectrum — modal SRSS/CQC combination"

    def __init__(
        self,
        patterns: list[LoadPattern],
        analyses: list[AnalysisCase],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(patterns, analyses, parent)
        # Patterns aren't used by RS case but base class wants the param.
        self._modal_case = _int_spin(1, minimum=1)
        self._spectrum_id = _int_spin(1, minimum=1)
        self._direction = _int_spin(1, minimum=1, maximum=6)
        self._combination = QComboBox()
        self._combination.addItems(["CQC", "SRSS"])
        self._damping = _spin(0.0, minimum=0.0, maximum=1.0, step=0.01)
        self._damping.setSpecialValueText("spectrum damping")

        self._layout.addRow("Modal case ID:", self._modal_case)
        self._layout.addRow("Spectrum ID:", self._spectrum_id)
        self._layout.addRow("Direction (DOF):", self._direction)
        self._layout.addRow("Combination:", self._combination)
        self._layout.addRow("Modal damping (CQC):", self._damping)
        self._layout.addRow(
            _note(
                "<i>CQC (default) is independent of the eigen basis inside closely spaced "
                "mode pairs; SRSS is not and warns about them after a run. The damping feeds "
                "the CQC correlation only: 0 means the spectrum's own damping ratio.</i>",
            )
        )
        self._combination.currentTextChanged.connect(self._sync_damping_enabled)
        self._sync_damping_enabled(self._combination.currentText())

    def _sync_damping_enabled(self, rule: str) -> None:
        self._damping.setEnabled(rule == "CQC")

    def _populate_specific(self, c: ResponseSpectrumCase) -> None:
        self._modal_case.setValue(c.modal_case_id)
        self._spectrum_id.setValue(c.spectrum_id)
        self._direction.setValue(c.direction)
        self._combination.setCurrentText(c.combination)
        self._damping.setValue(c.damping_ratio if c.damping_ratio is not None else 0.0)
        self._sync_damping_enabled(c.combination)

    def _read_specific(self, cid: int) -> ResponseSpectrumCase:
        damp_val = self._damping.value()
        return ResponseSpectrumCase(
            id=cid,
            name=self._name_edit.text(),
            modal_case_id=self._modal_case.value(),
            spectrum_id=self._spectrum_id.value(),
            direction=self._direction.value(),
            combination=self._combination.currentText(),  # type: ignore[arg-type]
            damping_ratio=damp_val if damp_val > 0.0 else None,
        )


# ─────────────────────────── registry ───────────────────────────
FORM_REGISTRY: dict[str, type[CaseFormBase]] = {
    "Static": StaticCaseForm,
    "Modal": ModalCaseForm,
    "Transient": TransientCaseForm,
    "Pushover": PushoverCaseForm,
    "ResponseSpectrum": ResponseSpectrumCaseForm,
}


def form_for(
    case: AnalysisCase,
    patterns: list[LoadPattern],
    analyses: list[AnalysisCase],
) -> CaseFormBase:
    cls = FORM_REGISTRY[case.type]
    form = cls(patterns, analyses)
    form.populate(case)
    return form
