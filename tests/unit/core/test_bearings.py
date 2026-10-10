"""Elastomeric bearing element models and closed-form helpers."""

from __future__ import annotations

import pytest
from pydantic import TypeAdapter, ValidationError

from opensees_studio.core import (
    ElasticUniaxial,
    ElastomericBearingBoucWenElement,
    ElastomericBearingPlasticityElement,
    Element,
    Node,
    Project,
    bearing_effective_stiffness,
    bearing_shear_force,
    bearing_yield_displacement,
    bearing_yield_force,
    bilinear_cycle_energy,
)

element_adapter = TypeAdapter(Element)

K_INIT, QD, ALPHA1 = 10.0, 5.0, 0.1
U_Y = QD / (K_INIT * (1.0 - ALPHA1))  # 0.5556


def _plasticity(**kw):  # type: ignore[no-untyped-def]
    base = dict(
        id=1, nodes=(1, 2), k_init=K_INIT, qd=QD, alpha1=ALPHA1, p_material_id=1, mz_material_id=2
    )
    base.update(kw)
    return ElastomericBearingPlasticityElement(**base)


def _bouc_wen(**kw):  # type: ignore[no-untyped-def]
    base = dict(
        id=1, nodes=(1, 2), k_init=K_INIT, qd=QD, alpha1=ALPHA1, p_material_id=1, mz_material_id=2
    )
    base.update(kw)
    return ElastomericBearingBoucWenElement(**base)


def test_closed_form_helpers() -> None:
    assert bearing_yield_displacement(K_INIT, QD, ALPHA1) == pytest.approx(U_Y)
    assert bearing_yield_force(K_INIT, QD, ALPHA1) == pytest.approx(QD / (1.0 - ALPHA1))
    # backbone: Kinit u below yield, Qd + alpha1 Kinit u beyond (continuous at u_y)
    assert bearing_shear_force(K_INIT, QD, ALPHA1, 0.5 * U_Y) == pytest.approx(K_INIT * 0.5 * U_Y)
    assert bearing_shear_force(K_INIT, QD, ALPHA1, U_Y) == pytest.approx(QD + ALPHA1 * K_INIT * U_Y)
    assert bearing_shear_force(K_INIT, QD, ALPHA1, 1.2) == pytest.approx(6.2)  # live OpenSees run
    assert bearing_effective_stiffness(K_INIT, QD, ALPHA1, 0.2) == pytest.approx(K_INIT)
    assert bearing_effective_stiffness(K_INIT, QD, ALPHA1, 2.0) == pytest.approx((QD + 2.0) / 2.0)
    # hardening term alpha2 Kinit u^mu
    assert bearing_shear_force(K_INIT, QD, ALPHA1, 2.0, alpha2=0.05, mu=2.0) == pytest.approx(
        7.0 + 0.05 * K_INIT * 4.0
    )
    assert bilinear_cycle_energy(QD, 2.0 * U_Y, U_Y) == pytest.approx(4.0 * QD * U_Y)
    assert bilinear_cycle_energy(QD, 0.5 * U_Y, U_Y) == 0.0
    with pytest.raises(ValueError):
        bearing_yield_displacement(K_INIT, QD, 1.0)
    with pytest.raises(ValueError):
        bearing_effective_stiffness(K_INIT, QD, ALPHA1, 0.0)


def test_plasticity_defaults_and_derived() -> None:
    el = _plasticity()
    assert el.type == "ElastomericBearingPlasticity"
    assert (el.alpha2, el.mu, el.shear_dist, el.do_rayleigh, el.mass, el.orient) == (
        0.0,
        2.0,
        0.5,
        False,
        0.0,
        None,
    )
    assert el.t_material_id is None and el.my_material_id is None
    assert el.yield_displacement == pytest.approx(U_Y)
    assert el.yield_force == pytest.approx(QD / (1.0 - ALPHA1))
    assert el.effective_stiffness(1.2) == pytest.approx(6.2 / 1.2)
    assert el.material_reference_ids == (1, 2)
    assert _plasticity(t_material_id=3, my_material_id=4).material_reference_ids == (1, 2, 3, 4)


