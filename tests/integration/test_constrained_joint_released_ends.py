"""Frame end releases at joints a user equalDOF or rigid link constrains, against hand-built OpenSeesPy.

A beam (3 -> 4) is released at end i, at joint 3, which hangs off column top 2:

* ``equalDOF``: joint 3 sits on its own column 0.5 m from column top 2 and
  follows it in the horizontal translations only (U1 in 2D, U1 and U2 in 3D);
* ``rigidLink``: joint 3 is the constrained node of ``rigidLink beam`` from
  column top 2, 0.5 m away (a panel zone).

Column 6 -> 4 carries the beam's other end. A released end used to hang off a
hidden node ``equalDOF``'d to joint 3: a constraint chain that OpenSees 3.8's
Transformation handler (and every eigen analysis) solves without a warning into
wrong results. Each variant is checked against references built by hand in
this file:

* **pinned** (M3, and M2 in 3D): the periods and the static case against the
  element releasing itself (``-release`` / ``-releasez`` / ``-releasey``), and
  the static case against hidden nodes solved with the Lagrange handler (which
  chains exactly, but cannot run an eigen analysis), to 1e-9;
* **fixity** (the same ends with partial-fixity springs): the periods against
  ``ModElasticBeam2d`` / ``ModElasticBeam3d`` carrying the series stiffness of
  member and springs, the static case against the Lagrange model. The runner
  holds the end with penalty springs ``f = CONSTRAINED_PENALTY_FACTOR`` times
  the member's stiffness, in series with it: the beam's own axial mode comes
  out about ``1 / f`` = 1e-5 too soft (measured 1e-5, the other modes 1e-7 and
  better), so the eigenvalues are held to ``2 / f``; the static case is off by
  2e-7 (measured), held to 1e-6.

The hidden-node chain itself, under Transformation, is off by more than 1e-3
in every variant: the comparison would catch the old plan.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import openseespy.opensees as ops
import pytest

from opensees_studio.core import (
    ElasticBeamColumn,
    ElasticSection,
    EndRelease,
    EqualDOFConstraint,
    FrameReleases,
    LinearTimeSeries,
    ModalCase,
    NodalLoad,
    Node,
    PlainLoadPattern,
    Project,
    RigidLink,
    StaticCase,
    UniformElementLoad,
)
from opensees_studio.services.frame_members import CONSTRAINED_PENALTY_FACTOR
from opensees_studio.services.opensees_runner import OpenSeesRunner

E, G = 30e9, 12e9
COLUMN = {"A": 0.25, "Iz": 0.0052, "Iy": 0.0052, "J": 0.0088}
BEAM = {"A": 0.18, "Iz": 0.0054, "Iy": 0.00135, "J": 0.0037}
H, DX, SPAN = 3.0, 0.5, 6.0
MASS, INERTIA = 1000.0, 10.0
Q = 1.0e4  # beam load, downwards
K2, K3 = 2.0e7, 5.0e7  # partial fixity about local y / z at end i
N_MODES = 4

VARIANTS = [
    (ndm, link, release)
    for ndm in (2, 3)
    for link in ("equalDOF", "rigidLink")
    for release in ("pinned", "fixity")
]


def _xyz(ndm: int, h: float, v: float) -> tuple[float, ...]:
    """A point of the frame's plane: (h, v) in 2D, (h, 0, v) in 3D."""
    return (h, v) if ndm == 2 else (h, 0.0, v)


def _released(ndm: int, release: str) -> tuple[str, ...]:
    return ("M3",) if ndm == 2 else ("M2", "M3")


def _springs(ndm: int, release: str) -> dict[str, float]:
    if release == "pinned":
        return {}
    return {"M3": K3} if ndm == 2 else {"M2": K2, "M3": K3}


def _tied_dofs(ndm: int) -> tuple[int, ...]:
    """What the user equalDOF ties: the horizontal translations."""
    return (1,) if ndm == 2 else (1, 2)


def _loads(ndm: int) -> dict[int, tuple[float, ...]]:
    """Nodal loads in the model's DOFs."""
    if ndm == 2:
        return {4: (1e5, -3e4, 0.0), 2: (2e4, 0.0, 1e4)}
    return {4: (1e5, 2e4, -3e4, 0.0, 0.0, 0.0), 2: (0.0, 1e4, 0.0, 5e3, 0.0, 0.0)}


