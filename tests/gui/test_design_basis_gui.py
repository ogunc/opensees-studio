"""Design → Design Basis and Design → Direct Analysis Method, through the dialogs and the menu.

The numbers are pinned in ``tests/unit/test_direct_analysis.py`` and
``tests/integration/test_direct_analysis_run.py``; here the wiring: the basis
dialog offers the grades and the Manual defaults, the direct analysis dialog
guesses the load roles, previews the cases and reads Δ2/Δ1 from results, and
the menu stores everything in one undoable step.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyvistaqt")
pytest.importorskip("openseespy")

from PySide6.QtWidgets import QDialogButtonBox

from opensees_studio.core.design.direct_analysis import is_direct_analysis_case
from opensees_studio.core.design.settings import DesignSettings
from opensees_studio.services.opensees_runner import OpenSeesRunner
from opensees_studio.views.dialogs.design_basis import DesignBasisDialog, DirectAnalysisDialog


def _portal():  # type: ignore[no-untyped-def]
    from tests.unit.test_direct_analysis import _portal

    return _portal()


@pytest.mark.gui
def test_the_basis_dialog_sets_grades_systems_and_method(qtbot) -> None:  # type: ignore[no-untyped-def]
    project = _portal()
    dialog = DesignBasisDialog(project)
    qtbot.addWidget(dialog)
    combo = dialog._grade_boxes["W"]
    assert combo.findText("ASTM A36") >= 0 and combo.findText("ASTM A572 Gr. 50") >= 0
    assert dialog.settings().steel_grades == {}
    dialog.apply_manual_defaults()
    dialog._grade_boxes["L"].setCurrentIndex(dialog._grade_boxes["L"].findData("A572-50"))
    dialog._stability.setCurrentIndex(dialog._stability.findData("direct"))
    dialog._system_x.setCurrentIndex(dialog._system_x.findData("SCBF"))
    assert "Ω0 = 2" in dialog._coefficients.text()
    settings = dialog.settings()
    assert settings.steel_grades["W"] == "A992"
    assert settings.steel_grades["L"] == "A572-50"
    assert settings.stability_method == "direct"
    assert settings.seismic_system == "SCBF"
    assert settings.seismic_system_y is None


@pytest.mark.gui
def test_the_direct_analysis_dialog_guesses_roles_and_previews(qtbot) -> None:  # type: ignore[no-untyped-def]
    project = _portal()
    dialog = DirectAnalysisDialog(project, {})
    qtbot.addWidget(dialog)
    assert dialog.roles() == {"D": [1], "L": [2], "W": [3]}
    assert "12 case(s)" in dialog._preview.toPlainText()
    assert len(dialog.cases()) == 12
    assert "No results yet" in dialog._ratio_status.text()
    assert dialog.settings().stability_method == "direct"


@pytest.mark.gui
def test_asd_disables_ok_with_the_reason(qtbot) -> None:  # type: ignore[no-untyped-def]
    project = _portal()
    project.design = DesignSettings(method="ASD")
    dialog = DirectAnalysisDialog(project, {})
    qtbot.addWidget(dialog)
    assert not dialog._buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled()
    assert "1.6" in dialog._preview.toPlainText()


@pytest.mark.gui
def test_the_ratio_tab_reads_the_results(qtbot) -> None:  # type: ignore[no-untyped-def]
    project = _portal()
    first = DirectAnalysisDialog(project, {})
    qtbot.addWidget(first)
    project.analyses += first.cases()
    results = {
        c.id: OpenSeesRunner(project).run(c)
        for c in project.analyses
        if is_direct_analysis_case(c) and c.direct_analysis.lateral
    }
    dialog = DirectAnalysisDialog(project, results)
    qtbot.addWidget(dialog)
    assert dialog._ratio_table.rowCount() == 4
    assert "Largest Δ2/Δ1 = 1.0" in dialog._ratio_status.text()
    assert not dialog._everywhere.isChecked()


@pytest.mark.gui
def test_the_menu_generates_the_cases_in_one_undo_step(qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.views.main_window import MainWindow

    mw = MainWindow()
    qtbot.addWidget(mw)
    mw._vm.adopt(_portal())
    monkeypatch.setattr(DirectAnalysisDialog, "exec", lambda self: 1)
    assert mw._act_direct_analysis.isEnabled()
    mw._act_direct_analysis.trigger()
    project = mw._vm.project
    assert sum(1 for c in project.analyses if is_direct_analysis_case(c)) == 12
    assert project.design.stability_method == "direct"
    assert "Direct Analysis Method: 12 case(s)" in mw._console.toPlainText()
    # Generating again replaces them instead of adding.
    mw._act_direct_analysis.trigger()
    assert sum(1 for c in project.analyses if is_direct_analysis_case(c)) == 12
    mw._vm.undo_stack.undo()
    mw._vm.undo_stack.undo()
    assert len(project.analyses) == 3
    assert project.design is None


@pytest.mark.gui
def test_the_menu_stores_the_basis_in_one_undo_step(qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.views.main_window import MainWindow

    mw = MainWindow()
    qtbot.addWidget(mw)
    mw._vm.adopt(_portal())

    def _accept(self) -> int:  # type: ignore[no-untyped-def]
        self.apply_manual_defaults()
        return 1

    monkeypatch.setattr(DesignBasisDialog, "exec", _accept)
    mw._act_design_basis.trigger()
    project = mw._vm.project
    assert project.design.steel_grades["W"] == "A992"
    mw._vm.undo_stack.undo()
    assert project.design is None
