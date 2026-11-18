"""A point load inside a frame element, solved by OpenSees, against the closed form.

A simply supported beam of span L with a load P at a from end i: the supports
carry P b / L and P a / L (b = L - a), whatever the element formulation, since
the beam is statically determinate. For the elastic element the deflection under
the load is also exact: P a² b² / (3 E I L).
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("openseespy.opensees")

from opensees_studio.core import (
    DispBeamColumn,
    ElasticBeamColumn,
    ElasticSection,
    ForceBeamColumn,
    LinearTimeSeries,
    Node,
    PlainLoadPattern,
    PointElementLoad,
    Project,
    StaticCase,
)
from opensees_studio.services.opensees_runner import OpenSeesRunner

E = 2e8
I_SEC = 1e-4
LENGTH = 4.0
LOAD = 10.0
A_POS = 1.0  # distance of the load from end i


def _beam(element_cls: type, *, ndm: int = 2) -> Project:
    ndf = 3 if ndm == 2 else 6
    if ndm == 2:
        # The X-Z plane: slots (Ux, Uy, Uz) = a pin holds Ux and Uz, a roller Uz.
        pin, roller = (True, False, True), (False, False, True)
    else:
        # 3D: the roller also holds the out-of-plane DOF and both ends the twist.
        pin = (True, True, True, True, False, False)
        roller = (False, True, True, True, False, False)
    pad = (False,) * (6 - ndf)
    point = (
        PointElementLoad(element_id=1, py=-LOAD, x=A_POS / LENGTH)
        if ndm == 2
        else PointElementLoad(element_id=1, pz=-LOAD, x=A_POS / LENGTH)
    )
    return Project(
        ndm=ndm,
        ndf=ndf,
        nodes=[
            Node(id=1, coords=(0.0, 0.0, 0.0), restraint=pin + pad),
            Node(id=2, coords=(LENGTH, 0.0, 0.0), restraint=roller + pad),
        ],
        sections=[ElasticSection(id=1, name="S", E=E, A=0.01, Iz=I_SEC, Iy=I_SEC, G=8e7, J=1e-4)],
        elements=[element_cls(id=1, nodes=(1, 2), section_id=1)],
        time_series=[LinearTimeSeries(id=1)],
        load_patterns=[PlainLoadPattern(id=1, time_series_id=1, point_loads=[point])],
        analyses=[StaticCase(id=1, name="point", n_steps=1, pattern_ids=[1])],
    )


def _solve(project: Project, tmp_path: Path):  # type: ignore[no-untyped-def]
    return OpenSeesRunner(project).run(project.analyses[0], results_dir=tmp_path)


@pytest.mark.parametrize("element_cls", [ElasticBeamColumn, ForceBeamColumn, DispBeamColumn])
def test_the_supports_share_the_load_by_the_lever_rule(element_cls: type, tmp_path: Path) -> None:
    results = _solve(_beam(element_cls), tmp_path)

    b = LENGTH - A_POS
    assert float(results.node_reaction[1][0][1]) == pytest.approx(LOAD * b / LENGTH, rel=1e-6)
    assert float(results.node_reaction[2][0][1]) == pytest.approx(LOAD * A_POS / LENGTH, rel=1e-6)


def test_the_elastic_deflection_under_the_load_is_exact(tmp_path: Path) -> None:
    # Split the span at the load point with an extra node so its deflection is
    # a nodal result: two elastic elements, the load at the end of the first.
    project = _beam(ElasticBeamColumn)
    project.nodes.append(Node(id=3, coords=(A_POS, 0.0, 0.0)))
    project.elements[:] = [
        ElasticBeamColumn(id=1, nodes=(1, 3), section_id=1),
        ElasticBeamColumn(id=2, nodes=(3, 2), section_id=1),
    ]
    project.load_patterns[0].point_loads[:] = [PointElementLoad(element_id=2, py=-LOAD, x=0.0)]

    results = _solve(project, tmp_path)

    b = LENGTH - A_POS
    expected = LOAD * A_POS**2 * b**2 / (3 * E * I_SEC * LENGTH)
    assert float(results.node_disp[3][0][1]) == pytest.approx(-expected, rel=1e-9)


def test_a_3d_frame_takes_the_local_z_component(tmp_path: Path) -> None:
    results = _solve(_beam(ElasticBeamColumn, ndm=3), tmp_path)

    b = LENGTH - A_POS
    reactions = [float(results.node_reaction[nid][0][2]) for nid in (1, 2)]
    assert sum(abs(r) for r in reactions) == pytest.approx(LOAD, rel=1e-6)
    assert abs(reactions[0]) == pytest.approx(LOAD * b / LENGTH, rel=1e-6)
