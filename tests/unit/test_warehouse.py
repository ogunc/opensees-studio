"""The parametric warehouse: geometry, pinned secondaries, bracing lengths, loads, plan."""

from __future__ import annotations

import itertools
import math

import numpy as np
import pytest

from opensees_studio.core.code_combinations import CODES
from opensees_studio.core.default_materials import default_materials
from opensees_studio.core.defaults import ensure_dead_load_case
from opensees_studio.core.frames import RoofType, SupportCondition
from opensees_studio.core.geometry.local_axes import frame_local_axes
from opensees_studio.core.loads import PlainLoadPattern
from opensees_studio.core.project import Project
from opensees_studio.core.units import UnitSystem
from opensees_studio.core.warehouse import (
    CODE_PRESETS,
    GROUPS,
    SECTION_KEYS,
    WarehouseError,
    WarehouseLoads,
    WarehouseSpec,
    build_warehouse,
    force_from_kn,
    member_design_overrides,
    midspan_point_loads,
    plan_warehouse,
    pressure_from_kpa,
    roof_pressure_loads,
    roof_stations,
    warehouse_grid,
)

SECTIONS = {"column": 1, "rafter": 2, "purlin": 3, "girt": 4, "brace": 5}


def _build(**fields):  # type: ignore[no-untyped-def]
    values = {"span": 20.0, "eave_height": 6.0, "frame_spacing": 6.0, "n_frames": 4, **fields}
    return build_warehouse(WarehouseSpec(**values), SECTIONS, first_node_id=1, first_element_id=1)


def _project(units: UnitSystem = UnitSystem.SI_M_N) -> Project:
    project = Project(ndm=3, ndf=6)
    project.meta.units = units
    project.materials.extend(default_materials(project.next_material_id(), units))
    ensure_dead_load_case(project)
    return project


# ─────────────────────────────── the spec ───────────────────────────────
@pytest.mark.parametrize(
    "fields",
    [
        {"span": 0.0},
        {"eave_height": -1.0},
        {"frame_spacing": 0.0},
        {"n_frames": 1},
        {"n_naves": 0},
        {"slope": 1.0},
        {"purlin_spacing": 0.0},
        {"girt_spacing": -1.0},
        {"rafter_fly_brace_every": -1},
        {"braced_bays": (3,)},
    ],
)
def test_numbers_that_describe_no_warehouse_are_refused(fields: dict) -> None:  # type: ignore[type-arg]
    values = {"span": 20.0, "eave_height": 6.0, "frame_spacing": 6.0, "n_frames": 4, **fields}
    with pytest.raises(WarehouseError):
        WarehouseSpec(**values)


def test_the_braced_bays_default_to_the_first_and_the_last() -> None:
    spec = WarehouseSpec(span=20.0, eave_height=6.0, frame_spacing=6.0, n_frames=6)
    assert spec.bracing_bays() == (0, 4)
    two = WarehouseSpec(span=20.0, eave_height=6.0, frame_spacing=6.0, n_frames=2)
    assert two.bracing_bays() == (0,)


# ───────────────────────────── purlin lines ─────────────────────────────
def test_purlin_lines_divide_each_slope_evenly_within_the_spacing() -> None:
    spec = WarehouseSpec(span=20.0, eave_height=6.0, frame_spacing=6.0, purlin_spacing=1.5)
    stations = roof_stations(spec)
    slope_length = math.hypot(10.0, 1.0)
    per_slope = math.ceil(slope_length / 1.5)
    assert len(stations) == 2 * per_slope + 1
    assert stations[0].x == 0.0 and stations[-1].x == 20.0
    assert stations[per_slope].x == pytest.approx(10.0)  # a purlin on the ridge
    assert stations[per_slope].z == pytest.approx(7.0)
    gaps = [math.hypot(b.x - a.x, b.z - a.z) for a, b in itertools.pairwise(stations)]
    assert max(gaps) <= 1.5 and max(gaps) == pytest.approx(min(gaps))
    # The tributary widths add up to the roof, on the slope and in plan.
    assert sum(s.tributary_slope for s in stations) == pytest.approx(2 * slope_length)
    assert sum(s.tributary_plan for s in stations) == pytest.approx(20.0)