def test_bouc_wen_defaults_and_validation() -> None:
    el = _bouc_wen()
    assert el.type == "ElastomericBearingBoucWen"
    assert (el.eta, el.beta, el.gamma) == (1.0, 0.5, 0.5)
    assert _bouc_wen(eta=10.0, beta=0.9, gamma=0.1).eta == 10.0
    with pytest.raises(ValidationError, match="eta"):
        _bouc_wen(eta=0.0)
    with pytest.raises(ValidationError, match="beta \\+ gamma"):
        _bouc_wen(beta=0.0, gamma=0.0)
    with pytest.raises(ValidationError):
        _bouc_wen(beta=-0.1)


@pytest.mark.parametrize("field", ["k_init", "qd"])
def test_stiffness_and_strength_must_be_positive(field: str) -> None:
    with pytest.raises(ValidationError, match=field):
        _plasticity(**{field: 0.0})
    with pytest.raises(ValidationError, match=field):
        _plasticity(**{field: -1.0})


@pytest.mark.parametrize("alpha", [-0.01, 1.0, 1.5])
def test_alpha_must_be_in_zero_one(alpha: float) -> None:
    with pytest.raises(ValidationError, match="alpha1"):
        _plasticity(alpha1=alpha)
    with pytest.raises(ValidationError, match="alpha2"):
        _plasticity(alpha2=alpha)
    assert _plasticity(alpha1=0.0).alpha1 == 0.0  # elastic-perfectly-plastic is allowed


def test_orient_validation() -> None:
    assert _plasticity(orient=(0, 1, 0, 1, 0, 0)).orient == (0.0, 1.0, 0.0, 1.0, 0.0, 0.0)
    with pytest.raises(ValidationError, match="parallel"):
        _plasticity(orient=(0, 1, 0, 0, 2, 0))
    with pytest.raises(ValidationError, match="non-zero"):
        _plasticity(orient=(0, 0, 0, 1, 0, 0))
    with pytest.raises(ValidationError):
        _plasticity(orient=(0, 1, 0))  # six values are required


def test_optional_flags_are_validated() -> None:
    with pytest.raises(ValidationError, match="shear_dist"):
        _plasticity(shear_dist=1.5)
    with pytest.raises(ValidationError, match="mass"):
        _plasticity(mass=-1.0)
    with pytest.raises(ValidationError):
        _plasticity(unknown_flag=1)  # extra fields are forbidden


def test_dump_round_trip_through_the_element_union() -> None:
    for original in (
        _plasticity(orient=(0, 1, 0, 1, 0, 0), shear_dist=0.3, do_rayleigh=True, mass=0.2),
        _bouc_wen(eta=4.0, beta=0.6, gamma=0.4, t_material_id=3, my_material_id=4, alpha2=0.02),
    ):
        payload = element_adapter.dump_python(original, mode="json")
        restored = element_adapter.validate_python(payload)
        assert type(restored) is type(original)
        assert restored == original
        assert payload["type"] == original.type


def test_project_reference_checks() -> None:
    nodes = [Node(id=1, coords=(0, 0, 0)), Node(id=2, coords=(0, 0, 0))]
    mats = [ElasticUniaxial(id=1, E=1e5), ElasticUniaxial(id=2, E=1e4)]
    ok = Project(ndm=2, ndf=3, nodes=nodes, materials=mats, elements=[_plasticity()])
    ok.validate_references()
    assert ok.schema_version == 2  # additive: bearings do not bump the schema
    bad = Project(ndm=2, ndf=3, nodes=nodes, materials=mats[:1], elements=[_plasticity()])
    with pytest.raises(ValueError, match="missing material 2"):
        bad.validate_references()
    three_d = Project(ndm=3, ndf=6, nodes=nodes, materials=mats, elements=[_plasticity()])
    with pytest.raises(ValueError, match="t_material_id and my_material_id"):
        three_d.validate_references()
    three_d_ok = Project(
        ndm=3,
        ndf=6,
        nodes=nodes,
        materials=mats,
        elements=[_plasticity(t_material_id=2, my_material_id=2)],
    )
    three_d_ok.validate_references()
