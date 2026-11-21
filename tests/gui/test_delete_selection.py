"""Edit → Delete selection removes everything selected, from the button and the key."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyvistaqt")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication


def _window(qtbot):  # type: ignore[no-untyped-def]
    from opensees_studio.views.main_window import MainWindow

    mw = MainWindow()
    qtbot.addWidget(mw)
    mw._vm.new_project()
    project = mw._vm.project
    from opensees_studio.core import ElasticBeamColumn, Node

    project.nodes.extend([Node(id=1, coords=(0, 0, 0)), Node(id=2, coords=(0, 0, 3))])
    project.elements.append(ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1))
    return mw


@pytest.mark.gui
def test_delete_action_removes_a_selected_frame(qtbot) -> None:  # type: ignore[no-untyped-def]
    mw = _window(qtbot)
    mw._canvas.selection.set_selection(set(), {1})
    assert mw._act_delete.isEnabled()
    mw._act_delete.trigger()
    assert mw._vm.project.elements == []
    assert mw._canvas.selection.is_empty
    mw._vm.undo_stack.undo()
    assert [e.id for e in mw._vm.project.elements] == [1]


@pytest.mark.gui
def test_delete_removes_frames_and_nodes_in_one_undo_step(qtbot) -> None:  # type: ignore[no-untyped-def]
    mw = _window(qtbot)
    mw._canvas.selection.set_selection({1, 2}, {1})
    before = mw._vm.undo_stack.count()
    mw._act_delete.trigger()
    assert mw._vm.project.elements == [] and mw._vm.project.nodes == []
    assert mw._vm.undo_stack.count() == before + 1
    mw._vm.undo_stack.undo()
    assert len(mw._vm.project.nodes) == 2 and len(mw._vm.project.elements) == 1


@pytest.mark.gui
@pytest.mark.parametrize("tab", ["home", "define", "analyze"])
def test_delete_key_works_on_every_ribbon_tab(qtbot, tab) -> None:  # type: ignore[no-untyped-def]
    # The Edit group lives on Home; with the menu bar hidden the Delete key
    # used to fire only while that tab was showing.
    mw = _window(qtbot)
    mw.show()
    qtbot.waitExposed(mw)
    mw.activateWindow()
    QApplication.setActiveWindow(mw)
    qtbot.waitUntil(lambda: QApplication.activeWindow() is mw)
    mw._ribbon.setCurrentTab(tab)
    mw._canvas.selection.set_selection(set(), {1})
    mw._canvas.setFocus()
    qtbot.keyClick(QApplication.focusWidget() or mw, Qt.Key.Key_Delete)
    assert mw._vm.project.elements == []
