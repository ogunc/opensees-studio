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

import math
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, PositiveFloat, PositiveInt, model_validator

from opensees_studio.core._base import Entity, omit_when_default


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


class WideFlangeShape(BaseModel):
    """I-shape (W, HP, M, S): depth ``d``, flange width ``bf``, web ``tw``, flanges ``tf``.

    Like the other hints, the depth stands along local z (a 3D beam); a 2D frame
    has it along local y.
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)
    kind: Literal["ishape"] = "ishape"
    d: PositiveFloat = Field(..., description="Overall depth.")
    bf: PositiveFloat = Field(..., description="Flange width.")
    tw: PositiveFloat = Field(..., description="Web thickness.")
    tf: PositiveFloat = Field(..., description="Flange thickness.")


class ChannelShape(BaseModel):
    """Channel (C, MC): web along the depth, both flanges on the +width side."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)
    kind: Literal["channel"] = "channel"
    d: PositiveFloat = Field(..., description="Overall depth.")
    bf: PositiveFloat = Field(..., description="Flange width.")
    tw: PositiveFloat = Field(..., description="Web thickness.")
    tf: PositiveFloat = Field(..., description="Flange thickness.")


class TeeShape(BaseModel):
    """Tee (WT, MT, ST): the flange at the top of the depth, the stem below it."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)
    kind: Literal["tee"] = "tee"
    d: PositiveFloat = Field(..., description="Overall depth (flange + stem).")
    bf: PositiveFloat = Field(..., description="Flange width.")
    tw: PositiveFloat = Field(..., description="Stem thickness.")
    tf: PositiveFloat = Field(..., description="Flange thickness.")


class TubeShape(BaseModel):
    """Rectangular hollow section (HSS): depth ``d``, width ``b``, wall ``t``."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)
    kind: Literal["tube"] = "tube"
    d: PositiveFloat = Field(..., description="Outer depth.")
    b: PositiveFloat = Field(..., description="Outer width.")
    t: PositiveFloat = Field(..., description="Wall thickness.")


