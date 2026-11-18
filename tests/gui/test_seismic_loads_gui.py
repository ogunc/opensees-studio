"""Define → Seismic Loads (Equivalent Lateral Force): preview, write, refill, undo."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyvistaqt")

from opensees_studio.core import Node, PlainLoadPattern, Storey
from opensees_studio.viewmodels import ProjectViewModel
from opensees_studio.views.dialogs.seismic_loads import SeismicLoadsDialog, pattern_names


def _vm(ndm: int = 3) -> ProjectViewModel:
    vm = ProjectViewModel()
    vm.new_project(ndm=ndm, ndf=6 if ndm == 3 else 3, dead_case=True)
    project = vm.project
    assert project is not None
    nid = 1
    for z in (0.0, 3.0, 6.0):
        for x, y in ((0.0, 0.0), (6.0, 0.0), (0.0, 4.0), (6.0, 4.0)):
            if ndm == 2 and y:
                continue
            m = 0.0 if z == 0.0 else 2.5
            project.nodes.append(Node(id=nid, coords=(x, y, z), mass=(m, m, 0.0, 0.0, 0.0, 0.0)))
            nid += 1
    project.storeys = [
        Storey(id=1, name="S1", elevation=3.0),
        Storey(id=2, name="S2", elevation=6.0),
    ]
    return vm


@pytest.mark.gui
def test_the_preview_lists_every_storey_and_direction(qtbot) -> None:  # type: ignore[no-untyped-def]
    dlg = SeismicLoadsDialog(_vm())
    qtbot.addWidget(dlg)
    assert dlg.code_key() == "asce7_16"
    assert dlg.chosen_axes() == ["X", "Y"]
    assert dlg.table.rowCount() == 4  # two storeys, two directions
    assert "V =" in dlg.summary.text() and "Cs =" in dlg.summary.text()


@pytest.mark.gui
def test_a_2d_model_offers_x_only_and_no_eccentricity(qtbot) -> None:  # type: ignore[no-untyped-def]
    dlg = SeismicLoadsDialog(_vm(ndm=2))
    qtbot.addWidget(dlg)
    assert dlg.chosen_axes() == ["X"]
    assert not dlg.eccentric.isEnabled()


@pytest.mark.gui
def test_ok_writes_one_pattern_and_case_per_direction_in_one_undo_step(qtbot) -> None:  # type: ignore[no-untyped-def]
    vm = _vm()
    project = vm.project
    assert project is not None
    before = (len(project.load_patterns), len(project.analyses))
    dlg = SeismicLoadsDialog(vm)
    qtbot.addWidget(dlg)
    assert dlg.apply() == ["EQ X", "EQ Y"]
    names = {p.name: p for p in project.load_patterns}
    eq_x = names["EQ X"]
    assert sum(load.forces[0] for load in eq_x.nodal_loads) == pytest.approx(
        dlg.results()["X"].base_shear
    )
    assert {c.name for c in project.analyses} >= {"EQ X", "EQ Y"}
    vm.undo_stack.undo()
    assert (len(project.load_patterns), len(project.analyses)) == before


@pytest.mark.gui
def test_an_existing_pattern_of_the_same_name_is_refilled(qtbot) -> None:  # type: ignore[no-untyped-def]
    vm = _vm()
    project = vm.project
    assert project is not None
    project.load_patterns.append(PlainLoadPattern(id=50, name="EQ X", time_series_id=1))
    dlg = SeismicLoadsDialog(vm)
    qtbot.addWidget(dlg)
    dlg.directions["Y"].setChecked(False)
    dlg.apply()
    same = [p for p in project.load_patterns if p.name == "EQ X"]
    assert len(same) == 1 and same[0].id == 50 and same[0].nodal_loads
    vm.undo_stack.undo()
    assert not next(p for p in project.load_patterns if p.id == 50).nodal_loads


@pytest.mark.gui
def test_eccentricity_writes_the_plus_and_minus_cases(qtbot) -> None:  # type: ignore[no-untyped-def]
    dlg = SeismicLoadsDialog(_vm())
    qtbot.addWidget(dlg)
    dlg.eccentric.setChecked(True)
    assert dlg.apply() == [n for axis in ("X", "Y") for n, _ in pattern_names(axis, True)]


@pytest.mark.gui
def test_approximate_fills_the_code_period_and_tbdy_switches_the_fields(qtbot) -> None:  # type: ignore[no-untyped-def]
    dlg = SeismicLoadsDialog(_vm())
    qtbot.addWidget(dlg)
    dlg.system.setCurrentIndex(dlg.system.findData("concrete_mrf"))
    dlg.fill_approximate_period()
    assert dlg.period.value() == pytest.approx(round(0.0466 * 6.0**0.9, 4))
    dlg.code.setCurrentIndex(dlg.code.findData("tbdy2018"))
    assert dlg.overstrength.isEnabled() and not dlg.s1.isEnabled()
    assert "Vt by" in dlg.summary.text()


@pytest.mark.gui
def test_the_menu_action_opens_the_dialog(qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.views.main_window import MainWindow

    mw = MainWindow()
    qtbot.addWidget(mw)
    mw._vm.new_project()
    mw._refresh_action_enablement()
    seen = []
    monkeypatch.setattr(SeismicLoadsDialog, "exec", lambda self: seen.append(self) or 0)
    mw._act_seismic_loads.trigger()
    assert seen and isinstance(seen[0], SeismicLoadsDialog)
