"""Force diagram dock — pick a component (N/V2/V3/M2/M3/T) + scale slider.

Exposes two signals:
- ``componentChanged(component)`` — user picked a different component.
  The host should compute a fresh suggested scale for the new component
  and call :meth:`set_scale_base` so the slider re-centres around it.
- ``changed(component, scale)`` — final per-frame value the renderer
  should use. Fires whenever component, scale spin, or slider changes.
"""

from __future__ import annotations

import math

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
    """Compact controls for live-updating an element-force diagram."""

    componentChanged = Signal(object)       # ForceComponent
    changed = Signal(object, float)         # (ForceComponent, scale)
    closed = Signal()

    def __init__(self, suggested_scale: float = 1.0,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._scale_base = max(suggested_scale, 1e-12)
        self._build_ui(suggested_scale)

    # ── public API ──────────────────────────────────────────────────
    def set_scale_base(self, suggested: float) -> None:
        """Replace the slider's reference scale (called when the host
        recomputes auto-scale after a component change). The slider is
        re-centred at midpoint and a fresh ``changed`` signal fires.
        """
        self._scale_base = max(suggested, 1e-12)
        # Update both controls without re-firing each other.
        self._scale_spin.blockSignals(True)
        self._scale_spin.setValue(self._scale_base)
        self._scale_spin.blockSignals(False)
        self._slider.blockSignals(True)
        self._slider.setValue(500)
        self._slider.blockSignals(False)
        self._emit_changed()

    def current_component(self) -> ForceComponent:
        return self._component.currentData()

    # ── UI build ────────────────────────────────────────────────────
    def _build_ui(self, suggested_scale: float) -> None:
        root = QVBoxLayout(self)

        group = QGroupBox("Diagram Settings", self)
        form = QFormLayout(group)

        self._component = QComboBox()
        for comp in ForceComponent:
            self._component.addItem(comp.value, comp)
        form.addRow("Component:", self._component)

        self._scale_spin = QDoubleSpinBox()
        self._scale_spin.setRange(1e-9, 1e9)
        self._scale_spin.setDecimals(6)
        self._scale_spin.setValue(suggested_scale)
        self._scale_spin.setSingleStep(
            suggested_scale * 0.1 if suggested_scale > 0 else 0.01,
        )
        form.addRow("Scale:", self._scale_spin)

        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._slider.setRange(1, 1000)
        self._slider.setValue(500)              # midpoint = suggested scale
        form.addRow("", self._slider)

        root.addWidget(group)

        info = QLabel(
            "Scale auto-adjusts when you switch components. The slider "
            "sweeps 0.01× to 100× of that suggested scale.",
        )
        info.setWordWrap(True)
        root.addWidget(info)

        self._hide_btn = QPushButton("Hide diagram")
        self._hide_btn.clicked.connect(self.closed.emit)
        root.addWidget(self._hide_btn)
        root.addStretch(1)

        # Wiring.
        # Component change is special: we emit `componentChanged` first so
        # the host can recompute the scale base, THEN the host call to
        # set_scale_base() emits the final `changed` signal with the right
        # values. We deliberately don't emit `changed` here on component
        # change to avoid one render with the stale scale.
        self._component.currentIndexChanged.connect(self._on_component_changed)
        self._scale_spin.valueChanged.connect(self._on_spin)
        self._slider.valueChanged.connect(self._on_slider)

        # Push initial render with the suggested scale.
        self._emit_changed()

    # ── slots ───────────────────────────────────────────────────────
    def _on_component_changed(self, _idx: int) -> None:
        comp = self._component.currentData()
        # Tell the host to recompute the scale base for this component.
        # The host (MainWindow) is responsible for calling set_scale_base()
        # back, which triggers the final `changed` emission with the right
        # scale. If no host is connected, our scale stays put and we still
        # emit `changed` so the renderer at least redraws with current scale.
        self.componentChanged.emit(comp)
        # Defensive fallback: if no host connected, ensure UI isn't dead.
        # (Cheap to re-emit; renderer dedupes on identical input.)
        self._emit_changed()

    def _on_spin(self, value: float) -> None:
        # User typed a value: treat it as the new scale base.
        self._scale_base = max(value, 1e-12)
        self._slider.blockSignals(True)
        self._slider.setValue(500)
        self._slider.blockSignals(False)
        self._emit_changed()

    def _on_slider(self, value: int) -> None:
        # value=500 → factor=1.0; value=1 → 0.01×; value=1000 → 100×.
        factor = 10.0 ** (((value - 500) / 500.0) * 2.0)
        new_scale = self._scale_base * factor
        self._scale_spin.blockSignals(True)
        self._scale_spin.setValue(new_scale)
        self._scale_spin.blockSignals(False)
        self.changed.emit(self._component.currentData(), new_scale)

    def _emit_changed(self) -> None:
        self.changed.emit(self._component.currentData(), self._scale_spin.value())
