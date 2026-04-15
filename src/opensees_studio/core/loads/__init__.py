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


# ──────────────────────────── Patterns ────────────────────────────
class PlainLoadPattern(Entity):
    """``pattern Plain`` — links a time series to a set of nodal loads."""

    type: Literal["Plain"] = "Plain"
    time_series_id: PositiveInt
    nodal_loads: list[NodalLoad] = Field(default_factory=list)


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