def test_a_purlin_web_stands_normal_to_the_roof_and_plumb_at_the_ridge() -> None:
    warehouse = _build()
    nodes = {n.id: n for n in warehouse.nodes}
    elements = {e.id: e for e in warehouse.elements}
    theta = math.atan(0.10)
    for element_id, k in warehouse.purlin_station.items():
        element = elements[element_id]
        axes = frame_local_axes(
            3,
            nodes[element.nodes[0]].coords,
            nodes[element.nodes[1]].coords,
            element.local_axis_angle,
        )
        assert axes is not None
        station = warehouse.stations[k]
        if station.x == pytest.approx(10.0):
            normal = np.array([0.0, 0.0, 1.0])
        elif station.x < 10.0:
            normal = np.array([-math.sin(theta), 0.0, math.cos(theta)])
        else:
            normal = np.array([math.sin(theta), 0.0, math.cos(theta)])
        assert axes[2] == pytest.approx(normal, abs=1e-12)


def test_interior_column_lines_and_the_ridge_carry_a_purlin() -> None:
    spec = WarehouseSpec(span=12.0, eave_height=5.0, frame_spacing=6.0, n_naves=3)
    xs = [s.x for s in roof_stations(spec)]
    for x in (0.0, 12.0, 18.0, 24.0, 36.0):  # column lines and the ridge at mid-width
        assert any(abs(x - other) < 1e-9 for other in xs)


# ───────────────────────────── the geometry ─────────────────────────────
def test_the_frames_repeat_along_y_with_supported_bases() -> None:
    warehouse = _build(support=SupportCondition.FIXED)
    ys = sorted({n.coords[1] for n in warehouse.nodes})
    assert ys == [0.0, 6.0, 12.0, 18.0]
    bases = [n for n in warehouse.nodes if n.id in warehouse.base_node_ids]
    assert len(bases) == 4 * 2
    assert all(n.coords[2] == 0.0 and n.restraint == (True,) * 6 for n in bases)
    free = [n for n in warehouse.nodes if n.id not in warehouse.base_node_ids]
    assert all(not any(n.restraint) for n in free)
    pinned = _build(support=SupportCondition.PINNED)
    base = next(n for n in pinned.nodes if n.id in pinned.base_node_ids)
    assert base.restraint == (True, True, True, False, False, False)


def test_every_member_is_in_one_group_with_its_section() -> None:
    warehouse = _build(girt_spacing=1.5)
    assert set(warehouse.members) == set(GROUPS)
    listed = [eid for ids in warehouse.members.values() for eid in ids]
    assert sorted(listed) == [e.id for e in warehouse.elements]
    by_id = {e.id: e for e in warehouse.elements}
    section_of = {
        "columns": 1, "rafters": 2, "purlins": 3, "girts": 4, "roof_bracing": 5, "wall_bracing": 5,
    }  # fmt: skip
    for group, ids in warehouse.members.items():
        assert ids, group
        assert {by_id[i].section_id for i in ids} == {section_of[group]}
    n_lines = len(warehouse.stations)
    assert len(warehouse.members["purlins"]) == n_lines * 3
    assert len(warehouse.members["rafters"]) == (n_lines - 1) * 4
    assert len(warehouse.members["girts"]) == 3 * 2 * 3  # 3 levels, 2 walls, 3 bays
    assert len(warehouse.members["columns"]) == 4 * 2 * 4  # split at the 3 girt levels
    assert len(warehouse.members["wall_bracing"]) == 2 * 2 * 2  # 2 bays, 2 walls, an X


def test_no_girts_and_no_bracing_when_not_asked_for() -> None:
    warehouse = _build(roof_bracing=False, wall_bracing=False)
    assert warehouse.members["girts"] == []
    assert warehouse.members["roof_bracing"] == []
    assert warehouse.members["wall_bracing"] == []
    assert len(warehouse.members["columns"]) == 4 * 2


def test_secondary_members_are_pinned_and_the_frames_are_continuous() -> None:
    warehouse = _build(girt_spacing=2.0)
    by_id = {e.id: e for e in warehouse.elements}
    for group in ("purlins", "girts", "roof_bracing", "wall_bracing"):
        for element_id in warehouse.members[group]:
            releases = by_id[element_id].releases
            assert {"M2", "M3"} <= set(releases.i.released), group
            assert {"M2", "M3"} <= set(releases.j.released), group
            # Torsion is held at one end at least: the member cannot spin.
            assert "T" not in releases.i.released
    for group in ("columns", "rafters"):
        assert not any(by_id[i].releases.any for i in warehouse.members[group])


