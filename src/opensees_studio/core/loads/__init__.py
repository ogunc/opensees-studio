"""Loads, time series, and load patterns.

OpenSees load model:
- ``timeSeries``: scalar function of time (Linear, Constant, Path, …)
- ``pattern``: applies a time series to a collection of loads
- ``load``: nodal force vector
- ``eleLoad``: distributed (``-beamUniform``) or point (``-beamPoint``) element load

Hierarchy here mirrors that. Patterns own their child loads — when a
pattern is deleted, its loads go with it.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, PositiveFloat, PositiveInt, model_validator

from opensees_studio.core._base import Entity, omit_when_default


# ──────────────────────────── Time series ────────────────────────────
class LinearTimeSeries(Entity):
    """``timeSeries Linear`` — value = factor * time."""

    type: Literal["Linear"] = "Linear"
    factor: float = 1.0


class ConstantTimeSeries(Entity):
    """``timeSeries Constant`` — value = factor (independent of time)."""

    type: Literal["Constant"] = "Constant"
    factor: float = 1.0


class PathTimeSeries(Entity):
    """``timeSeries Path`` — tabulated values at uniform dt or explicit times.

    Use either ``dt`` + ``values`` (uniform sampling) or explicit
    ``times`` paired with ``values``.
    """

    type: Literal["Path"] = "Path"
    factor: float = 1.0
    dt: float | None = Field(default=None, gt=0.0)
    times: list[float] | None = None
    values: list[float] = Field(
        default_factory=list,
        description=(
            "Sample values. Required for a plain series; for a record-backed "
            "series (``record_id`` set) they are hydrated from the record file "
            "on load and NOT saved into the project file."
        ),
    )
    record_id: PositiveInt | None = Field(
        default=None,
        description=(
            "Id of the ground-motion catalog entry this series is backed by. "
            "When set, ``values`` come from the record file (relative path + "
            "content hash) instead of being embedded in ``.osmodel``. An empty "
            "``values`` list then means the record is missing or changed on "
            "disk - analysis refuses to run such a series."
        ),
    )
    file_path: str | None = Field(
        default=None,
        description="Optional source file (informational; superseded by ``record_id``).",
    )
    use_last: bool = Field(
        default=False,
        description=(
            "Emit ``-useLast``: beyond the last point the series holds its final "
            "value instead of dropping to 0. Essential when the series is an "
            "imposed support DISPLACEMENT and the analysis end lands on (or a "
            "float-accumulation hair past) the record end — without it the "
            "support snaps to zero in the final step."
        ),
    )
    generator: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Descriptor of a generated (synthetic) series: the ``kind`` and the "
            "parameters that ``core.generators.from_descriptor`` needs to rebuild "
            "the values. Set together with ``file_path='generated:<kind>'``; the "
            "values stay embedded in the project file."
        ),
    )

    def model_post_init(self, _ctx) -> None:  # type: ignore[no-untyped-def]
        if not self.values and self.record_id is None:
            raise ValueError(
                "PathTimeSeries requires values unless it is record-backed (record_id set)."
            )


class ResponseSpectrum(Entity):
    """Tabulated period-vs-spectral-acceleration response spectrum.

    Used by :class:`ResponseSpectrumCase` to obtain Sa(T) for each
    eigen-mode. Pairs are sorted by period at validation time. Periods
    must be strictly positive and monotonically increasing.

    Spectrum values are spectral pseudo-accelerations in the project's
    unit system (e.g. m/s² for SI). Damping is informational — it
    documents which damping ratio the spectrum was constructed for and
    influences the CQC modal correlation if not overridden at the case.
    """

    type: Literal["ResponseSpectrum"] = "ResponseSpectrum"
    periods: list[float] = Field(
        ...,
        min_length=2,
        description="Periods (s), strictly increasing.",
    )
    accelerations: list[float] = Field(
        ...,
        min_length=2,
        description="Spectral pseudo-accelerations (length must match `periods`).",
    )
    damping_ratio: float = Field(
        default=0.05,
        ge=0.0,
        le=1.0,
        description="Modal damping ratio the spectrum was built for.",
    )

    def model_post_init(self, _ctx) -> None:  # type: ignore[no-untyped-def]
        if len(self.periods) != len(self.accelerations):
            raise ValueError(
                f"periods ({len(self.periods)}) and accelerations "
                f"({len(self.accelerations)}) length mismatch.",
            )
        for i in range(1, len(self.periods)):
            if self.periods[i] <= self.periods[i - 1]:
                raise ValueError(
                    f"periods must be strictly increasing; got "
                    f"{self.periods[i - 1]} → {self.periods[i]} at index {i}.",
                )
        if self.periods[0] <= 0.0:
            raise ValueError("periods must be strictly positive.")


class TrigTimeSeries(Entity):
    """``timeSeries Trig`` - continuous sine ``factor * sin(2 pi (t - t_start) / period + shift) + zero_shift``.

    Non-zero only for ``t_start <= t <= t_end``. ``factor`` is the amplitude
    in the unit the pattern expects (for a ``UniformExcitationPattern``: the
    project's acceleration unit).
    """

    type: Literal["Trig"] = "Trig"
    factor: float = 1.0
    t_start: float = Field(default=0.0, ge=0.0)
    t_end: float = Field(..., gt=0.0)
    period: float = Field(..., gt=0.0)
    shift: float = Field(default=0.0, description="Phase shift in radians.")
    zero_shift: float = Field(default=0.0, description="Constant offset added to the sine.")
    generator: dict[str, Any] | None = Field(
        default=None,
        description="Descriptor of the generator that built this series, if any.",
    )

    @property
    def frequency(self) -> float:
        return 1.0 / self.period

    def model_post_init(self, _ctx) -> None:  # type: ignore[no-untyped-def]
        if self.t_end <= self.t_start:
            raise ValueError(f"t_end ({self.t_end}) must be greater than t_start ({self.t_start}).")


class _WindowedSeries(Entity):
    """A series non-zero only for ``t_start <= t <= t_end`` (Triangle, Rectangular, Pulse)."""

    factor: float = 1.0
    t_start: float = Field(default=0.0, ge=0.0)
    t_end: float = Field(..., gt=0.0)

    def model_post_init(self, _ctx) -> None:  # type: ignore[no-untyped-def]
        if self.t_end <= self.t_start:
            raise ValueError(f"t_end ({self.t_end}) must be greater than t_start ({self.t_start}).")


class TriangleTimeSeries(_WindowedSeries):
    """``timeSeries Triangle`` - a triangular wave of ``period`` between t_start and t_end."""

    type: Literal["Triangle"] = "Triangle"
    period: float = Field(..., gt=0.0)
    shift: float = Field(default=0.0, description="Phase shift in radians.")
    zero_shift: float = Field(default=0.0, description="Constant offset added to the wave.")


class RectangularTimeSeries(_WindowedSeries):
    """``timeSeries Rectangular`` - ``factor`` between t_start and t_end, zero elsewhere."""

    type: Literal["Rectangular"] = "Rectangular"


class PulseTimeSeries(_WindowedSeries):
    """``timeSeries Pulse`` - rectangular pulses of ``period``, on for ``width`` of each period."""

    type: Literal["Pulse"] = "Pulse"
    period: float = Field(..., gt=0.0)
    width: float = Field(default=0.5, gt=0.0, lt=1.0, description="Fraction of the period on.")
    shift: float = Field(default=0.0, description="Time shift of the pulses.")
    zero_shift: float = Field(default=0.0, description="Constant offset added to the pulses.")


TimeSeries = Annotated[
    LinearTimeSeries
    | ConstantTimeSeries
    | PathTimeSeries
    | TrigTimeSeries
    | TriangleTimeSeries
    | RectangularTimeSeries
    | PulseTimeSeries,
    Field(discriminator="type"),
]


# ──────────────────────────── Loads ────────────────────────────
class NodalLoad(BaseModel):
    """A force/moment vector applied at a node — ``load <nodeTag> Fx Fy Fz Mx My Mz``."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    node_id: PositiveInt
    forces: tuple[float, float, float, float, float, float] = Field(
        ..., description="(Fx, Fy, Fz, Mx, My, Mz)."
    )


class UniformElementLoad(BaseModel):
    """Uniformly distributed load on a line element — ``eleLoad -ele N -type -beamUniform wy wz wx``.

    Conventions (OpenSees):
    - ``wy``, ``wz`` are transverse loads per unit length in the element's
      **local** y / z axes.
    - ``wx`` is an optional axial load per unit length along local x.
    All values can be negative; gravity is typically wy = -q (q > 0).
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    element_id: PositiveInt
    wy: float = 0.0
    wz: float = 0.0
    wx: float = 0.0


class PointElementLoad(BaseModel):
    """Concentrated load inside a frame element — ``eleLoad -ele N -type -beamPoint Py Pz xL Px``.

    Conventions (OpenSees):
    - ``py``, ``pz`` are transverse forces in the element's **local** y / z
      axes, ``px`` an optional axial force along local x.
    - ``x`` is the position as a fraction of the element length, measured
      from end i (0 = node i, 1 = node j).
    Only beam-column elements take it (see ``FRAME_ELEMENT_CLASSES``).
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    element_id: PositiveInt
    py: float = 0.0
    pz: float = 0.0
    px: float = 0.0
    x: float = Field(default=0.5, ge=0.0, le=1.0, description="Relative position x/L from end i.")


class TrapezoidalElementLoad(BaseModel):
    """Linearly varying load over part or all of a frame element (SAP2000 *Frame Distributed* load).

    Conventions:
    - ``w*_start`` / ``w*_end`` are the load per unit length at ``x_start`` and
      ``x_end``, in the element's **local** axes (``wy``, ``wz`` transverse,
      ``wx`` axial), varying linearly in between; the load is zero outside.
    - ``x_start`` < ``x_end`` are relative distances from end i along the full
      joint-to-joint length (0 = joint i, 1 = joint j). A part that falls on a
      rigid end zone goes straight to the joint (force plus moment).
    A uniform load over the whole member is the special case
    ``x_start = 0, x_end = 1`` with equal end values; ``UniformElementLoad``
    remains the way to write that one.
    Only beam-column elements take it (see ``FRAME_ELEMENT_CLASSES``).
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    element_id: PositiveInt
    x_start: float = Field(default=0.0, ge=0.0, le=1.0, description="Relative start x/L.")
    x_end: float = Field(default=1.0, ge=0.0, le=1.0, description="Relative end x/L.")
    wy_start: float = 0.0
    wy_end: float = 0.0
    wz_start: float = 0.0
    wz_end: float = 0.0
    wx_start: float = 0.0
    wx_end: float = 0.0

    @model_validator(mode="after")
    def _ordered(self) -> TrapezoidalElementLoad:
        if not self.x_end > self.x_start:
            raise ValueError(
                f"A distributed load needs x_end > x_start (got {self.x_start} to {self.x_end})."
            )
        return self

    def start(self) -> tuple[float, float, float]:
        """``(wx, wy, wz)`` at ``x_start``."""
        return (self.wx_start, self.wy_start, self.wz_start)

    def end(self) -> tuple[float, float, float]:
        """``(wx, wy, wz)`` at ``x_end``."""
        return (self.wx_end, self.wy_end, self.wz_end)


class SurfaceLoad(BaseModel):
    """A uniform pressure on a shell (SAP2000 *Area Uniform* load), force per area.

    ``direction`` ``"normal"`` acts along the shell's own normal (the right-hand
    turn of its nodes 1-2-3-4, positive along it); ``"X"``, ``"Y"``, ``"Z"``
    act along a global axis, so a floor's weight is ``direction="Z"`` with a
    negative value. The runner turns it into consistent nodal forces.
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    element_id: PositiveInt
    value: float
    direction: Literal["normal", "X", "Y", "Z"] = "Z"


