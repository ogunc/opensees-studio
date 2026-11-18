"""Frame releases, end offsets, insertion points, modifiers and trapezoidal loads.

The model and its file format, the member geometry, the load split, and the
OpenSees commands the runner plans and emits for them (with a recorder in place
of OpenSees, so no solver is needed here).
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from pydantic import ValidationError

from opensees_studio.core import (
    ElasticBeamColumn,
    ElasticSection,
    EndRelease,
    EqualDOFConstraint,
    FiberSection,
    ForceBeamColumn,
    FrameEndOffsets,
    FrameInsertion,
    FrameModifiers,
    FrameReleases,
    LinearTimeSeries,
    Node,
    PlainLoadPattern,
    Project,
    RectangularPatch,
    RigidLink,
    StaticCase,
    TrapezoidalElementLoad,
    UniformElementLoad,
)
from opensees_studio.core.frame_members import (
    ClearPiece,
    cardinal_offset,
    connectivity_offsets,
    gauss_point_loads,
    member_layout,
    section_extents,
    split_member_loads,
)
from opensees_studio.services.frame_members import (
    CONSTRAINED_PENALTY_FACTOR,
    PENALTY_FACTOR,
    plan_frame_members,
)
from opensees_studio.services.opensees_script import export_script

E, A, IZ = 2.0e8, 0.02, 2.0e-4


def _project(*elements, ndm: int = 2, end=(6.0, 0.0, 0.0), sections=None, **pattern) -> Project:  # type: ignore[no-untyped-def]
    return Project(
        ndm=ndm,
        ndf=3 if ndm == 2 else 6,
        nodes=[Node(id=1, coords=(0.0, 0.0, 0.0)), Node(id=2, coords=end)],
        sections=sections or [ElasticSection(id=1, E=E, A=A, Iz=IZ, Iy=IZ, G=8e7, J=3e-4)],
        elements=list(elements) or [ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1)],
        time_series=[LinearTimeSeries(id=1)],
        load_patterns=[PlainLoadPattern(id=1, time_series_id=1, **pattern)],
        analyses=[StaticCase(id=1, name="s", pattern_ids=[1])],
    )


def _beam(**options) -> ElasticBeamColumn:  # type: ignore[no-untyped-def]
    return ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1, **options)


# ──────────────────────────── model ────────────────────────────
def test_a_member_without_assignments_saves_as_before() -> None:
    dump = _beam().model_dump()
    for name in ("releases", "end_offsets", "insertion", "modifiers"):
        assert name not in dump
    assert "distributed_loads" not in PlainLoadPattern(id=1, time_series_id=1).model_dump()


def test_assignments_round_trip() -> None:
    beam = _beam(
        releases=FrameReleases(i=EndRelease(released=("M3", "T"), springs={"M3": 5.0})),
        end_offsets=FrameEndOffsets(length_i=0.3, rigid_factor=0.5),
        insertion=FrameInsertion(cardinal_point=8, offset_2=0.1),
        modifiers=FrameModifiers(i33=0.35, mass=0.0),
    )
    again = ElasticBeamColumn.model_validate_json(beam.model_dump_json())
    assert again == beam
    assert again.releases.i.released == ("T", "M3")  # canonical order


def test_a_spring_needs_its_action_released() -> None:
    with pytest.raises(ValidationError, match="needs M2 to be released"):
        EndRelease(released=("M3",), springs={"M2": 1.0})
    with pytest.raises(ValidationError, match="positive"):
        EndRelease(released=("M3",), springs={"M3": 0.0})


def test_torsion_released_at_both_ends_is_unstable() -> None:
    with pytest.raises(ValidationError, match="spin"):
        FrameReleases(i=EndRelease(released=("T",)), j=EndRelease(released=("T",)))
    FrameReleases(i=EndRelease(released=("T",)), j=EndRelease(released=("T",), springs={"T": 1.0}))


def test_a_distributed_load_runs_forward() -> None:
    with pytest.raises(ValidationError, match="x_end > x_start"):
        TrapezoidalElementLoad(element_id=1, x_start=0.5, x_end=0.5)


def test_a_distributed_load_needs_a_frame() -> None:
    project = _project(distributed_loads=[TrapezoidalElementLoad(element_id=9, wy_start=-1.0)])
    with pytest.raises(ValueError, match="missing element 9"):
        project.validate_references()


# ──────────────────────────── geometry ────────────────────────────
def test_rigid_zones_and_clear_length() -> None:
    project = _project(
        _beam(end_offsets=FrameEndOffsets(length_i=0.4, length_j=0.6, rigid_factor=0.5))
    )
    layout = member_layout(project, project.elements[0])
    assert layout is not None
    assert (layout.rigid_i, layout.rigid_j) == pytest.approx((0.2, 0.3))
    assert layout.clear_length == pytest.approx(5.5)
    assert layout.offset_i == pytest.approx([0.2, 0.0, 0.0])
    assert layout.offset_j == pytest.approx([-0.3, 0.0, 0.0])


def test_rigid_zones_must_leave_a_flexible_length() -> None:
    project = _project(_beam(end_offsets=FrameEndOffsets(length_i=3.0, length_j=3.0)))
    with pytest.raises(ValueError, match="no flexible length"):
        member_layout(project, project.elements[0])


@pytest.mark.parametrize(
    ("point", "expected"),
    [(8, (-0.25, 0.0)), (2, (0.25, 0.0)), (1, (0.25, 0.1)), (9, (-0.25, -0.1)), (10, (0.0, 0.0))],
)
def test_cardinal_points(point: int, expected: tuple[float, float]) -> None:
    project = _project(
        sections=[
            FiberSection(
                id=1,
                patches=[
                    RectangularPatch(
                        material_id=1, n_fib_y=2, n_fib_z=2, y_i=-0.25, z_i=-0.1, y_j=0.25, z_j=0.1
                    )
                ],
                GJ=1.0,
            )
        ]
    )
    assert cardinal_offset(point, section_extents(project, 1)) == pytest.approx(expected)


def test_an_elastic_section_is_sized_from_its_inertia() -> None:
    extents = section_extents(_project(), 1)
    assert extents is not None
    depth = math.sqrt(12 * IZ / A)
    assert (extents.y_min, extents.y_max) == pytest.approx((-depth / 2, depth / 2))


def test_a_top_insertion_lowers_a_2d_beam() -> None:
    project = _project(_beam(insertion=FrameInsertion(cardinal_point=8)))
    layout = member_layout(project, project.elements[0])
    assert layout is not None
    # A 2D beam along X: local y is +Z (the X-Z plane), so the top lies along -Z.
    assert layout.offset_i == pytest.approx([0.0, 0.0, -math.sqrt(12 * IZ / A) / 2])
    assert layout.offset_j == pytest.approx(layout.offset_i)


# ──────────────────────────── load split ────────────────────────────
def _layout(**offsets):  # type: ignore[no-untyped-def]
    project = _project(_beam(end_offsets=FrameEndOffsets(**offsets)))
    return member_layout(project, project.elements[0])


def test_a_load_on_a_rigid_zone_moves_to_the_joint() -> None:
    layout = _layout(length_i=1.0)
    w = (0.0, -10.0, 0.0)
    split = split_member_loads(layout, [(0.0, 1.0, w, w)])
    force, moment = split.joint["i"]
    # Local -y of a 2D beam is global -Z; the moment is about global Y.
    assert force == pytest.approx([0.0, 0.0, -10.0])
    assert moment == pytest.approx([0.0, 5.0, 0.0])  # 10 kN at 0.5 m
    (piece,) = split.pieces
    assert (piece.a, piece.b) == pytest.approx((0.0, 1.0))
    assert piece.is_uniform_full


def test_a_trapezoid_is_cut_at_the_rigid_zone() -> None:
    layout = _layout(length_j=1.5)
    split = split_member_loads(layout, [(0.5, 1.0, (0, -1.0, 0), (0, -2.0, 0))])
    (piece,) = split.pieces
    # Full length 6, clear 4.5: 3..4.5 m of it, i.e. 2/3..1 of the clear span.
    assert (piece.a, piece.b) == pytest.approx((2 / 3, 1.0))
    assert piece.w_b[1] == pytest.approx(-1.5)
    force, _ = split.joint["j"]
    assert force[2] == pytest.approx(-(1.5 + 2.0) / 2 * 1.5)


def test_a_point_load_on_a_rigid_zone() -> None:
    layout = _layout(length_j=1.0)
    split = split_member_loads(layout, points=[(1.0, (0.0, -3.0, 0.0))])
    force, moment = split.joint["j"]
    assert force == pytest.approx([0.0, 0.0, -3.0])
    assert moment == pytest.approx([0.0, 0.0, 0.0])  # at the joint itself
    assert not split.points


def test_gauss_points_keep_the_resultant_and_its_moments() -> None:
    piece = ClearPiece(a=0.2, b=0.9, w_a=np.array([0.0, -1.0, 0.0]), w_b=np.array([0.0, -4.0, 0.0]))
    points = gauss_point_loads(piece, 10.0)
    xs = np.linspace(2.0, 9.0, 20001)
    w = np.interp(xs, [2.0, 9.0], [-1.0, -4.0])
    for power in range(4):
        exact = np.trapezoid(w * xs**power, xs)
        total = sum(p.p[1] * (10.0 * p.x) ** power for p in points)
        assert total == pytest.approx(exact, rel=1e-6)


# ──────────────────────────── plan ────────────────────────────
def test_an_aligned_moment_release_is_an_equal_dof() -> None:
    plan = plan_frame_members(
        _project(_beam(releases=FrameReleases(j=EndRelease(released=("M3",)))))
    )
    (hidden,) = plan.nodes
    assert hidden.tag == 3 and hidden.joint == 2
    assert plan.equal_dofs == [(2, 3, (1, 2))]
    assert plan.members[1].nodes == (1, 3)
    assert not plan.springs and not plan.needs_transformation
    assert plan.released_dofs[(1, "j")] == {3}


def test_a_spring_is_a_zero_length_element() -> None:
    releases = FrameReleases(i=EndRelease(released=("M3",), springs={"M3": 7.0}))
    plan = plan_frame_members(_project(_beam(releases=releases)))
    (spring,) = plan.springs
    assert (spring.tag, spring.node_a, spring.node_b) == (2, 1, 3)
    assert spring.dirs == (6,) and spring.stiffnesses == (7.0,)
    assert spring.material_tags == (1,)


def test_a_skewed_kept_torsion_gets_a_penalty_spring() -> None:
    releases = FrameReleases(j=EndRelease(released=("M2", "M3")))
    plan = plan_frame_members(_project(_beam(releases=releases), ndm=3, end=(3.0, 3.0, 0.0)))
    assert plan.equal_dofs == [(2, 3, (1, 2, 3))]
    (spring,) = plan.springs
    assert spring.dirs == (4,)
    length = math.hypot(3.0, 3.0)
    assert spring.stiffnesses[0] == pytest.approx(PENALTY_FACTOR * 4 * E * IZ / length)


def test_the_same_release_along_x_needs_no_penalty() -> None:
    releases = FrameReleases(j=EndRelease(released=("M2", "M3")))
    plan = plan_frame_members(_project(_beam(releases=releases), ndm=3))
    assert plan.equal_dofs == [(2, 3, (1, 2, 3, 4))]
    assert not plan.springs


def test_a_release_at_an_offset_end_hangs_off_a_rigid_link() -> None:
    beam = _beam(
        releases=FrameReleases(j=EndRelease(released=("M3",))),
        end_offsets=FrameEndOffsets(length_j=0.5),
    )
    plan = plan_frame_members(_project(beam))
    face, inner = plan.nodes
    assert face.coords == pytest.approx((5.5, 0.0))
    assert plan.rigid_links == [(2, face.tag)]
    assert plan.equal_dofs == [(face.tag, inner.tag, (1, 2))]
    assert plan.needs_transformation
    assert plan.members[1].joint_offset == ()


def test_a_2d_frame_only_releases_m3() -> None:
    with pytest.raises(ValueError, match="only release M3"):
        plan_frame_members(_project(_beam(releases=FrameReleases(i=EndRelease(released=("T",))))))


def test_corotational_3d_offsets_are_refused() -> None:
    beam = _beam(geom_transf="Corotational", end_offsets=FrameEndOffsets(length_i=0.2))
    with pytest.raises(ValueError, match="Corotational"):
        plan_frame_members(_project(beam, ndm=3))


def test_modifiers_share_a_derived_section() -> None:
    mods = FrameModifiers(i33=0.35, area=0.5)
    project = _project(
        _beam(modifiers=mods),
        ElasticBeamColumn(id=2, nodes=(1, 2), section_id=1, modifiers=mods),
    )
    plan = plan_frame_members(project)
    (derived,) = plan.sections
    assert derived.tag == 2
    assert derived.args == pytest.approx((E, 0.5 * A, 0.35 * IZ))
    assert plan.members[1].section_id == plan.members[2].section_id == 2


def test_stiffness_modifiers_need_an_elastic_section() -> None:
    fiber = FiberSection(
        id=1,
        patches=[
            RectangularPatch(material_id=1, n_fib_y=1, n_fib_z=1, y_i=-1, z_i=-1, y_j=1, z_j=1)
        ],
    )
    beam = ForceBeamColumn(id=1, nodes=(1, 2), section_id=1, modifiers=FrameModifiers(i33=0.5))
    with pytest.raises(ValueError, match="elastic section"):
        plan_frame_members(_project(beam, sections=[fiber]))


# ─────────────────────── releases at constrained joints ───────────────────────
def _constrained_at_2(beam: ElasticBeamColumn, link: str, ndm: int = 2, **pattern) -> Project:  # type: ignore[no-untyped-def]
    """``beam`` with its joint 2 the constrained node of a user equalDOF or rigid link."""
    project = _project(beam, ndm=ndm, **pattern)
    # 2D lives in the X-Z plane (Z up).
    project.nodes.append(Node(id=3, coords=(6.0, 0.0, 1.0) if ndm == 2 else (6.0, 1.0, 0.0)))
    if link == "equalDOF":
        project.mp_constraints.append(
            EqualDOFConstraint(retained_node=3, constrained_node=2, dofs=(1,))
        )
    else:
        project.rigid_links.append(RigidLink(retained_node=3, constrained_node=2))
    return project


@pytest.mark.parametrize("link", ["equalDOF", "rigidLink"])
@pytest.mark.parametrize("ndm", [2, 3])
def test_a_release_at_a_constrained_joint_is_made_in_the_element(link: str, ndm: int) -> None:
    """A hidden node equalDOF'd to the joint would chain the two constraints."""
    plan = plan_frame_members(
        _constrained_at_2(_beam(releases=FrameReleases(j=EndRelease(released=("M3",)))), link, ndm)
    )
    assert not plan.nodes and not plan.equal_dofs and not plan.springs
    assert plan.members[1].nodes == (1, 2)
    assert plan.members[1].release_args == (("-release", 2) if ndm == 2 else ("-releasez", 2))
    assert plan.released_dofs[(1, "j")] == ({3} if ndm == 2 else {6})


