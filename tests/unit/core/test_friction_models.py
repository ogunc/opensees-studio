"""Friction models for sliding bearings: validation, helpers, round trip."""

from __future__ import annotations

import math

import pytest
from pydantic import TypeAdapter, ValidationError

from opensees_studio.core import (
    CoulombFriction,
    FrictionModel,
    Project,
    VelDependentFriction,
    VelNormalFrcDepFriction,
    velocity_dependent_coefficient,
)

adapter = TypeAdapter(FrictionModel)


def test_coulomb_requires_positive_mu() -> None:
    fm = CoulombFriction(id=1, mu=0.1)
    assert fm.type == "Coulomb"
    assert fm.coefficient(velocity=5.0, normal_force=20.0) == 0.1
    for bad in (0.0, -0.1):
        with pytest.raises(ValidationError, match="mu"):
            CoulombFriction(id=1, mu=bad)


def test_vel_dependent_validation_and_law() -> None:
    fm = VelDependentFriction(id=1, mu_slow=0.05, mu_fast=0.1, trans_rate=0.5)
    assert fm.type == "VelDependent"
    assert fm.coefficient(0.0) == pytest.approx(0.05)
    # values measured on the live build under N = 20: F = 1.005, 1.632, 2.000
    assert fm.coefficient(0.01) * 20.0 == pytest.approx(1.005, abs=1e-3)
    assert fm.coefficient(2.0) * 20.0 == pytest.approx(1.63212, abs=1e-4)
    assert fm.coefficient(-20.0) * 20.0 == pytest.approx(2.0, abs=1e-4)
    assert velocity_dependent_coefficient(0.05, 0.1, 0.5, 2.0) == pytest.approx(
        0.1 - 0.05 * math.exp(-1.0)
    )
    # OpenSees 3.8 terminates the process on a zero or negative coefficient
    # and on a negative rate; a zero rate would never reach mu_fast.
    for field, bad in (
        ("mu_slow", 0.0),
        ("mu_fast", 0.0),
        ("mu_fast", -0.1),
        ("trans_rate", 0.0),
        ("trans_rate", -0.5),
    ):
        kw = dict(id=1, mu_slow=0.05, mu_fast=0.1, trans_rate=0.5)
        kw[field] = bad
        with pytest.raises(ValidationError, match=field):
            VelDependentFriction(**kw)
    # mu_fast below mu_slow is allowed (OpenSees accepts it)
    assert VelDependentFriction(id=1, mu_slow=0.1, mu_fast=0.05, trans_rate=0.5).mu_fast == 0.05


def test_vel_normal_force_dependent_validation_and_law() -> None:
    fm = VelNormalFrcDepFriction(id=1, a_slow=0.1, n_slow=-0.1, a_fast=0.2, n_fast=-0.1)
    assert fm.type == "VelNormalFrcDep"
    assert (fm.alpha0, fm.alpha1, fm.alpha2, fm.max_mu_fact) == (0.0, 0.0, 0.0, 1.0)
    # live build: slow friction force aSlow N^nSlow (0.07415 at N = 20, 0.06918 at N = 40)
    assert fm.coefficient(0.0, 20.0) * 20.0 == pytest.approx(0.07415, abs=1e-4)
    assert fm.coefficient(0.0, 40.0) * 40.0 == pytest.approx(0.06918, abs=1e-4)
    # n = 1 gives a Coulomb-like coefficient a; rate alpha1 N with v = 1 gives 0.16321 at N = 20
    unit = VelNormalFrcDepFriction(id=1, a_slow=0.1, n_slow=1.0, a_fast=0.2, n_fast=1.0)
    assert unit.coefficient(0.0, 20.0) == pytest.approx(0.1)
    rated = VelNormalFrcDepFriction(id=1, a_slow=0.1, a_fast=0.2, alpha1=0.05)
    assert rated.coefficient(1.0, 20.0) * 20.0 == pytest.approx(0.16321, abs=1e-4)
    with pytest.raises(ValueError, match="normal_force"):
        fm.coefficient(0.0, 0.0)
    for field in ("a_slow", "a_fast", "max_mu_fact"):
        with pytest.raises(ValidationError, match=field):
            VelNormalFrcDepFriction(id=1, **{"a_slow": 0.1, "a_fast": 0.2, field: 0.0})
    for field in ("alpha0", "alpha1", "alpha2"):
        with pytest.raises(ValidationError, match=field):
            VelNormalFrcDepFriction(id=1, a_slow=0.1, a_fast=0.2, **{field: -1.0})


def test_dump_round_trip_through_the_union() -> None:
    for original in (
        CoulombFriction(id=1, name="c", mu=0.08),
        VelDependentFriction(id=2, mu_slow=0.04, mu_fast=0.12, trans_rate=2.5),
        VelNormalFrcDepFriction(
            id=3, a_slow=0.1, n_slow=-0.2, a_fast=0.3, n_fast=-0.1, alpha0=0.5, max_mu_fact=2.0
        ),
    ):
        payload = adapter.dump_python(original, mode="json")
        restored = adapter.validate_python(payload)
        assert type(restored) is type(original)
        assert restored == original
        assert payload["type"] == original.type
    with pytest.raises(ValidationError):
        CoulombFriction(id=1, mu=0.1, unknown=1)


def test_project_stores_friction_models_like_materials() -> None:
    p = Project(ndm=2, ndf=3, friction_models=[CoulombFriction(id=3, mu=0.1)])
    assert p.schema_version == 2  # additive field
    assert p.friction_model(3).mu == 0.1
    assert p.next_friction_model_id() == 4
    restored = Project.model_validate(p.model_dump(mode="json"))
    assert restored.friction_models == p.friction_models
    with pytest.raises(KeyError, match="Friction model"):
        p.friction_model(9)
    with pytest.raises(ValidationError, match="Duplicate friction model ids"):
        Project(
            ndm=2,
            ndf=3,
            friction_models=[CoulombFriction(id=1, mu=0.1), CoulombFriction(id=1, mu=0.2)],
        )
