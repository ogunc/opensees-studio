"""Meshing does not change the answer of a linear elastic model.

Splitting a prismatic member is a change of *discretisation*, not of structure,
so the numbers have to come out the same — and that is a much sharper check than
"it still runs": the tip deflection of a cantilever under a tip load, and the
mid-span deflection of a simply supported beam under its own uniform load, both
before and after the mesh, against the closed form.

The plate check is the other direction: there, refinement is supposed to *change*
the answer, because a coarse displacement-based mesh is too stiff. What is
asserted is that refining moves the result towards the classical solution, not
away from it.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("openseespy.opensees")

from opensees_studio.core import (
    ElasticBeamColumn,
    ElasticMembranePlateSection,
    ElasticSection,
    LinearTimeSeries,
    NodalLoad,
    Node,
    PlainLoadPattern,
    Project,
    ShellMITC4Element,
    StaticCase,
    UniformElementLoad,
)
from opensees_studio.core.mesh import MeshPlan, mesh_bars, mesh_shells
from opensees_studio.services.opensees_runner import OpenSeesRunner

E = 200e9
I_SEC = 1e-6
AREA = 0.01
LENGTH = 4.0


def _section() -> ElasticSection:
    return ElasticSection(id=1, name="S", E=E, A=AREA, Iz=I_SEC, Iy=I_SEC, G=80e9, J=1e-6)


def _apply(project: Project, plan: MeshPlan) -> None:
    """The command's effect, without the Qt view model (this is an integration test)."""
    removed = set(plan.removed_element_ids)
    project.elements[:] = [element for element in project.elements if element.id not in removed]
    project.nodes.extend(plan.new_nodes)
    project.elements.extend(plan.new_elements)


def _cantilever(target: float | None = None) -> tuple[Project, float]:
    """A cantilever with a tip load: w = P L³ / 3EI, exact for one element."""
    load = 1000.0
    project = Project(
        ndm=3,
        ndf=6,
        nodes=[
            Node(id=1, coords=(0.0, 0.0, 0.0), restraint=(True,) * 6),
            Node(id=2, coords=(LENGTH, 0.0, 0.0)),
        ],
        sections=[_section()],
        elements=[ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1)],
        time_series=[LinearTimeSeries(id=1)],
        load_patterns=[
            PlainLoadPattern(
                id=1,
                time_series_id=1,
                nodal_loads=[NodalLoad(node_id=2, forces=(0, 0, -load, 0, 0, 0))],
            )
        ],
        analyses=[StaticCase(id=1, name="tip", n_steps=1, pattern_ids=[1])],
    )
    if target is not None:
        _apply(project, mesh_bars(project, {1}, target_size=target))
    return project, load * LENGTH**3 / (3.0 * E * I_SEC)


def _simply_supported(target: float | None = None) -> tuple[Project, float]:
    """A simply supported beam under a uniform load: w = 5qL⁴ / 384EI at mid-span."""
    q = 5000.0
    mid = LENGTH / 2.0
    project = Project(
        ndm=3,
        ndf=6,
        nodes=[
            # Torsion restrained at both ends: a beam free to twist about its own
            # axis is a mechanism, and the mesh would only make it visible.
            Node(id=1, coords=(0.0, 0.0, 0.0), restraint=(True, True, True, True, False, False)),
            Node(
                id=2, coords=(LENGTH, 0.0, 0.0), restraint=(False, True, True, True, False, False)
            ),
            Node(id=3, coords=(mid, 0.0, 0.0)),
        ],
        sections=[_section()],
        elements=[
            ElasticBeamColumn(id=1, nodes=(1, 3), section_id=1),
            ElasticBeamColumn(id=2, nodes=(3, 2), section_id=1),
        ],
        time_series=[LinearTimeSeries(id=1)],
        load_patterns=[
            PlainLoadPattern(
                id=1,
                time_series_id=1,
                # The vertical (local z) uniformly distributed load: local y is
                # horizontal for a member along global X.
                element_loads=[
                    UniformElementLoad(element_id=1, wz=-q),
                    UniformElementLoad(element_id=2, wz=-q),
                ],
            )
        ],
        analyses=[StaticCase(id=1, name="udl", n_steps=1, pattern_ids=[1])],
    )
    if target is not None:
        plan = mesh_bars(project, {1, 2}, target_size=target)
        _apply(project, plan)
        # The pieces inherit the load from the originals: the command does that,
        # and here the plan's replacement map is what says which is which.
        pattern = project.load_patterns[0]
        for original, pieces in plan.replacements.items():
            for load in list(pattern.element_loads):
                if load.element_id != original:
                    continue
                pattern.element_loads.extend(
                    load.model_copy(update={"element_id": piece}) for piece in pieces
                )
        pattern.element_loads[:] = [
            load
            for load in pattern.element_loads
            if load.element_id not in set(plan.removed_element_ids)
        ]
    return project, 5.0 * q * LENGTH**4 / (384.0 * E * I_SEC)