def test_a_2d_partial_fixity_at_a_constrained_joint_is_held_by_penalty_springs() -> None:
    releases = FrameReleases(j=EndRelease(released=("M3",), springs={"M3": 7.0}))
    plan = plan_frame_members(_constrained_at_2(_beam(releases=releases), "equalDOF"))
    (hidden,) = plan.nodes
    assert hidden.coords == (6.0, 0.0) and hidden.joint == 2
    assert plan.members[1].nodes == (1, hidden.tag)
    assert not plan.equal_dofs and not plan.attached and plan.members[1].release_args == ()
    (link,) = plan.springs
    assert (link.node_a, link.node_b) == (2, hidden.tag)
    k_t = CONSTRAINED_PENALTY_FACTOR * max(E * A / 6.0, 12 * E * IZ / 6.0**3)
    assert link.dirs == (1, 2, 6)
    assert link.stiffnesses == pytest.approx((k_t, k_t, 7.0))


def test_a_point_load_sends_a_constrained_release_to_the_springs() -> None:
    """OpenSees condenses only a full-length ``-beamUniform`` in a released element."""
    from opensees_studio.core import PointElementLoad

    releases = FrameReleases(j=EndRelease(released=("M3",)))
    project = _constrained_at_2(
        _beam(releases=releases),
        "rigidLink",
        point_loads=[PointElementLoad(element_id=1, x=0.5, py=-1.0)],
    )
    plan = plan_frame_members(project)
    (link,) = plan.springs
    # The kept rotation is free: only the translations are tied.
    assert link.dirs == (1, 2) and plan.members[1].release_args == ()


