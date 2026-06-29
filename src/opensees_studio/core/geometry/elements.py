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
    rho: float = Field(default=0.0, ge=0.0, description="Mass per unit length.")
    consistent_mass: bool = Field(
        default=False,
        description=(
            "Emit the ``-cMass`` flag (consistent element mass matrix) instead of "
            "the default lumped mass. Matches benchmark models that rely on the "
            "consistent mass distribution for their modal periods."
        ),
    )


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
    do_rayleigh: bool = Field(
        default=False,
        description=(
            "Emit the ``-doRayleigh 1`` flag so this element's stiffness contributes "
            "to the stiffness-proportional Rayleigh damping term. OpenSees defaults "
            "zeroLength elements to OFF; an isolator whose initial stiffness anchors a "
            "Kinit-proportional damping target must set this, else the damping omits "
            "the isolators. Default False preserves the original emission."
        ),
    )


class ZeroLengthSectionElement(Entity):
    """Two coincident nodes connected by a full :class:`Section` —
    OpenSees ``element zeroLengthSection``.

    This is the element the Moment-Curvature example uses: node 1 is
    fully restrained, node 2 has axial + rotation free, the section's
    force-deformation response IS the moment-curvature relation that
    the analysis traces via a DisplacementControl integrator on the
    rotational DOF.

    Unlike :class:`ZeroLengthElement` (one uniaxial material per DOF),
    this element carries a section tag that contributes to every
    relevant DOF (P, Mz, My, T, Vy, Vz in 3D).
    """

    type: Literal["ZeroLengthSection"] = "ZeroLengthSection"
    nodes: tuple[PositiveInt, PositiveInt]
    section_id: PositiveInt = Field(..., description="Section attached to the two coincident nodes.")


class BeamWithHingesElement(Entity):
    """Force-based beam with lumped plasticity at both ends —
    ``element beamWithHinges``.

    The element has:
    - Plastic-hinge region at end i with ``section_i_id`` + length ``lp_i``
    - Plastic-hinge region at end j with ``section_j_id`` + length ``lp_j``
    - Elastic middle region characterised by E, A, Iz (+Iy, G, J for 3D)

    The hinge sections are typically ``FiberSection`` or aggregated
    moment-rotation sections (via a Hysteretic uniaxialMaterial). The
    elastic interior uses E·A / E·I properties directly, not a section
    tag — this is the OpenSees signature.
    """

    type: Literal["BeamWithHinges"] = "BeamWithHinges"
    nodes: tuple[PositiveInt, PositiveInt]
    section_i_id: PositiveInt = Field(..., description="Section for plastic hinge at end i.")
    section_j_id: PositiveInt = Field(..., description="Section for plastic hinge at end j.")
    lp_i: PositiveFloat = Field(..., description="Plastic-hinge length at end i.")
    lp_j: PositiveFloat = Field(..., description="Plastic-hinge length at end j.")
    # Elastic interior properties.
    E: PositiveFloat
    A: PositiveFloat
    Iz: PositiveFloat
    # 3D-only (optional for 2D models).
    Iy: float | None = None
    G: float | None = None
    J: float | None = None
    geom_transf: Literal["Linear", "PDelta", "Corotational"] = "Linear"


class QuadElement(Entity):
    """Four-node 2D quadrilateral (plane-stress / plane-strain) —
    ``element quad`` / ``bbarQuad`` / ``enhancedQuad``.

    Requires ``ndm=2, ndf=2``. The four nodes must be listed in
    counter-clockwise order (OpenSees convention). The element pairs a
    thickness with an ``nDMaterial`` (typically ElasticIsotropic for
    linear-elastic analyses). The pressure/behaviour flag picks
    plane-stress vs plane-strain; ``pressure`` is the constant body
    force per unit area (set to 0 for no body force).
    """

    type: Literal["Quad"] = "Quad"
    variant: Literal["quad", "bbarQuad", "enhancedQuad"] = "quad"
    nodes: tuple[PositiveInt, PositiveInt, PositiveInt, PositiveInt]
    thickness: PositiveFloat = Field(..., description="Out-of-plane thickness.")
    material_id: PositiveInt
    behaviour: Literal["PlaneStress2D", "PlaneStrain2D"] = "PlaneStress2D"
    pressure: float = Field(
        default=0.0,
        description="Surface pressure applied over the element (force / area).",
    )
    rho: float = Field(
        default=0.0, ge=0.0,
        description="Mass density override (kip·s²/in⁴). Leave 0 to use material rho.",
    )
    b1: float = Field(
        default=0.0,
        description="Body force per unit volume in global X.",
    )
    b2: float = Field(
        default=0.0,
        description="Body force per unit volume in global Y.",
    )


Element = Annotated[
    Union[
        TrussElement,
        CorotTrussElement,
        ElasticBeamColumn,
        ForceBeamColumn,
        DispBeamColumn,
        ZeroLengthElement,
        ZeroLengthSectionElement,
        BeamWithHingesElement,
        QuadElement,
    ],
    Field(discriminator="type"),
]
