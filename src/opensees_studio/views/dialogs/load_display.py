"""Display → Show Load Assigns…: which load pattern and which kinds of load the canvas draws."""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from opensees_studio.core import PlainLoadPattern
from opensees_studio.core.help import TOPIC_PROPERTY
from opensees_studio.core.load_display import KIND_LABELS
from opensees_studio.core.view_settings import ViewSettings
from opensees_studio.views.screen_fit import FittedDialog

ALL_PATTERNS = "All load patterns (one colour each, stacked)"

#: The view-setting field of each kind of load, in the order the dialog lists them.
_KIND_FIELDS: dict[str, str] = {
    "joint": "show_joint_loads",
    "frame_point": "show_frame_point_loads",
    "frame_distributed": "show_frame_distributed_loads",
    "shell": "show_shell_loads",
}


class LoadDisplayDialog(FittedDialog):
    """Pick one load pattern or all of them, the kinds of load, and the values."""

    def __init__(
        self,
        patterns: list[Any],
        view_settings: ViewSettings,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Show Load Assigns")
        self.setProperty(TOPIC_PROPERTY, "display.load_assigns")
        self._base = view_settings
        layout = QVBoxLayout(self)

        self._pattern = QComboBox()
        self._pattern.addItem(ALL_PATTERNS, None)
        for pattern in patterns:
            if isinstance(pattern, PlainLoadPattern):
                self._pattern.addItem(pattern.name or f"Pattern {pattern.id}", pattern.id)
        index = self._pattern.findData(view_settings.load_pattern_id)
        self._pattern.setCurrentIndex(max(index, 0))
        form = QFormLayout()
        form.addRow("Load pattern", self._pattern)
        layout.addLayout(form)

        kinds = QGroupBox("Kinds of load")
        kinds_layout = QVBoxLayout(kinds)
        self._kinds: dict[str, QCheckBox] = {}
        for kind, field in _KIND_FIELDS.items():
            box = QCheckBox(KIND_LABELS[kind])
            box.setChecked(bool(getattr(view_settings, field)))
            kinds_layout.addWidget(box)
            self._kinds[kind] = box
        layout.addWidget(kinds)

        self._values = QCheckBox("Show values (10 kN/m, 50 kN, …)")
        self._values.setChecked(view_settings.show_load_values)
        layout.addWidget(self._values)

        note = QLabel(
            "With all load patterns each one has its colour, named in the legend, and "
            "loads on the same member or joint are stacked so none hides another. "
            "Arrow sizes follow the magnitudes drawn."
        )
        note.setWordWrap(True)
        layout.addWidget(note)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # ── public API (also used by tests) ──────────────────────────────
    def set_pattern(self, pattern_id: int | None) -> None:
        self._pattern.setCurrentIndex(max(self._pattern.findData(pattern_id), 0))

    def set_kind(self, kind: str, shown: bool) -> None:
        self._kinds[kind].setChecked(shown)

    def set_show_values(self, shown: bool) -> None:
        self._values.setChecked(shown)

    def changes(self) -> dict[str, object]:
        """The view-setting fields the dialog sets; loads are switched on too."""
        changes: dict[str, object] = {
            "show_loads": True,
            "load_pattern_id": self._pattern.currentData(),
            "show_load_values": self._values.isChecked(),
        }
        for kind, field in _KIND_FIELDS.items():
            changes[field] = self._kinds[kind].isChecked()
        return changes
