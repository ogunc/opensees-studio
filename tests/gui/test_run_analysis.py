"""GUI tests for the Run Analysis dialog."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QObject, Signal  # noqa: E402

from opensees_studio.core import LinearTimeSeries, PlainLoadPattern, Project, TransientCase  # noqa: E402
from opensees_studio.viewmodels import ProjectViewModel  # noqa: E402
from opensees_studio.views.dialogs.run_analysis import RunAnalysisDialog  # noqa: E402


class _FakeRunner(QObject):
    started = Signal()
    log = Signal(str)
    finished = Signal(object)
    failed = Signal(str)
    runningChanged = Signal(bool)

    def __init__(self) -> None:
        super().__init__()
        self.is_running = False
        self.last_project = None
        self.last_case = None
        self.last_results_dir = None

    def run(self, project, case, results_dir=None) -> None:  # type: ignore[no-untyped-def]
        self.last_project = project
        self.last_case = case
        self.last_results_dir = results_dir


@pytest.mark.gui
def test_run_dialog_applies_transient_damping_overrides(qtbot, tmp_path) -> None:  # type: ignore[no-untyped-def]
    vm = ProjectViewModel()
    vm.new_project()
    vm.project.time_series.append(LinearTimeSeries(id=1, name="Ramp"))  # type: ignore[union-attr]
    vm.project.load_patterns.append(PlainLoadPattern(id=1, name="P1", time_series_id=1))  # type: ignore[union-attr]
    vm.project.analyses.append(TransientCase(  # type: ignore[union-attr]
        id=1,
        name="EQ",
        pattern_ids=[1],
        dt=0.01,
        n_steps=10,
        rayleigh_alpha_m=0.1,
        rayleigh_beta_k=0.002,
        rayleigh_mode1_damping=0.02,
    ))
    vm._path = Path(tmp_path) / "demo.osmodel"  # type: ignore[attr-defined]

    runner = _FakeRunner()
    dlg = RunAnalysisDialog(vm, runner)
    qtbot.addWidget(dlg)

    dlg._case_combo.setCurrentIndex(0)
    assert dlg._alpha_m.value() == pytest.approx(0.1)
    assert dlg._beta_k.value() == pytest.approx(0.002)
    assert dlg._mode1_damping.value() == pytest.approx(0.02)

    dlg._alpha_m.setValue(0.3)
    dlg._beta_k.setValue(0.005)
    dlg._mode1_damping.setValue(0.05)
    dlg._on_run()

    assert runner.last_project is vm.project
    assert runner.last_case.rayleigh_alpha_m == pytest.approx(0.3)
    assert runner.last_case.rayleigh_beta_k == pytest.approx(0.005)
    assert runner.last_case.rayleigh_mode1_damping == pytest.approx(0.05)
    assert runner.last_results_dir == tmp_path / "demo_results"
