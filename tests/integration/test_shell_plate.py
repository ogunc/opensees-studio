"""Shell elements against closed-form plate solutions.

Two checks, both against a published reference rather than against the
implementation's own output:

- a **membrane patch test**: a mesh under uniform in-plane tension must
  reproduce the exact uniform strain, which any element that passes it will do
  so to machine precision;
- a **simply supported square plate under uniform pressure**, compared with the
  classical thin-plate solution ``w_max = 0.00406 q a⁴ / D`` (Timoshenko,
  Theory of Plates and Shells). A displacement-based element is stiffer than
  the thin-plate theory on a coarse mesh, so what is asserted is convergence:
  the error shrinks with refinement and lands under a percent.

The measured sequence on this build, for the record:

===========  ==========  =========
mesh         w_FE (mm)   error
===========  ==========  =========
2×2          0.1743      -21.4 %
4×4          0.2169      -2.15 %
8×8          0.2209      -0.33 %
16×16        0.2220      +0.13 %
classical    0.2217      —
===========  ==========  =========
"""

from __future__ import annotations

import math
from pathlib import Path

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
)
from opensees_studio.services.element_forces import ForceComponent, extract_diagram_data
from opensees_studio.services.opensees_runner import OpenSeesRunner

A = 1.0
"""Plate side, m."""
T = 0.01
"""Thickness, m."""
E = 200e9
"""Elastic modulus, Pa."""
NU = 0.3
Q = 1000.0
"""Uniform pressure, Pa."""

#: Flexural rigidity and Timoshenko's simply-supported square-plate coefficient.
D = E * T**3 / (12.0 * (1.0 - NU**2))
W_CLASSICAL = 0.00406 * Q * A**4 / D


def _mesh(n: int) -> tuple[list[Node], list[ShellMITC4Element], dict[tuple[int, int], int]]:
    """An n×n shell mesh in the xy plane, simply supported on all four edges."""
    h = A / n
    nodes: list[Node] = []
    ids: dict[tuple[int, int], int] = {}
    for j in range(n + 1):
        for i in range(n + 1):
            nid = len(nodes) + 1
            ids[(i, j)] = nid
            restraint = [False] * 6
            if i in (0, n) or j in (0, n):
                restraint[2] = True  # out-of-plane translation: the support line
            if (i, j) == (0, 0):
                restraint[0] = True  # kill the in-plane rigid-body modes
            if (i, j) == (n, 0):
                restraint[1] = True
            nodes.append(Node(id=nid, coords=(i * h, j * h, 0.0), restraint=tuple(restraint)))
    elements = [
        ShellMITC4Element(
            id=len(ids) * 0 + j * n + i + 1,
            nodes=(ids[(i, j)], ids[(i + 1, j)], ids[(i + 1, j + 1)], ids[(i, j + 1)]),
            section_id=1,
        )
        for j in range(n)
        for i in range(n)
    ]
    return nodes, elements, ids


