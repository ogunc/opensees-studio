"""File → New starts with the default materials; Define → Add Default Materials tops up."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from opensees_studio.core import Project, UnitSystem
from opensees_studio.core.default_materials import DEFAULT_MATERIALS
from opensees_studio.core.materials import ElasticIsotropic
from opensees_studio.views.main_window import MainWindow

pytestmark = pytest.mark.gui

NAMES = [entry.name for entry in DEFAULT_MATERIALS]


@pytest.fixture
def window(qtbot):  # type: ignore[no-untyped-def]
    win = MainWindow()
    qtbot.addWidget(win)
    return win


def test_file_new_starts_with_the_default_materials(window: MainWindow) -> None:
    window._on_new()
    assert [m.name for m in window._vm.project.materials] == NAMES
    assert not window._vm.is_dirty


def test_the_materials_follow_the_units_of_a_new_model(window: MainWindow) -> None:
    window._vm.new_project(3, 6, units=UnitSystem.US_IN_KIP, default_materials=True)
    steel = next(m for m in window._vm.project.materials if m.name == "A572Gr50")
    assert pytest.approx(29_000.0) == steel.E
    assert steel.Fy == pytest.approx(50.0)


def test_an_empty_project_stays_empty_unless_asked(window: MainWindow) -> None:
    window._vm.new_project()
    assert window._vm.project.materials == []


def test_add_default_materials_adds_only_the_missing_ones_in_one_undo(
    window: MainWindow,
) -> None:
    project = Project()
    project.materials.append(ElasticIsotropic(id=1, name="A36", E=200e9, nu=0.3))
    window._vm.adopt(project)
    window._refresh_action_enablement()
    assert window._act_default_materials.isEnabled()

    window._act_default_materials.trigger()

    names = [m.name for m in window._vm.project.materials]
    assert names == ["A36", *(n for n in NAMES if n != "A36")]
    window._vm.undo_stack.undo()
    assert [m.name for m in window._vm.project.materials] == ["A36"]
    window._vm.undo_stack.redo()
    window._act_default_materials.trigger()  # nothing left to add
    assert len(window._vm.project.materials) == len(NAMES)
