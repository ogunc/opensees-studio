"""Force diagram dock — pick a component (N/V2/V3/M2/M3/T) + scale slider."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from opensees_studio.services.element_forces import ForceComponent


class ForceDiagramView(QWidget):
    """Compact controls for live-updating an element-force diagram.

    Emits :attr:`changed` on any setting change with ``(component, scale)``;
    the host (MainWindow) listens and re-renders the overlay.
    Emits :attr:`closed` when the user clicks "Hide".
    """

    changed = Signal(object, float)         # (ForceComponent, scale)
    closed = Signal()

    def __init__(self, suggested_scale: float = 1.0,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._build_ui(suggested_scale)

    def _build_ui(self, suggested_scale: float) -> None:
        root = QVBoxLayout(self)

        group = QGroupBox("Diagram Settings", self)
        form = QFormLayout(group)

        self._component = QComboBox()
        for comp in ForceComponent:
            self._component.addItem(comp.value, comp)
        form.addRow("Component:", self._component)

        # Scale: log-friendly spinbox + slider that shares the value.
        self._scale_spin = QDoubleSpinBox()
        self._scale_spin.setRange(1e-9, 1e9)
        self._scale_spin.setDecimals(6)
        self._scale_spin.setValue(suggested_scale)
        self._scale_spin.setSingleStep(suggested_scale * 0.1 if suggested_scale > 0 else 0.01)
        form.addRow("Scale:", self._scale_spin)

        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._slider.setRange(1, 1000)
        self._slider.setValue(500)          # midpoint = suggested scale
        self._scale_base = max(suggested_scale, 1e-12)
        form.addRow("", self._slider)

        root.addWidget(group)

        info = QLabel(
            "Scale is multiplied into the force values to convert them "
            "to model-space lengths. Slider sweeps 0.01× to 100× of the "
            "suggested scale.",
        )
        info.setWordWrap(True)
        root.addWidget(info)

        self._hide_btn = QPushButton("Hide diagram")
        self._hide_btn.clicked.connect(self.closed.emit)
        root.addWidget(self._hide_btn)
        root.addStretch(1)

        # Wiring: any control change → emit unified `changed` signal.
        self._component.currentIndexChanged.connect(self._emit)
        self._scale_spin.valueChanged.connect(self._on_spin)
        self._slider.valueChanged.connect(self._on_slider)

        # Push initial state out so the host renders something immediately.
        self._emit()

    # ── slots ───────────────────────────────────────────────────────
    def _on_spin(self, value: float) -> None:
        # Update slider position WITHOUT firing its signal.
        self._scale_base = max(value, 1e-12)
        self._slider.blockSignals(True)
        self._slider.setValue(500)
        self._slider.blockSignals(False)
        self._emit()

    def _on_slider(self, value: int) -> None:
        # Map 1..1000 to 0.01×..100× of the base, log-spaced.
        # value=500 → factor=1.0; value=1 → 0.01; value=1000 → 100.
        import math
        factor = 10.0 ** (((value - 500) / 500.0) * 2.0)
        new_scale = self._scale_base * factor
        self._scale_spin.blockSignals(True)
        self._scale_spin.setValue(new_scale)
        self._scale_spin.blockSignals(False)
        self.changed.emit(self._component.currentData(), new_scale)

    def _emit(self) -> None:
        self.changed.emit(self._component.currentData(), self._scale_spin.value())
