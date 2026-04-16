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
        default=(0.5, 0.25), description="Newmark gamma, beta (default = average acceleration).",
    )
    algorithm: str = "Newton"
    test: str = "NormDispIncr"
    tolerance: float = Field(default=1e-6, gt=0.0)
    max_iter: PositiveInt = 25
    # Rayleigh damping coefficients: C = αM·M + βK·K.
    # αM damps lower frequencies, βK damps higher. Typical values:
    # pick two target frequencies (e.g. 1st mode and 3rd mode) and 5%
    # damping, then solve the 2x2 for α and β.
    rayleigh_alpha_m: float = Field(
        default=0.0,
        description="Mass-proportional Rayleigh coefficient αM (damps low frequencies).",
    )
    rayleigh_beta_k: float = Field(
        default=0.0,
        description="Stiffness-proportional Rayleigh coefficient βK (damps high frequencies).",
    )


class PushoverCase(Entity):
    """Displacement-controlled monotonic pushover analysis.

    Applies the reference load pattern(s), then incrementally drives
    a single control DOF from 0 to ``target_disp`` in steps of
    ``step_size``. OpenSees reports base shear implicitly via reaction
    forces at restrained nodes — we aggregate them over the user's
    ``base_nodes`` list to build the pushover curve.
    """

    type: Literal["Pushover"] = "Pushover"
    pattern_ids: list[PositiveInt] = Field(..., min_length=1)
    control_node: PositiveInt = Field(..., description="Node whose displacement is driven.")
    control_dof: int = Field(..., ge=1, le=6, description="DOF direction (1..6) to push.")
    target_disp: float = Field(..., description="Final displacement target (signed).")
    step_size: PositiveFloat = Field(
        default=0.001,
        description="Incremental displacement per step. Smaller = more stable.",
    )
    base_nodes: list[PositiveInt] = Field(
        default_factory=list,
        description="Nodes whose reactions sum into the 'base shear' for the curve. "
                    "Leave empty to use every restrained node in the project.",
    )
    system: str = "BandGeneral"
    constraints: str = "Plain"
    algorithm: str = "Newton"
    test: str = "NormDispIncr"
    tolerance: float = Field(default=1e-6, gt=0.0)
    max_iter: PositiveInt = 25


AnalysisCase = Annotated[
    Union[StaticCase, ModalCase, TransientCase, PushoverCase],
    Field(discriminator="type"),
]
