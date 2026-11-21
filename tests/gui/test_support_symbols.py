"""Support symbols are line drawings that show which directions are held."""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("PySide6")

import pyvista as pv

from opensees_studio.core import Node, Project
from opensees_studio.views.canvas3d.model_canvas import ModelCanvas
from opensees_studio.views.canvas3d.model_renderer import support_symbol_segments


@pytest.mark.parametrize(
    ("translations", "rotations"),
    [
        ((False, False, True), (False, False, False)),  # roller Z
        ((True, False, False), (False, False, False)),  # roller X
        ((False, True, False), (False, False, False)),  # roller Y
        ((True, False, True), (False, False, False)),  # pin X + Z
        ((True, True, True), (True, True, True)),  # fix
        ((False, False, True), (False, True, False)),  # roller Z with Ry locked
    ],
)
def test_support_symbols_are_line_segments(
    translations: tuple[bool, bool, bool],
    rotations: tuple[bool, bool, bool],
) -> None:
    points, cells = support_symbol_segments(translations, rotations, 1.0)

    assert points.ndim == 2 and points.shape[1] == 3
    assert len(points) >= 2
    assert len(cells) % 3 == 0
    assert np.all(cells[0::3] == 2), "every cell must be a two-point line"

    # The ground line goes on the side opposite to the held direction.
    if translations[0]:
        assert points[:, 0].min() < 0.0
    if translations[1]:
        assert points[:, 1].min() < 0.0
    if translations[2]:
        assert points[:, 2].min() < 0.0


@pytest.mark.gui
def test_the_renderer_draws_supports_as_line_actors(qtbot) -> None:  # type: ignore[no-untyped-def]
    canvas = ModelCanvas()
    qtbot.addWidget(canvas)
    canvas.show_project(
        Project(
            nodes=[
                # Uz only: a roller on the floor.
                Node(
                    id=1,
                    coords=(0.0, 0.0, 0.0),
                    restraint=(False, False, True, False, False, False),
                ),
                # Ux + Uz: the two ground lines of a pin.
                Node(
                    id=2, coords=(4.0, 0.0, 0.0), restraint=(True, False, True, False, False, False)
                ),
                # Everything: the pin plus the rotation locks.
                Node(id=3, coords=(8.0, 0.0, 0.0), restraint=(True, True, True, True, True, True)),
            ]
        )
    )

    names = {name for name in canvas._renderer._plotter.actors if str(name).startswith("supports_")}
    assert {"supports_uz", "supports_ux_uz", "supports_ux_uy_uz_rx_ry_rz"} <= names
    for name in names:
        actor = canvas._renderer._plotter.actors[name]
        mesh = pv.wrap(actor.mapper.dataset)
        assert mesh.n_points > 0
        assert mesh.n_lines > 0
        assert mesh.n_lines == mesh.n_cells, "a support must not add any faces"
