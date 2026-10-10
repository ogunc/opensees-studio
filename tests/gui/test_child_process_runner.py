"""Analyses run in a child process: results arrive, a hard exit is reported, cancel works."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("openseespy.opensees")

from PySide6.QtCore import QProcess, QTimer
from PySide6.QtWidgets import QApplication

from opensees_studio.services import load_project
from opensees_studio.services.opensees_runner import SKIP_BEARING_ORIENT_ENV
from opensees_studio.services.results import StaticResults, TransientResults
from opensees_studio.viewmodels import AnalysisRunner
from opensees_studio.viewmodels.analysis_runner import IN_PROCESS_ENV, NO_STDERR_PLACEHOLDER
from opensees_studio.views.main_window import MainWindow

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"


@pytest.fixture(autouse=True)
def _child_process_mode(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv(IN_PROCESS_ENV, raising=False)
    monkeypatch.delenv("OPENSEES_STUDIO_CLI_HARD_EXIT_AFTER", raising=False)
    monkeypatch.delenv(SKIP_BEARING_ORIENT_ENV, raising=False)


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
    # Unbuffered child: what OpenSees printed before the exit (the mode-1 damping
    # eigen call's solver-speed banner) is in the failure details, not lost.
    assert "VERY SLOW" in report
    assert NO_STDERR_PLACEHOLDER not in report
    assert window._runner.last_exit_code == 255
    assert window.isVisible()
    assert not window._runner.is_running
    box = window._analysis_error_box
    assert box is not None and box.isVisible()
    assert "255" in box.text()
    assert "stderr (last 40 lines)" in box.detailedText()
    assert "VERY SLOW" in box.detailedText()
    assert [n.model_dump() for n in window._vm.project.nodes] == nodes_before
    assert window._vm.run_snapshot_path.is_file()  # kept for recovery
    box.close()


@pytest.mark.gui
def test_hard_exit_without_stderr_output_shows_the_placeholder(
    qtbot, tmp_path, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    """Without mode-1 damping the case makes no eigen call and the hook exits before
    anything reaches stderr: the details say so instead of showing an empty area."""
    monkeypatch.setenv("OPENSEES_STUDIO_CLI_HARD_EXIT_AFTER", "2")
    path = _copy_example("ex1a_canti2d", tmp_path)
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    assert window.open_project(path)
    case = next(c for c in window._vm.project.analyses if c.id == 3)
    quiet = case.model_copy(update={"rayleigh_mode1_damping": None})

    with qtbot.waitSignal(window._runner.failed, timeout=60000) as blocker:
        window._runner.run(window._vm.project, quiet, project_path=path)

    assert window._runner.last_exit_code == 255
    assert blocker.args[0].rstrip().endswith(NO_STDERR_PLACEHOLDER)
    box = window._analysis_error_box
    assert NO_STDERR_PLACEHOLDER in box.detailedText()
    box.close()


@pytest.mark.gui
def test_failure_box_opens_in_front_of_the_run_dialog(qtbot, tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """The report of a process failure is a child of the open Run dialog and the
    active window, not hidden behind the modal dialog on the main window."""
    monkeypatch.setenv("OPENSEES_STUDIO_CLI_HARD_EXIT_AFTER", "2")
    path = _copy_example("ex1a_canti2d", tmp_path)
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    assert window.open_project(path)
    seen: dict[str, object] = {}

    def drive_the_dialog() -> None:
        dlg = window._run_dialog
        seen["dialog"] = dlg
        index = dlg._case_combo.findData(3)
        dlg._case_combo.setCurrentIndex(index)
        failed: list[str] = []
        window._runner.failed.connect(failed.append)
        dlg._run_btn.click()
        qtbot.waitUntil(lambda: bool(failed), timeout=60000)
        box = window._analysis_error_box
        qtbot.waitUntil(lambda: QApplication.activeWindow() is box, timeout=5000)
        seen["parent"] = box.parent()
        seen["active"] = QApplication.activeWindow()
        seen["box"] = box
        seen["visible"] = box.isVisible()
        dlg.reject()

    QTimer.singleShot(0, drive_the_dialog)
    window._on_run_analysis()

    box = seen["box"]
    assert seen["parent"] is seen["dialog"]
    assert seen["active"] is box
    assert seen["visible"]
    # Closing the Run dialog leaves the unread report open on the main window.
    assert box.parent() is window
    assert box.isVisible()
    box.close()


@pytest.mark.gui
def test_real_opensees_crash_shows_its_own_message_in_front(qtbot, tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """OpenSees itself terminates on a bearing without -orient (test hook): the failure
    report opens in front of the Run dialog with OpenSees' orientation message."""
    monkeypatch.setenv(SKIP_BEARING_ORIENT_ENV, "1")
    path = _copy_example("isolated_portal2d", tmp_path)
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    assert window.open_project(path)
    seen: dict[str, object] = {}

    def drive_the_dialog() -> None:
        dlg = window._run_dialog
        dlg._case_combo.setCurrentIndex(dlg._case_combo.findData(1))
        failed: list[str] = []
        window._runner.failed.connect(failed.append)
        dlg._run_btn.click()
        qtbot.waitUntil(lambda: bool(failed), timeout=60000)
        box = window._analysis_error_box
        seen.update(dialog=dlg, parent=box.parent(), details=box.detailedText(), report=failed[0])
        dlg.reject()

    QTimer.singleShot(0, drive_the_dialog)
    window._on_run_analysis()

    assert seen["parent"] is seen["dialog"]
    assert window._runner.last_exit_code not in (0, 2, 3)
    assert "No error line was reported" in seen["report"]
    assert "orientation" in seen["details"]
    assert NO_STDERR_PLACEHOLDER not in seen["details"]
    window._analysis_error_box.close()


