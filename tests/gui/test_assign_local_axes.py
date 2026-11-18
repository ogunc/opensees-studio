"""Assign > Frame > Local Axes: the dialog and the undoable action."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyvistaqt")

from PySide6.QtWidgets import QDialog

from opensees_studio.core.geometry.elements import FRAME_ELEMENT_CLASSES
from opensees_studio.views.dialogs import AssignLocalAxesDialog

EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "building_3storey_diaphragm.osmodel"


@pytest.mark.gui
def test_the_dialog_returns_the_angle_and_disables_it_in_2d(qtbot) -> None:  # type: ignore[no-untyped-def]
    dialog = AssignLocalAxesDialog(2, 3, 15.0)
    qtbot.addWidget(dialog)
    assert dialog.angle() == pytest.approx(15.0)

    flat = AssignLocalAxesDialog(2, 2, 15.0)
    qtbot.addWidget(flat)
    assert flat.angle() == pytest.approx(0.0)


@pytest.mark.gui
def test_the_action_stores_the_angle_and_undoes_it(qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.views.main_window import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)
    assert window.open_project(EXAMPLE)
    project = window._vm.project
    element = next(e for e in project.elements if isinstance(e, FRAME_ELEMENT_CLASSES))
    window._canvas.selection.select_element(element.id)
    window._refresh_action_enablement()
    assert window._act_assign_local_axes.isEnabled()

    def _fake_exec(self: AssignLocalAxesDialog) -> int:
        self._angle.setValue(30.0)
        return int(QDialog.DialogCode.Accepted)

    monkeypatch.setattr(AssignLocalAxesDialog, "exec", _fake_exec)
    window._act_assign_local_axes.trigger()
    assert project.element(element.id).local_axis_angle == pytest.approx(30.0)

    window._vm.undo_stack.undo()
    assert project.element(element.id).local_axis_angle == pytest.approx(0.0)


@pytest.mark.gui
def test_the_property_editor_edits_the_local_axis_angle(qtbot) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.views.float_field import FloatField
    from opensees_studio.views.main_window import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)
    assert window.open_project(EXAMPLE)
    project = window._vm.project
    element = next(e for e in project.elements if isinstance(e, FRAME_ELEMENT_CLASSES))
    window._canvas.selection.select_element(element.id)
    fields = [f for f in window._props.findChildren(FloatField) if f.suffix() == " °"]
    assert len(fields) == 1
    fields[0].setValue(12.5)
    fields[0].editingFinished.emit()
    assert project.element(element.id).local_axis_angle == pytest.approx(12.5)
    window._vm.undo_stack.undo()
    assert project.element(element.id).local_axis_angle == pytest.approx(0.0)
