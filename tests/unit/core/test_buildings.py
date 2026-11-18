"""Storeys, rigid diaphragms, rigid links, the mass source and the storey table (pure core)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, call

import numpy as np
import pytest
from pydantic import ValidationError

from opensees_studio.core import (
    CoordinateGridSystem,
    ElasticBeamColumn,
    ElasticSection,
    EndRelease,
    EqualDOFConstraint,
    FrameReleases,
    GridSystem,
    LinearTimeSeries,
    MassSource,
    MassSourcePattern,
    NodalLoad,
    Node,
    PlainLoadPattern,
    PointElementLoad,
    Project,
    RigidDiaphragm,
    RigidLink,
    StaticCase,
    Storey,
    UniformElementLoad,
    make_grid_lines,
)
from opensees_studio.core.diaphragms import (
    auto_fixed_slots,
    centre_of_mass,
    constrained_node_ids,
    diaphragm_problems,
)
from opensees_studio.core.mass_source import (
    effective_nodal_masses,
    pattern_weight_per_node,
    self_weight_per_node,
    source_weight_per_node,
)
from opensees_studio.core.modal import free_dof_count
from opensees_studio.core.storey_results import (
    StoreyCut,
    base_shear_from_reactions,
    combine_storey_response,
    cut_force,
    inertia_storey_shears,
    level_reference_nodes,
    storey_cuts,
    storey_profile,
)
from opensees_studio.core.storeys import base_elevation, storey_levels, storeys_from_grid
from opensees_studio.core.units import gravity

FIXED = (True,) * 6


def _one_storey(*, with_diaphragm: bool = True, cm: tuple[float, float] = (3.0, 2.0)) -> Project:
    """A 6 x 4 m single bay, one storey of 3 m, a floating retained node 9 at ``cm``."""
    corners = [(0.0, 0.0), (6.0, 0.0), (6.0, 4.0), (0.0, 4.0)]
    nodes = [
        Node(id=i + 1, coords=(x, y, 0.0), restraint=FIXED) for i, (x, y) in enumerate(corners)
    ]
    nodes += [Node(id=i + 5, coords=(x, y, 3.0)) for i, (x, y) in enumerate(corners)]
    nodes.append(Node(id=9, coords=(cm[0], cm[1], 3.0)))
    elements = [ElasticBeamColumn(id=i + 1, nodes=(i + 1, i + 5), section_id=1) for i in range(4)]
    elements += [
        ElasticBeamColumn(id=5 + k, nodes=(a, b), section_id=1)
        for k, (a, b) in enumerate([(5, 6), (6, 7), (7, 8), (8, 5)])
    ]
    project = Project(
        ndm=3,
        ndf=6,
        storeys=[Storey(id=1, name="Story1", elevation=3.0)],
        nodes=nodes,
        sections=[
            ElasticSection(
                id=1, E=30e9, G=12.5e9, A=0.25, Iz=5e-3, Iy=5e-3, J=8e-3, unit_weight=25_000.0
            )
        ],
        elements=elements,
        time_series=[LinearTimeSeries(id=1)],
    )
    if with_diaphragm:
        project.diaphragms.append(RigidDiaphragm(id=1, retained_node=9, storey_id=1))
    return project


# ─────────────────────────── models and persistence ───────────────────────────
def test_a_project_without_building_data_dumps_without_the_new_keys() -> None:
    data = json.loads(Project().model_dump_json())
    for key in ("storeys", "diaphragms", "rigid_links", "mass_source"):
        assert key not in data


def test_building_data_round_trips() -> None:
    project = _one_storey()
    project.rigid_links.append(RigidLink(kind="bar", retained_node=5, constrained_node=6))
    project.mass_source = MassSource(patterns=[])
    again = Project.model_validate_json(project.model_dump_json())
    assert again.model_dump() == project.model_dump()


def test_rigid_diaphragm_needs_exactly_one_node_source() -> None:
    with pytest.raises(ValidationError, match="constrained nodes or a storey"):
        RigidDiaphragm(id=1, retained_node=9)
    with pytest.raises(ValidationError, match="not both"):
        RigidDiaphragm(id=1, retained_node=9, storey_id=1, constrained_nodes=(5,))
    with pytest.raises(ValidationError, match="perp_dirn must be 3"):
        RigidDiaphragm(id=1, retained_node=9, storey_id=1, perp_dirn=1)
    with pytest.raises(ValidationError, match="cannot also be"):
        RigidDiaphragm(id=1, retained_node=9, constrained_nodes=(9, 5))


def test_rigid_link_needs_two_nodes() -> None:
    with pytest.raises(ValidationError):
        RigidLink(retained_node=3, constrained_node=3)


def test_duplicate_storey_ids_are_refused() -> None:
    with pytest.raises(ValidationError, match="Duplicate storey ids"):
        Project(storeys=[Storey(id=1, elevation=3.0), Storey(id=1, elevation=6.0)])


# ─────────────────────────── storeys ───────────────────────────
def test_storeys_from_grid_skip_the_base_line_and_follow_the_origin() -> None:
    system = CoordinateGridSystem(
        name="Global", grid=GridSystem(z_grid_lines=make_grid_lines("Z", [0.0, 3.5, 7.0]))
    )
    storeys = storeys_from_grid(system, first_id=4)
    assert [(s.id, s.name, s.elevation) for s in storeys] == [
        (4, "Story1", 3.5),
        (5, "Story2", 7.0),
    ]
    assert len(storeys_from_grid(system, include_lowest=True)) == 3


def test_storey_levels_measure_heights_from_the_base() -> None:
    project = _one_storey()
    project.storeys.append(Storey(id=2, name="Roof", elevation=6.0))
    project.storeys.append(Storey(id=3, name="Ground", elevation=0.0))
    levels = storey_levels(project)
    assert base_elevation(project) == 0.0
    assert [(lv.storey.name, lv.below, lv.height) for lv in levels] == [
        ("Story1", 0.0, 3.0),
        ("Roof", 3.0, 3.0),
    ]
    assert levels[0].nodes == (5, 6, 7, 8, 9)
    assert levels[0].below_nodes == (1, 2, 3, 4)


# ─────────────────────────── diaphragms ───────────────────────────
def test_storey_diaphragm_takes_the_floor_joints_but_not_its_retained_node() -> None:
    project = _one_storey()
    assert constrained_node_ids(project, project.diaphragms[0]) == (5, 6, 7, 8)


def test_storey_diaphragm_leaves_out_joints_restrained_in_its_plane() -> None:
    project = _one_storey()
    project.nodes[5] = project.nodes[5].model_copy(
        update={"restraint": (True, False, False, False, False, False)}
    )
    assert constrained_node_ids(project, project.diaphragms[0]) == (5, 7, 8)


def test_floating_retained_node_gets_its_out_of_plane_dofs_fixed() -> None:
    project = _one_storey()
    assert auto_fixed_slots(project) == {9: {2, 3, 4}}
    project.diaphragms[0] = RigidDiaphragm(id=1, retained_node=5, constrained_nodes=(6, 7, 8))
    assert auto_fixed_slots(project) == {}  # node 5 is a column top


def test_free_dof_count_sees_the_diaphragm() -> None:
    plain = _one_storey(with_diaphragm=False)
    assert free_dof_count(plain) == 5 * 6
    # Node 9 loses Uz, Rx, Ry; each of the four joints loses Ux, Uy, Rz.
    assert free_dof_count(_one_storey()) == 5 * 6 - 3 - 4 * 3


def test_centre_of_mass_weights_by_mass_and_falls_back_to_the_centroid() -> None:
    coords = {1: (0.0, 0.0, 3.0), 2: (6.0, 0.0, 3.0)}
    assert centre_of_mass(coords, {1: 1.0, 2: 3.0}, [1, 2]) == (4.5, 0.0, 3.0)
    assert centre_of_mass(coords, {}, [1, 2]) == (3.0, 0.0, 3.0)


def test_diaphragm_problems() -> None:
    project = _one_storey()
    assert diaphragm_problems(project) == []
    project.validate_references()

    out_of_plane = _one_storey()
    out_of_plane.diaphragms[0] = RigidDiaphragm(id=1, retained_node=9, constrained_nodes=(5, 1))
    problems = " ".join(diaphragm_problems(out_of_plane))
    assert "node 1 is not in the plane" in problems
    assert "restrained in the plane" in problems

    twice = _one_storey()
    twice.diaphragms.append(RigidDiaphragm(id=2, retained_node=5, constrained_nodes=(6,)))
    assert any("diaphragms 1 and 2" in p for p in diaphragm_problems(twice))

    tied = _one_storey()
    tied.mp_constraints.append(EqualDOFConstraint(retained_node=9, constrained_node=6, dofs=(1,)))
    assert any("already constrained" in p for p in diaphragm_problems(tied))

    flat = Project(ndm=2, ndf=3, nodes=[Node(id=1, coords=(0, 0, 0)), Node(id=2, coords=(1, 0, 0))])
    flat.diaphragms.append(RigidDiaphragm(id=1, retained_node=1, constrained_nodes=(2,)))
    assert "3D model with 6 DOF" in diaphragm_problems(flat)[0]
    with pytest.raises(ValueError, match="6 DOF"):
        flat.validate_references()


# ─────────────────────────── mass source ───────────────────────────
def test_self_weight_goes_half_to_each_end() -> None:
    project = _one_storey()
    weights = self_weight_per_node(project)
    column = 25_000.0 * 0.25 * 3.0
    beam_x, beam_y = 25_000.0 * 0.25 * 6.0, 25_000.0 * 0.25 * 4.0
    assert weights[1] == pytest.approx(column / 2)
    assert weights[5] == pytest.approx((column + beam_x + beam_y) / 2)


def test_pattern_weight_lumps_uniform_point_and_nodal_loads() -> None:
    project = _one_storey()
    pattern = PlainLoadPattern(
        id=1,
        time_series_id=1,
        # Beam 5 runs 5 -> 6 along X: local z is up, so gravity is wz < 0.
        element_loads=[UniformElementLoad(element_id=5, wz=-1000.0)],
        point_loads=[PointElementLoad(element_id=5, pz=-600.0, x=0.25)],
        nodal_loads=[NodalLoad(node_id=7, forces=(50.0, 0.0, -200.0, 0.0, 0.0, 0.0))],
    )
    weights = pattern_weight_per_node(project, pattern)
    assert weights[5] == pytest.approx(3000.0 + 450.0)
    assert weights[6] == pytest.approx(3000.0 + 150.0)
    assert weights[7] == pytest.approx(200.0)


def test_mass_source_scales_patterns_and_drops_upward_weight() -> None:
    project = _one_storey()
    project.load_patterns.append(
        PlainLoadPattern(
            id=1,
            time_series_id=1,
            nodal_loads=[
                NodalLoad(node_id=7, forces=(0.0, 0.0, -1000.0, 0.0, 0.0, 0.0)),
                NodalLoad(node_id=8, forces=(0.0, 0.0, 500.0, 0.0, 0.0, 0.0)),
            ],
        )
    )
    source = MassSource(
        element_self_mass=False, patterns=[MassSourcePattern(pattern_id=1, factor=0.3)]
    )
    assert source_weight_per_node(project, source) == {7: pytest.approx(300.0)}


def test_effective_masses_are_the_typed_masses_without_a_source() -> None:
    project = _one_storey()
    project.nodes[4] = project.nodes[4].model_copy(update={"mass": (1.0, 2.0, 3.0, 0.0, 0.0, 0.0)})
    masses = effective_nodal_masses(project)
    assert masses[5].tolist() == [1.0, 2.0, 3.0, 0.0, 0.0, 0.0]
    assert not masses[9].any()


def _loaded_floor(cm: tuple[float, float], *, lump: bool, vertical: bool = False) -> Project:
    project = _one_storey(cm=cm)
    project.load_patterns.append(
        PlainLoadPattern(
            id=1,
            time_series_id=1,
            nodal_loads=[
                NodalLoad(node_id=n, forces=(0.0, 0.0, -9806.65, 0.0, 0.0, 0.0))
                for n in (5, 6, 7, 8)
            ],
        )
    )
    project.mass_source = MassSource(
        element_self_mass=False,
        patterns=[MassSourcePattern(pattern_id=1)],
        lump_at_diaphragms=lump,
        include_vertical=vertical,
    )
    return project


def test_mass_from_a_pattern_goes_on_the_lateral_translations() -> None:
    masses = effective_nodal_masses(_loaded_floor((3.0, 2.0), lump=False))
    assert gravity(Project().meta.units) == pytest.approx(9.80665)
    assert masses[5].tolist() == pytest.approx([1000.0, 1000.0, 0.0, 0.0, 0.0, 0.0])
    vertical = effective_nodal_masses(_loaded_floor((3.0, 2.0), lump=False, vertical=True))
    assert vertical[5][2] == pytest.approx(1000.0)


def test_lumping_at_the_centre_of_mass_adds_the_polar_inertia() -> None:
    masses = effective_nodal_masses(_loaded_floor((3.0, 2.0), lump=True))
    assert masses[9][0] == pytest.approx(4000.0)
    assert masses[9][1] == pytest.approx(4000.0)
    # Four 1000 kg joints at (+-3, +-2) from the centre: 4 * 1000 * (9 + 4).
    assert masses[9][5] == pytest.approx(52_000.0)
    for nid in (5, 6, 7, 8):
        assert not masses[nid].any()


def test_lumping_off_the_centre_of_mass_keeps_the_mass_on_the_joints() -> None:
    masses = effective_nodal_masses(_loaded_floor((1.0, 2.0), lump=True))
    assert not masses[9].any()
    assert masses[5][0] == pytest.approx(1000.0)


# ─────────────────────────── storey table ───────────────────────────
def test_storey_cut_crosses_the_columns_only() -> None:
    (cut,) = storey_cuts(_one_storey())
    assert cut.storey_id == 1
    assert cut.members == ((1, (0,)), (2, (0,)), (3, (0,)), (4, (0,)))


def test_cut_force_is_minus_the_forces_at_the_lower_nodes() -> None:
    cut = StoreyCut(storey_id=1, elevation=0.0, members=((1, (0,)),))
    # A cantilever column pushed by +P at the top: eleForce at the base is -P.
    forces = {1: [-10.0, 0.0, 0.0, 0.0, -30.0, 0.0, 10.0, 0.0, 0.0, 0.0, 0.0, 0.0]}
    assert cut_force(cut, {1: (1, 2)}, forces, 3).tolist() == [10.0, 0.0, 0.0]


def test_storey_profile_uses_the_retained_node_and_the_storey_height() -> None:
    project = _one_storey()
    assert level_reference_nodes(project, 3.0) == (9,)
    disp = {nid: np.zeros(6) for nid in range(1, 10)}
    disp[9] = np.array([0.03, -0.006, 0.0, 0.0, 0.0, 0.0])
    profile = storey_profile(project, disp)
    assert profile.disp.tolist() == [[0.03, -0.006]]
    np.testing.assert_allclose(profile.drift, [[0.01, -0.002]])

    without = _one_storey(with_diaphragm=False)
    assert level_reference_nodes(without, 3.0) == (5, 6, 7, 8, 9)


def test_base_shear_is_minus_the_lateral_reactions() -> None:
    project = _one_storey()
    reactions = {1: np.array([-1.0, 2.0, 5.0, 0, 0, 0]), 2: np.array([-3.0, 0.0, 5.0, 0, 0, 0])}
    assert base_shear_from_reactions(project, reactions).tolist() == [4.0, -2.0]


def test_inertia_shear_and_single_mode_combination() -> None:
    project = _one_storey()
    masses = {nid: np.zeros(6) for nid in range(1, 10)}
    masses[9] = np.array([4000.0, 4000.0, 0.0, 0.0, 0.0, 1e4])
    field = {nid: np.zeros(6) for nid in range(1, 10)}
    field[9] = np.array([-0.02, 0.0, 0.0, 0.0, 0.0, 0.0])
    levels = storey_levels(project)
    shears, base = inertia_storey_shears(project, levels, field, 10.0, masses)
    np.testing.assert_allclose(shears, [[-8000.0, 0.0]])
    assert base.tolist() == pytest.approx([-8000.0, 0.0])
    combined = combine_storey_response(project, [field], [10.0], masses, method="CQC", damping=0.05)
    np.testing.assert_allclose(combined.shear, [[8000.0, 0.0]])
    np.testing.assert_allclose(combined.drift, [[0.02 / 3.0, 0.0]])
    two = combine_storey_response(project, [field, field], [10.0, 30.0], masses)
    assert two.disp[0, 0] == pytest.approx(0.02 * np.sqrt(2.0))


# ─────────────────────────── translation (mock solver) ───────────────────────────
def test_runner_emits_the_diaphragm_its_fix_and_transformation() -> None:
    from opensees_studio.services.opensees_runner import OpenSeesRunner

    project = _loaded_floor((3.0, 2.0), lump=True)
    project.rigid_links.append(RigidLink(kind="beam", retained_node=1, constrained_node=2))
    project.analyses.append(StaticCase(id=1, pattern_ids=[1]))
    ops = MagicMock()
    ops.analyze.return_value = 0
    ops.eleForce.return_value = [0.0] * 12
    ops.nodeDisp.return_value = 0.0
    ops.nodeReaction.return_value = 0.0
    ops.eleResponse.return_value = []
    OpenSeesRunner(project, ops_module=ops).run(project.analyses[0])
    assert call.fix(9, 0, 0, 1, 1, 1, 0) in ops.mock_calls
    assert call.rigidDiaphragm(3, 9, 5, 6, 7, 8) in ops.mock_calls
    assert call.rigidLink("beam", 1, 2) in ops.mock_calls
    assert call.mass(9, 4000.0, 4000.0, 0.0, 0.0, 0.0, pytest.approx(52_000.0)) in ops.mock_calls
    assert call.constraints("Transformation") in ops.mock_calls
    names = [c[0] for c in ops.mock_calls]
    assert names.index("rigidDiaphragm") < names.index("mass")


def test_exported_script_carries_the_diaphragm() -> None:
    from opensees_studio.services.opensees_script import export_script

    project = _one_storey()
    script = export_script(project)
    assert "ops.rigidDiaphragm(3, 9, 5, 6, 7, 8)" in script
    assert "ops.fix(9, 0, 0, 1, 1, 1, 0)" in script


# ─────────────────────────── result tables ───────────────────────────
def test_storey_table_needs_storeys() -> None:
    from opensees_studio.services.result_tables import storey_table
    from opensees_studio.services.results import StaticResults

    project = _one_storey()
    project.storeys.clear()
    assert storey_table(StaticResults(case_id=1, case_name="S", n_steps=1), project) is None


def test_storey_table_for_modes_and_spectrum() -> None:
    from opensees_studio.services.result_tables import storey_table
    from opensees_studio.services.results import ModalResults, ResponseSpectrumResults
    from opensees_studio.services.spectrum import ModeContribution

    project = _loaded_floor((3.0, 2.0), lump=True)
    shape = {nid: np.zeros(6) for nid in range(1, 10)}
    shape[9] = np.array([0.006, 0.0, 0.0, 0.0, 0.0, 0.0])
    modal = ModalResults(
        case_id=1, case_name="M", eigenvalues=np.array([100.0]), mode_shapes={1: shape}
    )
    table = storey_table(modal, project)
    assert table is not None
    assert [row[:3] for row in table.rows] == [
        [1, pytest.approx(2 * np.pi / 10.0), "Story1"],
        [1, pytest.approx(2 * np.pi / 10.0), "Base"],
    ]
    assert table.rows[0][7] == pytest.approx(0.002)  # drift X of the mode shape

    peak = {nid: np.zeros(3) for nid in range(1, 10)}
    peak[9] = np.array([-0.01, 0.0, 0.0])
    mode = ModeContribution(
        mode_number=1,
        period=0.6,
        frequency=1 / 0.6,
        angular_frequency=10.0,
        participation_factor=1.0,
        effective_mass=1.0,
        mass_ratio=1.0,
        sa_at_period=1.0,
        modal_peak_disp=peak,
    )
    spectrum = ResponseSpectrumResults(
        case_id=2, case_name="RS", direction=1, combination="SRSS", modes=[mode]
    )
    table = storey_table(spectrum, project)
    assert table is not None
    story, base = table.rows
    # 4000 kg lumped at node 9, w^2 = 100: |100 * 4000 * -0.01| = 4000 N.
    assert story[3] == pytest.approx(0.01)
    assert story[7] == pytest.approx(4000.0)
    assert base[0] == "Base" and base[7] == pytest.approx(4000.0)


def test_mass_source_puts_no_mass_on_a_restrained_dof() -> None:
    project = _loaded_floor((3.0, 2.0), lump=False)
    project.nodes[4] = project.nodes[4].model_copy(
        update={"restraint": (True, False, False, False, False, False)}
    )
    masses = effective_nodal_masses(project)
    assert masses[5][:2].tolist() == pytest.approx([0.0, 1000.0])


def test_a_diaphragm_joint_cannot_retain_another_constraint() -> None:
    """OpenSees' Transformation handler solves such a chain silently wrong."""
    retaining = _one_storey()
    retaining.nodes.append(Node(id=10, coords=(0.0, 0.0, 3.0)))
    retaining.mp_constraints.append(
        EqualDOFConstraint(retained_node=5, constrained_node=10, dofs=(3,))
    )
    assert any(
        "node 5 is the retained node of an equalDOF" in p for p in diaphragm_problems(retaining)
    )


