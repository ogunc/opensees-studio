"""Move/Replicate + Measure: two joints fill dX, dY and dZ of the open dialog.

Both windows are modeless, so the viewport stays usable while they are open;
the Measure button (or F7 once the viewport has focus) arms Measure Distance
with the dialog as its destination.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyvistaqt")

from opensees_studio.commands import AddNodesCommand
from opensees_studio.core import Node
from opensees_studio.views.dialogs.move import MoveDialog
from opensees_studio.views.dialogs.replicate import ReplicateDialog
from opensees_studio.views.main_window import MainWindow


def _window(qtbot) -> MainWindow:  # type: ignore[no-untyped-def]
    window = MainWindow()
    qtbot.addWidget(window)
    window.resize(1000, 700)
    window.show()
    qtbot.waitExposed(window)
    window._vm.new_project(ndm=3, ndf=6)
    assert window._vm.project is not None
    window._vm.apply_command(
        AddNodesCommand(
            window._vm,
            [
                Node(id=1, coords=(0.0, 0.0, 0.0)),
                Node(id=2, coords=(3.0, 4.0, 0.0)),
                Node(id=3, coords=(3.0, 4.0, 12.0)),
            ],
        )
    )
    return window


def _select(window: MainWindow, *node_ids: int) -> None:
    window._canvas.selection.clear()
    for node_id in node_ids:
        window._canvas.selection.select_node(node_id, additive=True)


def _node(window: MainWindow, node_id: int) -> Node:
    assert window._vm.project is not None
    return next(node for node in window._vm.project.nodes if node.id == node_id)


@pytest.mark.gui
def test_move_dialog_measure_fills_the_offset(qtbot) -> None:  # type: ignore[no-untyped-def]
    window = _window(qtbot)
    _select(window, 1)
    window._act_move.trigger()

    dlg = window._offset_dialog
    assert isinstance(dlg, MoveDialog)
    assert dlg.isVisible()
    assert not dlg.isModal(), "the viewport must stay usable while the dialog is open"

    dlg._measure_button.click()
    assert window._tool_controller.active is window._measure_tool
    assert window._act_tool_measure.isChecked()

    # Measure 2 -> 3; the selection moves to the measured joints, but the
    # dialog must keep acting on the joints selected when it opened (1).
    window._measure_tool.on_node_picked(2)
    window._measure_tool.on_node_picked(3)

    assert dlg.offset() == pytest.approx((0.0, 0.0, 12.0))
    assert "Measured 12" in dlg._message.text()
    assert "dX=0, dY=0, dZ=12" in dlg._message.text()

    dlg.accept()

    assert window._offset_dialog is None
    assert window._tool_controller.active is None
    assert tuple(_node(window, 1).coords) == pytest.approx((0.0, 0.0, 12.0))
    assert tuple(_node(window, 2).coords) == pytest.approx((3.0, 4.0, 0.0))


@pytest.mark.gui
def test_replicate_dialog_measure_fills_the_offset(qtbot) -> None:  # type: ignore[no-untyped-def]
    window = _window(qtbot)
    _select(window, 2)
    window._act_replicate.trigger()

    dlg = window._offset_dialog
    assert isinstance(dlg, ReplicateDialog)
    dlg._measure_button.click()

    window._measure_tool.on_node_picked(1)
    window._measure_tool.on_node_picked(2)

    assert dlg.offset() == pytest.approx((3.0, 4.0, 0.0))
    dlg._n.setValue(1)
    assert window._vm.project is not None
    before = {node.id for node in window._vm.project.nodes}
    dlg.accept()

    copy = next(node for node in window._vm.project.nodes if node.id not in before)
    assert tuple(copy.coords) == pytest.approx((6.0, 8.0, 0.0))


@pytest.mark.gui
def test_f7_with_the_dialog_open_sends_the_measurement_to_it(qtbot) -> None:  # type: ignore[no-untyped-def]
    window = _window(qtbot)
    _select(window, 1)
    window._act_move.trigger()
    dlg = window._offset_dialog
    assert isinstance(dlg, MoveDialog)

    # F7 once the viewport has the focus: the same slot as the Measure button.
    window._on_measure_tool()
    window._measure_tool.on_node_picked(1)
    window._measure_tool.on_node_picked(2)

    assert dlg.offset() == pytest.approx((3.0, 4.0, 0.0))


@pytest.mark.gui
def test_closing_the_dialog_stops_measuring(qtbot) -> None:  # type: ignore[no-untyped-def]
    window = _window(qtbot)
    _select(window, 1)
    window._act_move.trigger()
    dlg = window._offset_dialog
    assert isinstance(dlg, MoveDialog)
    dlg._measure_button.click()
    assert window._tool_controller.active is window._measure_tool

    dlg.reject()

    assert window._offset_dialog is None
    assert window._tool_controller.active is None
