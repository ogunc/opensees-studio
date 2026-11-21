"""Support symbols are schematic lines, not solid glyphs."""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("PySide6")

import pyvista as pv

from opensees_studio.core import Node, Project
from opensees_studio.views.canvas3d.model_canvas import ModelCanvas
from opensees_studio.views.canvas3d.model_renderer import support_symbol_segments


@pytest.mark.parametrize("kind", ["fix", "pin", "roller", "custom"])
def test_support_symbols_are_line_segments_in_the_xz_plane(kind: str) -> None:
    points, cells = support_symbol_segments(kind, 1.0)

    assert points.shape == (2 * (len(cells) // 3), 3)
    assert len(cells) % 3 == 0
    assert np.all(cells[0::3] == 2), "every cell must be a two-point line"
    assert np.allclose(points[:, 1], 0.0), "the symbol lives in the X-Z plane"
    assert points[:, 2].min() < 0.0, "the symbol hangs below the joint"


@pytest.mark.gui
def test_the_renderer_draws_supports_as_line_actors(qtbot) -> None:  # type: ignore[no-untyped-def]
    canvas = ModelCanvas()
    qtbot.addWidget(canvas)
    canvas.show_project(Project(nodes=[Node(id=1, coords=(0.0, 0.0, 0.0), restraint=(True,) * 6)]))

    actor = canvas._renderer._plotter.actors.get("supports_fix")
    assert actor is not None
    mesh = pv.wrap(actor.mapper.dataset)
    assert mesh.n_points > 0
    assert mesh.n_lines > 0
    assert mesh.n_lines == mesh.n_cells, "a support must not add any faces"
