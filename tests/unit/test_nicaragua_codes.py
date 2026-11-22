"""RNC-07 (Nicaragua) and NSCM (Managua) seismic action, against the official texts."""

from __future__ import annotations

import numpy as np
import pytest

from opensees_studio.core import nscm, rnc07
from opensees_studio.core.target_spectrum import TargetSpectrum, target_to_case_spectrum
from opensees_studio.core.units import UnitSystem, gravity

# ─────────────────────────── RNC-07 ───────────────────────────


def test_rnc07_soil_factor_table_2() -> None:
    assert rnc07.soil_factor("A", "II") == 1.8
    assert rnc07.soil_factor("B", "III") == 2.2
    assert rnc07.soil_factor("C", "I") == 1.0
    with pytest.raises(rnc07.Rnc07Error, match="site-specific"):
        rnc07.soil_factor("C", "IV")


def test_rnc07_zone_for_a0_takes_the_higher_zone_between_values() -> None:
    assert rnc07.zone_for_a0(0.1) == "A"
    assert rnc07.zone_for_a0(0.15) == "B"
    assert rnc07.zone_for_a0(0.31) == "C"


def test_rnc07_spectrum_branches_ec_6() -> None:
    a0, s = 0.2, 1.0
    d = 2.7 * a0
    a = rnc07.elastic_spectrum([0.0, 0.05, 0.3, 1.2, 2.0, 4.0], a0, s)
    assert a[0] == pytest.approx(a0)
    assert a[1] == pytest.approx(a0 + (d - a0) * 0.5)
    assert a[2] == pytest.approx(0.54)
    assert a[3] == pytest.approx(d * 0.6 / 1.2)
    assert a[4] == pytest.approx(0.162)
    assert a[5] == pytest.approx(d * (0.6 / 2.0) * (2.0 / 4.0) ** 2)  # 0.0405
    assert rnc07.elastic_spectrum(0.3, a0, s, "A")[0] == pytest.approx(1.5 * 0.54)


def test_rnc07_ductility_reduction_ec_2_and_irregularity() -> None:
    assert rnc07.ductility_reduction(4.0) == 4.0
    assert rnc07.ductility_reduction(4.0, 0.05) == pytest.approx(1.0 + 0.5 * 3.0)
    assert rnc07.ductility_reduction(4.0, 0.5, "irregular_two") == pytest.approx(3.2)
    assert rnc07.ductility_reduction(1.0, 0.5, "strongly_irregular") == 1.0  # never below 1


def test_rnc07_anexo_d_example_iii_static_method() -> None:
    """RNC-07 Anexo D III: Managua, soil II, Q = 2: c = 0.304 raised to S a0 = 0.45."""
    coefficient = rnc07.static_coefficient(0.30, 1.5, 2.0)
    assert coefficient.c == pytest.approx(0.45)
    assert "minimum" in coefficient.why
    weights = np.array([131.57, 131.57, 131.57, 101.95])
    heights = np.array([2.7, 5.4, 8.1, 10.8])
    forces = coefficient.c * weights.sum() * weights * heights / (weights @ heights)
    assert forces[::-1] == pytest.approx([76.13, 73.68, 49.12, 24.56], abs=0.01)


def test_rnc07_coefficient_ec_3_and_group_a() -> None:
    # S 2.7 a0 / (Q'Ω) = 0.09 falls below the S a0 = 0.2 floor of Ec. 3
    assert rnc07.static_coefficient(0.2, 1.0, 3.0).c == pytest.approx(0.2)
    assert rnc07.static_coefficient(0.2, 1.0, 3.0, group="A").c == pytest.approx(0.3)
    assert rnc07.static_coefficient(0.2, 2.2, 1.0).c == pytest.approx(2.2 * 0.54 / 2.0)
    with_t = rnc07.static_coefficient(0.2, 1.0, 3.0, period=1.2)
    assert with_t.c == pytest.approx(max(0.54 * 0.5, 0.2) / (2.0 * 3.0))


def test_rnc07_modal_minimum_and_drift_factors() -> None:
    v = rnc07.modal_base_shear_minimum(0.3, 1.5, 2.0, 0.4, 1000.0)
    assert v == pytest.approx(0.8 * 1.215 * 1000.0 / 4.0)
    assert rnc07.service_drift_factor(2.0, 0.4) == pytest.approx(1.6)
    assert rnc07.collapse_drift_factor(2.0) == 4.0


