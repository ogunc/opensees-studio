"""Self weight of the frames, trusses and shells.

A load pattern with a ``self_weight`` multiplier carries, on top of its own
loads, the weight of every member whose section (or, for a member with its own
properties, the member itself) has a unit weight, acting downward — global -Z
(Z is the elevation axis of every model, see :mod:`core.plane`).

Frames: ``gamma * A`` per unit length, as a uniform element load. ``A`` is the
area of an :class:`ElasticSection`, the gross area of a :class:`FiberSection`
(patches, bars and loose fibres), the base section of a
:class:`SectionAggregator`, or the elastic area of a ``BeamWithHinges`` with
its own ``unit_weight``; the member's weight modifier scales it.

OpenSees takes a ``-beamUniform`` load in the element's *local* axes, so the
downward vector is split over local x / y / z here, with the axes the runner
builds the transformation from (:mod:`core.geometry.local_axes`). A column then
takes its weight as an axial load and a sloped rafter as an axial part and a
transverse part.

Trusses (``truss`` / ``corotTruss`` with a ``unit_weight``): ``gamma * area *
L``, half to each end node. A truss takes no element load, and a bar with no
bending carries its weight to its ends exactly like that.

Shells: ``gamma * h`` per unit area of a ``ShellMITC4`` (elastic plate, layered
or plate-fibre section), as **consistent nodal forces** — node i takes ``q *
integral(N_i dA)`` over the real (possibly warped, non-rectangular)
quadrilateral, integrated with 2 x 2 Gauss points, which is exact for the
bilinear shape. A rectangle gives a quarter of its weight to each corner.

Not covered: 2D ``quad`` elements, zero-length elements, bearings and links.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from opensees_studio.core.geometry.elements import (
    FRAME_ELEMENT_CLASSES,
    BeamWithHingesElement,
    CorotTrussElement,
    ShellMITC4Element,
    TrussElement,
)
from opensees_studio.core.geometry.local_axes import frame_local_axes
from opensees_studio.core.loads import UniformElementLoad
from opensees_studio.core.sections import (
    SHELL_SECTION_CLASSES,
    ElasticSection,
    FiberSection,
    SectionAggregator,
)

if TYPE_CHECKING:
    from opensees_studio.core.project import Project

TRUSS_CLASSES = (TrussElement, CorotTrussElement)


def gravity_direction(ndm: int) -> np.ndarray:
    """Unit vector of gravity: -Z, in 2D (the X-Z plane) and in 3D."""
    del ndm  # Z is the elevation axis of every model (see core.plane)
    return np.array([0.0, 0.0, -1.0])


def section_weight_per_length(
    project: Project, section_id: int, _seen: frozenset[int] = frozenset()
) -> float:
    """``gamma * A`` of a frame section, 0 when it has no unit weight.

    An aggregator weighs what the section it wraps weighs (the uniaxial
    materials it adds have no area).
    """
    if section_id in _seen:
        return 0.0
    section = next((s for s in project.sections if s.id == section_id), None)
    if isinstance(section, ElasticSection):
        return section.unit_weight * section.A
    if isinstance(section, FiberSection):
        return section.unit_weight * section.gross_area
    if isinstance(section, SectionAggregator) and section.section_id is not None:
        return section_weight_per_length(project, section.section_id, _seen | {section_id})
    return 0.0


def weight_per_length(project: Project, element: object) -> float:
    """``gamma * A`` of a frame times its weight modifier, 0 when nothing gives it a weight."""
    if not isinstance(element, FRAME_ELEMENT_CLASSES):
        return 0.0
    if isinstance(element, BeamWithHingesElement):
        w = element.unit_weight * element.A
    else:
        w = section_weight_per_length(project, element.section_id)
    return w * element.modifiers.weight


def truss_weight_per_length(element: object) -> float:
    """``gamma * area`` of a truss bar, 0 for anything else."""
    if not isinstance(element, TRUSS_CLASSES):
        return 0.0
    return element.unit_weight * element.area


def self_weight_loads(project: Project, multiplier: float = 1.0) -> list[UniformElementLoad]:
    """One uniform load per weighted frame, in its local axes, scaled by ``multiplier``."""
    if multiplier == 0.0:
        return []
    coords = {node.id: node.coords for node in project.nodes}
    down = gravity_direction(project.ndm)
    loads: list[UniformElementLoad] = []
    for element in project.elements:
        w = weight_per_length(project, element) * multiplier
        if w == 0.0 or len(element.nodes) != 2:
            continue
        axes = frame_local_axes(project.ndm, coords[element.nodes[0]], coords[element.nodes[1]])
        if axes is None:
            continue
        x, y, z = axes
        loads.append(
            UniformElementLoad(
                element_id=element.id,
                wx=float(w * (down @ x)),
                wy=float(w * (down @ y)),
                wz=float(w * (down @ z)),
            )
        )
    return loads


# ──────────────────────────── shells ────────────────────────────
_GAUSS = (-1.0 / np.sqrt(3.0), 1.0 / np.sqrt(3.0))
_CORNERS = ((-1.0, -1.0), (1.0, -1.0), (1.0, 1.0), (-1.0, 1.0))


def weight_per_area(project: Project, element: object) -> float:
    """``gamma * h`` of a shell, 0 when it is not a weighted ``ShellMITC4``."""
    if not isinstance(element, ShellMITC4Element):
        return 0.0
    section = next((s for s in project.sections if s.id == element.section_id), None)
    if not isinstance(section, SHELL_SECTION_CLASSES):
        return 0.0
    return section.unit_weight * section.h


def quad_tributary_areas(points: np.ndarray) -> np.ndarray:
    """``integral(N_i dA)`` for the four corners of a bilinear quad (4 x 3 points).

    The four values add up to the quad's area, also when it is warped.
    """
    shares = np.zeros(4)
    for xi in _GAUSS:
        for eta in _GAUSS:
            n = np.array([0.25 * (1 + a * xi) * (1 + b * eta) for a, b in _CORNERS])
            dn_dxi = np.array([0.25 * a * (1 + b * eta) for a, b in _CORNERS])
            dn_deta = np.array([0.25 * b * (1 + a * xi) for a, b in _CORNERS])
            jacobian = float(np.linalg.norm(np.cross(dn_dxi @ points, dn_deta @ points)))
            shares += n * jacobian  # Gauss weights are 1
    return shares


def nodal_self_weight_loads(project: Project, multiplier: float = 1.0) -> dict[int, np.ndarray]:
    """Node id -> global force (Fx, Fy, Fz) of the weight carried as nodal loads, summed.

    The shells (consistent nodal forces) and the truss bars (half to each end):
    the members a ``-beamUniform`` load cannot reach.
    """
    if multiplier == 0.0:
        return {}
    coords = {node.id: np.asarray(node.coords, dtype=float) for node in project.nodes}
    down = gravity_direction(project.ndm)
    forces: dict[int, np.ndarray] = {}

    def add(node_id: int, weight: float) -> None:
        forces[node_id] = forces.get(node_id, np.zeros(3)) + weight * down

    for element in project.elements:
        q = weight_per_area(project, element) * multiplier
        if q != 0.0:
            points = np.array([coords[node_id] for node_id in element.nodes])
            for node_id, share in zip(element.nodes, quad_tributary_areas(points), strict=True):
                add(node_id, q * share)
            continue
        w = truss_weight_per_length(element) * multiplier
        if w != 0.0:
            i, j = element.nodes[0], element.nodes[-1]
            half = 0.5 * w * float(np.linalg.norm(coords[j] - coords[i]))
            add(i, half)
            add(j, half)
    return forces


def is_weighted(project: Project, element: object) -> bool:
    """Whether a self-weight pattern loads ``element`` (a weighted frame, truss or shell)."""
    return bool(
        weight_per_length(project, element)
        or truss_weight_per_length(element)
        or weight_per_area(project, element)
    )


def total_self_weight(project: Project) -> float:
    """Total weight of the weighted frames, trusses and shells (a check value)."""
    coords = {node.id: np.asarray(node.coords, dtype=float) for node in project.nodes}
    total = 0.0
    for element in project.elements:
        w = weight_per_length(project, element) or truss_weight_per_length(element)
        if w and len(element.nodes) == 2:
            i, j = element.nodes
            total += w * float(np.linalg.norm(coords[j] - coords[i]))
        q = weight_per_area(project, element)
        if q:
            points = np.array([coords[node_id] for node_id in element.nodes])
            total += q * float(quad_tributary_areas(points).sum())
    return total
