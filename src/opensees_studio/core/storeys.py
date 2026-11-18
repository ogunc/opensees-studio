"""Storeys: the floor levels of a building.

A :class:`Storey` is a named elevation. The elevation axis is the model's
vertical one: global Z in a 3D model, Y in a 2D one (the canvas convention,
the same one :func:`core.self_weight.gravity_direction` uses).

The levels below the lowest storey belong to the *base*: the base elevation is
the lowest node of the model. A storey's height is the distance to the storey
(or the base) below it, which is what an inter-storey drift ratio divides by.

Storeys can be typed in or taken from the Z grid lines of a coordinate system
(:func:`storeys_from_grid`), the way ETABS reads its story data from the grid.

No Qt, no OpenSees.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from pydantic import Field

from opensees_studio.core._base import Entity
from opensees_studio.core.plane import VERTICAL_AXIS

if TYPE_CHECKING:
    from opensees_studio.core.geometry import CoordinateGridSystem
    from opensees_studio.core.project import Project

ELEVATION_REL_TOL = 1e-6
"""A node belongs to a level when it lies within this fraction of the model's
height span (at least an absolute 1e-9) of the level's elevation."""


class Storey(Entity):
    """A floor level: a name and an elevation along the vertical axis."""

    elevation: float = Field(..., description="Elevation of the floor, in model length units.")


def elevation_axis(ndm: int) -> int:
    """Index of the vertical coordinate: 2 (Z), in 2D and in 3D (see core.plane)."""
    del ndm
    return VERTICAL_AXIS


def lateral_axes(ndm: int) -> tuple[int, ...]:
    """Indices of the horizontal coordinates: (X,) in 2D, (X, Y) in 3D."""
    return (0,) if ndm == 2 else (0, 1)


def elevation_tolerance(project: Project) -> float:
    """How far from a level a node may lie and still belong to it."""
    axis = elevation_axis(project.ndm)
    values = [float(n.coords[axis]) for n in project.nodes]
    values += [float(s.elevation) for s in project.storeys]
    span = (max(values) - min(values)) if values else 0.0
    return max(ELEVATION_REL_TOL * span, 1e-9)


def sorted_storeys(project: Project) -> list[Storey]:
    """The project's storeys from the lowest to the highest."""
    return sorted(project.storeys, key=lambda s: (s.elevation, s.id))


def base_elevation(project: Project) -> float:
    """Elevation of the lowest node; the lowest storey when there is no node."""
    axis = elevation_axis(project.ndm)
    if project.nodes:
        return min(float(n.coords[axis]) for n in project.nodes)
    if project.storeys:
        return min(s.elevation for s in project.storeys)
    return 0.0


def nodes_at_elevation(project: Project, elevation: float) -> list[int]:
    """Ids of the nodes lying on the level ``elevation`` (sorted)."""
    axis = elevation_axis(project.ndm)
    tol = elevation_tolerance(project)
    return sorted(n.id for n in project.nodes if abs(float(n.coords[axis]) - elevation) <= tol)


def storey_node_ids(project: Project, storey: Storey) -> list[int]:
    """Ids of the nodes on ``storey``'s floor (sorted)."""
    return nodes_at_elevation(project, storey.elevation)


@dataclass(frozen=True)
class StoreyLevel:
    """One row of the storey table: a storey and the level below it.

    ``below`` is the elevation of the storey (or the base) underneath, so
    ``height`` is the storey height a drift ratio divides by. ``nodes`` are the
    joints on the floor, ``below_nodes`` those on the level underneath.
    """

    storey: Storey
    below: float
    nodes: tuple[int, ...]
    below_nodes: tuple[int, ...]

    @property
    def height(self) -> float:
        return self.storey.elevation - self.below


def storey_levels(project: Project) -> list[StoreyLevel]:
    """The storeys above the base, lowest first, each with the level beneath it.

    A storey at or below the base elevation is the base itself and gets no row.
    """
    tol = elevation_tolerance(project)
    below = base_elevation(project)
    levels: list[StoreyLevel] = []
    for storey in sorted_storeys(project):
        if storey.elevation <= below + tol:
            continue
        levels.append(
            StoreyLevel(
                storey=storey,
                below=below,
                nodes=tuple(storey_node_ids(project, storey)),
                below_nodes=tuple(nodes_at_elevation(project, below)),
            )
        )
        below = storey.elevation
    return levels


def storeys_from_grid(
    system: CoordinateGridSystem,
    *,
    first_id: int = 1,
    include_lowest: bool = False,
) -> list[Storey]:
    """One storey per Z grid line of ``system``, lowest first.

    The lowest line is the base and is left out unless ``include_lowest``. The
    elevation is the line's ordinate shifted by the system's origin (a rotated
    system keeps a horizontal floor only when it rotates about Z, which is the
    only rotation a storey can follow). Names are ``Story1``, ``Story2``... as
    in ETABS.
    """
    origin_z = float(system.coord.origin[2])
    ordinates = sorted({float(line.ordinate) for line in system.grid.z_grid_lines})
    if not include_lowest:
        ordinates = ordinates[1:]
    return [
        Storey(id=first_id + i, name=f"Story{i + 1}", elevation=origin_z + z)
        for i, z in enumerate(ordinates)
    ]
