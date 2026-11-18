"""File → Run Batch…: solve many project files unattended and keep their results.

The list takes files and folders (a folder adds its ``*.osmodel``); the cases
are every case of each project or the ones named; up to *Parallel jobs*
projects solve at the same time, each in its own analysis child driven by
:class:`~opensees_studio.viewmodels.batch_runner.BatchRunner`. Every project
keeps its results beside it, so opening it later shows them without solving
again. When the batch ends the summary is written to ``batch_summary.json`` and
``batch_summary.csv`` in the folder of the first project.
"""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from opensees_studio.core.help import TOPIC_PROPERTY
from opensees_studio.services import batch
from opensees_studio.services.batch import BatchOutcome
from opensees_studio.services.persistence import PROJECT_FILE_SUFFIX
from opensees_studio.viewmodels.batch_runner import BatchRunner
from opensees_studio.views.screen_fit import FittedDialog

SUMMARY_STEM = "batch_summary"

_COLUMNS = ("Project", "Status", "Progress", "Time (s)", "Message")
_STATUS_LABELS = {
    batch.OK: "Done",
    batch.FAILED: "Failed",
    batch.SKIPPED: "Skipped",
    batch.CANCELLED: "Cancelled",
}


class BatchRunDialog(FittedDialog):
    """Pick project files and cases, run them, watch each file's progress."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        start_dir: Path | None = None,
        runner: BatchRunner | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Run Batch")
        self.setProperty(TOPIC_PROPERTY, "file.run_batch")
        self.resize(820, 560)
        self._start_dir = start_dir
        self._runner = runner or BatchRunner(self)
        self._projects: list[Path] = []
        self.summary_paths: tuple[Path, Path] | None = None

        self._files = QListWidget()
        self._files.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        add_files = QPushButton("Add Files…")
        add_files.clicked.connect(self._on_add_files)
        add_folder = QPushButton("Add Folder…")
        add_folder.clicked.connect(self._on_add_folder)
        self._remove_btn = QPushButton("Remove")
        self._remove_btn.clicked.connect(self._on_remove)
        clear = QPushButton("Clear")
        clear.clicked.connect(self._files.clear)
        file_buttons = QVBoxLayout()
        for button in (add_files, add_folder, self._remove_btn, clear):
            file_buttons.addWidget(button)
        file_buttons.addStretch(1)
        files_row = QHBoxLayout()
        files_row.addWidget(self._files, stretch=1)
        files_row.addLayout(file_buttons)

        self._all_cases = QRadioButton("All cases")
        self._named_cases = QRadioButton("Cases named:")
        self._all_cases.setChecked(True)
        group = QButtonGroup(self)
        group.addButton(self._all_cases)
        group.addButton(self._named_cases)
        self._case_names = QLineEdit()
        self._case_names.setPlaceholderText("comma-separated names or ids, e.g. Dead, Modal")
        self._case_names.setEnabled(False)
        self._named_cases.toggled.connect(self._case_names.setEnabled)
        cases_row = QHBoxLayout()
        cases_row.addWidget(self._all_cases)
        cases_row.addWidget(self._named_cases)
        cases_row.addWidget(self._case_names, stretch=1)

        self._jobs_spin = QSpinBox()
        self._jobs_spin.setRange(1, max(1, os.cpu_count() or 1))
        self._jobs_spin.setValue(1)

        form = QFormLayout()
        form.addRow("Cases", cases_row)
        form.addRow("Parallel jobs", self._jobs_spin)

        self._table = QTableWidget(0, len(_COLUMNS))
        self._table.setHorizontalHeaderLabels(_COLUMNS)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self._status = QLabel("Add project files or a folder, then Run.")
        self._status.setWordWrap(True)

        self._buttons = QDialogButtonBox(parent=self)
        self._run_btn = self._buttons.addButton("Run", QDialogButtonBox.ButtonRole.ActionRole)
        self._cancel_btn = self._buttons.addButton(
            "Cancel Batch", QDialogButtonBox.ButtonRole.ActionRole
        )
        self._close_btn = self._buttons.addButton(QDialogButtonBox.StandardButton.Close)
        self._run_btn.clicked.connect(self.start)
        self._cancel_btn.clicked.connect(self._runner.cancel)
        self._close_btn.clicked.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Project files:"))
        layout.addLayout(files_row, stretch=1)
        layout.addLayout(form)
        layout.addWidget(self._table, stretch=2)
        layout.addWidget(self._status)
        layout.addWidget(self._buttons)

        self._runner.jobStarted.connect(self._on_job_started)
        self._runner.jobProgress.connect(self._on_job_progress)
        self._runner.jobFinished.connect(self._on_job_finished)
        self._runner.finished.connect(self._on_finished)
        self._runner.runningChanged.connect(self._set_running)
        self._set_running(False)

    # ── public API (also used by tests) ──────────────────────────────
    def add_paths(self, paths: list[str | Path]) -> None:
        """Add files and folders to the list (a folder stays one entry)."""
        present = {self._files.item(i).text() for i in range(self._files.count())}
        for path in paths:
            text = str(path)
            if text not in present:
                present.add(text)
                self._files.addItem(text)

    def paths(self) -> list[str]:
        return [self._files.item(i).text() for i in range(self._files.count())]

    def set_case_selector(self, text: str) -> None:
        """``"all"`` / empty for every case, otherwise names or ids separated by commas."""
        selector = batch.parse_case_selector(text)
        self._named_cases.setChecked(selector is not None)
        self._all_cases.setChecked(selector is None)
        self._case_names.setText("" if selector is None else ", ".join(selector))

    def set_parallel_jobs(self, n: int) -> None:
        self._jobs_spin.setValue(n)

    def table(self) -> QTableWidget:
        return self._table

    @property
    def runner(self) -> BatchRunner:
        return self._runner

    def start(self) -> None:
        """Plan every listed project and start the batch."""
        if self._runner.is_running:
            return
        selector = (
            batch.parse_case_selector(self._case_names.text())
            if self._named_cases.isChecked()
            else None
        )
        self._projects = batch.expand_inputs(self.paths())
        self.summary_paths = None
        self._table.setRowCount(0)
        if not self._projects:
            self._status.setText(f"No {PROJECT_FILE_SUFFIX} files in the list.")
            return
        for row, project in enumerate(self._projects):
            self._table.insertRow(row)
            self._set_cell(row, 0, project.name, tooltip=str(project))
            self._set_cell(row, 1, "Queued")
        self._status.setText(
            f"Running {len(self._projects)} project(s), {self._jobs_spin.value()} at a time…"
        )
        self._runner.start(self._projects, selector, self._jobs_spin.value())

    def reject(self) -> None:
        """Close: refused while the batch runs — cancel it first."""
        if self._runner.is_running:
            self._status.setText("The batch is still running: Cancel Batch first.")
            return
        super().reject()

    # ── slots ────────────────────────────────────────────────────────
    def _on_add_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Add project files",
            str(self._start_dir or ""),
            f"OpenSees Studio model (*{PROJECT_FILE_SUFFIX});;All files (*)",
        )
        self.add_paths(list(files))

    def _on_add_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "Add every project in a folder", str(self._start_dir or "")
        )
        if folder:
            self.add_paths([folder])

    def _on_remove(self) -> None:
        for item in self._files.selectedItems():
            self._files.takeItem(self._files.row(item))

    def _on_job_started(self, index: int, job: batch.BatchJob) -> None:
        self._set_cell(index, 1, "Running")
        self._set_cell(index, 2, ", ".join(job.case_names))

    def _on_job_progress(self, index: int, case_name: str, step: int, total: int) -> None:
        text = f"{case_name}: {step}/{total}" if total else case_name
        self._set_cell(index, 2, text)

    def _on_job_finished(self, index: int, outcome: BatchOutcome) -> None:
        self._set_cell(index, 1, _STATUS_LABELS.get(outcome.status, outcome.status))
        if outcome.status == batch.OK:
            self._set_cell(index, 2, ", ".join(outcome.cases))
        self._set_cell(index, 3, f"{outcome.seconds:.2f}")
        self._set_cell(index, 4, outcome.message, tooltip=outcome.message)

    def _on_finished(self, outcomes: list[BatchOutcome]) -> None:
        counts = batch.summary_counts(outcomes)
        text = ", ".join(f"{n} {_STATUS_LABELS[s].lower()}" for s, n in counts.items() if n)
        if self._projects:
            stem = self._projects[0].parent / SUMMARY_STEM
            try:
                self.summary_paths = batch.write_summary(outcomes, stem)
                text += f". Summary: {self.summary_paths[0]} and .csv"
            except OSError as exc:
                text += f". The summary was not written: {exc}"
        self._status.setText(text + ". Open a project to view its results.")

    def _set_running(self, running: bool) -> None:
        self._run_btn.setEnabled(not running)
        self._cancel_btn.setEnabled(running)
        self._close_btn.setEnabled(not running)

    def _set_cell(self, row: int, column: int, text: str, tooltip: str = "") -> None:
        if row >= self._table.rowCount():
            return
        item = QTableWidgetItem(text)
        if tooltip:
            item.setToolTip(tooltip)
        self._table.setItem(row, column, item)
