"""twoNodeLink and rigidLink beam ties in real OpenSeesPy runs (T1 to T6).

Small models with linear elastic materials (HystereticSM in T6). The runner builds
and runs each model; where a check needs a response the runner does not return
(end moments, link deformations, a prescribed motion), the test reads it from the
same OpenSees domain right after the runner has built or run the model. Each test
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
    HystereticSM,
    LinearTimeSeries,
    ModalCase,
    NodalLoad,
    Node,
    PlainLoadPattern,
    Project,
    RigidLinkConstraint,
    StaticCase,
    TransientCase,
    TrigTimeSeries,
    TwoNodeLinkElement,
    ZeroLengthElement,
)
from opensees_studio.services.opensees_runner import OpenSeesRunner  # noqa: E402

FIXED = (True,) * 6
TOL = {"rel": 1e-9, "abs": 1e-12}


def _static(
    nodes: list[Node],
    elements: list[object],
    loads: dict[int, tuple[float, ...]],
    materials: list[object],
    ties: list[RigidLinkConstraint] | None = None,
) -> Project:
    return Project(
        ndm=3,
        ndf=6,
        nodes=nodes,
        materials=materials,
        elements=elements,
        mp_constraints=ties or [],
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


# ───────────────────────── T1: twoNodeLink against zeroLength ─────────────────────────
def test_t1_axial_response_equals_zero_length() -> None:
    length, k, fz = 0.5, 100.0, -3.0
    only_z = (True, True, False, True, True, True)
    mats = [ElasticUniaxial(id=1, E=k)]
    link = _static(
        [
            Node(id=1, coords=(0, 0, 0), restraint=FIXED),
            Node(id=2, coords=(0, 0, length), restraint=only_z),
        ],
        [TwoNodeLinkElement(id=1, nodes=(1, 2), material_ids=(1,), dofs=(1,))],
        {2: (0, 0, fz, 0, 0, 0)},
        mats,
    )
    zl = _static(
        [
            Node(id=1, coords=(0, 0, 0), restraint=FIXED),
            Node(id=2, coords=(0, 0, 0), restraint=only_z),
        ],
        [ZeroLengthElement(id=1, nodes=(1, 2), material_ids=(1,), dofs=(3,))],
        {2: (0, 0, fz, 0, 0, 0)},
        mats,
    )
    r_link, r_zl = _run(link), _run(zl)
    u_link, u_zl = r_link.node_disp[2][-1, 2], r_zl.node_disp[2][-1, 2]
    f_link, f_zl = r_link.element_forces[1][-1], r_zl.element_forces[1][-1]
    print(
        f"T1 uz link {u_link!r} zeroLength {u_zl!r}; force link {list(f_link)} zeroLength {list(f_zl)}"
    )
    assert u_link == pytest.approx(u_zl, **TOL)
    assert u_link == pytest.approx(fz / k, **TOL)
    assert list(f_link) == pytest.approx(list(f_zl), **TOL)
    assert list(f_link) == pytest.approx([fz], **TOL)
    assert r_link.node_reaction[1][-1, 2] == pytest.approx(-fz, **TOL)


# ───────────────────────── T2: orientation ─────────────────────────
K1, K2, K3, L = 1000.0, 10.0, 40.0, 0.5


def _oriented(angle_deg: float, load: tuple[float, float]) -> Project:
    a = math.radians(angle_deg)
    return _static(
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


@pytest.mark.parametrize("angle", [0.0, 90.0, 45.0, 135.0])
@pytest.mark.parametrize("load", [(1.0, 0.0), (0.0, 1.0)], ids=["+X", "+Y"])
def test_t2_orientation_closed_form(angle: float, load: tuple[float, float]) -> None:
    a = math.radians(angle)
    y = np.array([math.cos(a), math.sin(a), 0.0])
    z = np.array([-math.sin(a), math.cos(a), 0.0])  # z = x cross y with x = +Z
    p = np.array([load[0], load[1], 0.0])
    f2, f3 = float(y @ p), float(z @ p)
    u = y * f2 / K2 + z * f3 / K3
    res = _run(_oriented(angle, load))
    got_u = res.node_disp[2][-1, :3]
    got_f = res.element_forces[1][-1]
    print(f"T2 angle {angle} load {load}: u {list(got_u)} expected {list(u)}; "
          f"forces {list(got_f)} expected [0, {f2}, {f3}]")  # fmt: skip
    assert list(got_u) == pytest.approx(list(u), **TOL)
    assert list(got_f) == pytest.approx([0.0, f2, f3], **TOL)


# ───────────────────────── T3: shear distance ─────────────────────────
@pytest.mark.parametrize("ratio", [0.5, 0.25, 1.0])
def test_t3_end_moments(ratio: float) -> None:
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
    _run(p)
    force = ops.eleResponse(1, "force")  # global: node i then node j, 6 each
    m_i, m_j = force[4], force[10]  # moment about global Y (local z)
    print(f"T3 r {ratio}: M_i {m_i!r} (V r L {v * ratio * L!r}), "
          f"M_j {m_j!r} (V (1 - r) L {v * (1 - ratio) * L!r}), force {force}")  # fmt: skip
    assert abs(m_i) == pytest.approx(v * ratio * L, **TOL)
    assert abs(m_j) == pytest.approx(v * (1.0 - ratio) * L, **TOL)


@pytest.mark.parametrize("ratio", [0.5, 0.25, 1.0])
def test_t3_prescribed_rotation(ratio: float) -> None:
    theta = 0.01
    p = _static(
        [
            Node(id=1, coords=(0, 0, 0), restraint=FIXED),
            # translations X, Y and the rotations X, Z fixed; Z keeps one equation
            # (the axial spring), rotation Y carries the prescribed value.
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
    OpenSeesRunner(p).build()
    ops.timeSeries("Constant", 9)
    ops.pattern("Plain", 9, 9)
    ops.sp(2, 5, theta)
    ops.system("BandGeneral")
    ops.numberer("Plain")
    ops.constraints("Transformation")
    ops.integrator("LoadControl", 1.0)
    ops.algorithm("Linear")
    ops.analysis("Static")
    assert ops.analyze(1) == 0
    rot = ops.nodeDisp(2, 5)
    trans = ops.nodeDisp(2)[:2]
    d = ops.eleResponse(1, "basicDeformation")
    print(f"T3 r {ratio}: theta {rot!r}, top ux uy {trans}, deformation {d}, "
          f"(1 - r) L theta {(1 - ratio) * L * theta!r}")  # fmt: skip
    assert rot == pytest.approx(theta, **TOL)
    assert trans == [0.0, 0.0]
    assert abs(d[1]) == pytest.approx((1.0 - ratio) * L * theta, **TOL)


# ───────────────────────── T4: rigid tie kinematics ─────────────────────────
OFFSET = np.array([0.4, -0.25, 0.6])
RETAINED = np.array([0.1, 0.2, 0.3])


def _tied(loads: dict[int, tuple[float, ...]]) -> Project:
    return _static(
        [
            Node(id=1, coords=(0.1, 0.2, 0.0), restraint=FIXED),
            Node(id=2, coords=tuple(RETAINED)),
            Node(id=3, coords=tuple(RETAINED + OFFSET)),
            # A separate axial spring keeps one equation in the prescribed-motion
            # model, where every DOF of nodes 2 and 3 is prescribed or tied.
            Node(id=4, coords=(1.1, 0.2, 0.0), restraint=(False,) + (True,) * 5),
        ],
        [
            TwoNodeLinkElement(
                id=1, nodes=(1, 2), material_ids=(1, 2, 3, 4, 5, 6), dofs=(1, 2, 3, 4, 5, 6)
            ),
            TwoNodeLinkElement(id=2, nodes=(1, 4), material_ids=(1,), dofs=(1,)),
        ],
        loads,
        [ElasticUniaxial(id=k, E=10.0 * k) for k in range(1, 7)],
        ties=[RigidLinkConstraint(retained_node=2, constrained_node=3)],
    )


def test_t4_prescribed_retained_motion() -> None:
    u = np.array([1e-3, -2e-3, 1.5e-3])
    th = np.array([2e-3, -1e-3, 3e-3])
    OpenSeesRunner(_tied({})).build()
    ops.timeSeries("Constant", 9)
    ops.pattern("Plain", 9, 9)
    for dof, value in enumerate([*u, *th], start=1):
        ops.sp(2, dof, float(value))
    ops.system("BandGeneral")
    ops.numberer("Plain")
    ops.constraints("Transformation")
    ops.integrator("LoadControl", 1.0)
    ops.algorithm("Linear")
    ops.analysis("Static")
    assert ops.analyze(1) == 0
    got = np.array(ops.nodeDisp(3))
    expected = np.concatenate([u + np.cross(th, OFFSET), th])
    print(f"T4 prescribed: node 3 {list(got)} expected {list(expected)}")
    assert list(got) == pytest.approx(list(expected), **TOL)


def test_t4_loaded_through_the_runner() -> None:
    """The runner's own static path (Transformation chosen automatically)."""
    res = _run(_tied({3: (1.0, -2.0, 0.5, 0.3, 0.2, -0.1)}))
    d2, d3 = res.node_disp[2][-1], res.node_disp[3][-1]
    expected = np.concatenate([d2[:3] + np.cross(d2[3:], OFFSET), d2[3:]])
    print(f"T4 runner: node 2 {list(d2)}, node 3 {list(d3)} expected {list(expected)}")
    assert list(d3) == pytest.approx(list(expected), **TOL)
    assert np.abs(d2).max() > 1e-3


