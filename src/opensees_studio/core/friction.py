"""Friction models for sliding bearings (OpenSees ``frictionModel``).

Stored in ``Project.friction_models`` and referenced by id from the
``flatSliderBearing`` and ``singleFPBearing`` elements, the way materials
are referenced from elements. Parameter names follow the OpenSeesPy
``frictionModel`` command. Every rule below mirrors a check that makes
OpenSees 3.8.0 terminate the whole process (exit code 255, no Python
exception) when it fails, measured on the live build:

* Coulomb: ``mu`` must be positive.
* VelDependent: ``muSlow`` and ``muFast`` must be positive (a zero muFast
  is refused by OpenSees too) and ``transRate`` must not be negative
  (OpenSees accepts zero; this model requires a positive rate so the fast
  coefficient can ever be reached).
* VelNormalFrcDep: ``aSlow`` and ``aFast`` must be positive.

Measured behaviour of the live build (flat slider under a constant normal
force N and an imposed velocity v):

* Coulomb: friction force ``mu N``.
* VelDependent: ``mu(v) = muFast - (muFast - muSlow) exp(-transRate |v|)``.
* VelNormalFrcDep: slow and fast friction forces ``aSlow N^nSlow`` and
  ``aFast N^nFast`` (so the coefficients are ``a N^(n - 1)``; ``n = 1``
  gives a Coulomb-like constant coefficient ``a``), blended with the same
  exponential law at the rate ``alpha0 + alpha1 N + alpha2 N^2``.
  ``maxMuFact`` is passed through unchanged; no cap was observed for
  ``n = 1`` with ``maxMuFact = 0.5``.
"""

from __future__ import annotations

import math
from typing import Annotated, Literal

from pydantic import Field, PositiveFloat

from opensees_studio.core._base import Entity


def velocity_dependent_coefficient(
    mu_slow: float, mu_fast: float, trans_rate: float, velocity: float
) -> float:
    """``muFast - (muFast - muSlow) exp(-transRate |v|)`` (OpenSees VelDependent)."""
    return mu_fast - (mu_fast - mu_slow) * math.exp(-trans_rate * abs(velocity))


class CoulombFriction(Entity):
    """``frictionModel Coulomb``: constant coefficient ``mu``."""

    type: Literal["Coulomb"] = "Coulomb"
    mu: PositiveFloat = Field(..., description="Friction coefficient.")

    def coefficient(self, velocity: float = 0.0, normal_force: float = 1.0) -> float:
        return self.mu


class VelDependentFriction(Entity):
    """``frictionModel VelDependent``: coefficient rising from ``muSlow`` to
    ``muFast`` with the sliding velocity at the rate ``transRate``."""

    type: Literal["VelDependent"] = "VelDependent"
    mu_slow: PositiveFloat = Field(..., description="Coefficient at zero velocity.")
    mu_fast: PositiveFloat = Field(..., description="Coefficient at high velocity.")
    trans_rate: PositiveFloat = Field(..., description="Transition rate (time/length).")

    def coefficient(self, velocity: float = 0.0, normal_force: float = 1.0) -> float:
        return velocity_dependent_coefficient(self.mu_slow, self.mu_fast, self.trans_rate, velocity)


class VelNormalFrcDepFriction(Entity):
    """``frictionModel VelNormalFrcDep``: velocity and normal-force dependent
    coefficient. Live 3.8.0 signature::

        frictionModel VelNormalFrcDep tag aSlow nSlow aFast nFast
                                          alpha0 alpha1 alpha2 maxMuFact
    """

    type: Literal["VelNormalFrcDep"] = "VelNormalFrcDep"
    a_slow: PositiveFloat = Field(..., description="Slow friction force constant aSlow.")
    n_slow: float = Field(default=0.0, description="Slow normal-force exponent nSlow.")
    a_fast: PositiveFloat = Field(..., description="Fast friction force constant aFast.")
    n_fast: float = Field(default=0.0, description="Fast normal-force exponent nFast.")
    alpha0: float = Field(default=0.0, ge=0.0, description="Transition rate constant.")
    alpha1: float = Field(default=0.0, ge=0.0, description="Transition rate, linear in N.")
    alpha2: float = Field(default=0.0, ge=0.0, description="Transition rate, quadratic in N.")
    max_mu_fact: PositiveFloat = Field(
        default=1.0, description="Maximum friction coefficient factor (passed through)."
    )

    def coefficient(self, velocity: float = 0.0, normal_force: float = 1.0) -> float:
        """Coefficient ``F / N`` measured on the live build for ``N > 0``."""
        if normal_force <= 0.0:
            raise ValueError("normal_force must be > 0.")
        mu_slow = self.a_slow * normal_force ** (self.n_slow - 1.0)
        mu_fast = self.a_fast * normal_force ** (self.n_fast - 1.0)
        rate = self.alpha0 + self.alpha1 * normal_force + self.alpha2 * normal_force**2
        return velocity_dependent_coefficient(mu_slow, mu_fast, rate, velocity)


FrictionModel = Annotated[
    CoulombFriction | VelDependentFriction | VelNormalFrcDepFriction,
    Field(discriminator="type"),
]
FRICTION_MODEL_CLASSES = (CoulombFriction, VelDependentFriction, VelNormalFrcDepFriction)
