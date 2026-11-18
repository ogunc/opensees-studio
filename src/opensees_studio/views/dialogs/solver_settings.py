"""Options → Solver: which engine solves, and where OpenSeesPy is installed.

OpenSeesPy is a separate program with its own license; the application may be
installed without it. This dialog shows whether an engine is available and
lets the user point to one: the application's own environment, another Python
of the same version that has ``openseespy``, or a folder holding the package —
or download it from PyPI into such a folder, after accepting its license. The
logic is in :mod:`opensees_studio.services.engines` and
:mod:`opensees_studio.services.engine_install`.
"""

from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from opensees_studio.core.help import TOPIC_PROPERTY
from opensees_studio.services.engine_install import (
    LICENSE_SUMMARY,
    LICENSE_URL,
    OPENSEESPY_VERSION,
    InstallError,
    wheels_for,
)
from opensees_studio.services.engines import (
    OPENSEES_PY,
    EngineError,
    SolverSettings,
    current_status,
    engines,
    inspect_python,
    opensees_status,
)
from opensees_studio.viewmodels.engine_installer import EngineInstaller
from opensees_studio.views.screen_fit import FittedDialog, MessageArea

LICENSE_NOTE = (
    "<i>OpenSeesPy is a separate program with its own license: free for research, "
    "education and internal use; commercial redistribution needs a license from its "
    "authors. OpenSees Studio does not include it — check that your use fits its "
    "terms.</i>"
)

OWN, PYTHON, FOLDER = "own", "python", "folder"


