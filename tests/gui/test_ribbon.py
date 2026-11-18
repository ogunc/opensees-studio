"""The ribbon: the menu actions regrouped, with nothing left out."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtGui import QAction

from opensees_studio.views.main_window import MainWindow
from opensees_studio.views.ribbon import build_ribbon_tabs


@pytest.fixture
def window(qtbot):  # type: ignore[no-untyped-def]
    win = MainWindow()
    qtbot.addWidget(win)
    return win


def _menu_actions(window: MainWindow) -> list[QAction]:
    out: list[QAction] = []

    def walk(menu) -> None:  # type: ignore[no-untyped-def]
        for action in menu.actions():
            sub = action.menu()
            if sub is not None:
                walk(sub)
                continue
            if action.isSeparator() or not action.text():
                continue
            out.append(action)

    for menu_action in window.menuBar().actions():
        menu = menu_action.menu()
        if menu is not None:
            walk(menu)
    return out


def test_the_ribbon_exposes_every_menu_action(window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    menu = _menu_actions(window)
    ribbon = window._ribbon.actions()

    assert len(menu) > 200
    assert len(ribbon) == len(menu), f"{len(menu)} menu actions, {len(ribbon)} ribbon actions"
    assert {id(a) for a in ribbon} == {id(a) for a in menu}


def test_the_tabs_follow_the_modelling_flow(window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    labels = [tab.label for tab in build_ribbon_tabs(window.menuBar())]
    assert labels == [
        "Home",
        "Modeling",
        "Define",
        "Loads",
        "Assign",
        "Analysis",
        "Design",
        "Results",
        "Views",
        "Help",
    ]


def test_the_design_tab_has_a_subpanel_per_material(window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    tab = next(t for t in build_ribbon_tabs(window.menuBar()) if t.id == "design")
    ids = [m.id for m in tab.materials]

    assert ids == ["acero", "concreto", "cold", "madera", "otros"]
    acero = next(m for m in tab.materials if m.id == "acero")
    acero_actions = [item.action.text() for group in acero.groups for item in group.items]
    assert any("Steel Frame Check" in label for label in acero_actions)
    concreto = next(m for m in tab.materials if m.id == "concreto")
    concreto_actions = [
        item.action.text().replace("&", "") for group in concreto.groups for item in group.items
    ]
    assert any("Concrete Frame Check" in label for label in concreto_actions)


def test_the_ribbon_is_the_default_and_the_menus_stay_available(window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    assert window._act_use_ribbon.isChecked()
    assert not window._menus_visible
    assert not window._ribbon_toolbar.isHidden()

    window._act_use_ribbon.setChecked(False)

    assert window._menus_visible
    assert window._ribbon_toolbar.isHidden()

    window._act_use_ribbon.setChecked(True)
    assert not window._menus_visible
    assert not window._ribbon_toolbar.isHidden()


def test_the_menus_button_brings_the_menu_bar_back(window: MainWindow) -> None:  # type: ignore[no-untyped-def]
    assert not window._menus_visible

    window._ribbon.menusRequested.emit()

    assert window._menus_visible
