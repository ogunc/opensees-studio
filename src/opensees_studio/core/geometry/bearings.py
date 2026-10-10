"""Bearing (seismic isolator) elements: elastomeric and sliding.

OpenSees ``elastomericBearingPlasticity`` and ``elastomericBearingBoucWen``
in 2D and 3D. Both share the same shear model inputs: initial elastic
stiffness ``k_init``, characteristic strength ``qd`` (the zero-displacement
intercept of the post-yield branch), post-yield stiffness ratio ``alpha1``,
a nonlinear hardening term ``alpha2 k_init |u|^mu`` (``alpha2 = 0`` gives a
plain bilinear loop). The Bouc-Wen variant adds the smooth transition
parameters ``eta``, ``beta`` and ``gamma``.

The axial (``-P``) and moment (``-Mz``) responses are uniaxial materials
referenced by id; a 3D model also needs the torsion (``-T``) and ``-My``
materials. The runner always writes the ``-orient x1 x2 x3 y1 y2 y3``
vectors because OpenSees 3.8 terminates the process when a bearing with
coincident nodes has no orientation (see ``OpenSeesRunner._emit_bearing``).

Closed-form helpers for the bilinear shear model (OpenSees 3.8 behaviour,
confirmed on a displacement-controlled run):

* yield displacement  ``u_y = qd / (k_init (1 - alpha1))``
* yield force         ``F_y = k_init u_y = qd / (1 - alpha1)``
* post-yield branch   ``F = qd + alpha1 k_init u``
* energy per full cycle of amplitude ``u_max >= u_y``:
  ``4 qd (u_max - u_y)``

Sliding bearings (``flatSliderBearing`` and ``singleFPBearing``) reference
a friction model from ``Project.friction_models`` and carry the same
materials, orientation and optional flags. Closed-form helpers for Coulomb
friction ``mu`` under the axial load ``W`` (confirmed on the live build):

* yield (slip) displacement  ``u_y = mu W / k_init``
* flat slider: rectangular loop at the force ``mu W``
* single FP: post-slip stiffness ``W / r_eff``, intercept ``mu W``
* energy per full cycle ``4 mu W (u_max - u_y)`` for both
* isolated period of the pendulum ``2 pi sqrt(r_eff / g)``
"""

from __future__ import annotations

import math
from typing import Literal

from pydantic import Field, PositiveFloat, PositiveInt, model_validator

from opensees_studio.core._base import Entity
from opensees_studio.core.units import UnitSystem, gravity

ORIENT_PARALLEL_TOL = 1e-9


def bearing_yield_displacement(k_init: float, qd: float, alpha1: float) -> float:
    """``u_y = qd / (k_init (1 - alpha1))`` of the bilinear shear model."""
    if k_init <= 0.0 or qd <= 0.0 or not 0.0 <= alpha1 < 1.0:
        raise ValueError("Need k_init > 0, qd > 0 and 0 <= alpha1 < 1.")
    return qd / (k_init * (1.0 - alpha1))


def bearing_yield_force(k_init: float, qd: float, alpha1: float) -> float:
    """``F_y = k_init u_y = qd / (1 - alpha1)``."""
    return k_init * bearing_yield_displacement(k_init, qd, alpha1)


def bearing_shear_force(
    k_init: float, qd: float, alpha1: float, u: float, alpha2: float = 0.0, mu: float = 2.0
) -> float:
    """Monotonic (backbone) shear force at displacement ``u >= 0``.

    ``k_init u`` up to the yield displacement, then ``qd + alpha1 k_init u``,
    plus the hardening term ``alpha2 k_init u^mu`` in both branches.
    """
    if u < 0.0:
        raise ValueError("u must be >= 0.")
    u_y = bearing_yield_displacement(k_init, qd, alpha1)
    hardening = alpha2 * k_init * u**mu if alpha2 else 0.0
    if u <= u_y:
        return k_init * u + hardening
    return qd + alpha1 * k_init * u + hardening


def bearing_effective_stiffness(
    k_init: float, qd: float, alpha1: float, u: float, alpha2: float = 0.0, mu: float = 2.0
) -> float:
    """Secant stiffness ``F(u) / u`` of the backbone at displacement ``u > 0``."""
    if u <= 0.0:
        raise ValueError("u must be > 0.")
    return bearing_shear_force(k_init, qd, alpha1, u, alpha2, mu) / u


