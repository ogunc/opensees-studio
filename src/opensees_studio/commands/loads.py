"""Commands that apply nodal, distributed and point element loads.

If the project has no time series and no plain pattern yet, this
module ensures a default pair (LinearTimeSeries id=1 +
PlainLoadPattern id=1) gets created as part of the same undoable step.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from opensees_studio.commands.base import ProjectCommand, restore_project, snapshot_project
from opensees_studio.core import (
    DEFAULT_PATTERN_NAME,
    FRAME_ELEMENT_CLASSES,
    NodalLoad,
    PlainLoadPattern,
    PointElementLoad,
    TemperatureLoad,
    TimeSeries,
    TrapezoidalElementLoad,
    UniformElementLoad,
    find_plain_pattern,
    make_default_pattern,
    make_default_time_series,
)
from opensees_studio.core.load_removal import Scope, remove_loads

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
        vm: ProjectViewModel,
        node_ids: set[int],
        forces: tuple[float, float, float, float, float, float],
        pattern_id: int | None = None,
        new_pattern_name: str | None = None,
        new_ts_type: str = "Linear",
    ) -> None:
        super().__init__(vm, f"Apply load to {len(node_ids)} node(s)")
        self._node_ids = set(node_ids)
        self._forces = forces
        self._pattern_id = pattern_id
        self._new_pattern_name = new_pattern_name
        self._new_ts_type = new_ts_type  # "Linear" or "Constant"
        self._created_ts: TimeSeries | None = None
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
            existing = find_plain_pattern(self.project)
            if existing is not None:
                return existing
        # Need to create both ts + pattern. The TimeSeries kind follows the
        # caller's requested type so constant axial preloads don't get a
        # ramping Linear factor by accident (see core.defaults).
        name = self._new_pattern_name or DEFAULT_PATTERN_NAME
        self._created_ts = make_default_time_series(
            self.project.next_time_series_id(), kind=self._new_ts_type, name=name
        )
        self.project.time_series.append(self._created_ts)
        self._created_pattern = make_default_pattern(
            self.project.next_pattern_id(), self._created_ts.id, name=name
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
        if (
            self._created_pattern is not None
            and self._created_pattern in self.project.load_patterns
        ):
            self.project.load_patterns.remove(self._created_pattern)
            self._created_pattern = None
        if self._created_ts is not None and self._created_ts in self.project.time_series:
            self.project.time_series.remove(self._created_ts)
            self._created_ts = None
        self._notify()


class _ElementLoadCommand(ProjectCommand):
    """Shared pattern handling for the element-load commands.

    Same pattern-resolution strategy as :class:`AddNodalLoadsCommand`:
    reuses an existing plain pattern, or creates a default one, and undo
    rolls that infrastructure back together with the loads.
    """

    #: Name of the ``PlainLoadPattern`` list the subclass appends to.
    _list_name: str

    def __init__(self, vm: ProjectViewModel, text: str, pattern_id: int | None) -> None:
        super().__init__(vm, text)
        self._pattern_id = pattern_id
        self._created_ts: TimeSeries | None = None
        self._created_pattern: PlainLoadPattern | None = None
        self._added_loads: list[tuple[int, Any]] = []

    def _resolve_pattern(self) -> PlainLoadPattern:
        if self._pattern_id is not None:
            for pat in self.project.load_patterns:
                if pat.id == self._pattern_id and isinstance(pat, PlainLoadPattern):
                    return pat
            raise ValueError(f"Plain pattern id={self._pattern_id} not found.")
        existing = find_plain_pattern(self.project)
        if existing is not None:
            return existing
        self._created_ts = make_default_time_series(self.project.next_time_series_id())
        self.project.time_series.append(self._created_ts)
        self._created_pattern = make_default_pattern(
            self.project.next_pattern_id(), self._created_ts.id
        )
        self.project.load_patterns.append(self._created_pattern)
        return self._created_pattern

    def _make_loads(self) -> list[Any]:
        raise NotImplementedError

    def redo(self) -> None:
        loads = self._make_loads()
        pattern = self._resolve_pattern()
        target = getattr(pattern, self._list_name)
        for load in loads:
            target.append(load)
            self._added_loads.append((pattern.id, load))
        self._notify()

    def undo(self) -> None:
        for pid, load in self._added_loads:
            for pat in self.project.load_patterns:
                if pat.id == pid and isinstance(pat, PlainLoadPattern):
                    target = getattr(pat, self._list_name)
                    # By identity: two loads on the same element can be equal.
                    target[:] = [x for x in target if x is not load]
                    break
        self._added_loads.clear()
        if (
            self._created_pattern is not None
            and self._created_pattern in self.project.load_patterns
        ):
            self.project.load_patterns.remove(self._created_pattern)
            self._created_pattern = None
        if self._created_ts is not None and self._created_ts in self.project.time_series:
            self.project.time_series.remove(self._created_ts)
            self._created_ts = None
        self._notify()


class AddElementLoadsCommand(_ElementLoadCommand):
    """Apply a uniform distributed load (wy, wz, wx) to a set of elements."""

    _list_name = "element_loads"

    def __init__(
        self,
        vm: ProjectViewModel,
        element_ids: set[int],
        wy: float = 0.0,
        wz: float = 0.0,
        wx: float = 0.0,
        pattern_id: int | None = None,
    ) -> None:
        super().__init__(vm, f"Apply distributed load to {len(element_ids)} element(s)", pattern_id)
        self._element_ids = set(element_ids)
        self._wy = wy
        self._wz = wz
        self._wx = wx

    def _make_loads(self) -> list[Any]:
        return [
            UniformElementLoad(element_id=eid, wy=self._wy, wz=self._wz, wx=self._wx)
            for eid in self._element_ids
        ]


class AddPointElementLoadsCommand(_ElementLoadCommand):
    """Apply a concentrated load (py, pz, px) inside a set of frame elements.

    ``positions`` maps each element id to the load position as a fraction of
    that element's length from end i, so an absolute distance can be turned
    into a different fraction on each member by the caller. Only beam-column
    elements (``FRAME_ELEMENT_CLASSES``) take the load; any other id is refused
    before anything is changed.
    """

    _list_name = "point_loads"

    def __init__(
        self,
        vm: ProjectViewModel,
        positions: dict[int, float],
        py: float = 0.0,
        pz: float = 0.0,
        px: float = 0.0,
        pattern_id: int | None = None,
    ) -> None:
        super().__init__(vm, f"Apply point load to {len(positions)} element(s)", pattern_id)
        self._positions = dict(positions)
        self._py = py
        self._pz = pz
        self._px = px

    def _make_loads(self) -> list[Any]:
        by_id = {el.id: el for el in self.project.elements}
        not_frames = sorted(
            eid for eid in self._positions if not isinstance(by_id.get(eid), FRAME_ELEMENT_CLASSES)
        )
        if not_frames:
            raise ValueError(
                "A point load needs a frame (beam-column) element; not one: "
                + ", ".join(str(eid) for eid in not_frames)
            )
        return [
            PointElementLoad(element_id=eid, py=self._py, pz=self._pz, px=self._px, x=x)
            for eid, x in sorted(self._positions.items())
        ]


class AddTrapezoidalElementLoadsCommand(_ElementLoadCommand):
    """Apply the same trapezoidal / partial-span load to a set of frame elements.

    ``values`` are the ``TrapezoidalElementLoad`` fields other than
    ``element_id`` (relative distances and the local end values). Only
    beam-column elements take it; any other id is refused before anything changes.
    """

    _list_name = "distributed_loads"

    def __init__(
        self,
        vm: ProjectViewModel,
        element_ids: set[int],
        values: dict[str, float],
        pattern_id: int | None = None,
    ) -> None:
        super().__init__(vm, f"Apply trapezoidal load to {len(element_ids)} element(s)", pattern_id)
        self._element_ids = set(element_ids)
        self._values = dict(values)

    def _make_loads(self) -> list[Any]:
        by_id = {el.id: el for el in self.project.elements}
        not_frames = sorted(
            eid
            for eid in self._element_ids
            if not isinstance(by_id.get(eid), FRAME_ELEMENT_CLASSES)
        )
        if not_frames:
            raise ValueError(
                "A distributed load needs a frame (beam-column) element; not one: "
                + ", ".join(str(eid) for eid in not_frames)
            )
        return [
            TrapezoidalElementLoad(element_id=eid, **self._values)
            for eid in sorted(self._element_ids)
        ]


class AddPatternLoadsCommand(_ElementLoadCommand):
    """Append prebuilt loads to one list of a Plain pattern (surface, floor, imposed).

    ``list_name`` is the ``PlainLoadPattern`` field (``surface_loads``,
    ``floor_loads``, ``imposed_displacements``); with no ``pattern_id`` the
    first Plain pattern is used, or a default one is created (and removed on
    undo), as for the other load commands.
    """

    def __init__(
        self,
        vm: ProjectViewModel,
        list_name: str,
        loads: list[Any],
        pattern_id: int | None = None,
        *,
        text: str | None = None,
    ) -> None:
        super().__init__(vm, text or f"Add {len(loads)} {list_name.replace('_', ' ')}", pattern_id)
        self._list_name = list_name
        self._loads = list(loads)

    def _make_loads(self) -> list[Any]:
        return list(self._loads)


class AddTemperatureLoadsCommand(_ElementLoadCommand):
    """Apply a temperature change (uniform and gradients) to a set of frame elements."""

    _list_name = "temperature_loads"

    def __init__(
        self,
        vm: ProjectViewModel,
        element_ids: set[int],
        *,
        alpha: float,
        uniform: float = 0.0,
        gradient_y: float = 0.0,
        gradient_z: float = 0.0,
        pattern_id: int | None = None,
    ) -> None:
        super().__init__(vm, f"Apply temperature load to {len(element_ids)} element(s)", pattern_id)
        self._element_ids = set(element_ids)
        self._values = {
            "alpha": alpha,
            "uniform": uniform,
            "gradient_y": gradient_y,
            "gradient_z": gradient_z,
        }

    def _make_loads(self) -> list[Any]:
        return [
            TemperatureLoad(element_id=eid, **self._values) for eid in sorted(self._element_ids)
        ]


class DeleteLoadsCommand(ProjectCommand):
    """Edit → Delete Loads: remove loads by type, pattern and selection, in one undo step."""

    def __init__(self, vm: ProjectViewModel, kinds: set[str], scope: Scope) -> None:
        super().__init__(vm, "Delete loads")
        self._kinds = set(kinds)
        self._scope = scope
        self._before: dict[str, Any] | None = None
        self.removed: dict[str, int] = {}

    def redo(self) -> None:
        self._before = snapshot_project(self.project)
        self.removed = remove_loads(self.project, self._kinds, self._scope)
        self._notify()

    def undo(self) -> None:
        if self._before is not None:
            restore_project(self.project, self._before)
        self._notify()
