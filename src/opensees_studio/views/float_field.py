"""One numeric input for every floating-point value in the GUI.

:class:`FloatField` is a ``QDoubleSpinBox`` that keeps the full double: it
accepts scientific notation (``1e-10``, ``2.9e4``), stores the typed value
without rounding it to a number of decimals, and displays the shortest text
that reads back to the same double (:func:`format_float`). Ranges still
apply: text outside the range is never accepted, and on focus-out the field
returns to its last valid value. The value commits on Enter, focus-out or a
step, not on every keystroke.

Text inputs holding lists of numbers (grid spacings, cyclic peaks) and table
cells use :func:`format_float` for display, so they lose no digits either.
"""

from __future__ import annotations

import math
import re

from PySide6.QtCore import QLocale
from PySide6.QtGui import QValidator
from PySide6.QtWidgets import QDoubleSpinBox, QWidget

_FULL_PRECISION = 323
"""QDoubleSpinBox's largest ``decimals``: a value is stored as typed, not rounded."""

_PARTIAL = re.compile(r"[+-]?(\d+\.?\d*|\.\d*)?([eE][+-]?\d*)?")
"""Text a user passes through while typing a number: ``-``, ``1.``, ``2e``, ``1e-``."""


def format_float(value: float) -> str:
    """Shortest text that reads back to ``value`` exactly, with a decimal point.

    ``29000.0`` shows as ``29000``, ``1e-10`` as ``1e-10``, ``0.1`` as ``0.1``.
    """
    value = float(value)
    if value == 0.0:
        return "0"
    if not math.isfinite(value):
        return repr(value)
    text = repr(value)
    return text[:-2] if text.endswith(".0") else text


def parse_float(text: str) -> float:
    """``float(text)`` for user input: surrounding blanks allowed, no nan or inf."""
    value = float(text.strip())
    if not math.isfinite(value):
        raise ValueError(f"not a finite number: {text!r}")
    return value


class FloatField(QDoubleSpinBox):
    """Full-precision numeric field with scientific notation.

    Drop-in for ``QDoubleSpinBox``: ranges, steps, prefix, suffix and special
    value text work as before. :meth:`setDecimals` is ignored, since the field
    never rounds.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        super().setDecimals(_FULL_PRECISION)
        # A decimal point whatever the system locale; no group separators.
        self.setLocale(QLocale(QLocale.Language.C))
        # Commit on Enter, focus-out or a step, not per keystroke: typing 1e-10
        # passes through 1, 0.1, ... and 1e13 through 10.
        self.setKeyboardTracking(False)

    def setDecimals(self, prec: int) -> None:
        """Ignored: the field keeps every digit of the value."""

    def _number_text(self, text: str) -> str:
        prefix, suffix = self.prefix(), self.suffix()
        if prefix and text.startswith(prefix):
            text = text[len(prefix) :]
        if suffix and text.endswith(suffix):
            text = text[: -len(suffix)]
        return text.strip()

    def validate(self, text: str, pos: int) -> object:
        special = self.specialValueText()
        if special and text == special:
            return QValidator.State.Acceptable, text, pos
        number = self._number_text(text)
        try:
            value = parse_float(number)
        except ValueError:
            state = (
                QValidator.State.Intermediate
                if _PARTIAL.fullmatch(number)
                else QValidator.State.Invalid
            )
            return state, text, pos
        if self.minimum() <= value <= self.maximum():
            return QValidator.State.Acceptable, text, pos
        return QValidator.State.Intermediate, text, pos

    def valueFromText(self, text: str) -> float:
        special = self.specialValueText()
        if special and text == special:
            return self.minimum()
        try:
            return parse_float(self._number_text(text))
        except ValueError:
            return self.value()

    def textFromValue(self, val: float) -> str:
        return format_float(val)
