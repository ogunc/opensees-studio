"""Design ratio dock: the colour legend and the summary of the steel check on the model."""

from __future__ import annotations

import html
from typing import Any

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QGridLayout,
    QGroupBox,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from opensees_studio.core.design.ratio_bands import NOT_DESIGNED_COLOR, ratio_bands


def _swatch(color: str) -> QLabel:
    label = QLabel()
    label.setFixedSize(28, 14)
    label.setStyleSheet(f"background: {color}; border: 1px solid #555;")
    return label


class DesignRatioView(QWidget):
    """Legend of the ratio bands, the check's summary, and a way back to the model."""

    selectFailing = Signal()
    closed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        self._title = QLabel("")
        self._title.setWordWrap(True)
        root.addWidget(self._title)
        self._legend = QGroupBox("Governing ratio", self)
        self._grid = QGridLayout(self._legend)
        root.addWidget(self._legend)
        self._summary = QLabel("")
        self._summary.setWordWrap(True)
        root.addWidget(self._summary)
        self._select = QPushButton("Select failing members")
        self._select.clicked.connect(self.selectFailing.emit)
        root.addWidget(self._select)
        close = QPushButton("Back to model")
        close.clicked.connect(self.closed.emit)
        root.addWidget(close)
        root.addStretch(1)

    def set_report(self, report: Any, *, method: str, limit: float) -> None:
        """Show ``report`` (a :class:`services.steel_design.DesignReport`)."""
        self._title.setText(f"<b>AISC 360-16 ({method})</b> — ratio limit {limit:g}")
        while self._grid.count():
            item = self._grid.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.deleteLater()
        rows = [(band.color, band.label) for band in ratio_bands(limit)]
        rows.append((NOT_DESIGNED_COLOR, "not designed"))
        for row, (color, text) in enumerate(rows):
            self._grid.addWidget(_swatch(color), row, 0)
            self._grid.addWidget(QLabel(text), row, 1)
        lines = [report.summary()]
        lines += report.notes
        self._summary.setText("<br>".join(html.escape(line) for line in lines))
        self._select.setEnabled(bool(report.failing))

    def summary_text(self) -> str:
        return self._summary.text()
