"""The DEAD case solved by OpenSees: the supports carry exactly the frames' weight.

A column, a sloped force-based rafter and a displacement-based leg (and, in 3D,
a beam along Y): whatever the orientation and formulation, the vertical
reactions add up to gamma * A * L over the members and the horizontal ones
cancel. A wrong local axis or sign would leave a horizontal residual or a
wrong total.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("openseespy.opensees")

from opensees_studio.core import (
    DispBeamColumn,
    ElasticBeamColumn,
    ForceBeamColumn,
    Node,
    Project,
    ensure_dead_load_case,
    make_default_section,
    total_self_weight,
)
from opensees_studio.services.opensees_runner import OpenSeesRunner


def _frame(ndm: int) -> tuple[Project, int]:
    ndf = 3 if ndm == 2 else 6
    # Z is up in 2D (the X-Z plane) and 3D; result columns follow the DOFs, so
    # the vertical reaction is column 1 in 2D (Ux, Uz, Ry) and 2 in 3D.
    up = 1 if ndm == 2 else 2

    def at(x: float, height: float, y: float = 0.0) -> tuple[float, float, float]:
        return (x, y, height)

    project = Project(ndm=ndm, ndf=ndf, sections=[make_default_section(1)])
    ensure_dead_load_case(project)
    fixed = (True,) * 6
    project.nodes += [
        Node(id=1, coords=at(0, 0), restraint=fixed),
        Node(id=2, coords=at(0, 3)),
        Node(id=3, coords=at(4, 4)),
        Node(id=4, coords=at(4, 0), restraint=fixed),
    ]
    project.elements += [
        ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1),
        ForceBeamColumn(id=2, nodes=(2, 3), section_id=1),
        DispBeamColumn(id=3, nodes=(4, 3), section_id=1),
    ]
    if ndm == 3:
        project.nodes.append(Node(id=5, coords=at(4, 4, y=5.0), restraint=fixed))
        project.elements.append(ElasticBeamColumn(id=4, nodes=(3, 5), section_id=1))
    return project, up


@pytest.mark.parametrize("ndm", [2, 3])
def test_the_supports_carry_the_whole_self_weight(ndm: int, tmp_path: Path) -> None:
    project, up = _frame(ndm)
    results = OpenSeesRunner(project).run(project.analyses[0], results_dir=tmp_path)

    supports = [node.id for node in project.nodes if any(node.restraint)]
    vertical = sum(float(results.node_reaction[n][0][up]) for n in supports)
    horizontal = [
        sum(float(results.node_reaction[n][0][axis]) for n in supports)
        for axis in range(ndm)
        if axis != up
    ]
    weight = total_self_weight(project)
    assert weight > 0.0
    assert vertical == pytest.approx(weight, rel=1e-9)
    assert horizontal == pytest.approx([0.0] * len(horizontal), abs=weight * 1e-9)


def test_a_skewed_slab_rests_its_whole_weight_on_its_corners(tmp_path: Path) -> None:
    from opensees_studio.core import ElasticMembranePlateSection, ShellMITC4Element

    project = Project(ndm=3, ndf=6)
    ensure_dead_load_case(project)
    project.sections.append(
        ElasticMembranePlateSection(id=1, E=30e9, nu=0.2, h=0.2, unit_weight=24e3)
    )
    ids = {}
    for j in range(3):
        for i in range(3):
            corner = i in (0, 2) and j in (0, 2)
            node = Node(
                id=len(ids) + 1,
                coords=(2.0 * i + 0.3 * j, 1.5 * j, 0.0),
                restraint=(True, True, True, False, False, False) if corner else (False,) * 6,
            )
            ids[(i, j)] = node.id
            project.nodes.append(node)
    for j in range(2):
        for i in range(2):
            project.elements.append(
                ShellMITC4Element(
                    id=len(project.elements) + 1,
                    nodes=(ids[(i, j)], ids[(i + 1, j)], ids[(i + 1, j + 1)], ids[(i, j + 1)]),
                    section_id=1,
                )
            )

    results = OpenSeesRunner(project).run(project.analyses[0], results_dir=tmp_path)

    weight = 24e3 * 0.2 * 4.0 * 3.0  # a parallelogram of base 4 and height 3
    assert total_self_weight(project) == pytest.approx(weight)
    reactions = sum(float(results.node_reaction[n][0][2]) for n in (1, 3, 7, 9))
    assert reactions == pytest.approx(weight, rel=1e-9)
    assert float(results.node_disp[ids[(1, 1)]][0][2]) < 0.0
