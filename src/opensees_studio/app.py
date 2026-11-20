"""QApplication bootstrap.

Keep this module thin: build the QApplication, instantiate the MainWindow,
exec the loop. No business logic here.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QLocale, Qt
from PySide6.QtWidgets import QApplication, QWidget

from opensees_studio.platform_env import prefer_xwayland_on_wayland

# `views.main_window` (and with it VTK, PyVista, Matplotlib, pyqtgraph) is
# imported inside `run`, after the splash is on screen: importing it here would
# keep the user looking at nothing for the seconds it takes.


def _configure_qt() -> None:
    """Apply Qt-wide attributes that must be set before QApplication exists."""
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )


def run(argv: list[str]) -> int:
    """Build the Qt application and run the event loop.

    Args:
        argv: Process argument vector, typically ``sys.argv``.

    Returns:
        The Qt exit code.
    """
    # Before QApplication exists: pick a platform plugin that delivers mouse
    # events to the VTK canvas (see `platform_env.prefer_xwayland_on_wayland`).
    prefer_xwayland_on_wayland()

    _configure_qt()

    # Force the C locale app-wide so every QDoubleSpinBox parses "." as
    # the decimal separator — keeps copy/paste from OpenSees Tcl scripts
    # (which always use ".") working on Turkish / European Windows where
    # the system locale expects "," and would otherwise reject "-0.004".
    QLocale.setDefault(QLocale(QLocale.Language.C))

    app = QApplication(argv)
    app.setApplicationName("OpenSees Studio")
    app.setOrganizationName("OpenSees Studio")

    # The splash goes up first, before the heavy imports (the `core` package,
    # VTK, PyVista...), so a double-click answers at once; it closes when the
    # window shows. A wait cursor stays while the window builds.
    from opensees_studio.views.splash import STAGES, show_splash

    splash = show_splash()
    QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
    try:
        window = _build_window(app, splash, STAGES)
    finally:
        splash.close()
        QApplication.restoreOverrideCursor()
    exit_code = app.exec()  # `window` stays referenced until the loop ends
    del window
    return exit_code


def _build_window(app: QApplication, splash: Any, stages: tuple[str, ...]) -> QWidget:
    """Everything from the splash to the shown window, the stages announced."""
    # The heartbeat only records when the opt-in monitor is enabled, but it has
    # to exist before a long action starts so that action's stall is visible.
    from opensees_studio.diagnostics.qt_events import install_stall_watchdog

    install_stall_watchdog(app)
    # Qt appends the display name to every window title, and the title already
    # carries the name and the version: leaving it empty stops the title from
    # reading "OpenSees Studio v0.0.18 — OpenSees Studio".
    app.setApplicationDisplayName("")

    # An unhandled exception in a slot would otherwise unwind the event loop and
    # kill the process with the user's unsaved work in it. The analysis child
    # does NOT install this: it reports errors as JSON and exits with a code.
    from opensees_studio.views.error_reporting import install

    install()

    from opensees_studio.views.i18n import install as install_translator

    install_translator(app)
    splash.advance(stages[0], 0.25)

    from opensees_studio.views.main_window import MainWindow

    splash.advance(stages[1], 0.7)
    window = MainWindow()
    splash.advance(stages[2], 0.95)
    window.show()
    splash.finish_on(window)
    QApplication.processEvents()
    return window
