"""fib Model Code 2010 creep and shrinkage, by hand."""

from __future__ import annotations

import math

import pytest

from opensees_studio.core.mc2010 import Mc2010Concrete, tdconcrete_material


def test_creep_coefficient_by_hand() -> None:
    mix = Mc2010Concrete(fcm=38.0, relative_humidity=60.0, h0=200.0, cement="42.5R/52.5N/R")
    t0_adj = 28.0 * (9.0 / (2.0 + 28.0**1.2) + 1.0)
    basic = 1.8 / 38.0**0.7 * math.log((30.0 / t0_adj + 0.035) ** 2 * 9972.0 + 1.0)
    beta_h = min(1.5 * 200.0 + 250.0 * (35 / 38) ** 0.5, 1500.0 * (35 / 38) ** 0.5)
    gamma = 1.0 / (2.3 + 3.5 / math.sqrt(t0_adj))
    drying = (
        412.0
        / 38.0**1.4
        * 0.4
        / 20.0 ** (1 / 3)
        / (0.1 + t0_adj**0.2)
        * (9972.0 / (beta_h + 9972.0)) ** gamma
    )
    assert mix.creep_coefficient(10000.0, 28.0) == pytest.approx(basic + drying)
    assert mix.creep_coefficient(28.0, 28.0) == 0.0


def test_shrinkage_by_hand() -> None:
    mix = Mc2010Concrete(fcm=38.0, relative_humidity=60.0, h0=200.0, cement="32.5R/42.5N")
    basic = -700.0 * (3.8 / 9.8) ** 2.5 * 1e-6 * (1 - math.exp(-0.2 * math.sqrt(365.0)))
    drying = (
        (220 + 440)
        * math.exp(-0.012 * 38.0)
        * 1e-6
        * -1.55
        * (1 - 0.6**3)
        * math.sqrt(358.0 / (0.035 * 200.0**2 + 358.0))
    )
    assert mix.shrinkage(365.0) == pytest.approx(basic + drying)


def test_the_material_carries_the_model_code_parameters() -> None:
    mix = Mc2010Concrete(fcm=30.0)
    material = tdconcrete_material(mix, 3, stress_scale=1e6, cast_time=10.0)
    assert material.fc == pytest.approx(-30e6)
    assert material.tcast == 10.0
    assert material.tD == pytest.approx(17.0)
    assert material.phidb == pytest.approx(mix.beta_h)
    assert material.cem == 0


def test_humidity_outside_the_model_code_range_is_refused() -> None:
    with pytest.raises(ValueError, match="RH"):
        Mc2010Concrete(fcm=30.0, relative_humidity=30.0)
