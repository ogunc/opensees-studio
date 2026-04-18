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

from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, PositiveFloat, PositiveInt

from opensees_studio.core._base import Entity


# ──────────────────────────── Elastic ────────────────────────────
class ElasticSection(Entity):
    """Linear-elastic frame section — ``section Elastic``."""

    type: Literal["ElasticSection"] = "ElasticSection"
    E: PositiveFloat
    A: PositiveFloat
    Iz: PositiveFloat = Field(..., description="Moment of inertia about local z-axis.")
    Iy: PositiveFloat | None = Field(default=None, description="Required for 3D frames.")
    G: PositiveFloat | None = Field(default=None, description="Shear modulus; required for 3D frames.")
    J: PositiveFloat | None = Field(default=None, description="Torsional constant; required for 3D frames.")


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
    Union[RectangularPatch, CircularPatch],
    Field(discriminator="kind"),
]

Layer = Annotated[
    Union[StraightLayer],
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


# ──────────────────────────── Aggregator ────────────────────────────
class AggregatorDOF(BaseModel):
    """One DOF → uniaxialMaterial pairing inside a ``SectionAggregator``."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    material_id: PositiveInt
    dof: Literal["P", "Mz", "My", "Vy", "Vz", "T"] = Field(
        ..., description="Section DOF code (OpenSees section-deformation names).",
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
    Union[ElasticSection, FiberSection, SectionAggregator],
    Field(discriminator="type"),
]
