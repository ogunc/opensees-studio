"""Design → Steel Frame Check and Storey Drift Check, through the dialogs and the menu.

The numbers are pinned in ``tests/integration/test_steel_design_run.py``; here the
wiring: the dialog lists the load sets, checks on demand, colours a failing row,
hands the settings back, and the menu stores them in one undoable step.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyvistaqt")
pytest.importorskip("openseespy")

from PySide6.QtWidgets import QDialog

from opensees_studio.core.design.settings import DesignSettings
from opensees_studio.services.opensees_runner import OpenSeesRunner
from opensees_studio.views.dialogs import DriftCheckDialog, SteelDesignDialog


def _beam_project():  # type: ignore[no-untyped-def]
    from tests.integration.test_steel_design_run import _beam

    return _beam()


def _results(project):  # type: ignore[no-untyped-def]
    return {case.id: OpenSeesRunner(project).run(case) for case in project.analyses}


@pytest.mark.gui
def test_the_dialog_checks_the_members(qtbot) -> None:  # type: ignore[no-untyped-def]
    project = _beam_project()
    dialog = SteelDesignDialog(project, _results(project))
    qtbot.addWidget(dialog)
    labels = [dialog._load_sets.item(r).text() for r in range(dialog._load_sets.count())]
    assert "Combination 1.2D+1.6L" in labels
    report = dialog.run_check()
    assert dialog._table.rowCount() == 4
    assert "4 member(s) checked" in dialog._summary.text()
    assert not report.failing


@pytest.mark.gui
def test_a_low_limit_fails_members_and_selects_them(qtbot) -> None:  # type: ignore[no-untyped-def]
    project = _beam_project()
    dialog = SteelDesignDialog(project, _results(project))
    qtbot.addWidget(dialog)
    dialog._limit.setValue(0.01)
    report = dialog.run_check()
    assert report.failing
    assert dialog._select_failing.isEnabled()
    assert dialog.failing_elements() == {m.element_id for m in report.failing}
    assert dialog.settings().ratio_limit == pytest.approx(0.01)


@pytest.mark.gui
def test_the_seismic_settings_round_trip(qtbot) -> None:  # type: ignore[no-untyped-def]
    project = _beam_project()
    project.design = DesignSettings(seismic_system="SCBF", ry=1.2)
    dialog = SteelDesignDialog(project, _results(project))
    qtbot.addWidget(dialog)
    assert dialog._seismic.currentText() == "SCBF"
    assert dialog._ry.value() == pytest.approx(1.2)
    dialog._seismic.setCurrentText("IMF")
    dialog._ry.setValue(1.0)
    settings = dialog.settings()
    assert settings.seismic_system == "IMF"
    assert settings.ry == pytest.approx(1.0)


@pytest.mark.gui
def test_p_delta_is_a_saved_setting(qtbot) -> None:  # type: ignore[no-untyped-def]
    project = _beam_project()
    project.design = DesignSettings(p_delta=True)
    dialog = SteelDesignDialog(project, _results(project))
    qtbot.addWidget(dialog)
    assert dialog._p_delta.isChecked()
    dialog._p_delta.setChecked(False)
    assert dialog.settings().p_delta is False
    dialog._p_delta.setChecked(True)
    assert dialog.settings().p_delta is True


@pytest.mark.gui
def test_overrides_apply_to_the_selection(qtbot) -> None:  # type: ignore[no-untyped-def]
    project = _beam_project()
    dialog = SteelDesignDialog(project, _results(project), selected_elements=frozenset({2, 3}))
    qtbot.addWidget(dialog)
    dialog._shape.setText("W21X44")
    dialog._cb.setValue(1.0)
    dialog._apply_overrides()
    members = {m.element_id: m for m in dialog.settings().members}
    assert set(members) == {2, 3}
    assert members[2].shape == "W21X44" and members[2].cb == 1.0
    report = dialog.run_check()
    assert next(m for m in report.members if m.element_id == 2).shape == "W21X44"


@pytest.mark.gui
def test_fu_and_the_net_area_round_trip(qtbot) -> None:  # type: ignore[no-untyped-def]
    project = _beam_project()
    dialog = SteelDesignDialog(project, _results(project), selected_elements=frozenset({2}))
    qtbot.addWidget(dialog)
    dialog._fu.setValue(60.0)
    dialog._net_area.setValue(12.0)
    dialog._shear_lag.setValue(0.85)
    dialog._apply_overrides()
    settings = dialog.settings()
    assert settings.fu == pytest.approx(60.0)
    member = next(m for m in settings.members if m.element_id == 2)
    assert member.net_area == pytest.approx(12.0)
    assert member.shear_lag == pytest.approx(0.85)


@pytest.mark.gui
def test_notional_loads_action_adds_and_undoes_in_one_step(qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from examples.building_3storey_diaphragm import build_building

    from opensees_studio.views.dialogs.notional_loads import NotionalLoadsDialog
    from opensees_studio.views.main_window import MainWindow

    mw = MainWindow()
    qtbot.addWidget(mw)
    project = build_building()
    mw._vm.adopt(project)
    before = len(project.load_patterns)

    def _accept(self) -> int:  # type: ignore[no-untyped-def]
        self._direction.setCurrentIndex(0)
        self._factor.setValue(0.002)
        return int(QDialog.DialogCode.Accepted)

    monkeypatch.setattr(NotionalLoadsDialog, "exec", _accept)
    mw._act_notional_loads.trigger()
    patterns = [p for p in project.load_patterns if p.name == "NOTIONAL X"]
    assert len(patterns) == 1
    assert patterns[0].nodal_loads
    assert len(project.load_patterns) == before + 1
    mw._vm.undo_stack.undo()
    assert len(project.load_patterns) == before


@pytest.mark.gui
def test_the_notional_dialog_follows_alpha(qtbot) -> None:  # type: ignore[no-untyped-def]
    from examples.building_3storey_diaphragm import build_building

    from opensees_studio.views.dialogs.notional_loads import NotionalLoadsDialog

    project = build_building()
    dialog = NotionalLoadsDialog(project, method="ASD")
    qtbot.addWidget(dialog)
    assert dialog.method() == "ASD"
    assert dialog.settings()[1] == pytest.approx(0.0032)
    dialog._method.setCurrentIndex(0)
    assert dialog.method() == "LRFD"
    assert dialog.settings()[1] == pytest.approx(0.002)


@pytest.mark.gui
def test_cases_without_results_are_marked(qtbot) -> None:  # type: ignore[no-untyped-def]
    project = _beam_project()
    dialog = SteelDesignDialog(project, {})
    qtbot.addWidget(dialog)
    labels = [dialog._load_sets.item(r).text() for r in range(dialog._load_sets.count())]
    assert "Case DEAD  (no result: run it first)" in labels
    dialog.run_check()
    assert "run Case DEAD" in dialog._summary.text()


@pytest.mark.gui
def test_the_drift_dialog_needs_storeys(qtbot) -> None:  # type: ignore[no-untyped-def]
    project = _beam_project()
    dialog = DriftCheckDialog(project, _results(project))
    qtbot.addWidget(dialog)
    dialog._preset.setCurrentIndex(4)  # NCh433, 0.002
    assert dialog.settings().drift_limit == pytest.approx(0.002)
    dialog.run_check()
    assert "no storeys" in dialog._summary.text()


@pytest.mark.gui
def test_the_menu_stores_the_settings_in_one_undo_step(qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.views.main_window import MainWindow

    mw = MainWindow()
    qtbot.addWidget(mw)
    mw._vm.adopt(_beam_project())

    def _accept(self) -> int:  # type: ignore[no-untyped-def]
        self._method.setCurrentText("ASD")
        self.run_check()
        return int(QDialog.DialogCode.Accepted)

    monkeypatch.setattr(SteelDesignDialog, "exec", _accept)
    assert mw._act_steel_check.isEnabled()
    mw._act_steel_check.trigger()
    project = mw._vm.project
    assert isinstance(project.design, DesignSettings)
    assert project.design.method == "ASD"
    assert "Steel frame check (AISC 360-16, ASD)" in mw._console.toPlainText()
    mw._vm.undo_stack.undo()
    assert project.design is None


@pytest.mark.gui
def test_display_steel_ratios_paints_the_members(qtbot) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.views.main_window import MainWindow

    mw = MainWindow()
    qtbot.addWidget(mw)
    project = _beam_project()
    mw._vm.adopt(project)
    for results in _results(project).values():
        mw._case_results.put(project, results)
    assert mw._act_steel_ratios.isEnabled()
    mw._act_steel_ratios.trigger()
    assert mw._ratio_renderer.is_drawn
    assert mw._ratio_renderer.members == 4
    view = mw._post_dock.widget()
    assert "4 member(s) checked" in view.summary_text()
    view.closed.emit()
    assert not mw._ratio_renderer.is_drawn
    assert mw._post_dock is None


@pytest.mark.gui
def test_display_steel_ratios_without_results_explains(qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QMessageBox

    from opensees_studio.views.main_window import MainWindow

    mw = MainWindow()
    qtbot.addWidget(mw)
    mw._vm.adopt(_beam_project())
    shown: list[str] = []
    monkeypatch.setattr(
        QMessageBox, "information", lambda _parent, _title, text: shown.append(text)
    )
    mw._act_steel_ratios.trigger()
    assert not mw._ratio_renderer.is_drawn
    assert shown and "run Case" in shown[0]


@pytest.mark.gui
def test_the_dialog_button_shows_the_ratios(qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.views.main_window import MainWindow

    mw = MainWindow()
    qtbot.addWidget(mw)
    project = _beam_project()
    mw._vm.adopt(project)
    for results in _results(project).values():
        mw._case_results.put(project, results)

    def _show(self) -> int:  # type: ignore[no-untyped-def]
        self.run_check()
        assert self._show_ratios.isEnabled()
        self.accept_and_show()
        return int(QDialog.DialogCode.Accepted)

    monkeypatch.setattr(SteelDesignDialog, "exec", _show)
    mw._act_steel_check.trigger()
    assert mw._ratio_renderer.is_drawn
