"""Assign → Area (surface, floor) and Assign → Joint → Imposed Displacement, from the window."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyvistaqt")

from opensees_studio.commands import AddElementsCommand, AddNodesCommand, AddSectionsCommand
from opensees_studio.core import (
    ElasticBeamColumn,
    ElasticMembranePlateSection,
    ElasticSection,
    Node,
    ShellMITC4Element,
)
from opensees_studio.views.dialogs.area_loads import (
    FloorLoadDialog,
    ImposedDisplacementDialog,
    SurfaceLoadDialog,
)


def _window(qtbot):  # type: ignore[no-untyped-def]
    from opensees_studio.views.main_window import MainWindow

    mw = MainWindow()
    qtbot.addWidget(mw)
    vm = mw._vm
    vm.new_project(dead_case=True)
    plan = ((0.0, 0.0), (6.0, 0.0), (6.0, 4.0), (0.0, 4.0))
    vm.apply_command(
        AddNodesCommand(
            vm,
            [Node(id=k + 1, coords=(x, y, 3.0)) for k, (x, y) in enumerate(plan)]
            + [
                Node(id=k + 11, coords=(x, y, 0.0), restraint=(True,) * 6)
                for k, (x, y) in enumerate(plan)
            ],
        )
    )
    vm.apply_command(
        AddSectionsCommand(
            vm,
            [
                ElasticSection(id=1, E=3e10, A=0.09, Iz=6.75e-4, Iy=6.75e-4, G=1.2e10, J=1e-3),
                ElasticMembranePlateSection(id=2, E=3e10, nu=0.2, h=0.2),
            ],
        )
    )
    beams = [
        ElasticBeamColumn(id=k + 1, nodes=(k + 1, (k + 1) % 4 + 1), section_id=1) for k in range(4)
    ]
    vm.apply_command(
        AddElementsCommand(vm, [*beams, ShellMITC4Element(id=20, nodes=(1, 2, 3, 4), section_id=2)])
    )
    return mw


def _accept(monkeypatch, cls, fill=None):  # type: ignore[no-untyped-def]
    def _exec(self) -> int:  # type: ignore[no-untyped-def]
        if fill is not None:
            fill(self)
        return 1

    monkeypatch.setattr(cls, "exec", _exec)


def _dead(mw):  # type: ignore[no-untyped-def]
    return next(p for p in mw._vm.project.load_patterns if p.name == "DEAD")


@pytest.mark.gui
def test_the_menu_holds_the_three_actions(qtbot) -> None:  # type: ignore[no-untyped-def]
    mw = _window(qtbot)
    menus = {a.text(): a.menu() for a in mw.menuBar().actions()}
    assign = {a.text(): a.menu() for a in menus["&Assign"].actions() if a.menu()}
    assert mw._act_assign_surface_load in assign["A&rea"].actions()
    assert mw._act_assign_floor_load in assign["A&rea"].actions()
    assert mw._act_assign_imposed_displacement in assign["&Joint"].actions()


@pytest.mark.gui
def test_a_surface_load_on_the_selected_shell(qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    mw = _window(qtbot)
    mw._canvas.selection.set_selection(set(), {20, 1})  # a beam in the selection is skipped
    _accept(monkeypatch, SurfaceLoadDialog, lambda d: d.value.setValue(-2.5))
    mw._on_assign_surface_load()
    (load,) = _dead(mw).surface_loads
    assert (load.element_id, load.value, load.direction) == (20, -2.5, "Z")
    mw._vm.undo_stack.undo()
    assert not _dead(mw).surface_loads


@pytest.mark.gui
def test_a_floor_load_on_the_bay_the_selected_joints_frame(qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    mw = _window(qtbot)
    mw._canvas.selection.set_selection({1, 2, 3, 4}, set())
    mw._refresh_action_enablement()
    assert mw._act_assign_floor_load.isEnabled()

    def fill(d: FloorLoadDialog) -> None:
        d.value.setValue(5.0)
        d.distribution.setCurrentIndex(d.distribution.findData("one_way_y"))

    _accept(monkeypatch, FloorLoadDialog, fill)
    mw._on_assign_floor_load()
    (load,) = _dead(mw).floor_loads
    assert load.nodes == (1, 2, 3, 4) and load.value == 5.0
    # Corner 1 -> 2 runs along X, so a slab spanning along Y spans edge 2-3.
    assert load.distribution == "one_way_23"


@pytest.mark.gui
def test_an_imposed_settlement_on_the_selected_joints(qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    mw = _window(qtbot)
    mw._canvas.selection.set_selection({11, 12}, set())
    mw._refresh_action_enablement()
    _accept(monkeypatch, ImposedDisplacementDialog)
    mw._on_assign_imposed_displacement()
    loads = _dead(mw).imposed_displacements
    assert [(x.node_id, x.dof, x.value) for x in loads] == [(11, 3, -0.01), (12, 3, -0.01)]
