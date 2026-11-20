"""Start-up splash: the logo, the version and what is loading.

The interface pulls in VTK, PyVista, Matplotlib and pyqtgraph before the window
can exist, which takes seconds on a warm disk and much longer on a cold one.
:func:`show_splash` puts the logo on screen right after the ``QApplication`` is
built, before any of that is imported, so a double-click answers at once.

Import only Qt from here: the module is loaded before the heavy libraries on
purpose. The logo carries its own dark panel, so it reads the same on the light
and the dark theme. The analysis and batch command lines never reach this
module (``__main__`` dispatches them first).
"""

from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QByteArray, QRectF, QSettings, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication, QSplashScreen, QWidget

from opensees_studio import __version__

#: The wordmark, shipped with the package (and the frozen bundle).
LOGO = Path(__file__).resolve().parents[1] / "data" / "logo.svg"

#: Same key as ``views.i18n.SETTINGS_KEY`` (not imported: see :func:`translated`).
LANGUAGE_KEY = "interface/language"

#: Logical size of the splash; the logo's 4:1 panel plus a strip for the stage.
_WIDTH = 600
_LOGO_HEIGHT = 150
_STRIP = 34

#: Colours of the logo's panel, so the strip under it continues it.
_PANEL = "#0F1620"
_TEXT = "#C9D4E5"
_MUTED = "#8FA2BF"
_ACCENT = "#4F92E8"

#: The stages :class:`StartupSplash` announces, in order.
STAGES = (
    "Loading the graphics engine…",
    "Building the interface…",
    "Opening the window…",
)


def stored_language() -> str:
    """The interface language the user picked (Options → Language)."""
    return str(QSettings().value(LANGUAGE_KEY, "en") or "en")


def translated(stage: str) -> str:
    """``stage`` in the stored language.

    Read straight from the catalog file: :mod:`opensees_studio.core.i18n` would
    import the whole ``core`` package first, seconds before the splash could show.
    The catalog keys drop the trailing ``…``, as :func:`core.i18n.translate` does.
    """
    language = stored_language()
    path = LOGO.parent / "i18n" / f"{language}.json"
    if language == "en" or not path.is_file():
        return stage
    try:
        table = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return stage
    body = stage.removesuffix("…")
    found = table.get(body)
    return stage if found is None else found + stage[len(body) :]


def _pixmap(ratio: float) -> QPixmap:
    pixmap = QPixmap(int(_WIDTH * ratio), int((_LOGO_HEIGHT + _STRIP) * ratio))
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(QColor(_PANEL))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    if LOGO.is_file():
        renderer = QSvgRenderer(QByteArray(LOGO.read_bytes()))
        renderer.render(painter, QRectF(0, 0, _WIDTH, _LOGO_HEIGHT))
    painter.setPen(QColor(_MUTED))
    font = QFont(painter.font())
    font.setPointSizeF(9)
    painter.setFont(font)
    painter.drawText(
        QRectF(0, 0, _WIDTH - 16, _LOGO_HEIGHT - 10),
        int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom),
        f"v{__version__}",
    )
    painter.end()
    return pixmap


class StartupSplash(QSplashScreen):
    """The splash, with a stage line and a thin progress bar under the logo."""

    def __init__(self) -> None:
        screen = QApplication.primaryScreen()
        ratio = screen.devicePixelRatio() if screen is not None else 1.0
        super().__init__(_pixmap(ratio))
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self._stage = ""
        self._fraction = 0.0

    @property
    def stage(self) -> str:
        return self._stage

    def advance(self, stage: str, fraction: float) -> None:
        """Show ``stage`` (translated) with the bar at ``fraction`` (0 to 1), repainted now."""
        self._stage = translated(stage)
        self._fraction = max(0.0, min(1.0, fraction))
        self.repaint()
        QApplication.processEvents()

    def drawContents(self, painter: QPainter) -> None:
        top = _LOGO_HEIGHT
        painter.setPen(QColor(_TEXT))
        painter.drawText(
            QRectF(16, top, _WIDTH - 32, _STRIP - 4),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            self._stage,
        )
        bar = QRectF(0, top + _STRIP - 3, _WIDTH * self._fraction, 3)
        painter.fillRect(bar, QColor(_ACCENT))

    def finish_on(self, window: QWidget) -> None:
        """Close once ``window`` is shown."""
        self.finish(window)


def show_splash() -> StartupSplash:
    """Build, show and paint the splash at once."""
    splash = StartupSplash()
    splash.show()
    splash.advance(STAGES[0], 0.1)
    return splash
