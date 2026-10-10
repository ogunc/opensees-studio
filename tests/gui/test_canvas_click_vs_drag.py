"""What counts as a click, and what counts as a camera drag.

The report — "no se puede dibujar nodos y elementos frame" — had a second cause
beyond the view jumping: a press/release pair was only accepted as a click when
the pointer moved **3 px or less**, so a hand that drifted a few pixels turned
every click into a (bogus) drag and nothing was drawn.

The camera decides now: if it did not move, the gesture was a click and it may
drift up to `CLICK_MAX_DRIFT_PX`; if it did move, the user was orbiting and no
pick is committed.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyvistaqt")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest


@pytest.fixture
def canvas(qtbot):  # type: ignore[no-untyped-def]
    from opensees_studio.core import Project
    from opensees_studio.views.canvas3d.model_canvas import ModelCanvas

    widget = ModelCanvas()
    qtbot.addWidget(widget)
    widget.resize(800, 600)
    widget.show()
    qtbot.waitExposed(widget)
    widget.show_project(Project())
    widget.view_xy()
    yield widget
    widget.close()


def _clicks(canvas) -> list[tuple]:  # type: ignore[no-untyped-def]
    seen: list[tuple] = []
    canvas.emptyClicked.connect(lambda *args: seen.append(args))
    return seen


def _orbit_camera(canvas, degrees: float = 20.0) -> None:  # type: ignore[no-untyped-def]
    """Tilt the camera as a real drag would, without relying on VTK offscreen.

    `QTest.mouseMove` does not rotate the camera in the headless harness (no real
    GL context), so a test that wants "the user dragged" has to put the camera
    where a drag would have left it.
    """
    import math

    state = canvas._camera_state()
    assert state is not None
    position, focal, up = state
    distance = math.dist(position, focal)
    angle = math.radians(degrees)
    canvas.camera.position = (
        focal[0] + distance * math.sin(angle),
        focal[1],
        focal[2] + distance * math.cos(angle),
    )
    canvas.camera.focal_point = focal
    canvas.camera.up = up


def _press_release(canvas, start: QPoint, end: QPoint | None = None) -> None:  # type: ignore[no-untyped-def]
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
    if end is not None:
        QTest.mouseMove(canvas, end)
    QTest.mouseRelease(
        canvas,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        end or start,
    )


def test_a_clean_click_commits(canvas) -> None:  # type: ignore[no-untyped-def]
    seen = _clicks(canvas)
    _press_release(canvas, QPoint(400, 300))
    assert len(seen) == 1


def test_a_click_that_drifts_a_few_pixels_still_commits(canvas) -> None:  # type: ignore[no-untyped-def]
    """The bug: 5 px of hand jitter used to swallow the click entirely."""
    seen = _clicks(canvas)
    _press_release(canvas, QPoint(400, 300), QPoint(405, 302))
    assert len(seen) == 1


def test_a_drag_past_the_threshold_does_not_commit(canvas) -> None:  # type: ignore[no-untyped-def]
    """An orbit travels far more than the click budget, and keeps the new view."""
    seen = _clicks(canvas)
    QTest.mousePress(
        canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(400, 300)
    )
    _orbit_camera(canvas)
    QTest.mouseRelease(
        canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(460, 340)
    )
    assert seen == []


def test_a_click_that_drifts_leaves_the_camera_untouched(canvas) -> None:  # type: ignore[no-untyped-def]
    """VTK rotates a little during the drift; a click must undo that."""
    before = tuple(canvas.camera.position)
    _press_release(canvas, QPoint(400, 300), QPoint(405, 302))
    after = tuple(canvas.camera.position)
    assert after == pytest.approx(before, abs=1e-9)


def test_the_select_tool_keeps_the_tighter_budget(canvas) -> None:  # type: ignore[no-untyped-def]
    """With no draw tool armed, 25 px is a drag: the user was orbiting."""
    from opensees_studio.views.canvas3d.model_canvas import CLICK_MAX_DRIFT_PX

    assert CLICK_MAX_DRIFT_PX == 20.0
    seen = _clicks(canvas)
    QTest.mousePress(
        canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(400, 300)
    )
    _orbit_camera(canvas)
    QTest.mouseRelease(
        canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(425, 300)
    )
    assert seen == []


def test_a_drag_that_moved_nothing_is_still_a_click(canvas) -> None:  # type: ignore[no-untyped-def]
    """If the view is identical to what it was at press, the pointer was just unsteady."""
    seen = _clicks(canvas)
    QTest.mousePress(
        canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(400, 300)
    )
    pressed = canvas._camera_state()
    assert pressed is not None
    # Simulate an interactor that never started rotating, however far the pointer
    # went: put the camera back to its press state before releasing.
    QTest.mouseMove(canvas, QPoint(520, 380))
    canvas.camera.position = pressed[0]
    canvas.camera.focal_point = pressed[1]
    canvas.camera.up = pressed[2]
    assert canvas._camera_moved_since_press() is False
    QTest.mouseRelease(
        canvas,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        QPoint(520, 380),
    )

    assert len(seen) == 1


def test_a_drag_while_a_tool_is_armed_says_so(canvas) -> None:  # type: ignore[no-untyped-def]
    """Silence is what made the tool feel dead: a swallowed click explains itself."""
    canvas.set_default_selection_enabled(False)
    seen = _clicks(canvas)
    messages: list[str] = []
    canvas.dragNotAClick.connect(lambda: messages.append("drag"))

    QTest.mousePress(
        canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(400, 300)
    )
    _orbit_camera(canvas)
    QTest.mouseRelease(
        canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(470, 340)
    )

    assert seen == []
    assert messages == ["drag"]


def test_a_drag_with_the_select_tool_says_nothing(canvas) -> None:  # type: ignore[no-untyped-def]
    """Orbiting with the select tool is normal; it must not nag."""
    messages: list[str] = []
    canvas.dragNotAClick.connect(lambda: messages.append("drag"))
    QTest.mousePress(
        canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(400, 300)
    )
    _orbit_camera(canvas)
    QTest.mouseRelease(
        canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(470, 340)
    )
    assert messages == []


def test_a_drifting_click_draws_a_node_end_to_end(qtbot) -> None:  # type: ignore[no-untyped-def]
    """The whole path: arm Draw Node, click with a little drift, get a node."""
    from opensees_studio.views.main_window import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)
    window.resize(1000, 700)
    window.show()
    qtbot.waitExposed(window)
    window._vm.new_project(ndm=2, ndf=3)

    canvas = window._canvas
    window._on_draw_node_tool()
    canvas.view_xy()

    centre = QPoint(canvas.width() // 2, canvas.height() // 2)
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, centre)
    QTest.mouseRelease(
        canvas,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        QPoint(centre.x() + 5, centre.y() + 2),
    )

    assert len(window._vm.project.nodes) >= 1


# ─────────────── a tool decides by how far the view turned (0.0.7) ───────────────
def test_a_tap_that_drifts_far_but_barely_turns_is_still_a_click(canvas) -> None:  # type: ignore[no-untyped-def]
    """A trackpad tap drifts tens of pixels while turning the camera almost nothing.

    Pixels were the wrong question; the view is the right one. Here the pointer
    travels 120 px but the camera is put back as if VTK had hardly moved it, and
    the draw tool must still place its pick.
    """

    canvas.set_default_selection_enabled(False)  # a pick-consuming tool is armed
    seen = _clicks(canvas)
    QTest.mousePress(
        canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(300, 300)
    )
    pressed = canvas._camera_state()
    assert pressed is not None
    QTest.mouseMove(canvas, QPoint(420, 340))
    # A fraction of a degree of rotation: tremor, not intent.
    camera = canvas.camera
    position, focal, up = pressed
    camera.position = (position[0] + 0.001, position[1], position[2])
    camera.focal_point = focal
    camera.up = up
    assert canvas._camera_moved_visibly() is False
    QTest.mouseRelease(
        canvas,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        QPoint(420, 340),
    )

    assert len(seen) == 1


def test_a_real_orbit_with_a_tool_armed_places_nothing(canvas) -> None:  # type: ignore[no-untyped-def]
    """Turning the view by a visible angle is an orbit, whatever the pixels say."""
    import math

    canvas.set_default_selection_enabled(False)
    seen = _clicks(canvas)
    QTest.mousePress(
        canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(300, 300)
    )
    pressed = canvas._camera_state()
    assert pressed is not None
    position, focal, _up = pressed
    # Tilt the camera 20 degrees about the focal point: an unmistakable orbit.
    distance = math.dist(position, focal)
    angle = math.radians(20.0)
    rotated = (
        focal[0] + distance * math.sin(angle),
        focal[1],
        focal[2] + distance * math.cos(angle),
    )
    canvas.camera.position = rotated
    canvas.camera.focal_point = focal
    assert canvas._camera_moved_visibly() is True
    QTest.mouseRelease(
        canvas,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        QPoint(320, 320),
    )

    assert seen == []
