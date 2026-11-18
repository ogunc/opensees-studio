"""Analysis case definitions.

These are *declarative* descriptions of analyses to run; the actual
solver invocation is in ``services.opensees_runner``. Phase 1 covers
the most common cases needed for verification (static, modal,
transient). More cases (cyclic pushover, IDA, response spectrum) come
in Phase 6/8.
"""

from __future__ import annotations

import warnings
from typing import Annotated, Literal, get_args

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PositiveFloat,
    PositiveInt,
    field_validator,
    model_validator,
)

from opensees_studio.core._base import Entity, omit_when_default
from opensees_studio.core.modal import KNOWN_SOLVERS, OFFERED_SOLVERS, SOLVER_AUTO

Numberer = Literal["Plain", "RCM", "AMD"]
"""DOF numberers offered: each gives its own equation numbering in OpenSeesPy 3.8.0, and an
unknown name is an error there, not a silent default."""

NUMBERERS: tuple[str, ...] = get_args(Numberer)

SYSTEMS: tuple[str, ...] = (
    "BandGeneral",
    "BandSPD",
    "ProfileSPD",
    "SparseGeneral",
    "UmfPack",
    "FullGeneral",
    "SparseSYM",
)
"""Linear solvers offered; each runs in OpenSeesPy 3.8.0 and gives its own result bits.

``system`` stays a free string so files naming another solver still load; the runner passes
it to OpenSees, which refuses an unknown name.
"""

SYSTEM_ARGS: dict[str, tuple[str, ...]] = {}
"""Arguments a system accepts here, per system: none at present.

``SparseGeneral -piv`` is not offered: this build ignores the flag and always applies SuperLU
partial pivoting (``DiagPivotThresh`` is fixed at 1.0), so the flag changes no result bit.
"""

SYSTEM_NOTES: dict[str, str] = {"SparseGeneral": "partial pivoting is always on in this build"}
"""Short notes shown with a system in the case forms."""

_RETIRED_SYSTEM_ARGS: dict[str, tuple[str, ...]] = {"SparseGeneral": ("-piv",)}
"""Arguments earlier files may carry that load with a notice and are dropped."""


TESTS: tuple[str, ...] = (
    "NormDispIncr",
    "NormUnbalance",
    "EnergyIncr",
    "RelativeNormDispIncr",
    "RelativeNormUnbalance",
    "RelativeEnergyIncr",
    "RelativeTotalNormDispIncr",
    "NormDispAndUnbalance",
    "NormDispOrUnbalance",
    "FixedNumIter",
)
"""Convergence tests offered; every one runs in OpenSeesPy 3.8.0."""

ALGORITHMS: tuple[str, ...] = (
    "Linear",
    "Newton",
    "NewtonLineSearch",
    "ModifiedNewton",
    "KrylovNewton",
    "SecantNewton",
    "RaphsonNewton",
    "PeriodicNewton",
    "BFGS",
    "Broyden",
)
"""Solution algorithms offered; every one runs in OpenSeesPy 3.8.0."""

STATIC_INTEGRATORS: tuple[str, ...] = (
    "LoadControl",
    "DisplacementControl",
    "ArcLength",
    "MinUnbalDispNorm",
)
TRANSIENT_INTEGRATORS: tuple[str, ...] = (
    "Newmark",
    "HHT",
    "GeneralizedAlpha",
    "CentralDifference",
    "TRBDF2",
)

TRANSIENT_PARAMS: dict[str, tuple[tuple[str, float], ...]] = {
    "Newmark": (("γ", 0.5), ("β", 0.25)),
    "HHT": (("α", 0.5), ("γ (unused)", 0.25)),
    "GeneralizedAlpha": (("αM", 1.0), ("αF", 0.8)),
    "CentralDifference": (),
    "TRBDF2": (),
}
"""The ``integrator_params`` each transient integrator reads, with defaults (labels for the form)."""


def test_args(test: str, tolerance: float, max_iter: int) -> tuple[float | int, ...]:
    """The arguments of ``ops.test(test, ...)``: tolerances and iterations as the test reads them."""
    if test == "FixedNumIter":
        return (max_iter,)
    if test in ("NormDispAndUnbalance", "NormDispOrUnbalance"):
        return (tolerance, tolerance, max_iter)
    return (tolerance, max_iter)


