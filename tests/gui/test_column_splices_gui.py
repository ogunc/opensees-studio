"""Design → Column Splices: the SCBF splice dialog and the undoable action."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyvistaqt")

from PySide6.QtWidgets import QDialog

from opensees_studio.core import ElasticBeamColumn, Node
from opensees_studio.core.design.column_splice_model import ColumnSplice
from opensees_studio.views.dialogs.column_splices import ColumnSplicesDialog
from opensees_studio.views.main_window import MainWindow


def _stacked():  # type: ignore[no-untyped-def]
    from tests.integration.test_steel_design_run import _portal

    project = _portal()
    project.nodes.append(Node(id=5, coords=(0.0, 0.0, 288.0)))
    project.elements.append(ElasticBeamColumn(id=6, nodes=(2, 5), section_id=1))
    return project


@pytest.mark.gui
def test_the_dialog_adds_a_column_splice(qtbot) -> None:  # type: ignore[no-untyped-def]
    project = _stacked()
    dialog = ColumnSplicesDialog(project)
    qtbot.addWidget(dialog)
    dialog._node.setCurrentIndex(dialog._node.findData(2))
    dialog._on_node_changed()
    dialog._top.setCurrentIndex(dialog._top.findData(6))
    dialog._bottom.setCurrentIndex(dialog._bottom.findData(1))
    dialog._height.setValue(144.0)
    dialog._add()
    splices = dialog.splices()
    assert len(splices) == 1
    assert splices[0].node_id == 2
    assert splices[0].top_element_id == 6
    assert splices[0].bottom_element_id == 1
    assert splices[0].clear_height == pytest.approx(144.0)


@pytest.mark.gui
def test_the_action_stores_and_undoes_the_column_splices(qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    project = _stacked()
    window = MainWindow()
    qtbot.addWidget(window)
    window._vm.adopt(project)
    splice = ColumnSplice(
        id=1,
        node_id=2,
        top_element_id=6,
        bottom_element_id=1,
        clear_height=144.0,
    )
    monkeypatch.setattr(ColumnSplicesDialog, "exec", lambda self: int(QDialog.DialogCode.Accepted))
    monkeypatch.setattr(ColumnSplicesDialog, "splices", lambda self: [splice])
    window._on_column_splices()
    assert project.column_splices == [splice]
    window._vm.undo_stack.undo()
    assert project.column_splices == []
