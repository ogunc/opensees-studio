"""Commands that apply nodal loads.

If the project has no time series and no plain pattern yet, this
module ensures a default pair (LinearTimeSeries id=1 +
PlainLoadPattern id=1) gets created as part of the same undoable step.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from opensees_studio.commands.base import ProjectCommand
from opensees_studio.core import (
    LinearTimeSeries,
    NodalLoad,
    PlainLoadPattern,
    UniformElementLoad,
)

if TYPE_CHECKING:
    from opensees_studio.viewmodels import ProjectViewModel


class AddNodalLoadsCommand(ProjectCommand):
    """Apply a force vector to a set of nodes within an existing pattern.

    If ``pattern_id`` is ``None`` the command falls back to (or creates)
    a default ``PlainLoadPattern(id=1)`` paired with a default
    ``LinearTimeSeries(id=1)``.
    """

    def __init__(
        self,
        vm: "ProjectViewModel",
        node_ids: set[int],
        forces: tuple[float, float, float, float, float, float],
        pattern_id: int | None = None,
        new_pattern_name: str | None = None,
    ) -> None:
        super().__init__(vm, f"Apply load to {len(node_ids)} node(s)")
        self._node_ids = set(node_ids)
        self._forces = forces
        self._pattern_id = pattern_id
        self._new_pattern_name = new_pattern_name
        self._created_ts: LinearTimeSeries | None = None
        self._created_pattern: PlainLoadPattern | None = None
        self._added_loads: list[tuple[int, NodalLoad]] = []  # (pattern_id, load)

    # ── helpers ──────────────────────────────────────────────────────
    def _resolve_pattern(self) -> PlainLoadPattern:
        if self._pattern_id is not None:
            for pat in self.project.load_patterns:
                if pat.id == self._pattern_id and isinstance(pat, PlainLoadPattern):
                    return pat
            raise ValueError(f"Plain pattern id={self._pattern_id} not found.")
        # No pattern requested. When the caller supplied a name, always
        # create a fresh pattern (letting the user stack several named
        # patterns on the same project — useful for moment-curvature
        # where "RefMoment" must stay separate from a gravity pattern).
        # With no name, reuse an existing plain pattern if one is there.
        if self._new_pattern_name is None:
            for pat in self.project.load_patterns:
                if isinstance(pat, PlainLoadPattern):
                    return pat
        # Need to create both ts + pattern.
        ts_id = self.project.next_time_series_id()
        self._created_ts = LinearTimeSeries(
            id=ts_id, name=self._new_pattern_name or "Default",
        )
        self.project.time_series.append(self._created_ts)
        pid = self.project.next_pattern_id()
        self._created_pattern = PlainLoadPattern(
            id=pid, name=self._new_pattern_name or "Default", time_series_id=ts_id,
        )
        self.project.load_patterns.append(self._created_pattern)
        return self._created_pattern

    # ── do/undo ──────────────────────────────────────────────────────
    def redo(self) -> None:
        pattern = self._resolve_pattern()
        for nid in self._node_ids:
            load = NodalLoad(node_id=nid, forces=self._forces)
            pattern.nodal_loads.append(load)
            self._added_loads.append((pattern.id, load))
        self._notify()

    def undo(self) -> None:
        # Remove the loads we added (by identity).
        for pid, load in self._added_loads:
            for pat in self.project.load_patterns:
                if pat.id == pid and isinstance(pat, PlainLoadPattern):
                    if load in pat.nodal_loads:
                        pat.nodal_loads.remove(load)
                    break
        self._added_loads.clear()
        # Roll back any infrastructure we created.
        if self._created_pattern is not None and self._created_pattern in self.project.load_patterns:
            self.project.load_patterns.remove(self._created_pattern)
            self._created_pattern = None
        if self._created_ts is not None and self._created_ts in self.project.time_series:
            self.project.time_series.remove(self._created_ts)
            self._created_ts = None
        self._notify()


class AddElementLoadsCommand(ProjectCommand):
    """Apply a uniform distributed load (wy, wz, wx) to a set of elements.

    Same pattern-resolution strategy as :class:`AddNodalLoadsCommand`:
    reuses an existing plain pattern, or creates a default one.
    """

    def __init__(
        self,
        vm: "ProjectViewModel",
        element_ids: set[int],
        wy: float = 0.0,
        wz: float = 0.0,
        wx: float = 0.0,
        pattern_id: int | None = None,
    ) -> None:
        super().__init__(vm, f"Apply distributed load to {len(element_ids)} element(s)")
        self._element_ids = set(element_ids)
        self._wy = wy
        self._wz = wz
        self._wx = wx
        self._pattern_id = pattern_id
        self._created_ts: LinearTimeSeries | None = None
        self._created_pattern: PlainLoadPattern | None = None
        self._added_loads: list[tuple[int, UniformElementLoad]] = []

    def _resolve_pattern(self) -> PlainLoadPattern:
        if self._pattern_id is not None:
            for pat in self.project.load_patterns:
                if pat.id == self._pattern_id and isinstance(pat, PlainLoadPattern):
                    return pat
            raise ValueError(f"Plain pattern id={self._pattern_id} not found.")
        for pat in self.project.load_patterns:
            if isinstance(pat, PlainLoadPattern):
                return pat
        ts_id = self.project.next_time_series_id()
        self._created_ts = LinearTimeSeries(id=ts_id, name="Default")
        self.project.time_series.append(self._created_ts)
        pid = self.project.next_pattern_id()
        self._created_pattern = PlainLoadPattern(
            id=pid, name="Default", time_series_id=ts_id,
        )
        self.project.load_patterns.append(self._created_pattern)
        return self._created_pattern

    def redo(self) -> None:
        pattern = self._resolve_pattern()
        for eid in self._element_ids:
            load = UniformElementLoad(
                element_id=eid, wy=self._wy, wz=self._wz, wx=self._wx,
            )
            pattern.element_loads.append(load)
            self._added_loads.append((pattern.id, load))
        self._notify()

    def undo(self) -> None:
        for pid, load in self._added_loads:
            for pat in self.project.load_patterns:
                if pat.id == pid and isinstance(pat, PlainLoadPattern):
                    if load in pat.element_loads:
                        pat.element_loads.remove(load)
                    break
        self._added_loads.clear()
        if self._created_pattern is not None and self._created_pattern in self.project.load_patterns:
            self.project.load_patterns.remove(self._created_pattern)
            self._created_pattern = None
        if self._created_ts is not None and self._created_ts in self.project.time_series:
            self.project.time_series.remove(self._created_ts)
            self._created_ts = None
        self._notify()
