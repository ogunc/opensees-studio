"""Unit tests for the AnalysisRunner Qt-thread orchestration.

These tests run a tiny analytical model end-to-end (Cantilever +
linear static), verifying signal flow without mocking. If openseespy
isn't importable on this platform, the whole module is skipped.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("openseespy.opensees")

from opensees_studio.commands import (  # noqa: E402
    AddAnalysisCasesCommand,
    AddElementsCommand,
    AddNodalLoadsCommand,
    AddNodesCommand,
    AddSectionsCommand,
)
from opensees_studio.core import (  # noqa: E402
    ElasticBeamColumn,
    ElasticSection,
    Node,
    StaticCase,
)
from opensees_studio.services.results import StaticResults  # noqa: E402
from opensees_studio.viewmodels import AnalysisRunner, ProjectViewModel  # noqa: E402


@pytest.fixture
def cantilever_vm() -> ProjectViewModel:
    """A minimal verifiable model: 2D cantilever beam with tip load."""
    L = 5.0
    vm = ProjectViewModel()
    vm.new_project(ndm=2, ndf=3)
    vm.apply_command(AddNodesCommand(vm, [
        Node(id=1, coords=(0.0, 0.0, 0.0),
             restraint=(True, True, False, False, False, True)),
        Node(id=2, coords=(L, 0.0, 0.0)),
    ]))
    vm.apply_command(AddSectionsCommand(vm, [
        ElasticSection(id=1, E=200e9, A=0.01, Iz=8.333e-6),
    ]))
    vm.apply_command(AddElementsCommand(vm, [
        ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1),
    ]))
    vm.apply_command(AddNodalLoadsCommand(vm, {2}, (0.0, -1000.0, 0.0, 0.0, 0.0, 0.0)))
    vm.apply_command(AddAnalysisCasesCommand(vm, [
        StaticCase(id=1, name="Cantilever", pattern_ids=[1]),
    ]))
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
