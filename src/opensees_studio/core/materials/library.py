"""Uniaxial materials written as their OpenSees signature (Material Library → Add).

Each class lists its fields **in the order OpenSees reads them**, so one emitter
(:meth:`SignatureMaterial.opensees_args`) and one generic form serve every one
of them; a class only overrides ``opensees_args`` when OpenSees wants flags or
lists. The signatures are those of the OpenSeesPy documentation and every class
is checked against the live solver in ``tests/integration/test_material_library_run.py``.

Wrappers (Parallel, Series, MinMax, InitStrain, InitStress, Fatigue) name other
materials in fields ending in ``material_id`` / ``material_ids``; the runner
emits a wrapper after the materials it wraps and ``Project.validate_references``
reports a missing one.

No Qt, no OpenSees.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar, Literal

from pydantic import Field, PositiveFloat, PositiveInt, model_validator

from opensees_studio.core._base import Entity

_SKIP = ("id", "name", "type")


class SignatureMaterial(Entity):
    """A uniaxial material whose fields are its OpenSees arguments, in order."""

    #: The OpenSees command that defines it.
    command: ClassVar[str] = "uniaxialMaterial"

    if TYPE_CHECKING:
        type: str  # each subclass's Literal discriminator

    def opensees_args(self) -> list[Any]:
        """Arguments after ``uniaxialMaterial(type, tag, ...)``."""
        return [getattr(self, name) for name in type(self).model_fields if name not in _SKIP]

    def referenced_material_ids(self) -> list[int]:
        """Materials this one wraps (empty for a plain material)."""
        out: list[int] = []
        for name in type(self).model_fields:
            value = getattr(self, name)
            if name.endswith("material_id") and isinstance(value, int):
                out.append(value)
            elif name.endswith("material_ids"):
                out.extend(value)
        return out


# ─────────────────────────── steel ───────────────────────────
class ReinforcingSteel(SignatureMaterial):
    """Chang-Mander reinforcing steel (no buckling or fatigue options)."""

    type: Literal["ReinforcingSteel"] = "ReinforcingSteel"
    fy: PositiveFloat = Field(420e6, description="Yield stress in tension")
    fu: PositiveFloat = Field(620e6, description="Ultimate stress in tension")
    Es: PositiveFloat = Field(200e9, description="Initial elastic tangent")
    Esh: PositiveFloat = Field(5e9, description="Tangent at the start of strain hardening")
    eps_sh: PositiveFloat = Field(0.01, description="Strain at the start of strain hardening")
    eps_ult: PositiveFloat = Field(0.1, description="Strain at peak stress")


# ─────────────────────────── concrete ───────────────────────────
class Concrete06(SignatureMaterial):
    """Thorenfeldt-base concrete with tension stiffening."""

    type: Literal["Concrete06"] = "Concrete06"
    fc: float = Field(-30e6, lt=0, description="Compressive strength (negative)")
    e0: float = Field(-0.002, lt=0, description="Strain at compressive strength (negative)")
    n: PositiveFloat = Field(2.0, description="Compressive shape factor")
    k: PositiveFloat = Field(1.0, description="Post-peak compressive shape factor")
    alpha1: float = Field(0.32, ge=0, description="Plastic strain ratio in compression")
    fcr: PositiveFloat = Field(2.5e6, description="Tensile strength")
    ecr: PositiveFloat = Field(0.00008, description="Strain at tensile strength")
    b: PositiveFloat = Field(4.0, description="Tension-stiffening exponent")
    alpha2: float = Field(0.08, ge=0, description="Plastic strain ratio in tension")


class Concrete07(SignatureMaterial):
    """Chang-Mander concrete."""

    type: Literal["Concrete07"] = "Concrete07"
    fc: float = Field(-30e6, lt=0, description="Compressive strength (negative)")
    epsc: float = Field(-0.002, lt=0, description="Strain at compressive strength (negative)")
    Ec: PositiveFloat = Field(27e9, description="Initial elastic modulus")
    ft: PositiveFloat = Field(2.5e6, description="Tensile strength")
    et: PositiveFloat = Field(0.0001, description="Strain at tensile strength")
    xp: PositiveFloat = Field(2.0, description="Non-dimensional critical strain in tension")
    xn: PositiveFloat = Field(2.3, description="Non-dimensional critical strain in compression")
    r: PositiveFloat = Field(7.0, description="Shape parameter")


class ConcreteCM(SignatureMaterial):
    """Chang and Mander (1994) cyclic concrete, with Tsai's envelope in compression and tension.

    The compression envelope is ``y = n x / (1 + (n - r / (r - 1)) x + x^r / (r - 1))``
    with ``x = strain / epcc``, ``y = stress / fpcc`` and ``n = Ec epcc / fpcc``;
    with ``rc = Ec / (Ec - fpcc / epcc)`` it is Mander's confined curve. ``xcrn``
    and ``xcrp`` are where the envelopes turn into straight lines (the crushing
    and cracking strains over the peak ones). Unlike Concrete07 it models gradual
    crack closure, and ``-GapClose 1`` closes cracks more gradually.
    """

    type: Literal["ConcreteCM"] = "ConcreteCM"
    fpcc: float = Field(-30e6, lt=0, description="Compressive strength (negative)")
    epcc: float = Field(-0.002, lt=0, description="Strain at compressive strength (negative)")
    Ec: PositiveFloat = Field(30e9, description="Initial tangent modulus")
    rc: float = Field(7.0, gt=1, description="Shape parameter of the compression envelope")
    xcrn: float = Field(1.035, gt=1, description="Critical strain over epcc, compression")
    ft: PositiveFloat = Field(2e6, description="Tensile strength")
    et: PositiveFloat = Field(0.00008, description="Strain at tensile strength")
    rt: float = Field(1.2, gt=1, description="Shape parameter of the tension envelope")
    xcrp: float = Field(10000.0, gt=1, description="Critical strain over et, tension")
    gap_close: Literal[0, 1] = Field(
        default=0, description="-GapClose: 0 less gradual crack closure, 1 more gradual"
    )

    def opensees_args(self) -> list[Any]:
        args: list[Any] = [
            self.fpcc,
            self.epcc,
            self.Ec,
            self.rc,
            self.xcrn,
            self.ft,
            self.et,
            self.rt,
            self.xcrp,
        ]
        return [*args, "-GapClose", 1] if self.gap_close else args


# ─────────────────────── deterioration (IMK, Pinching4) ───────────────────────
class _IMK(SignatureMaterial):
    """Fields shared by the modified Ibarra-Medina-Krawinkler models."""

    K0: PositiveFloat = Field(1e8, description="Elastic stiffness")
    as_Plus: float = Field(0.03, description="Strain-hardening ratio, positive")
    as_Neg: float = Field(0.03, description="Strain-hardening ratio, negative")
    My_Plus: PositiveFloat = Field(1e6, description="Effective yield moment, positive")
    My_Neg: float = Field(-1e6, lt=0, description="Effective yield moment, negative")
    Lamda_S: float = Field(1000.0, ge=0, description="Cyclic deterioration, strength")
    Lamda_C: float = Field(1000.0, ge=0, description="Cyclic deterioration, post-capping")
    Lamda_A: float = Field(1000.0, ge=0, description="Cyclic deterioration, acceleration")
    Lamda_K: float = Field(1000.0, ge=0, description="Cyclic deterioration, unloading stiffness")
    c_S: float = Field(1.0, description="Rate of strength deterioration")
    c_C: float = Field(1.0, description="Rate of post-capping deterioration")
    c_A: float = Field(1.0, description="Rate of accelerated reloading deterioration")
    c_K: float = Field(1.0, description="Rate of unloading stiffness deterioration")
    theta_p_Plus: PositiveFloat = Field(0.025, description="Pre-capping rotation, positive")
    theta_p_Neg: PositiveFloat = Field(0.025, description="Pre-capping rotation, negative")
    theta_pc_Plus: PositiveFloat = Field(0.2, description="Post-capping rotation, positive")
    theta_pc_Neg: PositiveFloat = Field(0.2, description="Post-capping rotation, negative")
    Res_Pos: float = Field(0.4, ge=0, description="Residual strength ratio, positive")
    Res_Neg: float = Field(0.4, ge=0, description="Residual strength ratio, negative")
    theta_u_Plus: PositiveFloat = Field(0.4, description="Ultimate rotation, positive")
    theta_u_Neg: PositiveFloat = Field(0.4, description="Ultimate rotation, negative")
    D_Plus: PositiveFloat = Field(1.0, description="Cyclic deterioration rate, positive")
    D_Neg: PositiveFloat = Field(1.0, description="Cyclic deterioration rate, negative")


class ModIMKPeakOriented(_IMK):
    """Modified IMK deterioration model with a peak-oriented hysteresis."""

    type: Literal["ModIMKPeakOriented"] = "ModIMKPeakOriented"

    def opensees_args(self) -> list[Any]:
        return [*_head(self), *_tail(self)]


class ModIMKPinching(_IMK):
    """Modified IMK deterioration model with a pinched hysteresis."""

    type: Literal["ModIMKPinching"] = "ModIMKPinching"
    FprPos: float = Field(0.25, ge=0, description="Pinching: force ratio, positive")
    FprNeg: float = Field(0.25, ge=0, description="Pinching: force ratio, negative")
    A_pinch: float = Field(0.5, ge=0, description="Pinching: deformation ratio")

    def opensees_args(self) -> list[Any]:
        return [*_head(self), self.FprPos, self.FprNeg, self.A_pinch, *_tail(self)]


class Bilin(_IMK):
    """Modified IMK deterioration model with a bilinear hysteresis (``Bilin``)."""

    type: Literal["Bilin"] = "Bilin"
    nFactor: float = Field(0.0, ge=0, description="Elastic stiffness amplification factor")

    def opensees_args(self) -> list[Any]:
        return [*_head(self), *_tail(self), self.nFactor]


_IMK_FIELDS = [name for name in _IMK.model_fields if name not in _SKIP]


def _head(m: _IMK) -> list[float]:
    return [getattr(m, name) for name in _IMK_FIELDS[:5]]


def _tail(m: _IMK) -> list[float]:
    return [getattr(m, name) for name in _IMK_FIELDS[5:]]


class Pinching4(SignatureMaterial):
    """Pinched load-deformation response with degradation (symmetric envelope)."""

    type: Literal["Pinching4"] = "Pinching4"
    ePf1: PositiveFloat = Field(1.0e5, description="Envelope force, point 1")
    ePd1: PositiveFloat = Field(0.001, description="Envelope deformation, point 1")
    ePf2: PositiveFloat = Field(1.5e5, description="Envelope force, point 2")
    ePd2: PositiveFloat = Field(0.004, description="Envelope deformation, point 2")
    ePf3: PositiveFloat = Field(1.8e5, description="Envelope force, point 3")
    ePd3: PositiveFloat = Field(0.012, description="Envelope deformation, point 3")
    ePf4: PositiveFloat = Field(0.5e5, description="Envelope force, point 4")
    ePd4: PositiveFloat = Field(0.03, description="Envelope deformation, point 4")
    rDispP: float = Field(0.5, description="Reloading: deformation ratio")
    rForceP: float = Field(0.25, description="Reloading: force ratio")
    uForceP: float = Field(0.05, description="Unloading: force ratio")
    gK1: float = Field(1.0, description="Unloading stiffness degradation 1")
    gK2: float = Field(0.2, description="Unloading stiffness degradation 2")
    gK3: float = Field(0.3, description="Unloading stiffness degradation 3")
    gK4: float = Field(0.2, description="Unloading stiffness degradation 4")
    gKLim: float = Field(0.9, description="Unloading stiffness degradation limit")
    gD1: float = Field(0.5, description="Reloading stiffness degradation 1")
    gD2: float = Field(0.5, description="Reloading stiffness degradation 2")
    gD3: float = Field(2.0, description="Reloading stiffness degradation 3")
    gD4: float = Field(2.0, description="Reloading stiffness degradation 4")
    gDLim: float = Field(0.5, description="Reloading stiffness degradation limit")
    gF1: float = Field(1.0, description="Strength degradation 1")
    gF2: float = Field(0.0, description="Strength degradation 2")
    gF3: float = Field(1.0, description="Strength degradation 3")
    gF4: float = Field(1.0, description="Strength degradation 4")
    gFLim: float = Field(0.9, description="Strength degradation limit")
    gE: float = Field(10.0, description="Energy degradation factor")
    dmgType: Literal["energy", "cycle"] = Field("energy", description="Damage type")

    def opensees_args(self) -> list[Any]:
        envelope = [getattr(self, f"eP{k}{i}") for i in range(1, 5) for k in ("f", "d")]
        negative = [-v for v in envelope]
        reload = [self.rDispP, self.rForceP, self.uForceP]
        rest = [
            getattr(self, name)
            for name in type(self).model_fields
            if name.startswith("g") and name != "gE"
        ]
        return [*envelope, *negative, *reload, *reload, *rest, self.gE, self.dmgType]


# ─────────────────────────── dampers and rate models ───────────────────────────
class ViscousDamper(SignatureMaterial):
    """Maxwell viscous damper: an elastic spring in series with a nonlinear dashpot.

    A transient case only, like :class:`Viscous`. ``K_el`` is the brace or
    device stiffness in series with the dashpot; a very stiff one leaves the
    pure dashpot. Its internal integrator fails (NaN) when the relaxation time
    ``Cd / K_el`` (alpha = 1) is some 1e5 times shorter than the time step: keep
    ``K_el`` realistic rather than "infinite".
    """

    type: Literal["ViscousDamper"] = "ViscousDamper"
    K_el: PositiveFloat = Field(1e8, description="Elastic stiffness of the linear spring")
    Cd: PositiveFloat = Field(1e5, description="Damping coefficient")
    alpha: PositiveFloat = Field(0.35, description="Velocity exponent")
    LGap: float = Field(0.0, ge=0, description="Gap length")
    NM: Literal[1, 2, 3] = Field(
        1, description="Numerical method (1 Dormand-Prince, 2 ABM, 3 Rosenbrock)"
    )
    RelTol: PositiveFloat = Field(1e-6, description="Relative tolerance")
    AbsTol: PositiveFloat = Field(1e-10, description="Absolute tolerance")
    MaxHalf: PositiveInt = Field(15, description="Maximum number of step halvings")


class BilinearOilDamper(SignatureMaterial):
    """Oil damper with a relief valve: bilinear force-velocity after the relief force."""

    type: Literal["BilinearOilDamper"] = "BilinearOilDamper"
    K_el: PositiveFloat = Field(1e8, description="Elastic stiffness of the linear spring")
    Cd: PositiveFloat = Field(1e5, description="Damping coefficient")
    Fr: PositiveFloat = Field(1.0, description="Relief force")
    p: float = Field(1.0, ge=0, description="Post-relief damping coefficient ratio")
    LGap: float = Field(0.0, ge=0, description="Gap length")
    NM: Literal[1, 2, 3] = Field(1, description="Numerical method")
    RelTol: PositiveFloat = Field(1e-6, description="Relative tolerance")
    AbsTol: PositiveFloat = Field(1e-10, description="Absolute tolerance")
    MaxHalf: PositiveInt = Field(15, description="Maximum number of step halvings")


class Viscous(SignatureMaterial):
    """Nonlinear dashpot: stress = C · strain-rate^alpha (use with a transient case).

    Only a transient case has a strain rate: a static case leaves the dashpot
    at zero force. Put it in a ``ZeroLength`` or link element, alone or in a
    ``Parallel`` material with the spring it damps.
    """

    type: Literal["Viscous"] = "Viscous"
    C: PositiveFloat = Field(1e5, description="Damping coefficient")
    alpha: PositiveFloat = Field(1.0, description="Velocity exponent")


class BoucWen(SignatureMaterial):
    """Smooth hysteretic Bouc-Wen model with degradation."""

    type: Literal["BoucWen"] = "BoucWen"
    alpha: float = Field(0.05, ge=0, le=1, description="Post-yield to initial stiffness ratio")
    ko: PositiveFloat = Field(1e7, description="Initial stiffness")
    n: PositiveFloat = Field(1.0, description="Transition sharpness")
    gamma: float = Field(0.5, description="Hysteresis shape, gamma")
    beta: float = Field(0.5, description="Hysteresis shape, beta")
    Ao: float = Field(1.0, description="Hysteresis amplitude")
    deltaA: float = Field(0.0, description="Degradation of A")
    deltaNu: float = Field(0.0, description="Strength degradation")
    deltaEta: float = Field(0.0, description="Stiffness degradation")


# ─────────────────────────── multilinear and gaps ───────────────────────────
class ElasticBilin(SignatureMaterial):
    """Bilinear elastic (no hysteresis), optionally different in compression."""

    type: Literal["ElasticBilin"] = "ElasticBilin"
    EP1: PositiveFloat = Field(2e8, description="Tangent in tension up to epsP2")
    EP2: float = Field(2e7, description="Tangent in tension beyond epsP2")
    epsP2: PositiveFloat = Field(0.002, description="Strain where the tension tangent changes")


class ElasticPPGap(SignatureMaterial):
    """Elastic-perfectly plastic gap: no force until the gap closes (negative gap: compression).

    Beyond the gap the stress is ``E (strain - gap)`` up to ``Fy``, then ``Fy``
    (plus ``eta E`` times the further strain); the plastic strain widens the gap.
    ``Fy`` and ``gap`` take the same sign — OpenSees accepts mixed signs with a
    warning and then answers neither law, so they are refused here.
    """

    type: Literal["ElasticPPGap"] = "ElasticPPGap"
    E: PositiveFloat = Field(2e8, description="Tangent")
    Fy: float = Field(1e5, description="Stress or force at which yielding occurs (sign of gap)")
    gap: float = Field(
        0.01, description="Initial gap (negative, with a negative Fy, in compression)"
    )
    eta: float = Field(0.0, ge=0, lt=1, description="Hardening ratio")
    damage: Literal["noDamage", "damage"] = Field("noDamage", description="Accumulate damage")

    @model_validator(mode="after")
    def _same_sign(self) -> ElasticPPGap:
        if self.Fy == 0.0:
            raise ValueError("Fy must not be zero.")
        if self.gap * self.Fy < 0.0:
            raise ValueError(
                "Fy and gap take the same sign: positive for a tension gap, "
                "negative for a compression gap."
            )
        return self


class MultiLinear(SignatureMaterial):
    """Multilinear hysteretic material through (strain, stress) points, symmetric."""

    type: Literal["MultiLinear"] = "MultiLinear"
    points: list[tuple[float, float]] = Field(
        default_factory=lambda: [(0.001, 2e5), (0.01, 3e5), (0.05, 3.2e5)],
        min_length=1,
        description="(strain, stress) points of the positive envelope",
    )

    def opensees_args(self) -> list[Any]:
        return [v for point in self.points for v in point]


class ElasticMultiLinear(SignatureMaterial):
    """Multilinear elastic material through (strain, stress) points, both signs."""

    type: Literal["ElasticMultiLinear"] = "ElasticMultiLinear"
    eta: float = Field(0.0, ge=0, description="Damping tangent")
    points: list[tuple[float, float]] = Field(
        default_factory=lambda: [
            (-0.01, -3e5),
            (-0.001, -2e5),
            (0.0, 0.0),
            (0.001, 2e5),
            (0.01, 3e5),
        ],
        min_length=2,
        description="(strain, stress) points, strain ascending",
    )

    @model_validator(mode="after")
    def _ascending(self) -> ElasticMultiLinear:
        strains = [p[0] for p in self.points]
        if strains != sorted(strains) or len(set(strains)) != len(strains):
            raise ValueError("ElasticMultiLinear strains must ascend strictly.")
        return self

    def opensees_args(self) -> list[Any]:
        return [
            self.eta,
            "-strain",
            *(p[0] for p in self.points),
            "-stress",
            *(p[1] for p in self.points),
        ]


# ─────────────────────────── soil springs ───────────────────────────
class PySimple1(SignatureMaterial):
    """p-y spring of a pile (soilType 1: soft clay, Matlock; 2: sand, API)."""

    type: Literal["PySimple1"] = "PySimple1"
    soilType: Literal[1, 2] = Field(1, description="1 clay (Matlock), 2 sand (API)")
    pult: PositiveFloat = Field(1e5, description="Ultimate capacity")
    Y50: PositiveFloat = Field(0.01, description="Displacement at half the capacity")
    Cd: float = Field(0.1, ge=0, description="Drag resistance ratio")
    c: float = Field(0.0, ge=0, description="Viscous damping")


class TzSimple1(SignatureMaterial):
    """t-z shaft-friction spring of a pile (soilType 1: Reese and O'Neill; 2: Mosher)."""

    type: Literal["TzSimple1"] = "TzSimple1"
    soilType: Literal[1, 2] = Field(1, description="1 Reese and O'Neill (clay), 2 Mosher (sand)")
    tult: PositiveFloat = Field(5e4, description="Ultimate capacity")
    z50: PositiveFloat = Field(0.005, description="Displacement at half the capacity")
    c: float = Field(0.0, ge=0, description="Viscous damping")


class QzSimple1(SignatureMaterial):
    """q-z tip spring of a pile (qzType 1: Reese and O'Neill clay; 2: Vijayvergiya sand)."""

    type: Literal["QzSimple1"] = "QzSimple1"
    qzType: Literal[1, 2] = Field(
        1, description="1 clay (Reese and O'Neill), 2 sand (Vijayvergiya)"
    )
    qult: PositiveFloat = Field(2e5, description="Ultimate capacity")
    Z50: PositiveFloat = Field(0.01, description="Displacement at half the capacity")
    suction: float = Field(0.0, ge=0, le=0.1, description="Uplift resistance ratio")
    c: float = Field(0.0, ge=0, description="Viscous damping")


# ─────────────────────────── wrappers ───────────────────────────
class ParallelMaterial(SignatureMaterial):
    """Materials side by side: same strain, stresses added (each times its factor)."""

    type: Literal["Parallel"] = "Parallel"
    material_ids: list[PositiveInt] = Field(
        default_factory=list, min_length=1, description="Materials"
    )
    factors: list[float] = Field(
        default_factory=list, description="Factor per material (empty: all 1)"
    )

    @model_validator(mode="after")
    def _factor_per_material(self) -> ParallelMaterial:
        if self.factors and len(self.factors) != len(self.material_ids):
            raise ValueError("Parallel: give one factor per material, or none.")
        return self

    def opensees_args(self) -> list[Any]:
        tail = ["-factors", *self.factors] if self.factors else []
        return [*self.material_ids, *tail]


class SeriesMaterial(SignatureMaterial):
    """Materials one after another: same stress, strains added."""

    type: Literal["Series"] = "Series"
    material_ids: list[PositiveInt] = Field(
        default_factory=list, min_length=1, description="Materials"
    )

    def opensees_args(self) -> list[Any]:
        return list(self.material_ids)


class MinMaxMaterial(SignatureMaterial):
    """Wraps a material and drops its stress to zero beyond a strain range (failure)."""

    type: Literal["MinMax"] = "MinMax"
    material_id: PositiveInt = Field(1, description="Wrapped material")
    min_strain: float = Field(-1e16, description="Minimum strain (failure below)")
    max_strain: float = Field(1e16, description="Maximum strain (failure above)")

    def opensees_args(self) -> list[Any]:
        return [self.material_id, "-min", self.min_strain, "-max", self.max_strain]


class InitStrainMaterial(SignatureMaterial):
    """Wraps a material with an initial strain (prestress, lack of fit)."""

    type: Literal["InitStrainMaterial"] = "InitStrainMaterial"
    material_id: PositiveInt = Field(1, description="Wrapped material")
    initStrain: float = Field(0.0, description="Initial strain")


class InitStressMaterial(SignatureMaterial):
    """Wraps a material with an initial stress (the strain it needs is found by OpenSees)."""

    type: Literal["InitStressMaterial"] = "InitStressMaterial"
    material_id: PositiveInt = Field(1, description="Wrapped material")
    initStress: float = Field(0.0, description="Initial stress")


class FatigueMaterial(SignatureMaterial):
    """Wraps a material with low-cycle fatigue (Coffin-Manson, rainflow counting)."""

    type: Literal["Fatigue"] = "Fatigue"
    material_id: PositiveInt = Field(1, description="Wrapped material")
    E0: float = Field(0.191, description="Strain amplitude at one cycle to failure")
    m: float = Field(-0.458, description="Slope of the Coffin-Manson curve")

    def opensees_args(self) -> list[Any]:
        return [self.material_id, "-E0", self.E0, "-m", self.m]


#: Every signature material, in the order the Material Library lists them.
SIGNATURE_MATERIALS: tuple[type[SignatureMaterial], ...] = (
    ReinforcingSteel,
    Concrete06,
    Concrete07,
    ConcreteCM,
    ModIMKPeakOriented,
    ModIMKPinching,
    Bilin,
    Pinching4,
    ViscousDamper,
    BilinearOilDamper,
    Viscous,
    BoucWen,
    ElasticBilin,
    ElasticPPGap,
    MultiLinear,
    ElasticMultiLinear,
    PySimple1,
    TzSimple1,
    QzSimple1,
    ParallelMaterial,
    SeriesMaterial,
    MinMaxMaterial,
    InitStrainMaterial,
    InitStressMaterial,
    FatigueMaterial,
)


def materials_in_emission_order(materials: list[Any]) -> list[Any]:
    """``materials`` with every wrapper after the materials it wraps (stable otherwise).

    A wrapper whose reference is missing or circular keeps its place;
    ``Project.validate_references`` reports it before the run.
    """
    by_id = {m.id: m for m in materials}
    done: set[int] = set()
    out: list[Any] = []

    def visit(m: Any, path: frozenset[int]) -> None:
        if m.id in done or m.id in path:
            return
        refs = m.referenced_material_ids() if isinstance(m, SignatureMaterial) else []
        for ref in refs:
            if ref in by_id:
                visit(by_id[ref], path | {m.id})
        done.add(m.id)
        out.append(m)

    for m in materials:
        visit(m, frozenset())
    return out


def material_reference_problems(materials: list[Any]) -> list[str]:
    """Wrappers naming a missing material, or themselves."""
    ids = {m.id for m in materials}
    problems = []
    for m in materials:
        if not isinstance(m, SignatureMaterial):
            continue
        for ref in m.referenced_material_ids():
            if ref == m.id:
                problems.append(f"Material {m.id} ({m.type}) wraps itself.")
            elif ref not in ids:
                problems.append(f"Material {m.id} ({m.type}) refers to missing material {ref}.")
    return problems


# ─────────────────────────── nD materials for plates and layered shells ───────────────────────────
class SignatureNDMaterial(SignatureMaterial):
    """An ``nDMaterial`` written as its OpenSees signature (plate and shell layers)."""

    command: ClassVar[str] = "nDMaterial"


class J2Plasticity(SignatureNDMaterial):
    """3D von Mises plasticity with isotropic hardening and saturation (steel plates)."""

    type: Literal["J2Plasticity"] = "J2Plasticity"
    K: PositiveFloat = Field(1.67e11, description="Bulk modulus")
    G: PositiveFloat = Field(7.7e10, description="Shear modulus")
    sig0: PositiveFloat = Field(250e6, description="Initial yield stress")
    sigInf: PositiveFloat = Field(300e6, description="Final saturation yield stress")
    delta: float = Field(0.0, ge=0, description="Exponential hardening parameter")
    H: float = Field(1e9, ge=0, description="Linear hardening parameter")


class PlasticDamageConcretePlaneStress(SignatureNDMaterial):
    """Plane-stress concrete with plasticity and damage (concrete layers of a wall or slab)."""

    type: Literal["PlasticDamageConcretePlaneStress"] = "PlasticDamageConcretePlaneStress"
    E: PositiveFloat = Field(3e10, description="Elastic modulus")
    nu: float = Field(0.2, ge=0, lt=0.5, description="Poisson's ratio")
    ft: PositiveFloat = Field(3e6, description="Tensile strength")
    fc: PositiveFloat = Field(30e6, description="Compressive strength (positive)")


class PlateFiberMaterial(SignatureNDMaterial):
    """Plate wrapper of a 3D nD material (ElasticIsotropic, J2Plasticity) for a layer."""

    type: Literal["PlateFiber"] = "PlateFiber"
    material_id: PositiveInt = Field(1, description="3D nD material")


class PlateFromPlaneStress(SignatureNDMaterial):
    """Plate wrapper of a plane-stress material, with an elastic out-of-plane shear."""

    type: Literal["PlateFromPlaneStress"] = "PlateFromPlaneStress"
    material_id: PositiveInt = Field(1, description="Plane-stress nD material")
    G_out: PositiveFloat = Field(1.25e10, description="Out-of-plane shear modulus")


class PlateRebar(SignatureNDMaterial):
    """A rebar layer of a layered shell: a uniaxial steel at an angle (0 = local x, 90 = y)."""

    type: Literal["PlateRebar"] = "PlateRebar"
    material_id: PositiveInt = Field(1, description="Uniaxial steel material")
    angle: float = Field(0.0, description="Bar direction from local x, degrees")


#: The plate materials the Material Library offers for layered shells.
ND_SIGNATURE_MATERIALS: tuple[type[SignatureNDMaterial], ...] = (
    J2Plasticity,
    PlasticDamageConcretePlaneStress,
    PlateFiberMaterial,
    PlateFromPlaneStress,
    PlateRebar,
)


def is_uniaxial(material: Any) -> bool:
    """True for a material a truss, spring, link or fibre can use (not an nD one)."""
    return getattr(material, "type", "") != "ElasticIsotropic" and not isinstance(
        material, SignatureNDMaterial
    )
