"""Run Analysis dialog - pick a case, watch it run, see results when done."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from opensees_studio.viewmodels import AnalysisRunner, ProjectViewModel


class RunAnalysisDialog(QDialog):
    """Modal dialog: select a case, hit Run, watch the log."""

    def __init__(
        self,
        vm: ProjectViewModel,
        runner: AnalysisRunner,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Run Analysis")
        self.resize(640, 480)
        self._vm = vm
        self._runner = runner
        self._results: Any = None
        self._build_ui()
        self._wire()
        self._populate_cases()

    @property
    def results(self) -> Any:
        """Set after a successful run; ``None`` if cancelled or failed."""
        return self._results

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        row = QHBoxLayout()
        row.addWidget(QLabel("Case:"))
        self._case_combo = QComboBox()
        row.addWidget(self._case_combo, stretch=1)
        layout.addLayout(row)

        # Run-time damping overrides for transient cases only.
        self._damping_box = QGroupBox("Rayleigh damping (transient only)")
        form = QFormLayout(self._damping_box)

        self._alpha_m = QDoubleSpinBox()
        self._alpha_m.setRange(0.0, 1e6)
        self._alpha_m.setDecimals(6)
        self._alpha_m.setSingleStep(0.01)
        form.addRow("alphaM (mass-prop.):", self._alpha_m)

        self._beta_k = QDoubleSpinBox()
        self._beta_k.setRange(0.0, 1e6)
        self._beta_k.setDecimals(6)
        self._beta_k.setSingleStep(1e-4)
        form.addRow("betaK (stiffness-prop.):", self._beta_k)

        self._mode1_damping = QDoubleSpinBox()
        self._mode1_damping.setRange(0.0, 1.0)
        self._mode1_damping.setDecimals(6)
        self._mode1_damping.setSingleStep(0.01)
        form.addRow("Mode-1 damping zeta:", self._mode1_damping)

        form.addRow(QLabel(
            "<i>Values are applied for this run only. If mode-1 damping is "
            "greater than zero, the runner computes betaK from the first "
            "mode after preload and overrides the manual betaK value.</i>",
        ))
        layout.addWidget(self._damping_box)

        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setVisible(False)
        layout.addWidget(self._progress)

        layout.addWidget(QLabel("<b>Log:</b>"))
        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        layout.addWidget(self._log, stretch=1)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Close, parent=self,
        )
        self._run_btn = QPushButton("Run")
        self._buttons.addButton(self._run_btn, QDialogButtonBox.ButtonRole.ActionRole)
        layout.addWidget(self._buttons)

    def _wire(self) -> None:
        self._run_btn.clicked.connect(self._on_run)
        self._buttons.rejected.connect(self.reject)
        self._case_combo.currentIndexChanged.connect(self._on_case_changed)

        self._runner.started.connect(self._on_started)
        self._runner.log.connect(self._on_log)
        self._runner.finished.connect(self._on_finished)
        self._runner.failed.connect(self._on_failed)
        self._runner.runningChanged.connect(self._on_running_changed)

    def _on_case_changed(self, _idx: int) -> None:
        """Show damping controls only for transient cases; pre-fill from the case."""
        if self._vm.project is None:
            self._damping_box.setVisible(False)
            return
        cid = self._case_combo.currentData()
        case = next((c for c in self._vm.project.analyses if c.id == cid), None)
        is_transient = case is not None and case.type == "Transient"
        self._damping_box.setVisible(is_transient)
        if is_transient:
            self._alpha_m.setValue(float(getattr(case, "rayleigh_alpha_m", 0.0)))
            self._beta_k.setValue(float(getattr(case, "rayleigh_beta_k", 0.0)))
            self._mode1_damping.setValue(
                float(getattr(case, "rayleigh_mode1_damping", 0.0) or 0.0),
            )

    def _populate_cases(self) -> None:
        self._case_combo.clear()
        if self._vm.project is None:
            return
        for case in self._vm.project.analyses:
            label = f"#{case.id}  {case.name or '(unnamed)'}  [{case.type}]"
            self._case_combo.addItem(label, userData=case.id)
        self._run_btn.setEnabled(self._case_combo.count() > 0)
        if self._case_combo.count() == 0:
            self._log.appendPlainText("No analysis cases. Define one in Analyze -> Cases...")

    def _on_run(self) -> None:
        if self._runner.is_running or self._vm.project is None:
            return
        case_id = self._case_combo.currentData()
        case = next((c for c in self._vm.project.analyses if c.id == case_id), None)
        if case is None:
            return
        if case.type == "Transient":
            mode1 = float(self._mode1_damping.value())
            case = case.model_copy(update={
                "rayleigh_alpha_m": float(self._alpha_m.value()),
                "rayleigh_beta_k": float(self._beta_k.value()),
                "rayleigh_mode1_damping": mode1 if mode1 > 0.0 else None,
            })
        self._results = None
        self._log.clear()
        results_dir: Path | None = None
        if case.type == "Transient" and self._vm.path is not None:
            results_dir = self._vm.path.parent / f"{self._vm.path.stem}_results"
        try:
            self._runner.run(self._vm.project, case, results_dir=results_dir)
        except Exception as exc:  # noqa: BLE001
            self._log.appendPlainText(f"Could not start: {exc}")

    def _on_started(self) -> None:
        self._log.appendPlainText("--- Analysis started ---")

    def _on_log(self, message: str) -> None:
        self._log.appendPlainText(message)

    def _on_finished(self, results: Any) -> None:
        self._results = results
        kind = type(results).__name__
        self._log.appendPlainText(f"--- Done. Returned {kind}. ---")

    def _on_failed(self, traceback_str: str) -> None:
        self._log.appendPlainText("--- FAILED ---")
        self._log.appendPlainText(traceback_str)

    def _on_running_changed(self, running: bool) -> None:
        self._progress.setVisible(running)
        self._run_btn.setEnabled(not running)
        self._case_combo.setEnabled(not running)
