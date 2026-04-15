"""AnalysisRunner — Qt-aware controller around AnalysisWorker.

Owns the QThread, the worker, and signal forwarding. The Run dialog
talks to this; the dialog never touches QThread directly.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QThread, Signal

from opensees_studio.core import Project
from opensees_studio.services.qt_workers import AnalysisWorker


class AnalysisRunner(QObject):
    """Run an analysis case on a background thread."""

    started = Signal()
    log = Signal(str)
    finished = Signal(object)         # StaticResults / ModalResults / TransientResults
    failed = Signal(str)
    runningChanged = Signal(bool)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._thread: QThread | None = None
        self._worker: AnalysisWorker | None = None
        self._is_running = False

    # ── public API ───────────────────────────────────────────────────
    @property
    def is_running(self) -> bool:
        return self._is_running

    def run(self, project: Project, case: Any, results_dir: Path | None = None) -> None:
        if self._is_running:
            raise RuntimeError("Another analysis is already running.")

        self._thread = QThread(self)
        self._worker = AnalysisWorker(project, case, results_dir=results_dir)
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.started.connect(self._on_started)
        self._worker.log.connect(self.log.emit)
        self._worker.finished.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)

        self._is_running = True
        self.runningChanged.emit(True)
        self._thread.start()

    # ── slots ────────────────────────────────────────────────────────
    def _on_started(self) -> None:
        self.started.emit()

    def _on_finished(self, results: Any) -> None:
        self.finished.emit(results)
        self._teardown()

    def _on_failed(self, traceback_str: str) -> None:
        self.failed.emit(traceback_str)
        self._teardown()

    def _teardown(self) -> None:
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait()
        if self._worker is not None:
            self._worker.deleteLater()
        if self._thread is not None:
            self._thread.deleteLater()
        self._worker = None
        self._thread = None
        self._is_running = False
        self.runningChanged.emit(False)
