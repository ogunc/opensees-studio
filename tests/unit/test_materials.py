"""Unit tests for materials and the discriminated union."""

from __future__ import annotations

import pytest
from pydantic import TypeAdapter, ValidationError

from opensees_studio.core import (
    Concrete02,
    ElasticIsotropic,
    HystereticSM,
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


class TestHystereticSM:
    def test_construct_asymmetric_multipoint(self) -> None:
        # The wire-rope axial backbone: 7 positive points (to ~69 kN), an
        # independent, softer negative (compression) envelope.
        m = HystereticSM(
            id=1, name="iso-axial",
            pos_env=[(1.57, 0.00207), (3.0, 0.00436), (69.1, 0.0399)],
            neg_env=[(-1.4, -0.00057), (-15.31, -0.0483)],
        )
        assert m.type == "HystereticSM"
        assert m.pos_env[-1] == (69.1, 0.0399)
        assert len(m.neg_env) == 2

    def test_positive_envelope_required(self) -> None:
        with pytest.raises(ValidationError):
            HystereticSM(id=1, pos_env=[])

    def test_negative_envelope_optional_for_symmetric(self) -> None:
        m = HystereticSM(id=2, pos_env=[(0.12, 0.00067), (9.21, 0.0804)])
        assert m.neg_env == []

    def test_round_trip_through_union(self) -> None:
        original = HystereticSM(
            id=7,
            pos_env=[(0.6, 0.00202), (12.85, 0.0783)],
            neg_env=[(-0.6, -0.00202), (-12.85, -0.0783)],
        )
        payload = material_adapter.dump_python(original, mode="json", by_alias=True)
        restored = material_adapter.validate_python(payload)
        assert isinstance(restored, HystereticSM)
        assert restored.pos_env == original.pos_env
        assert restored.neg_env == original.neg_env


class TestDiscriminatedUnion:
    def test_round_trip_preserves_type(self) -> None:
        for original in [
            Steel01(id=1, Fy=420e6, E0=200e9, b=0.01),
            Steel02(id=2, Fy=355e6, E0=210e9, b=0.005),
            ElasticIsotropic(id=3, E=200e9, nu=0.3, rho=7850),
            HystereticSM(id=4, pos_env=[(1.0, 0.001), (2.0, 0.01)]),
        ]:
            payload = material_adapter.dump_python(original, mode="json", by_alias=True)
            restored = material_adapter.validate_python(payload)
            assert type(restored) is type(original)
            assert restored.id == original.id

    def test_unknown_type_rejected(self) -> None:
        with pytest.raises(ValidationError):
            material_adapter.validate_python({"type": "Unobtanium", "id": 1, "E": 1.0})
