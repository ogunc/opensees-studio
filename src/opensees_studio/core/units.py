"""Unit system metadata.

OpenSees is unit-agnostic: it never converts. The engineer must pick a
consistent system (SI: m, kg, s, N, Pa) and stick to it. We don't
auto-convert either; we just record the choice in project metadata so
post-processing can label axes and so analysts opening a foreign file
know what they're looking at.
"""

from __future__ import annotations

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
