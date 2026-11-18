"""Structured calculation records for the design reports.

The design engine already computes nominal and available strengths; these
records keep them, the equation and the numbers that produced them, so a
calculation-memory document can print the check instead of a bare ratio.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class CalcStep:
    """One line of a limit-state calculation."""

    label: str
    formula: str
    substitution: str = ""
    value: float | None = None


@dataclass(frozen=True)
class LimitStateCheck:
    """One limit state of one member under one demand."""

    name: str
    equation: str
    demand: float
    capacity: float
    ratio: float
    steps: tuple[CalcStep, ...] = ()
    notes: tuple[str, ...] = field(default_factory=tuple)
