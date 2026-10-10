"""The shell resultants the runner records, against states known by hand.

Two uniform states, each with a single ShellMITC4, so the answer is closed form:

- **Uniaxial tension** of ``P`` newtons distributed over a 1 m edge, quarter
  symmetry, ν = 0: ``N11 = P / b`` (b = 1 m) and every other resultant zero.
  With ν = 0.2 the transverse resultant is *still* zero — the plate contracts
  freely — which is what makes the membrane/bending split checkable.
A *load-controlled* shear panel has no uniform closed form at this mesh size —
the loads are point loads and Saint-Venant effects dominate (measured: the
element averages of a 2x2 patch differ by a factor of three), so the shear slot
is verified in `tests/unit/test_shell_results.py`, where the field maths is
checked against hand-built resultants. The states here are the ones a
single-element quarter model reproduces exactly.
"""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("openseespy")

from opensees_studio.core import (
    ElasticBeamColumn,
    ElasticMembranePlateSection,
    ElasticSection,
    LinearTimeSeries,
    NodalLoad,
    Node,
    PlainLoadPattern,
    Project,
    ProjectMeta,
    ShellMITC4Element,
    StaticCase,
    UnitSystem,
)
from opensees_studio.services.opensees_runner import OpenSeesRunner

#: N11, N22, N12, M11, M22, M12, V13, V23 — the order OpenSees reports.
N11, N22, N12, M11, M22, M12, V13, V23 = range(8)

SIDE = 1.0
THICKNESS = 0.2
E = 30e9
LOAD = 1000.0  # per loaded node, so P = 2 * LOAD over the 1 m edge


def _quarter_symmetry_nodes() -> list[Node]:
    """One shell in the first quadrant: ux = 0 on x = 0, uy = 0 on y = 0, no bending."""
    return [
        Node(id=1, coords=(0.0, 0.0, 0.0), restraint=(True,) * 6),
        Node(id=2, coords=(SIDE, 0.0, 0.0), restraint=(False, True, True, True, True, False)),
        Node(id=3, coords=(SIDE, SIDE, 0.0), restraint=(False, False, True, True, True, False)),
        Node(id=4, coords=(0.0, SIDE, 0.0), restraint=(True, False, True, True, True, False)),
    ]


def _project(loads: dict[int, tuple[float, ...]], *, nu: float, elements=None) -> Project:
    return Project(
        meta=ProjectMeta(name="shell resultants", units=UnitSystem.SI_M_N),
        ndm=3,
        ndf=6,
        nodes=_quarter_symmetry_nodes(),
        sections=[ElasticMembranePlateSection(id=1, E=E, nu=nu, h=THICKNESS, rho=0.0)],
        elements=elements or [ShellMITC4Element(id=20, nodes=(1, 2, 3, 4), section_id=1)],
        time_series=[LinearTimeSeries(id=1, name="Ramp")],
        load_patterns=[
            PlainLoadPattern(
                id=1,
                name="L",
                time_series_id=1,
                nodal_loads=[NodalLoad(node_id=nid, forces=f) for nid, f in loads.items()],
            ),
        ],
        analyses=[
            StaticCase(
                id=1,
                name="S",
                pattern_ids=[1],
                n_steps=1,
                system="BandGeneral",
                constraints="Plain",
                integrator="LoadControl",
                # Not Linear: OpenSees leaves the section response at zero there.
                algorithm="Newton",
                test="NormDispIncr",
                tolerance=1e-10,
                max_iter=20,
            ),
        ],
    )


def test_uniaxial_tension_records_n11_equal_to_the_load_per_metre() -> None:
    project = _project({2: (LOAD, 0, 0, 0, 0, 0), 3: (LOAD, 0, 0, 0, 0, 0)}, nu=0.0)
    results = OpenSeesRunner(project).run(project.analyses[0])

    values = results.element_stresses[20][0]
    assert values[N11] == pytest.approx(2 * LOAD / SIDE, rel=1e-9)
    assert values[N22] == pytest.approx(0.0, abs=1e-6)
    assert values[N12] == pytest.approx(0.0, abs=1e-6)
    assert np.allclose(values[[M11, M22, M12, V13, V23]], 0.0, atol=1e-9)


def test_free_poisson_contraction_leaves_n22_zero() -> None:
    """ε22 = -ν ε11 while N22 stays zero: the split is checkable from the strains."""
    project = _project({2: (LOAD, 0, 0, 0, 0, 0), 3: (LOAD, 0, 0, 0, 0, 0)}, nu=0.2)
    results = OpenSeesRunner(project).run(project.analyses[0])

    values = results.element_stresses[20][0]
    assert values[N11] == pytest.approx(2 * LOAD / SIDE, rel=1e-9)
    assert abs(values[N22]) < 1e-6


def test_a_model_of_bars_records_no_resultants() -> None:
    """A frame model has nothing to contour, and must not be given zeros."""
    nodes = [
        Node(id=1, coords=(0.0, 0.0, 0.0), restraint=(True,) * 6),
        Node(id=2, coords=(1.0, 0.0, 0.0)),
    ]
    project = Project(
        meta=ProjectMeta(name="bar", units=UnitSystem.SI_M_N),
        ndm=3,
        ndf=6,
        nodes=nodes,
        sections=[
            ElasticSection(id=2, E=E, A=0.01, Iz=1e-5, Iy=1e-5, G=E / 2.6, J=1e-5),
        ],
        elements=[ElasticBeamColumn(id=10, nodes=(1, 2), section_id=2)],
        time_series=[LinearTimeSeries(id=1, name="Ramp")],
        load_patterns=[
            PlainLoadPattern(
                id=1,
                name="L",
                time_series_id=1,
                nodal_loads=[NodalLoad(node_id=2, forces=(0, 0, -100.0, 0, 0, 0))],
            ),
        ],
        analyses=[
            StaticCase(
                id=1,
                name="S",
                pattern_ids=[1],
                n_steps=1,
                system="BandGeneral",
                constraints="Plain",
                integrator="LoadControl",
                algorithm="Newton",
                test="NormDispIncr",
                tolerance=1e-10,
                max_iter=20,
            ),
        ],
    )
    results = OpenSeesRunner(project).run(project.analyses[0])
    assert results.element_stresses == {}
    assert results.element_forces  # the bar still reports its forces
