"""The generated warehouse, solved by OpenSees and taken through the steel check."""

from __future__ import annotations

import math

import numpy as np
import pytest

pytest.importorskip("openseespy.opensees")

from examples.warehouse_gable import build_warehouse_project

from opensees_studio.core.frames import RoofType, SupportCondition
from opensees_studio.core.project import Project
from opensees_studio.core.warehouse import (
    WarehouseLoads,
    WarehouseSpec,
    plan_warehouse,
)
from opensees_studio.services.opensees_runner import OpenSeesRunner
from opensees_studio.services.steel_design import member_lengths, steel_frame_check

KGF = 9.80665
SLOPE_LENGTH = math.hypot(10.0, 1.0)


def _results(project: Project) -> dict[int, object]:
    return {case.id: OpenSeesRunner(project).run(case) for case in project.analyses}


def _vertical_reaction(results: object) -> float:
    return float(
        sum(np.asarray(r).reshape(-1, 6)[-1][2] for r in results.node_reaction.values())  # type: ignore[attr-defined]
    )


@pytest.fixture(scope="module")
def solved() -> tuple[Project, dict[int, object]]:
    project = build_warehouse_project()
    return project, _results(project)


def test_the_live_case_carries_the_roof_load_and_the_ridge_loads(solved) -> None:  # type: ignore[no-untyped-def]
    project, results = solved
    live = next(c for c in project.analyses if c.name == "LIVE")
    expected = 10 * KGF * 20.0 * 30.0 + 6 * 200 * KGF
    assert _vertical_reaction(results[live.id]) == pytest.approx(expected, rel=1e-9)


def test_the_dead_case_carries_the_cladding_and_the_self_weight(solved) -> None:  # type: ignore[no-untyped-def]
    project, results = solved
    dead = next(c for c in project.analyses if c.name == "DEAD")
    cladding = 100.0 * 2 * SLOPE_LENGTH * 30.0
    sections = {s.id: s for s in project.sections}
    nodes = {n.id: np.asarray(n.coords) for n in project.nodes}
    steel = sum(
        sections[e.section_id].unit_weight
        * sections[e.section_id].A
        * float(np.linalg.norm(nodes[e.nodes[1]] - nodes[e.nodes[0]]))
        for e in project.elements
    )
    assert steel > 0.0
    assert _vertical_reaction(results[dead.id]) == pytest.approx(cladding + steel, rel=1e-9)


def test_gravity_does_not_rack_the_building_along_its_length(solved) -> None:  # type: ignore[no-untyped-def]
    """Symmetric gravity on a braced building: the frames stay in their planes."""
    _project, results = solved
    for case_results in results.values():
        disp = np.array([np.asarray(d).reshape(-1, 6)[-1] for d in case_results.node_disp.values()])
        assert np.all(np.isfinite(disp))
        assert np.abs(disp[:, 2]).max() < 0.05  # centimetres, not a mechanism
        assert np.abs(disp[:, 1]).max() < 1e-3


def test_the_steel_check_takes_the_stabilised_purlins_not_every_purlin(solved) -> None:  # type: ignore[no-untyped-def]
    project, results = solved
    rafters = set(next(g for g in project.groups if g.name == "Rafters").element_ids)
    purlin_gap = SLOPE_LENGTH / 7
    # As modelled, every purlin frames into the rafter and would count as a brace.
    automatic = {
        m.element_id: m.unbraced for m in member_lengths(project) if m.element_id in rafters
    }
    assert {round(lb, 6) for _lx, _ly, lb in automatic.values()} == {round(purlin_gap, 6)}

    report = steel_frame_check(project, results, project.design)
    checked = {m.element_id: m for m in report.members if m.element_id in rafters}
    assert len(checked) == len(rafters)
    for member in checked.values():
        assert member.shape == "W16X40"
        _lx, ly, lb = member.unbraced
        # Every second purlin has a stabilising angle; the last interval before
        # the ridge is a single space.
        assert lb == ly
        assert lb == pytest.approx(2 * purlin_gap) or lb == pytest.approx(purlin_gap)
    assert max(m.unbraced[2] for m in checked.values()) == pytest.approx(2 * purlin_gap)
    assert all(m.ratio > 0.0 for m in checked.values())

    columns = set(next(g for g in project.groups if g.name == "Columns").element_ids)
    side = [m for m in report.members if m.element_id in columns]
    assert {round(m.unbraced[2], 9) for m in side} == {6.0}  # girts without angles


def test_without_stabilising_angles_the_whole_slope_is_unbraced() -> None:
    project = build_warehouse_project()
    project.nodes.clear()
    project.elements.clear()
    project.groups.clear()
    project.design = None
    for pattern in project.load_patterns:
        pattern.element_loads.clear()  # type: ignore[union-attr]
        pattern.nodal_loads.clear()  # type: ignore[union-attr]
    spec = WarehouseSpec(span=20.0, eave_height=6.0, frame_spacing=6.0, n_frames=3)
    ids = {s.name: s.id for s in project.sections}
    plan = plan_warehouse(
        project,
        spec,
        sections={
            "column": ids["W14X48"],
            "rafter": ids["W16X40"],
            "purlin": ids["C150X50X15X2.38"],
            "girt": ids["C150X50X15X2.38"],
            "brace": ids["L3X3X1_4"],
        },
        loads=WarehouseLoads(roof_dead=100.0, roof_live=98.0),
        with_grid=False,
    )
    plan.apply(project)
    report = steel_frame_check(project, _results(project), project.design)
    rafters = set(plan.warehouse.members["rafters"])
    lbs = {round(m.unbraced[2], 9) for m in report.members if m.element_id in rafters}
    assert lbs == {round(SLOPE_LENGTH, 9)}


@pytest.mark.parametrize(
    "fields",
    [
        {"roof": RoofType.MONO_PITCH, "span": 12.0},
        {"n_naves": 3, "span": 12.0},
        {"slope": 0.0, "roof": RoofType.MONO_PITCH, "support": SupportCondition.FIXED},
        {"n_frames": 2, "girt_spacing": 2.0, "wall_bracing": True},
    ],
)
def test_other_shapes_are_stable_and_in_equilibrium(fields: dict) -> None:  # type: ignore[type-arg]
    project = Project(ndm=3, ndf=6)
    values = {"span": 16.0, "eave_height": 5.0, "frame_spacing": 5.0, "n_frames": 4, **fields}
    spec = WarehouseSpec(**values)
    plan = plan_warehouse(project, spec, loads=WarehouseLoads(roof_live=500.0, midspan_point=1e3))
    plan.apply(project)
    live = next(c for c in project.analyses if c.name == "LIVE")
    results = OpenSeesRunner(project).run(live)
    expected = 500.0 * spec.width * spec.length + 1e3 * spec.n_frames * spec.n_naves
    assert _vertical_reaction(results) == pytest.approx(expected, rel=1e-8)
    disp = np.array([np.asarray(d).reshape(-1, 6)[-1] for d in results.node_disp.values()])
    assert np.abs(disp[:, :3]).max() < 0.2
