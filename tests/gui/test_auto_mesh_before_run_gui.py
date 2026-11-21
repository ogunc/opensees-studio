"""Run auto-meshes frames first: one undo step, groups and loads follow, opt-outs hold."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyvistaqt")

from opensees_studio.commands import (
    AddElementsCommand,
    AddNodesCommand,
    AddSectionsCommand,
    AssignElementFieldsCommand,
)
from opensees_studio.core import (
    ElasticBeamColumn,
    ElasticSection,
    LinearTimeSeries,
    Node,
    PlainLoadPattern,
    UniformElementLoad,
)
from opensees_studio.core.groups import Group


def _window(qtbot):  # type: ignore[no-untyped-def]
    """A 10 m beam with a column ending at its middle, a load and a group on the beam."""
    from opensees_studio.views.main_window import MainWindow

    mw = MainWindow()
    qtbot.addWidget(mw)
    vm = mw._vm
    vm.new_project(ndm=3, ndf=6)
    vm.apply_command(
        AddNodesCommand(
            vm,
            [
                Node(id=1, coords=(0.0, 0.0, 3.0), restraint=(True,) * 6),
                Node(id=2, coords=(10.0, 0.0, 3.0), restraint=(True,) * 6),
                Node(id=3, coords=(5.0, 0.0, 0.0), restraint=(True,) * 6),
                Node(id=4, coords=(5.0, 0.0, 3.0)),
            ],
        )
    )
    vm.apply_command(
        AddSectionsCommand(
            vm, [ElasticSection(id=1, E=200e9, A=0.01, Iz=1e-5, Iy=1e-5, G=80e9, J=1e-6)]
        )
    )
    vm.apply_command(
        AddElementsCommand(
            vm,
            [
                ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1),
                ElasticBeamColumn(id=2, nodes=(3, 4), section_id=1),
            ],
        )
    )
    vm.project.time_series.append(LinearTimeSeries(id=1))
    vm.project.load_patterns.append(
        PlainLoadPattern(
            id=1, time_series_id=1, element_loads=[UniformElementLoad(element_id=1, wy=-5.0)]
        )
    )
    vm.project.groups.append(Group(id=1, name="Beams", element_ids=[1]))
    return mw


@pytest.mark.gui
def test_run_splits_the_beam_the_column_ends_on_in_one_undo_step(qtbot) -> None:  # type: ignore[no-untyped-def]
    mw = _window(qtbot)
    project = mw._vm.project
    mw._auto_mesh_before_run()
    beams = [e for e in project.elements if 4 in e.nodes and e.id != 2]
    assert sorted(e.nodes for e in beams) == [(1, 4), (4, 2)]
    pieces = {e.id for e in beams}
    assert set(project.groups[0].element_ids) == pieces
    loaded = {load.element_id for load in project.load_patterns[0].element_loads}
    assert loaded == pieces
    assert mw._vm.undo_stack.undoText() == "Auto-mesh frames"
    mw._vm.undo_stack.undo()
    assert sorted(e.id for e in project.elements) == [1, 2]
    assert project.groups[0].element_ids == [1]


@pytest.mark.gui
def test_a_member_with_auto_mesh_off_is_left_alone(qtbot) -> None:  # type: ignore[no-untyped-def]
    mw = _window(qtbot)
    mw._vm.apply_command(AssignElementFieldsCommand(mw._vm, {1}, {"auto_mesh": False}))
    count = mw._vm.undo_stack.count()
    mw._auto_mesh_before_run()
    assert sorted(e.id for e in mw._vm.project.elements) == [1, 2]
    assert mw._vm.undo_stack.count() == count


@pytest.mark.gui
def test_the_analyze_switch_is_saved_with_the_project_and_undoable(qtbot) -> None:  # type: ignore[no-untyped-def]
    mw = _window(qtbot)
    action = mw._act_auto_mesh_frames
    assert action.isChecked()
    action.setChecked(False)
    assert mw._vm.project.auto_mesh_frames is False
    mw._auto_mesh_before_run()
    assert sorted(e.id for e in mw._vm.project.elements) == [1, 2]
    mw._vm.undo_stack.undo()
    assert mw._vm.project.auto_mesh_frames is True