class SolverSettingsDialog(FittedDialog):
    """Choose where OpenSeesPy comes from and see whether it is usable."""

    def __init__(self, settings: SolverSettings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Solver")
        self.setProperty(TOPIC_PROPERTY, "options.solver")
        self._settings = settings
        self._build_ui()
        index = self._engine.findData(settings.engine)
        self._engine.setCurrentIndex(max(index, 0))
        if settings.python:
            self._python_radio.setChecked(True)
            self._python_edit.setText(settings.python)
        elif settings.package_dir:
            self._folder_radio.setChecked(True)
            self._folder_edit.setText(settings.package_dir)
        else:
            self._own_radio.setChecked(True)
        self._refresh()

    # ── ui ──────────────────────────────────────────────────────────
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(
                "OpenSees Studio models; an <b>engine</b> solves. Without one you can "
                "still model, export and report, but not run an analysis. The stability "
                "check and the Material Tester always use <b>OpenSeesPy</b>, whatever "
                "engine runs the cases."
            )
        )
        form = QFormLayout()
        self._engine = QComboBox()
        for key, engine in engines().items():
            self._engine.addItem(
                f"{engine.name} — runs {', '.join(sorted(engine.case_types))}", userData=key
            )
        self._engine.currentIndexChanged.connect(self._refresh)
        form.addRow("Engine:", self._engine)
        form.addRow(QLabel("<b>Where OpenSeesPy is</b>"))
        self._own_radio = QRadioButton("OpenSeesPy installed with OpenSees Studio")
        self._python_radio = QRadioButton(
            f"OpenSeesPy of another Python {sys.version_info[0]}.{sys.version_info[1]}"
        )
        self._folder_radio = QRadioButton("A folder that contains the openseespy package")
        self._group = QButtonGroup(self)
        for button in (self._own_radio, self._python_radio, self._folder_radio):
            self._group.addButton(button)
            button.toggled.connect(self._refresh)

        self._python_edit = QLineEdit()
        self._python_edit.setPlaceholderText("python executable")
        self._python_edit.editingFinished.connect(self._refresh)
        python_row = self._row(self._python_edit, self._browse_python)
        self._folder_edit = QLineEdit()
        self._folder_edit.setPlaceholderText("…/site-packages")
        self._folder_edit.editingFinished.connect(self._refresh)
        folder_row = self._row(self._folder_edit, self._browse_folder)

        form.addRow(self._own_radio)
        form.addRow(self._python_radio)
        form.addRow("Interpreter:", python_row)
        form.addRow(self._folder_radio)
        form.addRow("Folder:", folder_row)
        layout.addLayout(form)

        self._download = QPushButton()
        try:
            megabytes = sum(w.size for w in wheels_for()) / 1e6
            self._download.setText(
                f"Download OpenSeesPy {OPENSEESPY_VERSION} from PyPI ({megabytes:.0f} MB)…"
            )
        except InstallError as exc:
            self._download.setText(f"Download OpenSeesPy {OPENSEESPY_VERSION}…")
            self._download.setEnabled(False)
            self._download.setToolTip(str(exc))
        self._download.clicked.connect(self._on_download)
        layout.addWidget(self._download)
        self._installer = EngineInstaller(self)
        self._installer.installed.connect(self._on_installed)
        self._installer.failed.connect(self._on_install_failed)
        self._installer.cancelled.connect(self._on_install_cancelled)
        self._progress: QProgressDialog | None = None

        self._status = MessageArea()
        layout.addWidget(self._status)
        note = QLabel(LICENSE_NOTE)
        note.setWordWrap(True)
        layout.addWidget(note)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._ok = buttons.button(QDialogButtonBox.StandardButton.Ok)

    def _row(self, edit: QLineEdit, browse: object) -> QWidget:
        row = QWidget()
        box = QHBoxLayout(row)
        box.setContentsMargins(0, 0, 0, 0)
        box.addWidget(edit)
        button = QPushButton("Browse…")
        button.clicked.connect(browse)
        box.addWidget(button)
        return row

    def _browse_python(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Python interpreter")
        if path:
            self._python_edit.setText(path)
            self._python_radio.setChecked(True)
            self._refresh()

    def _browse_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Folder with the openseespy package")
        if path:
            self._folder_edit.setText(path)
            self._folder_radio.setChecked(True)
            self._refresh()

    # ── download ────────────────────────────────────────────────────
    def accept_license(self) -> bool:
        """Show OpenSeesPy's terms; True only when the user ticks that they accept them."""
        box = QMessageBox(self)
        box.setWindowTitle("OpenSeesPy license")
        box.setIcon(QMessageBox.Icon.Information)
        box.setTextFormat(Qt.TextFormat.RichText)
        box.setText(
            f'{LICENSE_SUMMARY}<br><br>Full terms: <a href="{LICENSE_URL}">{LICENSE_URL}</a>'
        )
        tick = QCheckBox("I have read the OpenSeesPy license and my use fits its terms")
        box.setCheckBox(tick)
        box.setStandardButtons(QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel)
        if box.exec() != QMessageBox.StandardButton.Ok:
            return False
        if not tick.isChecked():
            QMessageBox.information(
                self, "OpenSeesPy license", "Tick the box to accept the license and download."
            )
            return False
        return True

    def _on_download(self) -> None:
        if not self.accept_license():
            return
        self._progress = QProgressDialog("Downloading OpenSeesPy …", "Cancel", 0, 100, self)
        self._progress.setWindowModality(Qt.WindowModality.WindowModal)
        self._progress.setMinimumDuration(0)
        self._progress.setAutoClose(False)
        self._progress.setAutoReset(False)
        self._progress.canceled.connect(self._installer.cancel)
        self._installer.progressed.connect(self._on_progress)
        self._download.setEnabled(False)
        self._installer.start()

    def _on_progress(self, done: int, total: int) -> None:
        progress = self._progress
        if progress is None or not total:
            return
        progress.setLabelText(f"Downloading OpenSeesPy … {done / 1e6:.1f} of {total / 1e6:.1f} MB")
        # setValue processes events on a modal dialog: the "installed" slot may run
        # inside it and close the dialog, so it comes last.
        progress.setValue(int(100 * done / total))

    def _close_progress(self) -> None:
        progress, self._progress = self._progress, None
        if progress is not None:
            progress.canceled.disconnect()
            progress.hide()
            progress.deleteLater()
        self._download.setEnabled(True)

    def _on_installed(self, settings: SolverSettings) -> None:
        self._close_progress()
        self._folder_radio.setChecked(True)
        self._folder_edit.setText(settings.package_dir or "")
        self._refresh()

    def _on_install_failed(self, message: str) -> None:
        self._close_progress()
        self._status.show_message(message, level="error")

    def _on_install_cancelled(self) -> None:
        self._close_progress()
        self._status.show_message("The download was cancelled; nothing was installed.", "warning")

    def done(self, result: int) -> None:
        # Closing the dialog stops a download in progress instead of orphaning it.
        if self._installer.is_running:
            self._installer.cancel()
            self._installer.wait()
        super().done(result)

    # ── state ───────────────────────────────────────────────────────
    def mode(self) -> str:
        if self._python_radio.isChecked():
            return PYTHON
        if self._folder_radio.isChecked():
            return FOLDER
        return OWN

    def _candidate(self) -> SolverSettings:
        """The settings the form describes; raises EngineError when they cannot be used."""
        mode = self.mode()
        if mode == PYTHON:
            executable = self._python_edit.text().strip()
            if not executable:
                raise EngineError("Choose a Python interpreter.")
            found = inspect_python(executable)
            return SolverSettings(
                engine=self.engine_key(), package_dir=found.package_dir, python=found.python
            )
        if mode == FOLDER:
            folder = self._folder_edit.text().strip()
            if not folder:
                raise EngineError("Choose a folder.")
            return SolverSettings(engine=self.engine_key(), package_dir=folder)
        return SolverSettings(engine=self.engine_key())

    def engine_key(self) -> str:
        return str(self._engine.currentData() or OPENSEES_PY)

    def _refresh(self, *_: object) -> None:
        self._python_edit.setEnabled(self._python_radio.isChecked())
        self._folder_edit.setEnabled(self._folder_radio.isChecked())
        try:
            self._settings = self._candidate()
        except EngineError as exc:
            self._status.show_message(str(exc), level="error")
            self._ok.setEnabled(False)
            return
        self._ok.setEnabled(True)
        status = current_status(self._settings)
        lines = [f"Ready: {status.summary()}." if status.available else status.message]
        if status.available and status.message:
            lines.append(status.message)
        if self.engine_key() != OPENSEES_PY:
            opensees = opensees_status(self._settings)
            lines.append(
                f"Stability check and Material Tester: {opensees.summary()}."
                if opensees.available
                else "Stability check and Material Tester need OpenSeesPy: " + opensees.message
            )
        self._status.show_message("\n".join(lines), level="info" if status.available else "warning")

    def settings(self) -> SolverSettings:
        """What to save on OK (the last settings the form could describe)."""
        return self._settings
