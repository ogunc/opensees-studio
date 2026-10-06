"""Dialogs that fit the screen and keep their messages in sight.

Every dialog opens inside its screen's available area (the taskbar
excluded): on show its size is clamped to :data:`SCREEN_FRACTION` of that
area and its frame is centred in it. Content taller or wider than that
goes into a :func:`scroll_area`, and warnings, refusals and status lines
live in a :class:`MessageArea` outside the scroll area, so they are
visible without moving or resizing the window.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QRect, Qt, QTimer
from PySide6.QtGui import QGuiApplication, QShowEvent
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QStyle,
    QWidget,
)

from opensees_studio.views.window_bounds import fitted_frame

SCREEN_FRACTION = 0.9
"""Largest share of the available screen area a dialog takes when it opens."""

_LEVEL_STYLES = {
    "info": "color: palette(window-text); background: transparent;",
    "warning": "color: #6b4500; background: #fff3cd; border: 1px solid #e0b252;",
    "error": "color: #8b0000; background: #fde2e1; border: 1px solid #d9534f;",
}


def available_geometry(widget: QWidget) -> QRect:
    """The available area (taskbar excluded) of the screen ``widget`` opens on."""
    parent = widget.parentWidget()
    screen = parent.window().screen() if parent is not None else widget.screen()
    if screen is None:
        screen = QGuiApplication.primaryScreen()
    return screen.availableGeometry()


def fit_to_available_screen(widget: QWidget, fraction: float = SCREEN_FRACTION) -> None:
    """Clamp ``widget`` to ``fraction`` of its screen's available area and centre it there."""
    _fit_on_show(widget, fraction, center=True)


def clamp_window_to_screen(widget: QWidget) -> None:
    """Keep the complete frame on the current screen while preserving its position."""
    _fit_on_show(widget, 1.0, center=False)


def _apply_frame_bounds(widget: QWidget, fraction: float, *, center: bool) -> None:
    x, y, width, height = fitted_frame(
        (widget.width(), widget.height()),
        widget.frameGeometry().getRect(),
        available_geometry(widget).getRect(),
        fraction,
        center=center,
    )
    widget.resize(width, height)
    widget.move(x, y)


class _FitAfterExpose(QObject):
    """One correction after exposure, never a resize/move feedback loop."""

    def __init__(self, widget: QWidget) -> None:
        super().__init__(widget)
        self._pending = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._finish)
        widget.installEventFilter(self)

    def arm(self, fraction: float, *, center: bool) -> None:
        self._timer.stop()
        self._fraction = fraction
        self._center = center
        self._pending = True
        handle = self.parent().windowHandle()
        if handle is not None:
            handle.installEventFilter(self)
            if handle.isExposed():
                self._timer.start(0)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.Hide:
            self._pending = False
            self._timer.stop()
        elif event.type() == QEvent.Type.Expose and self._pending:
            if watched.isExposed():
                widget = self.parent()
                if widget.frameGeometry() != widget.geometry():
                    # The WM has supplied its margins. Apply them in this event:
                    # a zero timer can run after the first paint and measurement.
                    self._timer.stop()
                    self._finish()
                elif not self._timer.isActive():
                    self._timer.start(0)
        return False

    def _finish(self) -> None:
        if self._pending:
            self._pending = False
            widget = self.parent()
            if widget.isVisible():
                _apply_frame_bounds(widget, self._fraction, center=self._center)


def _fit_on_show(widget: QWidget, fraction: float, *, center: bool) -> None:
    helper = widget.findChild(_FitAfterExpose, options=Qt.FindChildOption.FindDirectChildrenOnly)
    if helper is None:
        helper = _FitAfterExpose(widget)
    helper.arm(fraction, center=center)
    _apply_frame_bounds(widget, fraction, center=center)


class FittedDialog(QDialog):
    """A resizable dialog that opens inside the available area of its screen."""

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        if not event.spontaneous():
            fit_to_available_screen(self)


def scroll_area(content: QWidget, *, vertical_only: bool = False) -> QScrollArea:
    """A frameless scroll area around ``content`` that resizes it to its width.

    With ``vertical_only`` the area never scrolls sideways: it is at least as
    wide as the content's minimum width, so form rows are never cut off.
    """
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QFrame.Shape.NoFrame)
    area.setWidget(content)
    if vertical_only:
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        bar = area.style().pixelMetric(QStyle.PixelMetric.PM_ScrollBarExtent)
        area.setMinimumWidth(content.minimumSizeHint().width() + bar)
    return area


class MessageArea(QLabel):
    """An always-visible, word-wrapped line for warnings, refusals and status text."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWordWrap(True)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        self._level = "info"
        self.clear_message()

    @property
    def level(self) -> str:
        return self._level

    def show_message(self, text: str, level: str = "info") -> None:
        """Show ``text`` as ``info``, ``warning`` or ``error``; empty text hides the area."""
        self._level = level
        self.setText(text)
        self.setStyleSheet(f"QLabel {{ {_LEVEL_STYLES[level]} padding: 4px; }}")
        self.setVisible(bool(text))

    def clear_message(self) -> None:
        self.show_message("")
