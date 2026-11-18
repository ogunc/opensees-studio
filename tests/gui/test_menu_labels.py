"""Menu entries follow one punctuation: "…" for a dialog, nothing for a command."""

from __future__ import annotations

import re

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyvistaqt")

from PySide6.QtWidgets import QMenu


@pytest.mark.gui
def test_menu_labels_end_in_an_ellipsis_or_nothing(qtbot) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.views.main_window import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)
    try:
        bad = []
        for menu in window.menuBar().findChildren(QMenu):
            for action in menu.actions():
                label = action.text().split("\t", 1)[0]
                if not label:
                    continue
                if label.endswith((".", "...")) or re.search(r"\((F\d+|Ctrl\+[^)]*)\)$", label):
                    bad.append(label)
        assert bad == [], "use '…' for a dialog, and put keys in the shortcut column"
    finally:
        window._help_controller.uninstall()


@pytest.mark.gui
def test_cancel_stability_check_shows_only_while_a_check_runs(qtbot) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.views.main_window import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)
    try:
        window._vm.new_project(ndm=3, ndf=6)
        window._refresh_action_enablement()
        assert not window._act_cancel_stability.isVisible()
    finally:
        window._help_controller.uninstall()
