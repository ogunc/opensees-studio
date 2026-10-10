"""
Tests for the auto-generated Pydantic v2 catalog stubs.

Fast unit tests only — no Qt, no openseespy, no file I/O.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from opensees_studio.core.catalog import CATALOG
from opensees_studio.core.catalog.generated.concrete04_popovics_concrete import (
    Concrete04PopovicsConcreteSpec,
)
from opensees_studio.core.catalog.generated.elastic import ElasticSpec
from opensees_studio.core.catalog.generated.steel02 import Steel02Spec

# ---------------------------------------------------------------------------
# CATALOG registry
# ---------------------------------------------------------------------------


class TestCatalogRegistry:
    def test_catalog_has_58_entries(self) -> None:
        assert len(CATALOG) == 58

    def test_all_entries_are_basemodel_subclasses(self) -> None:
        for name, cls in CATALOG.items():
            assert issubclass(cls, BaseModel), f"{name!r} is not a BaseModel subclass"

    def test_steel02_in_catalog(self) -> None:
        assert "Steel02" in CATALOG
        assert CATALOG["Steel02"] is Steel02Spec

    def test_elastic_in_catalog(self) -> None:
        assert "Elastic" in CATALOG
        assert CATALOG["Elastic"] is ElasticSpec

    def test_concrete04_in_catalog(self) -> None:
        assert "Concrete04_(Popovics_concrete)" in CATALOG
        assert CATALOG["Concrete04_(Popovics_concrete)"] is Concrete04PopovicsConcreteSpec


# ---------------------------------------------------------------------------
# Instantiation — every spec must accept zero arguments
# ---------------------------------------------------------------------------


class TestInstantiationWithDefaults:
    @pytest.mark.parametrize("gid_name,cls", list(CATALOG.items()))
    def test_instantiate_with_defaults(self, gid_name: str, cls: type[BaseModel]) -> None:
        instance = cls()
        assert instance is not None


# ---------------------------------------------------------------------------
# Steel02Spec — spot-check defaults against the source .mat VALUE lines
# ---------------------------------------------------------------------------


class TestSteel02Spec:
    def setup_method(self) -> None:
        self.spec = Steel02Spec()

    def test_parameter_r0_default(self) -> None:
        assert self.spec.parameter_r0 == 20

    def test_parameter_cr1_default(self) -> None:
        assert self.spec.parameter_cr1 == 0.925

    def test_parameter_cr2_default(self) -> None:
        assert self.spec.parameter_cr2 == 0.15

    def test_strain_hardening_ratio_b_default(self) -> None:
        assert self.spec.strain_hardening_ratio_b == 0.02

    def test_yield_stress_fy_default(self) -> None:
        # UNITS field — stored as string including unit label
        assert self.spec.yield_stress_fy == "500 MPa"

    def test_initial_elastic_tangent_e0_default(self) -> None:
        assert self.spec.initial_elastic_tangent_e0 == "200 GPa"

    def test_steel_grade_default(self) -> None:
        assert self.spec.steel_grade == "Custom"

    def test_formulation_default(self) -> None:
        assert self.spec.formulation == "Stress-Strain"

    def test_isotropic_hardening_parameter_a1_default(self) -> None:
        assert self.spec.isotropic_hardening_parameter_a1 == 0

    def test_isotropic_hardening_parameter_a2_default(self) -> None:
        assert self.spec.isotropic_hardening_parameter_a2 == 1

    def test_dependencies_in_model_config(self) -> None:
        extra = Steel02Spec.model_config.get("json_schema_extra") or {}
        assert isinstance(extra, dict)
        assert "dependencies" in extra
        assert len(extra["dependencies"]) > 0

    def test_gid_name_in_model_config(self) -> None:
        extra = Steel02Spec.model_config.get("json_schema_extra") or {}
        assert extra.get("x-gid-name") == "Steel02"

    def test_book_in_model_config(self) -> None:
        extra = Steel02Spec.model_config.get("json_schema_extra") or {}
        assert extra.get("x-book") == "Uniaxial_Steel_Materials"


# ---------------------------------------------------------------------------
# Round-trip: serialize -> deserialize -> equal
# ---------------------------------------------------------------------------


class TestRoundTrip:
    def _roundtrip(self, cls: type[BaseModel]) -> None:
        original = cls()
        json_str = original.model_dump_json()
        restored = cls.model_validate_json(json_str)
        assert original == restored, f"{cls.__name__} round-trip failed"

    def test_steel02_roundtrip(self) -> None:
        self._roundtrip(Steel02Spec)

    def test_elastic_roundtrip(self) -> None:
        self._roundtrip(ElasticSpec)

    def test_concrete04_roundtrip(self) -> None:
        self._roundtrip(Concrete04PopovicsConcreteSpec)


# ---------------------------------------------------------------------------
# Book union types are importable
# ---------------------------------------------------------------------------


class TestBookUnions:
    def test_standard_uniaxial_materials_union(self) -> None:
        from opensees_studio.core.catalog.generated import StandardUniaxialMaterials

        assert StandardUniaxialMaterials is not None

    def test_uniaxial_steel_materials_union(self) -> None:
        from opensees_studio.core.catalog.generated import UniaxialSteelMaterials

        assert UniaxialSteelMaterials is not None

    def test_conditions_restraints_union(self) -> None:
        from opensees_studio.core.catalog.generated.conditions import Restraints

        assert Restraints is not None
