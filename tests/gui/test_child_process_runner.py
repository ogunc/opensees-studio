"""Analyses run in a child process: results arrive, a hard exit is reported, cancel works."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("openseespy.opensees")

from PySide6.QtCore import QProcess

from opensees_studio.services import load_project
from opensees_studio.services.results import StaticResults, TransientResults
from opensees_studio.viewmodels import AnalysisRunner
from opensees_studio.viewmodels.analysis_runner import IN_PROCESS_ENV
from opensees_studio.views.main_window import MainWindow

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"


@pytest.fixture(autouse=True)
def _child_process_mode(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv(IN_PROCESS_ENV, raising=False)
    monkeypatch.delenv("OPENSEES_STUDIO_CLI_HARD_EXIT_AFTER", raising=False)


def _copy_example(name: str, tmp_path: Path) -> Path:
    """Copy an example and its record directory so relative record paths resolve."""
    target = tmp_path / f"{name}.osmodel"
    shutil.copy(EXAMPLES / f"{name}.osmodel", target)
    if (EXAMPLES / "data").is_dir() and not (tmp_path / "data").exists():
        shutil.copytree(EXAMPLES / "data", tmp_path / "data")
    return target


@pytest.mark.gui
def test_normal_run_through_qprocess_updates_the_results_views(qtbot, tmp_path) -> None:  # type: ignore[no-untyped-def]
    path = _copy_example("cantilever", tmp_path)
    window = MainWindow()
    qtbot.addWidget(window)
    assert window.open_project(path)
    case = window._vm.project.analyses[0]
    assert not window._act_show_deformed.isEnabled()

    logs: list[str] = []
    window._runner.log.connect(logs.append)
    with qtbot.waitSignal(window._runner.finished, timeout=60000) as blocker:
        window._runner.run(window._vm.project, case, project_path=path)
        assert window._runner.can_cancel

    results = blocker.args[0]
    assert isinstance(results, StaticResults)
    assert window._latest_results is results
    assert window._act_show_deformed.isEnabled()
    assert window._act_show_force_diagram.isEnabled()
    assert results.disp(2, 2) < 0.0  # tip goes down under the tip load
    assert any("opensees_studio.run" in line for line in logs)
    assert any(line == "Analysis complete." for line in logs)
    assert window._runner.last_exit_code == 0
    assert not window._runner.is_running


@pytest.mark.gui
def test_hard_exit_in_the_child_leaves_the_window_alive_with_a_report(
    qtbot, tmp_path, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("OPENSEES_STUDIO_CLI_HARD_EXIT_AFTER", "2")
    path = _copy_example("ex1a_canti2d", tmp_path)
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    assert window.open_project(path)
    case = next(c for c in window._vm.project.analyses if c.id == 3)
    nodes_before = [n.model_dump() for n in window._vm.project.nodes]

    with qtbot.waitSignal(window._runner.failed, timeout=60000) as blocker:
        window._runner.run(window._vm.project, case, project_path=path)

    report = blocker.args[0]
    assert "exited with code 255" in report
    assert "No error line was reported" in report
    assert "stderr (last 40 lines)" in report
    assert window._runner.last_exit_code == 255
    assert window.isVisible()
    assert not window._runner.is_running
    box = window._analysis_error_box
    assert box is not None and box.isVisible()
    assert "255" in box.text()
    assert "stderr (last 40 lines)" in box.detailedText()
    assert [n.model_dump() for n in window._vm.project.nodes] == nodes_before
    assert window._vm.run_snapshot_path.is_file()  # kept for recovery
    box.close()


@pytest.mark.gui
def test_cancel_during_a_long_transient_ends_with_cancelled(qtbot, tmp_path) -> None:  # type: ignore[no-untyped-def]
    path = _copy_example("ex1a_canti2d", tmp_path)
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    assert window.open_project(path)
    project = window._vm.project
    case = next(c for c in project.analyses if c.id == 3)
    long_case = case.model_copy(update={"n_steps": 2_000_000})
    dumped_before = project.model_dump()
    runner: AnalysisRunner = window._runner

    outcomes: list[str] = []
    runner.finished.connect(lambda _r: outcomes.append("finished"))
    runner.failed.connect(lambda _m: outcomes.append("failed"))
    runner.cancelled.connect(lambda: outcomes.append("cancelled"))

    with qtbot.waitSignal(runner.progress, timeout=60000):
        runner.run(project, long_case, project_path=path)
    process = runner._process
    assert process is not None and process.state() == QProcess.ProcessState.Running

    with qtbot.waitSignal(runner.cancelled, timeout=30000):
        runner.cancel()

    assert outcomes == ["cancelled"]
    assert not runner.is_running
    assert runner._process is None
    assert process.state() == QProcess.ProcessState.NotRunning
    assert window._vm.project is project
    assert project.model_dump() == dumped_before
    assert not window._vm.is_dirty
    # The window is responsive: the event loop turns and the widget answers.
    qtbot.waitUntil(lambda: window.isVisible(), timeout=5000)
    assert window._latest_results is None


@pytest.mark.gui
def test_in_process_mode_still_works_and_cannot_cancel(qtbot, tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv(IN_PROCESS_ENV, "1")
    project = load_project(EXAMPLES / "cantilever.osmodel")
    runner = AnalysisRunner()
    logs: list[str] = []
    runner.log.connect(logs.append)
    with qtbot.waitSignal(runner.finished, timeout=30000) as blocker:
        runner.run(project, project.analyses[0], project_path=tmp_path / "c.osmodel")
        assert not runner.can_cancel
    assert isinstance(blocker.args[0], StaticResults)
    assert any("in-process" in line for line in logs)


@pytest.mark.gui
def test_transient_results_from_the_child_live_in_the_results_dir(qtbot, tmp_path) -> None:  # type: ignore[no-untyped-def]
    path = _copy_example("ex1a_canti2d", tmp_path)
    project = load_project(path)
    case = next(c for c in project.analyses if c.id == 3)
    runner = AnalysisRunner()
    results_dir = tmp_path / "ex1a_canti2d_results"
    with qtbot.waitSignal(runner.finished, timeout=60000) as blocker:
        runner.run(project, case, results_dir=results_dir, project_path=path)
    results = blocker.args[0]
    assert isinstance(results, TransientResults)
    assert results.h5_path == results_dir / "case_3.h5"
    assert results.n_steps == 1000
    assert (results_dir / "manifest.json").is_file()
    assert results.node_disp_history(2).shape == (1000, 3)
