"""Keyboard shortcuts: one command per key, and the help page lists them all.

Qt treats a key bound to two enabled actions as ambiguous and runs neither, so a
duplicate does not pick a winner: it silently breaks both commands.
"""

from __future__ import annotations

from collections import defaultdict

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyvistaqt")

from PySide6.QtGui import QAction, QKeySequence

from opensees_studio.core.help import TOPICS


@pytest.fixture
def window(qtbot):  # type: ignore[no-untyped-def]
    from opensees_studio.views.main_window import MainWindow

    mw = MainWindow()
    qtbot.addWidget(mw)
    yield mw
    mw._help_controller.uninstall()


def _shortcuts(window) -> dict[str, list[str]]:  # type: ignore[no-untyped-def]
    keys: dict[str, list[str]] = defaultdict(list)
    for action in window.findChildren(QAction):
        for sequence in action.shortcuts():
            keys[sequence.toString(QKeySequence.SequenceFormat.PortableText)].append(action.text())
    return keys


@pytest.mark.gui
def test_no_two_actions_share_a_shortcut(window) -> None:
    shared = {key: names for key, names in _shortcuts(window).items() if len(names) > 1}
    assert shared == {}


@pytest.mark.gui
def test_the_shortcuts_page_lists_every_shortcut(window) -> None:
    body = TOPICS["help.shortcuts"].body
    missing = sorted(key for key in _shortcuts(window) if f"**{key}**" not in body)
    assert missing == []
