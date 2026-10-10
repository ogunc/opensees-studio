"""Cross sections.

Three section kinds:
- ``ElasticSection``: closed-form linear-elastic frame section.
- ``FiberSection``: arbitrary cross section composed of patches, layers,
  and/or individual fibres. The runner emits ``section Fiber`` followed
  by ``patch rect``, ``patch circ``, ``layer straight``, or ``fiber``
  commands.
- ``SectionAggregator``: wraps an existing section and adds uniaxial
  materials for specific DOFs (e.g. torsion via a separate material).
  Maps to ``section Aggregator``.

Patch/Layer geometry models mirror the OpenSees command arguments
exactly so the runner can emit them without further translation.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, PositiveFloat, PositiveInt

from opensees_studio.core._base import Entity


# ──────────────────────────── Section shape hint ────────────────────────────
# An ElasticSection carries only A/Iz/Iy/J — OpenSees' ``section Elastic`` (and the
# ``elasticBeamColumn`` inline form) has no concept of a geometric *type*, so a tube,
# an angle and a rectangle with the same A/I are indistinguishable to the analysis.
# These optional shape hints let an importer/builder record the true cross-section
# geometry purely so a viewer can DRAW it faithfully (a tube as a tube, an angle as an
# L) instead of back-solving an equivalent box. They are NEVER emitted to OpenSees and
# NEVER read by the runner: the stiffness/mass come from A/Iz/Iy/J alone, so attaching
# a shape can never change an analysis result.
class PipeShape(BaseModel):
    """Hollow circular tube (outer diameter ``od``, wall thickness ``t``)."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)
    kind: Literal["pipe"] = "pipe"
    od: PositiveFloat = Field(..., description="Outer diameter.")
    t: PositiveFloat = Field(..., description="Wall thickness (< od/2 for a hollow tube).")


class AngleShape(BaseModel):
    """L angle — legs ``d`` (along local z) and ``b`` (along local y), thickness ``t``."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)
    kind: Literal["angle"] = "angle"
    d: PositiveFloat = Field(..., description="Leg length along local z (depth).")
    b: PositiveFloat = Field(..., description="Leg length along local y (width).")
    t: PositiveFloat = Field(..., description="Leg thickness.")


class RectShape(BaseModel):
    """Solid rectangle — depth ``d`` (along local z) × width ``b`` (along local y)."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)
    kind: Literal["rect"] = "rect"
    d: PositiveFloat = Field(..., description="Depth along local z (height).")
    b: PositiveFloat = Field(..., description="Width along local y.")


SectionShape = Annotated[
    PipeShape | AngleShape | RectShape,
    Field(discriminator="kind"),
]


# ──────────────────────────── Elastic ────────────────────────────
class ElasticSection(Entity):
    """Linear-elastic frame section — ``section Elastic``."""

    type: Literal["ElasticSection"] = "ElasticSection"
    E: PositiveFloat
    A: PositiveFloat
    Iz: PositiveFloat = Field(..., description="Moment of inertia about local z-axis.")
    Iy: PositiveFloat | None = Field(default=None, description="Required for 3D frames.")
    G: PositiveFloat | None = Field(
        default=None, description="Shear modulus; required for 3D frames."
    )
    J: PositiveFloat | None = Field(
        default=None, description="Torsional constant; required for 3D frames."
    )
    shape: SectionShape | None = Field(
        default=None,
        description=(
            "Optional true cross-section geometry (pipe/angle/rect), used ONLY as a "
            "drawing hint for an extruded view. Never emitted to OpenSees and never "
            "read by the analysis (which uses A/Iz/Iy/J only), so it cannot change a "
            "result; absent ⇒ a viewer back-solves an equivalent rectangle from A/Iz."
        ),
    )


# ──────────────────────────── Fiber primitives ────────────────────────────
class Fibre(BaseModel):
    """A single fibre inside a ``FiberSection``."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    y: float = Field(..., description="Local y-coordinate of the fibre centroid.")
    z: float = Field(..., description="Local z-coordinate of the fibre centroid.")
    area: PositiveFloat
    material_id: PositiveInt


class RectangularPatch(BaseModel):
    """``patch rect`` — a rectangular grid of fibres.

    Corners: (y_i, z_i) lower-left, (y_j, z_j) upper-right. Subdivided
    into ``n_fib_y × n_fib_z`` equal fibres, all assigned ``material_id``.
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)
    kind: Literal["rect"] = "rect"

    material_id: PositiveInt
    n_fib_y: PositiveInt = Field(..., description="Fibre subdivisions in local y.")
    n_fib_z: PositiveInt = Field(..., description="Fibre subdivisions in local z.")
    y_i: float
    z_i: float
    y_j: float
    z_j: float


class CircularPatch(BaseModel):
    """``patch circ`` — an annular/circular ring of fibres.

    Centre at (y_center, z_center). ``r_inner`` / ``r_outer`` define the
    radii; use ``r_inner = 0`` for a solid disc. ``n_fib_circ`` ×
    ``n_fib_rad`` subdivisions.
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)
    kind: Literal["circ"] = "circ"

    material_id: PositiveInt
    n_fib_circ: PositiveInt = Field(..., description="Circumferential subdivisions.")
    n_fib_rad: PositiveInt = Field(..., description="Radial subdivisions.")
    y_center: float = 0.0
    z_center: float = 0.0
    r_inner: float = Field(default=0.0, ge=0.0)
    r_outer: PositiveFloat = Field(...)
    start_angle: float = Field(default=0.0, description="Starting angle (degrees).")
    end_angle: float = Field(default=360.0, description="Ending angle (degrees).")


class StraightLayer(BaseModel):
    """``layer straight`` — a line of equally-spaced rebar fibres.

    Runs from (y_start, z_start) to (y_end, z_end) with ``n_bars``
    bars of area ``bar_area`` each, all using ``material_id``.
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)
    kind: Literal["straight"] = "straight"

    material_id: PositiveInt
    n_bars: PositiveInt
    bar_area: PositiveFloat
    y_start: float
    z_start: float
    y_end: float
    z_end: float