# ───────────────────────────── the application's model ─────────────────────────────
def _project(ndm: int, link: str, release: str) -> Project:
    # A 2D model lives in the X-Z plane: its DOFs are Ux, Uz, Ry (slots 0, 2, 4).
    fixed = (True,) * 6 if ndm == 3 else (True, False, True, False, True, False)
    mass = (MASS,) * 3 + (INERTIA,) * 3 if ndm == 3 else (MASS, 0.0, MASS, 0.0, INERTIA, 0.0)

    def node(tag: int, h: float, v: float, **kw: Any) -> Node:
        return Node(id=tag, coords=(h, 0.0, v), **kw)

    nodes = [
        node(1, 0.0, 0.0, restraint=fixed),
        node(2, 0.0, H, mass=mass),
        node(3, DX, H, mass=mass),
        node(4, SPAN, H, mass=mass),
        node(6, SPAN, 0.0, restraint=fixed),
    ]
    elements = [
        ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1),
        ElasticBeamColumn(id=2, nodes=(6, 4), section_id=1),
        ElasticBeamColumn(
            id=3,
            nodes=(3, 4),
            section_id=2,
            releases=FrameReleases(
                i=EndRelease(released=_released(ndm, release), springs=_springs(ndm, release))
            ),
        ),
    ]
    mp_constraints: list[EqualDOFConstraint] = []
    rigid_links: list[RigidLink] = []
    if link == "equalDOF":
        nodes.append(node(7, DX, 0.0, restraint=fixed))
        elements.append(ElasticBeamColumn(id=4, nodes=(7, 3), section_id=1))
        mp_constraints.append(
            EqualDOFConstraint(retained_node=2, constrained_node=3, dofs=_tied_dofs(ndm))
        )
    else:
        rigid_links.append(RigidLink(kind="beam", retained_node=2, constrained_node=3))
    nodal = [
        # OpenSees' 2D DOFs (x, y, rz) are the global Ux, Uz and -Ry (core.plane).
        NodalLoad(node_id=n, forces=(f[0], 0.0, f[1], 0.0, -f[2], 0.0) if ndm == 2 else f)
        for n, f in _loads(ndm).items()
    ]
    beam_load = (
        UniformElementLoad(element_id=3, wy=-Q)
        if ndm == 2
        else UniformElementLoad(element_id=3, wz=-Q)
    )
    return Project(
        ndm=ndm,
        ndf=3 if ndm == 2 else 6,
        nodes=nodes,
        sections=[
            ElasticSection(id=1, E=E, G=G, **COLUMN),
            ElasticSection(id=2, E=E, G=G, **BEAM),
        ],
        elements=elements,
        mp_constraints=mp_constraints,
        rigid_links=rigid_links,
        time_series=[LinearTimeSeries(id=1)],
        load_patterns=[
            PlainLoadPattern(id=1, time_series_id=1, nodal_loads=nodal, element_loads=[beam_load])
        ],
        analyses=[
            # Transformation is what a model with a rigid link runs anyway, and
            # what every eigen analysis uses.
            StaticCase(
                id=1,
                name="static",
                pattern_ids=[1],
                system="UmfPack",
                constraints="Transformation",
                tolerance=1e-10,
            ),
            ModalCase(id=2, name="modal", n_modes=N_MODES),
        ],
    )


def _app(project: Project, case_id: int, tmp_path: Path) -> np.ndarray:
    case = next(c for c in project.analyses if c.id == case_id)
    results = OpenSeesRunner(project).run(case, results_dir=tmp_path / case.name)
    if case_id == 2:
        return np.asarray(results.eigenvalues, dtype=float)
    disp = np.array([results.node_disp[n][-1] for n in (2, 3, 4)], dtype=float)
    if project.ndm == 2:
        disp[:, 2] *= -1.0  # back to OpenSees' rz, which the references report
    return disp


