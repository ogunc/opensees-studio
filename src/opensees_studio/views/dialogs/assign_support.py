"""Assign Support dialog — apply restraint to selected nodes.

Offers four presets matching SAP/ETABS conventions plus a "Custom"
mode that exposes all six DOF checkboxes. All restraints are stored
in the canonical 6-DOF storage; ``OpenSeesRunner`` slices them to the
model's actual ``ndf`` at translation time.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QGroupBox,
    QLabel,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)


# Preset → 6-tuple (Ux, Uy, Uz, Rx, Ry, Rz)
PRESETS: dict[str, tuple[bool, bool, bool, bool, bool, bool]] = {
    "Free":   (False, False, False, False, False, False),
    "Roller (Z)": (False, False, True,  False, False, False),
    "Pin":    (True,  True,  True,  False, False, False),
    "Fix":    (True,  True,  True,  True,  True,  True),
}


class AssignSupportDialog(QDialog):
    """Modal dialog for choosing a restraint pattern."""

    def __init__(self, n_selected: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Assign Support")
        self._build_ui(n_selected)

    def _build_ui(self, n_selected: int) -> None:
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel(f"Apply to <b>{n_selected}</b> selected node(s)."))

        # Presets
        preset_box = QGroupBox("Preset")
        preset_layout = QVBoxLayout(preset_box)
        self._preset_group = QButtonGroup(self)
        self._preset_buttons: dict[str, QRadioButton] = {}
        for name in PRESETS:
            btn = QRadioButton(name)
            self._preset_buttons[name] = btn
            self._preset_group.addButton(btn)
            preset_layout.addWidget(btn)
        custom_btn = QRadioButton("Custom (use checkboxes below)")
        self._preset_buttons["Custom"] = custom_btn
        self._preset_group.addButton(custom_btn)
        preset_layout.addWidget(custom_btn)
        self._preset_buttons["Pin"].setChecked(True)
        layout.addWidget(preset_box)

        # Custom DOF checkboxes
        dof_box = QGroupBox("DOFs")
        grid = QGridLayout(dof_box)
        self._dof_boxes: list[QCheckBox] = []
        labels = ("Ux", "Uy", "Uz", "Rx", "Ry", "Rz")
        for i, lbl in enumerate(labels):
            cb = QCheckBox(lbl)
            cb.setEnabled(False)
            row, col = divmod(i, 3)
            grid.addWidget(cb, row, col)
            self._dof_boxes.append(cb)
        layout.addWidget(dof_box)

        # Wire preset → checkboxes (purely visual until "Custom" is picked)
        self._preset_group.buttonToggled.connect(self._on_preset_toggled)
        self._on_preset_toggled(self._preset_buttons["Pin"], True)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_preset_toggled(self, btn: QRadioButton, checked: bool) -> None:
        if not checked:
            return
        is_custom = btn is self._preset_buttons["Custom"]
        for cb in self._dof_boxes:
            cb.setEnabled(is_custom)
        if not is_custom:
            preset = PRESETS[btn.text()]
            for cb, val in zip(self._dof_boxes, preset, strict=True):
                cb.setChecked(val)

    # ── result ───────────────────────────────────────────────────────
    def restraint(self) -> tuple[bool, bool, bool, bool, bool, bool]:
        return tuple(cb.isChecked() for cb in self._dof_boxes)  # type: ignore[return-value]
