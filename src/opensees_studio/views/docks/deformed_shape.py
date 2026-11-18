"""Deformed shape control panel — slider drives the renderer's scale."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from opensees_studio.core import UnitConverter
from opensees_studio.views.float_field import FloatField

if TYPE_CHECKING:
    pass


class DeformedShapeView(QWidget):
    """Controls the renderer's deformed-shape display.

    Emits :sig:`scaleChanged(float)` whenever the user moves the slider
    or types a new value. Emits :sig:`closed` when the user clicks
    "Back to Model". For a result with a maximum and a minimum (an envelope
    load combination) :meth:`show_bounds` adds a Max/Min picker, and
    :sig:`boundChanged(str)` fires with ``"max"`` or ``"min"``.
    """

    scaleChanged = Signal(float)
    boundChanged = Signal(str)
    closed = Signal()

    def __init__(self, suggested_scale: float = 1.0, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._suggested = max(suggested_scale, 1e-6)
        self._converter = UnitConverter()
        self._peak: float | None = None
        self._has_bounds = False
        self._build_ui()
        self._refresh_peak_label()

    # ── public API ──────────────────────────────────────────────────
    def set_peak_displacement(self, peak: float | None) -> None:
        """Report the largest nodal displacement of the shown results, in model units.

        The drawn shape stays in model units — displacing only the deformation
        would put it a factor of a thousand away from the geometry it deforms —
        so this number is the part of the deformation a display-unit change can
        move, and it does.
        """
        self._peak = peak
        self._refresh_peak_label()

    def show_bounds(self, visible: bool) -> None:
        """Offer the Max/Min picker (results with two bounds) or hide it."""
        self._has_bounds = visible
        self._bound.setVisible(visible)
        self._bound_label.setVisible(visible)

    def current_bound(self) -> str:
        """``"max"`` or ``"min"``: the bound the shape draws (``"max"`` when there is one)."""
        return str(self._bound.currentData()) if self._has_bounds else "max"

    def set_units(self, converter: UnitConverter) -> None:
        """Show the reported displacement in the converter's display units."""
        self._converter = converter
        self._refresh_peak_label()

    def _refresh_peak_label(self) -> None:
        if not hasattr(self, "_peak_label"):
            return
        if self._peak is None:
            self._peak_label.setText("—")
            return
        value = self._peak * self._converter.length
        self._peak_label.setText(f"{value:.4g} {self._converter.labels.length}")

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(QLabel("<b>Deformed Shape</b>"))
        layout.addWidget(
            QLabel("<i>The slider scales displacement around the suggested factor.</i>")
        )

        form = QFormLayout()

        # Suggested-scale display (read-only).
        self._suggested_label = QLabel(f"{self._suggested:g}")
        form.addRow("Suggested:", self._suggested_label)

        # Which bound of an envelope the shape draws (hidden for one-valued results).
        self._bound = QComboBox()
        self._bound.addItem("Max", "max")
        self._bound.addItem("Min", "min")
        self._bound.currentIndexChanged.connect(
            lambda _i: self.boundChanged.emit(self.current_bound())
        )
        self._bound_label = QLabel("Bound:")
        form.addRow(self._bound_label, self._bound)
        self._bound.setVisible(False)
        self._bound_label.setVisible(False)

        # Largest nodal displacement of the current results, in display units.
        self._peak_label = QLabel("—")
        form.addRow("Peak displacement:", self._peak_label)

        # Multiplier ranging 0.1× — 10× the suggested scale.
        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._slider.setRange(1, 1000)  # represents 0.01 — 10.00
        self._slider.setValue(100)  # 1.00 ×
        self._slider.valueChanged.connect(self._on_slider)

        self._spin = FloatField()
        self._spin.setRange(0.001, 1e6)
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
            slider_val = max(1, min(1000, round(multiplier * 100)))
            self._slider.blockSignals(True)
            self._slider.setValue(slider_val)
            self._slider.blockSignals(False)
        self.scaleChanged.emit(value)

    @property
    def current_scale(self) -> float:
        return self._spin.value()
