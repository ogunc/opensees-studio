"""Every signature material is built by OpenSees and answers a strain; wrappers by closed form."""

from __future__ import annotations

import math

import pytest

from opensees_studio.core import ElasticUniaxial, Node, Project
from opensees_studio.core.materials.library import (
    SIGNATURE_MATERIALS,
    ElasticMultiLinear,
    InitStrainMaterial,
    MinMaxMaterial,
    ParallelMaterial,
    SeriesMaterial,
)
from opensees_studio.services.opensees_runner import OpenSeesRunner

ops = pytest.importorskip("openseespy.opensees")

BASE = ElasticUniaxial(id=100, E=1000.0)
OTHER = ElasticUniaxial(id=101, E=3000.0)


def _build(*materials) -> None:  # type: ignore[no-untyped-def]
    project = Project(
        ndm=2,
        ndf=3,
        nodes=[Node(id=1, coords=(0.0, 0.0, 0.0))],
        materials=[*materials, BASE, OTHER],
    )
    OpenSeesRunner(project).build()


def _stress(tag: int, strain: float) -> float:
    ops.testUniaxialMaterial(tag)
    ops.setStrain(strain)
    return float(ops.getStress())


def _default(cls, tag: int):  # type: ignore[no-untyped-def]
    if "material_ids" in cls.model_fields:
        return cls(id=tag, material_ids=[100, 101])
    if "material_id" in cls.model_fields:
        return cls(id=tag, material_id=100)
    return cls(id=tag)


@pytest.mark.parametrize("cls", SIGNATURE_MATERIALS, ids=lambda c: c.__name__)
def test_opensees_builds_it_with_its_defaults(cls) -> None:  # type: ignore[no-untyped-def]
    _build(_default(cls, 1))
    assert math.isfinite(_stress(1, 1e-4))


def test_parallel_adds_and_series_combines_in_series() -> None:
    # Wrappers are listed before what they wrap: the runner reorders them.
    _build(
        ParallelMaterial(id=1, material_ids=[100, 101], factors=[1.0, 2.0]),
        SeriesMaterial(id=2, material_ids=[100, 101]),
    )
    assert _stress(1, 1e-3) == pytest.approx((1000 + 2 * 3000) * 1e-3)
    assert _stress(2, 1e-3) == pytest.approx(1e-3 / (1 / 1000 + 1 / 3000), rel=1e-6)


def test_minmax_fails_beyond_its_strain_and_init_strain_offsets() -> None:
    _build(
        MinMaxMaterial(id=1, material_id=100, min_strain=-0.01, max_strain=0.01),
        InitStrainMaterial(id=2, material_id=100, initStrain=0.002),
    )
    assert _stress(1, 0.005) == pytest.approx(5.0)
    assert _stress(1, 0.02) == pytest.approx(0.0)
    assert _stress(2, 0.001) == pytest.approx(1000 * 0.003)


def test_elastic_multilinear_interpolates() -> None:
    _build(ElasticMultiLinear(id=1, points=[(-1.0, -10.0), (0.0, 0.0), (1.0, 10.0), (2.0, 15.0)]))
    assert _stress(1, 1.5) == pytest.approx(12.5)


def test_a_missing_or_self_reference_is_reported() -> None:
    project = Project(materials=[SeriesMaterial(id=1, material_ids=[1, 9])])
    with pytest.raises(ValueError) as info:
        project.validate_references()
    assert "wraps itself" in str(info.value) and "missing material 9" in str(info.value)


def test_the_material_tester_runs_a_wrapper_with_what_it_wraps() -> None:
    from opensees_studio.services.material_tester import test_uniaxial_material
    from opensees_studio.viewmodels.material_tester_vm import monotonic_protocol

    parallel = ParallelMaterial(id=1, material_ids=[100, 101])
    result = test_uniaxial_material(
        parallel, monotonic_protocol(0.001, 4), support=[parallel, BASE, OTHER]
    )
    assert result.stress[-1] == pytest.approx(-4000 * 0.001)  # monotonic is compressive
