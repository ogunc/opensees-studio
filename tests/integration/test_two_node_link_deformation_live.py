"""twoNodeLink basic deformation results in real OpenSeesPy runs (D1 to D5).

The runner returns a twoNodeLink's basicDeformation next to its basicForce: in the
static result (``StaticResults.element_deformations``) and as a transient history
(``TransientResults.element_deformation_history``), one value per -dir direction in
the order and sign of the forces. With elastic materials each deformation is its
force divided by its stiffness; under a prescribed top rotation it carries the shear
distance term of CC-015 T3. A model without a twoNodeLink returns none. Each test
prints its measured numbers (``pytest -s`` shows them).
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

ops = pytest.importorskip("openseespy.opensees")

from opensees_studio.core import (  # noqa: E402
    ElasticUniaxial,
    LinearTimeSeries,
    NodalLoad,
    Node,
    PlainLoadPattern,
    Project,
    StaticCase,
    TransientCase,
    TrigTimeSeries,
    TwoNodeLinkElement,
    ZeroLengthElement,
)
from opensees_studio.services.opensees_runner import OpenSeesRunner  # noqa: E402

FIXED = (True,) * 6
TOL = {"rel": 1e-9, "abs": 1e-12}
K1, K2, K3, L = 1000.0, 10.0, 40.0, 0.5


def _static(
    nodes: list[Node],
    elements: list[object],
    loads: dict[int, tuple[float, ...]],
    materials: list[object],
) -> Project:
    return Project(
        ndm=3,
        ndf=6,
        nodes=nodes,
        materials=materials,
        elements=elements,
        time_series=[LinearTimeSeries(id=1)],
        load_patterns=[
            PlainLoadPattern(
                id=1,
                time_series_id=1,
                nodal_loads=[NodalLoad(node_id=n, forces=f) for n, f in loads.items()],
            )
        ],
        analyses=[StaticCase(id=1, pattern_ids=[1])],
    )


def _run(project: Project, case_id: int = 1, tmp: Path | None = None):  # type: ignore[no-untyped-def]
    case = next(c for c in project.analyses if c.id == case_id)
    return OpenSeesRunner(project).run(case, tmp)


# D1: orientation (the CC-015 T2 cases)
@pytest.mark.parametrize("angle", [0.0, 90.0, 45.0, 135.0])
@pytest.mark.parametrize("load", [(1.0, 0.0), (0.0, 1.0)], ids=["+X", "+Y"])
def test_d1_deformation_is_force_over_stiffness(angle: float, load: tuple[float, float]) -> None:
    a = math.radians(angle)
    p = _static(
        [
            Node(id=1, coords=(0, 0, 0), restraint=FIXED),
            Node(id=2, coords=(0, 0, L), restraint=(False,) * 3 + (True,) * 3),
        ],
        [
            TwoNodeLinkElement(
                id=1,
                nodes=(1, 2),
                material_ids=(1, 2, 3),
                dofs=(1, 2, 3),
                orient_y=(math.cos(a), math.sin(a), 0.0),
            )
        ],
        {2: (load[0], load[1], 0, 0, 0, 0)},
        [ElasticUniaxial(id=1, E=K1), ElasticUniaxial(id=2, E=K2), ElasticUniaxial(id=3, E=K3)],
    )
    res = _run(p)
    f = res.element_forces[1][-1]
    d = res.element_deformations[1][-1]
    u = res.node_disp[2][-1, :3]
    y = np.array([math.cos(a), math.sin(a), 0.0])
    z = np.array([-math.sin(a), math.cos(a), 0.0])
    print(f"D1 angle {angle} load {load}: deformation {list(d)}, force / k "
          f"{[f[0] / K1, f[1] / K2, f[2] / K3]}, u.y {float(y @ u)!r}, u.z {float(z @ u)!r}")  # fmt: skip
    assert res.element_deformations[1].shape == res.element_forces[1].shape
    assert list(d) == pytest.approx([f[0] / K1, f[1] / K2, f[2] / K3], **TOL)
    assert list(d) == pytest.approx([float(u[2]), float(y @ u), float(z @ u)], **TOL)


# D2: shear distance (the CC-015 T3 cases)
@pytest.mark.parametrize("ratio", [0.5, 0.25, 1.0])
def test_d2_shear_distance_force_over_stiffness(ratio: float) -> None:
    v = 2.0
    p = _static(
        [
            Node(id=1, coords=(0, 0, 0), restraint=FIXED),
            Node(id=2, coords=(0, 0, L), restraint=(False,) + (True,) * 5),
        ],
        [
            TwoNodeLinkElement(
                id=1,
                nodes=(1, 2),
                material_ids=(2,),
                dofs=(2,),
                orient_y=(1.0, 0.0, 0.0),
                shear_dist=(ratio, ratio),
            )
        ],
        {2: (v, 0, 0, 0, 0, 0)},
        [ElasticUniaxial(id=2, E=K2)],
    )
    res = _run(p)
    f = res.element_forces[1][-1]
    d = res.element_deformations[1][-1]
    print(f"D2 r {ratio}: deformation {list(d)}, force / k {f[0] / K2!r}, V / k {v / K2!r}")
    assert list(d) == pytest.approx([f[0] / K2], **TOL)
    assert list(d) == pytest.approx([v / K2], **TOL)


@pytest.mark.parametrize("ratio", [0.5, 0.25, 1.0])
def test_d3_prescribed_rotation_equals_t3(ratio: float) -> None:
    theta = 0.01
    p = _static(
        [
            Node(id=1, coords=(0, 0, 0), restraint=FIXED),
            Node(id=2, coords=(0, 0, L), restraint=(True, True, False, True, False, True)),
        ],
        [
            TwoNodeLinkElement(
                id=1,
                nodes=(1, 2),
                material_ids=(1, 2),
                dofs=(1, 2),
                orient_y=(1.0, 0.0, 0.0),
                shear_dist=(ratio, ratio),
            )
        ],
        {2: (0, 0, 0, 0, 0, 0)},
        [ElasticUniaxial(id=1, E=K1), ElasticUniaxial(id=2, E=K2)],
    )
    # Transformation, as T3: the Plain handler does not impose a nonzero sp.
    case = p.analyses[0].model_copy(update={"constraints": "Transformation"})
    runner = OpenSeesRunner(p)
    runner.build()
    ops.timeSeries("Constant", 9)
    ops.pattern("Plain", 9, 9)
    ops.sp(2, 5, theta)
    res = runner._run_static(case)  # the runner's static path, rotation prescribed
    d = res.element_deformations[1][-1]
    f = res.element_forces[1][-1]
    print(f"D3 r {ratio}: theta {res.node_disp[2][-1, 4]!r}, deformation {list(d)}, "
          f"(1 - r) L theta {(1 - ratio) * L * theta!r}, force {list(f)}")  # fmt: skip
    assert res.node_disp[2][-1, 4] == pytest.approx(theta, **TOL)
    assert abs(d[1]) == pytest.approx((1.0 - ratio) * L * theta, **TOL)
    assert list(d) == pytest.approx([f[0] / K1, f[1] / K2], **TOL)


# D4: transient history
def test_d4_transient_deformation_history(tmp_path: Path) -> None:
    p = Project(
        ndm=3,
        ndf=6,
        nodes=[
            Node(id=1, coords=(0, 0, 0), restraint=FIXED),
            Node(
                id=2,
                coords=(0, 0, 0.153),
                restraint=(False,) * 3 + (True,) * 3,
                mass=(0.2, 0.2, 0.2, 0, 0, 0),
            ),
        ],
        materials=[
            ElasticUniaxial(id=1, E=K1),
            ElasticUniaxial(id=2, E=K2),
            ElasticUniaxial(id=3, E=K3),
        ],
        elements=[
            TwoNodeLinkElement(
                id=1,
                nodes=(1, 2),
                material_ids=(1, 2, 3),
                dofs=(1, 2, 3),
                orient_y=(1.0, 0.0, 0.0),
                shear_dist=(0.5, 0.5),
            )
        ],
        time_series=[TrigTimeSeries(id=1, t_end=1.0, period=0.25, factor=0.5)],
        load_patterns=[
            PlainLoadPattern(
                id=1,
                time_series_id=1,
                nodal_loads=[NodalLoad(node_id=2, forces=(1, 0.5, -0.2, 0, 0, 0))],
            )
        ],
        analyses=[TransientCase(id=1, pattern_ids=[1], dt=0.005, n_steps=200)],
    )
    res = _run(p, 1, tmp_path)
    d = res.element_deformation_history(1)
    f = res.element_force_history(1)
    u = res.node_disp_history(2)
    # The recorders write 6 significant digits: each value is within 5e-6 of itself.
    scale = 1e-5 * np.abs(d) + 1e-12
    err = float((np.abs(d - f / np.array([K1, K2, K3])) / scale).max())
    err_u = float((np.abs(d - u[:, [2, 0, 1]]) / scale).max())
    print(f"D4 steps {res.n_steps}; shape {d.shape}; peak |d| {list(np.abs(d).max(axis=0))}; "
          f"max |d - f / k| / scale {err!r}; max |d - u| / scale {err_u!r}")  # fmt: skip
    assert d.shape == f.shape == (200, 3)
    assert err <= 1.0
    assert err_u <= 1.0
    assert float(np.abs(d).max()) > 1e-3


# D5: no twoNodeLink, no deformation
def test_d5_model_without_a_link_returns_no_deformation(tmp_path: Path) -> None:
    import h5py

    nodes = [
        Node(id=1, coords=(0, 0, 0), restraint=FIXED),
        Node(
            id=2,
            coords=(0, 0, 0),
            restraint=(False,) * 3 + (True,) * 3,
            mass=(0.2, 0.2, 0.2, 0, 0, 0),
        ),
    ]
    elements = [ZeroLengthElement(id=1, nodes=(1, 2), material_ids=(1, 2, 3), dofs=(3, 1, 2))]
    mats = [ElasticUniaxial(id=1, E=K1), ElasticUniaxial(id=2, E=K2), ElasticUniaxial(id=3, E=K3)]
    static = _run(_static(nodes, elements, {2: (1.0, 0, 0, 0, 0, 0)}, mats))
    assert static.element_deformations == {}
    p = Project(
        ndm=3,
        ndf=6,
        nodes=nodes,
        materials=mats,
        elements=elements,
        time_series=[TrigTimeSeries(id=1, t_end=1.0, period=0.25, factor=0.5)],
        load_patterns=[
            PlainLoadPattern(
                id=1,
                time_series_id=1,
                nodal_loads=[NodalLoad(node_id=2, forces=(1, 0, 0, 0, 0, 0))],
            )
        ],
        analyses=[TransientCase(id=1, pattern_ids=[1], dt=0.005, n_steps=20)],
    )
    res = _run(p, 1, tmp_path)
    with h5py.File(res.h5_path, "r") as f:
        keys = sorted(f["elements/1"].keys())
    files = sorted(x.name for x in tmp_path.rglob("*.out"))
    print(f"D5 static deformations {static.element_deformations}; h5 element keys {keys}; "
          f"recorder files {files}")  # fmt: skip
    assert keys == ["forces"]
    assert not any("basicDeformation" in name for name in files)
    with pytest.raises(KeyError):
        res.element_deformation_history(1)
