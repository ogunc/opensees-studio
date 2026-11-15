"""The window remembers its panel layout; View → Panels and Reset Window Layout."""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QDockWidget

pytestmark = pytest.mark.gui


def _dock(window, name: str) -> QDockWidget:
    dock = window.findChild(QDockWidget, name)
    assert dock is not None, name
    return dock


def _open(qtbot):
    from opensees_studio.views.main_window import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)
    return window


def test_a_closed_panel_stays_closed_in_the_next_session(qtbot) -> None:
    window = _open(qtbot)
    _dock(window, "propertiesDock").close()
    window.close()  # saves the session state

    again = _open(qtbot)
    try:
        assert not _dock(again, "propertiesDock").isVisible()
        assert _dock(again, "modelExplorerDock").isVisible()
        # Reset brings it back, and the next session keeps it.
        again._act_reset_layout.trigger()
        assert _dock(again, "propertiesDock").isVisible()
    finally:
        again.close()
    third = _open(qtbot)
    try:
        assert _dock(third, "propertiesDock").isVisible()
    finally:
        third.close()


def test_view_panels_lists_every_permanent_panel(qtbot) -> None:
    window = _open(qtbot)
    try:
        view = next(m for m in window.menuBar().actions() if m.text() == "&View").menu()
        panels = next(a for a in view.actions() if a.text() == "&Panels").menu()
        assert [a.text() for a in panels.actions()] == [
            "Model Explorer",
            "Properties",
            "Console",
            "Results",
            "Reactions",
        ]
        console = _dock(window, "consoleDock")
        panels.actions()[2].trigger()
        assert not console.isVisible()
        panels.actions()[2].trigger()
        assert console.isVisible()
    finally:
        window.close()


def test_a_layout_from_another_version_is_ignored(qtbot) -> None:
    from PySide6.QtCore import QSettings

    window = _open(qtbot)
    _dock(window, "consoleDock").close()
    stale = window.saveState(window.LAYOUT_VERSION + 1)
    window.close()
    QSettings().setValue("window/state", stale)

    again = _open(qtbot)
    try:
        assert _dock(again, "consoleDock").isVisible()
    finally:
        again.close()
