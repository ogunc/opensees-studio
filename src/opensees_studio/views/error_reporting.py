"""Turn an unhandled exception in a Qt slot into a report instead of an exit.

PySide6 hands an exception raised inside a slot to ``sys.excepthook``; with the
default hook the traceback is printed and the interpreter unwinds the event
loop, so the process dies with whatever the user had not saved. That is how the
application was lost twice in one session — once on a force diagram over a
shell, once on a failure report that had already been closed — and neither
raised anything the user could act on.

The hook installed here keeps the window alive and puts the traceback where it
can be read: the Console dock (with the status bar pointing at it) and a
non-modal dialog. The full traceback also still goes to stderr, which is what
the frozen bundle's launcher log captures.

Only the GUI installs it. The analysis child must keep the default behaviour:
it reports errors as JSON on stdout and exits with a code the parent parses.
"""

from __future__ import annotations

import sys
import traceback
from types import TracebackType
from typing import Any

_PREVIOUS: Any = None


def _console_window() -> Any:
    """The main window to report into, or None when there is no GUI yet."""
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if not isinstance(app, QApplication):  # a bare QCoreApplication has no windows
        return None
    for widget in app.topLevelWidgets():
        if hasattr(widget, "report_unexpected_error"):
            return widget
    return None


def hook(exc_type: type[BaseException], exc: BaseException, tb: TracebackType | None) -> None:
    """Log the failure and keep running. This is ``sys.excepthook`` while the GUI is up."""
    text = "".join(traceback.format_exception(exc_type, exc, tb))
    sys.stderr.write(text)
    sys.stderr.flush()
    window = _console_window()
    if window is None:
        return
    try:
        window.report_unexpected_error(text)
    except Exception:  # pragma: no cover - the reporter must never raise
        traceback.print_exc()


def install() -> None:
    """Install :func:`hook`, remembering what was there before."""
    global _PREVIOUS
    _PREVIOUS = sys.excepthook
    sys.excepthook = hook


def uninstall() -> None:
    """Restore the hook :func:`install` replaced (tests)."""
    global _PREVIOUS
    if _PREVIOUS is not None:
        sys.excepthook = _PREVIOUS
        _PREVIOUS = None
