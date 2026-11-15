"""The Restraints bar: Fixed / Pinned / Roller / Free on the selected joints in one click."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyvistaqt")

pytestmark = pytest.mark.gui


@pytest.fixture
def window(qtbot):  # type: ignore[no-untyped-def]
    from opensees_studio.commands import AddNodesCommand
    from opensees_studio.core import Node
    from opensees_studio.views.main_window import MainWindow

    mw = MainWindow()
    qtbot.addWidget(mw)
    mw._vm.new_project(ndm=3, ndf=6)
    mw._vm.apply_command(
        AddNodesCommand(
            mw._vm, [Node(id=1, coords=(0.0, 0.0, 0.0)), Node(id=2, coords=(5.0, 0.0, 0.0))]
        )
    )
    yield mw
    mw._help_controller.uninstall()


def _restraint(window, node_id: int) -> tuple[bool, ...]:
    return tuple(next(n for n in window._vm.project.nodes if n.id == node_id).restraint)


def test_each_button_applies_its_preset_as_one_undo_step(window) -> None:
    window._canvas.selection.set_selection(nodes={1, 2}, elements=set())
    window._refresh_action_enablement()
    window._act_restraint_fixed.trigger()
    assert _restraint(window, 1) == (True,) * 6
    assert _restraint(window, 2) == (True,) * 6
    window._act_restraint_pinned.trigger()
    assert _restraint(window, 1) == (True, True, True, False, False, False)
    window._act_restraint_roller.trigger()
    assert _restraint(window, 2) == (False, False, True, False, False, False)
    window._act_restraint_free.trigger()
    assert _restraint(window, 1) == (False,) * 6
    window._vm.undo_stack.undo()
    assert _restraint(window, 1) == (False, False, True, False, False, False)


def test_the_buttons_wait_for_a_joint_and_keep_their_tip_once_enabled(window) -> None:
    window._canvas.selection.clear()
    window._refresh_action_enablement()
    assert not window._act_restraint_fixed.isEnabled()
    assert window._act_restraint_fixed.toolTip() == "Select one or more joints first."
    window._canvas.selection.set_selection(nodes={1}, elements=set())
    window._refresh_action_enablement()
    assert window._act_restraint_fixed.isEnabled()
    assert window._act_restraint_fixed.toolTip().startswith("Restrain the selected joints")


def test_the_dialog_shows_only_the_plane_dofs_in_2d(qtbot) -> None:
    from opensees_studio.views.dialogs.assign_support import AssignSupportDialog

    dialog = AssignSupportDialog(1, ndm=2)
    qtbot.addWidget(dialog)
    dialog.show()
    shown = [box.text() for box in dialog._dof_boxes if box.isVisible()]
    assert shown == ["Ux", "Uz", "Ry"]
    three_d = AssignSupportDialog(1)
    qtbot.addWidget(three_d)
    three_d.show()
    assert all(box.isVisible() for box in three_d._dof_boxes)
