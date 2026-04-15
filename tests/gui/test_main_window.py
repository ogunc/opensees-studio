"""Smoke test for the MainWindow.

Marked as ``gui`` so it can be deselected on environments without a display.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyvistaqt")


@pytest.mark.gui
def test_main_window_opens(qtbot) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.views.main_window import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    assert window.isVisible()
    assert window.windowTitle() == "OpenSees Studio"
