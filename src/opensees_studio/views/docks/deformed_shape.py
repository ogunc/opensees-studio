"""Deformed shape control panel — slider drives the renderer's scale."""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    pass


class DeformedShapeView(QWidget):
    """Controls the renderer's deformed-shape display.

    Emits :sig:`scaleChanged(float)` whenever the user moves the slider
    or types a new value. Emits :sig:`closed` when the user clicks
    "Back to Model".
    """

    scaleChanged = Signal(float)
    closed = Signal()

    def __init__(self, suggested_scale: float = 1.0,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._suggested = max(suggested_scale, 1e-6)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(QLabel("<b>Deformed Shape</b>"))
        layout.addWidget(QLabel(
            "<i>The slider scales displacement around the suggested factor.</i>"
        ))

        form = QFormLayout()

        # Suggested-scale display (read-only).
        self._suggested_label = QLabel(f"{self._suggested:g}")
        form.addRow("Suggested:", self._suggested_label)

        # Multiplier ranging 0.1× — 10× the suggested scale.
        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._slider.setRange(1, 1000)   # represents 0.01 — 10.00
        self._slider.setValue(100)        # 1.00 ×
        self._slider.valueChanged.connect(self._on_slider)

        self._spin = QDoubleSpinBox()
        self._spin.setRange(0.001, 1e6)
        self._spin.setDecimals(4)
        self._spin.setValue(self._suggested)
        self._spin.valueChanged.connect(self._on_spin)
        form.addRow("Scale (current):", self._spin)
        layout.addLayout(form)

        layout.addWidget(self._slider)

        btn_row = QHBoxLayout()
        self._back_btn = QPushButton("Back to model")
        self._back_btn.clicked.connect(self.closed.emit)
        btn_row.addStretch(1)
        btn_row.addWidget(self._back_btn)
        layout.addLayout(btn_row)
        layout.addStretch(1)

    # ── slots ────────────────────────────────────────────────────────
    def _on_slider(self, value: int) -> None:
        # Slider 1..1000 → multiplier 0.01..10.0 of suggested
        multiplier = value / 100.0
        scale = self._suggested * multiplier
        self._spin.blockSignals(True)
        self._spin.setValue(scale)
        self._spin.blockSignals(False)
        self.scaleChanged.emit(scale)

    def _on_spin(self, value: float) -> None:
        if self._suggested > 0:
            multiplier = value / self._suggested
            slider_val = max(1, min(1000, int(round(multiplier * 100))))
            self._slider.blockSignals(True)
            self._slider.setValue(slider_val)
            self._slider.blockSignals(False)
        self.scaleChanged.emit(value)

    @property
    def current_scale(self) -> float:
        return self._spin.value()
