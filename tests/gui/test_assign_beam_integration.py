"""Assign > Frame > Beam Integration and the property editor rows."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, call

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyvistaqt")

from PySide6.QtWidgets import QDialog, QMessageBox

from opensees_studio.services.opensees_runner import OpenSeesRunner
from opensees_studio.views.dialogs import AssignBeamIntegrationDialog

EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "rc_frame_gravity.osmodel"
COLUMNS = (1, 2)  # forceBeamColumn; element 3 is an elasticBeamColumn


def _window(qtbot):  # type: ignore[no-untyped-def]
    from opensees_studio.views.main_window import MainWindow

    mw = MainWindow()
    qtbot.addWidget(mw)
    assert mw.open_project(EXAMPLE)
    return mw


@pytest.mark.gui
def test_menu_assigns_lobatto_4_and_undo_restores(qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    mw = _window(qtbot)
    project = mw._vm.project
    before = [project.element(i) for i in COLUMNS]
    assert {(el.integration, el.integration_points) for el in before} == {("Lobatto", 5)}

    def _fake_exec(self: AssignBeamIntegrationDialog) -> int:
        assert (self.rule(), self.points()) == ("Lobatto", 5)  # the current values
        self._points.setValue(4)
        return int(QDialog.DialogCode.Accepted)

    monkeypatch.setattr(AssignBeamIntegrationDialog, "exec", _fake_exec)
    for eid in (1, 2, 3):
        mw._canvas.selection.select_element(eid, additive=True)
    mw._refresh_action_enablement()
    assert mw._act_assign_integration.isEnabled()
    mw._act_assign_integration.trigger()

    assert [project.element(i).integration_points for i in COLUMNS] == [4, 4]
    assert not hasattr(project.element(3), "integration")
    ops = MagicMock()
    OpenSeesRunner(project, ops_module=ops).build()
    assert ops.beamIntegration.call_args_list == [
        call("Lobatto", 1, 1, 4),
        call("Lobatto", 2, 1, 4),
    ]

    mw._vm.undo_stack.undo()
    assert [project.element(i) for i in COLUMNS] == before


@pytest.mark.gui
def test_selection_without_beam_columns_is_refused(qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    mw = _window(qtbot)
    shown: list[str] = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: shown.append(a[2]))
    mw._canvas.selection.select_element(3)
    mw._act_assign_integration.trigger()
    assert shown == ["Select one or more force or displacement beam-column elements first."]


@pytest.mark.gui
def test_property_editor_edits_rule_and_points(qtbot) -> None:  # type: ignore[no-untyped-def]
    mw = _window(qtbot)
    project = mw._vm.project
    mw._canvas.selection.select_element(1)
    mw._props._integration_rule.setCurrentText("Legendre")
    assert (project.element(1).integration, project.element(1).integration_points) == (
        "Legendre",
        5,
    )
    mw._props._integration_points.setValue(3)
    mw._props._integration_points.editingFinished.emit()
    assert project.element(1).integration_points == 3
    assert project.element(2).integration == "Lobatto"
    mw._vm.undo_stack.undo()
    mw._vm.undo_stack.undo()
    assert (project.element(1).integration, project.element(1).integration_points) == (
        "Lobatto",
        5,
    )
