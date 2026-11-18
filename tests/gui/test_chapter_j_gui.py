"""Design → Connection Checks: the Chapter J dialog and the undoable action."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyvistaqt")

from PySide6.QtWidgets import QDialog

from opensees_studio.core.design.chapter_j_model import ChapterJCheck
from opensees_studio.views.dialogs.chapter_j import ChapterJDialog
from opensees_studio.views.main_window import MainWindow


def _project():  # type: ignore[no-untyped-def]
    from tests.integration.test_steel_design_run import _portal

    return _portal()


@pytest.mark.gui
def test_the_dialog_adds_a_chapter_j_check(qtbot) -> None:  # type: ignore[no-untyped-def]
    dialog = ChapterJDialog(_project())
    qtbot.addWidget(dialog)
    dialog._type.setCurrentIndex(dialog._type.findData("fillet_weld"))
    dialog._name.setText("Weld")
    dialog._demand.setValue(40.0)
    dialog._add()
    checks = dialog.checks()
    assert len(checks) == 1
    assert checks[0].check_type == "fillet_weld"
    assert checks[0].name == "Weld"
    assert checks[0].demand == pytest.approx(40.0)
    assert checks[0].fexx and checks[0].fexx > 0.0


@pytest.mark.gui
def test_the_action_stores_and_undoes_the_chapter_j_checks(qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    project = _project()
    window = MainWindow()
    qtbot.addWidget(window)
    window._vm.adopt(project)
    check = ChapterJCheck(
        id=1,
        name="Weld",
        check_type="fillet_weld",
        demand=40.0,
        fexx=70.0,
        weld_leg=0.25,
        weld_length=10.0,
    )
    monkeypatch.setattr(ChapterJDialog, "exec", lambda self: int(QDialog.DialogCode.Accepted))
    monkeypatch.setattr(ChapterJDialog, "checks", lambda self: [check])
    window._on_chapter_j()
    assert project.chapter_j_checks == [check]
    window._vm.undo_stack.undo()
    assert project.chapter_j_checks == []


@pytest.mark.gui
def test_the_dialog_adds_a_concrete_bearing_check(qtbot) -> None:  # type: ignore[no-untyped-def]
    dialog = ChapterJDialog(_project())
    qtbot.addWidget(dialog)
    dialog._type.setCurrentIndex(dialog._type.findData("concrete_bearing"))
    dialog._demand.setValue(200.0)
    dialog._fc.setValue(4.0)
    dialog._a1.setValue(100.0)
    dialog._add()
    check = dialog.checks()[0]
    assert check.check_type == "concrete_bearing"
    assert check.fc == pytest.approx(4.0)
    assert check.a1 == pytest.approx(100.0)


@pytest.mark.gui
def test_the_dialog_adds_a_web_crippling_check(qtbot) -> None:  # type: ignore[no-untyped-def]
    dialog = ChapterJDialog(_project())
    qtbot.addWidget(dialog)
    dialog._type.setCurrentIndex(dialog._type.findData("web_local_crippling"))
    assert dialog._j10_group.isEnabled()
    dialog._demand.setValue(100.0)
    dialog._j10_fy.setValue(50.0)
    dialog._j10_tw.setValue(0.3)
    dialog._j10_tf.setValue(0.5)
    dialog._j10_d.setValue(14.0)
    dialog._j10_lb.setValue(2.0)
    dialog._j10_end.setValue(10.0)
    dialog._j10_e.setValue(29000.0)
    dialog._add()
    check = dialog.checks()[0]
    assert check.check_type == "web_local_crippling"
    assert check.fy == pytest.approx(50.0)
    assert check.web_thickness == pytest.approx(0.3)
    assert check.flange_thickness == pytest.approx(0.5)
    assert check.member_depth == pytest.approx(14.0)
    assert check.bearing_length == pytest.approx(2.0)
    assert check.distance_to_end == pytest.approx(10.0)
    assert check.elastic_modulus == pytest.approx(29000.0)


@pytest.mark.gui
def test_the_dialog_loads_a_saved_sidesway_check(qtbot) -> None:  # type: ignore[no-untyped-def]
    project = _project()
    project.chapter_j_checks = [
        ChapterJCheck(
            id=1,
            check_type="web_sidesway_buckling",
            demand=5000.0,
            fy=50.0,
            section_modulus=100.0,
            required_moment=1000.0,
            web_thickness=1.0,
            flange_thickness=0.5,
            clear_web_height=10.0,
            flange_width=8.0,
            bearing_length=100.0,
        )
    ]
    dialog = ChapterJDialog(project)
    qtbot.addWidget(dialog)
    dialog._table.selectRow(0)
    assert dialog._j10_group.isEnabled()
    assert dialog._j10_sx.value() == pytest.approx(100.0)
    assert dialog._j10_mr.value() == pytest.approx(1000.0)
    assert dialog._j10_tw.value() == pytest.approx(1.0)
    assert dialog._j10_restrained.isChecked()