def test_a_girt_lies_flat_and_bracing_spans_the_chosen_bays() -> None:
    warehouse = _build(girt_spacing=3.0, braced_bays=(1,))
    by_id = {e.id: e for e in warehouse.elements}
    nodes = {n.id: n for n in warehouse.nodes}
    assert {abs(by_id[i].local_axis_angle) for i in warehouse.members["girts"]} == {90.0}
    for group in ("roof_bracing", "wall_bracing"):
        for element_id in warehouse.members[group]:
            ys = sorted(nodes[n].coords[1] for n in by_id[element_id].nodes)
            assert ys == [6.0, 12.0]  # bay 2, between the second and third frames


def test_roof_bracing_panels_stay_near_square() -> None:
    wide = _build(span=30.0, frame_spacing=5.0)
    nodes = {n.id: n for n in wide.nodes}
    by_id = {e.id: e for e in wide.elements}
    for element_id in wide.members["roof_bracing"]:
        a, b = (np.array(nodes[n].coords) for n in by_id[element_id].nodes)
        run = math.hypot(b[0] - a[0], b[2] - a[2])
        assert 0.5 <= run / 5.0 <= 2.0


# ────────────────────── purlins do not brace the rafter ──────────────────────
def test_without_stabilising_angles_the_rafter_is_unbraced_from_eave_to_ridge() -> None:
    warehouse = _build()
    slope_length = math.hypot(10.0, 1.0)
    for element_id in warehouse.members["rafters"]:
        assert warehouse.unbraced[element_id] == pytest.approx(slope_length)


@pytest.mark.parametrize(("every", "panels"), [(1, 1), (2, 2), (3, 3)])
def test_a_stabilising_angle_makes_the_purlin_a_bracing_point(every: int, panels: int) -> None:
    warehouse = _build(rafter_fly_brace_every=every)
    stations = warehouse.stations
    spacing = math.hypot(stations[1].x - stations[0].x, stations[1].z - stations[0].z)
    lengths = [warehouse.unbraced[e] for e in warehouse.rafter_elements[0]]
    assert max(lengths) == pytest.approx(panels * spacing)
    # The first interval starts at the eave, a bracing point in every case.
    assert lengths[0] == pytest.approx(panels * spacing)


def test_the_design_overrides_carry_the_unbraced_lengths() -> None:
    warehouse = _build(girt_spacing=1.5, rafter_fly_brace_every=2, column_fly_brace_every=0)
    overrides = {o.element_id: o for o in member_design_overrides(warehouse)}
    rafters = set(warehouse.members["rafters"])
    assert rafters <= set(overrides)
    for element_id in rafters:
        override = overrides[element_id]
        assert override.length_ltb == override.length_minor == warehouse.unbraced[element_id]
        assert override.length_major is None  # in the frame's plane: as modelled
    # A girt without an angle does not brace the column either: the full height.
    columns = set(overrides) - rafters
    assert len(columns) == len(warehouse.members["columns"])
    assert {overrides[e].length_ltb for e in columns} == {6.0}


def test_interior_columns_get_no_override() -> None:
    warehouse = _build(n_naves=2, girt_spacing=2.0)
    nodes = {n.id: n for n in warehouse.nodes}
    by_id = {e.id: e for e in warehouse.elements}
    for element_id in warehouse.members["columns"]:
        x = nodes[by_id[element_id].nodes[0]].coords[0]
        assert (element_id in warehouse.unbraced) == (x != pytest.approx(20.0))


# ─────────────────────────────── loads ───────────────────────────────
def test_a_roof_load_puts_its_resultant_on_the_purlins() -> None:
    warehouse = _build()
    nodes = {n.id: n for n in warehouse.nodes}
    by_id = {e.id: e for e in warehouse.elements}

    def resultant(loads) -> float:  # type: ignore[no-untyped-def]
        total = 0.0
        for load in loads:
            element = by_id[load.element_id]
            axes = frame_local_axes(
                3,
                nodes[element.nodes[0]].coords,
                nodes[element.nodes[1]].coords,
                element.local_axis_angle,
            )
            assert axes is not None
            force = (load.wy * axes[1] + load.wz * axes[2]) * 6.0
            assert force[:2] == pytest.approx([0.0, 0.0], abs=1e-9)  # straight down
            total += float(force[2])
        return total

    plan_area = 20.0 * 18.0
    roof_area = 2 * math.hypot(10.0, 1.0) * 18.0
    assert resultant(roof_pressure_loads(warehouse, 500.0, projected=True)) == pytest.approx(
        -500.0 * plan_area
    )
    assert resultant(roof_pressure_loads(warehouse, 100.0, projected=False)) == pytest.approx(
        -100.0 * roof_area
    )
    assert roof_pressure_loads(warehouse, 0.0, projected=True) == []


