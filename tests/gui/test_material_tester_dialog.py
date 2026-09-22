"""Material Tester dialog: menu action, material list, run, CSV export, errors."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from opensees_studio.core import ElasticIsotropic, HystereticSM, Steel02, UnitSystem


def _open(qtbot):  # type: ignore[no-untyped-def]
    from opensees_studio.views.main_window import MainWindow

    mw = MainWindow()
    qtbot.addWidget(mw)
    mw._vm.new_project()
    mw._vm.project.meta.units = UnitSystem.SI_MM_N
    mw._vm.project.materials.extend(
        [
            ElasticIsotropic(id=1, E=30000.0, nu=0.2),
            Steel02(id=2, Fy=420.0, E0=200000.0, b=0.01, name="B420C"),
            HystereticSM(id=3, pos_env=[(1.0, 0.01), (2.0, 0.02)]),
        ]
    )
    mw._act_material_tester.trigger()
    dlg = mw._material_tester_dlg
    assert dlg is not None
    qtbot.addWidget(dlg)
    return mw, dlg


def _select(dlg, material_id: int) -> None:  # type: ignore[no-untyped-def]
    dlg._material.setCurrentIndex(dlg._material.findData(material_id))


@pytest.mark.gui
def test_action_is_in_define_menu_and_opens_non_modal_dialog(qtbot) -> None:  # type: ignore[no-untyped-def]
    mw, dlg = _open(qtbot)
    define = next(a.menu() for a in mw.menuBar().actions() if a.text() == "&Define")
    assert mw._act_material_tester in define.actions()
    assert dlg.isVisible()
    assert not dlg.isModal()
    mw._act_material_tester.trigger()
    assert mw._material_tester_dlg is dlg  # reused, not stacked


@pytest.mark.gui
def test_lists_project_uniaxial_materials(qtbot) -> None:  # type: ignore[no-untyped-def]
    _, dlg = _open(qtbot)
    ids = [dlg._material.itemData(i) for i in range(dlg._material.count())]
    assert ids == [2, 3]  # the nD ElasticIsotropic is left out
    assert dlg._material.itemText(0) == "2: Steel02 (B420C)"


@pytest.mark.gui
def test_steel02_run_plots_expected_points_and_rerun_replaces(qtbot) -> None:  # type: ignore[no-untyped-def]
    _, dlg = _open(qtbot)
    _select(dlg, 2)
    dlg._protocol.setCurrentIndex(dlg._protocol.findData("cyclic"))
    dlg._cycles.setValue(2)
    dlg._steps.setValue(40)
    dlg._run_btn.click()
    x, y = dlg.curve_data()
    assert len(x) == len(y) == 2 * 3 * 40
    assert "Energy dissipated, cycle 2" in dlg._summary.toPlainText()
    assert dlg._plot.getPlotItem().getAxis("left").labelText == "Stress [MPa]"
    assert dlg._export_btn.isEnabled()

    dlg._run_btn.click()
    assert len(dlg._plot.getPlotItem().listDataItems()) == 1


@pytest.mark.gui
def test_csv_export_row_count(qtbot, tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.views.dialogs import material_tester as mod

    _, dlg = _open(qtbot)
    _select(dlg, 2)
    dlg._protocol.setCurrentIndex(dlg._protocol.findData("increasing"))
    dlg._peaks.setText("0.001 0.002 0.004")
    dlg._steps.setValue(10)
    assert dlg.run()
    target = tmp_path / "steel.csv"
    monkeypatch.setattr(
        mod.QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(target), ""))
    )
    dlg._export_btn.click()
    lines = target.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "# material: 2: Steel02 (B420C)"
    assert "increasing amplitude" in lines[1]
    assert lines[2] == "strain,stress [MPa]"
    assert len(lines) - 3 == len(dlg.curve_data()[0]) == 3 * 3 * 10


@pytest.mark.gui
def test_unsupported_material_shows_error_and_empty_plot(qtbot) -> None:  # type: ignore[no-untyped-def]
    _, dlg = _open(qtbot)
    _select(dlg, 2)
    assert dlg.run()
    _select(dlg, 3)
    assert not dlg.run()
    assert "Unsupported material type: HystereticSM" in dlg._summary.toPlainText()
    assert dlg.curve_data() is None
    assert dlg._plot.getPlotItem().listDataItems() == []
    assert not dlg._export_btn.isEnabled()
