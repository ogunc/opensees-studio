"""EN 1990 equation 6.10 on a one-member model, against closed-form numbers.

A cantilever of length ``L`` takes a vertical tip force per case: permanent G,
imposed Q and wind W. The tip deflection is ``P L^3 / 3EI`` and the fixed-end
moment ``P L``, both linear in the force, so every generated combination has
the closed-form response ``(sum of factor x P)`` times those. The generated
set goes through ``combine_results`` and the real solver.
"""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("openseespy.opensees")

from opensees_studio.core import (
    CombinationTerm,
    ElasticBeamColumn,
    ElasticSection,
    LinearTimeSeries,
    LoadCombination,
    NodalLoad,
    Node,
    PlainLoadPattern,
    Project,
    ProjectMeta,
    StaticCase,
    UnitSystem,
)
from opensees_studio.core.code_combinations import generate_for_code
from opensees_studio.services.combination import combine_results
from opensees_studio.services.opensees_runner import OpenSeesRunner

LENGTH, E_MOD, I_MOD = 2.0, 200e9, 1.0e-4
P_G, P_Q, P_W = 10_000.0, 6_000.0, 4_000.0
GRAVITY, IMPOSED, WIND = 1, 2, 3


def _project() -> Project:
    patterns = [
        PlainLoadPattern(
            id=i,
            name=name,
            time_series_id=1,
            nodal_loads=[NodalLoad(node_id=2, forces=(0.0, 0.0, -force, 0.0, 0.0, 0.0))],
        )
        for i, (name, force) in enumerate((("G", P_G), ("Q", P_Q), ("W", P_W)), start=1)
    ]
    return Project(
        meta=ProjectMeta(name="en1990 cantilever", units=UnitSystem.SI_M_N),
        ndm=2,
        ndf=3,
        nodes=[
            Node(id=1, coords=(0.0, 0.0, 0.0), restraint=(True,) * 6),
            Node(id=2, coords=(LENGTH, 0.0, 0.0)),
        ],
        elements=[ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1)],
        sections=[ElasticSection(id=1, name="s", E=E_MOD, A=1.0, Iz=I_MOD)],
        time_series=[LinearTimeSeries(id=1, name="ramp")],
        load_patterns=patterns,
        analyses=[
            StaticCase(id=i, name=name, pattern_ids=[i]) for i, name in enumerate("GQW", start=1)
        ],
    )


@pytest.fixture(scope="module")
def solved() -> tuple[Project, dict[int, object], dict[str, int]]:
    project = _project()
    generated = generate_for_code("en1990", {"D": [GRAVITY], "L": [IMPOSED], "W": [WIND]})
    ids = {}
    for i, combo in enumerate(generated, start=1):
        project.combinations.append(LoadCombination(id=i, name=combo.name, terms=combo.terms))
        ids[combo.name] = i
    results = {case.id: OpenSeesRunner(project).run(case) for case in project.analyses}
    return project, results, ids


def _expect(load: float) -> tuple[float, float]:
    """Tip deflection and fixed-end moment magnitude of a downward tip force ``load``."""
    return load * LENGTH**3 / (3 * E_MOD * I_MOD), load * LENGTH


def test_equation_610_gravity_combination(solved) -> None:  # type: ignore[no-untyped-def]
    project, results, ids = solved
    out = combine_results(project, ids["ULS 1.35G+1.5Q"], results)
    load = 1.35 * P_G + 1.5 * P_Q  # 22 500 N
    deflection, moment = _expect(load)
    assert out.single_valued
    np.testing.assert_allclose(abs(out.max.node_disp[2][-1][1]), deflection, rtol=1e-9)
    np.testing.assert_allclose(abs(out.max.node_reaction[1][-1][2]), moment, rtol=1e-9)
    np.testing.assert_allclose(out.max.node_reaction[1][-1][1], load, rtol=1e-9)


def test_equation_610_with_wind_accompanying_uses_psi0() -> None:
    project = _project()
    generated = {
        c.name: c
        for c in generate_for_code("en1990", {"D": [GRAVITY], "L": [IMPOSED], "W": [WIND]})
    }
    results = {case.id: OpenSeesRunner(project).run(case) for case in project.analyses}
    for sign, label in ((1.0, "+"), (-1.0, "-")):
        combo = generated[f"ULS 1.35G+1.5Q{label}0.9W"]
        project.combinations.append(LoadCombination(id=9, name=combo.name, terms=combo.terms))
        out = combine_results(project, 9, results)
        project.combinations.clear()
        # 1.35 G + 1.5 Q + (+-) 1.5 x 0.6 W, the wind psi0 of Table A1.1.
        load = 1.35 * P_G + 1.5 * P_Q + sign * 1.5 * 0.6 * P_W
        deflection, moment = _expect(load)
        np.testing.assert_allclose(abs(out.max.node_disp[2][-1][1]), deflection, rtol=1e-9)
        np.testing.assert_allclose(abs(out.max.node_reaction[1][-1][2]), moment, rtol=1e-9)


def test_envelope_of_the_generated_ultimate_combinations(solved) -> None:  # type: ignore[no-untyped-def]
    project, results, ids = solved
    uls = [i for name, i in ids.items() if name.startswith("ULS ")]
    project.combinations.append(
        LoadCombination(
            id=99,
            name="ULS envelope",
            combination_type="Envelope",
            terms=[CombinationTerm(source="combination", ref_id=i) for i in uls],
        )
    )
    try:
        out = combine_results(project, 99, results)
    finally:
        project.combinations.pop()
    # The governing load is wind leading with the imposed load at psi0 = 0.7, or
    # imposed leading; the largest downward tip force of the set bounds the moment.
    loads = [
        1.35 * P_G + 1.5 * P_Q + 0.9 * P_W,
        1.35 * P_G + 1.05 * P_Q + 1.5 * P_W,
    ]
    _, moment = _expect(max(loads))
    np.testing.assert_allclose(
        np.max(np.abs([out.max.node_reaction[1][-1][2], out.min.node_reaction[1][-1][2]])),
        moment,
        rtol=1e-9,
    )


def test_serviceability_quasi_permanent_uses_psi2(solved) -> None:  # type: ignore[no-untyped-def]
    project, results, ids = solved
    out = combine_results(project, ids["SLS quasi G+0.3Q"], results)
    deflection, _ = _expect(P_G + 0.3 * P_Q)
    np.testing.assert_allclose(abs(out.max.node_disp[2][-1][1]), deflection, rtol=1e-9)