# ───────────────────────────── the hand-built references ─────────────────────────────
def _series(ei: float, length: float, k: float) -> tuple[float, float, float]:
    """``(K11, K33, K44)`` of a member with an end-i spring ``k``, over ``E I / L``."""
    flex = length / (6.0 * ei) * np.array([[2.0, -1.0], [-1.0, 2.0]]) + np.diag([1.0 / k, 0.0])
    s = np.linalg.inv(flex) * length / ei
    return s[0, 0], s[1, 1], s[0, 1]


def _hand(ndm: int, link: str, release: str, form: str, case: str) -> np.ndarray:
    """``form``: ``elem`` (the element releases), ``mod`` (ModElasticBeam), ``lagrange``
    (a hidden node under Lagrange) or ``chain`` (the same under Transformation)."""
    ndf = 3 if ndm == 2 else 6
    ops.wipe()
    ops.model("basic", "-ndm", ndm, "-ndf", ndf)
    fixed = [1] * ndf
    ops.node(1, *_xyz(ndm, 0.0, 0.0))
    ops.fix(1, *fixed)
    ops.node(2, *_xyz(ndm, 0.0, H))
    ops.node(3, *_xyz(ndm, DX, H))
    ops.node(4, *_xyz(ndm, SPAN, H))
    ops.node(6, *_xyz(ndm, SPAN, 0.0))
    ops.fix(6, *fixed)
    c, b = COLUMN, BEAM
    if ndm == 2:
        ops.geomTransf("Linear", 1)
        ops.geomTransf("Linear", 2)
        col_props: list[Any] = [c["A"], E, c["Iz"], 1]
    else:
        ops.geomTransf("Linear", 1, 1.0, 0.0, 0.0)  # columns
        ops.geomTransf("Linear", 2, 0.0, 0.0, 1.0)  # the beam: local (y, z) = global (Y, Z)
        col_props = [c["A"], E, G, c["J"], c["Iy"], c["Iz"], 1]
    ops.element("elasticBeamColumn", 1, 1, 2, *col_props)
    ops.element("elasticBeamColumn", 2, 6, 4, *col_props)
    if link == "equalDOF":
        ops.node(7, *_xyz(ndm, DX, 0.0))
        ops.fix(7, *fixed)
        ops.element("elasticBeamColumn", 4, 7, 3, *col_props)

    length = SPAN - DX
    beam_props: list[Any] = (
        [b["A"], E, b["Iz"], 2] if ndm == 2 else [b["A"], E, G, b["J"], b["Iy"], b["Iz"], 2]
    )
    springs = _springs(ndm, release)
    hidden = None
    if form == "elem":
        flags: list[Any] = ["-release", 1] if ndm == 2 else ["-releasez", 1, "-releasey", 1]
        ops.element("elasticBeamColumn", 3, 3, 4, *beam_props, *flags)
    elif form == "mod":
        kz = _series(E * b["Iz"], length, springs["M3"])
        if ndm == 2:
            ops.element("ModElasticBeam2d", 3, 3, 4, b["A"], E, b["Iz"], *kz, 2)
        else:
            ky = _series(E * b["Iy"], length, springs["M2"])
            ops.element(
                "ModElasticBeam3d", 3, 3, 4, b["A"], E, G, b["J"], b["Iy"], b["Iz"], *ky, *kz, 2
            )
    else:  # lagrange / chain: the released end on a hidden node tied to joint 3
        hidden = 5
        ops.node(hidden, *_xyz(ndm, DX, H))
        ops.element("elasticBeamColumn", 3, hidden, 4, *beam_props)

    if link == "equalDOF":
        ops.equalDOF(2, 3, *_tied_dofs(ndm))
    else:
        ops.rigidLink("beam", 2, 3)
    if hidden is not None:
        # Translations, and torsion in 3D (the X beam's T is global RX).
        ops.equalDOF(3, hidden, *((1, 2) if ndm == 2 else (1, 2, 3, 4)))
        if springs:
            # The X beam's local (y, z) are global (Y, Z): M2 is RY (5), M3 is RZ.
            rot = {"M2": 5, "M3": 3 if ndm == 2 else 6}
            dirs = sorted(rot[d] for d in springs)
            by_dir = {rot[d]: v for d, v in springs.items()}
            for k, d in enumerate(dirs, start=1):
                ops.uniaxialMaterial("Elastic", k, by_dir[d])
            ops.element("zeroLength", 9, 3, hidden, "-mat", *range(1, len(dirs) + 1), "-dir", *dirs)
    mass = (MASS, MASS, INERTIA) if ndm == 2 else (MASS,) * 3 + (INERTIA,) * 3
    for n in (2, 3, 4):
        ops.mass(n, *mass)

    if case == "modal":
        return np.asarray(ops.eigen("-fullGenLapack", N_MODES), dtype=float)
    ops.timeSeries("Linear", 1)
    ops.pattern("Plain", 1, 1)
    for n, f in _loads(ndm).items():
        ops.load(n, *f)
    if ndm == 2:
        ops.eleLoad("-ele", 3, "-type", "-beamUniform", -Q)
    else:
        ops.eleLoad("-ele", 3, "-type", "-beamUniform", 0.0, -Q)
    ops.system("UmfPack")
    ops.numberer("RCM")
    ops.constraints("Lagrange" if form == "lagrange" else "Transformation")
    ops.test("NormDispIncr", 1e-10, 10)
    ops.algorithm("Linear")
    ops.integrator("LoadControl", 1.0)
    ops.analysis("Static")
    assert ops.analyze(1) == 0
    return np.array([ops.nodeDisp(n) for n in (2, 3, 4)], dtype=float)


