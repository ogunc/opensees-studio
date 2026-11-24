"""File → New Model: the templates a new model can start from.

SAP2000's New Model offers a blank model, a grid only and a few parametric
structures. Here the 2D frame, the 2D truss and the warehouse go through their
wizards (:mod:`opensees_studio.core.frames`, :mod:`opensees_studio.core.trusses`,
:mod:`opensees_studio.core.warehouse`); this
module builds the two that have no wizard of their own:

* a **continuous beam** in the X-Z plane of a 2D frame model (ndm 2, ndf 3):
  equal spans on a pin at the left end and rollers on the other supports;
* a **3D frame** (ndm 3, ndf 6): a regular grid of bays in X and Y and storeys
  in Z, columns fixed at the base and beams both ways at every floor.

Each comes with the grid it was built on, so the user keeps drawing on its
lines. Pure: the window inserts the result with the usual add commands.
"""

from __future__ import annotations

from dataclasses import dataclass

from opensees_studio.core.geometry.elements import ElasticBeamColumn
from opensees_studio.core.geometry.grid import (
    CoordinateGridSystem,
    GridSystem,
    make_grid_lines,
)
from opensees_studio.core.geometry.node import Node

#: Template keys, in the order the dialog lists them, with their names.
TEMPLATES: dict[str, str] = {
    "blank": "Blank",
    "grid": "Grid Only",
    "beam": "Beam",
    "truss2d": "2D Truss",
    "frame2d": "2D Frame",
    "frame3d": "3D Frame",
    "warehouse": "Warehouse",
}

#: (ndm, ndf) each template's model is created with.
TEMPLATE_NDF: dict[str, tuple[int, int]] = {
    "blank": (3, 6),
    "grid": (3, 6),
    "beam": (2, 3),
    "truss2d": (2, 2),
    "frame2d": (2, 3),
    "frame3d": (3, 6),
    "warehouse": (3, 6),
}

_PINNED_2D = (True, False, True, False, False, False)  # Ux, Uz
_ROLLER_2D = (False, False, True, False, False, False)  # Uz
_FIXED_3D = (True, True, True, True, True, True)
_FREE = (False, False, False, False, False, False)


class TemplateError(ValueError):
    """The numbers cannot describe the structure."""


@dataclass(frozen=True)
class TemplateModel:
    """A built template: the joints, the members and the grid they sit on."""

    nodes: list[Node]
    elements: list[ElasticBeamColumn]
    grid: CoordinateGridSystem

    def summary(self) -> str:
        return f"{len(self.nodes)} joint(s), {len(self.elements)} member(s)."


def _grid(xs: list[float], ys: list[float], zs: list[float]) -> CoordinateGridSystem:
    """The Global grid: a new model's empty one is what the template fills."""
    return CoordinateGridSystem(
        name="Global",
        grid=GridSystem(
            x_grid_lines=make_grid_lines("X", xs),
            y_grid_lines=make_grid_lines("Y", ys),
            z_grid_lines=make_grid_lines("Z", zs),
        ),
    )


def build_beam(
    n_spans: int,
    span: float,
    *,
    section_id: int,
    first_node_id: int = 1,
    first_element_id: int = 1,
) -> TemplateModel:
    """A continuous beam along X at z = 0: a pin at the left end, rollers elsewhere."""
    if n_spans < 1:
        raise TemplateError("A beam needs at least one span.")
    if span <= 0.0:
        raise TemplateError("The span length must be positive.")
    xs = [i * span for i in range(n_spans + 1)]
    nodes = [
        Node(
            id=first_node_id + i,
            coords=(x, 0.0, 0.0),
            restraint=_PINNED_2D if i == 0 else _ROLLER_2D,
        )
        for i, x in enumerate(xs)
    ]
    elements = [
        ElasticBeamColumn(
            id=first_element_id + i,
            nodes=(first_node_id + i, first_node_id + i + 1),
            section_id=section_id,
        )
        for i in range(n_spans)
    ]
    return TemplateModel(nodes, elements, _grid(xs, [0.0], [0.0]))


def build_space_frame(
    bays_x: int,
    bays_y: int,
    storeys: int,
    spacing_x: float,
    spacing_y: float,
    storey_height: float,
    *,
    column_section_id: int,
    beam_section_id: int,
    first_node_id: int = 1,
    first_element_id: int = 1,
) -> TemplateModel:
    """A regular 3D frame: fixed column bases, beams along X and Y at every floor.

    Columns come first (storey by storey), then the X beams and the Y beams of
    each floor, so the ids read bottom to top.
    """
    if min(bays_x, bays_y, storeys) < 1:
        raise TemplateError("A 3D frame needs at least one bay each way and one storey.")
    if min(spacing_x, spacing_y, storey_height) <= 0.0:
        raise TemplateError("Bay widths and the storey height must be positive.")
    xs = [i * spacing_x for i in range(bays_x + 1)]
    ys = [j * spacing_y for j in range(bays_y + 1)]
    zs = [k * storey_height for k in range(storeys + 1)]

    ids: dict[tuple[int, int, int], int] = {}
    nodes: list[Node] = []
    for k, z in enumerate(zs):
        for j, y in enumerate(ys):
            for i, x in enumerate(xs):
                node_id = first_node_id + len(nodes)
                ids[i, j, k] = node_id
                nodes.append(
                    Node(id=node_id, coords=(x, y, z), restraint=_FIXED_3D if k == 0 else _FREE)
                )

    elements: list[ElasticBeamColumn] = []

    def member(a: int, b: int, section_id: int) -> None:
        elements.append(
            ElasticBeamColumn(
                id=first_element_id + len(elements), nodes=(a, b), section_id=section_id
            )
        )

    for k in range(1, storeys + 1):
        for j in range(bays_y + 1):
            for i in range(bays_x + 1):
                member(ids[i, j, k - 1], ids[i, j, k], column_section_id)
        for j in range(bays_y + 1):
            for i in range(bays_x):
                member(ids[i, j, k], ids[i + 1, j, k], beam_section_id)
        for i in range(bays_x + 1):
            for j in range(bays_y):
                member(ids[i, j, k], ids[i, j + 1, k], beam_section_id)
    return TemplateModel(nodes, elements, _grid(xs, ys, zs))
