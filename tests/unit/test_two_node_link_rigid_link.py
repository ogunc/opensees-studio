"""twoNodeLink element and rigidLink beam tie: schema, validation (T7), the
commands the runner writes, the constraint handler choice and the file round trip.
No openseespy: the runner gets a ``MagicMock`` ops module."""

from __future__ import annotations

import contextlib
from unittest.mock import MagicMock, call

import pytest
from pydantic import ValidationError

from opensees_studio.core import (
    ElasticUniaxial,
    EqualDOFConstraint,
    LinearTimeSeries,
    ModalCase,
    NodalLoad,
    Node,
    PlainLoadPattern,
    Project,
    RigidLinkConstraint,
    StaticCase,
    TransientCase,
    TwoNodeLinkElement,
)
from opensees_studio.services.opensees_runner import OpenSeesRunner


def _link(**kw: object) -> TwoNodeLinkElement:
    args: dict[str, object] = {
        "id": 1,
        "nodes": (1, 2),
        "material_ids": (1, 2, 3),
        "dofs": (1, 2, 3),
    }
    args.update(kw)
    return TwoNodeLinkElement(**args)  # type: ignore[arg-type]


def _project(link: TwoNodeLinkElement | None = None, ties: list | None = None) -> Project:  # type: ignore[type-arg]
    return Project(
        ndm=3,
        ndf=6,
        nodes=[
            Node(id=1, coords=(0, 0, 0), restraint=(True,) * 6),
            Node(id=2, coords=(0, 0, 0.2)),
            Node(id=3, coords=(0.3, 0.1, 0.25)),
        ],
        materials=[ElasticUniaxial(id=k, E=100.0 * k) for k in (1, 2, 3)],
        elements=[link if link is not None else _link()],
        mp_constraints=ties or [],
        time_series=[LinearTimeSeries(id=1)],
        load_patterns=[
            PlainLoadPattern(
                id=1,
                time_series_id=1,
                nodal_loads=[NodalLoad(node_id=2, forces=(1, 0, 0, 0, 0, 0))],
            )
        ],
        analyses=[
            StaticCase(id=1, pattern_ids=[1]),
            ModalCase(id=2, n_modes=1),
            TransientCase(id=3, dt=0.01, n_steps=1, constraints="Penalty"),
        ],
    )


def _errors(project: Project) -> str:
    with pytest.raises(ValueError) as exc:
        project.validate_references()
    return str(exc.value)


# ───────────────────────── T7: element validation ─────────────────────────
@pytest.mark.parametrize(
    ("kw", "message"),
    [
        ({"material_ids": (1, 2)}, "2 materials for 3 directions"),
        ({"dofs": (1, 2, 7)}, "directions must be 1..6"),
        ({"dofs": (0, 1, 2)}, "directions must be 1..6"),
        ({"dofs": (1, 2, 2)}, "repeated direction"),
        ({"shear_dist": (0.5, 1.5)}, "shear_dist ratios must lie in [0, 1]"),
        ({"shear_dist": (-0.1, 0.5)}, "shear_dist ratios must lie in [0, 1]"),
        ({"orient_y": (0.0, 0.0, 0.0)}, "orient_y must be non-zero"),
        ({"orient_y": (1, 0, 0), "orient_x": (0, 0, 0)}, "orient_x must be non-zero"),
        ({"orient_x": (0, 0, 1)}, "orient_x needs orient_y"),
    ],
)
def test_link_field_errors(kw: dict[str, object], message: str) -> None:
    with pytest.raises(ValidationError, match=message.replace("[", r"\[").replace("]", r"\]")):
        _link(**kw)


def test_link_extra_keys_are_refused() -> None:
    with pytest.raises(ValidationError):
        _link(p_delta=(0.5, 0.5))
    with pytest.raises(ValidationError):
        _link(mass=1.0)


def test_link_coincident_nodes_refused() -> None:
    p = _project(_link(nodes=(1, 2)))
    p.nodes[1] = Node(id=2, coords=(0, 0, 0))
    assert "are at the same coordinates" in _errors(p)


@pytest.mark.parametrize(
    "orient_x",
    [(1e-6, 0, 1), (0, 0, -1), (1, 0, 0)],
    ids=["off-by-1e-6", "anti-parallel", "perpendicular"],
)
def test_link_orient_x_must_follow_i_to_j(orient_x: tuple[float, float, float]) -> None:
    p = _project(_link(orient_x=orient_x, orient_y=(0, 1, 0)))
    assert "is not parallel to node 1 -> node 2" in _errors(p)


