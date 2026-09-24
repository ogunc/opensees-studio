"""OpenSeesRunner emission of elastomeric bearing elements (live 3.8.0 signature)."""

from __future__ import annotations

from unittest.mock import MagicMock, call

import pytest

from opensees_studio.core import (
    ElasticUniaxial,
    ElastomericBearingBoucWenElement,
    ElastomericBearingPlasticityElement,
    Node,
    Project,
)
from opensees_studio.services import OpenSeesRunner

MATS = [ElasticUniaxial(id=1, E=1e5), ElasticUniaxial(id=2, E=1e4)]
BASE = dict(id=7, nodes=(1, 2), k_init=10.0, qd=5.0, alpha1=0.1, p_material_id=1, mz_material_id=2)


def _project(ndm: int, element, top=(0.0, 0.0, 0.0)):  # type: ignore[no-untyped-def]
    ndf = 3 if ndm == 2 else 6
    return Project(
        ndm=ndm,
        ndf=ndf,
        nodes=[
            Node(id=1, coords=(0, 0, 0), restraint=(True,) * 6),
            Node(id=2, coords=top),
        ],
        materials=MATS,
        elements=[element],
    )


def _element_call(project: Project):  # type: ignore[no-untyped-def]
    ops = MagicMock()
    OpenSeesRunner(project, ops_module=ops).build()
    calls = [c for c in ops.method_calls if c[0] == "element"]
    assert len(calls) == 1
    return calls[0]


def test_plasticity_2d_minimal_writes_default_orient() -> None:
    el = ElastomericBearingPlasticityElement(**BASE)
    assert _element_call(_project(2, el)) == call.element(
        "elastomericBearingPlasticity",
        7,
        1,
        2,
        10.0,
        5.0,
        0.1,
        0.0,
        2.0,
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


def test_plasticity_3d_with_every_flag() -> None:
    el = ElastomericBearingPlasticityElement(
        **BASE,
        alpha2=0.05,
        mu=3.0,
        t_material_id=2,
        my_material_id=1,
        orient=(0, 0, 1, 0, 1, 0),
        shear_dist=0.3,
        do_rayleigh=True,
        mass=0.25,
    )
    assert _element_call(_project(3, el)) == call.element(
        "elastomericBearingPlasticity",
        7,
        1,
        2,
        10.0,
        5.0,
        0.1,
        0.05,
        3.0,
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
    )


def test_bouc_wen_2d_and_3d() -> None:
    el = ElastomericBearingBoucWenElement(**BASE, eta=2.0, beta=0.6, gamma=0.4, mass=0.1)
    two_d = _element_call(_project(2, el))
    assert two_d == call.element(
        "elastomericBearingBoucWen",
        7,
        1,
        2,
        10.0,
        5.0,
        0.1,
        0.0,
        2.0,
        2.0,
        0.6,
        0.4,
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
        "-mass",
        0.1,
    )
    el3 = el.model_copy(update={"t_material_id": 2, "my_material_id": 2})
    three_d = _element_call(_project(3, el3))
    assert three_d.args[12:20] == ("-P", 1, "-T", 2, "-My", 2, "-Mz", 2)
    assert three_d.args[20:27] == ("-orient", 0.0, 0.0, 1.0, 1.0, 0.0, 0.0)
    assert three_d.args[27:] == ("-mass", 0.1)


def test_default_orient_follows_the_element_axis_for_separated_nodes() -> None:
    el = ElastomericBearingPlasticityElement(**BASE)
    # 2D bearing standing on the X axis: x along +X, shear along -Y (perpendicular)
    horizontal = _element_call(_project(2, el, top=(2.0, 0.0, 0.0)))
    assert horizontal.args[13:20] == ("-orient", 1.0, 0.0, 0.0, 0.0, -1.0, 0.0)
    # 3D bearing along +Y: x = +Y, y = up x axis = (0,0,1) x (0,1,0) = (-1, 0, 0)
    el3 = el.model_copy(update={"t_material_id": 2, "my_material_id": 2})
    along_y = _element_call(_project(3, el3, top=(0.0, 3.0, 0.0)))
    assert along_y.args[17:24] == ("-orient", 0.0, 1.0, 0.0, -1.0, 0.0, 0.0)
    # 3D vertical bearing (coincident nodes): x = +Z, y = +X
    vertical = _element_call(_project(3, el3))
    assert vertical.args[17:24] == ("-orient", 0.0, 0.0, 1.0, 1.0, 0.0, 0.0)


def test_3d_bearing_without_t_and_my_materials_is_refused() -> None:
    el = ElastomericBearingPlasticityElement(**BASE)
    with pytest.raises(ValueError, match="t_material_id and my_material_id"):
        OpenSeesRunner(_project(3, el), ops_module=MagicMock()).build()
