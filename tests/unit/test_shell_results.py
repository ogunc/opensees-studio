"""Principal values and directions of a shell's resultants, against hand cases.

Everything here can be checked with a pencil: Mohr's circle has closed forms, the
invariants are exact, and a tensor built from known principal values at a known
angle has to come back as those values at that angle.
"""

from __future__ import annotations

import math
from dataclasses import FrozenInstanceError

import pytest

from opensees_studio.core.shell_results import (
    FIELD_NAMES,
    PRINCIPAL_NAMES,
    RESULTANT_NAMES,
    Principal,
    bending_principal,
    field_label,
    field_value,
    membrane_principal,
    named_values,
    principal,
    principal_angle,
    transverse_shear,
)

#: A resultant row with recognisable numbers in every slot.
ROW = [1000.0, 200.0, 300.0, 4000.0, 1000.0, -500.0, 50.0, -120.0]


# ───────────────────────── the order is the contract ─────────────────────────
def test_the_eight_names_are_in_the_order_opensees_reports() -> None:
    assert RESULTANT_NAMES == ("N11", "N22", "N12", "M11", "M22", "M12", "V13", "V23")
    named = named_values(ROW)
    assert named["N11"] == 1000.0
    assert named["N22"] == 200.0
    assert named["N12"] == 300.0
    assert named["M11"] == 4000.0
    assert named["M12"] == -500.0
    assert named["V23"] == -120.0


def test_a_row_of_the_wrong_length_is_refused() -> None:
    with pytest.raises(ValueError, match="eight"):
        named_values([1.0, 2.0, 3.0])


# ───────────────────────── Mohr's circle, by hand ─────────────────────────
def test_uniaxial_is_already_principal() -> None:
    result = principal(1000.0, 0.0, 0.0)
    assert (result.major, result.minor) == (1000.0, 0.0)
    assert result.angle_deg == pytest.approx(0.0)
    assert result.max_shear == pytest.approx(500.0)


def test_the_major_value_is_the_algebraically_larger_one() -> None:
    """Under compression the major principal value is the one nearer zero."""
    result = principal(-1000.0, 0.0, 0.0)
    assert result.major == pytest.approx(0.0)
    assert result.minor == pytest.approx(-1000.0)
    # The major (larger) value is zero and its direction is the *other* axis.
    assert abs(result.angle_deg) == pytest.approx(90.0)


def test_pure_shear_sits_at_forty_five_degrees() -> None:
    tension = principal(0.0, 0.0, 500.0)
    assert tension.major == pytest.approx(500.0)
    assert tension.minor == pytest.approx(-500.0)
    assert tension.angle_deg == pytest.approx(45.0)

    compression = principal(0.0, 0.0, -500.0)
    assert compression.major == pytest.approx(500.0)
    assert compression.minor == pytest.approx(-500.0)
    assert compression.angle_deg == pytest.approx(-45.0)


def test_equal_normals_have_no_unique_direction() -> None:
    result = principal(300.0, 300.0, 0.0)
    assert result.major == pytest.approx(300.0)
    assert result.minor == pytest.approx(300.0)
    assert result.is_isotropic
    # Not unique — the convention reports 0 for a pure equibiaxial state, and the
    # flag is what a view should trust.
    assert result.angle_deg == pytest.approx(0.0)
    assert principal(300.0, 300.0, 50.0).is_isotropic is False
    assert principal(300.0, 300.0, 50.0).angle_deg == pytest.approx(45.0)


def test_a_known_tensor_comes_back_at_its_own_angle() -> None:
    """Build the tensor from (major, minor, θ) and recover all three."""
    major, minor, theta = 1800.0, -400.0, 30.0
    radians = math.radians(theta)
    a = major * math.cos(radians) ** 2 + minor * math.sin(radians) ** 2
    b = major * math.sin(radians) ** 2 + minor * math.cos(radians) ** 2
    ab = (major - minor) * math.sin(radians) * math.cos(radians)

    result = principal(a, b, ab)
    assert result.major == pytest.approx(major)
    assert result.minor == pytest.approx(minor)
    assert result.angle_deg == pytest.approx(theta)


