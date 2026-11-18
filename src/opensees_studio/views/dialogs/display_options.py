"""Display options dialog."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from opensees_studio.core.view_settings import ViewSettings
from opensees_studio.views.screen_fit import FittedDialog


class DisplayOptionsDialog(FittedDialog):
    """Toggle viewport overlays and set the on-screen size of model objects."""

    def __init__(
        self,
        *,
        show_node_labels: bool,
        show_element_labels: bool,
        view_settings: ViewSettings | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Display Options")
        self._base = view_settings or ViewSettings()
        layout = QVBoxLayout(self)

        self._show_node_labels = QCheckBox("Show node labels")
        self._show_node_labels.setChecked(show_node_labels)
        layout.addWidget(self._show_node_labels)

        self._show_element_labels = QCheckBox("Show element labels")
        self._show_element_labels.setChecked(show_element_labels)
        layout.addWidget(self._show_element_labels)

        self._show_masses = QCheckBox("Show joint masses (purple diamonds)")
        self._show_masses.setChecked(self._base.show_masses)
        layout.addWidget(self._show_masses)

        size_box = QGroupBox("Screen size (% of viewport height)")
        size_form = QFormLayout(size_box)
        self._node_size = self._percent_spin(self._base.node_size_percent)
        self._support_size = self._percent_spin(self._base.support_size_percent)
        self._load_size = self._percent_spin(self._base.load_size_percent)
        self._reaction_size = self._percent_spin(self._base.reaction_size_percent)
        self._mass_size = self._percent_spin(self._base.mass_size_percent)
        self._release_size = self._percent_spin(self._base.release_size_percent)
        size_form.addRow("Nodes", self._node_size)
        size_form.addRow("Supports", self._support_size)
        size_form.addRow("Load arrows", self._load_size)
        size_form.addRow("Reactions", self._reaction_size)
        size_form.addRow("Masses", self._mass_size)
        size_form.addRow("Releases", self._release_size)
        layout.addWidget(size_box)

        text_box = QGroupBox("Text")
        text_form = QFormLayout(text_box)
        self._label_size = QSpinBox()
        self._label_size.setRange(6, 72)
        self._label_size.setSuffix(" px")
        self._label_size.setValue(self._base.label_size_px)
        text_form.addRow("Label height", self._label_size)
        layout.addWidget(text_box)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @staticmethod
    def _percent_spin(value: float) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(0.05, 25.0)
        spin.setDecimals(2)
        spin.setSingleStep(0.1)
        spin.setSuffix(" %")
        spin.setValue(value)
        return spin

    def values(self) -> tuple[bool, bool]:
        """The two label toggles, kept for callers that only need those."""
        return self._show_node_labels.isChecked(), self._show_element_labels.isChecked()

    def view_settings(self) -> ViewSettings:
        """The complete settings with every size and visibility the dialog edits."""
        return self._base.with_changes(
            show_node_labels=self._show_node_labels.isChecked(),
            show_element_labels=self._show_element_labels.isChecked(),
            show_masses=self._show_masses.isChecked(),
            node_size_percent=self._node_size.value(),
            support_size_percent=self._support_size.value(),
            load_size_percent=self._load_size.value(),
            reaction_size_percent=self._reaction_size.value(),
            mass_size_percent=self._mass_size.value(),
            release_size_percent=self._release_size.value(),
            label_size_px=self._label_size.value(),
        )
