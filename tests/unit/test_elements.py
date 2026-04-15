"""Unit tests for element types."""

from __future__ import annotations

import pytest
from pydantic import TypeAdapter, ValidationError

from opensees_studio.core import (
    Element,
    ElasticBeamColumn,
    ForceBeamColumn,
    TrussElement,
    ZeroLengthElement,
)

element_adapter: TypeAdapter[Element] = TypeAdapter(Element)


def test_truss_construct() -> None:
    t = TrussElement(id=1, nodes=(1, 2), area=0.01, material_id=1)
    assert t.type == "Truss"
    assert t.nodes == (1, 2)


def test_truss_requires_two_nodes() -> None:
    with pytest.raises(ValidationError):
        TrussElement(id=1, nodes=(1,), area=0.01, material_id=1)  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        TrussElement(id=1, nodes=(1, 2, 3), area=0.01, material_id=1)  # type: ignore[arg-type]


def test_truss_area_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        TrussElement(id=1, nodes=(1, 2), area=-0.01, material_id=1)


def test_elastic_beam_default_geom_transf() -> None:
    e = ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1)
    assert e.geom_transf == "Linear"


def test_force_beam_integration_points_bounds() -> None:
    ForceBeamColumn(id=1, nodes=(1, 2), section_id=1, integration_points=5)
    with pytest.raises(ValidationError):
        ForceBeamColumn(id=1, nodes=(1, 2), section_id=1, integration_points=1)
    with pytest.raises(ValidationError):
        ForceBeamColumn(id=1, nodes=(1, 2), section_id=1, integration_points=11)


def test_zero_length_dofs_match_materials() -> None:
    z = ZeroLengthElement(id=1, nodes=(1, 2), material_ids=(1, 2), dofs=(1, 2))
    assert z.dofs == (1, 2)


def test_element_union_round_trip() -> None:
    for original in [
        TrussElement(id=1, nodes=(1, 2), area=0.01, material_id=1),
        ElasticBeamColumn(id=2, nodes=(1, 2), section_id=1, geom_transf="PDelta"),
    ]:
        payload = element_adapter.dump_python(original, mode="json")
        restored = element_adapter.validate_python(payload)
        assert type(restored) is type(original)
        assert restored.id == original.id
