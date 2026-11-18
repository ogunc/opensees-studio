"""The ribbon: every menu command placed once, in workflow order, with its own icon."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QToolButton

from opensees_studio.views.main_window import MainWindow
from opensees_studio.views.ribbon import RIBBON_LAYOUT, build_ribbon_tabs
from opensees_studio.views.ribbon.icons import (
    ICON_DIR,
    command_icon_name,
    has_icon,
    icon_names,
    menu_icon_name,
)
from opensees_studio.views.ribbon.widget import OTHER


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


def _entries() -> list[str]:
    return [
        entry.lstrip("*")
        for _, _, groups in RIBBON_LAYOUT
        for _, entries in groups
        for entry in entries
    ]


def test_the_ribbon_exposes_every_menu_action(window: MainWindow) -> None:
    menu = {id(a) for a in _menu_actions(window)}
    ribbon = {id(a) for a in window._ribbon.actions()}

    assert len(menu) > 200
    assert ribbon == menu


def test_every_menu_command_has_a_place_in_the_layout(window: MainWindow) -> None:
    tabs = build_ribbon_tabs(window)
    other = [g for t in tabs for g in t.groups if g.title == OTHER]
    leftovers = [item.label for g in other for item in g.items]
    assert not leftovers, f"add these to RIBBON_LAYOUT: {leftovers}"


def test_the_layout_places_each_command_once(window: MainWindow) -> None:
    entries = _entries()
    assert len(entries) == len(set(entries)), "a command appears twice in RIBBON_LAYOUT"
    for entry in entries:
        if not entry.startswith("menu:"):
            assert isinstance(getattr(window, entry), QAction), entry


def test_the_tabs_follow_the_modelling_flow(window: MainWindow) -> None:
    labels = [tab.label for tab in build_ribbon_tabs(window)]
    assert labels == [
        "Home",
        "Define",
        "Draw",
        "Select",
        "Assign",
        "Loads",
        "Analyze",
        "Results",
        "Design",
        "View",
        "Help",
    ]


def test_every_button_has_its_own_svg_icon(window: MainWindow) -> None:
    for tab in build_ribbon_tabs(window):
        for group in tab.groups:
            for item in group.items:
                assert has_icon(item.icon), f"{item.label!r} needs {item.icon}.svg"


def test_every_command_action_has_its_icon_in_the_menus_too(window: MainWindow) -> None:
    missing = [
        name
        for name, value in vars(window).items()
        if name.startswith("_act_")
        and isinstance(value, QAction)
        and value.text()
        and not has_icon(command_icon_name(name))
    ]
    assert not missing, f"no SVG for {missing}"
    assert not window._act_run.icon().isNull()


def test_no_two_commands_share_a_picture() -> None:
    seen: dict[str, str] = {}
    for name in icon_names():
        body = (ICON_DIR / f"{name}.svg").read_text(encoding="utf-8")
        assert body.startswith("<svg"), name
        assert body not in seen, f"{name}.svg and {seen.get(body)}.svg are the same picture"
        seen[body] = name


def test_no_icon_is_left_over(window: MainWindow) -> None:
    used = {"more", "menus"}
    used |= {command_icon_name(name) for name in vars(window) if name.startswith("_act_")}
    used |= {
        menu_icon_name(entry.rsplit("/", 1)[1]) for entry in _entries() if entry.startswith("menu:")
    }
    unused = set(icon_names()) - used
    assert not unused, f"icons no command uses: {sorted(unused)}"


def test_primary_commands_get_large_buttons(window: MainWindow) -> None:
    window._ribbon.setCurrentTab("analyze")
    buttons = {
        b.defaultAction(): b for b in window._ribbon.findChildren(QToolButton) if b.defaultAction()
    }
    run = buttons[window._act_run]
    assert run.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonTextUnderIcon
    assert run.iconSize().width() == 32
    run_all = buttons[window._act_run_all]
    assert run_all.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonTextBesideIcon


def test_a_submenu_is_one_drop_down_button(window: MainWindow) -> None:
    drop_downs = [b for b in window._ribbon.findChildren(QToolButton) if b.menu() is not None]
    titles = {b.menu().title().replace("&", "") for b in drop_downs}
    assert {"Import", "Export", "Open Recent", "Language"} <= titles


def test_the_ribbon_is_the_default_and_the_menus_stay_available(window: MainWindow) -> None:
    assert window._act_use_ribbon.isChecked()
    assert not window._menus_visible
    assert not window._ribbon_toolbar.isHidden()

    window._act_use_ribbon.setChecked(False)

    assert window._menus_visible
    assert window._ribbon_toolbar.isHidden()

    window._act_use_ribbon.setChecked(True)
    assert not window._menus_visible
    assert not window._ribbon_toolbar.isHidden()


def test_the_menus_button_toggles_the_menu_bar(window: MainWindow) -> None:
    assert not window._menus_visible
    button = window._ribbon._menus_button
    assert button is not None and not button.isChecked()

    window._ribbon.menusRequested.emit()

    assert window._menus_visible
    assert button.isChecked()

    window._ribbon.menusRequested.emit()

    assert not window._menus_visible
    assert not button.isChecked()