@pytest.mark.gui
def test_solver_speed_banner_stays_out_of_the_run_log(qtbot, tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Modal-6 of space_frame_3d runs fullGenLapack, whose VERY SLOW banner OpenSees
    prints: it is kept in the raw stderr capture and never reaches the log."""
    path = _copy_example("space_frame_3d", tmp_path)
    project = load_project(path)
    case = next(c for c in project.analyses if c.name == "Modal-6")
    runner = AnalysisRunner()
    logs: list[str] = []
    runner.log.connect(logs.append)
    with qtbot.waitSignal(runner.finished, timeout=60000):
        runner.run(project, case, project_path=path)
    assert any("fullGenLapack" in line for line in logs)
    assert not any("VERY SLOW" in line for line in logs)
    assert "VERY SLOW" in runner._stderr  # raw capture keeps it
    # the same line arriving on the protocol stream is dropped as well
    banner = "WARNING - the 'fullGenLapack' eigen solver is VERY SLOW. Consider using the default."
    runner._handle_line(banner)
    runner._handle_line(json.dumps({"type": "log", "message": banner}))
    assert not any("VERY SLOW" in line for line in logs)


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


@pytest.mark.gui
def test_missing_recorder_output_reaches_the_failure_report(qtbot, tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """A recorder that writes nothing fails the run with the file named (in-process mode,
    where the runner can be wrapped; the child reports the same error as exit code 2)."""
    import openseespy.opensees as ops

    from opensees_studio.services import qt_workers
    from tests.integration._recorder_faults import DropOneRecorder

    class Runner(qt_workers.OpenSeesRunner):
        def __init__(self, project, ops_module=None, on_progress=None) -> None:  # type: ignore[no-untyped-def]
            super().__init__(project, DropOneRecorder(ops, "nodes_disp.out"), on_progress)

    monkeypatch.setenv(IN_PROCESS_ENV, "1")
    monkeypatch.setattr(qt_workers, "OpenSeesRunner", Runner)
    path = _copy_example("ex1a_canti2d", tmp_path)
    project = load_project(path)
    case = next(c for c in project.analyses if c.id == 3)
    runner = AnalysisRunner()
    results_dir = tmp_path / "ex1a_canti2d_results"
    with qtbot.waitSignal(runner.failed, timeout=60000) as blocker:
        runner.run(project, case, results_dir=results_dir, project_path=path)
    assert "RecorderOutputError" in blocker.args[0]
    assert "nodes_disp.out" in blocker.args[0]
    assert not (results_dir / "case_3.h5").exists()


_INJECT_DROPPED_RECORDER = """
import sys

sys.path.insert(0, {repo!r})

import openseespy.opensees as ops

import opensees_studio.services.opensees_runner as runner_module
from tests.integration._recorder_faults import DropOneRecorder


class Runner(runner_module.OpenSeesRunner):
    def __init__(self, project, ops_module=None, on_progress=None):
        super().__init__(project, DropOneRecorder(ops, "nodes_disp.out"), on_progress)


runner_module.OpenSeesRunner = Runner
"""


@pytest.mark.gui
def test_missing_recorder_output_in_the_child_opens_the_error_dialog(
    qtbot, tmp_path, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    """Default child-process mode: the child fails the case with exit code 2 and the
    window shows the report naming the recorder file. The fault is injected into
    the child through a sitecustomize module on PYTHONPATH (QProcess inherits it)."""
    inject = tmp_path / "inject"
    inject.mkdir()
    repo = str(Path(__file__).resolve().parents[2])
    (inject / "sitecustomize.py").write_text(
        _INJECT_DROPPED_RECORDER.format(repo=repo), encoding="utf-8"
    )
    monkeypatch.setenv("PYTHONPATH", str(inject))
    path = _copy_example("ex1a_canti2d", tmp_path)
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    assert window.open_project(path)
    case = next(c for c in window._vm.project.analyses if c.id == 3)

    with qtbot.waitSignal(window._runner.failed, timeout=60000) as blocker:
        window._runner.run(window._vm.project, case, project_path=path)

    report = blocker.args[0]
    assert window._runner.last_exit_code == 2
    assert "Last error:" in report
    assert "nodes_disp.out" in report
    box = window._analysis_error_box
    assert box is not None and box.isVisible()
    assert "nodes_disp.out" in box.detailedText()
    assert window._latest_results is None
    box.close()
