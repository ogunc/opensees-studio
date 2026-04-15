"""Mirror dialog — copy selection reflected across a global plane."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QLabel,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)


class MirrorDialog(QDialog):
    """Dialog for choosing a reflection plane."""

    def __init__(self, n_nodes: int, n_elements: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Mirror")
        self._build_ui(n_nodes, n_elements)

    def _build_ui(self, n_nodes: int, n_elements: int) -> None:
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            f"Mirror <b>{n_nodes}</b> node(s) and <b>{n_elements}</b> element(s)."
        ))
        layout.addWidget(QLabel(
            "<i>Only elements whose endpoints are both in the selection are copied.</i>"
        ))

        box = QGroupBox("Reflection plane (passes through origin)")
        box_layout = QVBoxLayout(box)
        self._group = QButtonGroup(self)
        self._buttons: dict[str, QRadioButton] = {}
        for label, hint in (
            ("XY", "z → -z   (mirror up-down)"),
            ("YZ", "x → -x   (mirror left-right in X)"),
            ("XZ", "y → -y   (mirror front-back in Y)"),
        ):
            btn = QRadioButton(f"{label}  —  {hint}")
            self._buttons[label] = btn
            self._group.addButton(btn)
            box_layout.addWidget(btn)
        self._buttons["YZ"].setChecked(True)
        layout.addWidget(box)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def plane(self) -> str:
        for name, btn in self._buttons.items():
            if btn.isChecked():
                return name
        return "YZ"