class FloorLoad(BaseModel):
    """A floor panel's load handed to the frames around it (SAP2000 *area load to frames*).

    ``nodes`` are the panel's four corners in order, on a horizontal rectangle;
    ``value`` is the load per area acting **downward** (-Z). ``distribution``:

    - ``"two_way"``: 45° yield lines from the corners — each edge takes the
      load of its trapezoid (or triangle), ``w(t) = q min(t, L - t, s/2)`` with
      ``s`` the panel's short side;
    - ``"one_way_12"``: the slab spans parallel to edge 1-2, so edges 2-3 and
      4-1 each take ``q |1-2| / 2``, uniform;
    - ``"one_way_23"``: the slab spans parallel to edge 2-3, so edges 1-2 and
      3-4 each take ``q |2-3| / 2``.

    Each edge needs frame members along all of it; the loads become
    trapezoidal member loads (see :mod:`core.area_loads`).
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    nodes: tuple[PositiveInt, PositiveInt, PositiveInt, PositiveInt]
    value: float
    distribution: Literal["two_way", "one_way_12", "one_way_23"] = "two_way"


class ImposedDisplacement(BaseModel):
    """A static displacement imposed on a node DOF (a support settlement), ``sp``.

    ``dof`` is the OpenSees DOF number (1..ndf: a 2D frame's 1, 2, 3 are Ux,
    Uz, Ry); ``value`` is in the global sign convention (a 2D rotation about
    +Y). On a restrained DOF the support moves by ``value``; on a free DOF the
    node is held there for the cases that run this pattern.
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    node_id: PositiveInt
    dof: int = Field(..., ge=1, le=6)
    value: float


