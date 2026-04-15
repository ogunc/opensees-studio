"""Qt-aware analysis worker.

Runs ``OpenSeesRunner.run()`` on a background thread so the GUI stays
responsive. Imports PySide6 — keep it isolated from the rest of
``services``; the runner itself remains Qt-free.

Usage from the View layer (Phase 6):

    self._thread = QThread()
    self._worker = AnalysisWorker(project, case)
    self._worker.moveToThread(self._thread)
    self._thread.started.connect(self._worker.run)
    self._worker.finished.connect(self._on_finished)
    self._worker.failed.connect(self._on_failed)
    self._thread.start()
"""

from __future__ import annotations

import traceback
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Signal, Slot

from opensees_studio.core import Project
from opensees_studio.services.opensees_runner import OpenSeesRunner


class AnalysisWorker(QObject):
    """Run an analysis case off the GUI thread."""

    started = Signal()
    log = Signal(str)
    finished = Signal(object)        # emits StaticResults / ModalResults / TransientResults
    failed = Signal(str)             # human-readable error message + traceback

    def __init__(
        self,
        project: Project,
        case: Any,
        results_dir: Path | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._project = project
        self._case = case
        self._results_dir = results_dir

    @Slot()
    def run(self) -> None:
        """Slot to be invoked by ``QThread.started``."""
        self.started.emit()
        try:
            self.log.emit(f"Building model: {len(self._project.nodes)} nodes, "
                          f"{len(self._project.elements)} elements.")
            runner = OpenSeesRunner(self._project)
            self.log.emit(f"Running case '{self._case.name}' ({type(self._case).__name__}) ...")
            results = runner.run(self._case, results_dir=self._results_dir)
            self.log.emit("Analysis complete.")
            self.finished.emit(results)
        except Exception:
            self.failed.emit(traceback.format_exc())
