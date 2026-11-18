"""Dialog with the reactions of the case on screen.

The same panel as the Reactions tab, opened on demand: the tab is there for
working with the numbers in view, and the dialog is for a glance without
switching docks.
"""

from __future__ import annotations

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QVBoxLayout, QWidget

from opensees_studio.core.reactions import ReactionRow
from opensees_studio.views.docks.reactions_panel import ReactionsPanel


class ReactionsDialog(QDialog):
    """Every reaction of the case, in a modal window."""

    def __init__(self, rows: list[ReactionRow], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Reactions")
        self.resize(560, 420)
        layout = QVBoxLayout(self)
        self.panel = ReactionsPanel()
        self.panel.set_rows(rows)
        layout.addWidget(self.panel, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
