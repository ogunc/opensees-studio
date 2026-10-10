"""F1: the help opens on the topic of whatever is on screen.

The interesting case is the one the menu bar creates: with a menu open the popup
owns the keyboard, so the key is caught by an application-wide event filter and
the topic is read from the item the cursor is on. The rest checks that the
contents page, the cross-reference links and the filter work, and that no menu
action is left without a page.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyvistaqt")

from PySide6.QtCore import QEvent, QPoint, Qt, QUrl
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication, QMenu

from opensees_studio.core.help import ACTION_TOPICS, TOPICS
from opensees_studio.views.help_window import HelpController, HelpWindow, topic_of


@pytest.fixture
def window(qtbot):  # type: ignore[no-untyped-def]
    from opensees_studio.views.main_window import MainWindow

    mw = MainWindow()
    qtbot.addWidget(mw)
    mw._vm.new_project(ndm=3, ndf=6)
    yield mw
    mw._help_controller.uninstall()


def _menu_of(window, attribute: str) -> QMenu:  # type: ignore[no-untyped-def]
    """The menu an action lives in."""
    action = getattr(window, attribute)
    for menu in window.findChildren(QMenu):
        if action in menu.actions():
            return menu
    raise AssertionError(f"{attribute} is not in any menu")


# ──────────────────────────── F1 ────────────────────────────
@pytest.mark.gui
def test_f1_with_a_menu_open_shows_a_topic_of_that_menu(qtbot, window) -> None:
    """The case the whole design is for: a deployed menu.

    Which *entry* of the menu is highlighted is Qt's business and the offscreen
    platform does not track it, so what is checked here is the wiring: the open
    popup is found, its entries are read and the page that comes up is one of
    them (the first one, on a platform with no highlight). The precedence itself
    is pinned in ``tests/unit/test_help.py``.
    """
    menu = _menu_of(window, "_act_replicate")
    menu.popup(QPoint(10, 10))
    qtbot.wait(20)

    assert QApplication.activePopupWidget() is menu
    window._help_controller.open_help()
    qtbot.wait(20)

    help_window = window._help_controller.help_window()
    topics_of_menu = {
        action.property("helpTopic") for action in menu.actions() if not action.isSeparator()
    }
    assert help_window.topic_id() in topics_of_menu
    assert help_window.topic_id() == "edit.undo"  # the menu's first entry

    menu.close()


@pytest.mark.gui
def test_f1_with_nothing_open_shows_the_contents(qtbot, window) -> None:
    window._help_controller.open_help()
    qtbot.wait(20)

    assert window._help_controller.help_window().topic_id() == "index"


@pytest.mark.gui
def test_the_key_itself_is_intercepted(qtbot, window) -> None:
    """The filter answers F1, so no widget has to know about the help."""
    event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_F1, Qt.KeyboardModifier.NoModifier)

    handled = QApplication.sendEvent(window, event)

    assert handled  # the application filter consumed it
    assert window._help_controller.help_window().isVisible()
    assert window._help_controller.help_window().topic_id() == "index"


@pytest.mark.gui
def test_f1_inside_a_dialog_opens_that_dialog_page(qtbot, window) -> None:
    """A dialog that declares its page gets it, instead of the window's topic."""
    from opensees_studio.core.help import TOPIC_PROPERTY
    from opensees_studio.views.dialogs import FrameWizard

    wizard = FrameWizard([], ndm=3, ndf=6)
    qtbot.addWidget(wizard)
    assert topic_of(wizard) == "define.portal_frame"

    # On top of everything (application modal), the dialog wins.
    wizard.setWindowModality(Qt.WindowModality.ApplicationModal)
    wizard.show()
    qtbot.wait(20)
    assert QApplication.activeModalWidget() is wizard
    window._help_controller.open_help()
    qtbot.wait(20)

    assert window._help_controller.help_window().topic_id() == "define.portal_frame"
    wizard.close()
    assert TOPIC_PROPERTY  # the property name lives with the content, not the UI


@pytest.mark.gui
def test_the_help_window_is_reused(qtbot, window) -> None:
    window._help_controller.open_help("edit.move")
    first = window._help_controller.help_window()
    window._help_controller.open_help("edit.mirror")

    assert window._help_controller.help_window() is first
    assert first.topic_id() == "edit.mirror"


# ──────────────────────────── the window ────────────────────────────
@pytest.mark.gui
def test_the_window_lists_the_topics_by_group(qtbot) -> None:
    help_window = HelpWindow()
    qtbot.addWidget(help_window)

    groups = [
        help_window._contents.topLevelItem(index).text(0)
        for index in range(help_window._contents.topLevelItemCount())
    ]
    assert groups[0] == "Getting started"
    assert {"File", "Edit and tools", "Define", "Analyze", "Mechanics"} <= set(groups)


@pytest.mark.gui
def test_choosing_in_the_contents_shows_the_page(qtbot) -> None:
    help_window = HelpWindow()
    qtbot.addWidget(help_window)

    help_window.show_topic("mechanics.isolators")

    assert help_window.topic_id() == "mechanics.isolators"
    assert "bilinear" in help_window._page.toPlainText().lower()


@pytest.mark.gui
def test_a_cross_reference_switches_the_page(qtbot) -> None:
    help_window = HelpWindow()
    qtbot.addWidget(help_window)

    help_window._on_anchor(QUrl("topic:mechanics.static"))

    assert help_window.topic_id() == "mechanics.static"
    assert help_window._page.toPlainText().startswith("Static analysis")


@pytest.mark.gui
def test_the_filter_keeps_the_matching_topics(qtbot) -> None:
    help_window = HelpWindow()
    qtbot.addWidget(help_window)

    help_window._filter.setText("pushover")

    visible = [
        child.text(0)
        for parent in help_window._groups()
        for child in help_window._children(parent)
        if not child.isHidden()
    ]
    assert visible, "the filter hid everything"
    assert any("Pushover" in title for title in visible)
    assert len(visible) < len(TOPICS)


# ──────────────────────────── coverage ────────────────────────────
@pytest.mark.gui
def test_every_menu_action_declares_a_page_that_exists(qtbot) -> None:
    """A new action without help fails here instead of opening nothing."""
    from opensees_studio.views.main_window import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)
    try:
        actions = {name for name in vars(window) if name.startswith("_act_")}
        assert sorted(actions - set(ACTION_TOPICS)) == [], "acciones sin entrada en ACTION_TOPICS"
        assert sorted(set(ACTION_TOPICS) - actions) == [], (
            "ACTION_TOPICS apunta a acciones que no existen"
        )

        for name in sorted(actions):
            topic_id = getattr(window, name).property("helpTopic")
            assert topic_id, f"{name} no declara página"
            assert topic_id in TOPICS, f"{name} apunta a {topic_id}, que no existe"
    finally:
        window.close()


@pytest.mark.gui
def test_a_help_controller_replaces_the_previous_one(qtbot, window) -> None:
    """Two windows must not both answer F1."""
    from opensees_studio.views.main_window import MainWindow

    other = MainWindow()
    qtbot.addWidget(other)
    try:
        assert HelpController._current() is other._help_controller
        window._help_controller.install()  # taking it back
        assert HelpController._current() is window._help_controller
    finally:
        other._help_controller.uninstall()
