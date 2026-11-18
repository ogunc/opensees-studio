"""Undoable addition of the notional-load patterns of the Direct Analysis Method."""

from __future__ import annotations

from typing import TYPE_CHECKING

from opensees_studio.commands.base import ProjectCommand

if TYPE_CHECKING:
    from opensees_studio.core import LinearTimeSeries, PlainLoadPattern
    from opensees_studio.viewmodels import ProjectViewModel


class AddNotionalLoadsCommand(ProjectCommand):
    """Add the notional-load patterns, and a time series when the project has none."""

    def __init__(
        self,
        vm: ProjectViewModel,
        patterns: list[PlainLoadPattern],
        series: LinearTimeSeries | None = None,
    ) -> None:
        names = ", ".join(pattern.name or str(pattern.id) for pattern in patterns)
        super().__init__(vm, f"Add notional loads ({names})")
        self._patterns = list(patterns)
        self._series = series

    def redo(self) -> None:
        if self._series is not None:
            if any(ts.id == self._series.id for ts in self.project.time_series):
                raise ValueError(f"TimeSeries id {self._series.id} already exists.")
            self.project.time_series.append(self._series)
        existing = {p.id for p in self.project.load_patterns}
        for pattern in self._patterns:
            if pattern.id in existing:
                raise ValueError(f"LoadPattern id {pattern.id} already exists.")
            self.project.load_patterns.append(pattern)
            existing.add(pattern.id)
        self._notify()

    def undo(self) -> None:
        ids = {pattern.id for pattern in self._patterns}
        self.project.load_patterns[:] = [
            pattern for pattern in self.project.load_patterns if pattern.id not in ids
        ]
        if self._series is not None:
            self.project.time_series[:] = [
                ts for ts in self.project.time_series if ts.id != self._series.id
            ]
        self._notify()
