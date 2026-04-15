"""Analysis case definitions.

These are *declarative* descriptions of analyses to run; the actual
solver invocation is in ``services.opensees_runner``. Phase 1 covers
the most common cases needed for verification (static, modal,
transient). More cases (cyclic pushover, IDA, response spectrum) come
in Phase 6/8.
"""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import Field, PositiveFloat, PositiveInt

from opensees_studio.core._base import Entity


class StaticCase(Entity):
    """Linear or nonlinear static analysis (single load step or pushover)."""

    type: Literal["Static"] = "Static"
    pattern_ids: list[PositiveInt] = Field(..., min_length=1)
    n_steps: PositiveInt = 1
    load_factor_increment: float = 1.0
    system: str = "BandGeneral"
    constraints: str = "Plain"
    integrator: str = "LoadControl"
    algorithm: str = "Linear"
    test: str = "NormDispIncr"
    tolerance: float = Field(default=1e-8, gt=0.0)
    max_iter: PositiveInt = 25


class ModalCase(Entity):
    """Eigenvalue analysis."""

    type: Literal["Modal"] = "Modal"
    n_modes: PositiveInt = 3
    solver: Literal["genBandArpack", "fullGenLapack", "symmBandLapack"] = "genBandArpack"


class TransientCase(Entity):
    """Direct-integration time-history analysis."""

    type: Literal["Transient"] = "Transient"
    pattern_ids: list[PositiveInt] = Field(..., min_length=1)
    dt: PositiveFloat
    n_steps: PositiveInt
    system: str = "BandGeneral"
    constraints: str = "Plain"
    integrator: str = "Newmark"
    integrator_params: tuple[float, float] = Field(
        default=(0.5, 0.25), description="Newmark gamma, beta (default = average acceleration)."
    )
    algorithm: str = "Newton"
    test: str = "NormDispIncr"
    tolerance: float = Field(default=1e-6, gt=0.0)
    max_iter: PositiveInt = 25


AnalysisCase = Annotated[
    Union[StaticCase, ModalCase, TransientCase],
    Field(discriminator="type"),
]
