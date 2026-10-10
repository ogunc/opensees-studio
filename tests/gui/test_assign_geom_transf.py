"""Assign > Frame > Geometric Transformation and the property editor field."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, call

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyvistaqt")

from PySide6.QtWidgets import QDialog, QMessageBox

from opensees_studio.commands import AddElementsCommand, AssignElementFieldsCommand
from opensees_studio.core import TrussElement
from opensees_studio.services import load_project
from opensees_studio.services.opensees_runner import OpenSeesRunner
from opensees_studio.views.dialogs import AssignGeomTransfDialog

EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "rc_frame_gravity.osmodel"
COLUMNS = {1, 2}  # the source (RCFrameGravity) gives the columns PDelta, the beam Linear
BEAM = 3


def _emitted(project) -> MagicMock:  # type: ignore[no-untyped-def]
    ops = MagicMock()
    OpenSeesRunner(project, ops_module=ops).build()
    return ops


def _window(qtbot):  # type: ignore[no-untyped-def]
    from opensees_studio.views.main_window import MainWindow

    mw = MainWindow()
    qtbot.addWidget(mw)
    assert mw.open_project(EXAMPLE)
    return mw


def _choose(monkeypatch, transf: str) -> None:  # type: ignore[no-untyped-def]
    def _fake_exec(self: AssignGeomTransfDialog) -> int:
        self._combo.setCurrentText(transf)
        return int(QDialog.DialogCode.Accepted)

    monkeypatch.setattr(AssignGeomTransfDialog, "exec", _fake_exec)


@pytest.mark.gui
def test_pdelta_on_the_columns_is_emitted_for_those_elements_only(qtbot) -> None:  # type: ignore[no-untyped-def]
    mw = _window(qtbot)
    vm = mw._vm
    assert {el.geom_transf for el in vm.project.elements} == {"Linear"}
    vm.apply_command(AssignElementFieldsCommand(vm, COLUMNS, {"geom_transf": "PDelta"}))

    ops = _emitted(vm.project)
    assert ops.geomTransf.call_args_list == [call("PDelta", 1), call("Linear", 2)]
    transf_tag = {c.args[1]: c.args[4] for c in ops.element.call_args_list}
    assert transf_tag == {1: 1, 2: 1, BEAM: 2}

    vm.undo_stack.undo()
    assert {el.geom_transf for el in vm.project.elements} == {"Linear"}
    assert _emitted(vm.project).geomTransf.call_args_list == [call("Linear", 1)]


@pytest.mark.gui
def test_gui_assignment_emits_the_same_commands_as_the_source_assignment(
    qtbot, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    # Reference: the example with the source's transformations written into the model.
    reference = load_project(EXAMPLE)
    reference.elements = [
        el.model_copy(update={"geom_transf": "PDelta"}) if el.id in COLUMNS else el
        for el in reference.elements
    ]

    mw = _window(qtbot)
    for eid in COLUMNS:
        mw._canvas.selection.select_element(eid, additive=True)
    mw._refresh_action_enablement()
    assert mw._act_assign_geom_transf.isEnabled()
    _choose(monkeypatch, "PDelta")
    mw._act_assign_geom_transf.trigger()

    assert _emitted(mw._vm.project).mock_calls == _emitted(reference).mock_calls
    assert mw._vm.project.model_dump() == reference.model_dump()

    mw._vm.undo_stack.undo()
    assert [el.geom_transf for el in mw._vm.project.elements] == ["Linear"] * 3


@pytest.mark.gui
def test_mixed_selection_assigns_to_frames_only_and_empty_selection_is_refused(
    qtbot, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    mw = _window(qtbot)
    vm = mw._vm
    vm.apply_command(
        AddElementsCommand(vm, [TrussElement(id=9, nodes=(1, 4), area=1.0, material_id=1)])
    )
    shown: list[str] = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: shown.append(a[2]))
    mw._canvas.selection.select_element(9)
    mw._act_assign_geom_transf.trigger()
    assert shown == ["Select one or more frame elements first."]

    _choose(monkeypatch, "Corotational")
    mw._canvas.selection.select_element(BEAM, additive=True)
    mw._act_assign_geom_transf.trigger()
    assert vm.project.element(BEAM).geom_transf == "Corotational"
    assert not hasattr(vm.project.element(9), "geom_transf")
    assert [vm.project.element(i).geom_transf for i in COLUMNS] == ["Linear", "Linear"]


@pytest.mark.gui
def test_property_editor_edits_the_transformation(qtbot) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QComboBox

    mw = _window(qtbot)
    mw._canvas.selection.select_element(1)
    combos = [
        c
        for c in mw._props.findChildren(QComboBox)
        if [c.itemText(i) for i in range(c.count())] == ["Linear", "PDelta", "Corotational"]
    ]
    assert len(combos) == 1 and combos[0].currentText() == "Linear"
    combos[0].setCurrentText("PDelta")
    assert mw._vm.project.element(1).geom_transf == "PDelta"
    assert mw._vm.project.element(2).geom_transf == "Linear"
    mw._vm.undo_stack.undo()
    assert mw._vm.project.element(1).geom_transf == "Linear"


@pytest.mark.gui
def test_invalid_value_is_refused_before_the_push(qtbot) -> None:  # type: ignore[no-untyped-def]
    from pydantic import ValidationError

    from opensees_studio.viewmodels import ProjectViewModel

    vm = ProjectViewModel()
    vm.open(EXAMPLE)
    with pytest.raises(ValidationError):
        AssignElementFieldsCommand(vm, COLUMNS, {"geom_transf": "Bogus"})
    assert vm.undo_stack.count() == 0
    assert {el.geom_transf for el in vm.project.elements} == {"Linear"}