def test_a_release_at_a_retained_joint_keeps_its_equal_dof() -> None:
    """Only the constrained node of a constraint would chain: joint 2 retains this one."""
    project = _project(_beam(releases=FrameReleases(j=EndRelease(released=("M3",)))))
    project.nodes.append(Node(id=3, coords=(6.0, 0.0, 1.0)))
    project.mp_constraints.append(
        EqualDOFConstraint(retained_node=2, constrained_node=3, dofs=(1,))
    )
    plan = plan_frame_members(project)
    assert plan.equal_dofs == [(2, 4, (1, 2))]
    assert plan.members[1].release_args == ()


@pytest.mark.parametrize(
    ("link", "remedy"),
    [("equalDOF", "remove an equalDOF"), ("rigidLink", "remove a rigid link")],
)
def test_a_fibre_member_released_at_a_constrained_joint_is_refused(link: str, remedy: str) -> None:
    fibre = FiberSection(
        id=1,
        patches=[
            RectangularPatch(material_id=1, n_fib_y=1, n_fib_z=1, y_i=-1, z_i=-1, y_j=1, z_j=1)
        ],
    )
    beam = ForceBeamColumn(
        id=1, nodes=(1, 2), section_id=1, releases=FrameReleases(j=EndRelease(released=("M3",)))
    )
    project = _constrained_at_2(beam, link)  # type: ignore[arg-type]
    project.sections[:] = [fibre]
    with pytest.raises(ValueError, match=f"joint 2, which an? .*{remedy}"):
        plan_frame_members(project)


