"""AnalysisRunner: Qt-aware controller that runs a case in a child process.

The Run dialog talks to this; it never touches QProcess or QThread
itself. By default the runner writes the pre-run snapshot, starts
``python -m opensees_studio.run`` with :class:`QProcess`, turns the JSON
line protocol into the signals below and loads the results from the
output directory when the child exits with code 0. A hard exit inside
OpenSees therefore ends the child, not the application.

``OPENSEES_STUDIO_IN_PROCESS=1`` switches to the previous in-process
mode (an :class:`~opensees_studio.services.qt_workers.AnalysisWorker` on
a ``QThread``) for debugging and for tests that need it. Cancel is not
available there: ``ops.analyze`` blocks the worker thread.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import traceback
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QProcess, QThread, QTimer, Signal

from opensees_studio.core import Project
from opensees_studio.services import write_run_snapshot
from opensees_studio.services.qt_workers import AnalysisWorker
from opensees_studio.services.result_store import load_results

IN_PROCESS_ENV = "OPENSEES_STUDIO_IN_PROCESS"
"""Set to ``1`` to run analyses on a thread of the GUI process instead of a child."""

STDERR_TAIL_LINES = 40
KILL_AFTER_TERMINATE_MS = 1500


def in_process_mode() -> bool:
    """True when ``OPENSEES_STUDIO_IN_PROCESS`` asks for the in-process runner."""
    return os.environ.get(IN_PROCESS_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


class AnalysisRunner(QObject):
    """Run an analysis case in a child process (or on a thread in in-process mode)."""

    started = Signal()
    log = Signal(str)
    finished = Signal(object)  # StaticResults / ModalResults / TransientResults / ...
    failed = Signal(str)  # human-readable report: exit code, error, stderr tail
    runningChanged = Signal(bool)
    progress = Signal(int, int)  # completed steps, total steps of the running case
    cancelled = Signal()
    processFailed = Signal(int, str, str)  # exit code, last error line, stderr tail

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._thread: QThread | None = None
        self._worker: AnalysisWorker | None = None
        self._process: QProcess | None = None
        self._is_running = False
        self._cancel_requested = False
        self._stdout_buffer = ""
        self._stderr = ""
        self._last_error: dict[str, str] | None = None
        self._finished_entry: dict[str, Any] | None = None
        self._out_dir: Path | None = None
        self.last_exit_code: int | None = None

    # ── public API ───────────────────────────────────────────────────
    @property
    def is_running(self) -> bool:
        return self._is_running

    @property
    def can_cancel(self) -> bool:
        """True while a child process is running (in-process runs cannot be cancelled)."""
        return self._is_running and self._process is not None

    def run(
        self,
        project: Project,
        case: Any,
        results_dir: Path | None = None,
        project_path: Path | None = None,
    ) -> None:
        """Run ``case`` of ``project``.

        Before anything else the project is written to its pre-run
        snapshot (next to ``project_path``, or in the app data directory
        for a never-saved project), so a solver crash cannot take unsaved
        work with it. The snapshot is also the input of the child process.
        """
        if self._is_running:
            raise RuntimeError("Another analysis is already running.")

        snapshot = write_run_snapshot(project, project_path)
        self.log.emit(f"Snapshot written: {snapshot}")

        if in_process_mode():
            self._run_in_process(project, case, results_dir)
        else:
            self._run_in_child(case, snapshot, results_dir)

    def cancel(self) -> None:
        """Stop the running child process: terminate, then kill after a short timeout."""
        if self._process is None or not self._is_running:
            return
        if self._cancel_requested:
            return
        self._cancel_requested = True
        self.log.emit("Cancelling analysis ...")
        self._process.terminate()
        QTimer.singleShot(KILL_AFTER_TERMINATE_MS, self._kill_if_alive)

    # ── in-process mode ──────────────────────────────────────────────
    def _run_in_process(self, project: Project, case: Any, results_dir: Path | None) -> None:
        self.log.emit("Running in-process (OPENSEES_STUDIO_IN_PROCESS is set).")
        self._thread = QThread(self)
        self._worker = AnalysisWorker(project, case, results_dir=results_dir)
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.started.connect(self._on_started)
        self._worker.log.connect(self.log.emit)
        self._worker.finished.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)

        self._set_running(True)
        self._thread.start()

    # ── child process mode ───────────────────────────────────────────
    def _run_in_child(self, case: Any, snapshot: Path, results_dir: Path | None) -> None:
        out_dir = results_dir or Path(tempfile.mkdtemp(prefix="osstudio_"))
        out_dir.mkdir(parents=True, exist_ok=True)
        # The dialog may pass a modified copy of the case (run-time damping
        # overrides): it travels beside the snapshot, never inside it.
        override = out_dir / f"case_{case.id}.override.json"
        override.write_text(
            json.dumps([case.model_dump(mode="json", by_alias=True)]), encoding="utf-8"
        )

        self._out_dir = out_dir
        self._stdout_buffer = ""
        self._stderr = ""
        self._last_error = None
        self._finished_entry = None
        self._cancel_requested = False
        self.last_exit_code = None

        process = QProcess(self)
        process.setProgram(sys.executable)
        process.setArguments(
            [
                "-m",
                "opensees_studio.run",
                "--project",
                str(snapshot),
                "--cases",
                str(case.id),
                "--out",
                str(out_dir),
                "--case-override",
                str(override),
            ]
        )
        process.readyReadStandardOutput.connect(self._on_stdout)
        process.readyReadStandardError.connect(self._on_stderr)
        process.started.connect(self._on_started)
        process.finished.connect(self._on_process_finished)
        process.errorOccurred.connect(self._on_process_error)
        self._process = process

        self._set_running(True)
        self.log.emit(f"Starting analysis process: {sys.executable} -m opensees_studio.run")
        process.start()

    def _kill_if_alive(self) -> None:
        if self._process is not None and self._process.state() != QProcess.ProcessState.NotRunning:
            self.log.emit("Analysis process did not stop; killing it.")
            self._process.kill()

    def _on_stdout(self) -> None:
        if self._process is None:
            return
        chunk = bytes(self._process.readAllStandardOutput()).decode("utf-8", errors="replace")
        self._stdout_buffer += chunk
        while "\n" in self._stdout_buffer:
            line, self._stdout_buffer = self._stdout_buffer.split("\n", 1)
            self._handle_line(line.strip())

    def _on_stderr(self) -> None:
        if self._process is None:
            return
        self._stderr += bytes(self._process.readAllStandardError()).decode(
            "utf-8", errors="replace"
        )

    def _handle_line(self, line: str) -> None:
        if not line:
            return
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            self.log.emit(line)
            return
        kind = payload.get("type")
        if kind == "log":
            self.log.emit(str(payload.get("message", "")))
        elif kind == "progress":
            self.progress.emit(int(payload.get("step", 0)), int(payload.get("total", 0)))
        elif kind == "case_started":
            pass  # the log line that follows carries the same information
        elif kind == "case_finished":
            self._finished_entry = payload
        elif kind == "error":
            self._last_error = {
                "message": str(payload.get("message", "")),
                "traceback": str(payload.get("traceback", "")),
            }
            self.log.emit(f"Error: {self._last_error['message']}")

    def _stderr_tail(self) -> str:
        lines = self._stderr.splitlines()
        return "\n".join(lines[-STDERR_TAIL_LINES:])

    def _on_process_error(self, error: QProcess.ProcessError) -> None:
        if error == QProcess.ProcessError.FailedToStart and self._process is not None:
            self.last_exit_code = -1
            report = (
                f"The analysis process could not be started: {self._process.errorString()}\n"
                f"Program: {sys.executable}"
            )
            self.processFailed.emit(-1, report, "")
            self._on_failed(report)

    def _on_process_finished(self, exit_code: int, exit_status: QProcess.ExitStatus) -> None:
        if self._process is None:
            return
        self._on_stdout()
        self._on_stderr()
        if self._stdout_buffer.strip():
            self._handle_line(self._stdout_buffer.strip())
            self._stdout_buffer = ""
        crashed = exit_status == QProcess.ExitStatus.CrashExit
        self.last_exit_code = exit_code if not crashed else (exit_code or -2)

        if self._cancel_requested:
            self.log.emit("Analysis cancelled.")
            self.cancelled.emit()
            self._teardown()
            return

        if exit_code == 0 and not crashed:
            try:
                if self._finished_entry is None or self._out_dir is None:
                    raise RuntimeError("The analysis process reported no finished case.")
                results = load_results(self._finished_entry, self._out_dir)
            except Exception:
                self._on_failed(
                    "Results could not be loaded from the analysis output:\n"
                    + traceback.format_exc()
                )
                return
            self._on_finished(results)
            return

        # Non-zero exit or death: report code, last error line and the stderr tail.
        tail = self._stderr_tail()
        status = "crashed" if crashed else f"exited with code {exit_code}"
        parts = [f"The analysis process {status}."]
        if self._last_error is not None:
            parts.append(f"Last error: {self._last_error['message']}")
            if self._last_error["traceback"].strip():
                parts.append(self._last_error["traceback"].rstrip())
        else:
            parts.append(
                "No error line was reported: the process died (hard exit inside OpenSees)."
            )
        parts.append(f"--- stderr (last {STDERR_TAIL_LINES} lines) ---")
        parts.append(tail if tail else "(empty)")
        last_error = self._last_error["message"] if self._last_error is not None else ""
        self.processFailed.emit(self.last_exit_code, last_error, tail)
        self._on_failed("\n".join(parts))

    # ── slots shared by both modes ───────────────────────────────────
    def _on_started(self) -> None:
        self.started.emit()

    def _on_finished(self, results: Any) -> None:
        self.finished.emit(results)
        self._teardown()

    def _on_failed(self, report: str) -> None:
        self.failed.emit(report)
        self._teardown()

    def _set_running(self, running: bool) -> None:
        self._is_running = running
        self.runningChanged.emit(running)

    def _teardown(self) -> None:
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait()
        if self._worker is not None:
            self._worker.deleteLater()
        if self._thread is not None:
            self._thread.deleteLater()
        if self._process is not None:
            if self._process.state() != QProcess.ProcessState.NotRunning:
                self._process.kill()
                self._process.waitForFinished(2000)
            self._process.deleteLater()
        self._worker = None
        self._thread = None
        self._process = None
        self._cancel_requested = False
        self._set_running(False)