def bilinear_cycle_energy(qd: float, u_max: float, u_y: float) -> float:
    """Area of one full bilinear hysteresis loop: ``4 qd (u_max - u_y)``.

    Zero below the yield displacement (the loop is a line).
    """
    if u_max <= u_y:
        return 0.0
    return 4.0 * qd * (u_max - u_y)


def sliding_yield_displacement(mu: float, weight: float, k_init: float) -> float:
    """Slip displacement ``u_y = mu W / k_init`` of a sliding bearing."""
    if mu <= 0.0 or weight <= 0.0 or k_init <= 0.0:
        raise ValueError("Need mu > 0, weight > 0 and k_init > 0.")
    return mu * weight / k_init


def pendulum_restoring_stiffness(weight: float, r_eff: float) -> float:
    """Post-slip stiffness ``W / r_eff`` of a single friction pendulum."""
    if weight <= 0.0 or r_eff <= 0.0:
        raise ValueError("Need weight > 0 and r_eff > 0.")
    return weight / r_eff


def pendulum_period(r_eff: float, g: float) -> float:
    """Isolated period ``2 pi sqrt(r_eff / g)``; ``g`` in the length unit of ``r_eff``."""
    if r_eff <= 0.0 or g <= 0.0:
        raise ValueError("Need r_eff > 0 and g > 0.")
    return 2.0 * math.pi * math.sqrt(r_eff / g)


def friction_cycle_energy(mu: float, weight: float, u_max: float, u_y: float) -> float:
    """Area of one full sliding loop: ``4 mu W (u_max - u_y)``, zero below slip."""
    if u_max <= u_y:
        return 0.0
    return 4.0 * mu * weight * (u_max - u_y)


class _BearingBase(Entity):
    """Nodes, materials, orientation and optional flags shared by every bearing."""

    nodes: tuple[PositiveInt, PositiveInt] = Field(
        ..., description="Bottom (i) and top (j) node; coincident nodes are allowed."
    )
    p_material_id: PositiveInt = Field(..., description="Uniaxial material for axial P.")
    mz_material_id: PositiveInt = Field(..., description="Uniaxial material for moment Mz.")
    t_material_id: PositiveInt | None = Field(
        default=None, description="Uniaxial material for torsion T (3D models only)."
    )
    my_material_id: PositiveInt | None = Field(
        default=None, description="Uniaxial material for moment My (3D models only)."
    )
    orient: tuple[float, float, float, float, float, float] | None = Field(
        default=None,
        description=(
            "Local axes (x1, x2, x3, y1, y2, y3): x is the bearing axis, y the shear "
            "direction. None lets the runner choose (element axis, or the vertical for "
            "coincident nodes, with the shear along global X)."
        ),
    )
    shear_dist: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Shear distance ratio from node i (OpenSees -shearDist, default 0.5).",
    )
    do_rayleigh: bool = Field(default=False, description="Emit -doRayleigh.")
    mass: float = Field(default=0.0, ge=0.0, description="Lumped element mass (-mass).")

    @model_validator(mode="after")
    def _check_orient(self) -> _BearingBase:
        if self.orient is None:
            return self
        x = self.orient[:3]
        y = self.orient[3:]
        nx = math.sqrt(sum(c * c for c in x))
        ny = math.sqrt(sum(c * c for c in y))
        if nx == 0.0 or ny == 0.0:
            raise ValueError("orient vectors must be non-zero.")
        cross = (
            x[1] * y[2] - x[2] * y[1],
            x[2] * y[0] - x[0] * y[2],
            x[0] * y[1] - x[1] * y[0],
        )
        if math.sqrt(sum(c * c for c in cross)) <= ORIENT_PARALLEL_TOL * nx * ny:
            raise ValueError("orient x and y vectors must not be parallel.")
        return self

    @property
    def material_reference_ids(self) -> tuple[int, ...]:
        """Every material id the element refers to (P, Mz, then T and My when set)."""
        return tuple(
            m
            for m in (
                self.p_material_id,
                self.mz_material_id,
                self.t_material_id,
                self.my_material_id,
            )
            if m is not None
        )


