"""Creep and shrinkage of concrete after the fib Model Code 2010 (section 5.1.9.4).

:class:`Mc2010Concrete` holds the mix and the exposure; its methods give the
creep coefficient ``phi(t, t0)`` and the shrinkage strain ``eps_cs(t)``, and
:meth:`Mc2010Concrete.tdconcrete_args` the sixteen arguments of OpenSees'
``TDConcreteMC10`` material, which applies the same equations step by step
(``setCreep 1``). Times are in **days**; ``fcm`` in MPa and ``h0`` in mm, as the
Model Code writes them.

* Basic creep ``phi_bc = 1.8 / fcm^0.7 · ln((30 / t0,adj + 0.035)² (t - t0) + 1)``.
* Drying creep ``phi_dc = 412 / fcm^1.4 · (1 - RH/100) / (0.1 h0)^(1/3) ·
  1 / (0.1 + t0,adj^0.2) · ((t - t0) / (beta_h + t - t0))^gamma(t0)``.
* Basic shrinkage ``eps_cbs = -alpha_bs ((0.1 fcm) / (6 + 0.1 fcm))^2.5 · 1e-6 ·
  (1 - exp(-0.2 sqrt(t)))``.
* Drying shrinkage ``eps_cds = (220 + 110 alpha_ds1) exp(-alpha_ds2 fcm) · 1e-6 ·
  beta_RH · sqrt((t - ts) / (0.035 h0² + t - ts))``.

``t`` is the concrete's age (days since casting). No Qt, no OpenSees.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

from opensees_studio.core.materials.library import TDConcreteMC10

CementClass = Literal["32.5N", "32.5R/42.5N", "42.5R/52.5N/R"]

#: alpha (time adjustment), alpha_bs, alpha_ds1, alpha_ds2 of each cement class.
_CEMENT: dict[str, tuple[int, float, float, float]] = {
    "32.5N": (-1, 800.0, 3.0, 0.013),
    "32.5R/42.5N": (0, 700.0, 4.0, 0.012),
    "42.5R/52.5N/R": (1, 600.0, 6.0, 0.012),
}


@dataclass(frozen=True)
class Mc2010Concrete:
    """A concrete mix and its exposure, in Model Code units (MPa, mm, days, %)."""

    fcm: float
    """Mean compressive strength at 28 days, MPa."""
    relative_humidity: float = 70.0
    """Ambient relative humidity, %."""
    h0: float = 200.0
    """Notional size 2 Ac / u, mm."""
    cement: CementClass = "32.5R/42.5N"
    drying_start: float = 7.0
    """Age at the end of curing, when drying starts, days."""

    def __post_init__(self) -> None:
        if self.fcm <= 0.0:
            raise ValueError("fcm must be positive.")
        if not 40.0 <= self.relative_humidity < 100.0:
            raise ValueError("The Model Code expressions hold for 40 % <= RH < 100 %.")
        if self.h0 <= 0.0:
            raise ValueError("The notional size h0 must be positive.")

    # ── constants of the mix ────────────────────────────────────────
    @property
    def _alpha(self) -> int:
        return _CEMENT[self.cement][0]

    @property
    def elastic_modulus(self) -> float:
        """``Eci = 21500 (fcm / 10)^(1/3)`` MPa (quartzite aggregate)."""
        return float(21500.0 * (self.fcm / 10.0) ** (1.0 / 3.0))

    @property
    def tensile_strength(self) -> float:
        """``fctm = 0.3 (fcm - 8)^(2/3)`` MPa (fck = fcm - 8, up to C50)."""
        return float(0.3 * max(self.fcm - 8.0, 1.0) ** (2.0 / 3.0))

    def adjusted_age(self, t0: float) -> float:
        """``t0,adj = t0 (9 / (2 + t0^1.2) + 1)^alpha >= 0.5``."""
        return float(max(0.5, t0 * (9.0 / (2.0 + t0**1.2) + 1.0) ** self._alpha))

    @property
    def basic_creep_factor(self) -> float:
        """``beta_bc(fcm) = 1.8 / fcm^0.7``."""
        return float(1.8 / self.fcm**0.7)

    @property
    def drying_creep_factor(self) -> float:
        """``beta_dc(fcm) · beta(RH) = 412 / fcm^1.4 · (1 - RH/100) / (0.1 h0)^(1/3)``."""
        rh = self.relative_humidity / 100.0
        return float(412.0 / self.fcm**1.4 * (1.0 - rh) / (0.1 * self.h0) ** (1.0 / 3.0))

    @property
    def beta_h(self) -> float:
        """``beta_h = 1.5 h0 + 250 alpha_fcm <= 1500 alpha_fcm``, alpha_fcm = (35 / fcm)^0.5."""
        alpha_fcm = (35.0 / self.fcm) ** 0.5
        return float(min(1.5 * self.h0 + 250.0 * alpha_fcm, 1500.0 * alpha_fcm))

    @property
    def basic_shrinkage_limit(self) -> float:
        """``eps_cbs0`` (negative)."""
        alpha_bs = _CEMENT[self.cement][1]
        return float(-alpha_bs * ((0.1 * self.fcm) / (6.0 + 0.1 * self.fcm)) ** 2.5 * 1e-6)

    @property
    def drying_shrinkage_limit(self) -> float:
        """``eps_cds0 · beta_RH`` (negative for RH below 99 %)."""
        _a, _bs, ds1, ds2 = _CEMENT[self.cement]
        rh = self.relative_humidity / 100.0
        beta_rh = -1.55 * (1.0 - rh**3)
        return (220.0 + 110.0 * ds1) * math.exp(-ds2 * self.fcm) * 1e-6 * beta_rh

    # ── time functions ──────────────────────────────────────────────
    def creep_coefficient(self, t: float, t0: float) -> float:
        """``phi(t, t0)``: creep at age ``t`` of a stress applied at age ``t0``."""
        if t <= t0:
            return 0.0
        t0_adj = self.adjusted_age(t0)
        basic = self.basic_creep_factor * math.log((30.0 / t0_adj + 0.035) ** 2 * (t - t0) + 1.0)
        gamma = 1.0 / (2.3 + 3.5 / math.sqrt(t0_adj))
        drying = (
            self.drying_creep_factor
            / (0.1 + t0_adj**0.2)
            * ((t - t0) / (self.beta_h + t - t0)) ** gamma
        )
        return float(basic + drying)

    def shrinkage(self, t: float) -> float:
        """``eps_cs(t)``: basic plus drying shrinkage at age ``t`` (negative)."""
        basic = self.basic_shrinkage_limit * (1.0 - math.exp(-0.2 * math.sqrt(max(t, 0.0))))
        drying = 0.0
        if t > self.drying_start:
            elapsed = t - self.drying_start
            drying = self.drying_shrinkage_limit * math.sqrt(
                elapsed / (0.035 * self.h0**2 + elapsed)
            )
        return basic + drying

    def tdconcrete_args(
        self, *, stress_scale: float = 1.0, cast_time: float = 0.0, beta: float = 0.4
    ) -> list[float]:
        """The sixteen ``TDConcreteMC10`` arguments, stresses multiplied by ``stress_scale``.

        ``stress_scale`` converts MPa to the project's stress unit (1e6 for Pa).
        ``cast_time`` is the analysis time of casting (the material carries no load
        before ``cast_time + 2``); drying starts ``drying_start`` days after it.
        ``beta`` is the tension-softening parameter.
        """
        e_modulus = self.elastic_modulus * stress_scale
        return [
            -self.fcm * stress_scale,
            self.tensile_strength * stress_scale,
            e_modulus,
            e_modulus,
            beta,
            cast_time + self.drying_start,
            self.basic_shrinkage_limit,
            1.0,
            self.drying_shrinkage_limit,
            0.035 * self.h0**2,
            self.basic_creep_factor,
            1.0,
            self.drying_creep_factor,
            self.beta_h,
            cast_time,
            float(self._alpha),
        ]


def tdconcrete_material(
    mix: Mc2010Concrete,
    material_id: int,
    *,
    name: str = "",
    stress_scale: float = 1e6,
    cast_time: float = 0.0,
) -> TDConcreteMC10:
    """A ``TDConcreteMC10`` material of ``mix``, cast at ``cast_time`` (days)."""
    fields = [n for n in TDConcreteMC10.model_fields if n not in ("id", "name", "type")]
    values = mix.tdconcrete_args(stress_scale=stress_scale, cast_time=cast_time)
    data = dict(zip(fields, values, strict=True))
    data["cem"] = int(data["cem"])
    return TDConcreteMC10.model_validate({"id": material_id, "name": name, **data})