def transient_integrator_args(case: TransientCase) -> tuple[float, ...]:
    """The arguments of ``ops.integrator`` for a transient case.

    Newmark and HHT keep what earlier builds sent (both ``integrator_params``);
    GeneralizedAlpha takes αM, αF; CentralDifference and TRBDF2 take none.
    """
    if case.integrator in ("CentralDifference", "TRBDF2"):
        return ()
    return tuple(case.integrator_params)


class _SolverOptions(Entity):
    """``numberer`` and ``system`` arguments shared by the stepped analysis cases.

    Both are left out of the file at their defaults (RCM, no arguments), so projects that do
    not use them save exactly as before.
    """

    numberer: Numberer = "RCM"
    system_args: tuple[str, ...] = ()
    algorithm_args: tuple[str, ...] = ()

    serialize_without_defaults = omit_when_default("numberer", "system_args", "algorithm_args")

    @model_validator(mode="before")
    @classmethod
    def _drop_retired_system_args(cls, data: object) -> object:
        if not isinstance(data, dict) or not data.get("system_args"):
            return data
        system = data.get("system", "")
        retired = _RETIRED_SYSTEM_ARGS.get(system, ())
        dropped = [a for a in data["system_args"] if a in retired]
        if not dropped:
            return data
        warnings.warn(
            f"Analysis case {data.get('id')}: system {system} {' '.join(dropped)} is not "
            f"offered ({SYSTEM_NOTES.get(system, 'no effect in this build')}); "
            f"running without {' '.join(dropped)}.",
            UserWarning,
            stacklevel=2,
        )
        kept = tuple(a for a in data["system_args"] if a not in retired)
        return {**data, "system_args": kept}

    @model_validator(mode="after")
    def _known_algorithm_args(self) -> _SolverOptions:
        allowed = (
            ((), ("-initial",))
            if getattr(self, "algorithm", "") in ("Newton", "ModifiedNewton")
            else ((),)
        )
        if self.algorithm_args not in allowed:
            raise ValueError("Only Newton and ModifiedNewton offer -initial in this build.")
        return self

    @model_validator(mode="after")
    def _known_system_args(self) -> _SolverOptions:
        system = getattr(self, "system", "")
        allowed = SYSTEM_ARGS.get(system, ())
        unknown = [a for a in self.system_args if a not in allowed]
        if unknown:
            accepted = ", ".join(allowed) if allowed else "none"
            raise ValueError(
                f"system {system} does not take {', '.join(unknown)} (accepted: {accepted})."
            )
        return self


NotionalDirection = Literal["+X", "-X", "+Y", "-Y"]
"""Global direction a case's notional loads act in."""

NOTIONAL_DIRECTIONS: tuple[str, ...] = get_args(NotionalDirection)


class DirectAnalysisTag(BaseModel):
    """Marks a static case made by Design → Direct Analysis Method, and what it stands for."""

    model_config = ConfigDict(extra="forbid")
    serialize_without_defaults = omit_when_default("order", "lateral", "overstrength")

    combination: str = Field(..., description="The load combination, e.g. '1.2D+1.6L'.")
    order: Literal["second", "first"] = Field(
        default="second",
        description=(
            "'second': the strength case (P-Delta, reduced stiffness). 'first': its "
            "first-order twin, only for the drift ratio Δ2/Δ1 (C2.2b(d))."
        ),
    )
    lateral: bool = Field(default=False, description="The combination has wind or earthquake.")
    overstrength: bool = Field(
        default=False, description="An ASCE 7 overstrength (Ω0) combination."
    )


