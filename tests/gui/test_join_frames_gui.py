"""Edit → Join Frames from the window: one undo step, or a message when nothing joins."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyvistaqt")

pytestmark = pytest.mark.gui


@pytest.fixture
def window(qtbot):  # type: ignore[no-untyped-def]
    from opensees_studio.commands import AddElementsCommand, AddNodesCommand, AddSectionsCommand
    from opensees_studio.core import ElasticBeamColumn, Node, make_default_section
    from opensees_studio.views.main_window import MainWindow

    mw = MainWindow()
    qtbot.addWidget(mw)
    mw._vm.new_project()
    vm = mw._vm
    vm.apply_command(
        AddNodesCommand(vm, [Node(id=i, coords=(2.0 * i, 0.0, 0.0)) for i in (1, 2, 3)])
    )
    vm.apply_command(AddSectionsCommand(vm, [make_default_section(1)]))
    vm.apply_command(
        AddElementsCommand(
            vm,
            [
                ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1),
                ElasticBeamColumn(id=2, nodes=(2, 3), section_id=1),
            ],
        )
    )
    yield mw
    mw._help_controller.uninstall()


def test_join_waits_for_two_members(window) -> None:
    window._canvas.selection.set_selection(set(), {1})
    window._refresh_action_enablement()
    assert not window._act_join_frames.isEnabled()
    assert window._act_join_frames.toolTip() == "Select two or more frame members first."


def test_joining_two_pieces_is_one_undo_step(window) -> None:
    project = window._vm.project
    window._canvas.selection.set_selection(set(), {1, 2})
    window._refresh_action_enablement()
    window._act_join_frames.trigger()
    assert [(e.id, e.nodes) for e in project.elements] == [(1, (1, 3))]
    assert window._canvas.selection.elements == frozenset({1})
    window._vm.undo_stack.undo()
    assert len(project.elements) == 2 and len(project.nodes) == 3


def test_nothing_to_join_is_a_message_not_an_undo_step(window, monkeypatch) -> None:
    from PySide6.QtWidgets import QMessageBox

    shown: list[str] = []
    monkeypatch.setattr(QMessageBox, "information", lambda _p, _t, text: shown.append(text))
    node = window._vm.project.nodes[1]
    window._vm.project.nodes[1] = node.model_copy(update={"restraint": (True,) * 6})
    depth = window._vm.undo_stack.count()
    window._canvas.selection.set_selection(set(), {1, 2})
    window._refresh_action_enablement()
    window._act_join_frames.trigger()
    assert shown and "restrained" in shown[0]
    assert window._vm.undo_stack.count() == depth
