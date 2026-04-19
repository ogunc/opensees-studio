"""Unit system metadata + display labels.

OpenSees is unit-agnostic: it never converts. The engineer picks a
consistent system (SI, kip-in, etc.) and sticks to it. We don't
auto-convert either — we just record the choice in project metadata
and use it to label axes / tables so users see the right ticks and
so analysts opening a foreign file know what they're looking at.

The :func:`labels_for` helper returns an :class:`UnitLabels` bundle
matching SAP2000's "Set Program Default Display Units" semantics:
length / force / moment / stress / curvature / rotation labels, all
driven by :class:`UnitSystem` enum.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class UnitSystem(str, Enum):
    """Consistent unit systems supported by the application."""

    SI_M_N = "SI (m, N, kg, s, Pa)"
    """Length: m, Force: N, Mass: kg, Time: s, Stress: Pa."""

    SI_MM_N = "SI (mm, N, t, s, MPa)"
    """Length: mm, Force: N, Mass: t, Time: s, Stress: MPa."""

    US_FT_KIP = "US (ft, kip, slug, s, ksf)"
    """Length: ft, Force: kip, Mass: slug, Time: s, Stress: ksf."""

    US_IN_KIP = "US (in, kip, kip·s²/in, s, ksi)"
    """Length: in, Force: kip, Mass: kip·s²/in, Time: s, Stress: ksi."""


@dataclass(frozen=True)
class UnitLabels:
    """Display strings for each basic quantity in a unit system.

    Consumed by result views (pushover curve, diagrams, tables) to
    label axes without hard-coding any particular set of units.
    """

    length: str           # "m", "mm", "in", "ft"
    force: str            # "N", "kip"
    moment: str           # "N·m", "kip·in"
    stress: str           # "Pa", "MPa", "ksi", "ksf"
    curvature: str        # "1/m", "1/in", …
    rotation: str         # "rad" (always, no unit variants in practice)


_LABELS: dict[UnitSystem, UnitLabels] = {
    UnitSystem.SI_M_N: UnitLabels(
        length="m", force="N", moment="N·m",
        stress="Pa", curvature="1/m", rotation="rad",
    ),
    UnitSystem.SI_MM_N: UnitLabels(
        length="mm", force="N", moment="N·mm",
        stress="MPa", curvature="1/mm", rotation="rad",
    ),
    UnitSystem.US_FT_KIP: UnitLabels(
        length="ft", force="kip", moment="kip·ft",
        stress="ksf", curvature="1/ft", rotation="rad",
    ),
    UnitSystem.US_IN_KIP: UnitLabels(
        length="in", force="kip", moment="kip·in",
        stress="ksi", curvature="1/in", rotation="rad",
    ),
}


def labels_for(units: UnitSystem) -> UnitLabels:
    """Return the label bundle for the given unit system."""
    return _LABELS[units]