Patch = Annotated[
    RectangularPatch | CircularPatch,
    Field(discriminator="kind"),
]

Layer = Annotated[
    StraightLayer,
    Field(discriminator="kind"),
]


# ──────────────────────────── Fiber section ────────────────────────────
class FiberSection(Entity):
    """Discretised section — ``section Fiber``.

    Composed of:
    - ``patches``: rectangular or circular filled regions
    - ``layers``: rebar straight layers
    - ``fibres``: individual point fibres (legacy / custom)

    At least one of the three should be non-empty for a useful section.
    """

    type: Literal["FiberSection"] = "FiberSection"
    GJ: PositiveFloat | None = Field(default=None, description="Optional torsional rigidity.")
    patches: list[Patch] = Field(default_factory=list)
    layers: list[Layer] = Field(default_factory=list)
    fibres: list[Fibre] = Field(default_factory=list)


def w_shape_patches(
    material_id: int,
    d: float,
    bf: float,
    tf: float,
    tw: float,
    n_web: int,
    n_flange: int,
) -> list[RectangularPatch]:
    """Rectangular patches of a wide-flange (W) shape, depth along local y.

    Top flange, web and bottom flange, one material. ``n_flange`` fibres through each
    flange thickness and ``n_web`` along the clear web depth ``d - 2*tf``, one across the
    width: the fibre locations and areas of OpenSees ``section WFSection2d secTag matTag d
    tw bf tf Nfw Nff`` (``Nfw = n_web``, ``Nff = n_flange``), so the two give the same
    section response.
    """
    if min(d, bf, tf, tw) <= 0.0:
        raise ValueError("d, bf, tf and tw must be positive.")
    if d <= 2.0 * tf:
        raise ValueError(f"d ({d}) must exceed twice the flange thickness ({2.0 * tf}).")
    if tw > bf:
        raise ValueError(f"tw ({tw}) must not exceed bf ({bf}).")
    if n_web < 1 or n_flange < 1:
        raise ValueError("Fibre counts must be at least 1.")
    half_d, half_dw = 0.5 * d, 0.5 * d - tf
    return [
        RectangularPatch(
            material_id=material_id,
            n_fib_y=n_flange,
            n_fib_z=1,
            y_i=half_dw,
            z_i=-0.5 * bf,
            y_j=half_d,
            z_j=0.5 * bf,
        ),
        RectangularPatch(
            material_id=material_id,
            n_fib_y=n_web,
            n_fib_z=1,
            y_i=-half_dw,
            z_i=-0.5 * tw,
            y_j=half_dw,
            z_j=0.5 * tw,
        ),
        RectangularPatch(
            material_id=material_id,
            n_fib_y=n_flange,
            n_fib_z=1,
            y_i=-half_d,
            z_i=-0.5 * bf,
            y_j=-half_dw,
            z_j=0.5 * bf,
        ),
    ]


# ──────────────────────────── plate / shell ────────────────────────────
class ElasticMembranePlateSection(Entity):
    """Linear-elastic plate section — ``section ElasticMembranePlateSection``.

    The section a ``ShellMITC4`` element takes. It carries the plate's own
    elastic modulus and thickness rather than referencing a material: OpenSees
    defines this section by (E, nu, h, rho) directly, so a shell model does not
    need an ``nDMaterial`` at all.
    """

    type: Literal["ElasticMembranePlateSection"] = "ElasticMembranePlateSection"
    E: PositiveFloat = Field(..., description="Plate elastic modulus.")
    nu: float = Field(..., ge=-1.0, le=0.5, description="Poisson's ratio.")
    h: PositiveFloat = Field(..., description="Plate thickness.")
    rho: float = Field(default=0.0, ge=0.0, description="Mass density per unit volume.")


# ──────────────────────────── Aggregator ────────────────────────────
class AggregatorDOF(BaseModel):
    """One DOF → uniaxialMaterial pairing inside a ``SectionAggregator``."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    material_id: PositiveInt
    dof: Literal["P", "Mz", "My", "Vy", "Vz", "T"] = Field(
        ...,
        description="Section DOF code (OpenSees section-deformation names).",
    )


class SectionAggregator(Entity):
    """``section Aggregator`` — adds uniaxial materials for specific DOFs
    to an existing section.

    Typical usage: wrap a ``FiberSection`` and add a Hysteretic material
    for torsion (T) or a shear spring (Vy / Vz) that the fibre section
    alone cannot represent.
    """

    type: Literal["SectionAggregator"] = "SectionAggregator"
    section_id: PositiveInt | None = Field(
        default=None,
        description="ID of the base section to wrap. None = aggregator-only (no base).",
    )
    pairings: list[AggregatorDOF] = Field(..., min_length=1)


Section = Annotated[
    ElasticSection | FiberSection | SectionAggregator | ElasticMembranePlateSection,
    Field(discriminator="type"),
]
