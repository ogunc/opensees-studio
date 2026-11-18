"""Load combinations on a real model: combining two linear cases equals one run of the summed loads.

The bundled cantilever has a tip load (pattern 1) and a uniform load (pattern 2),
each run by its own linear static case. A pattern carrying 1.2 × the tip load
plus 1.6 × the uniform load, solved as a third case, is what the Linear Add
combination 1.2·case 1 + 1.6·case 2 must reproduce, displacement by
displacement, reaction by reaction and end force by end force. The cases go
through the analysis CLI and the result store, the path the application uses.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("openseespy.opensees")

from opensees_studio.core import (
    CombinationTerm,
    LoadCombination,
    NodalLoad,
    PlainLoadPattern,
    Project,
    StaticCase,
    UniformElementLoad,
)
from opensees_studio.services import load_project, save_project
from opensees_studio.services.combination import combine_results
from opensees_studio.services.element_forces import ForceComponent, extract_diagram_data
from opensees_studio.services.result_store import load_manifest, load_results
from opensees_studio.services.results import StaticResults

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"
TIP, UNIFORM = 1.2, 1.6
SUMMED = 90
"""Pattern and case id of the summed loads (the example uses lower ids)."""


def _with_summed_case(project: Project) -> Project:
    """Add a pattern of 1.2 × pattern 1 + 1.6 × pattern 2 and a linear static case on it."""
    tip, uniform = project.load_patterns[0], project.load_patterns[1]
    assert isinstance(tip, PlainLoadPattern) and isinstance(uniform, PlainLoadPattern)
    project.load_patterns.append(
        PlainLoadPattern(
            id=SUMMED,
            name="Summed",
            time_series_id=tip.time_series_id,
            nodal_loads=[
                NodalLoad(node_id=nl.node_id, forces=tuple(TIP * f for f in nl.forces))  # type: ignore[arg-type]
                for nl in tip.nodal_loads
            ],
            element_loads=[
                UniformElementLoad(
                    element_id=el.element_id,
                    wy=UNIFORM * el.wy,
                    wz=UNIFORM * el.wz,
                    wx=UNIFORM * el.wx,
                )
                for el in uniform.element_loads
            ],
        )
    )
    project.analyses.append(StaticCase(id=SUMMED, name="Summed", pattern_ids=[SUMMED]))
    project.combinations.extend(
        [
            LoadCombination(
                id=1,
                name="1.2TIP+1.6UNI",
                terms=[
                    CombinationTerm(ref_id=1, factor=TIP),
                    CombinationTerm(ref_id=2, factor=UNIFORM),
                ],
            ),
            LoadCombination(
                id=2,
                name="ENV",
                combination_type="Envelope",
                terms=[CombinationTerm(ref_id=1), CombinationTerm(ref_id=2)],
            ),
        ]
    )
    return project


@pytest.fixture(scope="module")
def solved(tmp_path_factory: pytest.TempPathFactory) -> tuple[Project, dict[int, StaticResults]]:
    """The cantilever with the summed case, every case run through the analysis CLI."""
    tmp = tmp_path_factory.mktemp("combos")
    project = _with_summed_case(load_project(EXAMPLES / "cantilever.osmodel"))
    path = save_project(project, tmp / "cantilever_combos.osmodel")
    out = tmp / "results"
    proc = subprocess.run(
        [
            sys.executable,
            "-u",
            "-m",
            "opensees_studio.run",
            "--project",
            str(path),
            "--cases",
            "1",
            "2",
            str(SUMMED),
            "--out",
            str(out),
        ],
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    manifest = load_manifest(out)
    results = {}
    for entry in manifest["cases"]:
        r = load_results(entry, out)
        assert isinstance(r, StaticResults)
        results[r.case_id] = r
    assert set(results) == {1, 2, SUMMED}
    return load_project(path), results


def _close(a: np.ndarray, b: np.ndarray, scale: float) -> None:
    np.testing.assert_allclose(a, b, rtol=1e-9, atol=1e-12 * scale)


def test_linear_add_equals_one_run_of_the_summed_loads(solved) -> None:  # type: ignore[no-untyped-def]
    project, results = solved
    combo = combine_results(project, 1, {1: results[1], 2: results[2]})
    summed = results[SUMMED]
    assert combo.single_valued and combo.warnings == []

    disp_scale = max(float(np.abs(v).max()) for v in summed.node_disp.values())
    force_scale = max(float(np.abs(v).max()) for v in summed.element_forces.values())
    assert summed.node_disp.keys() == combo.max.node_disp.keys()
    for nid, history in summed.node_disp.items():
        _close(combo.max.node_disp[nid][-1], history[-1], disp_scale)
    assert summed.node_reaction.keys() == combo.max.node_reaction.keys()
    for nid, history in summed.node_reaction.items():
        _close(combo.max.node_reaction[nid][-1], history[-1], force_scale)
    assert summed.element_forces.keys() == combo.max.element_forces.keys()
    for eid, history in summed.element_forces.items():
        _close(combo.max.element_forces[eid][-1], history[-1], force_scale)
        _close(combo.min.element_forces[eid][-1], history[-1], force_scale)


def test_envelope_draws_the_envelope_of_the_two_case_diagrams(solved) -> None:  # type: ignore[no-untyped-def]
    project, results = solved
    env = combine_results(project, 2, {1: results[1], 2: results[2]})
    assert not env.single_valued and env.case_ids == [1, 2]
    for comp in (ForceComponent.N, ForceComponent.V2, ForceComponent.M3):
        d1 = extract_diagram_data(project, results[1], comp)
        d2 = extract_diagram_data(project, results[2], comp)
        hi = extract_diagram_data(project, env.max, comp)
        lo = extract_diagram_data(project, env.min, comp)
        for end in ("values_i", "values_j"):
            np.testing.assert_allclose(
                getattr(hi, end), np.maximum(getattr(d1, end), getattr(d2, end))
            )
            np.testing.assert_allclose(
                getattr(lo, end), np.minimum(getattr(d1, end), getattr(d2, end))
            )
    # Both loads push the tip down: the envelope's minimum is the uniform-load tip deflection.
    tip_uy = min(results[1].node_disp[6][-1][1], results[2].node_disp[6][-1][1])
    assert env.min.node_disp[6][0][1] == pytest.approx(tip_uy)