class TemperatureLoad(BaseModel):
    """A temperature change of a frame member: uniform, and a gradient across each axis.

    The member's temperature is ``uniform + gradient_y * y + gradient_z * z`` at
    the point ``(y, z)`` of its cross section, in the member's local axes
    (``gradient_y`` is the temperature difference per unit depth along local
    y: a face at ``+y`` hotter than the one at ``-y`` has ``gradient_y > 0``).
    ``alpha`` is the coefficient of thermal expansion (per degree).

    OpenSees' elastic frame elements take no thermal load, so the runner applies
    the equivalent nodal loads (minus the member's fixed-end forces) and adds the
    fixed-end forces back to the member's end forces: ``N = EA (ε - α ΔT)``,
    ``M = EI (κ - α g)``. Elastic members without releases or end offsets only;
    static cases only.
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    element_id: PositiveInt
    alpha: PositiveFloat = Field(..., description="Coefficient of thermal expansion, 1/°.")
    uniform: float = Field(default=0.0, description="Uniform temperature change, °.")
    gradient_y: float = Field(default=0.0, description="Temperature change per unit local y.")
    gradient_z: float = Field(default=0.0, description="Temperature change per unit local z.")


# ──────────────────────────── Patterns ────────────────────────────
class PlainLoadPattern(Entity):
    """``pattern Plain`` — links a time series to a set of nodal and element loads."""

    type: Literal["Plain"] = "Plain"
    time_series_id: PositiveInt
    nodal_loads: list[NodalLoad] = Field(default_factory=list)
    element_loads: list[UniformElementLoad] = Field(default_factory=list)
    point_loads: list[PointElementLoad] = Field(default_factory=list)
    distributed_loads: list[TrapezoidalElementLoad] = Field(default_factory=list)
    surface_loads: list[SurfaceLoad] = Field(default_factory=list)
    floor_loads: list[FloorLoad] = Field(default_factory=list)
    imposed_displacements: list[ImposedDisplacement] = Field(default_factory=list)
    temperature_loads: list[TemperatureLoad] = Field(default_factory=list)
    self_weight: float = Field(
        default=0.0,
        description=(
            "Self-weight multiplier: the pattern also carries this factor times the "
            "weight of every frame whose section has a unit weight, acting "
            "downward (-Z, in 2D and in 3D). 0 = no self weight."
        ),
    )

    serialize_without_defaults = omit_when_default(
        "point_loads",
        "distributed_loads",
        "surface_loads",
        "floor_loads",
        "imposed_displacements",
        "temperature_loads",
        "self_weight",
    )


class UniformExcitationPattern(Entity):
    """``pattern UniformExcitation`` — base ground motion in a single direction."""

    type: Literal["UniformExcitation"] = "UniformExcitation"
    direction: int = Field(..., ge=1, le=6, description="DOF direction (1..6).")
    accel_series_id: PositiveInt
    vel_series_id: PositiveInt | None = None
    disp_series_id: PositiveInt | None = None
    factor: float = 1.0


class ImposedSupportMotionPattern(Entity):
    """``pattern MultipleSupport`` — imposed support DISPLACEMENT at fixed nodes.

    One ``groundMotion Plain -disp`` shared by every listed node, applied via
    ``imposedMotion`` in a single direction. The nodes must be modelled
    *restrained* in the driven DOF (a grounded support): static/modal cases see
    the ordinary fix, and the runner swaps the fix for the imposed motion when
    this pattern is emitted — i.e. the ground is at rest until the transient
    starts. All other DOFs keep their restraints untouched.

    Only ``disp_series_id`` is stored (single-source rule: the displacement
    record IS the input). The runner derives the matching velocity series by
    central differences at emission time — ``ImposedMotionSP`` enforces both
    displacement and velocity at the constrained DOF, and the velocity is what
    carries the support motion into stiffness-proportional (Rayleigh betaKinit)
    damping forces of ``-doRayleigh`` elements. Leaving it to OpenSees's
    internal differentiation of the disp series is not reliable.
    """

    type: Literal["ImposedSupportMotion"] = "ImposedSupportMotion"
    direction: int = Field(..., ge=1, le=6, description="DOF direction (1..6).")
    disp_series_id: PositiveInt
    node_ids: list[int] = Field(
        ...,
        min_length=1,
        description="Support nodes driven by the motion (each restrained in `direction`).",
    )
    factor: float = 1.0


LoadPattern = Annotated[
    PlainLoadPattern | UniformExcitationPattern | ImposedSupportMotionPattern,
    Field(discriminator="type"),
]
