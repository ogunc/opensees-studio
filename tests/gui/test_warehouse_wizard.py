"""Define → Create Warehouse: the wizard, the preview, one undo step.

The geometry, the loads and the plan are pinned in ``tests/unit/test_warehouse.py``;
here it is the wiring: the fields reach the core spec, the warehouse arrives as
one undoable step with its sections, groups, cases and combinations, and a plan
that does not fit is refused before anything is pushed.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyvistaqt")

from PySide6.QtWidgets import QDialog, QMessageBox

from opensees_studio.commands.warehouse import insert_warehouse_plan, plan_problems
from opensees_studio.core.frames import RoofType, SupportCondition
from opensees_studio.core.units import UnitSystem
from opensees_studio.core.warehouse import GROUPS, WarehouseSpec, plan_warehouse
from opensees_studio.views.dialogs.warehouse_wizard import WarehouseWizard


def _window(qtbot, *, ndm: int = 3, ndf: int = 6):  # type: ignore[no-untyped-def]
    from opensees_studio.views.main_window import MainWindow

    mw = MainWindow()
    qtbot.addWidget(mw)
    mw._vm.new_project(ndm=ndm, ndf=ndf, dead_case=True, default_materials=True)
    return mw


def _accept(monkeypatch, setup=lambda wizard: None) -> None:  # type: ignore[no-untyped-def]
    def _fake_exec(self: WarehouseWizard) -> int:
        setup(self)
        return int(QDialog.DialogCode.Accepted)

    monkeypatch.setattr(WarehouseWizard, "exec", _fake_exec)


# ─────────────────────────────── the wizard ───────────────────────────────
@pytest.mark.gui
def test_the_fields_reach_the_spec(qtbot) -> None:  # type: ignore[no-untyped-def]
    wizard = WarehouseWizard([])
    qtbot.addWidget(wizard)
    wizard._roof.setCurrentIndex(1)  # one slope
    wizard._span.setValue(15.0)
    wizard._n_naves.setValue(2)
    wizard._n_frames.setValue(8)
    wizard._frame_spacing.setValue(5.0)
    wizard._eave_height.setValue(7.0)
    wizard._slope.setValue(12.0)
    wizard._support.setCurrentIndex(0)
    wizard._purlin_spacing.setValue(1.2)
    wizard._girt_spacing.setValue(0.0)
    wizard._rafter_fly.setValue(3)
    wizard._wall_bracing.setChecked(False)
    wizard._braced_bays.setText("1, 4; 7")

    spec = wizard.spec()
    assert spec == WarehouseSpec(
        span=15.0,
        eave_height=7.0,
        frame_spacing=5.0,
        n_frames=8,
        n_naves=2,
        roof=RoofType.MONO_PITCH,
        slope=0.12,
        support=SupportCondition.FIXED,
        purlin_spacing=1.2,
        girt_spacing=0.0,
        rafter_fly_brace_every=3,
        roof_bracing=True,
        wall_bracing=False,
        braced_bays=(0, 3, 6),
    )
    assert wizard.section_choice() == dict.fromkeys(("column", "rafter", "purlin", "girt", "brace"))


@pytest.mark.gui
def test_the_preview_follows_the_fields_and_bad_numbers_block_next(qtbot) -> None:  # type: ignore[no-untyped-def]
    wizard = WarehouseWizard([])
    qtbot.addWidget(wizard)
    assert wizard._page_geometry.isComplete()
    before = wizard._preview.line_count()
    assert before > 0
    wizard._n_frames.setValue(wizard._n_frames.value() + 2)
    assert wizard._preview.line_count() > before

    wizard._span.setValue(0.0)
    assert not wizard._page_geometry.isComplete()
    assert wizard._preview.line_count() == 0
    assert "must be positive" in wizard._geometry_summary.text()
    wizard._span.setValue(20.0)
    wizard._braced_bays.setText("two")
    assert not wizard._page_secondary.isComplete()
    wizard._braced_bays.setText("99")
    assert not wizard._page_secondary.isComplete()
    wizard._braced_bays.setText("")
    assert wizard._page_secondary.isComplete()
    wizard.grab()  # the preview paints


@pytest.mark.gui
def test_the_code_sets_the_roof_live_defaults_in_project_units(qtbot) -> None:  # type: ignore[no-untyped-def]
    wizard = WarehouseWizard([], units=UnitSystem.US_FT_KIP)
    qtbot.addWidget(wizard)
    assert wizard.loads().code == "rnc07"
    assert wizard._roof_live.value() == pytest.approx(10 * 9.80665 / 47880.26, rel=1e-4)  # ksf
    assert wizard._point.value() == pytest.approx(200 * 9.80665 / 4448.222, rel=1e-6)  # kip
    wizard._code.setCurrentIndex(wizard._code.findData("asce7_lrfd"))
    loads = wizard.loads()
    assert loads.code == "asce7_lrfd"
    assert loads.roof_live == pytest.approx(0.020, rel=1e-3)  # 20 psf
    assert loads.midspan_point == 0.0
    assert wizard._span.value() == pytest.approx(20.0 / 0.3048)


# ──────────────────────────── through the menu ────────────────────────────
@pytest.mark.gui
def test_the_menu_builds_the_warehouse_in_one_undo_step(qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    mw = _window(qtbot)
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: pytest.fail(str(a[2])))
    _accept(monkeypatch, lambda w: w._n_frames.setValue(3))
    project = mw._vm.project
    before = project.model_dump()
    index = mw._vm.undo_stack.index()
    mw._refresh_action_enablement()
    assert mw._act_warehouse_wizard.isEnabled()

    mw._act_warehouse_wizard.trigger()

    assert mw._vm.undo_stack.index() == index + 1  # one step
    assert len({n.coords[1] for n in project.nodes}) == 3
    assert [g.name for g in project.groups] == list(GROUPS.values())
    grouped = {eid for g in project.groups for eid in g.element_ids}
    assert grouped == {e.id for e in project.elements}
    assert {s.name for s in project.sections} >= {"W14X48", "W16X40", "C150X50X15X2.38"}
    assert [c.name for c in project.analyses] == ["DEAD", "LIVE"]
    assert [c.name for c in project.combinations][:2] == ["1.4CM", "1.2CM+1.6CV"]
    assert project.design is not None and project.design.members
    assert project.coord_systems[-1].name == "Warehouse"
    assert "Warehouse 20 x 12" in mw._console.toPlainText()

    mw._vm.undo_stack.undo()
    assert project.model_dump() == before
    mw._vm.undo_stack.redo()
    assert len(project.elements) == len(grouped)


@pytest.mark.gui
def test_cancelling_leaves_the_project_alone(qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    mw = _window(qtbot)
    monkeypatch.setattr(WarehouseWizard, "exec", lambda self: int(QDialog.DialogCode.Rejected))
    before = mw._vm.project.model_dump()
    mw._act_warehouse_wizard.trigger()
    assert mw._vm.project.model_dump() == before


@pytest.mark.gui
def test_a_2d_project_is_told_why_not(qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    mw = _window(qtbot, ndm=2, ndf=3)
    seen: list[str] = []
    monkeypatch.setattr(
        QMessageBox,
        "information",
        lambda _p, _t, text: seen.append(text) or QMessageBox.StandardButton.Ok,
    )
    monkeypatch.setattr(WarehouseWizard, "exec", lambda self: pytest.fail("the wizard opened"))
    mw._act_warehouse_wizard.trigger()
    assert seen and "ndm = 2" in seen[0]
    assert mw._vm.project.nodes == []


@pytest.mark.gui
def test_the_new_model_template_opens_the_wizard(qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.core.templates import TEMPLATE_NDF, TEMPLATES

    assert TEMPLATES["warehouse"] == "Warehouse" and TEMPLATE_NDF["warehouse"] == (3, 6)
    mw = _window(qtbot)
    _accept(monkeypatch, lambda w: w._n_frames.setValue(2))
    mw._start_template("warehouse", UnitSystem.SI_MM_N, None)
    project = mw._vm.project
    assert project.meta.units is UnitSystem.SI_MM_N
    assert max(n.coords[0] for n in project.nodes) == pytest.approx(20_000.0)
    assert project.elements


# ─────────────────────────── the insertion ───────────────────────────
@pytest.mark.gui
def test_a_plan_that_does_not_fit_is_refused_before_anything_is_pushed(qtbot) -> None:  # type: ignore[no-untyped-def]
    mw = _window(qtbot)
    project = mw._vm.project
    spec = WarehouseSpec(span=10.0, eave_height=4.0, frame_spacing=5.0, n_frames=2)
    plan = plan_warehouse(project, spec)
    assert plan_problems(project, plan) == []
    insert_warehouse_plan(mw._vm, plan)
    before = project.model_dump()
    index = mw._vm.undo_stack.index()

    # The same plan again: every id it carries is now taken.
    problems = plan_problems(project, plan)
    assert any("Node id" in p for p in problems) and any("Element id" in p for p in problems)
    with pytest.raises(ValueError, match="already in use"):
        insert_warehouse_plan(mw._vm, plan)
    assert project.model_dump() == before
    assert mw._vm.undo_stack.index() == index
