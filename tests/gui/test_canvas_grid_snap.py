"""Tests for the canvas-side pixel-space grid snap.

We verify the snap LOGIC by stubbing the world→screen projection so the
tests don't need a live VTK renderer. The real canvas composes these
pieces during a click.
"""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("PySide6")

from opensees_studio.core import (
    CoordinateGridSystem,
    CoordinateSystem,
    GridSystem,
    Project,
    make_grid_lines,
)


# ────────────────────── logic helpers (no VTK) ──────────────────────
def _nearest_snap(
    cx: float,
    cy: float,
    world_pts: np.ndarray,
    screen_pts: np.ndarray,
    tol_px: float,
) -> tuple[float, float, float] | None:
    """Mimics ModelCanvas._nearest_grid_intersection_px with pre-projected data."""
    if len(world_pts) == 0:
        return None
    d2 = (screen_pts[:, 0] - cx) ** 2 + (screen_pts[:, 1] - cy) ** 2
    idx = int(np.argmin(d2))
    if d2[idx] <= tol_px**2:
        return tuple(float(v) for v in world_pts[idx])  # type: ignore[return-value]
    return None


def test_snap_commits_when_click_is_within_tolerance() -> None:
    world = np.array([[0, 0, 0], [3, 0, 0], [3, 4, 0]], dtype=float)
    # Project as if they mapped to these screen pixels.
    screen = np.array([[100, 100], [300, 100], [300, 250]], dtype=float)
    # Click 10 pixels away from intersection #1 (at 300, 100).
    snapped = _nearest_snap(306, 108, world, screen, tol_px=15.0)
    assert snapped == (3.0, 0.0, 0.0)


def test_snap_rejects_when_click_is_beyond_tolerance() -> None:
    world = np.array([[0, 0, 0], [3, 0, 0]], dtype=float)
    screen = np.array([[100, 100], [300, 100]], dtype=float)
    # Click dead centre between the two pixels (200, 100) — 100 px away
    # from each, well beyond tol=15 px.
    snapped = _nearest_snap(200, 100, world, screen, tol_px=15.0)
    assert snapped is None


def test_snap_rejects_on_empty_grid() -> None:
    assert _nearest_snap(100, 100, np.empty((0, 3)), np.empty((0, 2)), 15.0) is None


# ────────────────── project ↔ intersections plumbing ─────────────────
def test_grid_intersections_world_includes_all_visible_systems(qtbot) -> None:  # type: ignore[no-untyped-def]
    """ModelCanvas._grid_intersections_world combines every visible system's
    intersections (transformed by that system's origin/rotation)."""
    from opensees_studio.views.canvas3d.model_canvas import ModelCanvas

    canvas = ModelCanvas()
    qtbot.addWidget(canvas)

    p = Project(
        coord_systems=[
            CoordinateGridSystem(
                name="Global",
                grid=GridSystem(
                    x_grid_lines=make_grid_lines("X", [0.0, 3.0]),
                    y_grid_lines=make_grid_lines("Y", [0.0]),
                    z_grid_lines=make_grid_lines("Z", [0.0]),
                ),
            ),
            CoordinateGridSystem(
                name="Floor2",
                coord=CoordinateSystem(origin=(0, 0, 3)),
                grid=GridSystem(
                    x_grid_lines=make_grid_lines("X", [0.0, 3.0]),
                    y_grid_lines=make_grid_lines("Y", [0.0]),
                    z_grid_lines=make_grid_lines("Z", [0.0]),
                ),
            ),
        ],
    )
    canvas.show_project(p)
    pts = canvas._grid_intersections_world()
    assert pts is not None
    # 2 X × 1 Y × 1 Z = 2 from each system; 4 total.
    assert pts.shape == (4, 3)
    # Floor2 intersections are at z=3.
    zs = sorted(set(float(z) for z in pts[:, 2]))
    assert zs == [0.0, 3.0]


def test_grid_intersections_world_returns_none_without_grid(qtbot) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.views.canvas3d.model_canvas import ModelCanvas

    canvas = ModelCanvas()
    qtbot.addWidget(canvas)
    canvas.show_project(Project())  # default: Global system with no grid lines
    assert canvas._grid_intersections_world() is None


def test_hide_all_suppresses_intersections(qtbot) -> None:  # type: ignore[no-untyped-def]
    """A system with ``hide_all=True`` must not contribute snap targets."""
    from opensees_studio.views.canvas3d.model_canvas import ModelCanvas

    canvas = ModelCanvas()
    qtbot.addWidget(canvas)

    p = Project(
        coord_systems=[
            CoordinateGridSystem(
                name="Global",
                grid=GridSystem(
                    x_grid_lines=make_grid_lines("X", [0.0, 3.0]),
                    y_grid_lines=make_grid_lines("Y", [0.0]),
                    z_grid_lines=make_grid_lines("Z", [0.0]),
                    hide_all=True,
                ),
            ),
        ],
    )
    canvas.show_project(p)
    assert canvas._grid_intersections_world() is None


