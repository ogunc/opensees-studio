"""OpenSeesRunner emission of flatSliderBearing and singleFPBearing (live 3.8.0 signature)."""

from __future__ import annotations

from unittest.mock import MagicMock, call

import pytest

from opensees_studio.core import (
    CoulombFriction,
    ElasticUniaxial,
    FlatSliderBearingElement,
    Node,
    Project,
    SingleFPBearingElement,
)
from opensees_studio.services import OpenSeesRunner

MATS = [ElasticUniaxial(id=1, E=1e5), ElasticUniaxial(id=2, E=1e4)]
FRICTION = [CoulombFriction(id=3, mu=0.1)]
BASE = dict(
    id=7, nodes=(1, 2), friction_model_id=3, k_init=1000.0, p_material_id=1, mz_material_id=2
)


def _project(ndm: int, element, top=(0.0, 0.0, 0.0)):  # type: ignore[no-untyped-def]
    return Project(
        ndm=ndm,
        ndf=3 if ndm == 2 else 6,
        nodes=[Node(id=1, coords=(0, 0, 0), restraint=(True,) * 6), Node(id=2, coords=top)],
        materials=MATS,
        friction_models=FRICTION,
        elements=[element],
    )


def _calls(project: Project):  # type: ignore[no-untyped-def]
    ops = MagicMock()
    OpenSeesRunner(project, ops_module=ops).build()
    return ops.method_calls


def test_flat_slider_2d_minimal_after_the_friction_model() -> None:
    calls = _calls(_project(2, FlatSliderBearingElement(**BASE)))
    names = [c[0] for c in calls]
    assert names.index("frictionModel") < names.index("element")
    assert [c for c in calls if c[0] == "element"] == [
        call.element(
            "flatSliderBearing",
            7,
            1,
            2,
            3,
            1000.0,
            "-P",
            1,
            "-Mz",
            2,
            "-orient",
            0.0,
            1.0,
            0.0,
            1.0,
            0.0,
            0.0,
        )
    ]


def test_single_fp_3d_with_every_flag() -> None:
    el = SingleFPBearingElement(
        **BASE,
        r_eff=2.0,
        t_material_id=2,
        my_material_id=1,
        orient=(0, 0, 1, 0, 1, 0),
        shear_dist=0.3,
        do_rayleigh=True,
        mass=0.25,
        max_iter=30,
        tol=1e-10,
    )
    (element_call,) = [c for c in _calls(_project(3, el)) if c[0] == "element"]
    assert element_call == call.element(
        "singleFPBearing",
        7,
        1,
        2,
        3,
        2.0,
        1000.0,
        "-P",
        1,
        "-T",
        2,
        "-My",
        1,
        "-Mz",
        2,
        "-orient",
        0.0,
        0.0,
        1.0,
        0.0,
        1.0,
        0.0,
        "-shearDist",
        0.3,
        "-doRayleigh",
        "-mass",
        0.25,
        "-iter",
        30,
        1e-10,
    )


def test_single_fp_2d_default_iter_is_not_written() -> None:
    (element_call,) = [
        c
        for c in _calls(_project(2, SingleFPBearingElement(**BASE, r_eff=2.0)))
        if c[0] == "element"
    ]
    assert element_call.args[:7] == ("singleFPBearing", 7, 1, 2, 3, 2.0, 1000.0)
    assert "-iter" not in element_call.args
    assert element_call.args[-6:] == (0.0, 1.0, 0.0, 1.0, 0.0, 0.0)


def test_default_orient_follows_the_element_axis() -> None:
    el = FlatSliderBearingElement(**BASE)
    (horizontal,) = [c for c in _calls(_project(2, el, top=(2.0, 0.0, 0.0))) if c[0] == "element"]
    assert horizontal.args[10:17] == ("-orient", 1.0, 0.0, 0.0, 0.0, -1.0, 0.0)
    el3 = el.model_copy(update={"t_material_id": 2, "my_material_id": 2})
    (vertical,) = [c for c in _calls(_project(3, el3)) if c[0] == "element"]
    assert vertical.args[14:21] == ("-orient", 0.0, 0.0, 1.0, 1.0, 0.0, 0.0)


def test_missing_references_are_refused_before_emission() -> None:
    project = _project(3, FlatSliderBearingElement(**BASE))
    with pytest.raises(ValueError, match="t_material_id and my_material_id"):
        OpenSeesRunner(project, ops_module=MagicMock()).build()
    project = _project(2, FlatSliderBearingElement(**BASE)).model_copy(
        update={"friction_models": []}
    )
    with pytest.raises(ValueError, match="missing friction model 3"):
        OpenSeesRunner(project, ops_module=MagicMock()).build()
