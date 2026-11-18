"""QApplication bootstrap.

Keep this module thin: build the QApplication, instantiate the MainWindow,
exec the loop. No business logic here.
"""

from __future__ import annotations

from PySide6.QtCore import QLocale, Qt
from PySide6.QtWidgets import QApplication

from opensees_studio.platform_env import prefer_xwayland_on_wayland
from opensees_studio.views.main_window import MainWindow


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

    # A wait cursor while the window builds and draws its first frame: a large
    # model takes a moment before the interface answers, and the user should see
    # that something is happening rather than a blank screen.
    QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
    try:
        window = MainWindow()
        window.show()
        QApplication.processEvents()
    finally:
        QApplication.restoreOverrideCursor()

    return app.exec()
