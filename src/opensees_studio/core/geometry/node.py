"""Structural node.

A node carries position, optional lumped mass, and DOF restraints.
Storage is always 3D (z=0 for planar models) and 6-DOF (rotational
components ignored for ndf<6); this uniform shape simplifies the
view layer and persistence.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import Field, field_validator

from opensees_studio.core._base import Entity, omit_when_default

# A 3-tuple of finite floats. Validation is lightweight; range checks live in Project.
Coord3 = Annotated[tuple[float, float, float], Field(description="(x, y, z) in project units.")]
Mass6 = Annotated[
    tuple[float, float, float, float, float, float],
    Field(description="(mx, my, mz, Ixx, Iyy, Izz) lumped mass; non-negative."),
]
Spring6 = Annotated[
    tuple[float, float, float, float, float, float],
    Field(description="(kx, ky, kz, krx, kry, krz) support spring stiffness to ground; >= 0."),
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
    spring: Spring6 = (0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    """Elastic support springs to ground per global DOF (force/length, moment/rad).

    The runner ties the joint to a fixed hidden node with a ``zeroLength`` of
    elastic materials; the spring force is reported as the joint's reaction. A
    project without springs saves byte-identical to before (omitted when zero)."""

    serialize_without_defaults = omit_when_default("spring")

    @field_validator("spring")
    @classmethod
    def _non_negative(cls, spring: tuple[float, ...]) -> tuple[float, ...]:
        if any(k < 0 or k != k for k in spring):
            raise ValueError("Support spring stiffnesses must be finite and not negative.")
        return spring

    @property
    def has_spring(self) -> bool:
        """True if any DOF has a support spring."""
        return any(k > 0 for k in self.spring)

    @property
    def is_restrained(self) -> bool:
        """True if any DOF is fixed."""
        return any(self.restraint)

    @property
    def is_free(self) -> bool:
        """True if no DOF is fixed."""
        return not self.is_restrained
