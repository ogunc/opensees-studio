"""GUI tests for secondary view windows and the startup menu gate."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyvistaqt")


def _window(qtbot):  # type: ignore[no-untyped-def]
    from opensees_studio.views.main_window import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)
    return window


@pytest.mark.gui
def test_startup_leaves_only_file_and_help_enabled(qtbot) -> None:  # type: ignore[no-untyped-def]
    """Requirement: nothing but File and Help before a project exists."""
    window = _window(qtbot)

    assert window._vm.project is None
    assert window._menus["file"].isEnabled()
    assert window._menus["help"].isEnabled()
    for role in ("edit", "select", "define", "assign", "analyze", "display", "view", "options"):
        assert not window._menus[role].isEnabled(), f"{role} should be disabled at startup"


@pytest.mark.gui
def test_a_second_window_shares_the_selection(qtbot) -> None:  # type: ignore[no-untyped-def]
    window = _window(qtbot)

    window._on_new_view_window()

    assert len(window._view_windows) == 1
    view = window._view_windows[0]
    qtbot.addWidget(view)
    assert view.canvas.selection is window._main_canvas.selection

    window._main_canvas.selection.select_node(7)
    assert view.canvas.selection.nodes == frozenset({7})
    # The new window took over the menus.
    assert window._canvas is view.canvas
    assert window._act_close_view.isEnabled()


@pytest.mark.gui
def test_closing_a_view_returns_the_menus_to_the_main_canvas(qtbot) -> None:  # type: ignore[no-untyped-def]
    window = _window(qtbot)
    window._on_new_view_window()
    view = window._view_windows[0]
    qtbot.addWidget(view)

    view.close()

    assert window._view_windows == []
    assert window._canvas is window._main_canvas
    assert not window._act_close_view.isEnabled()


@pytest.mark.gui
def test_each_viewport_keeps_its_own_settings(qtbot) -> None:  # type: ignore[no-untyped-def]
    """Requirement: two windows may show the model differently."""
    window = _window(qtbot)
    window._on_new_view_window()
    view = window._view_windows[0]
    qtbot.addWidget(view)

    window._apply_view_settings(show_nodes=False)

    assert view.canvas.view_settings.show_nodes is False
    assert window._main_canvas.view_settings.show_nodes is True
    assert window._act_vis_nodes.isChecked() is False


@pytest.mark.gui
def test_closing_the_main_window_closes_its_views(qtbot) -> None:  # type: ignore[no-untyped-def]
    window = _window(qtbot)
    window._on_new_view_window()
    view = window._view_windows[0]
    qtbot.addWidget(view)

    window.close()

    assert window._view_windows == []
