"""The model check accepts exactly the equalDOF / rigidLink layouts Transformation solves right.

Four cantilever columns of different stiffness carry random loads at their
tops 2, 3, 5 and 7, tied by user constraints. OpenSees 3.8's Transformation
handler (every eigen analysis uses it) is compared with Lagrange: a layout
``constraint_chain_problems`` accepts must give the same displacements and
the same eigenvalues as a Lagrange-derived reference, and one it refuses is
one Transformation gets wrong. If a future OpenSees fixes the chains, the
"refused" half fails and says the refusal can be lifted.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence

import numpy as np
import openseespy.opensees as ops
import pytest

from opensees_studio.core import EqualDOFConstraint, Node, Project, RigidLink
from opensees_studio.core.diaphragms import constraint_chain_problems

ALL = (1, 2, 3, 4, 5, 6)
TOPS = (2, 3, 5, 7)
TOP_COORDS = {2: (0.0, 0.0, 3.0), 3: (4.0, 0.0, 3.5), 5: (8.0, 1.0, 3.0), 7: (12.0, -1.0, 2.5)}
MASS = (10.0, 12.0, 8.0, 0.5, 0.7, 0.9)

Spec = Sequence[tuple[str, int, int, tuple[int, ...] | str]]


def _project(spec: Spec) -> Project:
    nodes = [Node(id=nid, coords=xyz) for nid, xyz in TOP_COORDS.items()]
    mps = [
        EqualDOFConstraint(retained_node=r, constrained_node=c, dofs=d)
        for kind, r, c, d in spec
        if kind == "eq" and isinstance(d, tuple)
    ]
    links = [
        RigidLink(kind="beam" if d == "beam" else "bar", retained_node=r, constrained_node=c)
        for kind, r, c, d in spec
        if kind == "link"
    ]
    return Project(ndm=3, ndf=6, nodes=nodes, mp_constraints=mps, rigid_links=links)


def _build(spec: Spec, load: tuple[int, int] | None = None) -> None:
    ops.wipe()
    ops.model("basic", "-ndm", 3, "-ndf", 6)
    ops.geomTransf("Linear", 1, 0, 1, 0)
    for k, (top, scale) in enumerate(zip(TOPS, (1.0, 1.7, 0.6, 1.3), strict=True), start=1):
        x, y, z = TOP_COORDS[top]
        base = 100 + top
        ops.node(base, x, y, 0.0)
        ops.fix(base, *([1] * 6))
        ops.node(top, x, y, z)
        ops.mass(top, *MASS)
        ops.element(
            "elasticBeamColumn", k, base, top, 0.1 * scale, 2e8, 8e7,
            1e-3 * scale, 2e-3 * scale, 1.5e-3 / scale, 1,
        )  # fmt: skip
    for kind, r, c, d in spec:
        if kind == "eq":
            ops.equalDOF(r, c, *d)
        else:
            ops.rigidLink(d, r, c)
    ops.timeSeries("Linear", 1)
    ops.pattern("Plain", 1, 1)
    if load is None:
        rng = np.random.default_rng(3)
        for top in TOPS:
            ops.load(top, *rng.uniform(-10.0, 10.0, 6))
    else:
        unit = [0.0] * 6
        unit[load[1]] = 1.0
        ops.load(load[0], *unit)


def _static(handler: str, spec: Spec, load: tuple[int, int] | None = None) -> np.ndarray:
    _build(spec, load)
    ops.constraints(handler)
    ops.numberer("RCM")
    ops.system("FullGeneral")
    ops.test("NormDispIncr", 1e-12, 10)
    ops.algorithm("Linear")
    ops.integrator("LoadControl", 1.0)
    ops.analysis("Static")
    assert ops.analyze(1) == 0
    return np.array([ops.nodeDisp(top, d) for top in TOPS for d in ALL])


def _transformation_eigen(spec: Spec) -> np.ndarray:
    _build(spec)
    return np.array(ops.eigen("-fullGenLapack", 3))


def _reference_eigen(spec: Spec) -> np.ndarray:
    """Lowest eigenvalues from the Lagrange flexibility at the lumped-mass top DOF."""
    flexibility = np.column_stack(
        [_static("Lagrange", spec, (top, d)) for top in TOPS for d in range(6)]
    )
    mu = np.sort(np.linalg.eigvals(flexibility @ np.diag(MASS * len(TOPS))).real)[::-1]
    return 1.0 / mu[:3]


ACCEPTED: dict[str, Spec] = {
    "star of equalDOFs and a rigid link": [("eq", 2, 3, (1, 2)), ("link", 2, 5, "beam")],
    "through a full equalDOF into an equalDOF": [("eq", 2, 3, ALL), ("eq", 3, 5, (1, 2))],
    "two full equalDOFs then a partial one": [
        ("eq", 2, 3, ALL),
        ("eq", 3, 5, ALL),
        ("eq", 5, 7, (1,)),
    ],
    "through a full equalDOF into a rigid beam": [("eq", 2, 3, ALL), ("link", 3, 5, "beam")],
    "through a full equalDOF into a rigid bar": [("eq", 2, 3, ALL), ("link", 3, 5, "bar")],
}

REFUSED: dict[str, Spec] = {
    "equalDOF into equalDOF": [("eq", 2, 3, (1, 2)), ("eq", 3, 5, (1, 2))],
    "equalDOF into a full equalDOF": [("eq", 2, 3, (1, 2)), ("eq", 3, 5, ALL)],
    "a partial link after a full one": [
        ("eq", 2, 3, ALL),
        ("eq", 3, 5, (1, 2)),
        ("eq", 5, 7, (1,)),
    ],
    "equalDOF into a rigid beam": [("eq", 2, 3, (1, 2)), ("link", 3, 5, "beam")],
    "rigid beam into a full equalDOF": [("link", 2, 3, "beam"), ("eq", 3, 5, ALL)],
    "rigid beam into a rigid beam": [("link", 2, 3, "beam"), ("link", 3, 5, "beam")],
    "rigid bar into a rigid bar": [("link", 2, 3, "bar"), ("link", 3, 5, "bar")],
    "one node constrained twice": [("eq", 2, 3, (1,)), ("eq", 5, 3, (2,))],
}


@pytest.fixture(autouse=True)
def _wipe() -> Iterator[None]:
    yield
    ops.wipe()


@pytest.mark.parametrize("spec", ACCEPTED.values(), ids=ACCEPTED.keys())
def test_an_accepted_layout_solves_right_under_transformation(spec: Spec) -> None:
    assert constraint_chain_problems(_project(spec)) == []
    lagrange = _static("Lagrange", spec)
    np.testing.assert_allclose(
        _static("Transformation", spec), lagrange, rtol=0, atol=1e-9 * np.abs(lagrange).max()
    )
    np.testing.assert_allclose(_transformation_eigen(spec), _reference_eigen(spec), rtol=1e-9)


@pytest.mark.parametrize("spec", REFUSED.values(), ids=REFUSED.keys())
def test_a_refused_layout_is_one_transformation_gets_wrong(spec: Spec) -> None:
    assert constraint_chain_problems(_project(spec))
    lagrange = _static("Lagrange", spec)
    error = np.linalg.norm(_static("Transformation", spec) - lagrange) / np.linalg.norm(lagrange)
    assert error > 1e-3
