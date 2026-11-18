"""Import an OpenSees Tcl script as a new project.

Tcl files carry no unit metadata, so the dialog asks which system the script's
numbers are in and shows what the translation found before anything replaces
the open project. The file is read once; changing the units only re-runs the
translation.
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
from opensees_studio.core.units import UnitSystem
from opensees_studio.services.tcl_import import TclImport, TclImportError, import_tcl
from opensees_studio.views.screen_fit import FittedDialog, MessageArea

#: File filter of the open dialog.
TCL_FILTER = "OpenSees Tcl scripts (*.tcl);;All files (*)"


class TclImportDialog(FittedDialog):
    """Pick a Tcl script, say which units its numbers use and preview the model."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        default_units: UnitSystem = UnitSystem.SI_M_N,
    ) -> None:
        super().__init__(parent)
        self._path: Path | None = None
        self._result: TclImport | None = None
        self.setWindowTitle("Import OpenSees Tcl Script")
        self.setProperty(TOPIC_PROPERTY, "file.import_tcl")
        self._build_ui(default_units)
        self._refresh()

    # ── ui ──────────────────────────────────────────────────────────
    def _build_ui(self, default_units: UnitSystem) -> None:
        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(
                "Nodes, supports, materials, sections, elements, constraints and plain "
                "loads become a <b>new project</b>. <i>Analysis commands, block3D meshes "
                "and unsupported items are reported, not imported.</i>"
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
        self._units = QComboBox()
        for system in UnitSystem:
            self._units.addItem(system.value, userData=system.name)
        self._units.setCurrentIndex(self._units.findData(default_units.name))
        self._units.setToolTip(
            "Tcl carries no unit metadata. Choose the system the script's numbers "
            "are in; values are kept exactly as written."
        )
        self._units.currentIndexChanged.connect(self._refresh)
        form.addRow("Script units:", self._units)

        self._hint = QLabel(
            "OpenSees' own examples usually use kip and inches (E ≈ 30000, "
            "fy ≈ 60, lengths in inches): pick <b>US (in, kip…)</b> for those."
        )
        self._hint.setWordWrap(True)
        form.addRow("", self._hint)
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
        path, _ = QFileDialog.getOpenFileName(self, "Import OpenSees Tcl script", "", TCL_FILTER)
        if path:
            self.load(Path(path))

    def load(self, path: str | Path) -> bool:
        """Read ``path`` and fill the preview. False when it cannot be read."""
        self._path = Path(path)
        self._file.setText(str(path))
        self._refresh()
        return self._result is not None

    def source(self) -> Path | None:
        return self._path

    def target_units(self) -> UnitSystem:
        data = self._units.currentData()
        return UnitSystem[data] if data in UnitSystem.__members__ else UnitSystem.SI_M_N

    def imported(self) -> TclImport | None:
        """The translated project for the current choices, None when there is none."""
        return self._result

    # ── live preview ────────────────────────────────────────────────
    def _refresh(self) -> None:
        self._result = None
        self._notes.clear_message()
        if self._path is None:
            self._summary.clear_message()
            self._ok.setEnabled(False)
            return
        try:
            result = import_tcl(self._path, units=self.target_units())
        except TclImportError as exc:
            self._summary.show_message(str(exc), level="error")
            self._ok.setEnabled(False)
            return
        self._result = result
        level = "warning" if result.dropped else "info"
        self._summary.show_message(
            f"{result.summary()}. {result.source_units} numbers kept as written.",
            level=level,
        )
        if result.notes:
            self._notes.show_message(" ".join(result.notes))
        self._ok.setEnabled(True)
