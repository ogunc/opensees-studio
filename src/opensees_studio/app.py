"""QApplication bootstrap.

Keep this module thin: build the QApplication, instantiate the MainWindow,
exec the loop. No business logic here.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

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
    _configure_qt()

    app = QApplication(argv)
    app.setApplicationName("OpenSees Studio")
    app.setOrganizationName("OpenSees Studio")
    app.setApplicationDisplayName("OpenSees Studio")

    window = MainWindow()
    window.show()

    return app.exec()
