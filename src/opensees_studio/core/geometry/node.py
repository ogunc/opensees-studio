"""Structural node.

A node carries position, optional lumped mass, and DOF restraints.
Storage is always 3D (z=0 for planar models) and 6-DOF (rotational
components ignored for ndf<6); this uniform shape simplifies the
view layer and persistence.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from opensees_studio.core._base import Entity

# A 3-tuple of finite floats. Validation is lightweight; range checks live in Project.
Coord3 = Annotated[tuple[float, float, float], Field(description="(x, y, z) in project units.")]
Mass6 = Annotated[
    tuple[float, float, float, float, float, float],
    Field(description="(mx, my, mz, Ixx, Iyy, Izz) lumped mass; non-negative."),
]
Restraint6 = Annotated[
    tuple[bool, bool, bool, bool, bool, bool],
    Field(description="(Ux, Uy, Uz, Rx, Ry, Rz) — True means restrained (fixed)."),
]


class Node(Entity):
    """A structural node."""

    coords: Coord3
    mass: Mass6 = (0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    restraint: Restraint6 = (False, False, False, False, False, False)

    @property
    def is_restrained(self) -> bool:
        """True if any DOF is fixed."""
        return any(self.restraint)

    @property
    def is_free(self) -> bool:
        """True if no DOF is fixed."""
        return not self.is_restrained
