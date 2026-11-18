"""Runs :func:`~opensees_studio.services.engine_install.install_opensees` off the GUI thread.

A download of tens of megabytes must not freeze the window, and the user must be
able to stop it. The worker reports progress and its outcome through signals;
:meth:`cancel` makes the installer stop at its next chunk and remove what it
had unpacked.
"""

from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal

from opensees_studio.services.engine_install import (
    InstallCancelledError,
    InstallError,
    install_opensees,
)


class _Worker(QThread):
    progressed = Signal(int, int)  # bytes so far, total
    installed = Signal(object)  # engines.SolverSettings
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, root: Path | None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._root = root
        self._stop = threading.Event()

    def cancel(self) -> None:
        self._stop.set()

    def run(self) -> None:
        try:
            settings = install_opensees(
                self._root,
                progress=lambda done, total: self.progressed.emit(done, total),
                cancelled=self._stop.is_set,
            )
        except InstallCancelledError:
            self.cancelled.emit()
        except InstallError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:
            self.failed.emit(f"The installation failed: {exc}")
        else:
            self.installed.emit(settings)


class EngineInstaller(QObject):
    """Starts one download at a time and relays what happens."""

    progressed = Signal(int, int)
    installed = Signal(object)  # SolverSettings
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, parent: QObject | None = None, *, root: Path | None = None) -> None:
        super().__init__(parent)
        self._root = root
        self._worker: _Worker | None = None

    @property
    def is_running(self) -> bool:
        return self._worker is not None and self._worker.isRunning()

    def start(self) -> None:
        if self.is_running:
            return
        worker = _Worker(self._root, self)
        worker.progressed.connect(self.progressed)
        worker.installed.connect(self.installed)
        worker.failed.connect(self.failed)
        worker.cancelled.connect(self.cancelled)
        self._worker = worker
        worker.start()

    def cancel(self) -> None:
        if self._worker is not None:
            self._worker.cancel()

    def wait(self, ms: int = 60_000) -> bool:
        """Block until the download ends (tests, and closing the dialog)."""
        return self._worker.wait(ms) if self._worker is not None else True
