"""Options → Keyboard Shortcuts → SAP2000: F6 deformed shape, F7 force diagram."""

from __future__ import annotations

from collections import Counter

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyvistaqt")

from PySide6.QtCore import QSettings
from PySide6.QtGui import QAction, QKeySequence

from opensees_studio.core.shortcut_profiles import SETTINGS_KEY

pytestmark = pytest.mark.gui


def _key(action: QAction) -> str:
    return action.shortcut().toString(QKeySequence.SequenceFormat.PortableText)


def _shared(window) -> list[str]:  # type: ignore[no-untyped-def]
    keys = Counter(
        sequence.toString(QKeySequence.SequenceFormat.PortableText)
        for action in window.findChildren(QAction)
        for sequence in action.shortcuts()
    )
    return [key for key, count in keys.items() if count > 1]


def test_the_sap2000_profile_moves_f6_and_f7_and_is_remembered(qtbot) -> None:
    from opensees_studio.views.main_window import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)
    try:
        assert _key(window._act_check_model) == "F6"
        assert _key(window._act_tool_measure) == "F7"
        window._shortcut_profile_actions["sap2000"].trigger()
        assert _key(window._act_show_deformed) == "F6"
        assert _key(window._act_show_force_diagram) == "F7"
        assert _key(window._act_run) == "F5"
        assert _key(window._act_table_editing) == "Ctrl+T"
        assert _key(window._act_check_model) == "" and _key(window._act_tool_measure) == ""
        assert _shared(window) == []
        assert QSettings().value(SETTINGS_KEY) == "sap2000"

        second = MainWindow()
        qtbot.addWidget(second)
        try:
            assert second._shortcut_profile_actions["sap2000"].isChecked()
            assert _key(second._act_show_deformed) == "F6"
        finally:
            second._help_controller.uninstall()

        window._shortcut_profile_actions["default"].trigger()
        assert _key(window._act_check_model) == "F6"
        assert _key(window._act_show_deformed) == ""
        assert _shared(window) == []
    finally:
        QSettings().remove(SETTINGS_KEY)
        window._help_controller.uninstall()
