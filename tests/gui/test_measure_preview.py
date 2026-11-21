"""Measure Distance's transient graphics: red anchor, dashed guide, length badge."""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("PySide6")

from opensees_studio.core import Node, Project
from opensees_studio.views.canvas3d.model_canvas import ModelCanvas
from opensees_studio.views.canvas3d.model_renderer import dashed_line_geometry


def test_dashed_line_geometry_leaves_a_gap_between_dashes() -> None:
    points, cells = dashed_line_geometry((0.0, 0.0, 0.0), (10.0, 0.0, 0.0), dashes=4, fill=0.5)

    assert points.shape == (8, 3)
    assert cells.shape == (12,)
    assert points[0] == pytest.approx((0.0, 0.0, 0.0))
    assert points[1] == pytest.approx((1.25, 0.0, 0.0))
    # The gap after the first dash is 1.25 -> 2.5, not continuous ink.
    assert points[2] == pytest.approx((2.5, 0.0, 0.0))
    assert points[3] == pytest.approx((3.75, 0.0, 0.0))
    assert points[-1] == pytest.approx((8.75, 0.0, 0.0))
    assert np.asarray(cells).reshape(-1, 3)[0].tolist() == [2, 0, 1]


def test_a_zero_length_guide_has_no_geometry() -> None:
    points, cells = dashed_line_geometry((1.0, 2.0, 3.0), (1.0, 2.0, 3.0))
    assert len(points) == 0
    assert len(cells) == 0


@pytest.mark.gui
def test_measure_preview_actors_round_trip(qtbot) -> None:  # type: ignore[no-untyped-def]
    canvas = ModelCanvas()
    qtbot.addWidget(canvas)
    canvas.show_project(
        Project(
            nodes=[
                Node(id=1, coords=(0.0, 0.0, 0.0)),
                Node(id=2, coords=(3.0, 4.0, 0.0)),
            ]
        )
    )
    renderer = canvas._renderer
    assert renderer.node_point(2) == pytest.approx((3.0, 4.0, 0.0))
    assert renderer.node_point(99) is None

    renderer.set_measure_anchor((0.0, 0.0, 0.0))
    assert renderer._measure_anchor_actor is not None
    renderer.set_measure_guide((0.0, 0.0, 0.0), (3.0, 4.0, 0.0), "5 m")
    assert renderer._measure_guide_actor is not None
    assert renderer._measure_label_actor is not None

    renderer.clear_measure_guide()
    assert renderer._measure_guide_actor is None
    assert renderer._measure_label_actor is None
    assert renderer._measure_anchor_actor is not None

    renderer.clear_measure_preview()
    assert renderer._measure_anchor_actor is None