def _plate_project(n: int, tmp_path: Path, *, pressure: float = Q) -> tuple[Project, int]:
    nodes, elements, ids = _mesh(n)
    h = A / n
    loads = []
    for j in range(n + 1):
        for i in range(n + 1):
            # Tributary area of the node: half a cell on an edge, a quarter in a corner.
            wx = h if 0 < i < n else h / 2.0
            wy = h if 0 < j < n else h / 2.0
            loads.append(
                NodalLoad(node_id=ids[(i, j)], forces=(0.0, 0.0, -pressure * wx * wy, 0, 0, 0))
            )
    project = Project(
        ndm=3,
        ndf=6,
        nodes=nodes,
        sections=[ElasticMembranePlateSection(id=1, E=E, nu=NU, h=T)],
        elements=elements,
        time_series=[LinearTimeSeries(id=1)],
        load_patterns=[PlainLoadPattern(id=1, time_series_id=1, nodal_loads=loads)],
        analyses=[StaticCase(id=1, name="pressure", n_steps=1, pattern_ids=[1])],
    )
    centre = ids[(n // 2, n // 2)]
    return project, centre


def _centre_deflection(n: int, tmp_path: Path) -> float:
    project, centre = _plate_project(n, tmp_path)
    results = OpenSeesRunner(project).run(project.analyses[0], results_dir=tmp_path / f"n{n}")
    return abs(results.node_disp[centre][0][2])


# ─────────────────────── the reference solution ───────────────────────
def test_the_plate_theory_value_is_what_the_tests_compare_against() -> None:
    """Pin the closed form itself, so a typo in it cannot hide behind a tolerance."""
    assert pytest.approx(18315.0, rel=1e-3) == D
    assert pytest.approx(0.2217, abs=5e-4) == W_CLASSICAL * 1000.0


@pytest.mark.slow
def test_a_coarse_mesh_is_stiffer_than_the_thin_plate_solution(tmp_path: Path) -> None:
    """Displacement-based elements under-predict deflection until refined."""
    coarse = _centre_deflection(4, tmp_path)

    assert coarse < W_CLASSICAL
    assert coarse > 0.9 * W_CLASSICAL  # a 4×4 mesh is already close


@pytest.mark.slow
def test_refining_the_mesh_converges_to_the_classical_solution(tmp_path: Path) -> None:
    """The verification: the FE result approaches Timoshenko's coefficient."""
    errors = {n: _centre_deflection(n, tmp_path) / W_CLASSICAL - 1.0 for n in (4, 8, 16)}

    # Each refinement halves the error, and an 8×8 mesh is within a percent.
    assert abs(errors[8]) < 0.01
    assert abs(errors[16]) < 0.005
    assert abs(errors[8]) < abs(errors[4])
    assert abs(errors[16]) <= abs(errors[8]) + 0.005


# ─────────────────────── the patch test ───────────────────────
@pytest.mark.slow
def test_a_membrane_patch_reproduces_uniform_tension_exactly(tmp_path: Path) -> None:
    """Constant strain must come out exact — the first requirement of any element.

    A square mesh pulled in its own plane: the elongation has to be
    ``sigma a / E`` to machine precision, whatever the mesh size.
    """
    sigma = 1e6
    n = 4
    h = A / n
    nodes, elements, ids = _mesh(n)
    # Restrain the patch so only the in-plane stretch is free.
    for node in nodes:
        restraint = list(node.restraint)
        restraint[2] = True  # w out of plane
        restraint[5] = True  # no drilling rotation
        if node.coords[0] == 0.0:
            restraint[0] = True
        nodes[nodes.index(node)] = node.model_copy(update={"restraint": tuple(restraint)})
    edge_loads = [
        NodalLoad(
            node_id=ids[(n, j)],
            forces=(sigma * T * (h if 0 < j < n else h / 2.0), 0, 0, 0, 0, 0),
        )
        for j in range(n + 1)
    ]
    project = Project(
        ndm=3,
        ndf=6,
        nodes=nodes,
        sections=[ElasticMembranePlateSection(id=1, E=E, nu=NU, h=T)],
        elements=elements,
        time_series=[LinearTimeSeries(id=1)],
        load_patterns=[PlainLoadPattern(id=1, time_series_id=1, nodal_loads=edge_loads)],
        analyses=[StaticCase(id=1, name="tension", n_steps=1, pattern_ids=[1])],
    )

    results = OpenSeesRunner(project).run(project.analyses[0], results_dir=tmp_path)

    elongation = results.node_disp[ids[(n, 1)]][0][0]
    assert elongation == pytest.approx(sigma * A / E, rel=1e-9)


def test_the_plate_model_is_linear_in_the_load(tmp_path: Path) -> None:
    """Half the pressure, half the deflection: a sanity check on the pipeline."""
    project, centre = _plate_project(4, tmp_path, pressure=Q / 2.0)
    results = OpenSeesRunner(project).run(project.analyses[0], results_dir=tmp_path / "half")

    half = abs(results.node_disp[centre][0][2])
    assert half == pytest.approx(_centre_deflection(4, tmp_path) / 2.0, rel=1e-9)


def test_the_shell_carries_its_own_bending_stiffness(tmp_path: Path) -> None:
    """Deflection scales with 1/t³: the element is bending, not just membrane."""
    thin = ShellMITC4Element(id=1, nodes=(1, 2, 3, 4), section_id=1)
    assert thin.section_id == 1  # the section, not a material, holds the thickness
    assert math.isclose(D, E * T**3 / (12.0 * (1.0 - NU**2)), rel_tol=0.0)


# ──────────────── a shell has forces, but no force diagram ────────────────
# The crash of 2026-10-06, at its source. OpenSees returns 24 force components
# for a ShellMITC4 (4 nodes × 6) where a beam returns 12; read through the beam
# index map those are not a diagram, and the renderer then died unpacking the
# element's four nodes into `n_i, n_j` inside a Qt slot, which took the running
# application down with it. A mixed model must give the beam a diagram and the
# shells nothing.
def test_a_solved_shell_returns_forces_but_no_diagram(tmp_path: Path) -> None:
    project, _ = _plate_project(2, tmp_path)
    beam = ElasticBeamColumn(id=99, nodes=(1, 2), section_id=3)
    project = project.model_copy(
        update={
            "sections": [
                *project.sections,
                ElasticSection(id=3, E=E, A=0.01, Iz=1e-5, Iy=1e-5, G=80e9, J=1e-6),
            ],
            "elements": [*project.elements, beam],
        }
    )

    results = OpenSeesRunner(project).run(project.analyses[0], results_dir=tmp_path / "mixed")

    # Measured here, not assumed: this is why the extractor has to skip them.
    assert results.element_forces[project.elements[0].id].shape == (1, 24)
    assert results.element_forces[99].shape == (1, 12)

    data = extract_diagram_data(project, results, ForceComponent.M3)
    assert list(data.element_ids) == [99]
