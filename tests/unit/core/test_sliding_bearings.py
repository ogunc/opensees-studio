"""Flat slider and single friction pendulum bearing models and helpers."""

from __future__ import annotations

import math

import pytest
from pydantic import TypeAdapter, ValidationError

from opensees_studio.core import (
    BEARING_CLASSES,
    ELASTOMERIC_BEARING_CLASSES,
    SLIDING_BEARING_CLASSES,
    CoulombFriction,
    ElasticUniaxial,
    Element,
    FlatSliderBearingElement,
    Node,
    Project,
    SingleFPBearingElement,
    UnitSystem,
    friction_cycle_energy,
    gravity,
    pendulum_period,
    pendulum_restoring_stiffness,
    sliding_yield_displacement,
)

element_adapter = TypeAdapter(Element)
MU, W, K_INIT, R_EFF = 0.1, 20.0, 1000.0, 2.0


def _flat(**kw):  # type: ignore[no-untyped-def]
    base = dict(
        id=1, nodes=(1, 2), friction_model_id=1, k_init=K_INIT, p_material_id=1, mz_material_id=2
    )
    base.update(kw)
    return FlatSliderBearingElement(**base)


def _fp(**kw):  # type: ignore[no-untyped-def]
    base = dict(
        id=1,
        nodes=(1, 2),
        friction_model_id=1,
        r_eff=R_EFF,
        k_init=K_INIT,
        p_material_id=1,
        mz_material_id=2,
    )
    base.update(kw)
    return SingleFPBearingElement(**base)


def test_closed_form_helpers() -> None:
    assert sliding_yield_displacement(MU, W, K_INIT) == pytest.approx(0.002)
    assert pendulum_restoring_stiffness(W, R_EFF) == pytest.approx(10.0)
    assert pendulum_period(R_EFF, 9.80665) == pytest.approx(
        2.0 * math.pi * math.sqrt(2.0 / 9.80665)
    )
    # live probe: singleFP at u = 0.05 carried 2.5078 = mu W + W u / Reff (2 + 0.5) up to the
    # small slip displacement correction
    assert MU * W + pendulum_restoring_stiffness(W, R_EFF) * 0.05 == pytest.approx(2.5, abs=1e-9)
    assert friction_cycle_energy(MU, W, 0.05, 0.002) == pytest.approx(4.0 * 2.0 * 0.048)
    assert friction_cycle_energy(MU, W, 0.001, 0.002) == 0.0
    for bad in (
        lambda: sliding_yield_displacement(0.0, W, K_INIT),
        lambda: pendulum_restoring_stiffness(W, 0.0),
        lambda: pendulum_period(0.0, 9.81),
        lambda: pendulum_period(R_EFF, 0.0),
    ):
        with pytest.raises(ValueError):
            bad()


def test_flat_slider_defaults_and_derived() -> None:
    el = _flat()
    assert el.type == "FlatSliderBearing"
    assert (el.max_iter, el.tol, el.shear_dist, el.do_rayleigh, el.mass, el.orient) == (
        25,
        1e-12,
        0.5,
        False,
        0.0,
        None,
    )
    assert el.yield_displacement(MU, W) == pytest.approx(0.002)
    assert el.material_reference_ids == (1, 2)
    assert _flat(t_material_id=3, my_material_id=4).material_reference_ids == (1, 2, 3, 4)
    assert not hasattr(el, "qd")


def test_single_fp_derived_in_project_units() -> None:
    el = _fp()
    assert el.type == "SingleFPBearing"
    assert el.restoring_stiffness(W) == pytest.approx(10.0)
    assert el.isolated_period(UnitSystem.SI_M_N) == pytest.approx(
        2.0 * math.pi * math.sqrt(R_EFF / gravity(UnitSystem.SI_M_N))
    )
    inch = _fp(r_eff=88.0)  # 88 in in the in-kip system, g = 386.0886 in/s^2
    assert inch.isolated_period(UnitSystem.US_IN_KIP) == pytest.approx(
        2.0 * math.pi * math.sqrt(88.0 / 386.0886), rel=1e-6
    )


