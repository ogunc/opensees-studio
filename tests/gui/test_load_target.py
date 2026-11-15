"""Load dialogs choose the pattern and whether a load adds, replaces or deletes."""

from __future__ import annotations

import pytest

from opensees_studio.commands import AddElementLoadsCommand, AddNodalLoadsCommand
from opensees_studio.commands.loads import AddPointElementLoadsCommand
from opensees_studio.core import (
    ElasticBeamColumn,
    ElasticSection,
    LinearTimeSeries,
    Node,
    PlainLoadPattern,
    Project,
    UniformElementLoad,
)
from opensees_studio.viewmodels import ProjectViewModel

pytestmark = pytest.mark.gui


def _vm() -> ProjectViewModel:
    project = Project()
    project.nodes = [Node(id=1, coords=(0, 0, 0)), Node(id=2, coords=(5, 0, 0))]
    project.sections = [ElasticSection(id=1, E=2e11, A=0.01, Iz=1e-4, Iy=1e-4, G=8e10, J=1e-5)]
    project.elements = [ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1)]
    project.time_series = [LinearTimeSeries(id=1), LinearTimeSeries(id=2)]
    project.load_patterns = [
        PlainLoadPattern(
            id=1,
            name="DEAD",
            time_series_id=1,
            element_loads=[UniformElementLoad(element_id=1, wz=-1000.0)],
        ),
        PlainLoadPattern(id=2, name="LIVE", time_series_id=2),
    ]
    vm = ProjectViewModel()
    vm.adopt(project)
    return vm


def _pattern(vm: ProjectViewModel, pid: int) -> PlainLoadPattern:
    return next(p for p in vm.project.load_patterns if p.id == pid)


def test_a_frame_load_goes_into_the_chosen_pattern(qtbot) -> None:
    vm = _vm()
    vm.apply_command(AddElementLoadsCommand(vm, {1}, wz=-300.0, pattern_id=2))
    assert [x.wz for x in _pattern(vm, 2).element_loads] == [-300.0]
    assert [x.wz for x in _pattern(vm, 1).element_loads] == [-1000.0]


def test_replace_swaps_the_load_and_undo_brings_it_back(qtbot) -> None:
    vm = _vm()
    vm.apply_command(AddElementLoadsCommand(vm, {1}, wz=-500.0, pattern_id=1, mode="replace"))
    assert [x.wz for x in _pattern(vm, 1).element_loads] == [-500.0]
    vm.undo_stack.undo()
    assert [x.wz for x in _pattern(vm, 1).element_loads] == [-1000.0]
    vm.undo_stack.redo()
    assert [x.wz for x in _pattern(vm, 1).element_loads] == [-500.0]


def test_add_sums_and_delete_removes_only_that_kind_in_that_pattern(qtbot) -> None:
    vm = _vm()
    vm.apply_command(AddElementLoadsCommand(vm, {1}, wz=-500.0, pattern_id=1))
    assert [x.wz for x in _pattern(vm, 1).element_loads] == [-1000.0, -500.0]
    vm.apply_command(AddPointElementLoadsCommand(vm, {1: 0.5}, pz=-10.0, pattern_id=1))
    vm.apply_command(AddElementLoadsCommand(vm, {1}, pattern_id=1, mode="delete"))
    assert _pattern(vm, 1).element_loads == []
    assert len(_pattern(vm, 1).point_loads) == 1  # another kind: untouched
    vm.undo_stack.undo()
    assert [x.wz for x in _pattern(vm, 1).element_loads] == [-1000.0, -500.0]


def test_nodal_replace_and_delete(qtbot) -> None:
    vm = _vm()
    vm.apply_command(AddNodalLoadsCommand(vm, {2}, (1.0, 0, 0, 0, 0, 0), pattern_id=2))
    vm.apply_command(
        AddNodalLoadsCommand(vm, {2}, (5.0, 0, 0, 0, 0, 0), pattern_id=2, mode="replace")
    )
    assert [x.forces[0] for x in _pattern(vm, 2).nodal_loads] == [5.0]
    vm.apply_command(AddNodalLoadsCommand(vm, {2}, (0, 0, 0, 0, 0, 0), pattern_id=2, mode="delete"))
    assert _pattern(vm, 2).nodal_loads == []
    vm.undo_stack.undo()
    assert [x.forces[0] for x in _pattern(vm, 2).nodal_loads] == [5.0]


def test_an_unknown_mode_is_refused(qtbot) -> None:
    with pytest.raises(ValueError, match="load mode"):
        AddElementLoadsCommand(_vm(), {1}, wz=-1.0, mode="merge")


def test_the_dialog_offers_the_patterns_units_and_remembers_the_last_one(qtbot) -> None:
    from opensees_studio.views.dialogs import load_target
    from opensees_studio.views.dialogs.distributed_load import AssignDistributedLoadDialog

    patterns = [(1, "DEAD"), (2, "LIVE")]
    dialog = AssignDistributedLoadDialog(1, patterns=patterns, units="N/m")
    qtbot.addWidget(dialog)
    assert dialog._labels["wz"].text() == "Fz (N/m):"
    dialog.target.set_pattern(2)
    dialog.target.set_mode(load_target.DELETE)
    assert not dialog._spinboxes["wz"].isEnabled()
    dialog._on_accept()
    assert (dialog.pattern_id(), dialog.load_mode()) == (2, "delete")

    again = AssignDistributedLoadDialog(1, patterns=patterns)
    qtbot.addWidget(again)
    assert again.pattern_id() == 2  # LIVE again, without picking it
    assert again.load_mode() == "add"


def test_a_project_without_patterns_says_one_is_created(qtbot) -> None:
    from opensees_studio.views.dialogs.point_element_load import AssignPointElementLoadDialog

    dialog = AssignPointElementLoadDialog(1, patterns=[], units="kip")
    qtbot.addWidget(dialog)
    assert dialog.pattern_id() is None
    assert "default pattern" in dialog.target._pattern.currentText()
