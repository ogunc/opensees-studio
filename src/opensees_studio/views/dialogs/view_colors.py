"""View → Colors: the six colours a viewport lets the user customise.

The dialog only edits colours; visibility is the Visibility submenu's job. It is
seeded from the canvas' current :class:`ViewSettings` so it always opens on what
is on screen, and returns the six hex strings keyed like the settings fields, so
the caller can hand them straight to ``with_changes``.
"""

from __future__ import annotations

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QColorDialog,
    QDialogButtonBox,
    QGridLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from opensees_studio.core.view_settings import ViewSettings
from opensees_studio.views.screen_fit import FittedDialog

#: Fields edited here, in display order: (ViewSettings field, row label).
COLOUR_FIELDS: tuple[tuple[str, str], ...] = (
    ("background_top", "Background top"),
    ("background_bottom", "Background bottom"),
    ("node_color", "Nodes"),
    ("frame_color", "Frames"),
    ("surface_color", "Shells"),
    ("selected_color", "Selected"),
)


class ViewColorsDialog(FittedDialog):
    """Pick the viewport background, entity and highlight colours."""

    def __init__(self, settings: ViewSettings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("View Colors")
        self._colours: dict[str, str] = {
            field: getattr(settings, field) for field, _label in COLOUR_FIELDS
        }
        self._buttons: dict[str, QPushButton] = {}

        layout = QVBoxLayout(self)
        grid = QGridLayout()
        for row, (field, label) in enumerate(COLOUR_FIELDS):
            grid.addWidget(QLabel(label), row, 0)
            button = QPushButton()
            button.setMinimumWidth(120)
            button.setToolTip(f"Current colour: {self._colours[field]}")
            button.clicked.connect(lambda _checked=False, name=field: self._pick(name))
            grid.addWidget(button, row, 1)
            self._buttons[field] = button
        layout.addLayout(grid)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._refresh_swatches()

    def _pick(self, field: str) -> None:
        """Open the colour picker for one field and keep the choice."""
        chosen = QColorDialog.getColor(
            QColor(self._colours[field]),
            self,
            "Select Color",
        )
        if chosen.isValid():
            self._colours[field] = chosen.name()
            self._refresh_swatches()

    def _refresh_swatches(self) -> None:
        """Paint each button with the colour it currently holds."""
        for field, button in self._buttons.items():
            colour = self._colours[field]
            button.setText(colour)
            button.setStyleSheet(f"background-color: {colour};")

    def colors(self) -> dict[str, str]:
        """The six chosen colours, keyed like the ``ViewSettings`` fields."""
        return dict(self._colours)
