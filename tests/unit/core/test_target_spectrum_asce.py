"""The ASCE 7-16 target spectrum on the model, and turning it into a case table.

Two halves: the ``TargetSpectrum`` of kind ``asce7_16`` (which is what the
Ground Motions dialog builds and the target plot draws) and
``target_to_case_spectrum`` (which is what a response-spectrum *case* reads).
The tables and branches of the standard itself are pinned in
``tests/unit/core/test_asce7.py``; what is checked here is the model around them.
"""

from __future__ import annotations

import numpy as np
import pytest
from pydantic import ValidationError

from opensees_studio.core import (
    ResponseSpectrum,
    TargetSpectrum,
    UnitSystem,
    asce7_design_spectrum,
)
from opensees_studio.core.project import Project
from opensees_studio.core.target_spectrum import target_to_case_spectrum

G = 9.80665
"""Standard gravity in m/s²: SI metres is the unit system used below."""


def _asce_from_site(**overrides: object) -> TargetSpectrum:
    fields: dict[str, object] = {
        "id": 1,
        "kind": "asce7_16",
        "ss": 1.0,
        "s1": 0.4,
        "asce_site_class": "C",
        "tl": 8.0,
    }
    fields.update(overrides)
    return TargetSpectrum(**fields)  # type: ignore[arg-type]


# ──────────────────────────── the model ────────────────────────────
def test_the_spectrum_can_be_built_from_the_site() -> None:
    target = _asce_from_site()

    assert target.from_site
    assert (target.fa, target.fv) == (1.2, 1.5)  # Table 11.4-1 / 11.4-2 at Ss=1, S1=0.4
    assert target.sds == pytest.approx(0.8)
    assert target.sd1 == pytest.approx(0.4)
    assert "ASCE 7-16" in target.describe()
    assert "site class C" in target.describe()


def test_the_spectrum_can_be_built_from_sds_and_sd1_the_engineer_already_has() -> None:
    target = TargetSpectrum(id=2, kind="asce7_16", sds=0.8, sd1=0.4, tl=8.0)

    assert not target.from_site
    assert target.corner_periods() == (pytest.approx(0.1), pytest.approx(0.5), 8.0)
    assert "SDS=0.8 g" in target.describe()


def test_the_long_period_transition_defaults_to_the_usual_map_value() -> None:
    assert TargetSpectrum(id=3, kind="asce7_16", sds=0.8, sd1=0.4).long_period_transition == 8.0


def test_sa_at_is_the_standard_spectrum() -> None:
    target = _asce_from_site()
    periods = np.array([0.0, 0.05, 0.3, 1.0, 8.0, 16.0])

    assert target.sa_at(periods) == pytest.approx(asce7_design_spectrum(periods, 0.8, 0.4, 8.0))


def test_a_class_f_site_is_refused_by_name() -> None:
    with pytest.raises(ValidationError, match="site-specific"):
        _asce_from_site(asce_site_class="F")


def test_a_default_class_d_uses_the_11_4_3_floor() -> None:
    assumed = _asce_from_site(ss=1.5, s1=0.5, asce_site_class="D", asce_site_class_is_default=True)
    determined = _asce_from_site(ss=1.5, s1=0.5, asce_site_class="D")

    assert assumed.fa == 1.2 and determined.fa == 1.0
    assert assumed.sds > determined.sds
    assert "assumed" in assumed.describe()


def test_sds_given_next_to_the_site_values_must_agree() -> None:
    with pytest.raises(ValidationError, match="does not match"):
        _asce_from_site(sds=0.5)


def test_a_spectrum_without_values_is_refused() -> None:
    with pytest.raises(ValidationError, match="needs SDS and SD1"):
        TargetSpectrum(id=4, kind="asce7_16")


def test_a_tl_that_does_not_exceed_ts_is_refused() -> None:
    with pytest.raises(ValidationError, match="must exceed Ts"):
        TargetSpectrum(id=5, kind="asce7_16", sds=0.8, sd1=0.4, tl=0.4)