class StaticCase(_SolverOptions):
    """Linear or nonlinear static analysis (single load step or pushover).

    ``pattern_factors`` scales each pattern, so one case can carry a whole factored
    load combination (``1.2D + 1.6L``) and be solved as one nonlinear analysis,
    which a combination of separate results cannot be. ``p_delta`` runs every
    frame with a Linear transformation as P-Delta, ``stiffness_factor`` scales the
    elastic stiffness of frames and trusses (0.8 in the AISC 360 direct analysis
    method), and ``notional_ratio`` adds a lateral load of that fraction of each
    storey's factored gravity load in this case (``Ni = ratio Yi``). All of it
    happens when the case runs; the model itself is never changed.
    """

    type: Literal["Static"] = "Static"
    pattern_ids: list[PositiveInt] = Field(..., min_length=1)
    pattern_factors: list[float] = Field(
        default_factory=list,
        description="Factor of each pattern of pattern_ids, in order; empty = every one 1.0.",
    )
    n_steps: PositiveInt = 1
    load_factor_increment: float = 1.0
    system: str = "BandGeneral"
    constraints: str = "Plain"
    integrator: str = "LoadControl"
    algorithm: str = "Linear"
    test: str = "NormDispIncr"
    tolerance: float = Field(default=1e-8, gt=0.0)
    max_iter: PositiveInt = 25
    preload_case_ids: list[PositiveInt] = Field(
        default_factory=list,
        description=(
            "StaticCase IDs run first, in order, as the gravity or axial preload. "
            "Each applies its patterns and then locks the load with loadConst -time 0.0."
        ),
    )
    p_delta: bool = Field(
        default=False,
        description="Run every frame with a Linear transformation as PDelta in this case.",
    )
    stiffness_factor: float = Field(
        default=1.0,
        gt=0.0,
        le=1.0,
        description=(
            "Factor on the elastic stiffness (E, G) of frame sections and elastic truss "
            "materials in this case; 0.8 for the AISC 360 C2.3 reduction."
        ),
    )
    notional_ratio: float = Field(
        default=0.0,
        ge=0.0,
        lt=0.1,
        description=(
            "Notional load Ni = ratio x Yi at every storey, Yi being the storey's "
            "factored gravity load in this case (AISC 360 C2-1: 0.002 alpha)."
        ),
    )
    notional_direction: NotionalDirection = "+X"
    direct_analysis: DirectAnalysisTag | None = None

    serialize_without_defaults = omit_when_default(
        "numberer",
        "system_args",
        "algorithm_args",
        "preload_case_ids",
        "pattern_factors",
        "p_delta",
        "stiffness_factor",
        "notional_ratio",
        "notional_direction",
        "direct_analysis",
    )

    @model_validator(mode="after")
    def _one_factor_per_pattern(self) -> StaticCase:
        if self.pattern_factors and len(self.pattern_factors) != len(self.pattern_ids):
            raise ValueError(
                f"Static case {self.id}: {len(self.pattern_factors)} pattern factors for "
                f"{len(self.pattern_ids)} patterns; give one per pattern or none."
            )
        return self

    def factor_of(self, index: int) -> float:
        """The factor of the ``index``-th pattern of ``pattern_ids``."""
        return float(self.pattern_factors[index]) if self.pattern_factors else 1.0


class ModalCase(Entity):
    """Eigenvalue analysis.

    ``solver`` is ``auto`` (the default: dense ``fullGenLapack`` at or below
    ``core.modal.DENSE_EIGEN_MAX_FREE_DOF`` free DOF, ``genBandArpack`` above
    it), or one of the two solvers this build really runs. ``symmBandLapack``
    loads but is refused at run time (lumped mass leaves DOF massless). Any
    other stored name loads with a warning and runs with the default routing.
    """

    type: Literal["Modal"] = "Modal"
    n_modes: PositiveInt = 3
    solver: str = SOLVER_AUTO

    @field_validator("solver", mode="before")
    @classmethod
    def _known_solver(cls, value: object) -> str:
        name = str(value).strip() if value is not None else SOLVER_AUTO
        if name in KNOWN_SOLVERS:
            return name
        warnings.warn(
            f"ModalCase solver {name!r} is not offered by this build (choose one of "
            f"{', '.join(OFFERED_SOLVERS)}); running with the default routing ({SOLVER_AUTO}).",
            UserWarning,
            stacklevel=2,
        )
        return SOLVER_AUTO


