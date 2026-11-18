"""The wait cursor while the application works."""

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
def test_a_run_turns_the_wait_cursor_on_and_off(qtbot) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QApplication

    window = _window(qtbot)
    assert QApplication.overrideCursor() is None

    window._runner._set_running(True)
    assert QApplication.overrideCursor() is not None

    window._runner._set_running(False)
    assert QApplication.overrideCursor() is None


@pytest.mark.gui
def test_nested_busy_sections_restore_once(qtbot) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QApplication

    window = _window(qtbot)

    with window._busy("outer"):
        assert QApplication.overrideCursor() is not None
        with window._busy("inner"):
            assert window._busy_depth == 2
        assert QApplication.overrideCursor() is not None, "still busy while one level remains"

    assert QApplication.overrideCursor() is None


@pytest.mark.gui
def test_a_failing_block_still_restores_the_cursor(qtbot) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QApplication

    window = _window(qtbot)
    failure: RuntimeError | None = None

    try:
        with window._busy("boom"):
            raise RuntimeError("boom")
    except RuntimeError as exc:  # the block failed: the cursor must still come back
        failure = exc

    assert failure is not None
    assert QApplication.overrideCursor() is None
    assert window._busy_depth == 0
