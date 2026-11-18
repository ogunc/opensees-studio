"""Support reactions: the rows the table shows and the vectors the viewport draws."""

from __future__ import annotations

import numpy as np

from opensees_studio.core import Node, Project
from opensees_studio.core.reactions import (
    largest_force,
    largest_moment,
    reaction_rows,
)


def _project() -> Project:
    return Project(
        nodes=[
            Node(id=1, coords=(0.0, 0.0, 0.0), restraint=(True,) * 6),
            Node(id=2, coords=(3.0, 0.0, 0.0), restraint=(True,) * 6),
            Node(id=3, coords=(6.0, 0.0, 0.0)),
        ]
    )


def test_a_six_wide_reaction_splits_into_forces_and_moments() -> None:
    rows = reaction_rows(_project(), {1: np.array([1.0, -2.0, 3.0, 4.0, -5.0, 6.0])})

    assert len(rows) == 1
    assert rows[0].node_id == 1
    assert rows[0].forces == (1.0, -2.0, 3.0)
    assert rows[0].moments == (4.0, -5.0, 6.0)
    assert rows[0].magnitude == np.linalg.norm([1.0, -2.0, 3.0])


def test_a_2d_reaction_maps_to_the_xz_plane() -> None:
    """2D storage is (Ux, Uz, Ry): Fz and Mz, with Fy and Mx at zero."""
    rows = reaction_rows(_project(), {1: np.array([7.0, -8.0, 9.0])})

    assert rows[0].forces == (7.0, 0.0, -8.0)
    assert rows[0].moments == (0.0, 0.0, 9.0)


def test_a_per_step_reaction_reads_the_last_step() -> None:
    steps = np.array([[1.0, 0.0, 0.0, 0.0, 0.0, 0.0], [5.0, 0.0, 0.0, 0.0, 0.0, 0.0]])

    rows = reaction_rows(_project(), {1: steps})

    assert rows[0].forces == (5.0, 0.0, 0.0)


def test_free_nodes_and_missing_entries_are_skipped() -> None:
    rows = reaction_rows(_project(), {1: np.zeros(6), 3: np.zeros(6)})

    assert [row.node_id for row in rows] == [1, 3], "project order, no phantom rows"


def test_a_reaction_of_the_wrong_width_is_ignored() -> None:
    assert reaction_rows(_project(), {1: np.zeros(2)}) == []


def test_the_largest_values_are_what_the_scale_is_built_from() -> None:
    rows = reaction_rows(
        _project(),
        {
            1: np.array([3.0, 4.0, 0.0, 0.0, 0.0, 1.0]),
            2: np.array([1.0, 0.0, 0.0, 0.0, 0.0, 6.0]),
        },
    )

    assert largest_force(rows) == 5.0
    assert largest_moment(rows) == 6.0


def test_no_rows_report_zero_scale() -> None:
    assert largest_force([]) == 0.0
    assert largest_moment([]) == 0.0
