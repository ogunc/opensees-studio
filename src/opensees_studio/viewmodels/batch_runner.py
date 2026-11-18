"""BatchRunner: runs planned batch jobs in analysis children, a few at a time.

File → Run Batch… talks to this. Each job is one project file solved by the
analysis CLI in its own :class:`QProcess`, started the way
:class:`~opensees_studio.viewmodels.analysis_runner.AnalysisRunner` starts a
single run (the program from ``child_cli.analysis_cli_command()``, the engine's
variables from ``engines.child_environment()``). The child itself writes the
result store and the results database (see :mod:`opensees_studio.services.batch`),
so nothing heavy happens on the GUI thread.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, Signal

from opensees_studio.child_cli import analysis_cli_command, is_frozen
from opensees_studio.services import batch, engines
from opensees_studio.services.batch import BatchJob, BatchOutcome
from opensees_studio.viewmodels.analysis_runner import (
    KILL_AFTER_TERMINATE_MS,
    _hide_child_console,
)


@dataclass
class _Running:
    """A job whose child is alive."""

    index: int
    job: BatchJob
    process: QProcess
    clock: batch.Stopwatch
    buffer: str = ""
    last_error: str = ""
    case_names: dict[int, str] = field(default_factory=dict)


class BatchRunner(QObject):
    """Run batch jobs, up to ``max_parallel`` children at a time."""

    jobStarted = Signal(int, object)  # job index, the planned BatchJob
    jobProgress = Signal(int, str, int, int)  # job index, case name, step, total
    jobFinished = Signal(int, object)  # job index, BatchOutcome
    finished = Signal(list)  # every BatchOutcome, in job order
    runningChanged = Signal(bool)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._jobs: list[BatchJob] = []
        self._outcomes: list[BatchOutcome | None] = []
        self._pending: list[int] = []
        self._running: dict[int, _Running] = {}
        self._max_parallel = 1
        self._selector: list[str] | None = None
        self._cancelled = False
        self._env: dict[str, str] = {}

    @property
    def is_running(self) -> bool:
        return bool(self._running) or bool(self._pending)

    @property
    def outcomes(self) -> list[BatchOutcome]:
        return [o for o in self._outcomes if o is not None]

    def start(
        self, projects: list[Path], selector: list[str] | None = None, max_parallel: int = 1
    ) -> None:
        """Run the ``selector`` cases (None: all) of every project file.

        Each file is read and planned only when its turn comes
        (:func:`~opensees_studio.services.batch.plan_job`), so a long list never
        stalls the window up front; one that cannot run is reported as skipped.
        """
        if self.is_running:
            raise RuntimeError("A batch is already running.")
        self._jobs = [BatchJob(project=Path(p)) for p in projects]
        self._outcomes = [None] * len(self._jobs)
        self._selector = selector
        self._max_parallel = max(1, max_parallel)
        self._cancelled = False
        self._env = engines.child_environment()
        self._pending = list(range(len(self._jobs)))
        self.runningChanged.emit(True)
        self._fill()

    def cancel(self) -> None:
        """Stop every running child and drop the jobs not started yet."""
        if not self.is_running or self._cancelled:
            return
        self._cancelled = True
        for index in self._pending:
            job = self._jobs[index]
            self._record(
                index,
                BatchOutcome(
                    project=str(job.project), status=batch.CANCELLED, cases=job.case_names
                ),
            )
        self._pending = []
        for running in list(self._running.values()):
            running.process.terminate()
        QTimer.singleShot(KILL_AFTER_TERMINATE_MS, self._kill_running)

    # ── internals ────────────────────────────────────────────────────
    def _kill_running(self) -> None:
        for running in list(self._running.values()):
            if running.process.state() != QProcess.ProcessState.NotRunning:
                running.process.kill()

    def _fill(self) -> None:
        while self._pending and len(self._running) < self._max_parallel:
            self._launch(self._pending.pop(0))
        if not self.is_running:
            self._finish()

    def _launch(self, index: int) -> None:
        job = batch.plan_job(self._jobs[index].project, self._selector)
        self._jobs[index] = job
        if job.error:
            self._record(index, batch.skipped_outcome(job))
            return
        try:
            batch.prepare_out_dir(job)
        except OSError as exc:
            self._record(index, self._outcome(job, batch.FAILED, None, str(exc), 0.0))
            return
        process = QProcess(self)
        command = analysis_cli_command()
        process.setProgram(command[0])
        process.setArguments([*command[1:], *batch.job_arguments(job)])
        env = QProcessEnvironment.systemEnvironment()
        env.insert("PYTHONUNBUFFERED", "1")
        for key, value in self._env.items():
            env.insert(key, value)
        process.setProcessEnvironment(env)
        process.setStandardErrorFile(str(job.out_dir / batch.STDERR_LOG))
        if is_frozen() and os.name == "nt":
            _hide_child_console(process)
        running = _Running(
            index=index,
            job=job,
            process=process,
            clock=batch.Stopwatch(),
            case_names=dict(zip(job.case_ids, job.case_names, strict=True)),
        )
        self._running[index] = running
        process.readyReadStandardOutput.connect(lambda r=running: self._on_stdout(r))
        process.finished.connect(lambda code, status, r=running: self._on_exit(r, code, status))
        process.errorOccurred.connect(lambda error, r=running: self._on_error(r, error))
        self.jobStarted.emit(index, job)
        process.start()

    def _on_stdout(self, running: _Running) -> None:
        data = running.process.readAllStandardOutput().data()
        chunk = bytes(data).decode("utf-8", errors="replace")
        running.buffer += chunk
        while "\n" in running.buffer:
            line, running.buffer = running.buffer.split("\n", 1)
            self._handle(running, line)

    def _handle(self, running: _Running, line: str) -> None:
        payload = batch.parse_line(line)
        if payload is None:
            return
        kind = payload.get("type")
        if kind == "progress":
            name = running.case_names.get(int(payload.get("case_id", 0)), "")
            self.jobProgress.emit(
                running.index, name, int(payload.get("step", 0)), int(payload.get("total", 0))
            )
        elif kind == "case_started":
            self.jobProgress.emit(running.index, str(payload.get("case_name", "")), 0, 0)
        elif kind == "error":
            running.last_error = str(payload.get("message", ""))

    def _on_error(self, running: _Running, error: QProcess.ProcessError) -> None:
        if error != QProcess.ProcessError.FailedToStart or running.index not in self._running:
            return
        message = f"The analysis process could not be started: {running.process.errorString()}"
        self._done(running, batch.FAILED, None, message)

    def _on_exit(self, running: _Running, code: int, status: QProcess.ExitStatus) -> None:
        if running.index not in self._running:
            return
        self._on_stdout(running)
        if running.buffer.strip():
            self._handle(running, running.buffer)
        crashed = status == QProcess.ExitStatus.CrashExit
        exit_code = (code or -2) if crashed else code
        status_text, message = batch.finish_job(
            running.job,
            exit_code,
            running.last_error,
            cancelled=self._cancelled,
            engine=self._env.get(engines.ENGINE_KEY_ENV, ""),
        )
        self._done(running, status_text, exit_code, message)

    def _done(self, running: _Running, status: str, code: int | None, message: str) -> None:
        del self._running[running.index]
        running.process.deleteLater()
        outcome = self._outcome(running.job, status, code, message, running.clock.seconds())
        self._record(running.index, outcome)
        self._fill()

    @staticmethod
    def _outcome(
        job: BatchJob, status: str, code: int | None, message: str, seconds: float
    ) -> BatchOutcome:
        return BatchOutcome(
            project=str(job.project),
            status=status,
            seconds=seconds,
            cases=list(job.case_names),
            exit_code=code,
            message=message,
            results_dir=str(job.out_dir),
        )

    def _record(self, index: int, outcome: BatchOutcome) -> None:
        self._outcomes[index] = outcome
        self.jobFinished.emit(index, outcome)

    def _finish(self) -> None:
        self.runningChanged.emit(False)
        self.finished.emit(self.outcomes)
