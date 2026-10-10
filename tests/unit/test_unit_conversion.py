"""Display-unit conversion: factors, labels, and the model's system staying put.

Reference values are exact definitions, not copies of the implementation:
1 in = 25.4 mm, 1 ft = 0.3048 m (both exact by definition), and
1 lbf = 4.4482216152605 N (NIST SP 811). Everything derives from those.
"""

from __future__ import annotations

import numpy as np
import pytest

from opensees_studio.core import Project, ProjectMeta, UnitConverter, UnitSystem
from opensees_studio.core.project import ProjectMeta as Meta
from opensees_studio.core.units import (
    force_scale,
    length_scale,
    moment_scale,
    stress_scale,
)

IN_M = 0.0254
FT_M = 0.3048
LBF_N = 4.4482216152605
KIP_N = 1000.0 * LBF_N


def test_no_display_system_means_the_model_s_own() -> None:
    conv = UnitConverter.of(ProjectMeta())
    assert conv.display is None
    assert conv.target is UnitSystem.SI_M_N
    assert conv.is_identity
    assert (conv.length, conv.force, conv.moment, conv.stress) == (1.0, 1.0, 1.0, 1.0)
    assert conv.labels.length == "m"


def test_a_missing_meta_is_the_identity() -> None:
    """A view can call ``of(None)`` before a project exists and still draw."""
    conv = UnitConverter.of(None)
    assert conv.is_identity
    assert conv.factor("force") == 1.0


def test_a_missing_display_attribute_is_the_identity() -> None:
    """Files written before ``display_units`` existed carry only ``units``."""

    class Legacy:
        units = UnitSystem.US_IN_KIP

    conv = UnitConverter.of(Legacy())
    assert conv.display is None
    assert conv.is_identity
    assert conv.labels.force == "kip"


def test_length_factors_follow_the_exact_definitions() -> None:
    assert length_scale(UnitSystem.SI_M_N, UnitSystem.SI_MM_N) == 1000.0
    assert length_scale(UnitSystem.SI_M_N, UnitSystem.US_IN_KIP) == pytest.approx(1.0 / IN_M)
    assert length_scale(UnitSystem.SI_M_N, UnitSystem.US_FT_KIP) == pytest.approx(1.0 / FT_M)
    assert length_scale(UnitSystem.US_IN_KIP, UnitSystem.SI_MM_N) == pytest.approx(IN_M * 1000.0)


def test_force_moment_and_stress_factors_derive_from_force_and_length() -> None:
    n_to_kip = 1.0 / KIP_N
    assert force_scale(UnitSystem.SI_M_N, UnitSystem.US_IN_KIP) == pytest.approx(n_to_kip)
    # 1 N·m = 1/LBF_N lbf·in = 1/(1000·LBF_N) kip·in — the published 8.8507e-3.
    assert moment_scale(UnitSystem.SI_M_N, UnitSystem.US_IN_KIP) == pytest.approx(
        n_to_kip / IN_M,
    )
    assert moment_scale(UnitSystem.SI_M_N, UnitSystem.US_IN_KIP) == pytest.approx(
        8.850745791327184e-3,
    )
    # 1 Pa = 1/(1000·psi) ksi, and 1 psi = 1 lbf/in² = 6894.757… Pa.
    psi_pa = LBF_N / IN_M**2
    assert stress_scale(UnitSystem.SI_M_N, UnitSystem.US_IN_KIP) == pytest.approx(
        1.0 / (psi_pa * 1000.0),
    )
    # The published 1.4503774e-4 psi / 1.4503774e-7 ksi.
    assert stress_scale(UnitSystem.SI_M_N, UnitSystem.US_IN_KIP) == pytest.approx(
        1.4503773773020922e-7,
    )
    # And the reverse direction really is the reciprocal.
    assert force_scale(UnitSystem.US_IN_KIP, UnitSystem.SI_M_N) == pytest.approx(KIP_N)


def test_conversion_is_a_round_trip() -> None:
    """SI → US → SI returns the same number to the last bit or so."""
    there = UnitConverter(UnitSystem.SI_M_N, UnitSystem.US_FT_KIP)
    back = UnitConverter(UnitSystem.US_FT_KIP, UnitSystem.SI_M_N)
    for value in (1.0, 1234.5, 9.81e-6):
        assert back.apply("moment", there.apply("moment", value)) == pytest.approx(value)


def test_kinds_name_the_quantity_not_the_factor() -> None:
    conv = UnitConverter(UnitSystem.SI_M_N, UnitSystem.SI_MM_N)
    # A displacement, a velocity and an acceleration are all lengths per a power
    # of time, and only the length unit changes between the two systems.
    assert conv.factor("length") == 1000.0
    assert conv.factor("velocity") == 1000.0
    assert conv.factor("accel") == 1000.0
    # Curvature is 1/length, so it converts the other way: 1/m → 0.001/mm.
    assert conv.factor("curvature") == pytest.approx(1e-3)
    assert conv.factor("rotation") == 1.0
    with pytest.raises(KeyError):
        conv.factor("temperature")


def test_force_and_moment_are_different_factors() -> None:
    conv = UnitConverter(UnitSystem.SI_M_N, UnitSystem.US_IN_KIP)
    assert conv.factor("moment") == pytest.approx(conv.factor("force") * conv.factor("length"))
    assert conv.factor("stress") == pytest.approx(
        conv.factor("force") / conv.factor("length") ** 2,
    )


def test_apply_handles_arrays_and_leaves_them_alone_when_identical() -> None:
    conv = UnitConverter(UnitSystem.SI_M_N, UnitSystem.SI_MM_N)
    values = np.array([1.0, -2.5, 0.0])
    assert np.array_equal(conv.apply("length", values), values * 1000.0)
    identity = UnitConverter(UnitSystem.SI_M_N)
    assert identity.apply("length", values) is values


def test_display_units_do_not_touch_the_model_numbers() -> None:
    """The whole point: a display change never rewrites what was typed."""
    project = Project(meta=Meta(units=UnitSystem.SI_M_N))
    project.meta.display_units = UnitSystem.US_IN_KIP
    assert project.meta.units is UnitSystem.SI_M_N
    conv = UnitConverter.of(project.meta)
    assert not conv.is_identity
    assert conv.labels.force == "kip"
    assert conv.force == pytest.approx(1.0 / KIP_N)


def test_display_units_are_left_out_of_a_dump_until_they_are_used() -> None:
    """An untouched project serializes exactly as it did before the field existed."""
    plain = ProjectMeta().model_dump_json()
    assert "display_units" not in plain
    assert '"units":"SI (m, N, kg, s, Pa)"' in plain

    with_display = ProjectMeta(display_units=UnitSystem.US_FT_KIP).model_dump_json()
    assert '"display_units":"US (ft, kip, slug, s, ksf)"' in with_display


def test_display_units_survive_a_round_trip_through_json() -> None:
    original = ProjectMeta(units=UnitSystem.US_IN_KIP, display_units=UnitSystem.SI_M_N)
    restored = ProjectMeta.model_validate_json(original.model_dump_json())
    assert restored.units is UnitSystem.US_IN_KIP
    assert restored.display_units is UnitSystem.SI_M_N
    # Same value shown in the model's own system again.
    back = ProjectMeta.model_validate_json(ProjectMeta().model_dump_json())
    assert back.display_units is None
