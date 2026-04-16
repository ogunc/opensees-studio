"""Loads, time series, and load patterns.

OpenSees load model:
- ``timeSeries``: scalar function of time (Linear, Constant, Path, …)
- ``pattern``: applies a time series to a collection of loads
- ``load``: nodal force vector
- ``eleLoad``: distributed element load

Hierarchy here mirrors that. Patterns own their child loads — when a
pattern is deleted, its loads go with it.
"""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, PositiveInt

from opensees_studio.core._base import Entity


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
    values: list[float] = Field(..., min_length=1)
    file_path: str | None = Field(
        default=None,
        description="Optional source file (informational; values are still embedded in the project).",
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
        ..., min_length=2,
        description="Periods (s), strictly increasing.",
    )
    accelerations: list[float] = Field(
        ..., min_length=2,
        description="Spectral pseudo-accelerations (length must match `periods`).",
    )
    damping_ratio: float = Field(
        default=0.05, ge=0.0, le=1.0,
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


TimeSeries = Annotated[
    Union[LinearTimeSeries, ConstantTimeSeries, PathTimeSeries],
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


# ──────────────────────────── Patterns ────────────────────────────
class PlainLoadPattern(Entity):
    """``pattern Plain`` — links a time series to a set of nodal and element loads."""

    type: Literal["Plain"] = "Plain"
    time_series_id: PositiveInt
    nodal_loads: list[NodalLoad] = Field(default_factory=list)
    element_loads: list[UniformElementLoad] = Field(default_factory=list)


class UniformExcitationPattern(Entity):
    """``pattern UniformExcitation`` — base ground motion in a single direction."""

    type: Literal["UniformExcitation"] = "UniformExcitation"
    direction: int = Field(..., ge=1, le=6, description="DOF direction (1..6).")
    accel_series_id: PositiveInt
    vel_series_id: PositiveInt | None = None
    disp_series_id: PositiveInt | None = None
    factor: float = 1.0


LoadPattern = Annotated[
    Union[PlainLoadPattern, UniformExcitationPattern],
    Field(discriminator="type"),
]
