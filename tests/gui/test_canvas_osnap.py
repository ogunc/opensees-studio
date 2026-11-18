"""Object snaps on members in the real canvas and the left icon bar."""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyvistaqt")

from opensees_studio.core import ElasticBeamColumn, ElasticSection, Node, Project
from opensees_studio.views.canvas3d import ModelCanvas, SnapMode


def _project() -> Project:
    return Project(
        ndm=3,
        ndf=6,
        nodes=[Node(id=1, coords=(0.0, 0.0, 0.0)), Node(id=2, coords=(10.0, 0.0, 0.0))],
        sections=[
            ElasticSection(
                id=1,
                E=200e9,
                A=0.01,
                Iz=1e-5,
                Iy=1e-5,
                G=80e9,
                J=2e-5,
            )
        ],
        elements=[ElasticBeamColumn(id=7, nodes=(1, 2), section_id=1)],
    )


def _top_canvas(qtbot) -> ModelCanvas:  # type: ignore[no-untyped-def]
    canvas = ModelCanvas()
    qtbot.addWidget(canvas)
    canvas.resize(800, 600)
    canvas.show()
    qtbot.waitExposed(canvas)
    canvas.show_project(_project())
    canvas.camera.position = (5.0, 0.0, 10.0)
    canvas.camera.focal_point = (5.0, 0.0, 0.0)
    canvas.camera.up = (0.0, 1.0, 0.0)
    canvas.render()
    canvas.set_default_selection_enabled(False)
    return canvas


def _click_world(canvas: ModelCanvas, point: tuple[float, float, float]) -> None:
    screen = canvas._project_world_to_screen(np.asarray([point], dtype=float), canvas.renderer)
    assert screen is not None
    canvas._handle_click(float(screen[0][0]), canvas.height() - float(screen[0][1]))


def _seen(canvas: ModelCanvas) -> list[tuple]:
    seen: list[tuple] = []
    canvas.emptyClicked.connect(lambda *args: seen.append(args))
    return seen


def test_midpoint_snap_wins_over_grid_and_reports_its_kind(qtbot) -> None:  # type: ignore[no-untyped-def]
    canvas = _top_canvas(qtbot)
    canvas.set_snap_modes({SnapMode.MIDPOINT})
    seen = _seen(canvas)

    _click_world(canvas, (5.0, 0.0, 0.0))

    assert seen
    x, y, z, snapped = seen[-1]
    assert (x, y, z) == pytest.approx((5.0, 0.0, 0.0), abs=1e-6)
    assert snapped is True
    assert canvas.last_snap_kind() == "midpoint"


def test_on_member_snap_follows_the_pointer(qtbot) -> None:  # type: ignore[no-untyped-def]
    canvas = _top_canvas(qtbot)
    canvas.set_snap_modes({SnapMode.ON_ELEMENT})
    seen = _seen(canvas)

    _click_world(canvas, (2.5, 0.0, 0.0))

    assert seen
    x, y, z, _ = seen[-1]
    # The screen-to-world round trip quantises to the viewport's pixel grid.
    assert (x, y, z) == pytest.approx((2.5, 0.0, 0.0), abs=0.02)
    assert canvas.last_snap_kind() == "on_element"


def test_perpendicular_snap_uses_the_first_point_as_reference(qtbot) -> None:  # type: ignore[no-untyped-def]
    canvas = _top_canvas(qtbot)
    canvas.set_snap_modes({SnapMode.PERPENDICULAR})
    canvas.set_snap_reference((2.0, 5.0, 0.0))
    seen = _seen(canvas)

    _click_world(canvas, (2.0, 0.0, 0.0))

    assert seen
    x, y, z, _ = seen[-1]
    assert (x, y, z) == pytest.approx((2.0, 0.0, 0.0), abs=1e-6)
    assert canvas.last_snap_kind() == "perpendicular"


def test_snap_toolbar_starts_enabled_and_toggles_every_viewport(qtbot) -> None:  # type: ignore[no-untyped-def]
    from opensees_studio.views.main_window import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)
    assert set(window._canvas.snap_modes()) == set(SnapMode)
    assert not window._snap_actions[SnapMode.MIDPOINT].icon().isNull()

    window._snap_actions[SnapMode.MIDPOINT].trigger()

    assert set(window._canvas.snap_modes()) == {SnapMode.PERPENDICULAR, SnapMode.ON_ELEMENT}
    assert "midpoint" not in window.statusBar().currentMessage()

    window._snap_actions[SnapMode.MIDPOINT].trigger()
    assert SnapMode.MIDPOINT in window._canvas.snap_modes()