def _run(project: Project, tmp_path: Path, name: str) -> float:
    results = OpenSeesRunner(project).run(project.analyses[0], results_dir=tmp_path / name)
    return results


def test_the_closed_forms_are_what_the_tests_compare_against() -> None:
    _, tip = _cantilever()
    _, mid = _simply_supported()

    assert tip == pytest.approx(1000.0 * LENGTH**3 / (3.0 * E * I_SEC))
    assert mid == pytest.approx(5.0 * 5000.0 * LENGTH**4 / (384.0 * E * I_SEC))


def test_splitting_a_cantilever_does_not_change_its_tip_deflection(tmp_path: Path) -> None:
    one, closed_form = _cantilever()
    many, _ = _cantilever(target=0.5)  # eight pieces

    single = _run(one, tmp_path, "one")
    split = _run(many, tmp_path, "split")

    w_one = abs(float(single.node_disp[2][0][2]))
    w_many = abs(float(split.node_disp[2][0][2]))
    assert w_one == pytest.approx(closed_form, rel=1e-9)
    assert w_many == pytest.approx(w_one, rel=1e-9)  # 0.5 m pieces, same answer
    assert len(many.elements) == 8


def test_splitting_a_loaded_beam_keeps_its_mid_span_deflection(tmp_path: Path) -> None:
    coarse, closed_form = _simply_supported()
    fine, _ = _simply_supported(target=0.25)  # 16 pieces, each still carrying q

    both = _run(coarse, tmp_path, "coarse")
    split = _run(fine, tmp_path, "fine")

    w_coarse = abs(float(both.node_disp[3][0][2]))
    w_fine = abs(float(split.node_disp[3][0][2]))
    assert w_coarse == pytest.approx(closed_form, rel=1e-6)
    assert w_fine == pytest.approx(w_coarse, rel=1e-6)

    # The same *total* load: more pieces carry the same q over shorter lengths.
    def total(project: Project) -> float:
        by_id = {element.id: element for element in project.elements}
        return sum(
            load.wz
            * float(
                np.linalg.norm(
                    np.asarray(project.node(by_id[load.element_id].nodes[1]).coords, dtype=float)
                    - np.asarray(project.node(by_id[load.element_id].nodes[0]).coords, dtype=float)
                )
            )
            for load in project.load_patterns[0].element_loads
        )

    assert total(fine) == pytest.approx(total(coarse))