def test_the_2d_element_release_reaches_the_script() -> None:
    project = _constrained_at_2(
        _beam(releases=FrameReleases(j=EndRelease(released=("M3",)))), "equalDOF"
    )
    # Hold joint 2's rotation (nothing else stiffens it) and the retained node.
    project.nodes[1] = project.nodes[1].model_copy(
        update={"restraint": (False, False, False, False, True, False)}  # Ry
    )
    project.nodes[2] = project.nodes[2].model_copy(update={"restraint": (True,) * 6})
    script = export_script(project, project.analyses[0])
    assert "ops.element('elasticBeamColumn', 1, 1, 2, 1, 1, '-mass', 0.0, '-release', 2)" in script
    assert script.count("ops.equalDOF") == 1


# ──────────────────────────── emitted script ────────────────────────────
def test_the_script_carries_the_assignments() -> None:
    beam = _beam(
        releases=FrameReleases(j=EndRelease(released=("M3",), springs={"M3": 9.0})),
        end_offsets=FrameEndOffsets(length_i=0.5),
        modifiers=FrameModifiers(i33=0.5),
    )
    project = _project(
        beam,
        element_loads=[UniformElementLoad(element_id=1, wy=-1.0)],
        distributed_loads=[TrapezoidalElementLoad(element_id=1, x_start=0.5, wy_start=-2.0)],
    )
    script = export_script(project, project.analyses[0])
    assert "ops.geomTransf('Linear', 1, '-jntOffset', 0.5, 0.0, 0.0, 0.0)" in script
    assert "ops.equalDOF(2, 3, 1, 2)" in script
    assert "ops.uniaxialMaterial('Elastic', 1, 9.0)" in script
    assert "ops.section('Elastic', 2, 200000000.0, 0.02, 0.0001)" in script
    assert "ops.element('elasticBeamColumn', 1, 1, 3, 2, 1, '-mass', 0.0)" in script
    assert "'zeroLength', 2, 2, 3, '-mat', 1, '-dir', 6" in script
    # The load on the rigid zone goes to joint 1; the clear part as Gauss point loads.
    assert "ops.load(1, " in script
    assert script.count("'-beamPoint'") == 3


