"""Structural steel grades for the AISC member check, and the default grade of each shape family.

A grade gives the specified minimum yield and tensile stress (``Fy``, ``Fu``) and
the ratio of expected to specified yield stress ``Ry`` of AISC 341-22 Table A3.1.
ASTM A500 and A53 specify a different ``Fy`` for round sections than for
rectangular ones, so a grade may carry a second pair for round HSS and pipe.

The defaults per family are the preferred materials of the AISC Steel
Construction Manual (16th ed.) Table 2-4: A992 for W shapes, A572 Grade 50 for
M and HP, A36 for S, channels and angles, A500 Grade C for HSS and A53 Grade B
for pipe. A tee takes the grade of the shape it is cut from.

Stresses here are in ksi; :func:`grade_stresses` converts them to a project's
units. No Qt, no OpenSees.
"""

from __future__ import annotations

from dataclasses import dataclass

from opensees_studio.core.units import UnitSystem, stress_scale


@dataclass(frozen=True)
class SteelGrade:
    """One ASTM grade: what the check needs from it, in ksi."""

    key: str
    label: str
    fy: float
    fu: float
    ry: float
    fy_round: float | None = None
    """``Fy`` of round HSS and pipe when the specification gives a different one."""
    fu_round: float | None = None


STEEL_GRADES: dict[str, SteelGrade] = {
    grade.key: grade
    for grade in (
        SteelGrade("A36", "ASTM A36", fy=36.0, fu=58.0, ry=1.5),
        SteelGrade("A572-50", "ASTM A572 Gr. 50", fy=50.0, fu=65.0, ry=1.1),
        SteelGrade("A992", "ASTM A992", fy=50.0, fu=65.0, ry=1.1),
        SteelGrade("A588-50", "ASTM A588 Gr. 50", fy=50.0, fu=70.0, ry=1.1),
        SteelGrade(
            "A500-B", "ASTM A500 Gr. B", fy=46.0, fu=58.0, ry=1.4, fy_round=42.0, fu_round=58.0
        ),
        SteelGrade(
            "A500-C", "ASTM A500 Gr. C", fy=50.0, fu=62.0, ry=1.3, fy_round=46.0, fu_round=62.0
        ),
        SteelGrade("A1085", "ASTM A1085", fy=50.0, fu=65.0, ry=1.25),
        SteelGrade("A53-B", "ASTM A53 Gr. B", fy=35.0, fu=60.0, ry=1.6),
    )
}
"""Every grade a project can choose, by key."""

ROUND_FAMILIES = frozenset({"HSS_R", "PIPE"})
"""Families that take a grade's round-section stresses."""

DEFAULT_GRADES: dict[str, str] = {
    "W": "A992",
    "M": "A572-50",
    "S": "A36",
    "HP": "A572-50",
    "WT": "A992",
    "MT": "A572-50",
    "ST": "A36",
    "C": "A36",
    "MC": "A36",
    "L": "A36",
    "HSS": "A500-C",
    "HSS_R": "A500-C",
    "PIPE": "A53-B",
    "BU": "A572-50",
}
"""AISC Manual Table 2-4 preferred grade of each family the check covers (BU: plates
of a built-up shape, A572 Gr. 50 as for welded girders and columns)."""

FAMILY_LABELS: dict[str, str] = {
    "W": "W shapes",
    "M": "M shapes",
    "S": "S shapes",
    "HP": "HP shapes",
    "WT": "WT tees",
    "MT": "MT tees",
    "ST": "ST tees",
    "C": "C channels",
    "MC": "MC channels",
    "L": "Angles",
    "HSS": "Rectangular HSS",
    "HSS_R": "Round HSS",
    "PIPE": "Pipe",
    "BU": "Built-up I (welded plates)",
}


def grade_stresses(key: str, family: str, units: UnitSystem) -> tuple[float, float]:
    """``(Fy, Fu)`` of grade ``key`` for a shape of ``family``, in ``units``.

    Raises:
        KeyError: an unknown grade.
    """
    grade = STEEL_GRADES[key]
    fy, fu = grade.fy, grade.fu
    if family in ROUND_FAMILIES and grade.fy_round is not None:
        fy = grade.fy_round
        fu = grade.fu_round if grade.fu_round is not None else fu
    scale = stress_scale(UnitSystem.US_IN_KIP, units)
    return fy * scale, fu * scale
