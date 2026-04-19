"""Unit-system label table tests."""

from __future__ import annotations

import pytest

from opensees_studio.core import UnitSystem, labels_for


def test_si_m_n_labels() -> None:
    lab = labels_for(UnitSystem.SI_M_N)
    assert lab.length == "m"
    assert lab.force == "N"
    assert lab.moment == "N·m"
    assert lab.stress == "Pa"
    assert lab.curvature == "1/m"


def test_us_in_kip_labels() -> None:
    lab = labels_for(UnitSystem.US_IN_KIP)
    assert lab.length == "in"
    assert lab.force == "kip"
    assert lab.moment == "kip·in"
    assert lab.stress == "ksi"
    assert lab.curvature == "1/in"


def test_us_ft_kip_labels() -> None:
    lab = labels_for(UnitSystem.US_FT_KIP)
    assert lab.length == "ft"
    assert lab.force == "kip"
    assert lab.moment == "kip·ft"
    assert lab.stress == "ksf"
    assert lab.curvature == "1/ft"


def test_si_mm_n_labels() -> None:
    lab = labels_for(UnitSystem.SI_MM_N)
    assert lab.length == "mm"
    assert lab.force == "N"
    assert lab.stress == "MPa"


def test_labels_for_covers_every_unit_system() -> None:
    """Every UnitSystem enum value must have a matching label bundle."""
    for us in UnitSystem:
        lab = labels_for(us)
        # sanity: at least length / force populated.
        assert lab.length and lab.force