def test_an_unassigned_model_emits_what_it_always_did() -> None:
    project = _project(element_loads=[UniformElementLoad(element_id=1, wy=-1.0)])
    script = export_script(project, project.analyses[0])
    assert "jntOffset" not in script and "equalDOF" not in script
    assert "ops.eleLoad('-ele', 1, '-type', '-beamUniform', -1.0, 0.0)" in script


# ──────────────────────────── diagrams ────────────────────────────
def test_diagrams_run_along_the_flexible_length() -> None:
    from opensees_studio.services.element_forces import ForceComponent, extract_diagram_data
    from opensees_studio.services.results import StaticResults

    project = _project(_beam(end_offsets=FrameEndOffsets(length_i=0.5, length_j=1.0)))
    results = StaticResults(
        case_id=1,
        case_name="s",
        n_steps=1,
        node_disp={},
        node_reaction={},
        element_forces={1: np.array([[0.0, 1.0, 2.0, 0.0, -1.0, 3.0]])},
    )
    data = extract_diagram_data(project, results, ForceComponent.M3)
    start, end = data.ends[1]
    assert start == pytest.approx([0.5, 0.0, 0.0])
    assert end == pytest.approx([5.0, 0.0, 0.0])
    assert not extract_diagram_data(_project(), results, ForceComponent.M3).ends


