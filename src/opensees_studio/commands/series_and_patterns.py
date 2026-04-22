"""Undoable add of a TimeSeries or a LoadPattern.

These generic helpers keep the PathTimeSeries + UniformExcitation
dialogs simple: the dialog builds the core entity, the command appends
it to the right project list and tracks the insertion for undo.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from opensees_studio.commands.base import ProjectCommand

if TYPE_CHECKING:
    from opensees_studio.core import LoadPattern, TimeSeries
    from opensees_studio.viewmodels import ProjectViewModel


class AddTimeSeriesCommand(ProjectCommand):
    """Append a :class:`TimeSeries` to the project (undoable)."""

    def __init__(self, vm: "ProjectViewModel", ts: "TimeSeries") -> None:
        super().__init__(vm, f"Add time series '{ts.name or ts.id}'")
        self._ts = ts

    def redo(self) -> None:
        existing = {t.id for t in self.project.time_series}
        if self._ts.id in existing:
            raise ValueError(f"TimeSeries id {self._ts.id} already exists.")
        self.project.time_series.append(self._ts)
        self._notify()

    def undo(self) -> None:
        self.project.time_series[:] = [
            t for t in self.project.time_series if t.id != self._ts.id
        ]
        self._notify()


class AddLoadPatternCommand(ProjectCommand):
    """Append a :class:`LoadPattern` to the project (undoable)."""

    def __init__(self, vm: "ProjectViewModel", pattern: "LoadPattern") -> None:
        super().__init__(vm, f"Add pattern '{pattern.name or pattern.id}'")
        self._pattern = pattern

    def redo(self) -> None:
        existing = {p.id for p in self.project.load_patterns}
        if self._pattern.id in existing:
            raise ValueError(f"Pattern id {self._pattern.id} already exists.")
        self.project.load_patterns.append(self._pattern)
        self._notify()

    def undo(self) -> None:
        self.project.load_patterns[:] = [
            p for p in self.project.load_patterns if p.id != self._pattern.id
        ]
        self._notify()
