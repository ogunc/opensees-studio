"""Mode shape animator panel — pick a mode, play sin(2π t / T) loop."""

from __future__ import annotations

import math

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)


class ModeShapeAnimator(QWidget):
    """Drive a sinusoidal modal animation on the renderer.

    Emits :sig:`frameChanged(int mode, float scale, float phase)` at
    ~30 Hz while playing. ``phase`` ∈ [-1, 1] is the multiplier for the
    eigenvector (so the deformation oscillates over one cycle).
    """

    frameChanged = Signal(int, float, float)
    closed = Signal()
    exportRequested = Signal()

    _FPS = 30
    _DEFAULT_PERIOD_S = 1.5  # animation period (one full oscillation)

    def __init__(self, n_modes: int, frequencies_hz: list[float],
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._n_modes = n_modes
        self._freqs = frequencies_hz
        self._t = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_tick)
        self._timer.setInterval(int(1000 / self._FPS))
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(QLabel("<b>Mode Shape Animator</b>"))

        form = QFormLayout()
        self._mode_combo = QComboBox()
        for i in range(self._n_modes):
            f = self._freqs[i] if i < len(self._freqs) else 0.0
            self._mode_combo.addItem(f"Mode {i + 1}  —  f = {f:.4g} Hz", userData=i)
        self._mode_combo.currentIndexChanged.connect(self._emit_static_frame)
        form.addRow("Mode:", self._mode_combo)

        self._scale = QDoubleSpinBox()
        self._scale.setRange(0.01, 100.0)
        self._scale.setValue(1.0)
        self._scale.setSingleStep(0.5)
        self._scale.valueChanged.connect(self._emit_static_frame)
        form.addRow("Scale:", self._scale)

        self._period = QDoubleSpinBox()
        self._period.setRange(0.1, 30.0)
        self._period.setSuffix(" s")
        self._period.setValue(self._DEFAULT_PERIOD_S)
        form.addRow("Animation period:", self._period)

        layout.addLayout(form)

        # Manual scrubber.
        self._scrubber = QSlider(Qt.Orientation.Horizontal)
        self._scrubber.setRange(-100, 100)
        self._scrubber.setValue(100)
        self._scrubber.valueChanged.connect(self._on_scrubber)
        layout.addWidget(QLabel("Phase:"))
        layout.addWidget(self._scrubber)

        btn_row = QHBoxLayout()
        self._play_btn = QPushButton("▶ Play")
        self._play_btn.setCheckable(True)
        self._play_btn.toggled.connect(self._on_play_toggled)
        self._stop_btn = QPushButton("■ Stop")
        self._stop_btn.clicked.connect(self._on_stop)
        self._export_btn = QPushButton("Export…")
        self._export_btn.clicked.connect(self.exportRequested.emit)
        self._back_btn = QPushButton("Back to model")
        self._back_btn.clicked.connect(self._on_back)
        btn_row.addWidget(self._play_btn)
        btn_row.addWidget(self._stop_btn)
        btn_row.addWidget(self._export_btn)
        btn_row.addStretch(1)
        btn_row.addWidget(self._back_btn)
        layout.addLayout(btn_row)
        layout.addStretch(1)

        # Initial static frame at full amplitude.
        self._emit_static_frame()

    # ── public getters (used by export) ─────────────────────────────
    def current_mode(self) -> int:
        return int(self._mode_combo.currentData())

    def current_scale(self) -> float:
        return float(self._scale_spin.value())

    # ── slots ────────────────────────────────────────────────────────
    def _on_play_toggled(self, playing: bool) -> None:
        if playing:
            self._play_btn.setText("⏸ Pause")
            self._timer.start()
        else:
            self._play_btn.setText("▶ Play")
            self._timer.stop()

    def _on_stop(self) -> None:
        self._timer.stop()
        self._play_btn.setChecked(False)
        self._t = 0.0
        self._scrubber.setValue(100)
        self._emit_static_frame()

    def _on_back(self) -> None:
        self._timer.stop()
        self.closed.emit()

    def _on_scrubber(self, value: int) -> None:
        if self._timer.isActive():
            return  # scrubber disabled during play
        phase = value / 100.0
        self.frameChanged.emit(self._mode_combo.currentData(),
                               self._scale.value(), phase)

    def _on_tick(self) -> None:
        self._t += 1.0 / self._FPS
        period = self._period.value()
        phase = math.sin(2.0 * math.pi * self._t / period)
        # Update the scrubber to track the animation.
        self._scrubber.blockSignals(True)
        self._scrubber.setValue(int(round(phase * 100)))
        self._scrubber.blockSignals(False)
        self.frameChanged.emit(self._mode_combo.currentData(),
                               self._scale.value(), phase)

    def _emit_static_frame(self) -> None:
        phase = self._scrubber.value() / 100.0
        self.frameChanged.emit(self._mode_combo.currentData(),
                               self._scale.value(), phase)