def _error(app: np.ndarray, hand: np.ndarray, ndm: int) -> float:
    """Largest difference relative to the largest translation / rotation."""
    split = ndm
    scale = np.concatenate(
        [
            np.full(split, np.abs(hand[:, :split]).max()),
            np.full(hand.shape[1] - split, np.abs(hand[:, split:]).max()),
        ]
    )
    return float((np.abs(app - hand) / scale).max())


def _tolerance(release: str) -> float:
    return 1e-9 if release == "pinned" else 1e-6


# ───────────────────────────── the tests ─────────────────────────────
@pytest.fixture(params=VARIANTS, ids=["-".join(map(str, v)) for v in VARIANTS])
def variant(request: pytest.FixtureRequest) -> tuple[int, str, str]:
    return request.param


def test_the_released_end_does_not_chain_a_constraint(variant: tuple[int, str, str]) -> None:
    ndm, link, release = variant
    runner = OpenSeesRunner(_project(ndm, link, release))
    runner.build()
    plan = runner._frame_plan
    assert not plan.equal_dofs and not plan.rigid_links
    if release == "pinned":
        assert not plan.nodes and not plan.springs
        expected = ("-release", 1) if ndm == 2 else ("-releasez", 1, "-releasey", 1)
        assert plan.members[3].release_args == expected
    else:
        (hidden,) = plan.nodes
        (spring,) = plan.springs
        assert (spring.node_a, spring.node_b) == (3, hidden.tag)
        assert plan.members[3].nodes == (hidden.tag, 4)


def test_periods_match_the_hand_built_model(variant: tuple[int, str, str], tmp_path: Path) -> None:
    ndm, link, release = variant
    app = _app(_project(ndm, link, release), 2, tmp_path)
    hand = _hand(ndm, link, release, "elem" if release == "pinned" else "mod", "modal")
    assert app.shape == hand.shape == (N_MODES,)
    rtol = _tolerance(release) if release == "pinned" else 2.0 / CONSTRAINED_PENALTY_FACTOR
    np.testing.assert_allclose(app, hand, rtol=rtol, atol=0.0)


def test_the_static_case_matches_the_hand_built_models(
    variant: tuple[int, str, str], tmp_path: Path
) -> None:
    ndm, link, release = variant
    app = _app(_project(ndm, link, release), 1, tmp_path)
    references = ["lagrange", "elem"] if release == "pinned" else ["lagrange"]
    for form in references:
        hand = _hand(ndm, link, release, form, "static")
        assert app.shape == hand.shape
        assert _error(app, hand, ndm) <= _tolerance(release), form
    # The hidden node equalDOF'd to joint 3, as the runner used to build it.
    chain = _hand(ndm, link, release, "chain", "static")
    assert _error(chain, hand, ndm) > 1e-3