def test_link_orient_x_within_tolerance_is_accepted() -> None:
    _project(_link(orient_x=(1e-11, 0, 3.0), orient_y=(1, 0, 0))).validate_references()


def test_link_orient_y_along_x_refused() -> None:
    assert "is parallel to the local x axis" in _errors(_project(_link(orient_y=(0, 0, 2))))


def test_link_direction_above_ndf_refused() -> None:
    p = Project(
        ndm=2,
        ndf=3,
        nodes=[Node(id=1, coords=(0, 0, 0)), Node(id=2, coords=(0, 1, 0))],
        materials=[ElasticUniaxial(id=1, E=1.0)],
        elements=[TwoNodeLinkElement(id=1, nodes=(1, 2), material_ids=(1,), dofs=(5,))],
    )
    assert "direction above ndf=3" in _errors(p)


# ───────────────────────── T7: rigid link validation ─────────────────────────
def test_rigid_link_self_tie_refused() -> None:
    p = _project(ties=[RigidLinkConstraint(retained_node=2, constrained_node=2)])
    assert "a node may not be tied to itself" in _errors(p)


@pytest.mark.parametrize(
    "second",
    [
        RigidLinkConstraint(retained_node=1, constrained_node=3),
        EqualDOFConstraint(retained_node=1, constrained_node=3, dofs=(1,)),
    ],
    ids=["rigid", "equalDOF"],
)
def test_rigid_link_constrained_twice_refused(second: object) -> None:
    p = _project(ties=[RigidLinkConstraint(retained_node=2, constrained_node=3), second])
    assert "constrained node of more than one tie" in _errors(p)


def test_rigid_link_fixity_on_constrained_node_refused() -> None:
    p = _project(ties=[RigidLinkConstraint(retained_node=2, constrained_node=3)])
    p.nodes[2] = Node(id=3, coords=(0.3, 0.1, 0.25), restraint=(False,) * 5 + (True,))
    assert "has a fixity on a tied DOF" in _errors(p)


def test_rigid_link_needs_rotational_dof() -> None:
    p = Project(
        ndm=3,
        ndf=3,
        nodes=[Node(id=1, coords=(0, 0, 0)), Node(id=2, coords=(1, 0, 0))],
        mp_constraints=[RigidLinkConstraint(retained_node=1, constrained_node=2)],
    )
    assert "needs rotational DOF" in _errors(p)


def test_rigid_link_missing_node_refused() -> None:
    p = _project(ties=[RigidLinkConstraint(retained_node=2, constrained_node=9)])
    assert "missing constrained node 9" in _errors(p)


def test_equal_dof_alone_keeps_its_rules() -> None:
    """Two equalDOF ties on one constrained node stay valid (no rigid link)."""
    _project(
        ties=[
            EqualDOFConstraint(retained_node=1, constrained_node=3, dofs=(1,)),
            EqualDOFConstraint(retained_node=2, constrained_node=3, dofs=(2,)),
        ]
    ).validate_references()


# ───────────────────────── written commands ─────────────────────────
def _built(project: Project) -> MagicMock:
    ops = MagicMock()
    OpenSeesRunner(project, ops_module=ops).build()
    return ops


def test_link_command_default() -> None:
    ops = _built(_project())
    assert call.element("twoNodeLink", 1, 1, 2, "-mat", 1, 2, 3, "-dir", 1, 2, 3) in ops.mock_calls


def test_link_command_all_options() -> None:
    link = _link(
        orient_x=(0, 0, 1), orient_y=(0.6, 0.8, 0), shear_dist=(0.25, 1.0), do_rayleigh=True
    )
    ops = _built(_project(link))
    assert (
        call.element(
            "twoNodeLink",
            1,
            1,
            2,
            "-mat",
            1,
            2,
            3,
            "-dir",
            1,
            2,
            3,
            "-orient",
            0,
            0,
            1,
            0.6,
            0.8,
            0,
            "-shearDist",
            0.25,
            1.0,
            "-doRayleigh",
        )
        in ops.mock_calls
    )


def test_link_command_orient_y_only_writes_x_from_i_to_j() -> None:
    link = _link(orient_y=(1, 0, 0), shear_dist=(0.5, 0.5))
    ops = _built(_project(link))
    args = ("twoNodeLink", 1, 1, 2, "-mat", 1, 2, 3, "-dir", 1, 2, 3, "-orient")
    assert call.element(*args, 0.0, 0.0, 0.2, 1, 0, 0, "-shearDist", 0.5, 0.5) in ops.mock_calls


