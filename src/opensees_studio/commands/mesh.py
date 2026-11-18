"""Apply a mesh plan: replace the originals with the pieces, in one undo step.

The plan (``core.mesh``) says what to add and what to remove; this puts it into
the project. Two things it takes care of that a plain add-and-delete would not:

* **the distributed loads follow the pieces**: a bar cut in three carries the
  same `q` on each third, not a third of it (which is what re-creating the bars
  without their loads would mean, and what leaving the load on the removed
  element would mean in the other direction); a point load goes to the one
  piece it falls on, at its position along that piece;
* **undo is exact**: a mesh touches the node list, the element list and the load
  patterns at once, so the model's fields are snapshotted and put back rather
  than each change being tracked.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np

from opensees_studio.commands.base import ProjectCommand, restore_project, snapshot_project
from opensees_studio.core.loads import PlainLoadPattern, PointElementLoad, TrapezoidalElementLoad
from opensees_studio.core.mesh import MeshPlan

if TYPE_CHECKING:
    from opensees_studio.viewmodels import ProjectViewModel


class MeshCommand(ProjectCommand):
    """Replace the elements a :class:`MeshPlan` lists with the elements it built."""

    def __init__(self, vm: ProjectViewModel, plan: MeshPlan) -> None:
        super().__init__(vm, f"Mesh: {len(plan.new_elements)} element(s)")
        self._plan = plan
        self._before: dict[str, Any] | None = None

    @property
    def plan(self) -> MeshPlan:
        return self._plan

    def redo(self) -> None:
        project = self.project
        self._before = snapshot_project(project)
        removed = set(self._plan.removed_element_ids)

        for pattern in project.load_patterns:
            if not isinstance(pattern, PlainLoadPattern):
                continue
            carried: list[Any] = []
            for load in pattern.element_loads:
                if load.element_id not in removed:
                    carried.append(load)
                    continue
                # The load of a replaced element is re-created on each piece.
                carried.extend(
                    load.model_copy(update={"element_id": new_id})
                    for new_id in self._plan.replacements.get(load.element_id, [])
                )
            pattern.element_loads[:] = carried
            pattern.point_loads[:] = [
                self._carry_point_load(load) if load.element_id in removed else load
                for load in pattern.point_loads
            ]
            distributed: list[Any] = []
            for dload in pattern.distributed_loads:
                if dload.element_id in removed:
                    distributed.extend(self._carry_distributed_load(dload))
                else:
                    distributed.append(dload)
            pattern.distributed_loads[:] = distributed
            # A temperature change is the same on every piece of a divided member.
            pattern.temperature_loads[:] = [
                piece
                for load in pattern.temperature_loads
                for piece in (
                    [load]
                    if load.element_id not in removed
                    else [
                        load.model_copy(update={"element_id": new_id})
                        for new_id in self._plan.replacements.get(load.element_id, [])
                    ]
                )
            ]
            # A uniform pressure is the same on every piece of a meshed shell.
            pattern.surface_loads[:] = [
                piece
                for load in pattern.surface_loads
                for piece in (
                    [load]
                    if load.element_id not in removed
                    else [
                        load.model_copy(update={"element_id": new_id})
                        for new_id in self._plan.replacements.get(load.element_id, [])
                    ]
                )
            ]

        project.elements[:] = [element for element in project.elements if element.id not in removed]
        project.nodes.extend(self._plan.new_nodes)
        project.elements.extend(self._plan.new_elements)
        self._notify()

    def _carry_distributed_load(self, load: TrapezoidalElementLoad) -> list[TrapezoidalElementLoad]:
        """The part of the load on each piece of its element, re-measured along that piece."""
        points = {node.id: np.asarray(node.coords, dtype=float) for node in self.project.nodes}
        points.update(
            {node.id: np.asarray(node.coords, dtype=float) for node in self._plan.new_nodes}
        )
        elements = {element.id: element for element in self.project.elements}
        elements.update({element.id: element for element in self._plan.new_elements})
        start, end = (points[node_id] for node_id in elements[load.element_id].nodes)
        axis = end - start
        length_sq = float(axis @ axis)
        if length_sq == 0.0:
            return [load]
        names = ("wx", "wy", "wz")
        w0, w1 = np.asarray(load.start()), np.asarray(load.end())

        def value_at(t: float) -> np.ndarray:
            return np.asarray(
                w0 + (t - load.x_start) / (load.x_end - load.x_start) * (w1 - w0), dtype=float
            )

        carried: list[TrapezoidalElementLoad] = []
        for piece_id in self._plan.replacements.get(load.element_id, []):
            i, j = (points[node_id] for node_id in elements[piece_id].nodes)
            t0 = float((i - start) @ axis) / length_sq
            t1 = float((j - start) @ axis) / length_sq
            lo, hi = max(t0, load.x_start), min(t1, load.x_end)
            if hi - lo <= 1e-12 or t1 - t0 <= 1e-12:
                continue
            a, b = value_at(lo), value_at(hi)
            fields: dict[str, Any] = {
                "element_id": piece_id,
                "x_start": min(max((lo - t0) / (t1 - t0), 0.0), 1.0),
                "x_end": min(max((hi - t0) / (t1 - t0), 0.0), 1.0),
            }
            for k, name in enumerate(names):
                fields[f"{name}_start"] = float(a[k])
                fields[f"{name}_end"] = float(b[k])
            carried.append(TrapezoidalElementLoad(**fields))
        return carried

    def _carry_point_load(self, load: PointElementLoad) -> PointElementLoad:
        """The load re-created on the piece of its element that it falls on."""
        points = {node.id: np.asarray(node.coords, dtype=float) for node in self.project.nodes}
        points.update(
            {node.id: np.asarray(node.coords, dtype=float) for node in self._plan.new_nodes}
        )
        elements = {element.id: element for element in self.project.elements}
        elements.update({element.id: element for element in self._plan.new_elements})
        start, end = (points[node_id] for node_id in elements[load.element_id].nodes)
        target = start + load.x * (end - start)

        best: tuple[float, int, float] | None = None  # (distance, piece id, x on piece)
        for piece_id in self._plan.replacements.get(load.element_id, []):
            i, j = (points[node_id] for node_id in elements[piece_id].nodes)
            axis = j - i
            length_sq = float(axis @ axis)
            if length_sq == 0.0:
                continue
            x = min(max(float((target - i) @ axis) / length_sq, 0.0), 1.0)
            distance = float(np.linalg.norm(i + x * axis - target))
            if best is None or distance < best[0]:
                best = (distance, piece_id, x)
        if best is None:
            return load
        return load.model_copy(update={"element_id": best[1], "x": best[2]})

    def undo(self) -> None:
        if self._before is not None:
            restore_project(self.project, self._before)
        self._notify()
