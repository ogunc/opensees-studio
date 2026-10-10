"""A shell's section stress resultants: their names, and their principal values.

OpenSees reports eight resultants per gauss point, and the runner stores their
average per element (see `reports/SHELL_CONTOURS_PLAN_2026-10-09.md` for how the
order was pinned against a uniform tension of 2000 N/m):

===========  ==============  =========================================
slot         name            meaning
===========  ==============  =========================================
0            ``N11``         membrane force along the element's 1-axis
1            ``N22``         membrane force along the 2-axis
2            ``N12``         membrane shear
3            ``M11``         bending moment about the 2-axis
4            ``M22``         bending moment about the 1-axis
5            ``M12``         twisting moment
6            ``V13``         transverse shear across the 1-axis
7            ``V23``         transverse shear across the 2-axis
===========  ==============  =========================================

All eight are per unit length: force per length for the membrane and shear terms
(N/m), moment per length for the bending ones (N·m/m, which is a force). The
three in-plane components form a symmetric 2×2 tensor whose principal values and
directions are what a contour view should show, and the same is true of the three
bending components.

The principal values come from Mohr's circle, which needs no tensor library and
no frame: they are invariant, so a contour of ``N1`` means the same thing
whichever way the element's local axes happen to point. The *directions* are
given relative to the element's own axes, in degrees, and are what the glyphs in
the view are drawn from.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass

#: The eight resultants, in the order OpenSees reports them.
RESULTANT_NAMES: tuple[str, ...] = (
    "N11",
    "N22",
    "N12",
    "M11",
    "M22",
    "M12",
    "V13",
    "V23",
)

#: What each one is called in a picker or a colour-bar title.
RESULTANT_LABELS: dict[str, str] = {
    "N11": "N11 — membrane, along 1",
    "N22": "N22 — membrane, along 2",
    "N12": "N12 — membrane shear",
    "M11": "M11 — bending, about 2",
    "M22": "M22 — bending, about 1",
    "M12": "M12 — twisting",
    "V13": "V13 — transverse shear",
    "V23": "V23 — transverse shear",
}

#: The unit of each field, for a colour bar or a table header.
RESULTANT_UNITS: dict[str, str] = {
    "N11": "force/length",
    "N22": "force/length",
    "N12": "force/length",
    "M11": "moment/length",
    "M22": "moment/length",
    "M12": "moment/length",
    "V13": "force/length",
    "V23": "force/length",
    "N1": "force/length",
    "N2": "force/length",
    "M1": "moment/length",
    "M2": "moment/length",
    "V": "force/length",
}

#: The principal fields the view offers, on top of the eight components.
PRINCIPAL_NAMES: tuple[str, ...] = ("N1", "N2", "M1", "M2")

#: Every field a contour can show from the resultants alone.
FIELD_NAMES: tuple[str, ...] = RESULTANT_NAMES + PRINCIPAL_NAMES

_MINOR_PRECISION = 1e-12
"""Below this, a component is numerical noise and the angle is not meaningful."""


@dataclass(frozen=True)
class Principal:
    """The principal values of one symmetric 2×2 tensor, and their direction."""

    major: float
    """The algebraically larger principal value (tension positive)."""
    minor: float
    angle_deg: float
    """Direction of ``major`` from the local 1-axis towards the 2-axis, in
    degrees, in ``[-90, 90)``."""

    @property
    def max_shear(self) -> float:
        """The in-plane shear on the 45° plane, ``(major - minor) / 2``."""
        return 0.5 * (self.major - self.minor)

    @property
    def is_isotropic(self) -> bool:
        """True when the two principal values coincide: every direction is principal."""
        return abs(self.major - self.minor) <= _MINOR_PRECISION * max(
            1.0,
            abs(self.major),
        )


def principal(a: float, b: float, ab: float) -> Principal:
    """Principal values and direction of the symmetric tensor ``[[a, ab], [ab, b]]``.

    Mohr's circle: centre ``(a+b)/2``, radius ``√(((a-b)/2)² + ab²)``, and the
    major direction at ``½ atan2(2ab, a - b)``.

    Hand checks that pin the conventions (all in `tests/unit/test_shell_results.py`):
    uniaxial ``(1000, 0, 0)`` gives ``(1000, 0, 0°)``; pure shear ``(0, 0, 500)``
    gives ``(500, -500, +45°)`` and ``(0, 0, -500)`` gives the same values at
    ``-45°``; uniaxial *compression* ``(-1000, 0, 0)`` gives ``(0, -1000, -90°)``,
    because the major value sits on the other axis. Equal normals with no shear
    give angle 0 — the direction is not unique, which is what
    :attr:`Principal.is_isotropic` reports.
    """
    mean = 0.5 * (a + b)
    radius = math.hypot(0.5 * (a - b), ab)
    angle = 0.5 * math.degrees(math.atan2(2.0 * ab, a - b))
    # atan2 lands in (-180, 180], so the angle lands in (-90, 90]; -90 and +90
    # are the same direction, and the canonical range reports it as -90.
    if angle >= 90.0:
        angle -= 180.0
    return Principal(major=mean + radius, minor=mean - radius, angle_deg=angle)


def named_values(values: Iterable[float]) -> dict[str, float]:
    """The eight resultants of one element as a ``{name: value}`` mapping.

    Raises:
        ValueError: if the vector does not hold exactly eight resultants.
    """
    sequence = [float(v) for v in values]
    if len(sequence) != len(RESULTANT_NAMES):
        raise ValueError(f"a shell resultant row holds eight values, got {len(sequence)}")
    return dict(zip(RESULTANT_NAMES, sequence, strict=True))


def membrane_principal(values: Iterable[float]) -> Principal:
    """Principal membrane forces: ``N1``, ``N2`` and the direction of ``N1``."""
    named = named_values(values)
    return principal(named["N11"], named["N22"], named["N12"])


def bending_principal(values: Iterable[float]) -> Principal:
    """Principal bending moments: ``M1``, ``M2`` and the direction of ``M1``."""
    named = named_values(values)
    return principal(named["M11"], named["M22"], named["M12"])


def transverse_shear(values: Iterable[float]) -> float:
    """The magnitude of the transverse shear, ``√(V13² + V23²)``."""
    named = named_values(values)
    return math.hypot(named["V13"], named["V23"])


def field_value(values: Iterable[float], name: str) -> float:
    """One contour field out of a resultant row.

    ``name`` is a component (``"N11"`` …) or a principal (``"N1"``, ``"N2"``,
    ``"M1"``, ``"M2"``).
    """
    if name in PRINCIPAL_NAMES:
        principal_values = (
            membrane_principal(values) if name[0] == "N" else bending_principal(values)
        )
        return principal_values.major if name.endswith("1") else principal_values.minor
    if name == "V":
        return transverse_shear(values)
    if name not in RESULTANT_NAMES:
        raise ValueError(f"unknown shell field {name!r}")
    return named_values(values)[name]


def field_label(name: str) -> str:
    """A human label for a field, for a picker entry or a colour-bar title."""
    if name in PRINCIPAL_NAMES:
        which = "major" if name.endswith("1") else "minor"
        family = "membrane" if name[0] == "N" else "bending"
        return f"{name} — {which} principal {family}"
    if name == "V":
        return "V — transverse shear"
    return RESULTANT_LABELS[name]


def principal_angle(values: Iterable[float], name: str = "N1") -> float:
    """The direction of a principal field, in degrees from the element's 1-axis."""
    if name.startswith("N"):
        return membrane_principal(values).angle_deg
    if name.startswith("M"):
        return bending_principal(values).angle_deg
    raise ValueError(f"{name!r} has no principal direction")