# ───────────────────────── T5: modal with a tie and a link ─────────────────────────
def test_t5_modal_period_closed_form() -> None:
    kt, m = 50.0, 2.0
    a, b, c = 0.3, 0.4, 0.25
    p = Project(
        ndm=3,
        ndf=6,
        nodes=[
            Node(id=1, coords=(0, 0, 0), restraint=FIXED),
            Node(id=2, coords=(0, 0, 0.2), restraint=(True,) * 5 + (False,)),
            Node(id=3, coords=(a, b, 0.2 + c), mass=(m, m, m, 0, 0, 0)),
        ],
        materials=[ElasticUniaxial(id=1, E=kt)],
        elements=[TwoNodeLinkElement(id=1, nodes=(1, 2), material_ids=(1,), dofs=(4,))],
        mp_constraints=[RigidLinkConstraint(retained_node=2, constrained_node=3)],
        analyses=[ModalCase(id=1, n_modes=1)],
    )
    res = _run(p)
    t1 = float(res.periods[0])
    expected = 2.0 * math.pi * math.sqrt(m * (a * a + b * b) / kt)
    print(f"T5 T1 {t1!r} closed form {expected!r} rel diff {abs(t1 - expected) / expected:.3e}, "
          f"solver {res.solver}")  # fmt: skip
    assert t1 == pytest.approx(expected, rel=1e-6)


