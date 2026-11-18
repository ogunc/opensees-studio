"""Design → Generate Notional Loads: the AISC 360 Direct Analysis Method loads."""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import (
    QComboBox,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from opensees_studio.core.design.stability import (
    notional_factor,
    storey_notional_loads,
)
from opensees_studio.core.help import TOPIC_PROPERTY
from opensees_studio.views.float_field import FloatField
from opensees_studio.views.screen_fit import FittedDialog


class NotionalLoadsDialog(FittedDialog):
    """Choose the direction, method and factor of the AISC 360 C2-1 notional loads."""

    def __init__(self, project: Any, parent: QWidget | None = None, method: str = "LRFD") -> None:
        super().__init__(parent)
        self._project = project
        self.setWindowTitle("Generate Notional Loads (DAM)")
        self.setProperty(TOPIC_PROPERTY, "design.notional_loads")
        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(
                "AISC 360 C2-1: a lateral force of <b>Ni = 0.002 α Yi</b> at every "
                "storey, where Yi is the storey gravity load and α is 1.0 in LRFD and "
                "1.6 in ASD. Add the generated patterns to the cases of the Direct "
                "Analysis Method; the stiffness reduction τb is a separate property "
                "modifier."
            )
        )
        form = QFormLayout()
        self._method = QComboBox()
        self._method.addItem("LRFD (α = 1.0)", "LRFD")
        self._method.addItem("ASD (α = 1.6)", "ASD")
        self._method.setCurrentIndex(1 if method.strip().upper() == "ASD" else 0)
        form.addRow("Design method:", self._method)
        self._direction = QComboBox()
        self._direction.addItem("X", 0)
        if project.ndm == 3:
            self._direction.addItem("Y", 1)
            self._direction.addItem("X and Y", "both")
        form.addRow("Direction:", self._direction)
        self._factor = FloatField()
        self._factor.setRange(1e-9, 1.0)
        self._factor.setValue(notional_factor(method=method))
        form.addRow("Factor:", self._factor)
        layout.addLayout(form)
        self._summary = QLabel()
        self._summary.setWordWrap(True)
        layout.addWidget(self._summary)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._method.currentIndexChanged.connect(self._reset_factor)
        self._factor.valueChanged.connect(self._update_summary)
        self._direction.currentIndexChanged.connect(self._update_summary)
        self._update_summary()

    def _reset_factor(self) -> None:
        """Follow the method's α until the user types a different factor."""
        self._factor.setValue(notional_factor(method=self.method()))
        self._update_summary()

    def _directions(self) -> list[int]:
        value = self._direction.currentData()
        return [0, 1] if value == "both" else [int(value)]

    def method(self) -> str:
        """``"LRFD"`` or ``"ASD"``."""
        return str(self._method.currentData())

    def _update_summary(self) -> None:
        lines: list[str] = []
        for direction in self._directions():
            levels = storey_notional_loads(
                self._project,
                factor=self._factor.value(),
                method=self.method(),
                direction=direction,
            )
            total = sum(level.force for level in levels)
            axis = "XY"[direction]
            lines.append(
                f"{axis}: {len(levels)} storey(s), total {total:.6g} "
                f"(weight {sum(level.weight for level in levels):.6g})."
            )
        self._summary.setText("\n".join(lines) if lines else "No storey carries gravity load.")

    def settings(self) -> tuple[list[int], float, str]:
        """``(directions, factor, method)`` as the dialog shows them."""
        return self._directions(), self._factor.value(), self.method()
