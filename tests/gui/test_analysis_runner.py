"""Unit tests for the AnalysisRunner Qt-thread orchestration.

These tests run a tiny analytical model end-to-end (Cantilever +
linear static), verifying signal flow without mocking. If openseespy
isn't importable on this platform, the whole module is skipped.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("openseespy.opensees")

from opensees_studio.commands import (
    AddAnalysisCasesCommand,
    AddElementsCommand,
    AddNodalLoadsCommand,
    AddNodesCommand,
    AddSectionsCommand,
)
from opensees_studio.core import (
    ElasticBeamColumn,
    ElasticSection,
    Node,
    StaticCase,
)
from opensees_studio.services.results import StaticResults
from opensees_studio.viewmodels import AnalysisRunner, ProjectViewModel


@pytest.fixture
def cantilever_vm() -> ProjectViewModel:
    """A minimal verifiable model: 2D cantilever beam with tip load."""
    L = 5.0
    vm = ProjectViewModel()
    vm.new_project(ndm=2, ndf=3)
    vm.apply_command(
        AddNodesCommand(
            vm,
            [
                Node(
                    id=1, coords=(0.0, 0.0, 0.0), restraint=(True, True, False, False, False, True)
                ),
                Node(id=2, coords=(L, 0.0, 0.0)),
            ],
        )
    )
    vm.apply_command(
        AddSectionsCommand(
            vm,
            [
                ElasticSection(id=1, E=200e9, A=0.01, Iz=8.333e-6),
            ],
        )
    )
    vm.apply_command(
        AddElementsCommand(
            vm,
            [
                ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1),
            ],
        )
    )
    vm.apply_command(AddNodalLoadsCommand(vm, {2}, (0.0, -1000.0, 0.0, 0.0, 0.0, 0.0)))
    vm.apply_command(
        AddAnalysisCasesCommand(
            vm,
            [
                StaticCase(id=1, name="Cantilever", pattern_ids=[1]),
            ],
        )
    )
    return vm


@pytest.mark.gui
def test_runner_emits_finished_with_static_results(qtbot, cantilever_vm) -> None:  # type: ignore[no-untyped-def]
    runner = AnalysisRunner()
    case = cantilever_vm.project.analyses[0]

    with qtbot.waitSignal(runner.finished, timeout=10000) as blocker:
        runner.run(cantilever_vm.project, case)

    results = blocker.args[0]
    assert isinstance(results, StaticResults)
    assert results.case_id == 1


@pytest.mark.gui
def test_runner_running_state_toggles(qtbot, cantilever_vm) -> None:  # type: ignore[no-untyped-def]
    runner = AnalysisRunner()
    case = cantilever_vm.project.analyses[0]
    assert not runner.is_running

    with qtbot.waitSignal(runner.runningChanged, timeout=10000) as blocker_start:
        runner.run(cantilever_vm.project, case)
    # First emission: running → True
    assert blocker_start.args[0] is True

    # Wait for finished + the second runningChanged → False
    with qtbot.waitSignal(runner.runningChanged, timeout=10000) as blocker_end:
        pass
    assert blocker_end.args[0] is False
    assert not runner.is_running


@pytest.mark.gui
def test_double_run_rejected(qtbot, cantilever_vm) -> None:  # type: ignore[no-untyped-def]
    runner = AnalysisRunner()
    case = cantilever_vm.project.analyses[0]
    runner.run(cantilever_vm.project, case)
    with pytest.raises(RuntimeError, match="already running"):
        runner.run(cantilever_vm.project, case)
    qtbot.waitSignal(runner.finished, timeout=10000).wait()


# ─────────────────── throwaway results directories ───────────────────
@pytest.mark.gui
def test_a_run_without_results_dir_cleans_up_after_itself(  # type: ignore[no-untyped-def]
    qtbot, cantilever_vm, tmp_path, monkeypatch
) -> None:
    """Static results live in memory once loaded; the scratch dir must go."""
    import tempfile

    real_mkdtemp = tempfile.mkdtemp

    def _mkdtemp_in(*args, **kwargs):  # type: ignore[no-untyped-def]
        return real_mkdtemp(*args, dir=str(tmp_path), **kwargs)

    monkeypatch.setattr(tempfile, "mkdtemp", _mkdtemp_in)
    runner = AnalysisRunner()

    with qtbot.waitSignal(runner.finished, timeout=20000):
        runner.run(cantilever_vm.project, cantilever_vm.project.analyses[0])
    qtbot.wait(50)  # let the queued teardown run

    assert list(tmp_path.glob("osstudio_*")) == []


@pytest.mark.gui
def test_a_caller_supplied_results_dir_is_kept(  # type: ignore[no-untyped-def]
    qtbot, cantilever_vm, tmp_path
) -> None:
    """A transient-style caller owns its directory; the runner must not delete it."""
    out_dir = tmp_path / "project_results"
    runner = AnalysisRunner()

    with qtbot.waitSignal(runner.finished, timeout=20000):
        runner.run(cantilever_vm.project, cantilever_vm.project.analyses[0], results_dir=out_dir)
    qtbot.wait(50)

    assert out_dir.is_dir()
    assert list(out_dir.glob("case_*.h5"))


@pytest.mark.gui
def test_transient_results_keep_their_scratch_dir(qtbot, tmp_path) -> None:
    """TransientResults streams from the .h5 file, so its directory has to survive."""
    from opensees_studio.services.results import TransientResults

    h5 = tmp_path / "case_1.h5"
    h5.write_bytes(b"")
    runner = AnalysisRunner()
    runner._out_dir = tmp_path
    runner._out_dir_is_temp = True
    runner._last_results = TransientResults(
        case_id=1, case_name="EQ", h5_path=h5, n_steps=10, dt=0.01, n_steps_requested=10
    )

    runner._discard_temp_out_dir()

    assert tmp_path.is_dir()
    assert h5.exists()
