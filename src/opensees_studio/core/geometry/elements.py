"""Structural elements.

Each element references its connecting nodes by id and (depending on
type) a material or a section by id. ID-resolution and existence checks
are performed by the ``Project`` validator, not by the element itself —
this keeps element instances cheap and freely constructible.

Conventions follow OpenSeesPy ``element ...`` commands.
"""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import Field, PositiveFloat, PositiveInt

from opensees_studio.core._base import Entity


class TrussElement(Entity):
    """Two-node truss with axial stiffness only — ``element truss``."""

    type: Literal["Truss"] = "Truss"
    nodes: tuple[PositiveInt, PositiveInt]
    area: PositiveFloat
    material_id: PositiveInt
    rho: float = Field(default=0.0, ge=0.0, description="Mass per unit length.")


class CorotTrussElement(Entity):
    """Co-rotational truss for large displacements — ``element corotTruss``."""

    type: Literal["CorotTruss"] = "CorotTruss"
    nodes: tuple[PositiveInt, PositiveInt]
    area: PositiveFloat
    material_id: PositiveInt
    rho: float = Field(default=0.0, ge=0.0)


class ElasticBeamColumn(Entity):
    """Linear-elastic frame element — ``element elasticBeamColumn``.

    Pure-section style: provide section_id; OpenSees pulls EA, EI from
    the section. (The alternate signature with raw E, A, I is omitted
    here in favour of one consistent parameterisation.)
    """

    type: Literal["ElasticBeamColumn"] = "ElasticBeamColumn"
    nodes: tuple[PositiveInt, PositiveInt]
    section_id: PositiveInt
    geom_transf: Literal["Linear", "PDelta", "Corotational"] = "Linear"
    rho: float = Field(default=0.0, ge=0.0)


class ForceBeamColumn(Entity):
    """Force-based fibre frame element — ``element forceBeamColumn``."""

    type: Literal["ForceBeamColumn"] = "ForceBeamColumn"
    nodes: tuple[PositiveInt, PositiveInt]
    section_id: PositiveInt
    integration_points: int = Field(default=5, ge=2, le=10)
    geom_transf: Literal["Linear", "PDelta", "Corotational"] = "Linear"
    max_iter: int = Field(default=10, ge=1)
    tolerance: float = Field(default=1e-12, gt=0.0)


class DispBeamColumn(Entity):
    """Displacement-based fibre frame element — ``element dispBeamColumn``."""

    type: Literal["DispBeamColumn"] = "DispBeamColumn"
    nodes: tuple[PositiveInt, PositiveInt]
    section_id: PositiveInt
    integration_points: int = Field(default=5, ge=2, le=10)
    geom_transf: Literal["Linear", "PDelta", "Corotational"] = "Linear"


class ZeroLengthElement(Entity):
    """Two coincident nodes connected by uniaxial materials per DOF.

    Foundation building block for plastic hinges and isolators.
    """

    type: Literal["ZeroLength"] = "ZeroLength"
    nodes: tuple[PositiveInt, PositiveInt]
    material_ids: tuple[PositiveInt, ...] = Field(..., min_length=1)
    dofs: tuple[int, ...] = Field(..., min_length=1, description="DOF directions, 1-indexed (1..6).")


Element = Annotated[
    Union[
        TrussElement,
        CorotTrussElement,
        ElasticBeamColumn,
        ForceBeamColumn,
        DispBeamColumn,
        ZeroLengthElement,
    ],
    Field(discriminator="type"),
]