def test_the_mid_span_load_goes_on_the_ridge_node_or_inside_the_rafter() -> None:
    gable = _build()
    nodal, inside = midspan_point_loads(gable, 2000.0)
    assert inside == [] and len(nodal) == 4
    nodes = {n.id: n for n in gable.nodes}
    for load in nodal:
        assert nodes[load.node_id].coords[0] == pytest.approx(10.0)
        assert load.forces == (0.0, 0.0, -2000.0, 0.0, 0.0, 0.0)

    # One slope, 7 purlin spaces over 10 m: mid-span falls inside an element.
    mono = _build(span=10.0, roof=RoofType.MONO_PITCH, purlin_spacing=1.5)
    assert all(abs(s.x - 5.0) > 1e-6 for s in mono.stations)
    nodal, inside = midspan_point_loads(mono, 2000.0)
    assert nodal == [] and len(inside) == 4
    by_id = {e.id: e for e in mono.elements}
    nodes = {n.id: n for n in mono.nodes}
    for load in inside:
        element = by_id[load.element_id]
        x_i, x_j = (nodes[n].coords[0] for n in element.nodes)
        assert x_i + load.x * (x_j - x_i) == pytest.approx(5.0)
        axes = frame_local_axes(3, nodes[element.nodes[0]].coords, nodes[element.nodes[1]].coords)
        assert axes is not None
        force = load.px * axes[0] + load.py * axes[1] + load.pz * axes[2]
        assert force == pytest.approx([0.0, 0.0, -2000.0], abs=1e-9)


def test_the_grid_follows_the_columns_frames_and_levels() -> None:
    spec = WarehouseSpec(span=20.0, eave_height=6.0, frame_spacing=6.0, n_frames=3)
    grid = warehouse_grid(spec).grid
    assert [line.ordinate for line in grid.x_grid_lines] == [0.0, 10.0, 20.0]
    assert [line.ordinate for line in grid.y_grid_lines] == [0.0, 6.0, 12.0]
    assert [line.ordinate for line in grid.z_grid_lines] == pytest.approx([0.0, 6.0, 7.0])


# ─────────────────────────────── the plan ───────────────────────────────
def _loads(project: Project, code: str = "rnc07") -> WarehouseLoads:
    units = project.meta.units
    preset = CODE_PRESETS[code]
    return WarehouseLoads(
        code=code,
        roof_dead=pressure_from_kpa(0.10, units),
        roof_live=pressure_from_kpa(preset.roof_live_kpa, units),
        midspan_point=force_from_kn(preset.midspan_point_kn, units),
    )


def test_planning_does_not_touch_the_project_and_applying_builds_it() -> None:
    project = _project()
    before = project.model_dump()
    spec = WarehouseSpec(span=20.0, eave_height=6.0, frame_spacing=6.0, girt_spacing=1.5)
    plan = plan_warehouse(project, spec, loads=_loads(project))
    assert project.model_dump() == before

    plan.apply(project)
    assert [s.name for s in plan.sections] == ["W14X48", "W16X40", "C150X50X15X2.38", "L3X3X1_4"]
    assert [g.name for g in project.groups] == list(GROUPS.values())
    assert project.coord_systems[-1].name == "Warehouse"
    assert [c.name for c in project.analyses] == ["DEAD", "LIVE"]
    dead, live = (p for p in project.load_patterns if isinstance(p, PlainLoadPattern))
    assert dead.self_weight == 1.0 and len(dead.element_loads) == len(plan.warehouse.purlin_station)
    assert len(live.element_loads) == len(plan.warehouse.purlin_station)
    assert len(live.nodal_loads) == spec.n_frames  # 200 kg on each ridge
    assert live.nodal_loads[0].forces[2] == pytest.approx(-200 * 9.80665)
    assert [c.name for c in project.combinations] == [
        "1.4CM",
        "1.2CM+1.6CV",
        "RNC-07 ultimate envelope",
    ]
    assert project.design is not None and project.design.method == "LRFD"
    assert len(project.design.members) == len(plan.warehouse.unbraced)
    # The saved file reloads: every reference the plan wrote resolves.
    Project.model_validate(project.model_dump())