# ──────────────────────────── the case table ────────────────────────────
def test_a_code_spectrum_becomes_a_tabulated_case_spectrum() -> None:
    target = _asce_from_site()

    spectrum = target_to_case_spectrum(target, 7, units=UnitSystem.SI_M_N, name="ASCE C")

    assert isinstance(spectrum, ResponseSpectrum)
    assert (spectrum.id, spectrum.name) == (7, "ASCE C")
    assert spectrum.periods == sorted(spectrum.periods)
    assert spectrum.periods[0] > 0.0  # a ResponseSpectrum requires strictly positive
    assert spectrum.periods[-1] == pytest.approx(8.0)  # up to TL
    assert max(spectrum.accelerations) == pytest.approx(0.8 * G, rel=1e-3)


def test_the_table_follows_the_curve_within_a_twentieth_of_a_percent() -> None:
    """The case interpolates linearly, so the sampling has to be fine enough."""
    target = _asce_from_site()
    spectrum = target_to_case_spectrum(target, 1, units=UnitSystem.SI_M_N)

    periods = np.linspace(0.002, target.long_period_transition, 3000)
    exact = target.sa_at(periods) * G
    interpolated = np.interp(periods, spectrum.periods, spectrum.accelerations)
    error = np.max(np.abs(interpolated - exact) / np.maximum(exact, 1e-12))

    assert error < 0.0006


def test_the_corner_periods_are_in_the_table() -> None:
    """They are where the curve changes; missing one costs a percent at that mode."""
    target = _asce_from_site()
    spectrum = target_to_case_spectrum(target, 1, units=UnitSystem.SI_M_N)
    t0, ts, tl = target.corner_periods()

    for corner in (t0, ts, tl):
        assert min(abs(period - corner) for period in spectrum.periods) < 1e-9


def test_the_values_are_in_the_project_units_not_in_g() -> None:
    target = _asce_from_site()

    si = target_to_case_spectrum(target, 1, units=UnitSystem.SI_M_N)
    millimetres = target_to_case_spectrum(target, 2, units=UnitSystem.SI_MM_N)

    assert max(si.accelerations) == pytest.approx(0.8 * 9.80665, rel=1e-3)
    assert max(millimetres.accelerations) == pytest.approx(0.8 * 9806.65, rel=1e-3)


def test_a_user_table_is_copied_point_for_point() -> None:
    """Resampling a table the user typed would change the numbers they meant."""
    target = TargetSpectrum(id=6, kind="user", periods=[0.1, 0.5, 2.0], sa=[0.4, 0.8, 0.2])

    spectrum = target_to_case_spectrum(target, 3, units=UnitSystem.SI_M_N)

    assert spectrum.periods == [0.1, 0.5, 2.0]
    assert spectrum.accelerations == pytest.approx([0.4 * G, 0.8 * G, 0.2 * G])


def test_the_damping_of_the_target_is_carried_over() -> None:
    target = _asce_from_site(damping_ratio=0.02)

    assert target_to_case_spectrum(target, 1, units=UnitSystem.SI_M_N).damping_ratio == 0.02
    assert (
        target_to_case_spectrum(
            target, 1, units=UnitSystem.SI_M_N, damping_ratio=0.05
        ).damping_ratio
        == 0.05
    )


def test_a_tbdy_target_converts_too() -> None:
    """The same path serves the code the application already had."""
    target = TargetSpectrum(id=8, kind="tbdy2018", sds=1.2, sd1=0.4)

    spectrum = target_to_case_spectrum(target, 9, units=UnitSystem.SI_M_N)

    assert spectrum.periods[-1] == pytest.approx(6.0)  # TBDY's own TL
    # The first tabulated point sits on the rising branch: 0.4 SDS at T = 0,
    # climbing to SDS at T0 (just above the base value at 0.001 s).
    assert 0.4 * 1.2 * G <= spectrum.accelerations[0] < 1.2 * G
    assert max(spectrum.accelerations) == pytest.approx(1.2 * G, rel=1e-3)


def test_the_project_hands_out_the_next_case_spectrum_id() -> None:
    project = Project()

    assert project.next_spectrum_id() == 1
    project.spectra.append(ResponseSpectrum(id=4, periods=[0.1, 1.0], accelerations=[1.0, 0.5]))
    assert project.next_spectrum_id() == 5