@pytest.mark.parametrize(
    ("a", "b", "ab"),
    [
        (1000.0, 200.0, 300.0),
        (-500.0, -900.0, 120.0),
        (0.0, 0.0, -250.0),
        (750.0, 750.0, 0.0),
        (1234.5, -678.9, 45.6),
    ],
)
def test_the_invariants_hold(a: float, b: float, ab: float) -> None:
    """Trace and determinant are what a rotation cannot change."""
    result = principal(a, b, ab)
    assert result.major + result.minor == pytest.approx(a + b)
    assert result.major * result.minor == pytest.approx(a * b - ab * ab)
    assert result.major - result.minor == pytest.approx(
        2.0 * math.hypot(0.5 * (a - b), ab),
    )
    assert -90.0 <= result.angle_deg < 90.0


def test_rotating_the_axes_leaves_the_principal_values_alone() -> None:
    """The point of a principal contour: it does not care about the element frame."""
    base = principal(1000.0, 200.0, 300.0)
    for theta in (0.0, 15.0, 45.0, -30.0, 80.0):
        radians = math.radians(theta)
        cos, sin = math.cos(radians), math.sin(radians)
        # Rotate the tensor by θ and take its principals again.
        a = 1000.0 * cos**2 + 200.0 * sin**2 + 2 * 300.0 * sin * cos
        b = 1000.0 * sin**2 + 200.0 * cos**2 - 2 * 300.0 * sin * cos
        ab = (200.0 - 1000.0) * sin * cos + 300.0 * (cos**2 - sin**2)
        rotated = principal(a, b, ab)
        assert rotated.major == pytest.approx(base.major)
        assert rotated.minor == pytest.approx(base.minor)


# ───────────────────────── the fields the view offers ─────────────────────────
def test_membrane_and_bending_principals_come_from_their_own_slots() -> None:
    membrane = membrane_principal(ROW)
    bending = bending_principal(ROW)
    expected_membrane = principal(1000.0, 200.0, 300.0)
    expected_bending = principal(4000.0, 1000.0, -500.0)
    assert (membrane.major, membrane.minor) == pytest.approx(
        (expected_membrane.major, expected_membrane.minor),
    )
    assert (bending.major, bending.minor) == pytest.approx(
        (expected_bending.major, expected_bending.minor),
    )
    # And the bending principals must not be contaminated by the membrane ones.
    assert bending.major != pytest.approx(membrane.major)


def test_transverse_shear_is_a_magnitude() -> None:
    assert transverse_shear(ROW) == pytest.approx(math.hypot(50.0, -120.0))
    assert transverse_shear(ROW) == pytest.approx(130.0)


def test_every_field_name_resolves_and_is_labelled() -> None:
    for name in FIELD_NAMES:
        value = field_value(ROW, name)
        assert isinstance(value, float)
        assert field_label(name)
    assert set(FIELD_NAMES) == set(RESULTANT_NAMES) | set(PRINCIPAL_NAMES)
    with pytest.raises(ValueError, match="unknown shell field"):
        field_value(ROW, "N99")


def test_a_principal_field_is_a_principal_value_not_a_component() -> None:
    membrane = membrane_principal(ROW)
    assert field_value(ROW, "N1") == pytest.approx(membrane.major)
    assert field_value(ROW, "N2") == pytest.approx(membrane.minor)
    assert field_value(ROW, "N1") != pytest.approx(ROW[0])
    bending = bending_principal(ROW)
    assert field_value(ROW, "M1") == pytest.approx(bending.major)
    assert field_value(ROW, "M2") == pytest.approx(bending.minor)


def test_a_principal_direction_is_reported_in_degrees() -> None:
    shear_row = [0.0, 0.0, 500.0, 0.0, 0.0, -500.0, 0.0, 0.0]
    assert principal_angle(shear_row, "N1") == pytest.approx(45.0)
    assert principal_angle(shear_row, "M1") == pytest.approx(-45.0)
    with pytest.raises(ValueError, match="no principal direction"):
        principal_angle(shear_row, "V13")


def test_the_principal_dataclass_is_frozen_and_cheap() -> None:
    result = Principal(major=10.0, minor=-10.0, angle_deg=30.0)
    assert result.max_shear == pytest.approx(10.0)
    with pytest.raises(FrozenInstanceError):
        result.major = 5.0  # type: ignore[misc]
