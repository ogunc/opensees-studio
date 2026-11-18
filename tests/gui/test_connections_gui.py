"""Design → Connections: the RBS dialog and the undoable action."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyvistaqt")

from PySide6.QtWidgets import QDialog, QMessageBox

from opensees_studio.core.design.connections import RbsConnection
from opensees_studio.views.dialogs.connections import ConnectionsDialog
from opensees_studio.views.main_window import MainWindow


def _portal():  # type: ignore[no-untyped-def]
    from tests.integration.test_steel_design_run import _portal as portal

    return portal()


@pytest.mark.gui
def test_the_dialog_adds_an_rbs_connection(qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    project = _portal()
    dialog = ConnectionsDialog(project)
    qtbot.addWidget(dialog)
    dialog._beam.setCurrentIndex(dialog._beam.findData(2))
    dialog._column.setCurrentIndex(dialog._column.findData(1))
    dialog._a.setValue(4.5)
    dialog._b.setValue(13.0)
    dialog._c.setValue(1.0)
    dialog._add()
    connections = dialog.connections()
    assert len(connections) == 1
    assert connections[0].beam_element_id == 2
    assert connections[0].column_element_id == 1
    assert connections[0].a == pytest.approx(4.5)

    warnings: list[str] = []
    monkeypatch.setattr(
        QMessageBox, "warning", lambda *args, **kwargs: warnings.append(str(args[2]))
    )
    dialog._c.setValue(3.0)
    dialog._add()
    assert warnings and "RBS c" in warnings[0]
    assert len(dialog.connections()) == 1


@pytest.mark.gui
def test_the_action_stores_and_undoes_the_connections(qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    project = _portal()
    window = MainWindow()
    qtbot.addWidget(window)
    window._vm.adopt(project)
    connection = RbsConnection(id=1, beam_element_id=2, column_element_id=1, a=4.5, b=13.0, c=1.0)
    monkeypatch.setattr(ConnectionsDialog, "exec", lambda self: int(QDialog.DialogCode.Accepted))
    monkeypatch.setattr(ConnectionsDialog, "connections", lambda self: [connection])
    window._on_connections()
    assert project.connections == [connection]
    window._vm.undo_stack.undo()
    assert project.connections == []


@pytest.mark.gui
def test_the_dialog_stores_the_web_connection(qtbot) -> None:  # type: ignore[no-untyped-def]
    project = _portal()
    dialog = ConnectionsDialog(project)
    qtbot.addWidget(dialog)
    dialog._beam.setCurrentIndex(dialog._beam.findData(2))
    dialog._column.setCurrentIndex(dialog._column.findData(1))
    dialog._a.setValue(4.5)
    dialog._b.setValue(13.0)
    dialog._c.setValue(1.0)
    dialog._web_check.setChecked(True)
    dialog._web_type.setCurrentIndex(dialog._web_type.findData("bolted"))
    dialog._web_t.setValue(0.5)
    dialog._web_h.setValue(12.0)
    dialog._web_n.setValue(4.0)
    dialog._web_db.setValue(0.75)
    dialog._web_leg.setValue(0.375)
    dialog._add()
    connection = dialog.connections()[0]
    assert connection.web_connection_type == "bolted"
    assert connection.web_plate_thickness == pytest.approx(0.5)
    assert connection.web_plate_height == pytest.approx(12.0)
    assert connection.web_bolt_count == 4
    assert connection.web_weld_leg == pytest.approx(0.375)
