"""Regression test: pure-truss models with ndf=3 must refuse to solve.

OpenSees silently returns the load vector as 'displacement' when the
stiffness matrix is singular on rotational DOFs. The runner now
pre-validates DOF coverage and raises a descriptive error instead.
"""

from __future__ import annotations

import pytest

pytest.importorskip("openseespy")

from opensees_studio.core import (  # noqa: E402
    ElasticUniaxial,
    LinearTimeSeries,
    NodalLoad,
    Node,
    PlainLoadPattern,
    Project,
    StaticCase,
    TrussElement,
)
from opensees_studio.services.opensees_runner import OpenSeesRunner  # noqa: E402


def _make_truss_project(ndf: int) -> Project:
    return Project(
        ndm=2, ndf=ndf,
        nodes=[
            Node(id=1, coords=(0, 0, 0),
                 restraint=(True, True, False, False, False, False)),
            Node(id=2, coords=(3, 0, 0),
                 restraint=(True, True, False, False, False, False)),
            Node(id=3, coords=(1.5, 2, 0)),
        ],
        materials=[ElasticUniaxial(id=1, E=200e9)],
        elements=[
            TrussElement(id=1, nodes=(1, 3), area=1e-3, material_id=1),
            TrussElement(id=2, nodes=(2, 3), area=1e-3, material_id=1),
        ],
        time_series=[LinearTimeSeries(id=1, name="R")],
        load_patterns=[PlainLoadPattern(
            id=1, time_series_id=1,
            nodal_loads=[NodalLoad(node_id=3, forces=(1e3, -5e3, 0, 0, 0, 0))],
        )],
        analyses=[StaticCase(id=1, name="Static", pattern_ids=[1], n_steps=1)],
    )


def test_truss_with_ndf_3_is_rejected_clearly() -> None:
    """A pure-truss project declared with ndf=3 must fail before the solve."""
    proj = _make_truss_project(ndf=3)
    with pytest.raises(RuntimeError) as excinfo:
        OpenSeesRunner(proj).run(proj.analyses[0])
    message = str(excinfo.value)
    assert "Singular stiffness matrix" in message
    # Every unrestrained Rz should be listed.
    assert "Rz" in message
    # Helpful hint steering the user to the right menu item.
    assert "New 2D Truss" in message


def test_truss_with_ndf_2_runs_to_completion() -> None:
    """The same truss with ndf=2 solves fine."""
    proj = _make_truss_project(ndf=2)
    result = OpenSeesRunner(proj).run(proj.analyses[0])
    assert 3 in result.node_disp
    # Sanity: displacement must be non-zero and finite.
    ux, uy = result.node_disp[3][-1]
    assert abs(ux) > 0 or abs(uy) > 0
    assert ux == ux and uy == uy  # NaN check
