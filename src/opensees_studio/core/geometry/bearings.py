"""Elastomeric bearing (seismic isolator) elements.

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
"""

from __future__ import annotations

import math
from typing import Literal

from pydantic import Field, PositiveFloat, PositiveInt, model_validator

from opensees_studio.core._base import Entity

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


class _ElastomericBearingBase(Entity):
    """Fields shared by both elastomeric bearing elements."""

    nodes: tuple[PositiveInt, PositiveInt] = Field(
        ..., description="Bottom (i) and top (j) node; coincident nodes are allowed."
    )
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
    def _check_orient(self) -> _ElastomericBearingBase:
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


ElastomericBearingElement = ElastomericBearingPlasticityElement | ElastomericBearingBoucWenElement
BEARING_CLASSES = (ElastomericBearingPlasticityElement, ElastomericBearingBoucWenElement)
