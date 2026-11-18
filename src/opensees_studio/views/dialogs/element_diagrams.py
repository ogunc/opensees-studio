"""Non-modal window with one member's diagrams in a 3 x 3 grid.

Opened by right-clicking a frame element while a force diagram or a deformed
shape is on screen. The nine panels are:

* row 1: axial force N; shear V2; shear V3;
* row 2: torsion T; moment M2; moment M3;
* row 3: absolute/relative deformation; distributed loads wx/wy/wz; point loads
  Px/Py/Pz.

Each panel labels its extreme values. A result picker switches between the
stored cases and the load combinations without leaving the window, a units
picker changes the display system, and a distance box places a vertical cursor
on every panel and reports the value at that section.

The data comes from :mod:`opensees_studio.services.element_diagrams`; this
module only draws it and converts model units to the display units.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from opensees_studio.core import UnitConverter, UnitSystem
from opensees_studio.services.element_diagrams import (
    ElementDiagramBundle,
    LoadSegment,
    PointLoad,
)
from opensees_studio.services.element_forces import ForceComponent
from opensees_studio.views.plot_style import add_legend, axis_label, readable_plot

_COMPONENT_COLORS = {
    ForceComponent.N: "#1f77b4",
    ForceComponent.V2: "#ff7f0e",
    ForceComponent.V3: "#2ca02c",
    ForceComponent.T: "#9467bd",
    ForceComponent.M2: "#d62728",
    ForceComponent.M3: "#8c564b",
}

_LOAD_COLORS = ("#1f77b4", "#ff7f0e", "#2ca02c")
_ZERO_PEN = pg.mkPen("#888888", width=1)
_QUERY_PEN = pg.mkPen("#ffffff", width=1, style=Qt.PenStyle.DotLine)


def _unit_text(text: str) -> str:
    """Unit labels without symbols the application font cannot draw."""
    return text.replace("·", "*").replace("×", "x").replace("²", "^2").replace("³", "^3")


class _DiagramPanel(QWidget):
    """A titled plot with a value-at-cursor line and a note under it."""

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        header = QHBoxLayout()
        self.title = QLabel(f"<b>{title}</b>")
        self.value = QLabel("")
        self.value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.value.setWordWrap(True)
        header.addWidget(self.title)
        header.addStretch(1)
        header.addWidget(self.value, 2)
        layout.addLayout(header)

        self.plot = readable_plot()
        self.plot.setMinimumWidth(360)
        self.plot.setMinimumHeight(200)
        layout.addWidget(self.plot, 1)

        self.note = QLabel("")
        self.note.setWordWrap(True)
        self.note.setStyleSheet(
            f"color: {self.palette().color(QPalette.ColorRole.WindowText).name()};"
        )
        layout.addWidget(self.note)

        self._legend = None
        self._curves: list[tuple[np.ndarray, np.ndarray, str, str]] = []
        self._query_line: pg.InfiniteLine | None = None
        self._query_value: Callable[[float], str] | None = None
        self._max_labels: list[pg.TextItem] = []
        self._unit_length: str = ""

    def reset(self) -> None:
        self.plot.clear()
        self._legend = None
        self.note.setText("")
        self.value.setText("")
        self._curves = []
        self._query_line = None
        self._query_value = None
        self._max_labels = []

    def set_note(self, text: str) -> None:
        self.note.setText(text)

    def show_empty(self, text: str) -> None:
        """Show a reason instead of a plot with default axes."""
        self.set_note(text)
        self.plot.setXRange(0.0, 1.0, padding=0.0)
        self.plot.setYRange(-1.0, 1.0, padding=0.0)

    def legend(self) -> Any:
        if self._legend is None:
            self._legend = add_legend(self.plot)
        return self._legend

    def set_curves(self, curves: list[tuple[np.ndarray, np.ndarray, str, str]]) -> None:
        """Remember the plotted curves for the value at the cursor."""
        self._curves = curves

    def set_query_value(self, callback: Callable[[float], str]) -> None:
        """Use ``callback(x_display)`` instead of interpolating the curves."""
        self._query_value = callback

    def set_query(self, x_display: float, x_max: float) -> None:
        """Place the vertical cursor and show the value at ``x_display``."""
        if self._query_line is not None:
            self.plot.removeItem(self._query_line)
            self._query_line = None
        if x_max > 0.0:
            self._query_line = pg.InfiniteLine(
                pos=x_display,
                angle=90,
                movable=False,
                pen=_QUERY_PEN,
            )
            self.plot.addItem(self._query_line, ignoreBounds=True)
        self._update_value(x_display)

    def _update_value(self, x_display: float) -> None:
        if self._query_value is not None:
            self.value.setText(self._query_value(x_display))
            return
        parts: list[str] = []
        for x, y, label, unit in self._curves:
            finite = np.isfinite(x) & np.isfinite(y)
            if not finite.any():
                continue
            xs = x[finite]
            ys = y[finite]
            order = np.argsort(xs, kind="stable")
            xs = xs[order]
            ys = ys[order]
            value = float(np.interp(x_display, xs, ys))
            parts.append(f"{label} = {value:.4g} {unit}")
        self.value.setText("  |  ".join(parts))


def _y_extent(values: list[np.ndarray]) -> tuple[float, float, float]:
    """``(low, high, span)`` of the finite values, always including zero."""
    finite = [array[np.isfinite(array)] for array in values if array.size]
    if not finite or all(array.size == 0 for array in finite):
        return 0.0, 0.0, 0.0
    low = min(0.0, min(float(array.min()) for array in finite if array.size))
    high = max(0.0, max(float(array.max()) for array in finite if array.size))
    return low, high, high - low


def _finish_panel(
    panel: _DiagramPanel,
    *,
    x_max: float,
    low: float,
    high: float,
    unit: str,
    left_title: str,
) -> None:
    panel.plot.addLine(y=0, pen=_ZERO_PEN)
    panel.plot.setLabel("bottom", axis_label("Distance along member", panel._unit_length))
    panel.plot.setLabel("left", axis_label(left_title, unit))
    panel.plot.setXRange(0.0, max(x_max, 1e-12), padding=0.02)
    span = high - low
    if span <= 0.0:
        panel.plot.setYRange(-1.0, 1.0, padding=0.0)
    else:
        panel.plot.setYRange(low - 0.40 * span, high + 0.40 * span, padding=0.0)


def _plot_curve(
    panel: _DiagramPanel,
    x: np.ndarray,
    y: np.ndarray,
    *,
    color: str,
    name: str,
    style: Qt.PenStyle,
    label: str,
    unit: str,
    label_shift: float,
    x_max: float,
) -> None:
    """Plot one curve and label its largest absolute value."""
    panel.plot.plot(
        x,
        y,
        pen=pg.mkPen(color, width=2, style=style),
        name=name,
        connect="finite",
    )
    finite = np.isfinite(x) & np.isfinite(y)
    if not finite.any():
        return
    xs = x[finite]
    ys = y[finite]
    index = int(np.argmax(np.abs(ys)))
    value = float(ys[index])
    if abs(value) <= 1e-12:
        return
    x_peak = float(xs[index])
    if x_peak <= 0.12 * max(x_max, 1e-12):
        anchor_x = 0.0
    elif x_peak >= 0.88 * max(x_max, 1e-12):
        anchor_x = 1.0
    else:
        anchor_x = 0.5
    above = value >= 0.0
    anchor_y = 1.0 if above else 0.0
    offset = label_shift if above else -label_shift
    text = pg.TextItem(
        f"{label} = {value:.4g} {unit}",
        color=color,
        anchor=(anchor_x, anchor_y),
        fill=pg.mkBrush(0, 0, 0, 160),
        border=pg.mkPen(color, width=1),
    )
    text.setPos(x_peak, value + offset)
    panel.plot.addItem(text)
    panel._max_labels.append(text)
    panel.plot.plot(
        [x_peak],
        [value],
        pen=None,
        symbol="o",
        symbolSize=6,
        symbolBrush=color,
        symbolPen=None,
    )


class ElementDiagramWindow(QWidget):
    """A top-level, non-modal window for one frame element."""

    resultChanged = Signal(str)
    unitsChanged = Signal(str)

    def __init__(
        self,
        bundle: ElementDiagramBundle,
        converter: UnitConverter,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent, Qt.WindowType.Window)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.resize(1700, 1000)
        self.setMinimumSize(1300, 760)
        self._bundle = bundle
        self._converter = converter
        self._query_fraction = 0.5
        self._build_ui()
        self.refresh()

    @property
    def bundle(self) -> ElementDiagramBundle:
        """The data currently drawn."""
        return self._bundle

    def set_bundle(self, bundle: ElementDiagramBundle, converter: UnitConverter) -> None:
        """Replace the element or the result and redraw the window."""
        self._bundle = bundle
        self._converter = converter
        self.refresh()

    def set_units(self, converter: UnitConverter) -> None:
        """Redraw in a new display-unit system."""
        self._converter = converter
        self.refresh()

    def set_result_choices(self, choices: list[tuple[str, str]], current_key: str) -> None:
        """Fill the result picker without firing ``resultChanged``."""
        self._results.blockSignals(True)
        self._results.clear()
        for label, key in choices:
            self._results.addItem(label, key)
        index = self._results.findData(current_key)
        if index >= 0:
            self._results.setCurrentIndex(index)
        self._results.blockSignals(False)
        self._results.setEnabled(len(choices) > 1)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        self._header = QLabel()
        self._header.setTextFormat(Qt.TextFormat.RichText)
        self._header.setWordWrap(True)
        root.addWidget(self._header)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Results:"))
        self._results = QComboBox()
        self._results.setMinimumWidth(360)
        self._results.currentIndexChanged.connect(self._emit_result_changed)
        controls.addWidget(self._results, 1)
        controls.addWidget(QLabel("Units:"))
        self._units = QComboBox()
        self._units.setMinimumWidth(230)
        for unit in UnitSystem:
            self._units.addItem(_unit_text(unit.value), unit.value)
        self._units.currentIndexChanged.connect(self._emit_units_changed)
        controls.addWidget(self._units)
        controls.addWidget(QLabel("Distance:"))
        self._distance = QDoubleSpinBox()
        self._distance.setDecimals(4)
        self._distance.setMinimumWidth(150)
        self._distance.setKeyboardTracking(False)
        self._distance.valueChanged.connect(self._on_distance_changed)
        controls.addWidget(self._distance)
        self._query_label = QLabel("")
        controls.addWidget(self._query_label)
        root.addLayout(controls)

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(6)

        self._axial = _DiagramPanel("Axial force N")
        self._v2 = _DiagramPanel("Shear V2")
        self._v3 = _DiagramPanel("Shear V3")
        self._torsion = _DiagramPanel("Torsion T")
        self._m2 = _DiagramPanel("Moment M2")
        self._m3 = _DiagramPanel("Moment M3")
        self._deformation = _DiagramPanel("Deformation absolute / relative")
        self._distributed = _DiagramPanel("Distributed loads wx / wy / wz")
        self._points = _DiagramPanel("Point loads Px / Py / Pz")
        self._panels = [
            self._axial,
            self._v2,
            self._v3,
            self._torsion,
            self._m2,
            self._m3,
            self._deformation,
            self._distributed,
            self._points,
        ]
        # 3 rows x 3 columns: forces, then moments, then deformation and loads.
        for index, panel in enumerate(self._panels):
            row, column = divmod(index, 3)
            grid.addWidget(panel, row, column)
            grid.setRowStretch(row, 1)
            grid.setColumnStretch(column, 1)
        root.addLayout(grid, 1)

        self._notes = QLabel()
        self._notes.setWordWrap(True)
        self._notes.setMinimumHeight(64)
        self._notes.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self._notes.setStyleSheet(
            f"color: {self.palette().color(QPalette.ColorRole.WindowText).name()};"
        )
        root.addWidget(self._notes)

    def _emit_result_changed(self, _index: int) -> None:
        key = self._results.currentData()
        if key:
            self.resultChanged.emit(str(key))

    def _emit_units_changed(self, _index: int) -> None:
        value = self._units.currentData()
        if value:
            self.unitsChanged.emit(str(value))

    def _sync_units_combo(self, target: UnitSystem) -> None:
        index = self._units.findData(target.value)
        if index >= 0 and index != self._units.currentIndex():
            self._units.blockSignals(True)
            self._units.setCurrentIndex(index)
            self._units.blockSignals(False)

    def _on_distance_changed(self, value: float) -> None:
        length = self._bundle.length * self._converter.length
        if length > 0.0:
            self._query_fraction = min(max(value / length, 0.0), 1.0)
        self._update_query()

    def refresh(self) -> None:
        """Draw the current bundle in the display units."""
        bundle = self._bundle
        converter = self._converter
        labels = converter.labels
        length_unit = _unit_text(labels.length)
        length = bundle.length * converter.length
        self._sync_units_combo(converter.target)

        name = f" - {bundle.element_name}" if bundle.element_name else ""
        case = f" - {bundle.case_name}" if bundle.case_name else ""
        bound = f" - {bundle.bound} bound" if bundle.bound else ""
        self._header.setText(
            f"<b>Element {bundle.element_id}</b>{name} - {bundle.element_type} - "
            f"L = {length:.4g} {length_unit}{case}{bound}"
        )
        self.setWindowTitle(f"Element {bundle.element_id} - Diagrams")

        self._distance.blockSignals(True)
        self._distance.setRange(0.0, max(length, 0.0))
        self._distance.setSuffix(f" {length_unit}")
        self._distance.setSingleStep(max(length / 100.0, 1e-6))
        self._distance.setValue(self._query_fraction * length)
        self._distance.blockSignals(False)
        self._distance.setEnabled(length > 0.0)

        for panel in self._panels:
            panel._unit_length = length_unit

        self._plot_force_panel(
            self._axial,
            (ForceComponent.N,),
            "Axial force N",
            "force",
        )
        self._plot_force_panel(
            self._v2,
            (ForceComponent.V2,),
            "Shear V2",
            "force",
        )
        self._plot_force_panel(
            self._v3,
            (ForceComponent.V3,),
            "Shear V3",
            "force",
        )
        self._plot_force_panel(
            self._torsion,
            (ForceComponent.T,),
            "Torsion T",
            "moment",
        )
        self._plot_force_panel(
            self._m2,
            (ForceComponent.M2,),
            "Moment M2",
            "moment",
        )
        self._plot_force_panel(
            self._m3,
            (ForceComponent.M3,),
            "Moment M3",
            "moment",
        )
        self._plot_deformation()
        self._plot_distributed()
        self._plot_points()

        notes = [
            "Forces and loads are in the member's local axes; deformations are magnitudes.",
            *bundle.notes,
        ]
        self._notes.setText("<br>".join(f"- {note}" for note in notes))
        self._notes.setVisible(True)

        self._update_query()

    # ── panels ──────────────────────────────────────────────────────

    def _plot_force_panel(
        self,
        panel: _DiagramPanel,
        components: tuple[ForceComponent, ...],
        title: str,
        quantity: str,
    ) -> None:
        panel.reset()
        series = [item for item in self._bundle.forces if item.component in components]
        if not series:
            panel.show_empty("Not reported for this element.")
            return

        converter = self._converter
        labels = converter.labels
        unit = _unit_text(labels.moment if quantity == "moment" else labels.force)
        factor = converter.moment if quantity == "moment" else converter.force
        x_max = self._bundle.length * converter.length
        curves: list[tuple[np.ndarray, np.ndarray, str, str]] = []
        y_values: list[np.ndarray] = []
        for item in series:
            x = item.x * converter.length
            y = item.values * factor
            name = item.component.value
            if item.label:
                name = f"{name} ({item.label})"
            curves.append((x, y, name, unit))
            y_values.append(y)

        low, high, span = _y_extent(y_values)
        if len(series) > 1:
            panel.legend()
        for index, (item, (x, y, name, _curve_unit)) in enumerate(zip(series, curves, strict=True)):
            color = _COMPONENT_COLORS[item.component]
            style = Qt.PenStyle.DashLine if item.label.lower() == "min" else Qt.PenStyle.SolidLine
            label = item.component.value
            if item.label:
                label = f"{label} {item.label}"
            _plot_curve(
                panel,
                x,
                y,
                color=color,
                name=name,
                style=style,
                label=label,
                unit=unit,
                label_shift=0.06 * span * (index + 1),
                x_max=x_max,
            )
        panel.set_curves(curves)
        _finish_panel(
            panel,
            x_max=x_max,
            low=low,
            high=high,
            unit=unit,
            left_title=title,
        )
        missing = [c.value for c in components if c not in {item.component for item in series}]
        if missing:
            panel.set_note(f"Not reported: {', '.join(missing)}.")

    def _plot_deformation(self) -> None:
        panel = self._deformation
        panel.reset()
        bundle = self._bundle
        if bundle.absolute is None or bundle.relative is None:
            panel.show_empty("No nodal displacements in this result.")
            return

        converter = self._converter
        labels = converter.labels
        unit = _unit_text(labels.length)
        x_max = bundle.length * converter.length
        curves: list[tuple[np.ndarray, np.ndarray, str, str]] = []
        y_values: list[np.ndarray] = []
        entries = (
            (bundle.absolute, "|u|", "#1f77b4", Qt.PenStyle.DashLine),
            (bundle.relative, "relative", "#ff7f0e", Qt.PenStyle.SolidLine),
        )
        for curve, label, _color, _style in entries:
            x = curve[0] * converter.length
            y = curve[1] * converter.length
            curves.append((x, y, label, unit))
            y_values.append(y)

        low, high, span = _y_extent(y_values)
        panel.legend()
        for index, ((_curve, label, color, style), (x, y, _name, _unit)) in enumerate(
            zip(entries, curves, strict=True)
        ):
            _plot_curve(
                panel,
                x,
                y,
                color=color,
                name=label,
                style=style,
                label=label,
                unit=unit,
                label_shift=0.12 * span * (index + 1),
                x_max=x_max,
            )
        panel.set_curves(curves)
        _finish_panel(
            panel,
            x_max=x_max,
            low=low,
            high=high,
            unit=unit,
            left_title="Deformation",
        )

    def _plot_distributed(self) -> None:
        panel = self._distributed
        panel.reset()
        segments = self._bundle.segments
        if not segments:
            panel.show_empty("No distributed load or self weight on this member.")
            return

        converter = self._converter
        labels = converter.labels
        factor = converter.force / converter.length
        unit = _unit_text(f"{labels.force}/{labels.length}")
        x_max = self._bundle.length * converter.length
        names = ("wx", "wy", "wz")
        curves: list[tuple[np.ndarray, np.ndarray, str, str]] = []
        y_values: list[np.ndarray] = []
        for index, name in enumerate(names):
            xs: list[float] = []
            ys: list[float] = []
            for segment in segments:
                xs.extend([segment.x0 * converter.length, segment.x1 * converter.length, np.nan])
                ys.extend([segment.w0[index] * factor, segment.w1[index] * factor, np.nan])
            x = np.asarray(xs)
            y = np.asarray(ys)
            curves.append((x, y, name, unit))
            y_values.append(y)

        if not any(
            np.isfinite(y).any() and float(np.max(np.abs(y[np.isfinite(y)]))) > 0.0
            for y in y_values
        ):
            panel.show_empty("The distributed loads are zero on this member.")
            return

        low, high, span = _y_extent(y_values)
        if sum(np.isfinite(y).any() for y in y_values) > 1:
            panel.legend()
        for index, (x, y, name, _unit) in enumerate(curves):
            if not np.isfinite(y).any() or float(np.max(np.abs(y[np.isfinite(y)]))) <= 0.0:
                continue
            _plot_curve(
                panel,
                x,
                y,
                color=_LOAD_COLORS[index],
                name=name,
                style=Qt.PenStyle.SolidLine,
                label=name,
                unit=unit,
                label_shift=0.08 * span * (index + 1),
                x_max=x_max,
            )
        panel.set_curves(curves)

        def value_at(x_display: float) -> str:
            x_model = x_display / converter.length if converter.length else x_display
            parts = [
                f"{name} = {_distributed_value(segments, index, x_model) * factor:.4g} {unit}"
                for index, name in enumerate(names)
            ]
            return "  |  ".join(parts)

        panel.set_query_value(value_at)
        _finish_panel(
            panel,
            x_max=x_max,
            low=low,
            high=high,
            unit=unit,
            left_title="Distributed load",
        )

    def _plot_points(self) -> None:
        panel = self._points
        panel.reset()
        points = self._bundle.points
        if not points:
            panel.show_empty("No point load on this member.")
            return

        converter = self._converter
        labels = converter.labels
        unit = _unit_text(labels.force)
        x_max = self._bundle.length * converter.length
        names = ("Px", "Py", "Pz")
        curves: list[tuple[np.ndarray, np.ndarray, str, str]] = []
        y_values: list[np.ndarray] = []
        for index, name in enumerate(names):
            xs: list[float] = []
            ys: list[float] = []
            for point in points:
                if abs(point.p[index]) <= 0.0:
                    continue
                x_point = point.x * converter.length
                y_point = point.p[index] * converter.force
                xs.extend([x_point, x_point, np.nan])
                ys.extend([0.0, y_point, np.nan])
            x_curve = np.asarray(xs)
            y_curve = np.asarray(ys)
            curves.append((x_curve, y_curve, name, unit))
            y_values.append(y_curve)

        if not any(
            np.isfinite(y_curve).any()
            and float(np.max(np.abs(y_curve[np.isfinite(y_curve)]))) > 0.0
            for y_curve in y_values
        ):
            panel.show_empty("The point loads are zero on this member.")
            return

        low, high, span = _y_extent(y_values)
        if sum(np.isfinite(y_curve).any() for y_curve in y_values) > 1:
            panel.legend()
        for index, (x_curve, y_curve, name, _unit) in enumerate(curves):
            if (
                not np.isfinite(y_curve).any()
                or float(np.max(np.abs(y_curve[np.isfinite(y_curve)]))) <= 0.0
            ):
                continue
            _plot_curve(
                panel,
                x_curve,
                y_curve,
                color=_LOAD_COLORS[index],
                name=name,
                style=Qt.PenStyle.SolidLine,
                label=name,
                unit=unit,
                label_shift=0.08 * span * (index + 1),
                x_max=x_max,
            )
        panel.set_curves(curves)
        panel.set_query_value(lambda x_display: _point_value(points, converter, x_display, x_max))
        _finish_panel(
            panel,
            x_max=x_max,
            low=low,
            high=high,
            unit=unit,
            left_title="Point load",
        )

    def _update_query(self) -> None:
        labels = self._converter.labels
        length_unit = _unit_text(labels.length)
        length = self._bundle.length * self._converter.length
        x_display = self._query_fraction * length
        for panel in self._panels:
            panel.set_query(x_display, length)
        self._query_label.setText(
            f"x = {x_display:.4g} {length_unit} ({self._query_fraction * 100.0:.0f}%)"
        )


def _distributed_value(segments: tuple[LoadSegment, ...], index: int, x_model: float) -> float:
    """Local load component at ``x_model``, zero outside the loaded pieces."""
    for segment in segments:
        low = min(segment.x0, segment.x1)
        high = max(segment.x0, segment.x1)
        if not (low <= x_model <= high):
            continue
        if high - low <= 1e-12:
            return float(segment.w0[index])
        fraction = (x_model - low) / (high - low)
        return float(segment.w0[index] + fraction * (segment.w1[index] - segment.w0[index]))
    return 0.0


def _point_value(
    points: tuple[PointLoad, ...],
    converter: UnitConverter,
    x_display: float,
    length_display: float,
) -> str:
    """Point-load components at ``x_display``, or a note when none acts there."""
    tolerance = max(1e-6, 1e-3 * length_display)
    hits = [point for point in points if abs(point.x * converter.length - x_display) <= tolerance]
    if not hits:
        return "no point load at x"
    parts: list[str] = []
    for point in hits:
        for index, name in enumerate(("Px", "Py", "Pz")):
            if abs(point.p[index]) <= 0.0:
                continue
            parts.append(
                f"{name} = {point.p[index] * converter.force:.4g} {_unit_text(converter.labels.force)}"
            )
    return "  |  ".join(parts) if parts else "0"


__all__ = ["ElementDiagramWindow"]
