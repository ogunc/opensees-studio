"""The status-bar strip that shows a running analysis: case, progress, Cancel.

Analyze → Run All Cases and Run Selected Cases start the solver without a
dialog, so this is where the person sees which case is running, how far it got,
and stops it. It shows itself while the runner runs and hides again after.
"""

from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QLabel, QProgressBar, QPushButton, QWidget

from opensees_studio.viewmodels import AnalysisRunner


class RunStatusWidget(QWidget):
    """Case label, progress bar and Cancel button for ``runner``."""

    def __init__(self, runner: AnalysisRunner, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._runner = runner
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._label = QLabel("Running analysis")
        self._bar = QProgressBar()
        self._bar.setFixedWidth(160)
        self._bar.setRange(0, 0)  # busy until the first progress line
        self._cancel = QPushButton("Cancel")
        self._cancel.setToolTip("Stop the running analysis process. The project is unchanged.")
        layout.addWidget(self._label)
        layout.addWidget(self._bar)
        layout.addWidget(self._cancel)
        self.setVisible(False)

        self._cancel.clicked.connect(self._on_cancel)
        runner.runningChanged.connect(self._on_running_changed)
        runner.caseStarted.connect(self._on_case_started)
        runner.progress.connect(self._on_progress)

    @property
    def text(self) -> str:
        return self._label.text()

    def _on_running_changed(self, running: bool) -> None:
        if running:
            self._label.setText("Running analysis")
            self._bar.setRange(0, 0)
            self._cancel.setEnabled(self._runner.can_cancel)
        self.setVisible(running)

    def _on_case_started(self, index: int, count: int, name: str) -> None:
        label = f"'{name}'" if name else "case"
        self._label.setText(
            f"Running {label} ({index} of {count})" if count > 1 else f"Running {label}"
        )
        self._bar.setRange(0, 0)

    def _on_progress(self, step: int, total: int) -> None:
        if total > 0:
            self._bar.setRange(0, total)
            self._bar.setValue(step)

    def _on_cancel(self) -> None:
        self._cancel.setEnabled(False)
        self._label.setText("Cancelling…")
        self._runner.cancel()
