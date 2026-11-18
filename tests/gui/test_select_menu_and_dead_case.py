"""File → New starts with the DEAD case; the Select menu; the self-weight fields."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyvistaqt")

from opensees_studio.commands import AddElementsCommand, AddNodesCommand, AddSectionsCommand
from opensees_studio.core import (
    ElasticBeamColumn,
    ElasticSection,
    Node,
    PlainLoadPattern,
    RectShape,
    TrussElement,
)


def _window(qtbot):  # type: ignore[no-untyped-def]
    from opensees_studio.views.main_window import MainWindow

    mw = MainWindow()
    qtbot.addWidget(mw)
    return mw


def _model(mw) -> None:  # type: ignore[no-untyped-def]
    vm = mw._vm
    vm.new_project(ndm=3, ndf=6)
    vm.apply_command(
        AddNodesCommand(
            vm,
            [
                Node(id=1, coords=(0.0, 0.0, 0.0), restraint=(True,) * 6),
                Node(id=2, coords=(4.0, 0.0, 0.0)),
                Node(id=3, coords=(0.0, 0.0, 3.0)),
            ],
        )
    )
    vm.apply_command(
        AddSectionsCommand(
            vm,
            [
                ElasticSection(id=1, name="B", E=1, A=1, Iz=1, Iy=1, G=1, J=1, unit_weight=2.0),
                ElasticSection(id=2, name="C", E=1, A=1, Iz=1, Iy=1, G=1, J=1),
            ],
        )
    )
    vm.apply_command(
        AddElementsCommand(
            vm,
            [
                ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1),
                ElasticBeamColumn(id=2, nodes=(1, 3), section_id=2),
                TrussElement(id=3, nodes=(2, 3), area=1.0, material_id=1),
            ],
        )
    )


def _submenu_entries(mw, submenu, fill):  # type: ignore[no-untyped-def]
    fill(submenu)
    return {action.text(): action for action in submenu.actions()}


# ──────────────────────────── the DEAD case ────────────────────────────
@pytest.mark.gui
@pytest.mark.parametrize("action", ["_act_new", "_act_new_2d_truss"])
def test_file_new_starts_with_the_dead_case(qtbot, monkeypatch, action) -> None:  # type: ignore[no-untyped-def]
    mw = _window(qtbot)
    getattr(mw, action).trigger()

    project = mw._vm.project
    (pattern,) = project.load_patterns
    assert isinstance(pattern, PlainLoadPattern)
    assert (pattern.name, pattern.self_weight) == ("DEAD", 1.0)
    (case,) = project.analyses
    assert (case.type, case.name, case.pattern_ids) == ("Static", "DEAD", [pattern.id])


@pytest.mark.gui
def test_the_section_form_keeps_unit_weight_and_shape(qtbot) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.views.dialogs.section_forms import ElasticSectionForm

    form = ElasticSectionForm()
    qtbot.addWidget(form)
    shape = RectShape(b=0.2, d=0.4)
    form.populate(
        ElasticSection(
            id=4, name="S", E=1, A=1, Iz=1, Iy=1, G=1, J=1, unit_weight=25e3, shape=shape
        )
    )
    section = form.read()
    assert (section.unit_weight, section.shape) == (25e3, shape)


@pytest.mark.gui
def test_the_pattern_dialog_sets_the_self_weight(qtbot) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.core import LinearTimeSeries, Project
    from opensees_studio.views.dialogs import PlainPatternDialog

    dialog = PlainPatternDialog(Project(time_series=[LinearTimeSeries(id=1)]), 3)
    qtbot.addWidget(dialog)
    assert dialog.pattern().self_weight == 0.0
    dialog._self_weight.setValue(1.0)
    assert dialog.pattern().self_weight == 1.0


# ──────────────────────────── the Select menu ────────────────────────────
@pytest.mark.gui
def test_by_section_adds_to_the_selection(qtbot) -> None:  # type: ignore[no-untyped-def]
    mw = _window(qtbot)
    _model(mw)
    sel = mw._canvas.selection

    entries = _submenu_entries(mw, mw._menu_select_by_section, mw._fill_select_by_section)
    assert sorted(entries) == ["#1 B (1)", "#2 C (1)"]
    entries["#1 B (1)"].trigger()
    assert sel.elements == {1}
    entries["#2 C (1)"].trigger()
    assert sel.elements == {1, 2}  # additive


@pytest.mark.gui
def test_by_type_and_by_pattern(qtbot) -> None:  # type: ignore[no-untyped-def]
    mw = _window(qtbot)
    _model(mw)
    mw._vm.project.load_patterns.append(PlainLoadPattern(id=7, time_series_id=1, self_weight=1.0))
    sel = mw._canvas.selection

    by_type = _submenu_entries(mw, mw._menu_select_by_type, mw._fill_select_by_type)
    by_type["Truss (1)"].trigger()
    assert sel.elements == {3}

    sel.clear()
    by_pattern = _submenu_entries(mw, mw._menu_select_by_pattern, mw._fill_select_by_pattern)
    (entry,) = by_pattern.values()
    entry.trigger()
    assert sel.elements == {1}  # only section B has a unit weight


@pytest.mark.gui
def test_by_material_lists_what_the_elements_use(qtbot) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.core import ElasticUniaxial

    mw = _window(qtbot)
    _model(mw)
    entries = _submenu_entries(mw, mw._menu_select_by_material, mw._fill_select_by_material)
    assert list(entries) == ["(none in the model)"]  # material 1 is not defined yet

    mw._vm.project.materials.append(ElasticUniaxial(id=1, name="steel", E=1.0))
    entries = _submenu_entries(mw, mw._menu_select_by_material, mw._fill_select_by_material)
    entries["#1 steel (1)"].trigger()
    assert mw._canvas.selection.elements == {3}


@pytest.mark.gui
def test_invert_previous_and_node_queries(qtbot) -> None:  # type: ignore[no-untyped-def]
    mw = _window(qtbot)
    _model(mw)
    sel = mw._canvas.selection

    sel.set_selection({1}, {1})
    mw._act_invert_selection.trigger()
    assert (sel.nodes, sel.elements) == ({2, 3}, {2, 3})

    mw._act_previous_selection.trigger()
    assert (sel.nodes, sel.elements) == ({1}, {1})

    sel.clear()
    mw._act_select_supports.trigger()
    assert sel.nodes == {1}
    sel.set_selection(set(), {2})
    mw._act_select_joints_of_elements.trigger()
    assert sel.nodes == {1, 3}
    sel.set_selection({1, 2}, set())
    mw._act_select_elements_within_joints.trigger()
    assert sel.elements == {1}
    mw._act_select_weighted.trigger()
    assert sel.elements == {1}


@pytest.mark.gui
def test_the_select_menu_is_in_the_menu_bar(qtbot) -> None:  # type: ignore[no-untyped-def]
    mw = _window(qtbot)
    titles = [action.text() for action in mw.menuBar().actions()]
    assert titles.index("&Select") == titles.index("&Edit") + 1
