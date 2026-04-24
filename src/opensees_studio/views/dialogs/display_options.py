"""Display options dialog."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QVBoxLayout,
    QWidget,
)


class DisplayOptionsDialog(QDialog):
    """Toggle viewport overlays such as node / element labels."""

    def __init__(
        self,
        *,
        show_node_labels: bool,
        show_element_labels: bool,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Display Options")
        layout = QVBoxLayout(self)

        self._show_node_labels = QCheckBox("Show node labels")
        self._show_node_labels.setChecked(show_node_labels)
        layout.addWidget(self._show_node_labels)

        self._show_element_labels = QCheckBox("Show element labels")
        self._show_element_labels.setChecked(show_element_labels)
        layout.addWidget(self._show_element_labels)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def values(self) -> tuple[bool, bool]:
        return self._show_node_labels.isChecked(), self._show_element_labels.isChecked()