# ─────────────────────────── releases at diaphragm joints ───────────────────────────
def _released(**ends: EndRelease) -> Project:
    """``_one_storey`` with element 5 (the X beam from joint 5 to joint 6) released."""
    project = _one_storey()
    project.elements[4] = project.elements[4].model_copy(update={"releases": FrameReleases(**ends)})
    return project


def test_a_released_end_at_a_diaphragm_joint_is_no_problem() -> None:
    assert diaphragm_problems(_released(i=EndRelease(released=("M3",)))) == []


def test_an_elastic_member_is_released_inside_the_element_at_a_diaphragm_joint() -> None:
    from opensees_studio.services.frame_members import plan_frame_members

    project = _released(i=EndRelease(released=("M2", "M3")))
    project.elements[5] = project.elements[5].model_copy(
        update={"releases": FrameReleases(j=EndRelease(released=("T",)))}
    )
    plan = plan_frame_members(project)
    assert not plan.nodes and not plan.equal_dofs and not plan.springs
    assert plan.members[5].release_args == ("-releasez", 1, "-releasey", 1)
    assert plan.members[5].nodes == (5, 6)
    # The X beam's local (y, z) are global (Y, Z): M2 and M3 leave RY and RZ at joint 5.
    assert plan.released_dofs[(5, "i")] == {5, 6}
    # A torsion release is a section with no G J (and no flag).
    assert plan.members[6].release_args == ()
    (derived,) = plan.sections
    assert derived.args == pytest.approx((30e9, 0.25, 5e-3, 5e-3, 12.5e9, 0.0))
    assert plan.members[6].section_id == derived.tag