# ───────────────────────── T6: transient, HystereticSM, Rayleigh flag ─────────────────────────
ENV_POS = [(0.12, 0.00067), (0.34, 0.0043), (0.87, 0.0215), (9.21, 0.0804)]
ENV_NEG = [(-0.12, -0.00067), (-0.34, -0.0043), (-0.87, -0.0215), (-9.21, -0.0804)]


def _transient(do_rayleigh: bool) -> Project:
    return Project(
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
        materials=[HystereticSM(id=k, pos_env=ENV_POS, neg_env=ENV_NEG) for k in (1, 2, 3)],
        elements=[
            TwoNodeLinkElement(
                id=1,
                nodes=(1, 2),
                material_ids=(1, 2, 3),
                dofs=(1, 2, 3),
                orient_y=(1.0, 0.0, 0.0),
                do_rayleigh=do_rayleigh,
            )
        ],
        time_series=[TrigTimeSeries(id=1, t_end=1.0, period=0.25, factor=0.5)],
        load_patterns=[
            PlainLoadPattern(
                id=1,
                time_series_id=1,
                nodal_loads=[NodalLoad(node_id=2, forces=(1, 0, 0, 0, 0, 0))],
            )
        ],
        analyses=[
            TransientCase(id=1, pattern_ids=[1], dt=0.005, n_steps=300, rayleigh_beta_k_init=0.02)
        ],
    )


def test_t6_transient_rayleigh_flag(tmp_path: Path) -> None:
    on = _run(_transient(True), 1, tmp_path / "on")
    off = _run(_transient(False), 1, tmp_path / "off")
    assert on.n_steps == off.n_steps == 300
    ux_on, ux_off = on.node_disp_history(2)[:, 0], off.node_disp_history(2)[:, 0]
    f_on = on.element_force_history(1)
    diff = float(np.abs(ux_on - ux_off).max())
    print(f"T6 steps {on.n_steps} {off.n_steps}; peak |ux| on {np.abs(ux_on).max()!r} "
          f"off {np.abs(ux_off).max()!r}; max |difference| {diff!r}; "
          f"force columns {f_on.shape[1]}, peak shear {np.abs(f_on[:, 1]).max()!r}")  # fmt: skip
    assert f_on.shape == (300, 3)
    assert diff > 1e-6
