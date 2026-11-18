"""Import a PORTICO model (``.s3d``) as a new project.

The file's numbers are in PORTICO's own unit system, named by its ``units``
label; the project gets ours. The dialog shows both systems and the factors
between them before anything is built, and the summary — what came across, what
did not and why — recomputes on every change.

The file is read once; changing a unit system only re-runs the translation.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QComboBox,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from opensees_studio.core.help import TOPIC_PROPERTY
from opensees_studio.core.units import UnitSystem, labels_for
from opensees_studio.services.s3d_import import (
    DEFAULT_TARGET,
    SOURCE_UNITS,
    S3dFile,
    S3dImport,
    S3dImportError,
    read_s3d,
    s3d_to_project,
)
from opensees_studio.views.screen_fit import FittedDialog, MessageArea

#: File filter of the open dialog.
S3D_FILTER = "PORTICO models (*.s3d);;All files (*)"


class S3dImportDialog(FittedDialog):
    """Pick a PORTICO file, say which units it is in and which ones the project takes."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._file_data: S3dFile | None = None
        self._result: S3dImport | None = None
        self.setWindowTitle("Import PORTICO Model")
        self.setProperty(TOPIC_PROPERTY, "file.import_s3d")
        self._build_ui()
        self._refresh()

    # ── ui ──────────────────────────────────────────────────────────
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(
                "Nodes, supports, frame members, shells, diaphragms, links, static load "
                "cases, combinations and the mass source become a <b>new project</b>, "
                "scaled to the units chosen below. <i>Whatever cannot come across is "
                "counted and reported.</i>"
            )
        )

        file_row = QWidget()
        file_layout = QHBoxLayout(file_row)
        file_layout.setContentsMargins(0, 0, 0, 0)
        self._file = QLineEdit()
        self._file.setReadOnly(True)
        self._file.setPlaceholderText("No file chosen")
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._on_browse)
        file_layout.addWidget(self._file)
        file_layout.addWidget(browse)
        layout.addWidget(file_row)

        form = QFormLayout()
        self._source = QComboBox()
        for label in SOURCE_UNITS:
            self._source.addItem(label, userData=label)
        self._source.setToolTip(
            "The unit system the file's numbers are in. Filled in from the file's own "
            "'units' label; change it if the label is wrong."
        )
        self._source.currentIndexChanged.connect(self._on_source_changed)
        form.addRow("File units:", self._source)

        self._target = QComboBox()
        for system in UnitSystem:
            # By name: Qt hands a str-Enum back as a plain str.
            self._target.addItem(system.value, userData=system.name)
        self._target.setToolTip("The project's unit system: every value is scaled to it.")
        self._target.currentIndexChanged.connect(self._refresh)
        form.addRow("Project units:", self._target)

        self._factors = QLabel()
        self._factors.setWordWrap(True)
        form.addRow("Scale:", self._factors)
        layout.addLayout(form)

        self._summary = MessageArea()
        layout.addWidget(self._summary)
        self._notes = MessageArea()
        layout.addWidget(self._notes)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self._ok.setText("Import")

    # ── the file ────────────────────────────────────────────────────
    def _on_browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import PORTICO model", "", S3D_FILTER)
        if path:
            self.load(Path(path))

    def load(self, path: str | Path) -> bool:
        """Read ``path`` and fill the unit choices in from it. False when it cannot be read."""
        try:
            data = read_s3d(path)
        except S3dImportError as exc:
            self._file_data = None
            self._file.clear()
            self._summary.show_message(str(exc), level="error")
            self._refresh()
            return False
        self._file_data = data
        self._file.setText(str(path))
        self._source.blockSignals(True)
        index = self._source.findData(data.units)
        self._source.setCurrentIndex(index if index >= 0 else 0)
        self._source.blockSignals(False)
        self._select_default_target()
        self._refresh()
        return True

    def _select_default_target(self) -> None:
        target = DEFAULT_TARGET.get(self.source_units() or "", UnitSystem.SI_M_N)
        self._target.blockSignals(True)
        self._target.setCurrentIndex(self._target.findData(target.name))
        self._target.blockSignals(False)

    def _on_source_changed(self) -> None:
        self._select_default_target()
        self._refresh()

    # ── what the caller needs ───────────────────────────────────────
    def source_units(self) -> str | None:
        data = self._source.currentData()
        return str(data) if data is not None else None

    def target_units(self) -> UnitSystem:
        data = self._target.currentData()
        return UnitSystem[data] if data in UnitSystem.__members__ else UnitSystem.SI_M_N

    def source(self) -> Path | None:
        return self._file_data.path if self._file_data is not None else None

    def imported(self) -> S3dImport | None:
        """The translated project for the current choices, None when there is none."""
        return self._result

    # ── live summary ────────────────────────────────────────────────
    def _refresh(self) -> None:
        self._result = None
        self._notes.clear_message()
        data = self._file_data
        if data is None:
            self._factors.clear()
            if self._summary.level != "error":
                self._summary.clear_message()
            self._ok.setEnabled(False)
            return
        try:
            result = s3d_to_project(
                data, units=self.target_units(), source_units=self.source_units()
            )
        except S3dImportError as exc:
            self._factors.clear()
            self._summary.show_message(str(exc), level="error")
            self._ok.setEnabled(False)
            return
        self._result = result
        labels = labels_for(self.target_units())
        scale = result.scale
        unknown = data.units not in SOURCE_UNITS
        label_note = (
            f" <b>The file says {data.units!r}, which is not a known PORTICO system: "
            "check the file units.</b>"
            if unknown
            else ""
        )
        self._factors.setText(
            f"1 length unit of the file = {scale.length:g} {labels.length}; "
            f"1 force unit = {scale.force:g} {labels.force}.{label_note}"
        )
        text = f"{data.summary()} Imports {result.summary()}"
        self._summary.show_message(text, level="warning" if result.dropped else "info")
        if result.notes:
            self._notes.show_message(" ".join(result.notes))
        self._ok.setEnabled(True)
