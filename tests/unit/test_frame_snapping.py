"""Object-snap maths on frame members (no viewport needed)."""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("PySide6")

from opensees_studio.views.canvas3d.snapping import (
    SnapMode,
    frame_snap_candidates,
)

A_WORLD = np.array([[0.0, 0.0, 0.0]])
B_WORLD = np.array([[10.0, 0.0, 0.0]])
A_SCREEN = np.array([[0.0, 100.0]])
B_SCREEN = np.array([[100.0, 100.0]])


def _snap(
    cursor: tuple[float, float],
    modes: set[SnapMode],
    reference: tuple[float, float, float] | None = None,
    tolerance: float = 15.0,
):
    return frame_snap_candidates(
        [7],
        A_WORLD,
        B_WORLD,
        A_SCREEN,
        B_SCREEN,
        cursor,
        modes,
        reference,
        tolerance,
    )


def test_midpoint_is_preferred_over_the_nearest_point_at_the_same_place() -> None:
    snap = _snap((50.0, 100.0), {SnapMode.MIDPOINT, SnapMode.ON_ELEMENT})
    assert snap is not None
    assert snap.element_id == 7
    assert snap.mode is SnapMode.MIDPOINT
    assert snap.point == pytest.approx((5.0, 0.0, 0.0))


def test_on_element_snaps_to_the_nearest_point_on_the_bar() -> None:
    snap = _snap((25.0, 100.0), {SnapMode.ON_ELEMENT})
    assert snap is not None
    assert snap.mode is SnapMode.ON_ELEMENT
    assert snap.point == pytest.approx((2.5, 0.0, 0.0))


def test_perpendicular_uses_the_reference_point_and_wins_a_tie() -> None:
    snap = _snap(
        (20.0, 100.0),
        {SnapMode.MIDPOINT, SnapMode.PERPENDICULAR, SnapMode.ON_ELEMENT},
        reference=(2.0, 5.0, 0.0),
    )
    assert snap is not None
    assert snap.mode is SnapMode.PERPENDICULAR
    assert snap.point == pytest.approx((2.0, 0.0, 0.0))


def test_perpendicular_is_not_offered_when_its_foot_lies_outside_the_bar() -> None:
    snap = _snap(
        (0.0, 100.0),
        {SnapMode.PERPENDICULAR, SnapMode.ON_ELEMENT},
        reference=(-5.0, 5.0, 0.0),
    )
    assert snap is not None
    assert snap.mode is SnapMode.ON_ELEMENT
    assert snap.point == pytest.approx((0.0, 0.0, 0.0))


def test_no_snap_outside_the_aperture() -> None:
    assert _snap((50.0, 130.0), {SnapMode.MIDPOINT, SnapMode.ON_ELEMENT}) is None


def test_no_snap_when_every_mode_is_off() -> None:
    assert _snap((50.0, 100.0), set()) is None