@pytest.mark.parametrize("field", ["k_init", "r_eff", "tol"])
def test_single_fp_positive_parameters(field: str) -> None:
    # live build: Reff = 0 makes the analysis fail with NaN, Reff < 0 and Kinit < 0 give
    # wrong-signed forces, Kinit = 0 fails; a positive value is required for each.
    for bad in (0.0, -1.0):
        with pytest.raises(ValidationError, match=field):
            _fp(**{field: bad})


def test_flat_slider_hard_exit_rules() -> None:
    with pytest.raises(ValidationError, match="k_init"):
        _flat(k_init=0.0)
    with pytest.raises(ValidationError, match="max_iter"):
        _flat(max_iter=0)  # -iter 0 makes the integrator fail on the live build
    with pytest.raises(ValidationError, match="friction_model_id"):
        _flat(friction_model_id=0)
    with pytest.raises(ValidationError, match="parallel"):
        _flat(orient=(0, 1, 0, 0, 2, 0))  # OpenSees 3.8 terminates on parallel vectors
    with pytest.raises(ValidationError, match="non-zero"):
        _flat(orient=(0, 0, 0, 1, 0, 0))  # and on a zero vector
    with pytest.raises(ValidationError):
        _flat(orient=(0, 1, 0))
    with pytest.raises(ValidationError, match="shear_dist"):
        _flat(shear_dist=1.5)
    with pytest.raises(ValidationError):
        _flat(r_eff=2.0)  # extra field: r_eff belongs to the pendulum only


def test_class_tuples() -> None:
    assert (FlatSliderBearingElement, SingleFPBearingElement) == SLIDING_BEARING_CLASSES
    assert BEARING_CLASSES == ELASTOMERIC_BEARING_CLASSES + SLIDING_BEARING_CLASSES


def test_dump_round_trip_through_the_element_union() -> None:
    for original in (
        _flat(orient=(0, 1, 0, 1, 0, 0), shear_dist=0.3, do_rayleigh=True, mass=0.2),
        _fp(t_material_id=3, my_material_id=4, max_iter=50, tol=1e-10),
    ):
        payload = element_adapter.dump_python(original, mode="json")
        restored = element_adapter.validate_python(payload)
        assert type(restored) is type(original)
        assert restored == original
        assert payload["type"] == original.type


def test_project_reference_checks() -> None:
    nodes = [Node(id=1, coords=(0, 0, 0)), Node(id=2, coords=(0, 0, 0))]
    mats = [ElasticUniaxial(id=1, E=1e5), ElasticUniaxial(id=2, E=1e4)]
    fric = [CoulombFriction(id=1, mu=MU)]
    ok = Project(ndm=2, ndf=3, nodes=nodes, materials=mats, friction_models=fric, elements=[_fp()])
    ok.validate_references()
    assert ok.schema_version == 2
    no_friction = Project(ndm=2, ndf=3, nodes=nodes, materials=mats, elements=[_flat()])
    with pytest.raises(ValueError, match="missing friction model 1"):
        no_friction.validate_references()
    no_material = Project(
        ndm=2, ndf=3, nodes=nodes, materials=mats[:1], friction_models=fric, elements=[_flat()]
    )
    with pytest.raises(ValueError, match="missing material 2"):
        no_material.validate_references()
    three_d = Project(
        ndm=3, ndf=6, nodes=nodes, materials=mats, friction_models=fric, elements=[_fp()]
    )
    with pytest.raises(ValueError, match="t_material_id and my_material_id"):
        three_d.validate_references()
    Project(
        ndm=3,
        ndf=6,
        nodes=nodes,
        materials=mats,
        friction_models=fric,
        elements=[_fp(t_material_id=2, my_material_id=2)],
    ).validate_references()
