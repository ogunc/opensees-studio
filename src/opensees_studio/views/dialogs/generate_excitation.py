"""Generate a synthetic excitation (sine or sine-beat) as a project time series.

Opened from the Ground Motions dialog. The parameters drive a live
preview of the acceleration trace and of its response spectrum in g,
overlaid on the project's target spectrum when one exists. Accepting
returns the core entity (a ``TrigTimeSeries`` for a plain sine, an
embedded generated ``PathTimeSeries`` otherwise); the caller applies it
through one undoable command. Reopening an existing generated series
restores its stored parameters. Generated inputs are never catalog
records.
"""

from __future__ import annotations

import contextlib
from typing import Any

import pyqtgraph as pg
from PySide6.QtCore import QLocale, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from opensees_studio.core import BEAT_PRESETS, PathTimeSeries, TimeSeries, TrigTimeSeries
from opensees_studio.viewmodels.ground_motion_catalog_vm import (
    GENERATED_UNIT_CHOICES,
    GENERATOR_CHOICES,
    PLOT_PERIODS,
    GroundMotionCatalogViewModel,
)

_CUSTOM_PRESET = "Custom"


class GenerateExcitationDialog(QDialog):
    """Sine / sine-beat generator with live trace and spectrum preview."""

    def __init__(
        self,
        catalog: GroundMotionCatalogViewModel,
        existing: TimeSeries | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._catalog = catalog
        self._existing = existing
        self._trace_curve: Any | None = None
        self._spectrum_curve: Any | None = None
        self._target_curve: Any | None = None
        self._syncing = False
        self.setWindowTitle(
            "Generate excitation" if existing is None else f"Edit generated series #{existing.id}"
        )
        self.resize(900, 640)
        self._build_ui()
        if existing is not None:
            self._load_existing(existing)
        self._update_preview()

    # ---- construction ------------------------------------------------------
    @staticmethod
    def _spin(lo: float, hi: float, value: float, decimals: int, step: float) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setLocale(QLocale(QLocale.Language.C))
        spin.setDecimals(decimals)
        spin.setRange(lo, hi)
        spin.setSingleStep(step)
        spin.setValue(value)
        return spin

    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        left = QVBoxLayout()
        form = QFormLayout()
        self._name = QLineEdit()
        self._name.setPlaceholderText("(automatic)")
        form.addRow("Name:", self._name)
        self._kind = QComboBox()
        for key, label in GENERATOR_CHOICES:
            self._kind.addItem(label, key)
        self._kind.currentIndexChanged.connect(self._on_kind_changed)
        form.addRow("Type:", self._kind)
        self._amplitude = self._spin(1e-6, 1e6, 0.5, decimals=4, step=0.05)
        form.addRow("Amplitude (peak):", self._amplitude)
        self._units = QComboBox()
        for key, label in GENERATED_UNIT_CHOICES:
            self._units.addItem(label, key)
        self._units.setToolTip("Unit of the amplitude; the series factor carries the conversion.")
        form.addRow("Amplitude units:", self._units)
        self._frequency = self._spin(0.01, 200.0, 1.0, decimals=3, step=0.1)
        form.addRow("Frequency [Hz]:", self._frequency)
        self._dt = self._spin(1e-5, 1.0, 0.005, decimals=5, step=0.001)
        self._dt.setToolTip(
            "Sampling interval of an embedded Path series (a plain sine is continuous)."
        )
        form.addRow("dt [s]:", self._dt)
        left.addLayout(form)

        self._sine_group = QGroupBox("Continuous sine")
        sine_form = QFormLayout(self._sine_group)
        self._duration = self._spin(0.01, 1e4, 10.0, decimals=3, step=0.5)
        sine_form.addRow("Duration [s]:", self._duration)
        self._ramp_in = self._spin(0.0, 1e3, 0.0, decimals=2, step=0.5)
        sine_form.addRow("Ramp-in [cycles]:", self._ramp_in)
        self._ramp_out = self._spin(0.0, 1e3, 0.0, decimals=2, step=0.5)
        sine_form.addRow("Ramp-out [cycles]:", self._ramp_out)
        left.addWidget(self._sine_group)

        self._beat_group = QGroupBox("Sine-beat")
        beat_form = QFormLayout(self._beat_group)
        self._preset = QComboBox()
        self._preset.addItem(_CUSTOM_PRESET, None)
        for i, preset in enumerate(BEAT_PRESETS):
            self._preset.addItem(preset.label, i)
        self._preset.setToolTip("Standard-derived values stay editable; confirm them before use.")
        self._preset.currentIndexChanged.connect(self._on_preset_changed)
        beat_form.addRow("Preset:", self._preset)
        self._cycles = QSpinBox()
        self._cycles.setRange(1, 1000)
        self._cycles.setValue(10)
        beat_form.addRow("Cycles per beat:", self._cycles)
        self._beats = QSpinBox()
        self._beats.setRange(1, 1000)
        self._beats.setValue(5)
        beat_form.addRow("Number of beats:", self._beats)
        self._pause = self._spin(0.0, 1e3, 2.0, decimals=3, step=0.5)
        beat_form.addRow("Pause between beats [s]:", self._pause)
        left.addWidget(self._beat_group)

        self._info = QLabel("")
        self._info.setWordWrap(True)
        left.addWidget(self._info)
        left.addStretch(1)
        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)
        left.addWidget(self._buttons)
        root.addLayout(left, 0)

        plots = QVBoxLayout()
        pg.setConfigOptions(antialias=True)
        self._trace_plot = pg.PlotWidget()
        self._trace_plot.setBackground("#1e1e1e")
        self._trace_plot.showGrid(x=True, y=True, alpha=0.3)
        self._trace_plot.setLabel("bottom", "Time [s]")
        self._trace_plot.setLabel("left", "Acceleration")
        plots.addWidget(self._trace_plot, 1)
        self._spectrum_plot = pg.PlotWidget()
        self._spectrum_plot.setBackground("#1e1e1e")
        self._spectrum_plot.showGrid(x=True, y=True, alpha=0.3)
        self._spectrum_plot.setLogMode(x=True, y=False)
        self._spectrum_plot.setLabel("bottom", "Period [s]")
        self._spectrum_plot.setLabel("left", "Sa [g], 5 % damping")
        self._spectrum_plot.addLegend(offset=(-10, 10))
        plots.addWidget(self._spectrum_plot, 1)
        root.addLayout(plots, 1)

        for spin in (
            self._amplitude,
            self._frequency,
            self._dt,
            self._duration,
            self._ramp_in,
            self._ramp_out,
            self._pause,
        ):
            spin.valueChanged.connect(self._on_parameter_changed)
        for spin in (self._cycles, self._beats):
            spin.valueChanged.connect(self._on_parameter_changed)
        self._units.currentIndexChanged.connect(self._update_preview)
        self._preset.setCurrentIndex(1 if BEAT_PRESETS else 0)
        self._on_kind_changed()

    # ---- state ---------------------------------------------------------------
    def _on_kind_changed(self, *_: object) -> None:
        beat = self._kind.currentData() == "sine-beat"
        self._sine_group.setVisible(not beat)
        self._beat_group.setVisible(beat)
        self._update_preview()

    def _on_preset_changed(self, *_: object) -> None:
        index = self._preset.currentData()
        if index is None:
            return
        preset = BEAT_PRESETS[index]
        self._syncing = True
        try:
            self._cycles.setValue(preset.cycles_per_beat)
            self._beats.setValue(preset.n_beats)
            self._pause.setValue(preset.pause)
        finally:
            self._syncing = False
        self._update_preview()

    def _on_parameter_changed(self, *_: object) -> None:
        if self._syncing:
            return
        sender = self.sender()
        if (
            sender in (self._cycles, self._beats, self._pause)
            and self._preset.currentData() is not None
        ):
            self._syncing = True
            try:
                self._preset.setCurrentIndex(0)  # edited away from the preset
            finally:
                self._syncing = False
        self._update_preview()

    def set_kind(self, kind: str) -> None:
        self._kind.setCurrentIndex(max(0, self._kind.findData(kind)))

    def set_preset(self, label: str) -> None:
        self._preset.setCurrentIndex(max(0, self._preset.findText(label)))

    def preset_label(self) -> str:
        return self._preset.currentText()

    def descriptor(self) -> dict[str, Any]:
        """The generator parameters as shown, plus the amplitude units."""
        kind = self._kind.currentData()
        base: dict[str, Any] = {
            "kind": kind,
            "amplitude": self._amplitude.value(),
            "frequency": self._frequency.value(),
            "dt": self._dt.value(),
            "units": self._units.currentData(),
        }
        if kind == "sine":
            base.update(
                duration=self._duration.value(),
                ramp_in_cycles=self._ramp_in.value(),
                ramp_out_cycles=self._ramp_out.value(),
            )
        else:
            base.update(
                cycles_per_beat=self._cycles.value(),
                n_beats=self._beats.value(),
                pause=self._pause.value(),
            )
        return base

    def load_descriptor(self, descriptor: dict[str, Any]) -> None:
        """Populate the widgets from a stored descriptor (units default to g)."""
        self._syncing = True
        try:
            self.set_kind(str(descriptor.get("kind", "sine")))
            self._amplitude.setValue(float(descriptor.get("amplitude", 0.5)))
            self._frequency.setValue(float(descriptor.get("frequency", 1.0)))
            self._dt.setValue(float(descriptor.get("dt", 0.005)))
            self._units.setCurrentIndex(max(0, self._units.findData(descriptor.get("units", "g"))))
            self._duration.setValue(float(descriptor.get("duration", 10.0)))
            self._ramp_in.setValue(float(descriptor.get("ramp_in_cycles", 0.0)))
            self._ramp_out.setValue(float(descriptor.get("ramp_out_cycles", 0.0)))
            self._cycles.setValue(int(descriptor.get("cycles_per_beat", 10)))
            self._beats.setValue(int(descriptor.get("n_beats", 5)))
            self._pause.setValue(float(descriptor.get("pause", 2.0)))
            self._preset.setCurrentIndex(self._matching_preset())
        finally:
            self._syncing = False
        self._update_preview()

    def _matching_preset(self) -> int:
        for i, preset in enumerate(BEAT_PRESETS):
            if (
                self._cycles.value() == preset.cycles_per_beat
                and self._beats.value() == preset.n_beats
                and self._pause.value() == preset.pause
            ):
                return i + 1
        return 0

    def _load_existing(self, ts: TimeSeries) -> None:
        self._name.setText(ts.name)
        descriptor = self._catalog.generator_descriptor_of(ts)
        if descriptor is not None:
            self.load_descriptor(descriptor)

    # ---- preview ---------------------------------------------------------------
    def _clear_curves(self) -> None:
        for attr, plot in (
            ("_trace_curve", self._trace_plot),
            ("_spectrum_curve", self._spectrum_plot),
            ("_target_curve", self._spectrum_plot),
        ):
            curve = getattr(self, attr)
            if curve is not None:
                with contextlib.suppress(Exception):
                    plot.removeItem(curve)
                setattr(self, attr, None)

    def _update_preview(self, *_: object) -> None:
        self._clear_curves()
        descriptor = self.descriptor()
        try:
            dt, accel = self._catalog.generated_accel(descriptor)
            spectrum = self._catalog.generated_spectrum(descriptor)
        except ValueError as exc:
            self._info.setText(str(exc))
            self._buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
            return
        times = [i * dt for i in range(accel.size)]
        self._trace_curve = self._trace_plot.plot(times, accel, pen=pg.mkPen("#1f77b4", width=1))
        self._trace_plot.enableAutoRange()
        self._spectrum_curve = self._spectrum_plot.plot(
            spectrum.periods, spectrum.sa, pen=pg.mkPen("#ff7f0e", width=1.5), name="Generated"
        )
        target = self._catalog.active_target()
        if target is not None:
            self._target_curve = self._spectrum_plot.plot(
                PLOT_PERIODS,
                target.sa_at(PLOT_PERIODS),
                pen=pg.mkPen("#ffffff", width=2, style=Qt.PenStyle.DashLine),
                name="Target",
            )
        self._spectrum_plot.enableAutoRange()
        stored = (
            "native Trig series"
            if descriptor["kind"] == "sine"
            and not (descriptor["ramp_in_cycles"] or descriptor["ramp_out_cycles"])
            else f"embedded Path series, {accel.size} points"
        )
        self._info.setText(
            f"{accel.size} samples, {(accel.size - 1) * dt:g} s, peak {float(abs(accel).max()):g} "
            f"{descriptor['units']}. Stored as {stored}."
        )
        self._buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(True)

    def preview_curve_data(self) -> tuple[Any, Any] | None:
        return self._trace_curve.getData() if self._trace_curve is not None else None

    def spectrum_curve_count(self) -> int:
        return (1 if self._spectrum_curve is not None else 0) + (
            1 if self._target_curve is not None else 0
        )

    def info_text(self) -> str:
        return self._info.text()

    # ---- result ----------------------------------------------------------------
    def time_series(self) -> TimeSeries:
        """The entity to add or to swap in for the edited series (``ValueError`` on bad input)."""
        series_id = self._existing.id if self._existing is not None else None
        ts = self._catalog.build_generated_series(
            self.descriptor(), series_id=series_id, name=self._name.text().strip()
        )
        assert isinstance(ts, PathTimeSeries | TrigTimeSeries)
        return ts
