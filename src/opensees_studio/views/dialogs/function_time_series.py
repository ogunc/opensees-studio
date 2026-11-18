"""Define → Add Function TimeSeries: Constant, Trig, Triangle, Rectangular or Pulse.

One dialog for every time series given by a formula rather than samples (Linear
and Path keep their own dialogs). The rows follow the chosen type; the result is
a plain core model the main window adds with ``AddTimeSeriesCommand``.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import (
    QComboBox,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from opensees_studio.core import (
    ConstantTimeSeries,
    PulseTimeSeries,
    RectangularTimeSeries,
    TriangleTimeSeries,
    TrigTimeSeries,
)
from opensees_studio.views.float_field import FloatField
from opensees_studio.views.screen_fit import FittedDialog, MessageArea

#: type → (model class, ((field, label, default), …), one-line description)
SERIES_TYPES: dict[str, tuple[type[Any], tuple[tuple[str, str, float], ...], str]] = {
    "Constant": (ConstantTimeSeries, (("factor", "Factor", 1.0),), "value = factor, at every time"),
    "Trig": (
        TrigTimeSeries,
        (
            ("factor", "Amplitude (factor)", 1.0),
            ("t_start", "Start time", 0.0),
            ("t_end", "End time", 10.0),
            ("period", "Period", 1.0),
            ("shift", "Phase shift [rad]", 0.0),
            ("zero_shift", "Zero shift", 0.0),
        ),
        "factor·sin(2π(t - t_start)/T + shift) + zero shift, between start and end",
    ),
    "Triangle": (
        TriangleTimeSeries,
        (
            ("factor", "Amplitude (factor)", 1.0),
            ("t_start", "Start time", 0.0),
            ("t_end", "End time", 10.0),
            ("period", "Period", 1.0),
            ("shift", "Phase shift [rad]", 0.0),
            ("zero_shift", "Zero shift", 0.0),
        ),
        "a triangular wave of the period, between start and end",
    ),
    "Rectangular": (
        RectangularTimeSeries,
        (
            ("factor", "Factor", 1.0),
            ("t_start", "Start time", 0.0),
            ("t_end", "End time", 1.0),
        ),
        "value = factor between start and end, zero elsewhere",
    ),
    "Pulse": (
        PulseTimeSeries,
        (
            ("factor", "Amplitude (factor)", 1.0),
            ("t_start", "Start time", 0.0),
            ("t_end", "End time", 10.0),
            ("period", "Period", 1.0),
            ("width", "Width (fraction of period)", 0.5),
            ("shift", "Time shift", 0.0),
            ("zero_shift", "Zero shift", 0.0),
        ),
        "rectangular pulses, on for the width of each period, between start and end",
    ),
}


class FunctionTimeSeriesDialog(FittedDialog):
    """Pick a formula series type and its parameters."""

    def __init__(self, next_ts_id: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Add Function TimeSeries")
        self._next_id = next_ts_id
        root = QVBoxLayout(self)
        top = QFormLayout()
        self.type_combo = QComboBox()
        self.type_combo.addItems(list(SERIES_TYPES))
        self.name_edit = QLineEdit()
        top.addRow("Type:", self.type_combo)
        top.addRow("Name:", self.name_edit)
        root.addLayout(top)
        self.description = QLabel()
        self.description.setWordWrap(True)
        root.addWidget(self.description)
        self.form = QFormLayout()
        root.addLayout(self.form)
        self.fields: dict[str, FloatField] = {}
        self.message = MessageArea()
        root.addWidget(self.message)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self.type_combo.currentTextChanged.connect(self._rebuild)
        self._rebuild(self.type_combo.currentText())

    def _rebuild(self, kind: str) -> None:
        while self.form.rowCount():
            self.form.removeRow(0)
        self.fields = {}
        _cls, rows, text = SERIES_TYPES[kind]
        self.description.setText(f"<i>{kind}: {text}.</i>")
        for name, label, default in rows:
            field = FloatField()
            field.setRange(-1e300, 1e300)
            field.setValue(default)
            self.form.addRow(f"{label}:", field)
            self.fields[name] = field

    def time_series(self) -> Any:
        """The series as typed (raises ``ValueError`` on an inconsistent one)."""
        kind = self.type_combo.currentText()
        cls = SERIES_TYPES[kind][0]
        values = {name: float(field.value()) for name, field in self.fields.items()}
        name = self.name_edit.text().strip() or f"{kind}{self._next_id}"
        return cls(id=self._next_id, name=name, **values)

    def accept(self) -> None:
        try:
            self.time_series()
        except ValueError as exc:
            self.message.show_message(str(exc), "error")
            return
        super().accept()