def test_the_element_releases_reach_the_element_command() -> None:
    from opensees_studio.services.opensees_script import export_script

    script = export_script(_released(j=EndRelease(released=("M3",))))
    assert "ops.element('elasticBeamColumn', 5, 5, 6, 1, " in script
    assert "'-mass', 0.0, '-releasez', 2)" in script
    assert "equalDOF" not in script


@pytest.mark.parametrize(
    "change",
    ["spring", "point load", "consistent mass"],
)
def test_a_release_the_element_cannot_condense_is_held_by_penalty_springs(change: str) -> None:
    from opensees_studio.services.frame_members import (
        CONSTRAINED_PENALTY_FACTOR,
        plan_frame_members,
    )

    springs = {"M3": 1.0e7} if change == "spring" else {}
    project = _released(i=EndRelease(released=("M3",), springs=springs))
    if change == "point load":
        project.load_patterns.append(
            PlainLoadPattern(
                id=1, time_series_id=1, point_loads=[PointElementLoad(element_id=5, pz=-1.0)]
            )
        )
    if change == "consistent mass":
        project.elements[4] = project.elements[4].model_copy(update={"consistent_mass": True})
    plan = plan_frame_members(project)
    (hidden,) = plan.nodes
    assert hidden.coords == (0.0, 0.0, 3.0) and hidden.joint == 5
    assert plan.members[5].nodes == (hidden.tag, 6)
    assert plan.members[5].release_args == ()
    # No constraint at all (it would chain through the diaphragm), and the
    # springs carry the force into the joint, so nothing is folded back.
    assert not plan.equal_dofs and not plan.rigid_links and not plan.attached
    (link,) = plan.springs
    assert (link.node_a, link.node_b) == (5, hidden.tag)
    L, EI = 6.0, 30e9 * 5e-3
    k_t = CONSTRAINED_PENALTY_FACTOR * max(30e9 * 0.25 / L, 12 * EI / L**3)
    k_r = CONSTRAINED_PENALTY_FACTOR * max(4 * EI, 12.5e9 * 8e-3) / L
    if springs:
        assert link.dirs == (1, 2, 3, 4, 5, 6)
        assert link.stiffnesses == pytest.approx((k_t, k_t, k_t, k_r, k_r, 1.0e7))
    else:
        assert link.dirs == (1, 2, 3, 4, 5)
        assert link.stiffnesses == pytest.approx((k_t, k_t, k_t, k_r, k_r))
    assert link.orient == pytest.approx((1.0, 0.0, 0.0, 0.0, 1.0, 0.0))
    assert plan.released_dofs[(5, "i")] == ({6} if not springs else set())