class TransientCase(_SolverOptions):
    """Direct-integration time-history analysis.

    Supports chained analysis via ``preload_case_ids``: a list of
    StaticCase IDs to run first (applying their patterns in order), after
    which ``ops.loadConst -time 0.0`` locks the load and resets pseudo-
    time. Patterns in ``remove_patterns`` are then dropped via
    ``ops.remove loadPattern`` so the transient runs as a *free-vibration*
    (or reduced-pattern) continuation of the preloaded state.

    If ``rayleigh_mode1_damping`` is set, the runner computes a stiffness-
    proportional Rayleigh coefficient βK = 2ζ/√λ₁ from the first eigen-
    value of the current (possibly preloaded) structure and applies it to
    the committed stiffness, the Tcl idiom
    ``rayleigh 0 0 0 [expr 2*ζ/sqrt([eigen 1])]``.
    """

    type: Literal["Transient"] = "Transient"
    pattern_ids: list[PositiveInt] = Field(default_factory=list)
    dt: PositiveFloat
    n_steps: PositiveInt
    system: str = "BandGeneral"
    constraints: str = "Plain"
    integrator: str = "Newmark"
    integrator_params: tuple[float, float] = Field(
        default=(0.5, 0.25),
        description="Newmark gamma, beta (default = average acceleration).",
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
        description="Stiffness-proportional βK on COMMITTED stiffness — ``rayleigh`` slot 4.",
    )
    rayleigh_mode1_damping: float | None = Field(
        default=None,
        ge=0.0,
        description=(
            "If set, βK is computed as 2·ζ/√λ₁ (first-mode eigenvalue) and applied "
            "to the COMMITTED stiffness (``rayleigh`` slot 4), replacing the three "
            "βK fields. ``rayleigh_alpha_m`` still applies."
        ),
    )
    # Modal damping — OpenSees ``modalDamping`` over the first N modes. Additive:
    # a case without it saves byte-identical to before (both fields omitted).
    serialize_without_defaults = omit_when_default(
        "numberer", "system_args", "algorithm_args", "modal_damping", "modal_damping_modes"
    )
    modal_damping: float | None = Field(
        default=None,
        ge=0.0,
        lt=1.0,
        description=(
            "Damping ratio ζ of each of the first ``modal_damping_modes`` modes "
            "(``eigen N`` then ``modalDamping ζ``), on top of any Rayleigh damping. "
            "None = no modal damping."
        ),
    )
    modal_damping_modes: PositiveInt = Field(
        default=10,
        description="Number of modes the modal damping is applied to (capped at the free DOF).",
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


class PushoverCase(_SolverOptions):
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
        ...,
        description="ID of the ModalCase whose mode shapes drive this analysis.",
    )
    spectrum_id: PositiveInt = Field(
        ...,
        description="ID of the ResponseSpectrum to apply.",
    )
    direction: int = Field(
        ...,
        ge=1,
        le=6,
        description="DOF direction (1..6) for the seismic excitation.",
    )
    combination: Literal["SRSS", "CQC"] = Field(
        default="CQC",
        description=(
            "Modal combination rule. CQC is the default for new cases: its result does "
            "not depend on the arbitrary basis an eigen solver returns inside a repeated "
            "or near-repeated mode pair, SRSS does. Saved cases keep their stored rule."
        ),
    )
    damping_ratio: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description=(
            "Modal damping for the CQC correlation. None (also stored for 0 or an empty "
            "value) means the spectrum's own damping_ratio. A CQC run never uses zero "
            "damping: if that would be the outcome, 0.05 is used and a warning is issued."
        ),
    )
    closely_spaced_ratio: float = Field(
        default=0.9,
        gt=0.0,
        le=1.0,
        description=(
            "SRSS only: two included modes whose frequency ratio (lower over higher) is at "
            "least this count as closely spaced and produce a warning."
        ),
    )

    @field_validator("damping_ratio", mode="before")
    @classmethod
    def _zero_damping_means_spectrum(cls, value: object) -> object:
        if value is None or value == "" or value == 0:
            return None
        return value


