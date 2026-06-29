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
    """Direct-integration time-history analysis.

    Supports chained analysis via ``preload_case_ids``: a list of
    StaticCase IDs to run first (applying their patterns in order), after
    which ``ops.loadConst -time 0.0`` locks the load and resets pseudo-
    time. Patterns in ``remove_patterns`` are then dropped via
    ``ops.remove loadPattern`` so the transient runs as a *free-vibration*
    (or reduced-pattern) continuation of the preloaded state.

    If ``rayleigh_mode1_damping`` is set, the runner computes a stiffness-
    proportional Rayleigh coefficient βK = 2ζ/√λ₁ from the first eigen-
    value of the current (possibly preloaded) structure. This matches
    the Tcl idiom ``rayleigh 0 0 0 [expr 2*ζ/sqrt([eigen 1])]``.
    """

    type: Literal["Transient"] = "Transient"
    pattern_ids: list[PositiveInt] = Field(default_factory=list)
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
        description="Stiffness-proportional βK on CURRENT/tangent stiffness — "
                    "``rayleigh`` slot 2 (damps high frequencies).",
    )
    rayleigh_beta_k_init: float = Field(
        default=0.0,
        description=(
            "Stiffness-proportional βK on INITIAL stiffness — ``rayleigh`` slot 3 "
            "(``rayleigh 0 0 βKinit 0`` Kinit-proportional damping: βK·K_init held "
            "constant). For ζ at a chosen mode i set βKinit = 2·ζ/ωᵢ. The four "
            "coefficients are emitted in a SINGLE ``rayleigh`` call (a second call "
            "would silently replace the first)."
        ),
    )
    rayleigh_beta_k_comm: float = Field(
        default=0.0,
        description="Stiffness-proportional βK on COMMITTED stiffness — "
                    "``rayleigh`` slot 4.",
    )
    rayleigh_mode1_damping: float | None = Field(
        default=None, ge=0.0,
        description=(
            "If set, βK is computed as 2·ζ/√λ₁ (first-mode eigenvalue) and "
            "overrides ``rayleigh_beta_k``. ``rayleigh_alpha_m`` still applies."
        ),
    )
    # Chained analysis — preload + pattern removal before the transient.
    preload_case_ids: list[PositiveInt] = Field(
        default_factory=list,
        description=(
            "StaticCase IDs to run first. Each runs its ``pattern_ids`` "
            "through ``LoadControl`` steps, then ``loadConst -time 0.0`` "
            "locks the applied load and resets pseudo-time to zero."
        ),
    )
    remove_patterns: list[PositiveInt] = Field(
        default_factory=list,
        description=(
            "Pattern IDs to drop (``ops.remove loadPattern``) after the "
            "preload phase and before the transient loop — use this for "
            "Tcl-style free-vibration analyses."
        ),
    )


class PushoverCase(Entity):
    """Displacement-controlled monotonic pushover analysis.

    Applies the reference load pattern(s), then incrementally drives
    a single control DOF from 0 to ``target_disp`` in steps of
    ``step_size``. OpenSees reports base shear implicitly via reaction
    forces at restrained nodes — we aggregate them over the user's
    ``base_nodes`` list to build the pushover curve.

    Gravity preload options:
        - **Recommended**: set ``preload_case_ids`` to a list of
          ``StaticCase`` IDs. Each preload case runs its ``pattern_ids``
          through the configured ``LoadControl`` loop (ramped over
          ``n_steps``) before the pushover starts, then
          ``ops.loadConst -time 0.0`` locks the preload. This matches
          the Tcl ``analyze 10; loadConst`` recipe from the RC Portal
          Pushover example.
        - **Legacy fallback**: if ``preload_case_ids`` is empty, the
          runner splits ``pattern_ids`` by TimeSeries type — patterns
          driven by a ``ConstantTimeSeries`` are applied in a single
          ``LoadControl(0)`` step before the pushover; Linear patterns
          are treated as the DisplacementControl reference load. Kept
          for backward compatibility with older ``.osmodel`` files.
    """

    type: Literal["Pushover"] = "Pushover"
    pattern_ids: list[PositiveInt] = Field(default_factory=list)
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
    preload_case_ids: list[PositiveInt] = Field(
        default_factory=list,
        description=(
            "StaticCase IDs to run first (in order) as the gravity / "
            "axial preload. After all preloads complete, "
            "``loadConst -time 0.0`` locks the applied load and resets "
            "pseudo-time so the pushover's DisplacementControl starts "
            "from a clean t=0."
        ),
    )


class ResponseSpectrumCase(Entity):
    """Modal response-spectrum analysis with SRSS or CQC combination.

    Operates on a previously-computed :class:`ModalCase` result —
    we re-run that modal eigenvalue analysis under the hood so the
    spectrum case is self-contained from the user's perspective.

    For each mode i:
    1. Read frequency f_i, modal mass participation factor Γ_i, and
       mode shape φ_i from the modal results.
    2. Look up Sa(T_i) from the spectrum (linear interpolation in
       period; clamped at table ends).
    3. Compute the modal peak response u_i = Γ_i · φ_i · Sa(T_i) / ω_i².
    4. Combine across modes using SRSS or CQC.
    """

    type: Literal["ResponseSpectrum"] = "ResponseSpectrum"
    modal_case_id: PositiveInt = Field(
        ..., description="ID of the ModalCase whose mode shapes drive this analysis.",
    )
    spectrum_id: PositiveInt = Field(
        ..., description="ID of the ResponseSpectrum to apply.",
    )
    direction: int = Field(
        ..., ge=1, le=6, description="DOF direction (1..6) for the seismic excitation.",
    )
    combination: Literal["SRSS", "CQC"] = "SRSS"
    damping_ratio: float | None = Field(
        default=None, ge=0.0, le=1.0,
        description="Override the spectrum's damping for CQC correlation. "
                    "Defaults to the spectrum's damping_ratio.",
    )


AnalysisCase = Annotated[
    Union[StaticCase, ModalCase, TransientCase, PushoverCase, ResponseSpectrumCase],
    Field(discriminator="type"),
]
