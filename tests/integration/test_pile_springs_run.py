"""A pile on generated soil springs reaches the capacities the formulas give.

* Pushed down far enough, the head force tends to the axial capacity: the sum of
  the shaft friction of every t-z spring plus the tip's q-z capacity.
* Pushed sideways, a short rigid-ish pile in uniform clay mobilises the lateral
  springs: at large displacement the head force is bounded by the sum of their
  capacities, and stays below it.
"""

from __future__ import annotations

import pytest

pytest.importorskip("openseespy")

from opensees_studio.core import (
    ElasticBeamColumn,
    ElasticSection,
    LinearTimeSeries,
    NodalLoad,
    Node,
    PlainLoadPattern,
    Project,
    PushoverCase,
)
from opensees_studio.core.piles import PileSpec, SoilLayer, pile_springs
from opensees_studio.services.opensees_runner import OpenSeesRunner

D = 0.6
CLAY = SoilLayer(top=0.0, bottom=30.0, kind="clay", unit_weight=8e3, su=40e3)


def _pile_on_springs(direction: int) -> tuple[Project, float]:
    nodes = [Node(id=k + 1, coords=(0.0, 0.0, -1.0 * k)) for k in range(11)]  # 0 .. -10 m
    project = Project(
        ndm=2,
        ndf=3,
        nodes=nodes,
        sections=[ElasticSection(id=1, E=30e9, A=0.283, Iz=6.4e-3, Iy=6.4e-3, G=12e9, J=1e-2)],
        elements=[
            ElasticBeamColumn(id=k + 1, nodes=(k + 1, k + 2), section_id=1) for k in range(10)
        ],
    )
    spec = PileSpec(diameter=D, ground_level=0.0, layers=(CLAY,), stress_unit=1e3)
    springs = pile_springs(
        project,
        set(range(1, 11)),
        spec,
        first_node_id=100,
        first_material_id=1,
        first_element_id=100,
    )
    project.nodes += springs.nodes
    project.materials += springs.materials
    project.elements += springs.elements
    forces = (1.0, 0, 0, 0, 0, 0) if direction == 1 else (0, 0, -1.0, 0, 0, 0)
    project.time_series.append(LinearTimeSeries(id=1))
    project.load_patterns.append(
        PlainLoadPattern(id=1, time_series_id=1, nodal_loads=[NodalLoad(node_id=1, forces=forces)])
    )
    if direction == 1:
        capacity = sum(m.pult for m in springs.materials if m.type == "PySimple1")
    else:
        capacity = sum(m.tult for m in springs.materials if m.type == "TzSimple1") + sum(
            m.qult for m in springs.materials if m.type == "QzSimple1"
        )
    return project, capacity


def test_pushed_down_the_pile_reaches_its_axial_capacity() -> None:
    project, capacity = _pile_on_springs(direction=2)
    case = PushoverCase(
        id=1,
        name="Push down",
        pattern_ids=[1],
        control_node=1,
        control_dof=2,
        target_disp=-0.5 * D,
        step_size=0.002,
        algorithm="Newton",
        base_nodes=[n.id for n in project.nodes if n.id >= 100],
    )
    result = OpenSeesRunner(project).run(case)
    head = abs(float(result.base_shear[-1]))
    assert head == pytest.approx(capacity, rel=0.05)


def test_pushed_sideways_the_soil_resistance_stays_below_its_capacity() -> None:
    project, capacity = _pile_on_springs(direction=1)
    case = PushoverCase(
        id=1,
        name="Push sideways",
        pattern_ids=[1],
        control_node=1,
        control_dof=1,
        target_disp=0.2,
        step_size=0.002,
        algorithm="Newton",
        base_nodes=[n.id for n in project.nodes if n.id >= 100],
    )
    result = OpenSeesRunner(project).run(case)
    head = abs(float(result.base_shear[-1]))
    assert 0.1 * capacity < head < capacity
