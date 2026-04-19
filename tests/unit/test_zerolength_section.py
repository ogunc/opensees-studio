"""Unit tests for ZeroLengthSectionElement model + serialization."""

from __future__ import annotations

import pytest

from opensees_studio.core import (
    ElasticSection,
    Node,
    Project,
    ZeroLengthSectionElement,
)
from opensees_studio.services import load_project, save_project


def test_zero_length_section_schema_defaults() -> None:
    el = ZeroLengthSectionElement(id=1, nodes=(1, 2), section_id=5)
    assert el.type == "ZeroLengthSection"
    assert el.nodes == (1, 2)
    assert el.section_id == 5


def test_zero_length_section_rejects_extra_fields() -> None:
    with pytest.raises(Exception):
        ZeroLengthSectionElement(
            id=1, nodes=(1, 2), section_id=1,
            bogus="not allowed",  # type: ignore[call-arg]
        )


def test_zero_length_section_round_trips(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """A project containing a zeroLengthSection must save+load unchanged."""
    p = Project(
        ndm=2, ndf=3,
        nodes=[
            Node(id=1, coords=(0, 0, 0),
                 restraint=(True, True, False, False, False, True)),
            Node(id=2, coords=(0, 0, 0),
                 restraint=(False, True, False, False, False, False)),
        ],
        sections=[ElasticSection(
            id=1, name="Box", E=200e9, A=0.01, Iz=1e-5, Iy=1e-5,
            G=80e9, J=1e-6,
        )],
        elements=[
            ZeroLengthSectionElement(id=10, nodes=(1, 2), section_id=1),
        ],
    )
    path = tmp_path / "mk.osmodel"
    save_project(p, path)
    r = load_project(path)
    assert len(r.elements) == 1
    assert isinstance(r.elements[0], ZeroLengthSectionElement)
    assert r.elements[0].nodes == (1, 2)
    assert r.elements[0].section_id == 1
