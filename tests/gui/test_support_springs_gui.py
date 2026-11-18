"""Line, edge and area springs in the interface: the dialog, the menu entries, undo, the canvas.

The distribution and the solve are pinned in the unit and integration tests;
here, what the three Assign entries build from a selection, that replace, add and
delete do what they say, that one undo takes it back, and that the springs are
drawn toward the medium.
"""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyvistaqt")

from PySide6.QtWidgets import QDialog

from opensees_studio.views.dialogs.support_springs import SupportSpringDialog
from tests.unit.test_support_springs import _beam, _raft


def _window(qtbot, project):  # type: ignore[no-untyped-def]
    from opensees_studio.views.main_window import MainWindow

    mw = MainWindow()
    qtbot.addWidget(mw)
    project.area_springs.clear()
    project.line_springs.clear()
    mw._vm.adopt(project)
    return mw


def _accept(monkeypatch, values: dict, mode: str = "replace") -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(SupportSpringDialog, "exec", lambda self: int(QDialog.DialogCode.Accepted))
    monkeypatch.setattr(SupportSpringDialog, "values", lambda self: dict(values))
    monkeypatch.setattr(SupportSpringDialog, "mode", lambda self: mode)


SOIL = {"stiffness": 2e7, "direction": "Z", "side": "negative", "behaviour": "compression"}


@pytest.mark.gui
def test_the_dialog_returns_what_it_shows_and_delete_disables_the_fields(qtbot) -> None:  # type: ignore[no-untyped-def]
    dialog = SupportSpringDialog("line", 3)
    qtbot.addWidget(dialog)
    dialog.stiffness.setValue(500.0)
    dialog.direction.setCurrentIndex(dialog.direction.findData("2"))
    dialog.behaviour.setCurrentIndex(dialog.behaviour.findData("tension"))
    assert dialog.values() == {
        "stiffness": 500.0,
        "direction": "2",
        "side": "negative",
        "behaviour": "tension",
    }
    dialog.action.setCurrentIndex(dialog.action.findData("delete"))
    assert not dialog.stiffness.isEnabled()
    assert dialog.mode() == "delete"


@pytest.mark.gui
def test_area_springs_replace_add_delete_and_undo(qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    mw = _window(qtbot, _raft())
    project = mw._vm.project
    shells = [e.id for e in project.elements]
    mw._canvas.selection.clear()
    for sid in shells[:2]:
        mw._canvas.selection.select_element(sid, additive=True)

    _accept(monkeypatch, SOIL)
    mw._act_assign_area_springs.trigger()
    assert [s.element_id for s in project.area_springs] == shells[:2]
    assert project.area_springs[0].behaviour == "compression"

    _accept(monkeypatch, {**SOIL, "behaviour": "both"}, "add")
    mw._act_assign_area_springs.trigger()
    assert len(project.area_springs) == 4

    _accept(monkeypatch, SOIL, "replace")
    mw._act_assign_area_springs.trigger()
    assert len(project.area_springs) == 2

    _accept(monkeypatch, SOIL, "delete")
    mw._act_assign_area_springs.trigger()
    assert project.area_springs == []

    mw._vm.undo_stack.undo()
    assert len(project.area_springs) == 2
    assert "Area springs: delete on 2" in mw._console.toPlainText()


@pytest.mark.gui
def test_edge_springs_take_the_edges_whose_two_joints_are_selected(qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    mw = _window(qtbot, _raft(n=1))
    project = mw._vm.project
    shell = project.elements[0]
    mw._canvas.selection.clear()
    mw._canvas.selection.select_element(shell.id, additive=True)
    for nid in shell.nodes[1:3]:  # the joints of edge 2
        mw._canvas.selection.select_node(nid, additive=True)

    _accept(
        monkeypatch, {"stiffness": 10.0, "direction": "Z", "side": "negative", "behaviour": "both"}
    )
    mw._act_assign_edge_springs.trigger()
    assert [(s.element_id, s.edge) for s in project.edge_springs] == [(shell.id, 2)]


@pytest.mark.gui
def test_line_springs_go_on_the_selected_frames_and_are_drawn_toward_the_medium(
    qtbot, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    mw = _window(qtbot, _beam())
    project = mw._vm.project
    mw._canvas.selection.clear()
    mw._canvas.selection.select_element(1, additive=True)
    _accept(
        monkeypatch, {"stiffness": 200.0, "direction": "Z", "side": "negative", "behaviour": "both"}
    )
    mw._act_assign_line_springs.trigger()
    assert [s.element_id for s in project.line_springs] == [1]

    glyphs = mw._canvas._renderer._distributed_spring_glyphs(project, 1.0)
    assert glyphs is not None
    # The zigzags hang below the beam (the soil is under it): every point at or below z = 0.
    assert float(np.max(glyphs.points[:, 2])) <= 1e-9
    assert float(np.min(glyphs.points[:, 2])) < 0.0
