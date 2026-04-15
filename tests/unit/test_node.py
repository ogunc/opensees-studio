"""Unit tests for the Node entity."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from opensees_studio.core import Node


class TestNodeConstruction:
    def test_minimum_required_fields(self) -> None:
        n = Node(id=1, coords=(0.0, 0.0, 0.0))
        assert n.id == 1
        assert n.coords == (0.0, 0.0, 0.0)
        assert n.mass == (0.0,) * 6
        assert n.restraint == (False,) * 6
        assert n.is_free
        assert not n.is_restrained

    def test_with_name_and_mass(self) -> None:
        n = Node(id=42, name="A1", coords=(1.0, 2.0, 3.0),
                 mass=(100.0, 100.0, 100.0, 0.0, 0.0, 0.0))
        assert n.name == "A1"
        assert n.mass[0] == 100.0

    def test_pin_restraint(self) -> None:
        pin = Node(id=1, coords=(0, 0, 0), restraint=(True, True, True, False, False, False))
        assert pin.is_restrained
        assert sum(pin.restraint) == 3


class TestNodeValidation:
    def test_id_must_be_positive(self) -> None:
        with pytest.raises(ValidationError):
            Node(id=0, coords=(0, 0, 0))
        with pytest.raises(ValidationError):
            Node(id=-1, coords=(0, 0, 0))

    def test_coords_must_be_three_floats(self) -> None:
        with pytest.raises(ValidationError):
            Node(id=1, coords=(0.0, 0.0))  # type: ignore[arg-type]
        with pytest.raises(ValidationError):
            Node(id=1, coords=(0.0, 0.0, 0.0, 0.0))  # type: ignore[arg-type]

    def test_mass_must_be_six_components(self) -> None:
        with pytest.raises(ValidationError):
            Node(id=1, coords=(0, 0, 0), mass=(1.0, 2.0, 3.0))  # type: ignore[arg-type]

    def test_extra_fields_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Node(id=1, coords=(0, 0, 0), unknown="oops")  # type: ignore[call-arg]
