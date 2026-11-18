"""Analyze → Check Model Stability, run the way an analysis runs.

The project goes to its pre-run snapshot and the analysis CLI checks it in a
child process (``--check-stability``): building a model is OpenSees work, and
OpenSees can end its process on a bad model. The child prints one ``stability``
line with the report; this object turns it back into a
:class:`~opensees_studio.services.stability.StabilityReport`.

With ``OPENSEES_STUDIO_IN_PROCESS=1`` (debugging) the check runs in this
process instead, like the in-process analysis runner.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, Signal

from opensees_studio.child_cli import analysis_cli_command, is_frozen
from opensees_studio.core import Project
from opensees_studio.core.combinations import model_fingerprint
from opensees_studio.services import engines, write_run_snapshot
from opensees_studio.services.stability import StabilityReport, check_stability
from opensees_studio.viewmodels.analysis_runner import (
    KILL_AFTER_TERMINATE_MS,
    STDERR_TAIL_LINES,
    _hide_child_console,
    in_process_mode,
    is_solver_banner,
)

DEFAULT_STABILITY_TIMEOUT_S = 300.0
"""Soft limit for a check; a native eigenvalue call is never cooperatively interrupted."""


class StabilityChecker(QObject):
    """Check a project for mechanisms in a child process."""

    log = Signal(str)
    progress = Signal(str, str)  # phase, message
    finished = Signal(object)  # StabilityReport
    failed = Signal(str)
    runningChanged = Signal(bool)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._process: QProcess | None = None
        self._stdout = ""
        self._stderr = ""
        self._report: StabilityReport | None = None
        self._error: str | None = None
        self._cancel_requested = False
        self._timed_out = False
        self._timeout_timer: QTimer | None = None
        self._fingerprint = ""

    @property
    def is_running(self) -> bool:
        return self._process is not None

    def check(
        self,
        project: Project,
        project_path: Path | None = None,
        *,
        timeout_s: float | None = DEFAULT_STABILITY_TIMEOUT_S,
    ) -> None:
        """Start the check; ``finished`` or ``failed`` follows."""
        if self._process is not None:
            return
        self._cancel_requested = False
        self._timed_out = False
        self._fingerprint = model_fingerprint(project)
        snapshot = write_run_snapshot(project, project_path)
        if in_process_mode():
            try:
                report = check_stability(
                    project,
                    timeout_s=timeout_s,
                    progress=lambda phase, message: self.progress.emit(phase, message),
                    should_cancel=lambda: self._cancel_requested,
                )
            except Exception as exc:  # the report is the user's answer either way
                self.failed.emit(f"The stability check failed: {exc}")
                return
            self.finished.emit(report)
            return

        self._stdout = self._stderr = ""
        self._report = None
        self._error = None
        process = QProcess(self)
        command = analysis_cli_command()
        process.setProgram(command[0])
        env = QProcessEnvironment.systemEnvironment()
        env.insert("PYTHONUNBUFFERED", "1")
        # Where the solver is, when it is not in this environment (Options → Solver).
        for key, value in engines.child_environment().items():
            env.insert(key, value)
        process.setProcessEnvironment(env)
        arguments = [*command[1:], "--project", str(snapshot), "--check-stability"]
        if timeout_s is not None and timeout_s > 0:
            arguments += ["--stability-timeout", f"{timeout_s:g}"]
        process.setArguments(arguments)
        if is_frozen() and os.name == "nt":
            _hide_child_console(process)
        process.readyReadStandardOutput.connect(self._on_stdout)
        process.readyReadStandardError.connect(self._on_stderr)
        process.finished.connect(self._on_finished)
        process.errorOccurred.connect(self._on_error)
        self._process = process
        if timeout_s is not None and timeout_s > 0:
            self._timeout_timer = QTimer(self)
            self._timeout_timer.setSingleShot(True)
            self._timeout_timer.setInterval(int((timeout_s + 10.0) * 1000))
            self._timeout_timer.timeout.connect(self._on_timeout)
            self._timeout_timer.start()
        self.runningChanged.emit(True)
        self.log.emit("Checking the model's stability ...")
        process.start()

    def cancel(self) -> None:
        """Stop the child process; the UI receives a cancelled report."""
        if self._process is None or self._cancel_requested:
            return
        self._cancel_requested = True
        self.log.emit("Cancelling the stability check ...")
        self._process.terminate()
        QTimer.singleShot(KILL_AFTER_TERMINATE_MS, self._kill_if_alive)

    def _kill_if_alive(self) -> None:
        if self._process is not None:
            self._process.kill()

    def _on_timeout(self) -> None:
        if self._process is None:
            return
        self._cancel_requested = True
        self._timed_out = True
        self.log.emit("The stability check exceeded its time limit; stopping it.")
        self._process.terminate()
        QTimer.singleShot(KILL_AFTER_TERMINATE_MS, self._kill_if_alive)

    def _cancelled_report(self) -> StabilityReport:
        return StabilityReport(
            n_equations=0,
            rank=None,
            completion="cancelled",
            classification="indeterminate",
            method="cancelled",
            backend="opensees",
            count_kind="estimate",
            failure_reason=(
                "the stability check exceeded its time limit"
                if self._timed_out
                else "cancelled by the user"
            ),
            model_fingerprint=self._fingerprint,
        )

    # ── the child ────────────────────────────────────────────────────
    def _on_stdout(self) -> None:
        if self._process is None:
            return
        self._stdout += bytes(self._process.readAllStandardOutput().data()).decode(
            "utf-8", "replace"
        )
        while "\n" in self._stdout:
            line, self._stdout = self._stdout.split("\n", 1)
            self._handle(line.strip())

    def _on_stderr(self) -> None:
        if self._process is not None:
            self._stderr += bytes(self._process.readAllStandardError().data()).decode(
                "utf-8", "replace"
            )

    def _handle(self, line: str) -> None:
        if not line:
            return
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            return
        kind = message.get("type")
        if kind == "stability":
            self._report = StabilityReport.from_dict(message.get("report", {}))
        elif kind == "stability_progress":
            self.progress.emit(str(message.get("phase", "")), str(message.get("message", "")))
        elif kind == "log" and not is_solver_banner(str(message.get("message", ""))):
            self.log.emit(str(message.get("message", "")))
        elif kind == "error":
            self._error = str(message.get("message", ""))

    def _on_error(self, error: QProcess.ProcessError) -> None:
        if error == QProcess.ProcessError.FailedToStart:
            self._finish(None, "The stability check could not start its process.")

    def _on_finished(self, exit_code: int, exit_status: QProcess.ExitStatus) -> None:
        self._on_stdout()
        if self._cancel_requested:
            self._finish(self._cancelled_report(), None)
            return
        if self._report is not None and exit_code == 0:
            self._finish(self._report, None)
            return
        tail = "\n".join(self._stderr.strip().splitlines()[-STDERR_TAIL_LINES:])
        crashed = exit_status == QProcess.ExitStatus.CrashExit
        reason = self._error or (
            "OpenSees ended the process while building the model"
            if crashed or exit_code not in (0, 2, 3)
            else "no report came back"
        )
        text = f"The stability check failed (exit code {exit_code}): {reason}"
        if tail and not self._error:
            text += f"\n\nLast solver output:\n{tail}"
        self._finish(None, text)

    def _finish(self, report: StabilityReport | None, error: str | None) -> None:
        if self._timeout_timer is not None:
            self._timeout_timer.stop()
            self._timeout_timer = None
        process, self._process = self._process, None
        if process is not None:
            process.deleteLater()
        self.runningChanged.emit(False)
        if report is not None:
            self.finished.emit(report)
        else:
            self.failed.emit(error or "The stability check failed.")
