"""Uniaxial and isotropic materials.

All materials share the ``Entity`` base. Concrete subclasses set a
``type`` discriminator literal; this lets Pydantic round-trip the
heterogeneous collection in Project.materials through JSON cleanly.

Naming and parameter conventions follow the OpenSeesPy
``uniaxialMaterial`` and ``nDMaterial`` commands. See
https://openseespydoc.readthedocs.io/en/latest/src/uniaxialMaterial.html
"""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import Field, PositiveFloat

from opensees_studio.core._base import Entity


# ──────────────────────────── Linear-elastic ────────────────────────────
class ElasticIsotropic(Entity):
    """Linear-elastic isotropic 3D material — ``nDMaterial ElasticIsotropic``."""

    type: Literal["ElasticIsotropic"] = "ElasticIsotropic"
    E: PositiveFloat = Field(..., description="Young's modulus.")
    nu: float = Field(..., ge=-1.0, le=0.5, description="Poisson's ratio.")
    rho: float = Field(default=0.0, ge=0.0, description="Mass density.")


class ElasticUniaxial(Entity):
    """Linear-elastic uniaxial material — ``uniaxialMaterial Elastic``."""

    type: Literal["Elastic"] = "Elastic"
    E: PositiveFloat
    eta: float = Field(default=0.0, description="Damping coefficient.")
    Eneg: float | None = Field(default=None, description="Optional negative-strain modulus.")


# ──────────────────────────── Steel ────────────────────────────
class Steel01(Entity):
    """Bilinear steel with kinematic hardening — ``uniaxialMaterial Steel01``."""

    type: Literal["Steel01"] = "Steel01"
    Fy: PositiveFloat = Field(..., description="Yield strength.")
    E0: PositiveFloat = Field(..., description="Initial elastic tangent.")
    b: float = Field(..., ge=0.0, le=1.0, description="Strain-hardening ratio (Et/E0).")
    a1: float | None = Field(default=None, description="Isotropic hardening parameter.")
    a2: float | None = None
    a3: float | None = None
    a4: float | None = None


class Steel02(Entity):
    """Giuffre-Menegotto-Pinto steel with isotropic hardening — ``uniaxialMaterial Steel02``."""

    type: Literal["Steel02"] = "Steel02"
    Fy: PositiveFloat
    E0: PositiveFloat
    b: float = Field(..., ge=0.0, le=1.0)
    R0: float = Field(default=18.0, description="Bauschinger curvature parameter (typically 10–20).")
    cR1: float = Field(default=0.925)
    cR2: float = Field(default=0.15)


# ──────────────────────────── Concrete ────────────────────────────
class Concrete01(Entity):
    """Kent-Scott-Park concrete, no tension — ``uniaxialMaterial Concrete01``."""

    type: Literal["Concrete01"] = "Concrete01"
    fpc: float = Field(..., lt=0.0, description="Peak compressive strength (negative).")
    epsc0: float = Field(..., lt=0.0, description="Strain at peak strength (negative).")
    fpcu: float = Field(..., le=0.0, description="Crushing strength (negative or zero).")
    epsU: float = Field(..., lt=0.0, description="Crushing strain (negative).")


class Concrete02(Entity):
    """Linear-tension Kent-Scott-Park — ``uniaxialMaterial Concrete02``."""

    type: Literal["Concrete02"] = "Concrete02"
    fpc: float = Field(..., lt=0.0)
    epsc0: float = Field(..., lt=0.0)
    fpcu: float = Field(..., le=0.0)
    epsU: float = Field(..., lt=0.0)
    lambda_: float = Field(
        ..., alias="lambda", ge=0.0, le=1.0,
        description="Ratio between unloading slope at epscu and initial slope.",
    )
    ft: PositiveFloat = Field(..., description="Tensile strength.")
    Ets: PositiveFloat = Field(..., description="Tension softening stiffness.")


class ElasticPP(Entity):
    """Elastic-perfectly-plastic — ``uniaxialMaterial ElasticPP``."""

    type: Literal["ElasticPP"] = "ElasticPP"
    E: PositiveFloat
    epsy_pos: PositiveFloat = Field(..., description="Yield strain in tension.")
    epsy_neg: float | None = Field(
        default=None, description="Yield strain in compression (negative); defaults to -epsy_pos.",
    )
    eps0: float = Field(default=0.0, description="Initial strain.")


class HystereticMaterial(Entity):
    """Trilinear hysteretic model — ``uniaxialMaterial Hysteretic``.

    Suitable for moment-rotation plastic hinges. Takes three positive
    and three negative backbone points (stress-strain pairs). The
    unload/reload behaviour is controlled by the pinching parameters.

    Positive and negative envelopes may be asymmetric — useful for
    reinforced-concrete members where cracking capacity differs from
    crushing capacity.
    """

    type: Literal["Hysteretic"] = "Hysteretic"
    # Positive (tension/positive-rotation) envelope: 3 points on backbone.
    s1p: float = Field(..., gt=0.0, description="Stress/moment at first positive point.")
    e1p: float = Field(..., gt=0.0, description="Strain/rotation at first positive point.")
    s2p: float = Field(..., description="Stress/moment at second (yield) point.")
    e2p: float = Field(..., description="Strain/rotation at second (yield) point.")
    s3p: float = Field(..., description="Stress/moment at ultimate positive point.")
    e3p: float = Field(..., description="Strain/rotation at ultimate positive point.")
    # Negative envelope (all values stored as negative numbers).
    s1n: float = Field(..., lt=0.0)
    e1n: float = Field(..., lt=0.0)
    s2n: float
    e2n: float
    s3n: float
    e3n: float
    # Pinching & damage (OpenSees defaults work for most cases).
    px: float = Field(default=1.0, ge=0.0, le=1.0, description="Pinching factor for strain.")
    py: float = Field(default=1.0, ge=0.0, le=1.0, description="Pinching factor for stress.")
    d1: float = Field(default=0.0, ge=0.0, description="Ductility damage, linear portion.")
    d2: float = Field(default=0.0, ge=0.0, description="Ductility damage, cumulative portion.")
    beta: float = Field(
        default=0.0, ge=0.0,
        description="Unloading-stiffness degradation (0 = no degradation).",
    )


# ──────────────────────────── Discriminated union ────────────────────────────
Material = Annotated[
    Union[
        ElasticIsotropic,
        ElasticUniaxial,
        Steel01,
        Steel02,
        Concrete01,
        Concrete02,
        ElasticPP,
        HystereticMaterial,
    ],
    Field(discriminator="type"),
]
"""Tagged union of every material kind. Pydantic uses ``type`` to dispatch on JSON load."""
