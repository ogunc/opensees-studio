"""What a duplicated model does to a real solve, and what the repair restores.

The interesting part is that the deflection of a copied model *looks* right: the
copy doubled the stiffness and the load together, so the tip moves exactly as it
should. The reactions are what give it away — they are double — and that is what
this module pins, against the closed form for a cantilever,

    w = P L^3 / (3 E I),   R = P,

rather than against the application's own output.

Measured on this build (P = 1 kN, L = 2 m, E = 200 GPa, I = 1e-6 m⁴):

=============  ================  ==============
model          tip deflection    total reaction
=============  ================  ==============
reference      1.333333e-2 m     1000 N
copied         1.333333e-2 m     2000 N
closed form    1.333333e-2 m     1000 N
=============  ================  ==============
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("openseespy.opensees")

from opensees_studio.commands import FixDuplicatesCommand
from opensees_studio.core import (
    ElasticBeamColumn,
    ElasticSection,
    LinearTimeSeries,
    NodalLoad,
    Node,
    PlainLoadPattern,
    Project,
    StaticCase,
)
from opensees_studio.services.opensees_runner import OpenSeesRunner
from opensees_studio.viewmodels import ProjectViewModel

E = 200e9
"""Elastic modulus, Pa."""
I_SEC = 1e-6
"""Second moment of area, m^4 (equal about both local axes, so the local-axis
convention of a member along X cannot change the answer)."""
LENGTH = 2.0
"""Cantilever length, m."""
LOAD = 1000.0
"""Tip load, N (downwards)."""

W_CLASSICAL = LOAD * LENGTH**3 / (3.0 * E * I_SEC)
"""Tip deflection, m."""


def _section() -> ElasticSection:
    return ElasticSection(id=1, name="S", E=E, A=0.01, Iz=I_SEC, Iy=I_SEC, G=80e9, J=1e-6)


def _project(nodes: list[Node], elements: list, loads: list[NodalLoad]) -> Project:
    return Project(
        ndm=3,
        ndf=6,
        nodes=nodes,
        sections=[_section()],
        elements=elements,
        time_series=[LinearTimeSeries(id=1)],
        load_patterns=[PlainLoadPattern(id=1, time_series_id=1, nodal_loads=loads)],
        analyses=[StaticCase(id=1, name="tip", n_steps=1, pattern_ids=[1])],
    )


def _tip_load(node_id: int) -> NodalLoad:
    return NodalLoad(node_id=node_id, forces=(0.0, 0.0, -LOAD, 0, 0, 0))


def _fixed(node_id: int, x: float = 0.0) -> Node:
    return Node(id=node_id, coords=(x, 0.0, 0.0), restraint=(True,) * 6)


def _free(node_id: int, x: float) -> Node:
    return Node(id=node_id, coords=(x, 0.0, 0.0))


def _reference() -> Project:
    return _project(
        [_fixed(1), _free(2, LENGTH)],
        [ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1)],
        [_tip_load(2)],
    )


def _copied() -> Project:
    """The whole cantilever twice: as ``Edit → Replicate`` with a zero offset leaves it."""
    return _project(
        [_fixed(1), _free(2, LENGTH), _fixed(3), _free(4, LENGTH)],
        [
            ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1),
            ElasticBeamColumn(id=2, nodes=(3, 4), section_id=1),
        ],
        [_tip_load(2), _tip_load(4)],
    )


def _run(project: Project, tmp_path: Path, name: str):  # type: ignore[no-untyped-def]
    return OpenSeesRunner(project).run(project.analyses[0], results_dir=tmp_path / name)


def _tip_deflection(results, node_id: int = 2) -> float:  # type: ignore[no-untyped-def]
    return abs(float(results.node_disp[node_id][0][2]))


def _support_reaction(results, project: Project) -> float:  # type: ignore[no-untyped-def]
    """Total vertical reaction at every restrained support."""
    fixed = [node.id for node in project.nodes if node.restraint[2]]
    return abs(sum(float(results.node_reaction[node_id][0][2]) for node_id in fixed))


def test_the_reference_cantilever_matches_the_closed_form(tmp_path: Path) -> None:
    project = _reference()
    results = _run(project, tmp_path, "reference")

    assert _tip_deflection(results) == pytest.approx(W_CLASSICAL, rel=1e-9)
    assert _support_reaction(results, project) == pytest.approx(LOAD, rel=1e-9)


def test_a_copied_model_hides_in_the_deflection_and_shows_in_the_reactions(
    tmp_path: Path,
) -> None:
    """Why this tool is worth having: the deformed shape looks perfect."""
    reference_project = _reference()
    copied_project = _copied()
    reference = _run(reference_project, tmp_path, "reference")
    copied = _run(copied_project, tmp_path, "copied")

    # The deformed shape is right — the copy doubled stiffness and load together.
    assert _tip_deflection(copied) == pytest.approx(_tip_deflection(reference), rel=1e-9)
    # The supports carry twice the load the structure is meant to carry.
    assert _support_reaction(copied, copied_project) == pytest.approx(
        2.0 * _support_reaction(reference, reference_project),
        rel=1e-9,
    )


def test_the_repair_puts_the_model_back_on_the_closed_form(tmp_path: Path) -> None:
    project = _copied()
    vm = ProjectViewModel()
    vm.new_project()
    vm._project = project  # the commands need a view model; the model is the one under test
    command = FixDuplicatesCommand(vm)
    vm.apply_command(command)

    assert [node.id for node in project.nodes] == [1, 2]
    assert [element.id for element in project.elements] == [1]
    assert [load.node_id for load in project.load_patterns[0].nodal_loads] == [2]

    results = _run(project, tmp_path, "repaired")

    assert _tip_deflection(results) == pytest.approx(W_CLASSICAL, rel=1e-9)
    assert _support_reaction(results, project) == pytest.approx(LOAD, rel=1e-9)
    assert command.report.removed_nodes == 2
    assert command.report.removed_elements == 1
