"""Every unit system: coherent factors, a label in every table, the kgf systems by hand."""

from __future__ import annotations

import math

import pytest

from opensees_studio.core.load_display import format_force, format_line_load, format_pressure
from opensees_studio.core.units import (
    UnitConverter,
    UnitSystem,
    density_scale,
    force_scale,
    gravity,
    labels_for,
    length_scale,
    mass_density_label,
    mass_scale,
    metres_per_unit,
    newtons_per_unit,
    stress_scale,
)

G = 9.80665


@pytest.mark.parametrize("system", list(UnitSystem))
def test_every_system_is_in_every_table(system: UnitSystem) -> None:
    labels_for(system)
    mass_density_label(system)
    assert metres_per_unit(system) > 0.0
    assert newtons_per_unit(system) > 0.0
    # Standard gravity is the same acceleration in every system.
    assert gravity(system) * metres_per_unit(system) == pytest.approx(G, rel=1e-6)


@pytest.mark.parametrize("system", list(UnitSystem))
def test_every_system_reaches_every_service_table(system: UnitSystem) -> None:
    from opensees_studio.services import ifc_export, sap2000_text

    assert system in ifc_export._LENGTH_UNIT
    assert system in ifc_export._FORCE_UNIT
    assert system in sap2000_text._WRITE_UNITS


def test_the_kgf_systems_convert_by_hand() -> None:
    kgf_m, kgf_cm, tonf_m = UnitSystem.MKS_M_KGF, UnitSystem.MKS_CM_KGF, UnitSystem.MKS_M_TONF
    assert force_scale(kgf_m, UnitSystem.SI_M_N) == pytest.approx(G)
    assert force_scale(tonf_m, kgf_m) == pytest.approx(1000.0)
    assert length_scale(kgf_cm, kgf_m) == pytest.approx(0.01)
    # f'c = 280 kgf/cm² is 27.46 MPa and 2 800 000 kgf/m².
    assert 280.0 * stress_scale(kgf_cm, UnitSystem.SI_MM_N) == pytest.approx(27.459, rel=1e-4)
    assert 280.0 * stress_scale(kgf_cm, kgf_m) == pytest.approx(2.8e6)
    # The coherent mass is kgf·s²/m = 9.80665 kg: 1 kg is 1/g of it.
    assert mass_scale(UnitSystem.SI_M_N, kgf_m) == pytest.approx(1.0 / G)
    # Steel, 7850 kg/m³, is 800.5 kgf·s²/m⁴ (its weight 7850 kgf/m³ over g).
    assert 7850.0 * density_scale(UnitSystem.SI_M_N, kgf_m) == pytest.approx(7850.0 / G)
    assert labels_for(kgf_cm).stress == "kgf/cm²"
    assert labels_for(tonf_m).moment == "tonf·m"


def test_the_us_pound_and_si_kilonewton_systems() -> None:
    assert force_scale(UnitSystem.US_IN_KIP, UnitSystem.US_IN_LB) == pytest.approx(1000.0)
    assert stress_scale(UnitSystem.US_IN_LB, UnitSystem.US_IN_KIP) == pytest.approx(1e-3)  # psi→ksi
    assert stress_scale(UnitSystem.SI_M_KN, UnitSystem.SI_M_N) == pytest.approx(1000.0)  # kPa→Pa
    assert stress_scale(UnitSystem.SI_MM_KN, UnitSystem.SI_MM_N) == pytest.approx(1000.0)
    # kN·s²/m is a tonne.
    assert mass_scale(UnitSystem.SI_M_KN, UnitSystem.SI_M_N) == pytest.approx(1000.0)


def test_load_values_in_kgf_and_tonf() -> None:
    shown_in_kgf_m = UnitConverter(model=UnitSystem.SI_M_N, display=UnitSystem.MKS_M_KGF)
    assert format_force(G * 500.0, shown_in_kgf_m) == "500 kgf"
    assert format_force(G * 2500.0, shown_in_kgf_m) == "2.5 tonf"
    assert format_line_load(-G * 1200.0, None, shown_in_kgf_m) == "-1.2 tonf/m"
    kgf_cm = UnitConverter(model=UnitSystem.MKS_CM_KGF)
    assert format_pressure(280.0, kgf_cm) == "280 kgf/cm²"
    lb = UnitConverter(model=UnitSystem.US_IN_LB)
    assert format_force(1500.0, lb) == "1.5 kip"


def test_old_files_keep_their_unit_strings() -> None:
    # Saved in .osmodel files: these four must never change.
    assert UnitSystem.SI_M_N.value == "SI (m, N, kg, s, Pa)"
    assert UnitSystem.US_IN_KIP.value == "US (in, kip, kip·s²/in, s, ksi)"
    assert len({s.value for s in UnitSystem}) == len(UnitSystem)
    assert math.isclose(gravity(UnitSystem.US_IN_KIP), 386.0886)
