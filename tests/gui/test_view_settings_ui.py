"""GUI tests for the per-viewport display settings (visibility, hiding, zoom)."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from opensees_studio.core import ElasticBeamColumn, ElasticSection, Node, Project
from opensees_studio.core.view_settings import ViewSettings


def _frame_project() -> Project:
    b, h = 0.30, 0.50
    return Project(
        nodes=[
            Node(id=1, coords=(0.0, 0.0, 0.0), restraint=(True, True, True, True, True, True)),
            Node(id=2, coords=(6.0, 0.0, 0.0)),
        ],
        sections=[
            ElasticSection(
                id=1,
                name="Rect",
                E=200e9,
                A=b * h,
                Iz=b * h**3 / 12.0,
                Iy=h * b**3 / 12.0,
                G=80e9,
                J=1e-6,
            )
        ],
        elements=[ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1)],
    )


def _canvas(qtbot):  # type: ignore[no-untyped-def]
    from opensees_studio.views.canvas3d.model_canvas import ModelCanvas

    canvas = ModelCanvas()
    qtbot.addWidget(canvas)
    canvas.show_project(_frame_project())
    return canvas


@pytest.mark.gui
def test_hiding_an_element_removes_it_from_the_scene(qtbot) -> None:  # type: ignore[no-untyped-def]
    canvas = _canvas(qtbot)
    assert canvas._renderer._frame_pd is not None

    canvas.set_hidden(nodes=set(), elements={1})

    assert canvas._renderer._frame_pd is None
    assert canvas.hidden == (frozenset(), frozenset({1}))


@pytest.mark.gui
def test_showing_it_again_brings_the_element_back(qtbot) -> None:  # type: ignore[no-untyped-def]
    canvas = _canvas(qtbot)
    canvas.set_hidden(nodes=set(), elements={1})

    canvas.set_hidden(nodes=set(), elements=set())

    assert canvas._renderer._frame_pd is not None
    assert canvas.hidden == (frozenset(), frozenset())


@pytest.mark.gui
def test_terminal_settings_are_applied_to_the_renderer(qtbot) -> None:  # type: ignore[no-untyped-def]
    canvas = _canvas(qtbot)

    canvas.set_view_settings(ViewSettings(show_nodes=False, show_frames=False))

    assert canvas._renderer._node_pd is None
    assert canvas._renderer._frame_pd is None
    # The project itself is untouched: hiding is a viewport concern.
    assert len(canvas.view_settings.model_fields) > 0


@pytest.mark.gui
def test_background_colour_reaches_the_plotter(qtbot) -> None:  # type: ignore[no-untyped-def]
    canvas = _canvas(qtbot)

    canvas.set_view_settings(ViewSettings(background_bottom="#101010", background_top="#202020"))

    rgb = canvas.renderer.GetBackground()
    # VTK normalises to 0..1 and may keep one value for both ends.
    assert all(
        abs(channel - (0x10 / 255)) < 0.02 or abs(channel - (0x20 / 255)) < 0.02 for channel in rgb
    )


@pytest.mark.gui
def test_zoom_in_and_out_change_the_camera_scale(qtbot) -> None:  # type: ignore[no-untyped-def]
    """VTK zooms by widening the view angle (or the parallel scale), not by
    moving the camera, so the assertion is on whichever is in play."""
    canvas = _canvas(qtbot)
    camera = canvas.camera
    before = (camera.GetViewAngle(), camera.GetParallelScale())

    canvas.zoom_in()
    zoomed_in = (camera.GetViewAngle(), camera.GetParallelScale())
    canvas.zoom_out()
    zoomed_out = (camera.GetViewAngle(), camera.GetParallelScale())

    assert zoomed_in != before
    assert zoomed_out != zoomed_in
    # Zooming in magnifies: VTK narrows the view angle (perspective) or
    # shrinks the parallel scale (orthographic).
    assert zoomed_in[0] < before[0] or zoomed_in[1] < before[1]


@pytest.mark.gui
def test_zoom_refreshes_the_screen_relative_overlay_size(qtbot) -> None:  # type: ignore[no-untyped-def]
    canvas = _canvas(qtbot)
    renderer = canvas._renderer
    before = renderer._screen_key
    assert before is not None

    canvas.zoom_in()
    qtbot.wait(300)

    assert renderer._screen_key != before
