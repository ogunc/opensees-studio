"""Influence lines: the stops of the moving load, the vehicle envelope, the case, the store."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from opensees_studio.core import (
    ElasticBeamColumn,
    ElasticSection,
    InfluenceLineCase,
    Node,
    Project,
)
from opensees_studio.core.analysis import Axle
from opensees_studio.core.influence import (
    InfluencePathError,
    influence_positions,
    moving_load_envelope,
    path_length,
)
from opensees_studio.services import load_project, save_project
from opensees_studio.services.influence import influence_line
from opensees_studio.services.result_store import load_results, write_results
from opensees_studio.services.results import InfluenceLineResults


def _chain(coords: list[tuple[float, float]], members: list[tuple[int, int]]) -> Project:
    return Project(
        ndm=2,
        ndf=3,
        nodes=[Node(id=k + 1, coords=(x, 0.0, z)) for k, (x, z) in enumerate(coords)],
        sections=[ElasticSection(id=1, E=1.0, A=1.0, Iz=1.0)],
        elements=[
            ElasticBeamColumn(id=k + 1, nodes=ends, section_id=1) for k, ends in enumerate(members)
        ],
    )


# ──────────────────────────── stops ────────────────────────────
def test_stops_walk_the_chain_and_share_joints() -> None:
    project = _chain([(0, 0), (4, 0), (10, 0)], [(1, 2), (2, 3)])
    stops = influence_positions(project, [1, 2], 2)
    assert [s.distance for s in stops] == [0.0, 2.0, 4.0, 7.0, 10.0]
    assert [s.node_id for s in stops] == [1, None, 2, None, 3]
    assert [(s.element_id, s.fraction) for s in stops] == [
        (1, 0.0),
        (1, 0.5),
        (1, 1.0),
        (2, 0.5),
        (2, 1.0),
    ]
    assert path_length(stops) == 10.0


def test_a_member_walked_backwards_counts_from_its_end_j() -> None:
    # Member 2 is drawn 3 -> 2: walking from joint 2 it runs from its end j.
    project = _chain([(0, 0), (4, 0), (10, 0)], [(1, 2), (3, 2)])
    stops = influence_positions(project, [1, 2], 4)
    second = [s for s in stops if s.element_id == 2]
    assert [s.fraction for s in second] == [0.75, 0.5, 0.25, 0.0]
    # A path given end-first starts at the joint the first member does not share.
    reverse = influence_positions(project, [2, 1], 1)
    assert [s.node_id for s in reverse] == [3, 2, 1]


def test_broken_paths_are_refused() -> None:
    project = _chain([(0, 0), (4, 0), (10, 0), (12, 0)], [(1, 2), (3, 4)])
    with pytest.raises(InfluencePathError, match="does not touch joint"):
        influence_positions(project, [1, 2], 2)
    with pytest.raises(InfluencePathError, match="does not exist"):
        influence_positions(project, [9], 2)


# ──────────────────────────── vehicles ────────────────────────────
def _midspan_moment(length: float, n: int = 20) -> tuple[np.ndarray, np.ndarray]:
    """Influence line of the midspan moment of a simply supported span."""
    x = np.linspace(0.0, length, n + 1)
    return x, np.where(x <= length / 2, x / 2, (length - x) / 2)


def test_one_axle_gives_the_peak_of_the_line() -> None:
    x, line = _midspan_moment(10.0)
    found = moving_load_envelope(x, line, [Axle(load=3.0)])
    assert found.maximum == pytest.approx(3.0 * 10.0 / 4)
    assert found.front_at_maximum == pytest.approx(5.0)
    assert found.minimum == pytest.approx(0.0)


def test_two_axles_on_a_simple_span() -> None:
    """Two equal axles P a apart: the midspan moment peaks at P (L - a) / 2."""
    x, line = _midspan_moment(10.0)
    found = moving_load_envelope(x, line, [Axle(load=1.0), Axle(load=1.0, offset=2.0)])
    assert found.maximum == pytest.approx((10.0 - 2.0) / 2)


def test_an_unequal_vehicle_is_worse_one_way() -> None:
    # A heavy rear axle on a line that rises to the end of the path. Forward, the
    # light front axle leads: the heavy one reaches the peak only once the light one
    # has left (4.0). Backward, the heavy axle sits on the peak with the light one
    # 3 m before it, still on the path: 4 + 0.7.
    x = np.linspace(0.0, 10.0, 11)
    line = x / 10.0
    found = moving_load_envelope(x, line, [Axle(load=1.0), Axle(load=4.0, offset=3.0)])
    assert found.maximum == pytest.approx(4.0 + 1.0 * 0.7)
    assert found.reversed_at_maximum is True
    assert found.front_at_maximum == pytest.approx(7.0)


# ──────────────────────────── the case and the store ────────────────────────────
def test_the_case_saves_compactly_and_round_trips(tmp_path: Path) -> None:
    project = _chain([(0, 0), (4, 0)], [(1, 2)])
    project.analyses.append(InfluenceLineCase(id=1, name="IL", path=[1]))
    dumped = project.analyses[0].model_dump(mode="json")
    assert "axles" not in dumped
    project.analyses.append(
        InfluenceLineCase(
            id=2, name="Truck", path=[1], axles=[Axle(load=35.0), Axle(load=145.0, offset=4.3)]
        )
    )
    path = save_project(project, tmp_path / "il.osmodel")
    assert load_project(path).analyses == project.analyses
    with pytest.raises(ValueError, match="cannot be zero"):
        InfluenceLineCase(id=3, name="x", path=[1], load=0.0)


def _results() -> InfluenceLineResults:
    return InfluenceLineResults(
        case_id=7,
        case_name="IL",
        distances=np.array([0.0, 5.0, 10.0]),
        element_ids=np.array([1, 1, 1]),
        fractions=np.array([0.0, 0.5, 1.0]),
        load=-2.0,
        node_disp={1: np.zeros((3, 3)), 2: np.array([[0, 0, 0], [0, -4.0, 0], [0, 0, 0]])},
        node_reaction={1: np.array([[0, 2.0, 0], [0, 1.0, 0], [0, 0, 0]])},
        element_forces={1: np.arange(18, dtype=float).reshape(3, 6)},
    )


def test_the_store_keeps_an_influence_line(tmp_path: Path) -> None:
    entry = write_results(_results(), tmp_path)
    assert entry["result_type"] == "InfluenceLineResults"
    back = load_results(entry, tmp_path)
    assert isinstance(back, InfluenceLineResults)
    assert back.load == -2.0 and back.n_steps == 3
    np.testing.assert_array_equal(back.fractions, [0.0, 0.5, 1.0])
    np.testing.assert_array_equal(back.element_forces[1], _results().element_forces[1])


def test_lines_are_per_unit_load_and_in_the_diagram_sign() -> None:
    project = _chain([(0, 0), (10, 0)], [(1, 2)])
    results = _results()
    reaction = influence_line(project, results, "reaction", 1, "Uz")
    np.testing.assert_allclose(reaction, [1.0, 0.5, 0.0])  # divided by |load| = 2
    disp = influence_line(project, results, "displacement", 2, "Uz")
    np.testing.assert_allclose(disp, [0.0, -2.0, 0.0])
    moment_j = influence_line(project, results, "force", 1, "M3", end="j")
    np.testing.assert_allclose(moment_j, -results.element_forces[1][:, 5] / 2)
    with pytest.raises(KeyError, match="not a force of a 2D member"):
        influence_line(project, results, "force", 1, "M2")
    with pytest.raises(KeyError, match="not a DOF"):
        influence_line(project, results, "reaction", 1, "Uy")