# ──────────────────────────── offsets from connectivity ────────────────────────────
def _frame_with_columns(ndm: int = 2) -> Project:
    """A 6 m beam (1-2) with a 0.4 m column on joint 1 and a 0.6 m column on joint 2."""
    wide = 0.6 * 0.6
    sections = [
        ElasticSection(id=1, E=E, A=A, Iz=IZ, Iy=IZ, G=8e7, J=3e-4),
        ElasticSection(id=2, E=E, A=0.16, Iz=0.16 * 0.16 / 12, Iy=0.16 * 0.16 / 12, G=8e7, J=1e-3),
        ElasticSection(id=3, E=E, A=wide, Iz=wide * wide / 12, Iy=wide * wide / 12, G=8e7, J=1e-3),
    ]
    project = _project(sections=sections, ndm=ndm)
    up = 2 if ndm == 2 else 1  # 2D: columns rise along Z (the X-Z plane)
    project.nodes += [
        Node(id=3, coords=tuple(3.0 if k == up else 0.0 for k in range(3))),
        Node(id=4, coords=tuple(3.0 if k == up else (6.0 if k == 0 else 0.0) for k in range(3))),
        Node(id=5, coords=(12.0, 0.0, 0.0)),
    ]
    project.elements += [
        ElasticBeamColumn(id=2, nodes=(1, 3), section_id=2),
        ElasticBeamColumn(id=3, nodes=(2, 4), section_id=3),
        # collinear neighbour: its depth is across the beam axis only if it were crossing
        ElasticBeamColumn(id=4, nodes=(2, 5), section_id=3),
    ]
    return project


@pytest.mark.parametrize("ndm", [2, 3])
def test_connectivity_offsets_are_half_the_framing_member_depth(ndm: int) -> None:
    project = _frame_with_columns(ndm)
    li, lj = connectivity_offsets(project, 1)
    assert li == pytest.approx(0.2)
    assert lj == pytest.approx(0.3)  # the collinear member adds nothing, the column 0.6/2


def test_connectivity_offsets_follow_the_projection_on_the_member_axis() -> None:
    """A column leaning at 45 deg reaches into the beam by the projected half extent."""
    project = _frame_with_columns()
    project.nodes[2] = Node(id=3, coords=(3.0, 0.0, 3.0))  # column 2 at 45 deg
    li, _ = connectivity_offsets(project, 1)
    assert li == pytest.approx(
        0.2 * math.sqrt(0.5)
    )  # |x . y_col| * h/2, y_col = (-1, 1)/sqrt2 -> .707


def test_connectivity_offsets_of_an_isolated_member_are_zero() -> None:
    assert connectivity_offsets(_project(), 1) == (0.0, 0.0)


def test_connectivity_offsets_need_a_frame() -> None:
    project = _frame_with_columns()
    with pytest.raises(ValueError, match="not a frame member"):
        connectivity_offsets(project, 99)


# ──────────────────────────── shear areas ────────────────────────────
def test_shear_areas_are_left_out_of_a_dump_until_set() -> None:
    plain = ElasticSection(id=1, E=E, A=A, Iz=IZ)
    assert "As2" not in plain.model_dump() and "As3" not in plain.model_dump()
    assert not plain.has_shear_deformation
    shear = ElasticSection(id=1, E=E, A=A, Iz=IZ, G=8e7, As2=0.01)
    assert ElasticSection.model_validate(shear.model_dump()).As2 == 0.01
    assert shear.has_shear_deformation


