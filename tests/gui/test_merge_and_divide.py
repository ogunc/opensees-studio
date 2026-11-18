"""Edit → Merge Joints, Edit → Divide Frames at Joints, and the connectivity selections."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyvistaqt")

from PySide6.QtWidgets import QDialog

from opensees_studio.commands import AddElementsCommand, AddNodesCommand, AddSectionsCommand
from opensees_studio.core import (
    BeamWithHingesElement,
    ElasticBeamColumn,
    LinearTimeSeries,
    Node,
    PlainLoadPattern,
    PointElementLoad,
    make_default_section,
)
from opensees_studio.views.dialogs.connect_joints import DivideFramesDialog, MergeJointsDialog


def _window(qtbot):  # type: ignore[no-untyped-def]
    from opensees_studio.views.main_window import MainWindow

    mw = MainWindow()
    qtbot.addWidget(mw)
    vm = mw._vm
    vm.new_project(ndm=3, ndf=6)
    vm.apply_command(
        AddNodesCommand(
            vm,
            [
                Node(id=1, coords=(0.0, 0.0, 0.0), restraint=(True,) * 6),
                Node(id=2, coords=(4.0, 0.0, 0.0), restraint=(True,) * 6),
                Node(id=3, coords=(2.0, 0.0, 0.0)),  # inside beam 1
                Node(id=4, coords=(2.0, 0.0, 3.0)),
                Node(id=5, coords=(2.002, 0.0, 3.0)),  # 2 mm from node 4
                Node(id=6, coords=(5.0, 0.0, 3.0)),
                Node(id=7, coords=(9.0, 9.0, 9.0)),  # loose
            ],
        )
    )
    vm.apply_command(AddSectionsCommand(vm, [make_default_section(1)]))
    vm.apply_command(
        AddElementsCommand(
            vm,
            [
                ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1),
                ElasticBeamColumn(id=2, nodes=(3, 4), section_id=1),  # column on the beam
                ElasticBeamColumn(id=3, nodes=(5, 6), section_id=1),  # beam 2 mm short of it
            ],
        )
    )
    return mw


def _accept(monkeypatch, cls, setup=lambda dialog: None) -> None:  # type: ignore[no-untyped-def]
    def _fake_exec(self) -> int:  # type: ignore[no-untyped-def]
        setup(self)
        return int(QDialog.DialogCode.Accepted)

    monkeypatch.setattr(cls, "exec", _fake_exec)


@pytest.mark.gui
def test_merge_joints_joins_the_beam_to_the_column_in_one_undo_step(qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    mw = _window(qtbot)
    _accept(monkeypatch, MergeJointsDialog, lambda d: d._tolerance.setValue(0.01))
    mw._refresh_action_enablement()
    assert mw._act_merge_joints.isEnabled()

    mw._act_merge_joints.trigger()

    project = mw._vm.project
    assert 5 not in {n.id for n in project.nodes}
    assert project.element(3).nodes == (4, 6)
    mw._vm.undo_stack.undo()
    assert project.element(3).nodes == (5, 6)


@pytest.mark.gui
def test_merge_joints_on_a_selection_only_merges_the_selected(qtbot) -> None:  # type: ignore[no-untyped-def]
    mw = _window(qtbot)
    dialog = MergeJointsDialog(mw._vm.project, selected_nodes={4, 6})
    qtbot.addWidget(dialog)
    dialog._tolerance.setValue(0.01)
    assert dialog.scope_ids() == {4, 6}
    assert not dialog._ok.isEnabled()  # 4 and 6 are 3 m apart
    dialog._scope_all.setChecked(True)
    assert dialog._ok.isEnabled()
    assert "1 group(s)" in dialog._summary.text()


@pytest.mark.gui
def test_divide_frames_splits_the_beam_under_the_column_and_moves_its_load(
    qtbot, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    mw = _window(qtbot)
    project = mw._vm.project
    project.time_series.append(LinearTimeSeries(id=1))
    project.load_patterns.append(
        PlainLoadPattern(
            id=1, time_series_id=1, point_loads=[PointElementLoad(element_id=1, pz=-1.0, x=0.75)]
        )
    )
    _accept(monkeypatch, DivideFramesDialog)

    mw._act_divide_frames.trigger()

    beams = [e for e in project.elements if set(e.nodes) & {1, 2}]
    assert sorted(tuple(sorted(e.nodes)) for e in beams) == [(1, 3), (2, 3)]
    (load,) = project.load_patterns[0].point_loads
    piece = project.element(load.element_id)
    assert set(piece.nodes) == {2, 3} and load.x == pytest.approx(0.5)
    mw._vm.undo_stack.undo()
    assert project.element(1).nodes == (1, 2)


@pytest.mark.gui
def test_the_divide_dialog_reports_loose_joints(qtbot) -> None:  # type: ignore[no-untyped-def]
    mw = _window(qtbot)
    dialog = DivideFramesDialog(mw._vm.project, selected_elements=set())
    qtbot.addWidget(dialog)
    assert dialog._ok.isEnabled()
    assert "1 loose joint(s)" in dialog._summary.text()


@pytest.mark.gui
def test_the_connectivity_selections(qtbot) -> None:  # type: ignore[no-untyped-def]
    mw = _window(qtbot)
    sel = mw._canvas.selection
    mw._act_select_loose_joints.trigger()
    assert sel.nodes == {7}
    sel.clear()
    mw._act_select_joints_in_bars.trigger()
    assert (sel.nodes, sel.elements) == ({3}, {1})


@pytest.mark.gui
def test_assign_hinge_keeps_the_weight_per_length(qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.core.self_weight import weight_per_length
    from opensees_studio.views.dialogs import AssignHingeDialog

    mw = _window(qtbot)
    project = mw._vm.project
    before = weight_per_length(project, project.element(1))
    assert before > 0.0

    def _values(self) -> dict:  # type: ignore[no-untyped-def]
        return {
            "section_i_id": 1,
            "section_j_id": 1,
            "lp_i": 0.2,
            "lp_j": 0.2,
            "E": 200e9,
            "A": 0.02,
            "Iz": 1e-5,
            "Iy": 1e-5,
            "G": 80e9,
            "J": 1e-6,
        }

    monkeypatch.setattr(AssignHingeDialog, "values", _values)
    _accept(monkeypatch, AssignHingeDialog)
    mw._canvas.selection.set_selection(set(), {1})
    mw._act_assign_hinge.trigger()

    member = project.element(1)
    assert isinstance(member, BeamWithHingesElement)
    assert weight_per_length(project, member) == pytest.approx(before)
