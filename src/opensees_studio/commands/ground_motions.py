"""Undoable mutations of the project's ground-motion catalog."""

from __future__ import annotations

from typing import TYPE_CHECKING

from opensees_studio.commands.base import ProjectCommand

if TYPE_CHECKING:
    from opensees_studio.core import GroundMotionRecord
    from opensees_studio.viewmodels import ProjectViewModel


class AddGroundMotionCommand(ProjectCommand):
    """Append a :class:`GroundMotionRecord` to the catalog (undoable)."""

    def __init__(self, vm: ProjectViewModel, record: GroundMotionRecord) -> None:
        super().__init__(vm, f"Add ground motion '{record.name or record.id}'")
        self._record = record

    def redo(self) -> None:
        existing = {r.id for r in self.project.ground_motions}
        if self._record.id in existing:
            raise ValueError(f"Ground-motion id {self._record.id} already exists.")
        self.project.ground_motions.append(self._record)
        self._notify()

    def undo(self) -> None:
        self.project.ground_motions[:] = [
            r for r in self.project.ground_motions if r.id != self._record.id
        ]
        self._notify()


class RemoveGroundMotionCommand(ProjectCommand):
    """Remove a catalog entry (undoable).

    The caller must ensure no time series references the record — the
    dialog refuses the removal, this command only guards against races.
    """

    def __init__(self, vm: ProjectViewModel, record_id: int) -> None:
        super().__init__(vm, f"Remove ground motion {record_id}")
        self._record_id = record_id
        self._removed: GroundMotionRecord | None = None
        self._index: int = -1

    def redo(self) -> None:
        in_use = [
            ts.id
            for ts in self.project.time_series
            if getattr(ts, "record_id", None) == self._record_id
        ]
        if in_use:
            raise ValueError(
                f"Ground motion {self._record_id} is used by time series {in_use}; "
                "remove or relink those first."
            )
        entries = self.project.ground_motions
        self._index, self._removed = next(
            (i, r) for i, r in enumerate(entries) if r.id == self._record_id
        )
        entries.pop(self._index)
        self._notify()

    def undo(self) -> None:
        if self._removed is not None:
            entries = self.project.ground_motions
            entries.insert(min(self._index, len(entries)), self._removed)
        self._notify()


class RelinkGroundMotionCommand(ProjectCommand):
    """Point a catalog entry at a re-checked file (undoable).

    ``new_record`` is a fully re-imported entry (same id, fresh path,
    hash, dt, npts, status 'ok') and ``values`` its samples; both come
    from the view model's relink parse. Redo swaps the entry in and
    re-hydrates every time series backed by it; undo restores the old
    entry and empties those series again if the old entry was flagged.
    """

    def __init__(
        self,
        vm: ProjectViewModel,
        new_record: GroundMotionRecord,
        values: list[float],
    ) -> None:
        super().__init__(vm, f"Relink ground motion '{new_record.name or new_record.id}'")
        self._new = new_record
        self._values = values
        self._old: GroundMotionRecord | None = None
        self._old_series_values: dict[int, list[float]] = {}

    def _series_backed_by(self, record_id: int):  # type: ignore[no-untyped-def]
        return [
            ts for ts in self.project.time_series if getattr(ts, "record_id", None) == record_id
        ]

    def redo(self) -> None:
        entries = self.project.ground_motions
        index = next(i for i, r in enumerate(entries) if r.id == self._new.id)
        self._old = entries[index]
        entries[index] = self._new
        for ts in self._series_backed_by(self._new.id):
            self._old_series_values[ts.id] = ts.values
            ts.values = list(self._values)
        self._notify()

    def undo(self) -> None:
        if self._old is not None:
            entries = self.project.ground_motions
            index = next(i for i, r in enumerate(entries) if r.id == self._new.id)
            entries[index] = self._old
        for ts in self._series_backed_by(self._new.id):
            if ts.id in self._old_series_values:
                ts.values = self._old_series_values[ts.id]
        self._notify()