def test_a_torsion_free_member_keeps_torsion_tied_at_its_other_released_end() -> None:
    """Column 1 releases T at joint 5 (a zero G J) and M2 at its base: the base's
    hidden node keeps the rotation about the column axis tied, or it would spin."""
    from opensees_studio.services.frame_members import plan_frame_members

    project = _one_storey()
    project.elements[0] = project.elements[0].model_copy(
        update={
            "releases": FrameReleases(i=EndRelease(released=("M2",)), j=EndRelease(released=("T",)))
        }
    )
    plan = plan_frame_members(project)
    (base, hidden, dofs) = plan.equal_dofs[0]
    assert base == 1 and 6 in dofs
    assert plan.members[1].nodes == (hidden, 5)
    assert plan.sections[0].args[-1] == 0.0


def test_releases_at_a_diaphragm_joint_that_cannot_be_modelled_are_refused() -> None:
    from opensees_studio.core import FiberSection, ForceBeamColumn, RectangularPatch
    from opensees_studio.core.geometry.frame_options import FrameEndOffsets
    from opensees_studio.services.frame_members import plan_frame_members

    offset = _released(i=EndRelease(released=("M3",), springs={"M3": 1.0e7}))
    offset.elements[4] = offset.elements[4].model_copy(
        update={"end_offsets": FrameEndOffsets(length_i=0.25)}
    )
    with pytest.raises(ValueError, match="face of a rigid end zone"):
        plan_frame_members(offset)
    # Without the spring, the element releases it at the face itself.
    offset.elements[4] = offset.elements[4].model_copy(
        update={"releases": FrameReleases(i=EndRelease(released=("M3",)))}
    )
    plan = plan_frame_members(offset)
    assert plan.members[5].release_args == ("-releasez", 1)
    assert plan.members[5].joint_offset == pytest.approx((0.25, 0, 0, 0, 0, 0))

    fibre = _released(i=EndRelease(released=("M3",)))
    fibre.sections.append(
        FiberSection(
            id=2,
            patches=[
                RectangularPatch(material_id=1, n_fib_y=1, n_fib_z=1, y_i=-1, z_i=-1, y_j=1, z_j=1)
            ],
        )
    )
    fibre.elements[4] = ForceBeamColumn(
        id=5, nodes=(5, 6), section_id=2, releases=fibre.elements[4].releases
    )
    with pytest.raises(ValueError, match="fibre member"):
        plan_frame_members(fibre)


def test_a_project_without_releases_at_diaphragm_joints_plans_as_before() -> None:
    """The same release at a joint no diaphragm constrains keeps its equalDOF."""
    from opensees_studio.services.frame_members import plan_frame_members

    project = _released(i=EndRelease(released=("M3",)))
    project.diaphragms.clear()
    plan = plan_frame_members(project)
    (hidden,) = plan.nodes
    assert plan.equal_dofs == [(5, hidden.tag, (1, 2, 3, 4, 5))]
    assert plan.members[5].release_args == ()