def test_link_command_2d_takes_one_shear_ratio() -> None:
    p = Project(
        ndm=2,
        ndf=3,
        nodes=[Node(id=1, coords=(0, 0, 0)), Node(id=2, coords=(0, 1, 0))],
        materials=[ElasticUniaxial(id=1, E=1.0)],
        elements=[
            TwoNodeLinkElement(
                id=1, nodes=(1, 2), material_ids=(1,), dofs=(2,), shear_dist=(0.3, 0.7)
            )
        ],
    )
    ops = _built(p)
    assert (
        call.element("twoNodeLink", 1, 1, 2, "-mat", 1, "-dir", 2, "-shearDist", 0.3)
        in ops.mock_calls
    )


def test_rigid_link_command() -> None:
    ops = _built(_project(ties=[RigidLinkConstraint(retained_node=2, constrained_node=3)]))
    assert call.rigidLink("beam", 2, 3) in ops.mock_calls
    assert not [c for c in ops.mock_calls if c[0] == "equalDOF"]


# ───────────────────────── constraint handler ─────────────────────────
def _handlers(project: Project, case_id: int) -> list[str]:
    ops = MagicMock()
    ops.analyze.return_value = 0
    ops.getTime.return_value = 1.0
    ops.eleResponse.return_value = [0.0, 0.0, 0.0]
    ops.eleForce.return_value = [0.0] * 12
    ops.nodeDisp.return_value = 0.0
    ops.nodeReaction.return_value = 0.0
    ops.nodeEigenvector.return_value = 1.0
    ops.eigen.return_value = [4.0]
    runner = OpenSeesRunner(project, ops_module=ops)
    # Node 3 carries no element in the untied model; the handler is what is tested.
    runner._check_dof_coverage = lambda: None  # type: ignore[method-assign]
    case = next(c for c in project.analyses if c.id == case_id)
    # A mock solver cannot finish every path; the handler calls come first.
    with contextlib.suppress(Exception):
        runner.run(case)
    return [c.args[0] for c in ops.mock_calls if c[0] == "constraints"]


@pytest.mark.parametrize(
    ("case_id", "without", "with_tie"),
    [
        (1, ["Plain"], ["Transformation"]),
        (2, [], ["Transformation"]),
        (3, ["Penalty"], ["Transformation"]),
    ],
    ids=["static", "modal", "transient"],
)
def test_handler_switches_only_with_a_rigid_link(
    case_id: int, without: list[str], with_tie: list[str]
) -> None:
    assert _handlers(_project(), case_id)[: len(without)] == without
    assert not _handlers(_project(), case_id)[len(without) :]
    tied = _project(ties=[RigidLinkConstraint(retained_node=2, constrained_node=3)])
    assert _handlers(tied, case_id)[:1] == with_tie
    assert set(_handlers(tied, case_id)) == {"Transformation"}


def test_equal_dof_does_not_switch_the_handler() -> None:
    p = _project(ties=[EqualDOFConstraint(retained_node=2, constrained_node=3, dofs=(1,))])
    assert _handlers(p, 1) == ["Plain"]
    assert not p.has_rigid_links


# ───────────────────────── file round trip ─────────────────────────
def test_round_trip_keeps_both_kinds() -> None:
    link = _link(orient_y=(1, 0, 0), shear_dist=(0.5, 0.25), do_rayleigh=True)
    ties = [
        RigidLinkConstraint(retained_node=2, constrained_node=3),
        EqualDOFConstraint(retained_node=1, constrained_node=2, dofs=(1, 2)),
    ]
    p = _project(link, ties)
    again = Project.model_validate_json(p.model_dump_json())
    assert again == p
    assert isinstance(again.mp_constraints[0], RigidLinkConstraint)
    assert isinstance(again.mp_constraints[1], EqualDOFConstraint)
    assert isinstance(again.elements[0], TwoNodeLinkElement)


def test_equal_dof_dump_unchanged() -> None:
    eq = EqualDOFConstraint(retained_node=1, constrained_node=2, dofs=(1,))
    assert eq.model_dump() == {"retained_node": 1, "constrained_node": 2, "dofs": (1,)}
    data = {"retained_node": 1, "constrained_node": 2, "dofs": [1]}
    loaded = Project.model_validate({"mp_constraints": [data], "nodes": []})
    assert isinstance(loaded.mp_constraints[0], EqualDOFConstraint)
    assert RigidLinkConstraint(retained_node=1, constrained_node=2).model_dump() == {
        "type": "RigidLinkBeam",
        "retained_node": 1,
        "constrained_node": 2,
    }
