"""twoNodeLink and TripleFrictionPendulum solved by OpenSees."""

from __future__ import annotations

import pytest

from opensees_studio.core import (
    CoulombFriction,
    ElasticUniaxial,
    LinearTimeSeries,
    NodalLoad,
    Node,
    PlainLoadPattern,
    Project,
    StaticCase,
    TransientCase,
    TripleFrictionPendulumElement,
    TwoNodeLinkElement,
)
from opensees_studio.services.opensees_runner import OpenSeesRunner

pytest.importorskip("openseespy.opensees")

ROT_FIXED = (False, False, False, True, True, True)


def _run(project: Project):  # type: ignore[no-untyped-def]
    return OpenSeesRunner(project).run(project.analyses[0])


def _loaded(nodes, materials, element, forces, ndm=3, ndf=6, **extra) -> Project:  # type: ignore[no-untyped-def]
    return Project(
        ndm=ndm,
        ndf=ndf,
        nodes=nodes,
        materials=materials,
        elements=[element],
        time_series=[LinearTimeSeries(id=1)],
        load_patterns=[
            PlainLoadPattern(
                id=1, time_series_id=1, nodal_loads=[NodalLoad(node_id=2, forces=forces)]
            )
        ],
        analyses=[
            StaticCase(
                id=1,
                name="s",
                pattern_ids=[1],
                n_steps=10,
                load_factor_increment=0.1,
                algorithm="Newton",
            )
        ],
        **extra,
    )


def test_a_coincident_link_with_its_own_axes() -> None:
    link = TwoNodeLinkElement(
        id=1,
        nodes=(1, 2),
        material_ids=(1, 2, 3),
        dirs=(1, 2, 3),
        orient=(0.0, 0.0, 1.0, 1.0, 0.0, 0.0),  # local x up, local y along global X
    )
    project = _loaded(
        [
            Node(id=1, coords=(0.0, 0.0, 0.0), restraint=(True,) * 6),
            Node(id=2, coords=(0.0, 0.0, 0.0), restraint=ROT_FIXED),
        ],
        [ElasticUniaxial(id=1, E=1e9), ElasticUniaxial(id=2, E=1e3), ElasticUniaxial(id=3, E=2e3)],
        link,
        (10.0, 10.0, 0.0, 0.0, 0.0, 0.0),
    )
    disp = _run(project).node_disp[2][-1]
    # local y = global X (k 1e3), local z = x × y = global Y (k 2e3)
    assert (float(disp[0]), float(disp[1])) == pytest.approx((0.01, 0.005), rel=1e-9)


def test_a_2d_axial_link() -> None:
    link = TwoNodeLinkElement(id=1, nodes=(1, 2), material_ids=(1,), dirs=(1,))
    project = _loaded(
        [
            Node(id=1, coords=(0.0, 0.0, 0.0), restraint=(True,) * 6),
            Node(id=2, coords=(2.0, 0.0, 0.0), restraint=(False, False, True, False, True, False)),
        ],
        [ElasticUniaxial(id=1, E=500.0)],
        link,
        (5.0, 0.0, 0.0, 0.0, 0.0, 0.0),
        ndm=2,
        ndf=3,
    )
    assert float(_run(project).node_disp[2][-1][0]) == pytest.approx(0.01, rel=1e-9)


def test_a_triple_friction_pendulum_under_gravity_then_shaking(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """The OpenSees way: a gravity case in steps, held (preload), then a transient."""
    tfp = TripleFrictionPendulumElement(
        id=1,
        nodes=(1, 2),
        friction_model_ids=(1, 2, 3),
        vertical_material_id=1,
        rot_z_material_id=1,
        rot_x_material_id=1,
        rot_y_material_id=1,
        L1=0.36,
        L2=2.1,
        L3=2.1,
        d1=0.05,
        d2=0.4,
        d3=0.4,
        W=1e5,
    )
    m = 1e5 / 9.81
    project = Project(
        ndm=3,
        ndf=6,
        nodes=[
            Node(id=1, coords=(0.0, 0.0, 0.0), restraint=(True,) * 6),
            Node(id=2, coords=(0.0, 0.0, 0.0), restraint=ROT_FIXED, mass=(m, m, m, 0, 0, 0)),
        ],
        materials=[ElasticUniaxial(id=1, E=1e10)],
        friction_models=[
            CoulombFriction(id=1, mu=0.012),
            CoulombFriction(id=2, mu=0.052),
            CoulombFriction(id=3, mu=0.12),
        ],
        elements=[tfp],
        time_series=[LinearTimeSeries(id=1), LinearTimeSeries(id=2, factor=1e4)],
        load_patterns=[
            PlainLoadPattern(
                id=1,
                time_series_id=1,
                nodal_loads=[NodalLoad(node_id=2, forces=(0, 0, -1e5, 0, 0, 0))],
            ),
            PlainLoadPattern(
                id=2,
                time_series_id=2,
                nodal_loads=[NodalLoad(node_id=2, forces=(1, 0, 0, 0, 0, 0))],
            ),
        ],
        analyses=[
            StaticCase(
                id=1,
                name="gravity",
                pattern_ids=[1],
                n_steps=10,
                load_factor_increment=0.1,
                algorithm="Newton",
                max_iter=100,
            ),
        ],
    )
    case = TransientCase(
        id=2, name="push", pattern_ids=[2], preload_case_ids=[1], dt=0.01, n_steps=20, max_iter=100
    )
    project.analyses.append(case)
    results = OpenSeesRunner(project).run(case, results_dir=tmp_path)
    assert results.n_steps == 20
    history = results.node_disp_history(2)
    assert float(history[-1][2]) == pytest.approx(-1e5 / 1e10, rel=1e-3)
    assert float(history[-1][0]) > 0.0


def test_a_tfp_in_2d_is_refused() -> None:
    project = Project(
        ndm=2,
        ndf=3,
        nodes=[Node(id=1, coords=(0.0, 0.0, 0.0)), Node(id=2, coords=(0.0, 0.0, 0.0))],
        materials=[ElasticUniaxial(id=1, E=1.0)],
        friction_models=[CoulombFriction(id=1, mu=0.1)],
        elements=[
            TripleFrictionPendulumElement(
                id=1,
                nodes=(1, 2),
                friction_model_ids=(1, 1, 1),
                vertical_material_id=1,
                rot_z_material_id=1,
                rot_x_material_id=1,
                rot_y_material_id=1,
                L1=1,
                L2=1,
                L3=1,
                d1=1,
                d2=1,
                d3=1,
                W=1,
            )
        ],
    )
    with pytest.raises(ValueError, match="needs a 3D model"):
        project.validate_references()