# ──────────────────────── hover snap + radius sizing ──────────────────────
def test_hover_snap_marker_round_trips(qtbot) -> None:  # type: ignore[no-untyped-def]
    """set_hover_snap(pt) creates an actor; passing None removes it."""
    from opensees_studio.views.canvas3d.model_canvas import ModelCanvas

    canvas = ModelCanvas()
    qtbot.addWidget(canvas)
    canvas.show_project(
        Project(
            coord_systems=[
                CoordinateGridSystem(
                    name="Global",
                    grid=GridSystem(
                        x_grid_lines=make_grid_lines("X", [0.0, 3.0]),
                        y_grid_lines=make_grid_lines("Y", [0.0, 4.0]),
                        z_grid_lines=make_grid_lines("Z", [0.0]),
                    ),
                ),
            ],
        )
    )
    r = canvas._renderer
    assert r._hover_actor is None
    r.set_hover_snap((3.0, 0.0, 0.0))
    assert r._hover_actor is not None
    r.set_hover_snap(None)
    assert r._hover_actor is None


def test_snap_preview_flag_clears_marker(qtbot) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.views.canvas3d.model_canvas import ModelCanvas

    canvas = ModelCanvas()
    qtbot.addWidget(canvas)
    canvas.show_project(
        Project(
            coord_systems=[
                CoordinateGridSystem(
                    name="Global",
                    grid=GridSystem(
                        x_grid_lines=make_grid_lines("X", [0.0]),
                        y_grid_lines=make_grid_lines("Y", [0.0]),
                        z_grid_lines=make_grid_lines("Z", [0.0]),
                    ),
                ),
            ],
        )
    )
    canvas.set_snap_preview_enabled(True)
    canvas._renderer.set_hover_snap((0.0, 0.0, 0.0))
    assert canvas._renderer._hover_actor is not None
    canvas.set_snap_preview_enabled(False)
    assert canvas._renderer._hover_actor is None


