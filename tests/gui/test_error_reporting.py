"""Interface errors are reported, not fatal.

Two failures from one session, both of which closed the application with the
user's work in it: a force diagram that unpacked a shell's four nodes, and a
failure report touched after Qt had deleted it. The first is fixed where it was
raised; this module covers the net under both — an unhandled exception in a Qt
slot now reaches the Console dock and the event loop keeps running.

The event-loop check runs in a subprocess on purpose: if the net ever regresses,
the test fails instead of taking the whole suite down with it.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyvistaqt")

import shiboken6
from PySide6.QtWidgets import QDialog, QMessageBox

from opensees_studio.views import error_reporting

ROOT = Path(__file__).resolve().parents[2]


def _window(qtbot):  # type: ignore[no-untyped-def]
    from opensees_studio.views.main_window import MainWindow

    mw = MainWindow()
    qtbot.addWidget(mw)
    mw._vm.new_project(ndm=3, ndf=6)
    return mw


# ──────────────── the report that had already been deleted ────────────────
@pytest.mark.gui
def test_a_closed_failure_report_does_not_break_the_run_teardown(qtbot) -> None:  # type: ignore[no-untyped-def]
    """`WA_DeleteOnClose` destroys the box; the window must not touch it after."""
    mw = _window(qtbot)
    run_dialog = QDialog(mw)
    box = QMessageBox(run_dialog)
    mw._analysis_error_box = box

    shiboken6.delete(box)  # exactly what closing it does
    with pytest.raises(RuntimeError):
        box.parent()  # the wrapper is now dangling: this is what used to raise

    mw._keep_failure_report_alive(run_dialog)  # must not raise

    assert mw._analysis_error_box is None  # and the stale reference is dropped


@pytest.mark.gui
def test_an_unread_failure_report_is_kept_alive(qtbot) -> None:  # type: ignore[no-untyped-def]
    mw = _window(qtbot)
    run_dialog = QDialog(mw)
    box = QMessageBox(run_dialog)
    box.setText("Analysis failed")
    mw._analysis_error_box = box

    mw._keep_failure_report_alive(run_dialog)

    assert box.parent() is mw
    assert box.isVisible()


@pytest.mark.gui
def test_closing_the_report_forgets_it(qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """The real wiring: a failure creates the box, closing it drops the reference."""
    mw = _window(qtbot)
    monkeypatch.setattr(QMessageBox, "show", lambda self: None)  # no window needed

    mw._on_analysis_failed("exit code 3\nstderr tail")
    box = mw._analysis_error_box
    assert box is not None
    assert box.text().startswith("Analysis failed")  # no run, so no exit code
    assert "stderr tail" in box.detailedText()

    box.finished.emit(0)  # what the OK button does

    assert mw._analysis_error_box is None


# ──────────────── the safety net ────────────────
@pytest.mark.gui
def test_an_unhandled_error_reaches_the_console(qtbot) -> None:  # type: ignore[no-untyped-def]
    mw = _window(qtbot)

    mw.report_unexpected_error("Traceback (most recent call last):\nValueError: boom")

    assert "ValueError: boom" in mw._console.toPlainText()
    assert "Unexpected error" in mw.statusBar().currentMessage()


def test_the_hook_writes_to_stderr_and_reports(capsys: pytest.CaptureFixture[str]) -> None:
    """No window yet: the traceback still has to reach stderr."""
    try:
        raise ValueError("hook check")
    except ValueError:
        error_reporting.hook(*sys.exc_info())

    assert "ValueError: hook check" in capsys.readouterr().err


def test_install_and_uninstall_restore_the_previous_hook() -> None:
    previous = sys.excepthook
    try:
        error_reporting.install()
        assert sys.excepthook is error_reporting.hook
        error_reporting.uninstall()
        assert sys.excepthook is previous
    finally:
        sys.excepthook = previous


def test_a_slot_exception_reaches_the_window_and_leaves_it_running(tmp_path: Path) -> None:
    """The net end to end, in a child process.

    PySide6 hands a slot's exception to ``sys.excepthook``. The default hook
    only prints it — this application's puts it in the Console dock and keeps
    the window alive, and that is what the child checks: the traceback is in the
    console *and* the window is still there to be asked. Out of process so a
    regression fails the test instead of the suite.
    """
    script = tmp_path / "slot_error.py"
    script.write_text(
        textwrap.dedent(
            """
            import sys
            from PySide6.QtCore import QTimer
            from PySide6.QtWidgets import QApplication

            from opensees_studio.views.error_reporting import install
            from opensees_studio.views.main_window import MainWindow

            app = QApplication([])
            install()
            window = MainWindow()
            window.show()
            state = {"reported": False, "closed": False}

            def boom():
                raise ValueError("from a slot")

            def check():
                state["reported"] = "ValueError: from a slot" in window._console.toPlainText()
                state["closed"] = window.isVisible()
                print("REPORTED" if state["reported"] else "MISSING")
                print("STILL-OPEN" if state["closed"] else "GONE")
                app.quit()

            QTimer.singleShot(0, boom)
            QTimer.singleShot(2000, check)
            app.exec()
            sys.exit(0 if state["reported"] and state["closed"] else 1)
            """
        ),
        encoding="utf-8",
    )
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "PYTHONPATH": str(ROOT / "src")}
    proc = subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
        timeout=180,
        env=env,
        cwd=ROOT,
    )

    assert proc.returncode == 0, proc.stderr[-2000:]
    assert "REPORTED" in proc.stdout and "STILL-OPEN" in proc.stdout
    assert "ValueError: from a slot" in proc.stderr  # still reported to stderr too