# ─────────────────────────── NSCM ───────────────────────────


def test_nscm_zone_and_tables() -> None:
    assert nscm.zone_for_a0(0.16) == "Z1"
    assert nscm.zone_for_a0(0.17) == "Z2"
    assert nscm.zone_for_a0(0.30) == "Z3"
    assert nscm.zone_for_a0(0.36667) == "Z4"
    assert nscm.site_amplification(0.36667, "C") == 1.3
    with pytest.raises(nscm.NscmError, match="site response"):
        nscm.site_amplification(0.36667, "E")
    assert nscm.spectral_adjustment("D") == (2.0, 5.0 / 3.0)
    assert nscm.importance_factor("IV") == 1.65


def test_nscm_spectrum_ec_6_7_1_managua_d() -> None:
    site = nscm.NscmSite(a0=0.36667, site_class="D", risk_category="II", r0=6.0)
    a0 = 0.36667 * 1.4
    tb, tc, td = site.corner_periods()
    assert (tb, tc, td) == pytest.approx((0.1, 0.5, 2.0))
    a = site.elastic([0.0, 0.05, 0.3, 1.0, 3.0])
    assert a[0] == pytest.approx(a0)
    assert a[1] == pytest.approx(a0 * (1.0 + 0.5 * 1.4))
    assert a[2] == pytest.approx(2.4 * a0)
    assert a[3] == pytest.approx(2.4 * a0 * 0.5**0.8)
    assert a[4] == pytest.approx(2.4 * a0 * (0.5 / 3.0) ** 0.8 * (2.0 / 3.0) ** 2)
    # reduced: rising branch Ec. 6.9-1, then A / Ro
    r = site.reduced([0.0, 0.1, 1.0])
    assert r[0] == pytest.approx(a0)
    assert r[1] == pytest.approx(2.4 * a0 / 6.0)
    assert r[2] == pytest.approx(a[3] / 6.0)


def test_nscm_seismic_coefficient_and_minimum() -> None:
    site = nscm.NscmSite(a0=0.36667, site_class="C", risk_category="III", r0=8.0)
    a0 = 0.36667 * 1.3 * 1.3
    cs, why = site.seismic_coefficient(0.3)
    assert cs == pytest.approx(2.4 * a0 / 8.0) and "plateau" in why
    assert site.minimum_coefficient() == pytest.approx(4.0 / 3.0 * 2.4 * a0 / 16.0)
    cs_long, why_long = site.seismic_coefficient(4.0)
    assert cs_long == pytest.approx(site.minimum_coefficient()) and "minimum" in why_long
    assert site.cu == pytest.approx(1.4)  # Fas a0 = 0.48 >= 0.3
    assert nscm.upper_limit_coefficient(0.125, 1.0) == pytest.approx(1.65)
    assert site.vertical_load_factor() == pytest.approx(0.2 * 0.36667 * 1.3)


def test_nscm_approximate_period_and_drift() -> None:
    assert nscm.approximate_period("concrete_mrf", 10.0) == pytest.approx(0.0466 * 10.0**0.9)
    assert nscm.drift_amplification(5.5, 1.3) == pytest.approx(5.5 / 1.3)


# ─────────────────────────── target spectra ───────────────────────────


def test_target_spectrum_rnc07_and_nscm_round_trip_and_case() -> None:
    rnc = TargetSpectrum(id=1, kind="rnc07", a0=0.3, soil="II", importance_class="B")
    again = TargetSpectrum.model_validate(rnc.model_dump())
    assert again == rnc
    assert rnc.sa_at(0.3)[0] == pytest.approx(1.215)
    case = target_to_case_spectrum(rnc, 7, units=UnitSystem.SI_M_N)
    assert case.periods[-1] == pytest.approx(10.0)
    assert 0.1 in case.periods and 0.6 in case.periods and 2.0 in case.periods
    managua = TargetSpectrum(
        id=2, kind="nscm2021", a0=0.36667, soil="D", importance_class="II", reduction=6.0
    )
    assert managua.sa_at(0.3)[0] == pytest.approx(2.4 * 0.36667 * 1.4 / 6.0)
    with pytest.raises(ValueError, match="site response"):
        TargetSpectrum(id=3, kind="nscm2021", a0=0.36667, soil="E")
    with pytest.raises(ValueError, match="a0"):
        TargetSpectrum(id=4, kind="rnc07", soil="II")


