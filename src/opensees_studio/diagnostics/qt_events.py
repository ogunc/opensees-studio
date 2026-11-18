"""Qt-side diagnostics: detect UI stalls without touching the event loop.

A heartbeat timer measures the gap between its own ticks. A long action that
does not process events shows up as a gap much larger than the interval; the
performance report then has a ``ui.stall`` event with its duration. The timer is
always installed and is cheap; events are recorded only when the monitor is
enabled.
"""

from __future__ import annotations

import time

from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QApplication

from opensees_studio.diagnostics.performance import perf

#: Heartbeat interval. A stall is a gap above ``_STALL_FACTOR`` intervals.
_INTERVAL_MS = 200
_STALL_FACTOR = 2.5


class _StallWatchdog(QObject):
    def __init__(self, app: QApplication) -> None:
        super().__init__(app)
        self._last = time.perf_counter()
        self._timer = QTimer(self)
        self._timer.setInterval(_INTERVAL_MS)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def _tick(self) -> None:
        now = time.perf_counter()
        gap_ms = (now - self._last) * 1000.0
        self._last = now
        if gap_ms > _INTERVAL_MS * _STALL_FACTOR:
            perf.event("ui.stall", duration_ms=round(gap_ms, 1))


_WATCHDOG: list[_StallWatchdog] = []


def install_stall_watchdog(app: QApplication) -> None:
    """Install the heartbeat once per QApplication (idempotent)."""
    if not _WATCHDOG or _WATCHDOG[0].parent() is not app:
        _WATCHDOG.append(_StallWatchdog(app))


__all__ = ["install_stall_watchdog"]