# ──────────────────────── frame picking (point-to-segment) ────────────────
def _pt_to_segment_d2(p: np.ndarray, a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Vectorised point-to-segment squared distance, used to verify logic."""
    ab = b - a
    ab_sq = (ab**2).sum(axis=1)
    ab_sq = np.where(ab_sq == 0, 1.0, ab_sq)
    pa = p - a
    t = (pa * ab).sum(axis=1) / ab_sq
    t = np.clip(t, 0.0, 1.0)
    closest = a + t[:, None] * ab
    return ((p - closest) ** 2).sum(axis=1)


def test_point_to_segment_midpoint_hit() -> None:
    """A click at the midpoint of a long frame must match — the old midpoint-
    only test already passed; sanity check before end-hit tests."""
    p = np.array([50.0, 50.0])
    a = np.array([[0.0, 50.0]])
    b = np.array([[100.0, 50.0]])
    d2 = _pt_to_segment_d2(p, a, b)
    assert d2[0] == pytest.approx(0.0)


def test_point_to_segment_endpoint_hit() -> None:
    """A click near an endpoint must also hit — the bug fix this test guards."""
    p = np.array([1.0, 51.0])  # 1 px off node-a on a horizontal frame
    a = np.array([[0.0, 50.0]])
    b = np.array([[100.0, 50.0]])
    d2 = _pt_to_segment_d2(p, a, b)
    assert d2[0] <= 2.0**2  # well inside a 5-pixel test tolerance


def test_point_to_segment_orthogonal_miss() -> None:
    """Clicking far from a short frame must produce a large distance."""
    p = np.array([50.0, 200.0])
    a = np.array([[0.0, 50.0]])
    b = np.array([[10.0, 50.0]])  # short frame at (0..10, 50)
    d2 = _pt_to_segment_d2(p, a, b)
    # Closest point is (10, 50), distance ≈ sqrt(40² + 150²) ≈ 155
    assert d2[0] > 150.0**2


def test_single_node_radius_uses_grid_extent(qtbot) -> None:  # type: ignore[no-untyped-def]
    """With a single node placed, the sphere radius must scale with the
    grid bounds so the node remains visible (regression guard)."""
    from opensees_studio.core import Node
    from opensees_studio.views.canvas3d.model_canvas import ModelCanvas

    canvas = ModelCanvas()
    qtbot.addWidget(canvas)
    p = Project(
        nodes=[Node(id=1, coords=(0.0, 0.0, 0.0))],
        coord_systems=[
            CoordinateGridSystem(
                name="Global",
                grid=GridSystem(
                    x_grid_lines=make_grid_lines("X", [0.0, 10.0]),
                    y_grid_lines=make_grid_lines("Y", [0.0, 10.0]),
                    z_grid_lines=make_grid_lines("Z", [0.0]),
                ),
            ),
        ],
    )
    canvas.show_project(p)
    r = canvas._renderer._scene_node_radius()
    # Grid diagonal = sqrt(10² + 10²) ≈ 14.14. Radius ≈ 0.008 · 14.14 ≈ 0.113.
    # Without the grid fix we'd get the 0.05 floor. Assert it's *above* the floor.
    assert r > 0.05


# ─────────────────── the working-plane fallback (0.0.7 fix) ───────────────────
def _sized_canvas(qtbot):  # type: ignore[no-untyped-def]
    from opensees_studio.views.canvas3d.model_canvas import ModelCanvas

    canvas = ModelCanvas()
    qtbot.addWidget(canvas)
    canvas.resize(800, 600)
    canvas.show()
    qtbot.waitExposed(canvas)
    return canvas


def _look_down_at(canvas, focus: tuple[float, float, float]) -> None:  # type: ignore[no-untyped-def]
    canvas.camera.position = (focus[0], focus[1], focus[2] + 10.0)
    canvas.camera.focal_point = focus
    canvas.camera.up = (0.0, 1.0, 0.0)
    canvas.render()


def test_a_click_meets_the_working_plane_when_no_intersection_is_close(qtbot) -> None:  # type: ignore[no-untyped-def]
    """The fix for 'it never draws anything': a click always has a point.

    With the camera looking down at Z = 0, the centre of the viewport is the
    focal point — whatever the grid does or does not offer.
    """
    canvas = _sized_canvas(qtbot)
    canvas.show_project(Project())  # empty grid: no intersection to snap to
    _look_down_at(canvas, (4.0, -2.0, 0.0))

    point = canvas.world_on_working_plane(canvas.width() / 2.0, canvas.height() / 2.0)

    assert point is not None
    assert point[0] == pytest.approx(4.0, abs=1e-6)
    assert point[1] == pytest.approx(-2.0, abs=1e-6)
    assert point[2] == pytest.approx(0.0, abs=1e-9)


def test_the_fallback_point_follows_the_active_level(qtbot) -> None:  # type: ignore[no-untyped-def]
    canvas = _sized_canvas(qtbot)
    canvas.show_project(Project())
    canvas.set_working_plane("XY", 3.5)  # a floor at Z = 3.5
    _look_down_at(canvas, (0.0, 0.0, 3.5))

    point = canvas.world_on_working_plane(canvas.width() / 2.0, canvas.height() / 2.0)

    assert point is not None
    assert point[2] == pytest.approx(3.5, abs=1e-9)


def test_an_empty_click_lands_on_the_nearest_grid_crossing(qtbot) -> None:  # type: ignore[no-untyped-def]
    """A grid exists, so the click belongs on it — SAP2000 draws on the grid.

    Landing at the pointer's own coordinates instead produced nodes at
    (-0.0074, 1.9923): geometry that reads as broken, not as free.
    """
    canvas = _sized_canvas(qtbot)
    # A grid nowhere near the centre of the view: the nearest crossing wins.
    canvas.show_project(
        Project(
            coord_systems=[
                CoordinateGridSystem(
                    name="Global",
                    grid=GridSystem(
                        x_grid_lines=make_grid_lines("X", [40.0, 45.0]),
                        y_grid_lines=make_grid_lines("Y", [40.0]),
                        z_grid_lines=make_grid_lines("Z", [0.0]),
                    ),
                ),
            ],
        ),
    )
    _look_down_at(canvas, (0.0, 0.0, 0.0))
    seen: list[tuple] = []
    canvas.emptyClicked.connect(lambda *args: seen.append(args))

    canvas._handle_click(canvas.width() / 2.0, canvas.height() / 2.0)

    assert seen, "an empty click must always resolve to a point"
    x, y, z, snapped = seen[-1]
    assert snapped is True
    assert (x, y, z) == pytest.approx((40.0, 40.0, 0.0), abs=1e-6)


def test_a_grid_less_project_still_places_the_point(qtbot) -> None:  # type: ignore[no-untyped-def]
    """No grid, nothing to snap to: the click lands where the ray meets the plane."""
    canvas = _sized_canvas(qtbot)
    canvas.show_project(Project())  # the default Global system has no lines
    _look_down_at(canvas, (4.0, -2.0, 0.0))
    seen: list[tuple] = []
    canvas.emptyClicked.connect(lambda *args: seen.append(args))

    canvas._handle_click(canvas.width() / 2.0, canvas.height() / 2.0)

    assert seen
    x, y, z, snapped = seen[-1]
    assert snapped is False
    assert (x, y, z) == pytest.approx((4.0, -2.0, 0.0), abs=1e-6)


def test_a_click_on_an_intersection_is_reported_as_snapped(qtbot) -> None:  # type: ignore[no-untyped-def]
    canvas = _sized_canvas(qtbot)
    canvas.show_project(
        Project(
            coord_systems=[
                CoordinateGridSystem(
                    name="Global",
                    grid=GridSystem(
                        x_grid_lines=make_grid_lines("X", [0.0]),
                        y_grid_lines=make_grid_lines("Y", [0.0]),
                        z_grid_lines=make_grid_lines("Z", [0.0]),
                    ),
                ),
            ],
        ),
    )
    _look_down_at(canvas, (0.0, 0.0, 0.0))
    seen: list[tuple] = []
    canvas.emptyClicked.connect(lambda *args: seen.append(args))

    canvas._handle_click(canvas.width() / 2.0, canvas.height() / 2.0)

    assert seen, "a click on the intersection must resolve"
    x, y, z, snapped = seen[-1]
    assert snapped is True
    assert (x, y, z) == pytest.approx((0.0, 0.0, 0.0), abs=1e-6)
