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
def test_a_run_shows_the_status_strip_not_a_wait_cursor(qtbot) -> None:  # type: ignore[no-untyped-def]
    """The window stays usable during a run; the strip says what runs and offers Cancel."""
    from PySide6.QtWidgets import QApplication

    window = _window(qtbot)
    window.show()
    assert not window._run_status.isVisible()

    window._runner._set_running(True)
    assert QApplication.overrideCursor() is None
    assert window._run_status.isVisible()

    window._runner._case_count = 3
    window._runner._handle_line('{"type": "case_started", "case_id": 2, "case_name": "Dead"}')
    assert window._run_status.text == "Running 'Dead' (1 of 3)"
    window._runner._handle_line('{"type": "progress", "case_id": 2, "step": 4, "total": 10}')
    assert window._run_status._bar.value() == 4

    window._runner._set_running(False)
    assert not window._run_status.isVisible()


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
