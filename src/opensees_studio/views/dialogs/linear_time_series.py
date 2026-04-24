"""Add Linear TimeSeries dialog."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from opensees_studio.core import LinearTimeSeries


class LinearTimeSeriesDialog(QDialog):
    """Modal dialog: build a simple ``timeSeries Linear`` entity."""

    def __init__(self, next_ts_id: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Add Linear TimeSeries")
        self._next_id = next_ts_id
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self._name_edit = QLineEdit("Linear")
        form.addRow("Name:", self._name_edit)

        self._factor_spin = QDoubleSpinBox()
        self._factor_spin.setRange(-1e12, 1e12)
        self._factor_spin.setDecimals(6)
        self._factor_spin.setSingleStep(0.1)
        self._factor_spin.setValue(1.0)
        form.addRow("Factor:", self._factor_spin)

        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def time_series(self) -> LinearTimeSeries:
        return LinearTimeSeries(
            id=self._next_id,
            name=self._name_edit.text().strip() or "Linear",
            factor=self._factor_spin.value(),
        )
