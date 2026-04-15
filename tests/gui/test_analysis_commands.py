"""Unit tests for analysis case commands."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from opensees_studio.commands import (  # noqa: E402
    AddAnalysisCasesCommand,
    DeleteAnalysisCasesCommand,
    UpdateAnalysisCaseCommand,
)
from opensees_studio.core import (  # noqa: E402
    LinearTimeSeries,
    ModalCase,
    NodalLoad,
    Node,
    PlainLoadPattern,
    StaticCase,
    TransientCase,
)
from opensees_studio.viewmodels import ProjectViewModel  # noqa: E402


def _vm_with_pattern() -> ProjectViewModel:
    vm = ProjectViewModel()
    vm.new_project()
    vm.project.nodes.append(Node(id=1, coords=(0, 0, 0)))
    vm.project.time_series.append(LinearTimeSeries(id=1))
    vm.project.load_patterns.append(
        PlainLoadPattern(id=1, time_series_id=1,
                         nodal_loads=[NodalLoad(node_id=1, forces=(100, 0, 0, 0, 0, 0))])
    )
    return vm


# ──────────────────────── Add ────────────────────────
@pytest.mark.gui
def test_add_static_case(qtbot) -> None:  # type: ignore[no-untyped-def]
    vm = _vm_with_pattern()
    case = StaticCase(id=1, name="LS", pattern_ids=[1])
    vm.apply_command(AddAnalysisCasesCommand(vm, [case]))
    assert len(vm.project.analyses) == 1
    assert isinstance(vm.project.analyses[0], StaticCase)


@pytest.mark.gui
def test_add_modal_case_no_pattern_needed(qtbot) -> None:  # type: ignore[no-untyped-def]
    vm = ProjectViewModel()
    vm.new_project()
    vm.apply_command(AddAnalysisCasesCommand(vm, [ModalCase(id=1, n_modes=3)]))
    assert isinstance(vm.project.analyses[0], ModalCase)


@pytest.mark.gui
def test_add_emits_modelMutated(qtbot) -> None:  # type: ignore[no-untyped-def]
    vm = _vm_with_pattern()
    with qtbot.waitSignal(vm.modelMutated, timeout=500):
        vm.apply_command(AddAnalysisCasesCommand(vm, [
            StaticCase(id=1, pattern_ids=[1]),
        ]))


@pytest.mark.gui
def test_add_duplicate_id_raises(qtbot) -> None:  # type: ignore[no-untyped-def]
    vm = _vm_with_pattern()
    vm.apply_command(AddAnalysisCasesCommand(vm, [StaticCase(id=1, pattern_ids=[1])]))
    with pytest.raises(ValueError, match="already exists"):
        vm.apply_command(AddAnalysisCasesCommand(vm, [StaticCase(id=1, pattern_ids=[1])]))


# ──────────────────────── Update ────────────────────────
@pytest.mark.gui
def test_update_static_changes_n_steps(qtbot) -> None:  # type: ignore[no-untyped-def]
    vm = _vm_with_pattern()
    vm.apply_command(AddAnalysisCasesCommand(vm, [
        StaticCase(id=1, name="A", pattern_ids=[1], n_steps=1),
    ]))
    new = StaticCase(id=1, name="A", pattern_ids=[1], n_steps=10)
    vm.apply_command(UpdateAnalysisCaseCommand(vm, new))
    assert vm.project.analyses[0].n_steps == 10
    vm.undo_stack.undo()
    assert vm.project.analyses[0].n_steps == 1


@pytest.mark.gui
def test_update_changes_case_type(qtbot) -> None:  # type: ignore[no-untyped-def]
    vm = _vm_with_pattern()
    vm.apply_command(AddAnalysisCasesCommand(vm, [
        StaticCase(id=1, pattern_ids=[1]),
    ]))
    swapped = ModalCase(id=1, name="Mode swap", n_modes=5)
    vm.apply_command(UpdateAnalysisCaseCommand(vm, swapped))
    assert isinstance(vm.project.analyses[0], ModalCase)
    vm.undo_stack.undo()
    assert isinstance(vm.project.analyses[0], StaticCase)


@pytest.mark.gui
def test_update_unknown_id_raises(qtbot) -> None:  # type: ignore[no-untyped-def]
    vm = _vm_with_pattern()
    bogus = ModalCase(id=99)
    with pytest.raises(KeyError):
        vm.apply_command(UpdateAnalysisCaseCommand(vm, bogus))


# ──────────────────────── Delete ────────────────────────
@pytest.mark.gui
def test_delete_round_trip(qtbot) -> None:  # type: ignore[no-untyped-def]
    vm = _vm_with_pattern()
    vm.apply_command(AddAnalysisCasesCommand(vm, [
        StaticCase(id=1, pattern_ids=[1]),
        ModalCase(id=2),
    ]))
    vm.apply_command(DeleteAnalysisCasesCommand(vm, {1}))
    assert {c.id for c in vm.project.analyses} == {2}
    vm.undo_stack.undo()
    assert {c.id for c in vm.project.analyses} == {1, 2}


# ──────────────────────── Transient defaults ────────────────────────
@pytest.mark.gui
def test_transient_case_default_integrator_params(qtbot) -> None:  # type: ignore[no-untyped-def]
    """Newmark γ=0.5, β=0.25 (average acceleration) — unconditionally stable."""
    vm = _vm_with_pattern()
    case = TransientCase(id=1, pattern_ids=[1], dt=0.01, n_steps=100)
    vm.apply_command(AddAnalysisCasesCommand(vm, [case]))
    assert vm.project.analyses[0].integrator == "Newmark"
    assert vm.project.analyses[0].integrator_params == (0.5, 0.25)
