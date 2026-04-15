"""Unit tests for materials and the discriminated union."""

from __future__ import annotations

import pytest
from pydantic import TypeAdapter, ValidationError

from opensees_studio.core import (
    Concrete02,
    ElasticIsotropic,
    Material,
    Steel01,
    Steel02,
)

material_adapter: TypeAdapter[Material] = TypeAdapter(Material)


class TestSteel01:
    def test_construct(self) -> None:
        s = Steel01(id=1, name="S420", Fy=420e6, E0=200e9, b=0.01)
        assert s.type == "Steel01"
        assert s.Fy == 420e6

    def test_b_must_be_in_range(self) -> None:
        with pytest.raises(ValidationError):
            Steel01(id=1, Fy=420e6, E0=200e9, b=-0.01)
        with pytest.raises(ValidationError):
            Steel01(id=1, Fy=420e6, E0=200e9, b=1.5)

    def test_fy_must_be_positive(self) -> None:
        with pytest.raises(ValidationError):
            Steel01(id=1, Fy=-1.0, E0=200e9, b=0.01)


class TestConcrete02:
    def test_lambda_alias(self) -> None:
        c = Concrete02(
            id=1, fpc=-30e6, epsc0=-0.002, fpcu=-15e6, epsU=-0.005,
            ft=3e6, Ets=2e9, **{"lambda": 0.1},
        )
        assert c.lambda_ == 0.1
        # Round-trip should preserve the alias.
        dumped = c.model_dump(by_alias=True)
        assert "lambda" in dumped
        assert "lambda_" not in dumped

    def test_negative_signs_enforced(self) -> None:
        with pytest.raises(ValidationError):
            Concrete02(
                id=1, fpc=30e6, epsc0=-0.002, fpcu=-15e6, epsU=-0.005,
                ft=3e6, Ets=2e9, **{"lambda": 0.1},
            )


class TestElasticIsotropic:
    def test_poisson_bounds(self) -> None:
        ElasticIsotropic(id=1, E=200e9, nu=0.3)
        with pytest.raises(ValidationError):
            ElasticIsotropic(id=1, E=200e9, nu=0.6)


class TestDiscriminatedUnion:
    def test_round_trip_preserves_type(self) -> None:
        for original in [
            Steel01(id=1, Fy=420e6, E0=200e9, b=0.01),
            Steel02(id=2, Fy=355e6, E0=210e9, b=0.005),
            ElasticIsotropic(id=3, E=200e9, nu=0.3, rho=7850),
        ]:
            payload = material_adapter.dump_python(original, mode="json", by_alias=True)
            restored = material_adapter.validate_python(payload)
            assert type(restored) is type(original)
            assert restored.id == original.id

    def test_unknown_type_rejected(self) -> None:
        with pytest.raises(ValidationError):
            material_adapter.validate_python({"type": "Unobtanium", "id": 1, "E": 1.0})