SectionShape = Annotated[
    PipeShape | AngleShape | RectShape | WideFlangeShape | ChannelShape | TeeShape | TubeShape,
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
    As2: PositiveFloat | None = Field(
        default=None,
        description=(
            "Shear area for shear along local 2 (y). With As2 (and As3 in 3D) set, an "
            "elasticBeamColumn is run as an ElasticTimoshenkoBeam and deforms in shear; "
            "None keeps the Euler-Bernoulli member (no shear deformation). Needs G."
        ),
    )
    As3: PositiveFloat | None = Field(
        default=None, description="Shear area for shear along local 3 (z); 3D frames only."
    )
    shape: SectionShape | None = Field(
        default=None,
        description=(
            "Optional true cross-section geometry (pipe, angle, rectangle, I, channel, "
            "tee, rectangular tube), used ONLY as a "
            "drawing hint for an extruded view. Never emitted to OpenSees and never "
            "read by the analysis (which uses A/Iz/Iy/J only), so it cannot change a "
            "result; absent ⇒ a viewer back-solves an equivalent rectangle from A/Iz."
        ),
    )
    unit_weight: float = Field(
        default=0.0,
        ge=0.0,
        description=(
            "Weight per unit volume (force / length³). Only the self weight of a "
            "load pattern reads it (gamma * A per unit length); it is not a mass."
        ),
    )

    serialize_without_defaults = omit_when_default("unit_weight", "As2", "As3")

    @property
    def has_shear_deformation(self) -> bool:
        """A shear area is set: the member is a Timoshenko beam."""
        return self.As2 is not None or self.As3 is not None


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
    unit_weight: float = Field(
        default=0.0,
        ge=0.0,
        description=(
            "Weight per unit volume (force / length³), applied to the gross area "
            "(:attr:`gross_area`). Only the self weight of a load pattern reads it."
        ),
    )

    serialize_without_defaults = omit_when_default("unit_weight")

    @property
    def gross_area(self) -> float:
        """Area of the patches, the bars of the layers and the loose fibres.

        Bars inside a concrete patch are counted on top of it, so an RC section
        comes out larger by its steel ratio (1-3 %): the weight of one unit
        weight over that area is within the same margin of the true one.
        """
        area = 0.0
        for patch in self.patches:
            if isinstance(patch, RectangularPatch):
                area += abs(patch.y_j - patch.y_i) * abs(patch.z_j - patch.z_i)
            else:
                sweep = min(abs(patch.end_angle - patch.start_angle), 360.0) / 360.0
                area += math.pi * (patch.r_outer**2 - patch.r_inner**2) * sweep
        area += sum(layer.n_bars * layer.bar_area for layer in self.layers)
        area += sum(fibre.area for fibre in self.fibres)
        return area


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


def rc_rectangular_fibres(
    *,
    core_material_id: int,
    cover_material_id: int,
    steel_material_id: int,
    h: float,
    b: float,
    cover: float,
    n_top: int,
    n_bottom: int,
    n_side: int,
    bar_area: float,
    n_fib_h: int = 20,
    n_fib_b: int = 10,
) -> tuple[list[RectangularPatch], list[StraightLayer]]:
    """Patches and bar layers of a rectangular RC section, depth ``h`` along local y.

    The confined core is the rectangle inside the bar centrelines (``cover`` to the
    bar centres); the unconfined cover is the four strips around it. ``n_top`` and
    ``n_bottom`` bars sit on the faces at ±(h/2 - cover), ``n_side`` intermediate bars
    on each side face (between the corner bars).
    """
    if min(h, b, cover, bar_area) <= 0.0:
        raise ValueError("h, b, cover and the bar area must be positive.")
    if 2.0 * cover >= min(h, b):
        raise ValueError("The cover must be less than half the smaller side.")
    if n_top < 2 or n_bottom < 2 or n_side < 0:
        raise ValueError("Top and bottom need at least two bars each; side bars may be zero.")
    yc, zc = 0.5 * h - cover, 0.5 * b - cover
    ye, ze = 0.5 * h, 0.5 * b
    fh, fb = max(n_fib_h, 1), max(n_fib_b, 1)
    cover_fibres = max(1, fh // 10)

    def rect(
        mid: int, ny: int, nz: int, y1: float, z1: float, y2: float, z2: float
    ) -> RectangularPatch:
        return RectangularPatch(
            material_id=mid, n_fib_y=ny, n_fib_z=nz, y_i=y1, z_i=z1, y_j=y2, z_j=z2
        )

    patches = [
        rect(core_material_id, fh, fb, -yc, -zc, yc, zc),
        rect(cover_material_id, cover_fibres, fb, yc, -ze, ye, ze),  # top strip
        rect(cover_material_id, cover_fibres, fb, -ye, -ze, -yc, ze),  # bottom strip
        rect(cover_material_id, fh, cover_fibres, -yc, -ze, yc, -zc),  # left strip
        rect(cover_material_id, fh, cover_fibres, -yc, zc, yc, ze),  # right strip
    ]
    layers = [
        StraightLayer(
            material_id=steel_material_id,
            n_bars=n_top,
            bar_area=bar_area,
            y_start=yc,
            z_start=-zc,
            y_end=yc,
            z_end=zc,
        ),
        StraightLayer(
            material_id=steel_material_id,
            n_bars=n_bottom,
            bar_area=bar_area,
            y_start=-yc,
            z_start=-zc,
            y_end=-yc,
            z_end=zc,
        ),
    ]
    if n_side:
        step = 2.0 * yc / (n_side + 1)
        for z in (-zc, zc):
            layers.append(
                StraightLayer(
                    material_id=steel_material_id,
                    n_bars=n_side,
                    bar_area=bar_area,
                    y_start=-yc + step,
                    z_start=z,
                    y_end=yc - step,
                    z_end=z,
                )
            )
    return patches, layers


def rc_circular_fibres(
    *,
    core_material_id: int,
    cover_material_id: int,
    steel_material_id: int,
    diameter: float,
    cover: float,
    n_bars: int,
    bar_area: float,
    n_fib_circ: int = 16,
    n_fib_rad: int = 8,
) -> tuple[list[CircularPatch], list[StraightLayer]]:
    """Core and cover rings and the bars of a circular RC section."""
    if min(diameter, cover, bar_area) <= 0.0:
        raise ValueError("The diameter, cover and bar area must be positive.")
    if 2.0 * cover >= diameter:
        raise ValueError("The cover must be less than the radius.")
    if n_bars < 3:
        raise ValueError("A circular section needs at least three bars.")
    import math

    r_out, r_core = 0.5 * diameter, 0.5 * diameter - cover
    patches = [
        CircularPatch(
            material_id=core_material_id,
            n_fib_circ=n_fib_circ,
            n_fib_rad=n_fib_rad,
            r_inner=0.0,
            r_outer=r_core,
        ),
        CircularPatch(
            material_id=cover_material_id,
            n_fib_circ=n_fib_circ,
            n_fib_rad=max(1, n_fib_rad // 4),
            r_inner=r_core,
            r_outer=r_out,
        ),
    ]
    # One single-bar straight layer per bar (start = end = the bar), so the fibre
    # section editor, which edits patches and layers, can hold them.
    bars = []
    for k in range(n_bars):
        y = r_core * math.cos(2.0 * math.pi * k / n_bars)
        z = r_core * math.sin(2.0 * math.pi * k / n_bars)
        bars.append(
            StraightLayer(
                material_id=steel_material_id,
                n_bars=1,
                bar_area=bar_area,
                y_start=y,
                z_start=z,
                y_end=y,
                z_end=z,
            )
        )
    return patches, bars


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
    unit_weight: float = Field(
        default=0.0,
        ge=0.0,
        description=(
            "Weight per unit volume (force / length³). Only the self weight of a "
            "load pattern reads it (gamma * h per unit area); it is not a mass."
        ),
    )

    serialize_without_defaults = omit_when_default("unit_weight")


class ShellLayer(BaseModel):
    """One layer of a ``LayeredShell``: a plate nD material and its thickness."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    material_id: PositiveInt = Field(
        ..., description="Plate nD material (PlateFiber, PlateRebar …)."
    )
    thickness: PositiveFloat


class LayeredShellSection(Entity):
    """``section LayeredShell`` — a shell through the thickness, layer by layer.

    Layers go from one face to the other. Concrete layers use a plate material
    (``PlateFromPlaneStress`` of a damage-plasticity concrete, or ``PlateFiber`` of a
    3D material), rebar layers ``PlateRebar`` with the bars' smeared thickness
    (area per unit width). OpenSees needs at least three layers.
    """

    type: Literal["LayeredShell"] = "LayeredShell"
    layers: list[ShellLayer] = Field(..., min_length=3)
    unit_weight: float = Field(default=0.0, ge=0.0, description="Weight per unit volume.")

    @property
    def h(self) -> float:
        """Total thickness."""
        return float(sum(layer.thickness for layer in self.layers))


class PlateFiberSection(Entity):
    """``section PlateFiber`` — one plate nD material through the thickness ``h``."""

    type: Literal["PlateFiber"] = "PlateFiber"
    material_id: PositiveInt = Field(..., description="Plate nD material (PlateFiber of a 3D one).")
    h: PositiveFloat = Field(..., description="Plate thickness.")
    unit_weight: float = Field(default=0.0, ge=0.0, description="Weight per unit volume.")


#: Sections a shell element takes.
SHELL_SECTION_CLASSES = (ElasticMembranePlateSection, LayeredShellSection, PlateFiberSection)


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


NonprismaticVariation = Literal["linear", "parabolic", "cubic"]
"""How a segment's properties vary from its start section to its end section."""


class NonprismaticSegment(BaseModel):
    """One segment of a :class:`NonprismaticSection`.

    The segment runs from ``start_section_id`` to ``end_section_id`` over
    ``length``. ``length_type`` says whether that length is an absolute
    member length (``"absolute"``) or a fraction of the member (``"relative"``).
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    start_section_id: PositiveInt
    end_section_id: PositiveInt
    length_type: Literal["absolute", "relative"] = "relative"
    length: PositiveFloat
    variation: NonprismaticVariation = Field(
        default="linear",
        description=(
            "Variation of the interpolated properties along this segment: linear, "
            "parabolic (u^2) or cubic (u^3), with u measured from start to end."
        ),
    )


class NonprismaticSection(Entity):
    """A tapered frame section built from prismatic :class:`ElasticSection` pieces.

    The section is a *library template*: a frame that references it is
    subdivided into ``subdivisions`` elastic beam-column elements when the
    model is materialised (on import or when the section is assigned). This
    keeps the analysis a plain, linear ``elasticBeamColumn`` model while
    following the taper.

    ``subdivisions`` is the number of elements a member is split into. It is
    deliberately user-editable in the Section Library and defaults to (and
    never goes below) 12, the accuracy the SAP2000 nonprismatic import uses.
    """

    type: Literal["NonprismaticSection"] = "NonprismaticSection"
    segments: list[NonprismaticSegment] = Field(
        ...,
        min_length=1,
        description="Segments in member order, from end i to end j.",
    )
    subdivisions: int = Field(
        default=12,
        ge=12,
        le=200,
        description="Number of beam-column elements a member is split into (minimum 12).",
    )

    serialize_without_defaults = omit_when_default("subdivisions")

    @model_validator(mode="after")
    def _check_lengths(self) -> NonprismaticSection:
        relative = sum(s.length for s in self.segments if s.length_type == "relative")
        absolute = sum(s.length for s in self.segments if s.length_type == "absolute")
        if absolute > 0.0 and relative >= 1.0:
            raise ValueError(
                "Relative segment lengths must add up to less than 1 when absolute "
                f"lengths are also used (they add up to {relative:g})."
            )
        return self

    def fractions(self) -> list[float]:
        """The length of every segment as a fraction of the member (sums to 1).

        Absolute lengths are measured against the member length implied by the
        definition; relative lengths are fractions of that same member. A
        definition made only of relative lengths is normalised so it always
        covers the whole member.
        """
        relative = sum(s.length for s in self.segments if s.length_type == "relative")
        absolute = sum(s.length for s in self.segments if s.length_type == "absolute")
        if absolute > 0.0:
            total = absolute / (1.0 - relative)
            return [
                s.length if s.length_type == "relative" else s.length / total for s in self.segments
            ]
        if relative <= 0.0:
            raise ValueError("A nonprismatic section needs a positive total length.")
        return [s.length / relative for s in self.segments]


Section = Annotated[
    ElasticSection
    | FiberSection
    | SectionAggregator
    | ElasticMembranePlateSection
    | LayeredShellSection
    | PlateFiberSection
    | NonprismaticSection,
    Field(discriminator="type"),
]
