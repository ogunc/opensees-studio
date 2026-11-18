"""File → Export → Calculation Memory: language, format and member filter."""

from __future__ import annotations

from typing import Literal

from PySide6.QtWidgets import (
    QComboBox,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from opensees_studio.core.help import TOPIC_PROPERTY
from opensees_studio.views.screen_fit import FittedDialog

Format = Literal["html", "markdown", "latex", "odt", "pdf"]
Filter = Literal["all", "selected", "ng"]


class CalculationMemoryDialog(FittedDialog):
    """The calculation-memory export options."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Calculation Memory")
        self.setProperty(TOPIC_PROPERTY, "file.calc_memory")
        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(
                "A member-by-member calculation memory: cover, index, properties, "
                "demands and every limit state with its formula and numbers."
            )
        )
        form = QFormLayout()
        self._language = QComboBox()
        self._language.addItem("English", "en")
        self._language.addItem("Español", "es")
        form.addRow("Language:", self._language)
        self._format = QComboBox()
        for label, value in (
            ("HTML page (*.html)", "html"),
            ("Markdown (*.md)", "markdown"),
            ("LaTeX (*.tex)", "latex"),
            ("OpenDocument text (*.odt)", "odt"),
            ("PDF (*.pdf)", "pdf"),
        ):
            self._format.addItem(label, value)
        form.addRow("Format:", self._format)
        self._filter = QComboBox()
        for label, value in (
            ("All designed members", "all"),
            ("Selected members", "selected"),
            ("Members over the limit (NG)", "ng"),
        ):
            self._filter.addItem(label, value)
        form.addRow("Members:", self._filter)
        layout.addLayout(form)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def language(self) -> str:
        return str(self._language.currentData())

    def format(self) -> Format:
        return self._format.currentData()  # type: ignore[no-any-return]

    def member_filter(self) -> Filter:
        return self._filter.currentData()  # type: ignore[no-any-return]
