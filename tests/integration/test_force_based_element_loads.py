"""Element loads on force-based frames, solved with the default StaticCase.

A force-based frame (``forceBeamColumn``, ``beamWithHinges``) only takes an
element load into its resisting force at its next state determination, so the
first solve of a step moves nothing: Linear stops there, and Newton with an
increment test (NormDispIncr, EnergyIncr) takes it as convergence. Either way a
simply supported beam reports the fixed-end reactions and no end rotation. The
runner follows each such step with a zero-increment correction solve; these
tests pin the result to the lever rule and to the converged Newton answer.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("openseespy.opensees")

from opensees_studio.core import (
    BeamWithHingesElement,
    ElasticBeamColumn,
    ElasticSection,
    ForceBeamColumn,
    LinearTimeSeries,
    Node,
    PlainLoadPattern,
    PointElementLoad,
    Project,
    StaticCase,
    UniformElementLoad,
)
from opensees_studio.services.opensees_runner import OpenSeesRunner

E = 2e8
AREA = 0.01
I_SEC = 1e-4
LENGTH = 4.0
LOAD = 10.0
A_POS = 1.0  # distance of the point load from end i


def _element(kind: str):  # type: ignore[no-untyped-def]
    if kind == "force":
        return ForceBeamColumn(id=1, nodes=(1, 2), section_id=1)
    if kind == "hinges":
        return BeamWithHingesElement(
            id=1,
            nodes=(1, 2),
            section_i_id=1,
            section_j_id=1,
            lp_i=0.4,
            lp_j=0.4,
            E=E,
            A=AREA,
            Iz=I_SEC,
        )
    return ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1)


def _beam(kind: str, load: str, *, n_steps: int = 1) -> Project:
    pattern = PlainLoadPattern(id=1, time_series_id=1)
    if load == "uniform":
        pattern.element_loads.append(UniformElementLoad(element_id=1, wy=-LOAD))
    else:
        pattern.point_loads.append(PointElementLoad(element_id=1, py=-LOAD, x=A_POS / LENGTH))
    return Project(
        ndm=2,
        ndf=3,
        nodes=[
            Node(id=1, coords=(0.0, 0.0, 0.0), restraint=(True, False, True, False, False, False)),
            Node(
                id=2, coords=(LENGTH, 0.0, 0.0), restraint=(False, False, True, False, False, False)
            ),
        ],
        sections=[ElasticSection(id=1, name="S", E=E, A=AREA, Iz=I_SEC)],
        elements=[_element(kind)],
        time_series=[LinearTimeSeries(id=1)],
        load_patterns=[pattern],
        analyses=[
            StaticCase(
                id=1,
                name="gravity",
                n_steps=n_steps,
                load_factor_increment=1.0 / n_steps,
                pattern_ids=[1],
            )
        ],
    )


def _solve(project: Project, tmp_path: Path):  # type: ignore[no-untyped-def]
    return OpenSeesRunner(project).run(project.analyses[0], results_dir=tmp_path)


def _lever_rule(load: str) -> tuple[float, float]:
    if load == "uniform":
        return LOAD * LENGTH / 2, LOAD * LENGTH / 2
    return LOAD * (LENGTH - A_POS) / LENGTH, LOAD * A_POS / LENGTH


@pytest.mark.parametrize("load", ["uniform", "point"])
@pytest.mark.parametrize("kind", ["force", "hinges"])
def test_the_default_static_case_gives_the_lever_rule(kind: str, load: str, tmp_path: Path) -> None:
    project = _beam(kind, load)
    assert project.analyses[0].algorithm == "Linear"

    results = _solve(project, tmp_path)

    r1, r2 = _lever_rule(load)
    assert float(results.node_reaction[1][0][1]) == pytest.approx(r1, rel=1e-9)
    assert float(results.node_reaction[2][0][1]) == pytest.approx(r2, rel=1e-9)


@pytest.mark.parametrize("load", ["uniform", "point"])
@pytest.mark.parametrize("kind", ["force", "hinges"])
def test_the_end_rotation_matches_the_converged_newton_answer(
    kind: str, load: str, tmp_path: Path
) -> None:
    linear = _solve(_beam(kind, load), tmp_path / "linear")
    newton_project = _beam(kind, load)
    newton_project.analyses[0] = newton_project.analyses[0].model_copy(
        update={"algorithm": "Newton", "test": "NormUnbalance"}
    )
    newton = _solve(newton_project, tmp_path / "newton")

    rotation = float(linear.node_disp[1][0][2])
    assert rotation != 0.0
    assert rotation == pytest.approx(float(newton.node_disp[1][0][2]), rel=1e-9)


def test_the_uniform_load_end_rotation_is_exact(tmp_path: Path) -> None:
    # Lobatto with five points integrates the cubic M·m product exactly.
    results = _solve(_beam("force", "uniform"), tmp_path)

    expected = LOAD * LENGTH**3 / (24 * E * I_SEC)
    # The left end of a sagging beam turns X toward -Z: a positive rotation about Y.
    assert float(results.node_disp[1][0][2]) == pytest.approx(expected, rel=1e-9)


@pytest.mark.parametrize("load", ["uniform", "point"])
def test_every_step_carries_its_own_share_of_the_load(load: str, tmp_path: Path) -> None:
    n_steps = 4
    results = _solve(_beam("force", load, n_steps=n_steps), tmp_path)

    r1, r2 = _lever_rule(load)
    for step in range(n_steps):
        factor = (step + 1) / n_steps
        assert float(results.node_reaction[1][step][1]) == pytest.approx(factor * r1, rel=1e-9)
        assert float(results.node_reaction[2][step][1]) == pytest.approx(factor * r2, rel=1e-9)


def _with_solver(project: Project, algorithm: str, test: str) -> Project:
    project.analyses[0] = project.analyses[0].model_copy(
        update={"algorithm": algorithm, "test": test}
    )
    return project


@pytest.mark.parametrize(
    ("algorithm", "test"),
    [
        ("Newton", "NormDispIncr"),
        ("Newton", "EnergyIncr"),
        ("ModifiedNewton", "NormDispIncr"),
        ("KrylovNewton", "EnergyIncr"),
        ("BFGS", "NormDispIncr"),
    ],
)
@pytest.mark.parametrize("load", ["uniform", "point"])
def test_an_iterating_case_with_an_increment_test_converges_on_the_load(
    algorithm: str, test: str, load: str, tmp_path: Path
) -> None:
    # The first iteration of such a step moves nothing, which an increment
    # test would take as convergence on the lagging answer.
    n_steps = 3
    project = _with_solver(_beam("force", load, n_steps=n_steps), algorithm, test)
    reference = _with_solver(_beam("force", load, n_steps=n_steps), "Newton", "NormUnbalance")

    results = _solve(project, tmp_path / "case")
    converged = _solve(reference, tmp_path / "reference")

    r1, r2 = _lever_rule(load)
    for step in range(n_steps):
        factor = (step + 1) / n_steps
        assert float(results.node_reaction[1][step][1]) == pytest.approx(factor * r1, rel=1e-7)
        assert float(results.node_reaction[2][step][1]) == pytest.approx(factor * r2, rel=1e-7)
        assert float(results.node_disp[1][step][2]) == pytest.approx(
            float(converged.node_disp[1][step][2]), rel=1e-7
        )


def test_a_relative_test_solves_a_single_step(tmp_path: Path) -> None:
    project = _with_solver(_beam("force", "point"), "Newton", "RelativeNormDispIncr")

    results = _solve(project, tmp_path)

    r1, _ = _lever_rule("point")
    assert float(results.node_reaction[1][0][1]) == pytest.approx(r1, rel=1e-7)


def test_a_relative_test_over_several_steps_is_refused_with_a_reason(tmp_path: Path) -> None:
    project = _with_solver(_beam("force", "point", n_steps=2), "Newton", "RelativeNormDispIncr")

    with pytest.raises(ValueError, match="RelativeNormDispIncr test cannot converge"):
        _solve(project, tmp_path)


def test_only_force_based_element_loads_take_the_correction_solve() -> None:
    elastic = _beam("elastic", "uniform")
    force = _beam("force", "uniform")
    newton = _with_solver(_beam("force", "uniform"), "Newton", "NormDispIncr")
    newton_unbalance = _with_solver(_beam("force", "uniform"), "Newton", "NormUnbalance")
    linear_unbalance = _with_solver(_beam("force", "uniform"), "Linear", "NormUnbalance")
    no_loads = _beam("force", "uniform")
    no_loads.load_patterns[0].element_loads.clear()

    def needs(project: Project) -> bool:
        case = project.analyses[0]
        return OpenSeesRunner(project)._needs_correction_solve(case, case.pattern_ids)

    assert needs(force)
    assert needs(newton)
    # Linear ignores its test, so a force test does not spare it the correction.
    assert needs(linear_unbalance)
    assert not needs(newton_unbalance)
    assert not needs(elastic)
    assert not needs(no_loads)