def test_a_section_with_shear_areas_plans_a_timoshenko_member() -> None:
    section = ElasticSection(id=1, E=E, A=A, Iz=IZ, G=8e7, As2=0.01)
    element = _beam(modifiers=FrameModifiers(as2=0.5, i33=0.5))
    plan = plan_frame_members(_project(element, sections=[section]))
    assert plan.members[1].timoshenko == (E, 8e7, A, IZ * 0.5, 0.005)
    assert plan_frame_members(_project()).members[1].timoshenko is None


def test_a_zero_shear_modifier_turns_shear_deformation_off() -> None:
    section = ElasticSection(id=1, E=E, A=A, Iz=IZ, G=8e7, As2=0.01)
    element = _beam(modifiers=FrameModifiers(as2=0.0, i33=0.5))
    plan = plan_frame_members(_project(element, sections=[section]))
    assert plan.members[1].timoshenko is None
    assert plan.members[1].section_id != 1  # the I33 modifier still derives a section


def test_a_zero_as3_modifier_disables_shear_in_3d() -> None:
    section = ElasticSection(id=1, E=E, A=A, Iz=IZ, Iy=IZ, G=8e7, J=3e-4, As2=0.01, As3=0.02)
    element = _beam(modifiers=FrameModifiers(as3=0.0))
    plan = plan_frame_members(_project(element, sections=[section], ndm=3))
    assert plan.members[1].timoshenko is None


def test_a_shear_area_needs_the_shear_modulus() -> None:
    section = ElasticSection(id=1, E=E, A=A, Iz=IZ, As2=0.01)
    with pytest.raises(ValueError, match="shear modulus"):
        plan_frame_members(_project(sections=[section]))


def test_a_3d_timoshenko_member_needs_both_shear_areas() -> None:
    section = ElasticSection(id=1, E=E, A=A, Iz=IZ, Iy=IZ, G=8e7, J=3e-4, As2=0.01)
    with pytest.raises(ValueError, match="As2, As3"):
        plan_frame_members(_project(sections=[section], ndm=3))


def test_a_shape_hint_stands_upright_in_2d_and_3d() -> None:
    from opensees_studio.core import RectShape

    section = ElasticSection(
        id=1, E=E, A=A, Iz=IZ, Iy=IZ, G=8e7, J=3e-4, shape=RectShape(d=0.5, b=0.2)
    )
    two = section_extents(_project(sections=[section]), 1)
    three = section_extents(_project(sections=[section], ndm=3), 1)
    assert (two.y_max - two.y_min, two.z_max - two.z_min) == pytest.approx((0.5, 0.2))
    assert (three.y_max - three.y_min, three.z_max - three.z_min) == pytest.approx((0.2, 0.5))


def test_is_default_is_true_only_for_an_untouched_option() -> None:
    """The renderer skips members whose options are all defaults, so this is load-bearing."""
    from opensees_studio.core.geometry.frame_options import (
        FrameEndOffsets,
        FrameInsertion,
        FrameReleases,
    )

    assert FrameReleases().is_default()
    assert FrameEndOffsets().is_default()
    assert FrameInsertion().is_default()

    released = FrameReleases(i={"released": ("M3",)})
    assert not released.is_default()

    # A spring only means something on a released action; the validator refuses
    # the other way round, so is_default never sees that state.
    assert FrameReleases(j={"released": ("M3",), "springs": {"M3": 1e9}}).is_default() is False

    assert not FrameEndOffsets(length_i=0.4).is_default()
    assert not FrameInsertion(offset_2=0.1).is_default()


def test_is_default_does_not_share_a_mutable_default_between_classes() -> None:
    """The per-class cache must not leak one class's defaults into another."""
    from opensees_studio.core.geometry.frame_options import FrameEndOffsets, FrameReleases

    assert FrameReleases().is_default()
    assert FrameEndOffsets().is_default()
    assert not FrameReleases(i={"released": ("T",)}).is_default()
    assert FrameReleases().is_default(), "the cache must survive a non-default instance"
