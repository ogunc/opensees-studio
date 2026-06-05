"""Unit tests for Concrete04 (Popovics concrete)."""

from __future__ import annotations

import pytest
from pydantic import TypeAdapter, ValidationError

from opensees_studio.core import Concrete04, Material

material_adapter: TypeAdapter[Material] = TypeAdapter(Material)


class TestConcrete04Instantiation:
    def test_no_tension_construct(self) -> None:
        m = Concrete04(id=1, name="C30-NoTension", fpc=-30e6, epsc0=-0.002, epscu=-0.005, Ec=30e9)
        assert m.type == "Concrete04"
        assert m.fpc == -30e6
        assert m.epsc0 == -0.002
        assert m.epscu == -0.005
        assert m.Ec == 30e9
        assert m.fct is None
        assert m.et is None
        assert m.beta is None

    def test_with_tension_construct(self) -> None:
        m = Concrete04(
            id=2, name="C30-Tension",
            fpc=-30e6, epsc0=-0.002, epscu=-0.005, Ec=30e9,
            fct=3.0e6, et=1e-4,
        )
        assert m.fct == 3.0e6
        assert m.et == 1e-4
        assert m.beta is None

    def test_with_beta_construct(self) -> None:
        m = Concrete04(
            id=3, name="C30-Cyclic",
            fpc=-30e6, epsc0=-0.002, epscu=-0.005, Ec=30e9,
            fct=3.0e6, et=1e-4, beta=0.1,
        )
        assert m.beta == pytest.approx(0.1)

    def test_defaults_are_no_tension(self) -> None:
        m = Concrete04(id=1, fpc=-30e6, epsc0=-0.002, epscu=-0.005, Ec=30e9)
        assert m.fct is None and m.et is None and m.beta is None


class TestConcrete04SignConventions:
    def test_fpc_must_be_negative(self) -> None:
        with pytest.raises(ValidationError):
            Concrete04(id=1, fpc=30e6, epsc0=-0.002, epscu=-0.005, Ec=30e9)

    def test_epsc0_must_be_negative(self) -> None:
        with pytest.raises(ValidationError):
            Concrete04(id=1, fpc=-30e6, epsc0=0.002, epscu=-0.005, Ec=30e9)

    def test_epscu_must_be_negative(self) -> None:
        with pytest.raises(ValidationError):
            Concrete04(id=1, fpc=-30e6, epsc0=-0.002, epscu=0.005, Ec=30e9)

    def test_ec_must_be_positive(self) -> None:
        with pytest.raises(ValidationError):
            Concrete04(id=1, fpc=-30e6, epsc0=-0.002, epscu=-0.005, Ec=-30e9)

    def test_fct_must_be_positive(self) -> None:
        with pytest.raises(ValidationError):
            Concrete04(id=1, fpc=-30e6, epsc0=-0.002, epscu=-0.005, Ec=30e9, fct=-1.0, et=1e-4)


class TestConcrete04TensileParamConsistency:
    def test_fct_without_et_raises(self) -> None:
        with pytest.raises(ValidationError, match="et is required"):
            Concrete04(id=1, fpc=-30e6, epsc0=-0.002, epscu=-0.005, Ec=30e9, fct=3e6)

    def test_et_without_fct_raises(self) -> None:
        with pytest.raises(ValidationError, match="fct is required"):
            Concrete04(id=1, fpc=-30e6, epsc0=-0.002, epscu=-0.005, Ec=30e9, et=1e-4)

    def test_beta_without_fct_et_raises(self) -> None:
        with pytest.raises(ValidationError, match="beta requires"):
            Concrete04(id=1, fpc=-30e6, epsc0=-0.002, epscu=-0.005, Ec=30e9, beta=0.1)

    def test_beta_bounds(self) -> None:
        with pytest.raises(ValidationError):
            Concrete04(
                id=1, fpc=-30e6, epsc0=-0.002, epscu=-0.005, Ec=30e9,
                fct=3e6, et=1e-4, beta=1.5,
            )


class TestConcrete04JsonRoundTrip:
    def test_no_tension_round_trip(self) -> None:
        original = Concrete04(id=1, name="C30", fpc=-30e6, epsc0=-0.002, epscu=-0.005, Ec=30e9)
        payload = material_adapter.dump_python(original, mode="json", by_alias=True)
        assert payload["type"] == "Concrete04"
        restored = material_adapter.validate_python(payload)
        assert type(restored) is Concrete04
        assert restored.id == original.id
        assert restored.fpc == original.fpc
        assert restored.fct is None

    def test_with_tension_round_trip(self) -> None:
        original = Concrete04(
            id=2, name="C30-T",
            fpc=-30e6, epsc0=-0.002, epscu=-0.005, Ec=30e9,
            fct=3.0e6, et=1e-4,
        )
        payload = material_adapter.dump_python(original, mode="json", by_alias=True)
        restored = material_adapter.validate_python(payload)
        assert type(restored) is Concrete04
        assert restored.fct == pytest.approx(3.0e6)
        assert restored.et == pytest.approx(1e-4)

    def test_old_osmodel_without_concrete04_loads_cleanly(self) -> None:
        """An osmodel payload that doesn't mention Concrete04 is unaffected."""
        from pathlib import Path
        from opensees_studio.services import load_project

        osmodel = Path(__file__).parents[4] / "examples" / "cantilever.osmodel"
        if not osmodel.exists():
            pytest.skip("cantilever.osmodel not present")
        proj = load_project(osmodel)
        proj.validate_references()
        # No Concrete04 in a cantilever; confirm it still round-trips cleanly.
        assert all(m.type != "Concrete04" for m in proj.materials)
