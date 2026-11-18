"""Design → Gussets: the SCBF plate dialog and the undoable action."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyvistaqt")

from PySide6.QtWidgets import QDialog

from opensees_studio.core import ElasticBeamColumn
from opensees_studio.core.design.gusset_model import Gusset
from opensees_studio.views.dialogs.gussets import GussetsDialog
from opensees_studio.views.main_window import MainWindow


def _portal():  # type: ignore[no-untyped-def]
    from tests.integration.test_steel_design_run import _portal as portal

    project = portal()
    project.elements.append(ElasticBeamColumn(id=5, nodes=(1, 3), section_id=2))
    return project


@pytest.mark.gui
def test_the_dialog_adds_updates_and_removes_a_gusset(qtbot) -> None:  # type: ignore[no-untyped-def]
    project = _portal()
    dialog = GussetsDialog(project)
    qtbot.addWidget(dialog)
    dialog._brace.setCurrentIndex(dialog._brace.findData(5))
    dialog._t.setValue(0.5)
    dialog._b.setValue(12.0)
    dialog._lw.setValue(10.0)
    dialog._lc.setValue(10.0)
    dialog._add()
    gussets = dialog.gussets()
    assert len(gussets) == 1
    assert gussets[0].brace_element_id == 5
    assert gussets[0].t == pytest.approx(0.5)
    assert gussets[0].b == pytest.approx(12.0)

    dialog._table.selectRow(0)
    dialog._t.setValue(0.75)
    dialog._update()
    gussets = dialog.gussets()
    assert len(gussets) == 1
    assert gussets[0].id == 1
    assert gussets[0].t == pytest.approx(0.75)

    dialog._table.selectRow(0)
    dialog._remove()
    assert dialog.gussets() == []


@pytest.mark.gui
def test_the_action_stores_and_undoes_the_gussets(qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    project = _portal()
    window = MainWindow()
    qtbot.addWidget(window)
    window._vm.adopt(project)
    gusset = Gusset(id=1, brace_element_id=5, t=0.5, b=12.0, lw=10.0, free_length=10.0)
    monkeypatch.setattr(GussetsDialog, "exec", lambda self: int(QDialog.DialogCode.Accepted))
    monkeypatch.setattr(GussetsDialog, "gussets", lambda self: [gusset])
    window._on_gussets()
    assert project.gussets == [gusset]
    window._vm.undo_stack.undo()
    assert project.gussets == []


@pytest.mark.gui
def test_the_dialog_suggests_and_stores_the_weld_leg(qtbot) -> None:  # type: ignore[no-untyped-def]
    project = _portal()
    dialog = GussetsDialog(project)
    qtbot.addWidget(dialog)
    dialog._brace.setCurrentIndex(dialog._brace.findData(5))
    dialog._t.setValue(0.5)
    dialog._weld_check.setChecked(True)
    assert dialog._weld_leg.value() == pytest.approx(0.74 * 0.5)
    dialog._add()
    gusset = dialog.gussets()[0]
    assert gusset.weld_leg == pytest.approx(0.37)
    assert gusset.weld_both_sides
