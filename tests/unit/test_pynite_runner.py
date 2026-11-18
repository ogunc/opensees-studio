"""The PyNite engine refuses what it does not model, and lines its axes up with OpenSees'."""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("Pynite")

from opensees_studio.core import (
    ElasticBeamColumn,
    ElasticSection,
    EqualDOFConstraint,
    FiberSection,
    ModalCase,
    Node,
    PathTimeSeries,
    PlainLoadPattern,
    Project,
    StaticCase,
    ensure_dead_load_case,
    make_default_section,
)
from opensees_studio.core.geometry.frame_options import EndRelease, FrameReleases
from opensees_studio.services.engines import PYNITE, PyNiteEngine, SolverSettings, engines
from opensees_studio.services.pynite_runner import (
    PyNiteRunner,
    PyNiteUnsupportedError,
    _member,
    _solver_axes,
)


def _beam(ndm: int = 3, end: tuple[float, float, float] = (4.0, 0.0, 0.0)) -> Project:
    project = Project(ndm=ndm, ndf=3 if ndm == 2 else 6)
    ensure_dead_load_case(project)
    project.sections.append(make_default_section(1))
    project.nodes += [
        Node(id=1, coords=(0.0, 0.0, 0.0), restraint=(True,) * 6),
        Node(id=2, coords=end),
    ]
    project.elements.append(ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1))
    return project


def _refused(project: Project, match: str, case: object = None) -> None:
    with pytest.raises(PyNiteUnsupportedError, match=match):
        PyNiteRunner(project).run(case or project.analyses[0])


def test_the_engine_is_registered_and_available() -> None:
    assert PYNITE in engines()
    status = PyNiteEngine().status(SolverSettings(engine=PYNITE))
    assert status.available and status.version == "3.2.0"
    assert PyNiteEngine().case_types == {"Static"}


def test_a_modal_case_is_refused() -> None:
    _refused(_beam(), "runs static cases", ModalCase(id=9, name="m"))


def test_a_fibre_section_is_refused() -> None:
    project = _beam()
    project.sections[0] = FiberSection(id=1)
    _refused(project, "needs an elastic section")


def test_shear_areas_are_refused() -> None:
    project = _beam()
    section = project.sections[0]
    assert isinstance(section, ElasticSection)
    project.sections[0] = section.model_copy(update={"As2": 0.008})
    _refused(project, "Timoshenko")


def test_constraints_and_partial_fixity_are_refused() -> None:
    project = _beam()
    project.nodes.append(Node(id=3, coords=(4.0, 0.0, 0.0)))
    project.mp_constraints.append(EqualDOFConstraint(retained_node=2, constrained_node=3, dofs=[1]))
    _refused(project, "equalDOF constraints")
    project = _beam()
    spring = FrameReleases(j=EndRelease(released=("M3",), springs={"M3": 1e5}))
    project.elements[0] = project.elements[0].model_copy(update={"releases": spring})
    _refused(project, "partial-fixity")


def test_a_joint_inside_a_member_is_refused() -> None:
    project = _beam()
    project.nodes.append(Node(id=3, coords=(2.0, 0.0, 0.0)))
    _refused(project, "Divide Frames at Joints")


def test_an_unsupported_time_series_is_refused() -> None:
    project = _beam()
    project.time_series.append(PathTimeSeries(id=7, dt=0.1, values=[0.0, 1.0]))
    project.load_patterns.append(PlainLoadPattern(id=7, time_series_id=7))
    _refused(project, "Linear and", StaticCase(id=5, name="s", pattern_ids=[7]))


@pytest.mark.parametrize(
    ("ndm", "end"),
    [
        (3, (4.0, 0.0, 0.0)),  # beam along X
        (3, (0.0, 4.0, 0.0)),  # beam along Y
        (3, (0.0, 0.0, 3.0)),  # column
        (3, (3.0, 2.0, 4.0)),  # brace
        (3, (0.0, 0.0, -3.0)),  # column drawn downwards
        (2, (4.0, 0.0, 3.0)),  # 2D rafter
        (2, (0.0, 0.0, 3.0)),  # 2D column
    ],
)
def test_pynite_local_axes_match_opensees(ndm: int, end: tuple[float, float, float]) -> None:
    project = _beam(ndm, end)
    runner = PyNiteRunner(project)
    model = runner._build(project.analyses[0])
    transform = model.members[_member(1)].T()
    x, y, z = _solver_axes(project, project.elements[0])
    np.testing.assert_allclose(transform[0, :3], x, atol=1e-12)
    np.testing.assert_allclose(transform[1, :3], y, atol=1e-9)
    np.testing.assert_allclose(transform[2, :3], z, atol=1e-9)
