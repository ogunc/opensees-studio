"""The contour's numbers against a plate-strip solution that is exact.

A cantilever strip with a tip moment is the one bending case with no
discretisation error in the bending moment: the applied moment per unit width
*is* ``M11``, element for element, whatever the mesh. So this is the reference
the bending contour is pinned to — ``M11 = M`` at every element, ``V13 = 0``
because there is no shear, and the tip deflection against the classical
cylindrical-bending value ``M L² / 2D`` with ``D = E h³ / 12(1 - ν²)``.

The deflection is checked to 5 %, not exactly: the strip is thick (h/L = 0.1)
and two elements along the span carry the curvature, which is worth about 3 %
against the thin-plate closed form. ``M11`` itself is exact.
"""

from __future__ import annotations

import pytest

pytest.importorskip("openseespy")

from opensees_studio.core import (
    ElasticMembranePlateSection,
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
from opensees_studio.services.shell_fields import element_values, nodal_values

L = 2.0  # span [m]
WIDTH = 1.0  # width [m]
THICKNESS = 0.2  # thickness [m]
E = 30e9
NU = 0.2
M_LINE = 500.0  # tip moment per unit width [N·m/m]

#: N11, N22, N12, M11, M22, M12, V13, V23 — the order OpenSees reports.
M11, V13 = 3, 6

D = E * THICKNESS**3 / (12.0 * (1.0 - NU**2))  # plate rigidity [N·m]


def _strip() -> Project:
    """Two shells along the span, one across, clamped at the root, tip moment."""
    coords = {
        1: (0.0, 0.0, 0.0),
        2: (L / 2, 0.0, 0.0),
        3: (L, 0.0, 0.0),
        4: (L, WIDTH, 0.0),
        5: (L / 2, WIDTH, 0.0),
        6: (0.0, WIDTH, 0.0),
    }
    elements = [(1, 2, 5, 6), (2, 3, 4, 5)]
    return Project(
        meta=ProjectMeta(name="strip in pure bending", units=UnitSystem.SI_M_N),
        ndm=3,
        ndf=6,
        nodes=[
            Node(id=nid, coords=c, restraint=(True,) * 6 if nid in (1, 6) else (False,) * 6)
            for nid, c in coords.items()
        ],
        sections=[ElasticMembranePlateSection(id=1, E=E, nu=NU, h=THICKNESS, rho=0.0)],
        elements=[
            ShellMITC4Element(id=index + 1, nodes=nodes, section_id=1)
            for index, nodes in enumerate(elements)
        ],
        time_series=[LinearTimeSeries(id=1, name="Ramp")],
        load_patterns=[
            PlainLoadPattern(
                id=1,
                name="Tip moment",
                time_series_id=1,
                # Half the width each: the moment per unit width times the
                # tributary width of the node.
                nodal_loads=[
                    NodalLoad(node_id=3, forces=(0, 0, 0, 0, M_LINE * WIDTH / 2, 0)),
                    NodalLoad(node_id=4, forces=(0, 0, 0, 0, M_LINE * WIDTH / 2, 0)),
                ],
            ),
        ],
        analyses=[
            StaticCase(
                id=1,
                name="Bending",
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


def test_the_bending_contour_reads_the_applied_moment_per_unit_width() -> None:
    project = _strip()
    results = OpenSeesRunner(project).run(project.analyses[0])

    assert set(results.element_stresses) == {1, 2}
    for element_id in (1, 2):
        row = results.element_stresses[element_id][0]
        assert row[M11] == pytest.approx(M_LINE, rel=1e-9), element_id
        assert row[V13] == pytest.approx(0.0, abs=1e-6), element_id  # no shear


def test_the_contour_fields_read_that_moment_per_node() -> None:
    """What the renderer paints is the same number the solver recorded."""
    project = _strip()
    results = OpenSeesRunner(project).run(project.analyses[0])

    per_element = element_values(project, results, "M11")
    assert per_element == {1: pytest.approx(M_LINE), 2: pytest.approx(M_LINE)}

    nodal = nodal_values(project, results, "M11")
    assert set(nodal) == {1, 2, 3, 4, 5, 6}
    assert all(value == pytest.approx(M_LINE) for value in nodal.values())

    # And the principal bending moment of a cylindrical state is M11 itself.
    assert element_values(project, results, "M1")[1] == pytest.approx(M_LINE, rel=1e-6)


def test_the_tip_deflection_matches_cylindrical_bending() -> None:
    project = _strip()
    runner = OpenSeesRunner(project)
    results = runner.run(project.analyses[0])

    tip = float(results.node_disp[3][-1][2])
    expected = M_LINE * L**2 / (2.0 * D)
    assert abs(tip) == pytest.approx(expected, rel=0.05), (
        f"tip {tip:.6e} m against {expected:.6e} m of cylindrical bending"
    )
    # Rotation at the tip: theta = M L / D, and the same 5 % band.
    rotation = float(results.node_disp[3][-1][4])
    assert abs(rotation) == pytest.approx(M_LINE * L / D, rel=0.05)


def test_a_linear_case_reports_the_same_resultants() -> None:
    """The algorithm does not matter: the runner reads after ``ops.reactions()``.

    An earlier probe asked `eleResponse` *straight after* ``analyze`` and got
    zeros for `Linear`; with `reactions()` in between — which is what the runner
    does — the section state is materialised and the answer is the same as
    Newton's. Pinned here so nobody re-adds a "Linear shows nothing" caveat to
    the view.
    """
    project = _strip()
    project.analyses[0].algorithm = "Linear"
    results = OpenSeesRunner(project).run(project.analyses[0])

    assert set(results.element_stresses) == {1, 2}
    for element_id in (1, 2):
        row = results.element_stresses[element_id][0]
        assert row[M11] == pytest.approx(M_LINE, rel=1e-9), element_id
    assert results.disp(3, 3) != 0.0
