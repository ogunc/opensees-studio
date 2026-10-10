"""The review that runs before the analysis: loose nodes, loose members, mechanisms.

Two halves, and both have to hold. The check must *find* what stops a model from
solving — a node nobody reaches, a frame missing a support, bars that line up —
and it must stay quiet about models that are fine, because a check that cries
wolf is a check people learn to click through. The second half is pinned by the
shipped examples and by the long-chain and 3D-grid cases below.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from opensees_studio.core import (
    ElasticBeamColumn,
    ElasticSection,
    EqualDOFConstraint,
    Node,
    Project,
    QuadElement,
    ShellMITC4Element,
    TrussElement,
    ZeroLengthElement,
)
from opensees_studio.core.model_check import (
    MAX_DOF_ENV,
    Severity,
    check_model,
)
from opensees_studio.services.persistence import load_project

EXAMPLES = sorted((Path(__file__).resolve().parents[2] / "examples").glob("*.osmodel"))

PIN = (True, True, False, False, False, False)  # Ux, Uy
ROLLER = (False, True, False, False, False, False)  # Uy
FIXED = (True, True, True, True, True, True)
BALL = (True, True, True, False, False, False)  # Ux, Uy, Uz; rotations free
FREE = (False,) * 6


def _section() -> ElasticSection:
    return ElasticSection(id=1, name="S", E=200e9, A=0.01, Iz=1e-5, Iy=1e-5, G=80e9, J=1e-6)


def _node(nid: int, x: float = 0.0, y: float = 0.0, z: float = 0.0, fix: tuple = FREE) -> Node:
    return Node(id=nid, coords=(x, y, z), restraint=fix)  # type: ignore[arg-type]


def _beam(eid: int, a: int, b: int) -> ElasticBeamColumn:
    return ElasticBeamColumn(id=eid, nodes=(a, b), section_id=1)


def _bar(eid: int, a: int, b: int) -> TrussElement:
    return TrussElement(id=eid, nodes=(a, b), area=0.01, material_id=1)


def _frame2d(nodes: list[Node], elements: list, **extra: object) -> Project:
    """A 2D frame model: ndm=2, ndf=3 (Ux, Uy, Rz)."""
    return Project(ndm=2, ndf=3, nodes=nodes, sections=[_section()], elements=elements, **extra)  # type: ignore[arg-type]


def _truss2d(nodes: list[Node], elements: list) -> Project:
    """A 2D truss model: ndm=2, ndf=2."""
    return Project(ndm=2, ndf=2, nodes=nodes, sections=[_section()], elements=elements)  # type: ignore[arg-type]


def _frame3d(nodes: list[Node], elements: list, **extra: object) -> Project:
    return Project(ndm=3, ndf=6, nodes=nodes, sections=[_section()], elements=elements, **extra)  # type: ignore[arg-type]


def _portal() -> Project:
    """Fixed-base portal frame: the model every defect below is a variation of."""
    return _frame2d(
        [
            _node(1, 0, 0, fix=FIXED),
            _node(2, 0, 3),
            _node(3, 4, 3),
            _node(4, 4, 0, fix=FIXED),
        ],
        [_beam(1, 1, 2), _beam(2, 2, 3), _beam(3, 3, 4)],
    )


def _codes(report) -> list[str]:
    return [f.code for f in report.findings]


def _only(report, code: str):
    found = [f for f in report.findings if f.code == code]
    assert len(found) == 1, f"expected one {code!r}, got {_codes(report)}"
    return found[0]


# ──────────────────────────── a good model ────────────────────────────
def test_a_sound_frame_passes_and_says_it_was_checked() -> None:
    report = check_model(_portal())

    assert report.is_clean
    assert not report.has_errors
    assert report.findings == ()
    assert report.stability_checked
    assert report.part_count == 1
    assert report.mechanism_count == 0
    assert "passed" in report.summary()


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.stem)
def test_every_shipped_example_passes(path: Path) -> None:
    """The examples all solve, so any error here is the check being wrong."""
    report = check_model(load_project(path))
    assert not report.has_errors, [f.summary() for f in report.errors]
    assert report.is_clean, [f.summary() for f in report.warnings]


def test_an_empty_project_is_an_error_not_a_crash() -> None:
    report = check_model(Project())
    assert _codes(report) == ["no_nodes"]
    assert report.has_errors


def test_nodes_without_any_element_are_reported_once() -> None:
    report = check_model(_frame2d([_node(1, fix=FIXED), _node(2, 1, 0)], []))
    finding = _only(report, "no_elements")
    assert finding.severity is Severity.ERROR
    assert finding.node_ids == (1, 2)


# ──────────────────────────── loose nodes ────────────────────────────
def test_a_free_node_that_nothing_reaches_is_an_error() -> None:
    project = _portal()
    project.nodes.append(_node(9, 7, 7))

    finding = _only(check_model(project), "orphan_node")
    assert finding.severity is Severity.ERROR
    assert finding.node_ids == (9,)


def test_a_fully_restrained_loose_node_is_only_clutter() -> None:
    project = _portal()
    project.nodes.append(_node(9, 7, 7, fix=FIXED))

    report = check_model(project)
    finding = _only(report, "orphan_support")
    assert finding.severity is Severity.WARNING
    assert not report.has_errors
    assert not report.is_clean


def test_a_node_held_only_by_an_equal_dof_constraint_is_not_loose() -> None:
    project = _portal()
    project.nodes.append(_node(9, 0, 3))
    project.mp_constraints.append(
        EqualDOFConstraint(retained_node=2, constrained_node=9, dofs=(1, 2, 3))
    )
    assert "orphan_node" not in _codes(check_model(project))


# ──────────────────────────── references and geometry ────────────────────────────
def test_an_element_pointing_at_a_deleted_node_is_named() -> None:
    project = _portal()
    project.elements.append(_beam(7, 3, 99))

    finding = _only(check_model(project), "missing_node")
    assert finding.severity is Severity.ERROR
    assert finding.element_ids == (7,)
    assert "99" in finding.message


def test_a_constraint_pointing_at_a_deleted_node_is_reported() -> None:
    project = _portal()
    project.mp_constraints.append(
        EqualDOFConstraint(retained_node=2, constrained_node=42, dofs=(1,))
    )
    finding = _only(check_model(project), "missing_node")
    assert "42" in finding.message


def test_a_bar_with_the_same_node_at_both_ends_is_reported() -> None:
    project = _portal()
    project.elements.append(_bar(8, 2, 2))
    finding = _only(check_model(project), "repeated_node")
    assert finding.element_ids == (8,)


def test_a_member_of_zero_length_is_an_error() -> None:
    project = _portal()
    project.nodes.append(_node(5, 0, 3))  # on top of node 2
    project.elements.append(_beam(8, 2, 5))

    finding = _only(check_model(project), "zero_length_member")
    assert finding.element_ids == (8,)
    assert finding.node_ids == (2, 5)


def test_a_zero_length_element_with_its_nodes_apart_is_a_warning() -> None:
    project = _frame2d(
        [_node(1, fix=FIXED), _node(2, 1, 0)],
        [ZeroLengthElement(id=1, nodes=(1, 2), material_ids=(1,), dofs=(1, 2, 3))],
    )
    finding = _only(check_model(project), "separated_zero_length")
    assert finding.severity is Severity.WARNING


def test_a_zero_length_element_acting_on_a_missing_dof_is_reported() -> None:
    project = _frame2d(
        [_node(1, fix=FIXED), _node(2)],
        [ZeroLengthElement(id=1, nodes=(1, 2), material_ids=(1,), dofs=(1, 6))],
    )
    assert "dof_mismatch" in _codes(check_model(project))


def test_a_frame_in_a_model_without_rotations_is_a_dof_mismatch() -> None:
    project = Project(
        ndm=2,
        ndf=2,
        nodes=[_node(1, fix=PIN), _node(2, 3)],
        sections=[_section()],
        elements=[_beam(1, 1, 2)],
    )
    assert "dof_mismatch" in _codes(check_model(project))


def test_a_quad_outside_a_2d_solid_model_is_a_dof_mismatch() -> None:
    quad = QuadElement(id=1, nodes=(1, 2, 3, 4), thickness=0.1, material_id=1)
    project = _frame2d(
        [_node(1, fix=FIXED), _node(2, 1), _node(3, 1, 1), _node(4, 0, 1)],
        [quad],
    )
    assert "dof_mismatch" in _codes(check_model(project))


# ──────────────────────────── connectivity ────────────────────────────
def test_a_model_with_no_supports_is_a_rigid_body() -> None:
    project = _frame2d([_node(1), _node(2, 3)], [_beam(1, 1, 2)])
    report = check_model(project)

    finding = _only(report, "floating_part")
    assert finding.severity is Severity.ERROR
    assert "no supports" in finding.message
    assert not report.stability_checked  # nothing supported to test


def test_one_unsupported_part_is_named_among_supported_ones() -> None:
    project = _frame2d(
        [_node(1, fix=FIXED), _node(2, 3), _node(5, 10), _node(6, 13)],
        [_beam(1, 1, 2), _beam(2, 5, 6)],
    )
    finding = _only(check_model(project), "floating_part")
    assert finding.node_ids == (5, 6)
    assert "no support" in finding.message


def test_two_supported_parts_are_a_warning_naming_the_nodes_on_top_of_each_other() -> None:
    project = _frame2d(
        [_node(1, fix=FIXED), _node(2, 3), _node(3, 0, 3), _node(4, 3, 3, fix=FIXED)],
        [_beam(1, 1, 2), _beam(2, 3, 4)],
    )
    # Nodes 2 and 3 are different points here, so move 3 onto 2.
    project.nodes[2] = _node(3, 3, 0)
    report = check_model(project)

    finding = _only(report, "disconnected_parts")
    assert finding.severity is Severity.WARNING
    assert finding.node_ids == (2, 3)
    assert "merge" in finding.hint
    assert not report.has_errors
    assert report.part_count == 2


def test_separate_parts_without_a_coincident_pair_get_the_general_hint() -> None:
    project = _frame2d(
        [_node(1, fix=FIXED), _node(2, 3), _node(3, 20, fix=FIXED), _node(4, 23)],
        [_beam(1, 1, 2), _beam(2, 3, 4)],
    )
    finding = _only(check_model(project), "disconnected_parts")
    assert "missing" in finding.hint


def test_equal_dof_ties_two_parts_into_one() -> None:
    project = _frame2d(
        [_node(1, fix=FIXED), _node(2, 3), _node(3, 3), _node(4, 6, fix=FIXED)],
        [_beam(1, 1, 2), _beam(2, 3, 4)],
        mp_constraints=[EqualDOFConstraint(retained_node=2, constrained_node=3, dofs=(1, 2))],
    )
    report = check_model(project)
    assert report.part_count == 1
    assert report.is_clean, [f.summary() for f in report.findings]


# ──────────────────────────── mechanisms ────────────────────────────
def _square_truss(*, diagonal: bool, scale: float = 1.0) -> Project:
    elements = [_bar(1, 1, 2), _bar(2, 2, 3), _bar(3, 3, 4), _bar(4, 4, 1)]
    if diagonal:
        elements.append(_bar(5, 1, 3))
    return _truss2d(
        [
            _node(1, 0, 0, fix=PIN),
            _node(2, 4 * scale, 0, fix=ROLLER),
            _node(3, 4 * scale, 3 * scale),
            _node(4, 0, 3 * scale),
        ],
        elements,
    )


def test_a_square_of_bars_is_a_mechanism_and_a_diagonal_cures_it() -> None:
    loose = check_model(_square_truss(diagonal=False))
    finding = _only(loose, "mechanism")
    assert loose.mechanism_count == 1
    assert set(finding.node_ids) == {3, 4}  # the two free corners shear sideways
    assert "Ux" in finding.message

    braced = check_model(_square_truss(diagonal=True))
    assert braced.is_clean
    assert braced.mechanism_count == 0


def test_the_answer_does_not_depend_on_the_units_of_the_model() -> None:
    """Millimetres or metres: the same mechanism, the same count."""
    for scale in (1e-3, 1.0, 1e3):
        assert check_model(_square_truss(diagonal=False, scale=scale)).mechanism_count == 1
        assert check_model(_square_truss(diagonal=True, scale=scale)).mechanism_count == 0


def test_two_bars_in_a_line_leave_the_middle_node_free_to_move_sideways() -> None:
    project = _truss2d(
        [_node(1, 0, 0, fix=PIN), _node(2, 3, 0), _node(3, 6, 0, fix=PIN)],
        [_bar(1, 1, 2), _bar(2, 2, 3)],
    )
    finding = _only(check_model(project), "mechanism")
    assert finding.node_ids == (2,)
    assert "Uy" in finding.message


def test_a_beam_pinned_at_one_end_only_can_swing() -> None:
    project = _frame2d([_node(1, fix=PIN), _node(2, 4)], [_beam(1, 1, 2)])
    report = check_model(project)
    finding = _only(report, "mechanism")
    assert report.mechanism_count == 1
    assert set(finding.node_ids) == {1, 2}
    assert "Rz" in finding.message


def test_a_fixed_cantilever_and_a_pinned_beam_on_two_supports_are_stable() -> None:
    cantilever = _frame2d([_node(1, fix=FIXED), _node(2, 4)], [_beam(1, 1, 2)])
    simple = _frame2d(
        [_node(1, fix=PIN), _node(2, 4, fix=ROLLER)],
        [_beam(1, 1, 2)],
    )
    assert check_model(cantilever).is_clean
    assert check_model(simple).is_clean


def test_a_truss_modelled_with_free_rotations_says_to_restrain_them() -> None:
    """The model the runner used to reject at run time with a singular matrix."""
    project = _frame2d(
        [_node(1, 0, 0, fix=PIN), _node(2, 4, 0, fix=ROLLER), _node(3, 2, 3)],
        [_bar(1, 1, 2), _bar(2, 2, 3), _bar(3, 3, 1)],
    )
    report = check_model(project)
    finding = _only(report, "mechanism")
    assert report.mechanism_count == 3  # Rz at each of the three nodes
    assert set(finding.node_ids) == {1, 2, 3}
    assert "restrain" in finding.hint
    assert "ndf" in finding.hint


def test_a_beam_between_two_ball_joints_in_3d_can_spin_about_its_axis() -> None:
    project = _frame3d(
        [_node(1, 0, 0, 0, fix=BALL), _node(2, 4, 0, 0, fix=BALL)],
        [_beam(1, 1, 2)],
    )
    report = check_model(project)
    _only(report, "mechanism")
    assert report.mechanism_count == 1


def test_a_3d_cantilever_is_stable() -> None:
    project = _frame3d([_node(1, fix=FIXED), _node(2, 3, 2, 1)], [_beam(1, 1, 2)])
    assert check_model(project).is_clean


def test_a_zero_length_spring_that_leaves_a_dof_free_is_a_mechanism() -> None:
    def build(dofs: tuple[int, ...]) -> Project:
        return _frame2d(
            [_node(1, fix=FIXED), _node(2), _node(3, 3)],
            [
                ZeroLengthElement(id=1, nodes=(1, 2), material_ids=(1,), dofs=dofs),
                _beam(2, 2, 3),
            ],
        )

    assert check_model(build((1, 2, 3))).is_clean
    report = check_model(build((1,)))
    assert report.has_errors
    assert report.mechanism_count >= 1


def test_a_quad_needs_enough_support_to_stop_it_moving_as_a_body() -> None:
    quad = QuadElement(id=1, nodes=(1, 2, 3, 4), thickness=0.1, material_id=1)

    def build(fix_1: tuple, fix_2: tuple) -> Project:
        return _truss2d(
            [_node(1, fix=fix_1), _node(2, 1, fix=fix_2), _node(3, 1, 1), _node(4, 0, 1)],
            [quad],
        )

    assert check_model(build(PIN, ROLLER)).is_clean
    report = check_model(build(PIN, FREE))
    assert report.mechanism_count == 1  # it can still turn about the pin


def test_a_shell_held_by_translations_alone_can_still_rotate() -> None:
    shell = ShellMITC4Element(id=1, nodes=(1, 2, 3, 4), section_id=1)

    def build(fix: tuple) -> Project:
        return _frame3d(
            [_node(1, fix=fix), _node(2, 1), _node(3, 1, 1), _node(4, 0, 1)],
            [shell],
        )

    assert check_model(build(FIXED)).is_clean
    assert check_model(build(BALL)).mechanism_count == 3  # three rigid rotations


# ──────────────────────────── the check stays quiet on good models ────────────────────────────
def test_a_long_flexible_chain_is_not_mistaken_for_a_mechanism() -> None:
    """Many short members in a row make a flexible cantilever, not a mechanism."""
    count = 300
    nodes = [_node(1, fix=FIXED)] + [_node(i + 1, i * 0.01) for i in range(1, count + 1)]
    elements = [_beam(i, i, i + 1) for i in range(1, count + 1)]
    report = check_model(_frame2d(nodes, elements))
    assert report.is_clean, [f.summary() for f in report.findings]
    assert report.stability_checked


def test_members_of_wildly_different_lengths_are_not_a_mechanism() -> None:
    lengths = [1e-3, 5.0, 2e-3, 8.0, 1e-3]
    xs = [0.0]
    for length in lengths:
        xs.append(xs[-1] + length)
    nodes = [_node(1, xs[0], fix=FIXED)] + [_node(i + 1, x) for i, x in enumerate(xs[1:], start=1)]
    elements = [_beam(i, i, i + 1) for i in range(1, len(xs))]
    assert check_model(_frame2d(nodes, elements)).is_clean


def test_a_braced_3d_grid_is_stable_and_fast() -> None:
    n = 6
    nodes: list[Node] = []
    ids: dict[tuple[int, int, int], int] = {}
    for k in range(3):
        for j in range(n):
            for i in range(n):
                ids[(i, j, k)] = len(nodes) + 1
                nodes.append(
                    _node(len(nodes) + 1, i * 4.0, j * 4.0, k * 3.0, fix=FIXED if k == 0 else FREE)
                )
    elements: list = []
    for (i, j, k), nid in ids.items():
        for di, dj, dk in ((1, 0, 0), (0, 1, 0), (0, 0, 1)):
            other = ids.get((i + di, j + dj, k + dk))
            if other:
                elements.append(_beam(len(elements) + 1, nid, other))

    started = time.perf_counter()
    report = check_model(_frame3d(nodes, elements))
    elapsed = time.perf_counter() - started

    assert report.is_clean, [f.summary() for f in report.findings]
    assert elapsed < 10.0, f"stability check took {elapsed:.1f}s on {len(nodes)} nodes"


# ──────────────────────────── limits and switches ────────────────────────────
def test_a_part_above_the_dof_limit_is_skipped_with_a_note(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(MAX_DOF_ENV, "3")
    report = check_model(_portal())

    finding = _only(report, "stability_skipped")
    assert finding.severity is Severity.INFO
    assert not report.stability_checked
    assert report.is_clean  # information alone is not a problem


def test_the_stability_test_can_be_switched_off() -> None:
    report = check_model(_square_truss(diagonal=False), check_stability=False)
    assert report.findings == ()
    assert not report.stability_checked


def test_findings_come_errors_first_and_the_summary_counts_them() -> None:
    project = _portal()
    project.nodes.append(_node(9, 7, 7, fix=FIXED))  # a warning
    project.nodes.append(_node(10, 8, 8))  # an error
    report = check_model(project)

    severities = [f.severity for f in report.findings]
    assert severities == sorted(
        severities, key=lambda s: ["error", "warning", "info"].index(s.value)
    )
    assert severities[0] is Severity.ERROR
    assert report.summary() == "Model check: 1 error, 1 warning."


def test_the_check_never_changes_the_project() -> None:
    project = _square_truss(diagonal=False)
    before = project.model_dump_json()
    check_model(project)
    assert project.model_dump_json() == before