class _ElastomericBearingBase(_BearingBase):
    """Shear model inputs shared by both elastomeric bearing elements."""

    k_init: PositiveFloat = Field(..., description="Initial elastic shear stiffness Kinit.")
    qd: PositiveFloat = Field(..., description="Characteristic strength Qd (force).")
    alpha1: float = Field(..., ge=0.0, lt=1.0, description="Post-yield stiffness ratio.")
    alpha2: float = Field(
        default=0.0,
        ge=0.0,
        lt=1.0,
        description="Nonlinear hardening ratio (alpha2 Kinit |u|^mu); 0 for bilinear.",
    )
    mu: PositiveFloat = Field(default=2.0, description="Exponent of the hardening term.")

    @property
    def yield_displacement(self) -> float:
        return bearing_yield_displacement(self.k_init, self.qd, self.alpha1)

    @property
    def yield_force(self) -> float:
        return bearing_yield_force(self.k_init, self.qd, self.alpha1)

    def effective_stiffness(self, u: float) -> float:
        """Secant stiffness of the backbone at displacement ``u > 0``."""
        return bearing_effective_stiffness(
            self.k_init, self.qd, self.alpha1, u, self.alpha2, self.mu
        )


class ElastomericBearingPlasticityElement(_ElastomericBearingBase):
    """OpenSees ``elastomericBearingPlasticity``: bilinear shear with a
    return-mapping plasticity model and coupled axial and moment materials."""

    type: Literal["ElastomericBearingPlasticity"] = "ElastomericBearingPlasticity"


class ElastomericBearingBoucWenElement(_ElastomericBearingBase):
    """OpenSees ``elastomericBearingBoucWen``: smooth Bouc-Wen shear loop.

    ``eta`` sharpens the elastic-to-plastic transition (large eta approaches
    the bilinear loop); ``beta`` and ``gamma`` shape the loop and their sum
    should be 1 for the yield force to equal ``qd / (1 - alpha1)``.
    """

    type: Literal["ElastomericBearingBoucWen"] = "ElastomericBearingBoucWen"
    eta: PositiveFloat = Field(default=1.0, description="Bouc-Wen transition exponent.")
    beta: float = Field(default=0.5, ge=0.0, description="Bouc-Wen beta.")
    gamma: float = Field(default=0.5, ge=0.0, description="Bouc-Wen gamma.")

    @model_validator(mode="after")
    def _check_bouc_wen(self) -> ElastomericBearingBoucWenElement:
        if self.beta + self.gamma <= 0.0:
            raise ValueError("beta + gamma must be positive.")
        return self


class _SlidingBearingBase(_BearingBase):
    """Friction model reference, initial stiffness and the ``-iter`` flag."""

    friction_model_id: PositiveInt = Field(..., description="Friction model (Project) id.")
    k_init: PositiveFloat = Field(
        ..., description="Initial (stick) stiffness Kinit before sliding starts."
    )
    max_iter: PositiveInt = Field(default=25, description="-iter maximum iterations.")
    tol: PositiveFloat = Field(default=1e-12, description="-iter convergence tolerance.")

    def yield_displacement(self, mu: float, weight: float) -> float:
        """Slip displacement ``mu W / k_init`` for the friction coefficient ``mu``."""
        return sliding_yield_displacement(mu, weight, self.k_init)


class FlatSliderBearingElement(_SlidingBearingBase):
    """OpenSees ``flatSliderBearing``: rigid-plastic sliding at ``mu W`` after
    the initial branch ``k_init``, no restoring stiffness."""

    type: Literal["FlatSliderBearing"] = "FlatSliderBearing"


class SingleFPBearingElement(_SlidingBearingBase):
    """OpenSees ``singleFPBearing``: single friction pendulum with the
    effective radius ``r_eff`` (post-slip stiffness ``W / r_eff``)."""

    type: Literal["SingleFPBearing"] = "SingleFPBearing"
    r_eff: PositiveFloat = Field(..., description="Effective radius of curvature Reff.")

    def restoring_stiffness(self, weight: float) -> float:
        """Post-slip stiffness ``W / r_eff``."""
        return pendulum_restoring_stiffness(weight, self.r_eff)

    def isolated_period(self, units: UnitSystem) -> float:
        """``2 pi sqrt(r_eff / g)`` with ``g`` in the length unit of ``units``."""
        return pendulum_period(self.r_eff, gravity(units))


ElastomericBearingElement = ElastomericBearingPlasticityElement | ElastomericBearingBoucWenElement
SlidingBearingElement = FlatSliderBearingElement | SingleFPBearingElement
ELASTOMERIC_BEARING_CLASSES = (
    ElastomericBearingPlasticityElement,
    ElastomericBearingBoucWenElement,
)
SLIDING_BEARING_CLASSES = (FlatSliderBearingElement, SingleFPBearingElement)
BEARING_CLASSES = ELASTOMERIC_BEARING_CLASSES + SLIDING_BEARING_CLASSES