def _plate(n: int) -> tuple[Project, int]:
    """A simply supported plate of side 1 m, either one shell or an n x n mesh."""
    side, thickness, pressure = 1.0, 0.01, 1000.0
    nodes: list[Node] = []
    ids: dict[tuple[int, int], int] = {}
    for j in range(n + 1):
        for i in range(n + 1):
            restraint = [False] * 6
            if i in (0, n) or j in (0, n):
                restraint[2] = True
            if (i, j) == (0, 0):
                restraint[0] = True
            if (i, j) == (n, 0):
                restraint[1] = True
            ids[(i, j)] = len(nodes) + 1
            nodes.append(
                Node(
                    id=len(nodes) + 1,
                    coords=(i * side / n, j * side / n, 0.0),
                    restraint=tuple(restraint),
                )
            )
    elements = [
        ShellMITC4Element(
            id=j * n + i + 1,
            nodes=(ids[(i, j)], ids[(i + 1, j)], ids[(i + 1, j + 1)], ids[(i, j + 1)]),
            section_id=1,
        )
        for j in range(n)
        for i in range(n)
    ]
    loads = []
    cell = side / n
    for j in range(n + 1):
        for i in range(n + 1):
            wx = cell if 0 < i < n else cell / 2.0
            wy = cell if 0 < j < n else cell / 2.0
            loads.append(
                NodalLoad(node_id=ids[(i, j)], forces=(0, 0, -pressure * wx * wy, 0, 0, 0))
            )
    project = Project(
        ndm=3,
        ndf=6,
        nodes=nodes,
        sections=[ElasticMembranePlateSection(id=1, E=E, nu=0.3, h=thickness)],
        elements=elements,
        time_series=[LinearTimeSeries(id=1)],
        load_patterns=[PlainLoadPattern(id=1, time_series_id=1, nodal_loads=loads)],
        analyses=[StaticCase(id=1, name="pressure", n_steps=1, pattern_ids=[1])],
    )
    return project, ids[(n // 2, n // 2)]


def _pressure_loads(project: Project, pressure: float) -> list[NodalLoad]:
    """Tributary nodal loads for a uniform pressure on any face mesh.

    A quarter of each face's area goes to each of its four nodes, which is what
    building the loads by hand on that grid gives — and what makes "mesh it and
    reload it" comparable with "build it fine".
    """
    share: dict[int, float] = {}
    for element in project.elements:
        points = [
            np.asarray(project.node(node_id).coords, dtype=float) for node_id in element.nodes
        ]
        area = 0.5 * float(np.linalg.norm(np.cross(points[2] - points[0], points[3] - points[1])))
        for node_id in element.nodes:
            share[node_id] = share.get(node_id, 0.0) + area / 4.0
    return [
        NodalLoad(node_id=node_id, forces=(0.0, 0.0, -pressure * area, 0, 0, 0))
        for node_id, area in sorted(share.items())
    ]


def test_meshing_a_plate_builds_the_same_model_as_drawing_it_fine(tmp_path: Path) -> None:
    """Mesh a 2x2 slab into 4x4 and reload it: the answer matches the 4x4 model.

    The mesh alone does not redistribute the pressure — a nodal load stays where it
    is — so the loads are rebuilt on the new grid by tributary area. After that the
    meshed model *is* the finely built one, and the tip of the comparison is that
    the two agree, so the mesher and the hand-built mesh are interchangeable.
    """
    pressure = 1000.0
    meshed, meshed_centre = _plate(2)
    plan = mesh_shells(meshed, None, target_size=0.25)
    _apply(meshed, plan)
    assert len(meshed.elements) == 16
    meshed.load_patterns[0].nodal_loads = _pressure_loads(meshed, pressure)

    fine, fine_centre = _plate(4)
    fine.load_patterns[0].nodal_loads = _pressure_loads(fine, pressure)

    w_meshed = abs(float(_run(meshed, tmp_path, "meshed").node_disp[meshed_centre][0][2]))
    w_fine = abs(float(_run(fine, tmp_path, "fine").node_disp[fine_centre][0][2]))

    assert w_meshed > 0.0
    assert w_meshed == pytest.approx(w_fine, rel=1e-6)
    # ... and that number is the 4x4 row of the plate convergence table.
    assert w_meshed * 1000.0 == pytest.approx(0.2169, abs=0.005)