def test_existing_target_spectra_dump_unchanged() -> None:
    """The new fields stay out of a dump that does not use them (byte-identical files)."""
    dump = TargetSpectrum(id=1, kind="tbdy2018", sds=1.0, sd1=0.5).model_dump()
    for key in ("a0", "zone", "soil", "importance_class", "reduction", "regularity"):
        assert key not in dump


# ─────────────────────────── equivalent lateral force ───────────────────────────


def _building():  # type: ignore[no-untyped-def]
    from opensees_studio.core import Node, Project, Storey

    project = Project(ndm=3, ndf=6)
    nid = 1
    masses = {2.7: 131.57, 5.4: 131.57, 8.1: 131.57, 10.8: 101.95}
    project.nodes.append(Node(id=nid, coords=(0.0, 0.0, 0.0)))
    for z, w in masses.items():
        nid += 1
        m = w / gravity(project.meta.units)
        project.nodes.append(Node(id=nid, coords=(0.0, 0.0, z), mass=(m, m, 0.0, 0.0, 0.0, 0.0)))
    project.storeys = [Storey(id=i + 1, name=f"N{i + 1}", elevation=z) for i, z in enumerate(masses)]
    return project


def test_elf_rnc07_reproduces_anexo_d_example_iii() -> None:
    from opensees_studio.core.equivalent_lateral import ElfParameters, equivalent_lateral_forces

    project = _building()
    params = ElfParameters(
        code="rnc07", period=0.4, sds=0.0, sd1=0.0, r=2.0, a0=0.30, soil="II", zone="C"
    )
    result = equivalent_lateral_forces(project, 0, params)
    assert result.coefficient == pytest.approx(0.45)
    forces = [level.force for level in result.levels]
    assert forces[::-1] == pytest.approx([76.13, 73.68, 49.12, 24.56], abs=0.02)


def test_elf_nscm_caps_the_period_and_warns_on_height() -> None:
    from opensees_studio.core.equivalent_lateral import ElfParameters, equivalent_lateral_forces

    project = _building()
    params = ElfParameters(
        code="nscm2021",
        period=1.5,
        sds=0.0,
        sd1=0.0,
        r=8.0,
        a0=0.36667,
        soil="C",
        importance_class="II",
        approximate_period=0.4,
    )
    result = equivalent_lateral_forces(project, 0, params)
    site = nscm.NscmSite(a0=0.36667, site_class="C", r0=8.0)
    expected, _why = site.seismic_coefficient(1.4 * 0.4)
    assert result.coefficient == pytest.approx(expected)
    assert any("Cu·Ta" in note for note in result.notes)
    assert not any("static method" in note for note in result.notes)  # 10.8 m <= 12 m
    irregular = equivalent_lateral_forces(
        project, 0, ElfParameters(**{**params.__dict__, "regularity": "irregular_one"})
    )
    assert any("6 m" in note for note in irregular.notes)


def test_drift_presets_follow_rnc07_art_34_and_nscm_table_5_5_1() -> None:
    from opensees_studio.core.design.settings import DRIFT_PRESETS

    rnc = {k: v for k, v in DRIFT_PRESETS.items() if k.startswith("RNC-07")}
    assert (0.002, rnc07.service_drift_factor(2.0, 0.5)) in rnc.values()
    assert (0.030, rnc07.collapse_drift_factor(4.0)) in rnc.values()
    assert rnc07.RNC07_COLLAPSE_DRIFT["Ductile RC frames (Q = 3 or 4)"] == 0.030
    nscm_presets = {k: v for k, v in DRIFT_PRESETS.items() if k.startswith("NSCM")}
    assert nscm_presets["NSCM, special RC moment frame (0.020 h, Cd = 5.5)"] == (
        0.020,
        nscm.drift_amplification(5.5, 1.0),
    )
