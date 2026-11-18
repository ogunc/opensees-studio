"""View → Grid Line View: only the objects lying on one grid line.

A grid line is a plane (a Cartesian X or Y line, or a Z level), a cylinder (a
ring of a cylindrical grid) or a half-plane (a radial line). The objects shown
are the joints within ``tolerance`` of it — measured in the line's own
coordinate system — and the elements all of whose joints are shown. The default
window is 50 mm either side, in the model's length unit.

Pure: the view renders :func:`filtered_project`, the model itself is untouched.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from opensees_studio.core.project import Project
from opensees_studio.core.units import UnitSystem, metres_per_unit

DEFAULT_WINDOW_M = 0.050
"""The default window either side of the line, in metres (50 mm)."""

_AXES = ("X", "Y", "Z")
_CYLINDRICAL_AXES = ("R", "T", "Z")


@dataclass(frozen=True)
class GridLineRef:
    """One grid line: its system, axis (0, 1, 2), id and ordinate."""

    system: str
    axis: int
    line_id: str
    ordinate: float
    cylindrical: bool = False

    @property
    def axis_name(self) -> str:
        return (_CYLINDRICAL_AXES if self.cylindrical else _AXES)[self.axis]

    @property
    def label(self) -> str:
        unit = "°" if self.cylindrical and self.axis == 1 else ""
        return f"{self.system}: {self.axis_name} {self.line_id} ({self.ordinate:g}{unit})"


def default_window(units: UnitSystem) -> float:
    """50 mm in the model's length unit."""
    return DEFAULT_WINDOW_M / metres_per_unit(units)


def grid_lines(project: Project) -> list[GridLineRef]:
    """Every grid line of every coordinate system, in order (system, axis, ordinate)."""
    out: list[GridLineRef] = []
    for cs in project.coord_systems:
        grid = cs.grid
        for axis, lines in enumerate((grid.x_grid_lines, grid.y_grid_lines, grid.z_grid_lines)):
            out.extend(
                GridLineRef(cs.name, axis, ln.id, ln.ordinate, grid.is_cylindrical) for ln in lines
            )
    return out


def find_grid_line(project: Project, label: str) -> GridLineRef | None:
    """The line whose :attr:`GridLineRef.label` is ``label`` (None if it is gone)."""
    return next((ref for ref in grid_lines(project) if ref.label == label), None)


def _distance(ref: GridLineRef, local: tuple[float, float, float]) -> float:
    x, y, _z = local
    if not ref.cylindrical or ref.axis == 2:
        return abs(local[ref.axis] - ref.ordinate)
    if ref.axis == 0:  # ring: distance to the cylinder of that radius
        return abs(math.hypot(x, y) - ref.ordinate)
    # radial line: distance to the half-plane from the axis towards the angle
    c, s = math.cos(math.radians(ref.ordinate)), math.sin(math.radians(ref.ordinate))
    along = x * c + y * s
    across = abs(-x * s + y * c)
    return across if along >= 0.0 else math.hypot(along, across)


def objects_on_line(
    project: Project, ref: GridLineRef, tolerance: float
) -> tuple[frozenset[int], frozenset[int]]:
    """(joint ids, element ids) within ``tolerance`` of the line.

    An element is on the line when every one of its joints is.
    """
    system = next((cs for cs in project.coord_systems if cs.name == ref.system), None)
    if system is None:
        return frozenset(), frozenset()
    tol = max(float(tolerance), 0.0)
    nodes = frozenset(
        n.id
        for n in project.nodes
        if _distance(ref, system.coord.world_to_local(n.coords)) <= tol + 1e-12
    )
    elements = frozenset(
        e.id for e in project.elements if e.nodes and all(nid in nodes for nid in e.nodes)
    )
    return nodes, elements


def filtered_project(project: Project, nodes: frozenset[int], elements: frozenset[int]) -> Project:
    """A shallow copy holding only ``nodes`` and ``elements`` (for display only).

    Loads on hidden joints and elements are dropped with them, so the copy never
    points at something it does not hold.
    """
    patterns = []
    for pattern in project.load_patterns:
        update: dict[str, object] = {}
        for name, key, pool in (
            ("nodal_loads", "node_id", nodes),
            ("imposed_displacements", "node_id", nodes),
            ("element_loads", "element_id", elements),
            ("distributed_loads", "element_id", elements),
            ("point_loads", "element_id", elements),
            ("surface_loads", "element_id", elements),
            ("temperature_loads", "element_id", elements),
        ):
            items = getattr(pattern, name, None)
            if items is not None:
                update[name] = [it for it in items if getattr(it, key, None) in pool]
        floors = getattr(pattern, "floor_loads", None)
        if floors is not None:
            update["floor_loads"] = [f for f in floors if all(n in nodes for n in f.nodes)]
        patterns.append(pattern.model_copy(update=update) if update else pattern)

    def shown(*ids: int) -> bool:
        return all(i in nodes for i in ids)

    return project.model_copy(
        update={
            "nodes": [n for n in project.nodes if n.id in nodes],
            "elements": [e for e in project.elements if e.id in elements],
            "load_patterns": patterns,
            "mp_constraints": [
                c for c in project.mp_constraints if shown(c.retained_node, c.constrained_node)
            ],
            "rigid_links": [
                c for c in project.rigid_links if shown(c.retained_node, c.constrained_node)
            ],
            "diaphragms": [
                d for d in project.diaphragms if shown(d.retained_node, *d.constrained_nodes)
            ],
        }
    )