class Axle(BaseModel):
    """One axle of a moving load: its force and its distance behind the front axle."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    load: float = Field(..., description="Axle force, along the case's load direction.")
    offset: float = Field(
        default=0.0, ge=0.0, description="Distance behind the front axle along the path."
    )


class InfluenceLineCase(Entity):
    """A unit load walked along a chain of frame members, one linear static solve per stop.

    ``path`` lists the members in the order the load travels; consecutive
    members must share a joint, and each is walked from the joint it shares
    with the previous one. The load stops at ``stations`` equal intervals of
    every member (joints included once), acting along the global
    ``direction`` with the value ``load`` (-1 = a unit load downward along Z).

    The result holds every response (displacements, reactions, member end
    forces) at every stop: an influence line per quantity. ``axles`` describe
    a vehicle whose extreme effects :mod:`core.influence` finds from them.
    Linear elastic analysis only: the solve uses the Linear algorithm.
    """

    type: Literal["InfluenceLine"] = "InfluenceLine"
    path: list[PositiveInt] = Field(..., min_length=1)
    stations: PositiveInt = Field(default=10, le=200)
    direction: Literal["X", "Y", "Z"] = "Z"
    load: float = Field(default=-1.0, description="Value of the moving load along direction.")
    axles: list[Axle] = Field(default_factory=list)

    serialize_without_defaults = omit_when_default("axles")

    @field_validator("load")
    @classmethod
    def _nonzero(cls, value: float) -> float:
        if value == 0.0:
            raise ValueError("The moving load cannot be zero.")
        return value


class ConstructionStage(BaseModel):
    """One stage of a :class:`StagedCase`: what is built or taken away, then loaded.

    Elements (and their joints) of ``add_group_ids`` are activated at the start
    of the stage, stress-free in the current deformed shape; elements of
    ``remove_group_ids`` are taken out (shoring, formwork), and the forces they
    carried go back into the structure. Then ``pattern_ids`` are applied in
    ``n_steps`` load steps and locked, so the next stage starts from this state.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = ""
    add_group_ids: list[PositiveInt] = Field(default_factory=list)
    remove_group_ids: list[PositiveInt] = Field(default_factory=list)
    pattern_ids: list[PositiveInt] = Field(default_factory=list)
    n_steps: PositiveInt = 1
    duration: float = Field(
        default=0.0,
        ge=0.0,
        description="Days the stage's state is held after its loads (time-dependent case).",
    )
    time_steps: PositiveInt = Field(
        default=20, description="Time steps over the duration, geometrically spaced."
    )


class StagedCase(_SolverOptions):
    """Staged construction: the structure grows (and loses its shoring) stage by stage.

    Elements in a group that some stage adds do not exist before that stage;
    every other element is there from the start. Each stage starts from the
    deformed, stressed state of the previous one: new elements appear
    stress-free, removed elements give their forces back, and the stage's load
    patterns are applied and locked (``loadConst``). The result is a static
    result with one step per stage: the state at the end of each.

    ``new_joints`` says where a joint that appears with a stage is built:
    ``"design"`` (the default) at its drawn position, as a floor is built level
    whatever the storeys below have shortened, so its displacement is the
    movement since it was built; ``"follow"`` by the rigid continuation of the
    joint it is built from, so the structure keeps the deformed shape of the
    stages before. Either way its elements are stress-free when they appear.
    """

    type: Literal["Staged"] = "Staged"
    stages: list[ConstructionStage] = Field(..., min_length=1)
    new_joints: Literal["design", "follow"] = "design"
    time_dependent: bool = False
    """Creep and shrinkage: time is the concrete age in days, each stage's loads
    act at once and are then held for its ``duration`` (``TDConcreteMC10``)."""
    start_time: float = Field(default=28.0, ge=0.0, description="Time of the first stage, days.")
    system: str = "BandGeneral"
    constraints: str = "Plain"
    integrator: str = "LoadControl"
    algorithm: str = "Linear"
    test: str = "NormDispIncr"
    tolerance: float = Field(default=1e-8, gt=0.0)
    max_iter: PositiveInt = 25

    serialize_without_defaults = omit_when_default(
        "numberer", "system_args", "algorithm_args", "new_joints", "time_dependent", "start_time"
    )

    @property
    def pattern_ids(self) -> list[int]:
        """Every pattern some stage applies, in stage order."""
        out: list[int] = []
        for stage in self.stages:
            out.extend(p for p in stage.pattern_ids if p not in out)
        return out


AnalysisCase = Annotated[
    StagedCase
    | StaticCase
    | ModalCase
    | TransientCase
    | PushoverCase
    | ResponseSpectrumCase
    | InfluenceLineCase,
    Field(discriminator="type"),
]