@pytest.mark.parametrize("code", sorted(CODE_PRESETS))
def test_each_code_combines_its_own_roof_live_role(code: str) -> None:
    project = _project()
    spec = WarehouseSpec(span=15.0, eave_height=5.0, frame_spacing=5.0, n_frames=3)
    plan = plan_warehouse(project, spec, loads=_loads(project, code))
    plan.apply(project)
    preset = CODE_PRESETS[code]
    assert code in CODES and preset.roof_live_role in CODES[code].roles
    live = next(c for c in project.analyses if c.name == preset.roof_live_case)
    used = {t.ref_id for c in project.combinations for t in c.terms if t.source == "case"}
    assert live.id in used  # the roof live case is in a combination of the code
    assert project.design is not None and project.design.method == preset.design_method


def test_chosen_sections_are_used_and_only_the_missing_ones_created() -> None:
    project = _project()
    first = plan_warehouse(
        project, WarehouseSpec(span=10.0, eave_height=4.0, frame_spacing=5.0, n_frames=2)
    )
    first.apply(project)
    ids = {s.name: s.id for s in project.sections}
    again = plan_warehouse(
        project,
        WarehouseSpec(span=10.0, eave_height=4.0, frame_spacing=5.0, n_frames=2, origin=(30, 0, 0)),
        sections={"column": ids["W14X48"], "rafter": ids["W16X40"], "brace": ids["L3X3X1_4"]},
        loads=_loads(project),
    )
    assert [s.name for s in again.sections] == ["C150X50X15X2.38"]  # purlins and girts share it
    assert {e.section_id for e in again.warehouse.elements} >= {ids["W14X48"], ids["W16X40"]}
    again.apply(project)
    # A second warehouse gets its own groups and grid, and fresh ids throughout.
    assert len({g.name for g in project.groups}) == len(project.groups)
    assert [c.name for c in project.coord_systems][-2:] == ["Warehouse", "Warehouse 2"]
    assert len({n.id for n in project.nodes}) == len(project.nodes)
    assert len({e.id for e in project.elements}) == len(project.elements)
    with pytest.raises(WarehouseError, match="not in the project"):
        plan_warehouse(project, again.warehouse.spec, sections={"column": 999})


def test_existing_combinations_are_kept_not_duplicated() -> None:
    project = _project()
    spec = WarehouseSpec(span=10.0, eave_height=4.0, frame_spacing=5.0, n_frames=2)
    plan_warehouse(project, spec, loads=_loads(project)).apply(project)
    names = [c.name for c in project.combinations]
    second = plan_warehouse(
        project,
        WarehouseSpec(span=10.0, eave_height=4.0, frame_spacing=5.0, n_frames=2, origin=(0, 20, 0)),
        loads=_loads(project),
    )
    assert second.combinations == [] and second.cases == []  # the LIVE case is reused
    assert second.notes
    second.apply(project)
    assert [c.name for c in project.combinations] == names
    # The second warehouse's unbraced lengths join the first one's.
    assert project.design is not None
    assert len(project.design.members) == len({m.element_id for m in project.design.members})


def test_a_warehouse_needs_a_3d_frame_model() -> None:
    with pytest.raises(WarehouseError, match="3D frame model"):
        plan_warehouse(
            Project(ndm=2, ndf=3),
            WarehouseSpec(span=10.0, eave_height=4.0, frame_spacing=5.0),
        )


def test_the_default_sections_follow_the_project_units() -> None:
    si = _project()
    mm = _project(UnitSystem.SI_MM_N)
    spec = WarehouseSpec(span=10.0, eave_height=4.0, frame_spacing=5.0, n_frames=2)
    a = {s.name: s for s in plan_warehouse(si, spec).sections}
    b = {s.name: s for s in plan_warehouse(mm, spec).sections}
    for name, section in a.items():
        assert pytest.approx(section.A * 1e6) == b[name].A
    assert a["C150X50X15X2.38"].shape.d == pytest.approx(0.150)
    assert set(SECTION_KEYS) == {"column", "rafter", "purlin", "girt", "brace"}
