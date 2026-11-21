"""A static case with preload cases runs them first and reports the whole state.

``StaticCase.preload_case_ids`` (SAP2000's "initial conditions from another
case", read by the S2K importer) used to be ignored by the static runner: the
case ran from zero and said nothing. The preloads now run first, are locked with
``loadConst -time 0``, and the case's results include them.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("openseespy")

from opensees_studio.core import (
    ElasticUniaxial,
    NodalLoad,
    Node,
    PlainLoadPattern,
    PointElementLoad,
    Project,
    StaticCase,
    UniformElementLoad,
    ensure_dead_load_case,
)
from opensees_studio.core.geometry.elements import TrussElement
from opensees_studio.core.loads import TemperatureLoad
from opensees_studio.services.opensees_runner import OpenSeesRunner
from opensees_studio.services.opensees_script import export_script
from opensees_studio.services.pynite_runner import (
    PyNiteRunner,
    PyNiteUnsupportedError,
)
from tests.integration.test_frame_member_options import (
    I_SEC,
    W,
    _shear_cantilever,
)

EA = 1000.0  # truss axial stiffness, length 1


def _bar(main: float = 1.0, pre: float = 100.0) -> Project:
    """A unit truss along X: case 1 pushes ``main``, case 2 (the preload) ``pre``."""
    project = Project(ndm=2, ndf=2)
    ensure_dead_load_case(project)
    project.materials.append(ElasticUniaxial(id=1, name="E", E=EA))
    project.nodes += [
        Node(id=1, coords=(0.0, 0.0, 0.0), restraint=(True,) * 6),
        Node(id=2, coords=(1.0, 0.0, 0.0), restraint=(False, True, True, True, True, True)),
    ]
    project.elements.append(TrussElement(id=1, nodes=(1, 2), area=1.0, material_id=1))
    project.load_patterns[0].nodal_loads.append(
        NodalLoad(node_id=2, forces=(main, 0.0, 0.0, 0.0, 0.0, 0.0))
    )
    series = project.load_patterns[0].time_series_id
    project.load_patterns.append(
        PlainLoadPattern(
            id=2,
            time_series_id=series,
            nodal_loads=[NodalLoad(node_id=2, forces=(pre, 0.0, 0.0, 0.0, 0.0, 0.0))],
        )
    )
    project.analyses.append(StaticCase(id=2, name="PRE", pattern_ids=[2]))
    project.analyses[0] = project.analyses[0].model_copy(update={"preload_case_ids": [2]})
    return project


def test_the_preload_is_part_of_the_case_results(tmp_path: Path) -> None:
    project = _bar()
    results = OpenSeesRunner(project).run(project.analyses[0], results_dir=tmp_path)

    assert results.node_disp[2][-1][0] == pytest.approx(101.0 / EA)
    assert results.node_reaction[1][-1][0] == pytest.approx(-101.0)
    assert abs(results.element_forces[1][-1][0]) == pytest.approx(101.0, rel=1e-9)
    assert any("Preloaded by PRE" in note for note in results.warnings)


def test_a_linear_preload_equals_one_case_with_both_patterns(tmp_path: Path) -> None:
    project = _bar(main=3.0, pre=7.0)
    preloaded = OpenSeesRunner(project).run(project.analyses[0], results_dir=tmp_path / "a")
    both = StaticCase(id=3, name="BOTH", pattern_ids=[1, 2])
    project.analyses.append(both)
    summed = OpenSeesRunner(project).run(both, results_dir=tmp_path / "b")
    assert preloaded.node_disp[2][-1] == pytest.approx(summed.node_disp[2][-1])
    assert preloaded.node_reaction[1][-1] == pytest.approx(summed.node_reaction[1][-1])


def test_the_preload_case_alone_is_unchanged(tmp_path: Path) -> None:
    project = _bar()
    results = OpenSeesRunner(project).run(project.analyses[1], results_dir=tmp_path)
    assert results.node_disp[2][-1][0] == pytest.approx(100.0 / EA)


def test_the_exported_script_runs_the_preload_first() -> None:
    project = _bar()
    script = export_script(project, project.analyses[0])
    assert "loadConst('-time', 0.0)" in script or 'loadConst("-time", 0.0)' in script


def test_a_point_load_in_the_preload_drops_the_shear_areas(tmp_path: Path) -> None:
    project = _shear_cantilever(ndm=2, as2=0.008, as3=None, iz=I_SEC, iy=I_SEC, load=())
    project.load_patterns[0] = PlainLoadPattern(
        id=1, time_series_id=1, element_loads=[UniformElementLoad(element_id=1, wy=-W)]
    )
    project.load_patterns.append(
        PlainLoadPattern(
            id=2, time_series_id=1, point_loads=[PointElementLoad(element_id=1, x=0.5, py=-W)]
        )
    )
    project.analyses.append(StaticCase(id=2, name="PRE", pattern_ids=[2], n_steps=1))
    project.analyses[0] = project.analyses[0].model_copy(update={"preload_case_ids": [2]})
    results = OpenSeesRunner(project).run(project.analyses[0], results_dir=tmp_path)
    assert any("As2 = As3 = 0" in note for note in results.warnings)


def test_a_case_cannot_preload_itself(tmp_path: Path) -> None:
    project = _bar()
    project.analyses[0] = project.analyses[0].model_copy(update={"preload_case_ids": [1]})
    with pytest.raises(ValueError, match="creates a cycle"):
        OpenSeesRunner(project).run(project.analyses[0], results_dir=tmp_path)


def test_a_heated_preload_is_refused(tmp_path: Path) -> None:
    project = _shear_cantilever(ndm=2, as2=None, as3=None, iz=I_SEC, iy=I_SEC, load=())
    project.load_patterns[0] = PlainLoadPattern(
        id=1, time_series_id=1, element_loads=[UniformElementLoad(element_id=1, wy=-W)]
    )
    project.load_patterns.append(
        PlainLoadPattern(
            id=2,
            time_series_id=1,
            temperature_loads=[TemperatureLoad(element_id=1, uniform=20.0, alpha=1.2e-5)],
        )
    )
    project.analyses.append(StaticCase(id=2, name="PRE", pattern_ids=[2], n_steps=1))
    project.analyses[0] = project.analyses[0].model_copy(update={"preload_case_ids": [2]})
    with pytest.raises(ValueError, match="temperature loads"):
        OpenSeesRunner(project).run(project.analyses[0], results_dir=tmp_path)


def test_pynite_refuses_a_preloaded_static_case() -> None:
    project = _bar()
    with pytest.raises(PyNiteUnsupportedError, match="preload cases"):
        PyNiteRunner(project).run(project.analyses[0])
