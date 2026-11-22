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

    # Both elevation planes use the same vocabulary: X-Z for Ux/Uz and Y-Z
    # for Uy/Uz.
    if translations[0]:
        assert points[:, 0].min() < 0.0
    if translations[1]:
        assert points[:, 1].min() < 0.0
    if translations[2]:
        assert points[:, 2].min() < 0.0


def test_uy_only_is_a_wall_roller_in_the_yz_plane() -> None:
    points, _cells = support_symbol_segments((False, True, False), (False, False, False), 1.0)
    assert points[:, 1].min() < 0.0
    assert np.allclose(points[:, 0], 0.0)


def test_uz_only_has_a_floor_roller_in_each_plane() -> None:
    points, _cells = support_symbol_segments((False, False, True), (False, False, False), 1.0)
    assert points[:, 0].min() < 0.0
    assert points[:, 1].min() < 0.0
    assert points[:, 2].min() < 0.0


def test_a_pin_in_both_directions_has_two_perpendicular_triangles() -> None:
    points, _cells = support_symbol_segments((True, True, True), (False, False, False), 1.0)
    assert points[:, 0].min() < 0.0
    assert points[:, 1].min() < 0.0
    assert points[:, 2].min() < 0.0


def test_ry_fixes_the_xz_plane_without_the_node_square() -> None:
    _pin_points, pin_cells = support_symbol_segments((True, True, True), (False, False, False), 1.0)
    fixed_points, fixed_cells = support_symbol_segments(
        (True, True, True), (False, True, False), 1.0
    )

    assert len(fixed_cells) > len(pin_cells), "the X-Z block replaces the triangle"
    assert fixed_points[:, 2].max() <= 0.0, "Ry is shown by the block, not the node square"
    assert fixed_points[:, 0].min() < 0.0
    assert fixed_points[:, 1].min() < 0.0


def test_rx_fixes_the_yz_plane_without_the_node_square() -> None:
    points, _cells = support_symbol_segments((True, True, True), (True, False, False), 1.0)
    assert points[:, 2].max() <= 0.0, "Rx is shown by the Y-Z block, not the node square"


def test_rz_adds_the_node_square() -> None:
    points, _cells = support_symbol_segments((True, True, True), (False, False, True), 1.0)
    assert points[:, 2].max() > 0.0, "torsion has no plane block, so it keeps the square"


def test_the_two_planes_can_be_taken_apart() -> None:
    xz_points, xz_cells = support_symbol_segments(
        (True, True, True), (False, False, False), 1.0, part="xz"
    )
    yz_points, yz_cells = support_symbol_segments(
        (True, True, True), (False, False, False), 1.0, part="yz"
    )

    assert len(xz_cells) and np.allclose(xz_points[:, 1], 0.0)
    assert xz_points[:, 0].min() < 0.0
    assert len(yz_cells) and np.allclose(yz_points[:, 0], 0.0)
    assert yz_points[:, 1].min() < 0.0


@pytest.mark.gui
def test_the_renderer_draws_supports_as_line_actors(qtbot) -> None:  # type: ignore[no-untyped-def]
    canvas = ModelCanvas()
    qtbot.addWidget(canvas)
    canvas.show_project(
        Project(
            nodes=[
                # Uz only: a floor roller in both elevation planes.
                Node(
                    id=1,
                    coords=(0.0, 0.0, 0.0),
                    restraint=(False, False, True, False, False, False),
                ),
                # Ux + Uz: a pin in X-Z and a floor roller in Y-Z.
                Node(
                    id=2, coords=(4.0, 0.0, 0.0), restraint=(True, False, True, False, False, False)
                ),
                # Everything: fixed blocks in both planes plus the Rz square.
                Node(id=3, coords=(8.0, 0.0, 0.0), restraint=(True, True, True, True, True, True)),
            ]
        )
    )

    names = {name for name in canvas._renderer._plotter.actors if str(name).startswith("supports_")}
    assert {
        "supports_uz_xz",
        "supports_uz_yz",
        "supports_ux_uz_xz",
        "supports_ux_uz_yz",
        "supports_ux_uy_uz_rx_ry_rz_xz",
        "supports_ux_uy_uz_rx_ry_rz_yz",
        "supports_ux_uy_uz_rx_ry_rz_lock",
    } <= names
    xz_actor = canvas._renderer._plotter.actors["supports_uz_xz"]
    yz_actor = canvas._renderer._plotter.actors["supports_uz_yz"]
    lock_actor = canvas._renderer._plotter.actors["supports_ux_uy_uz_rx_ry_rz_lock"]
    assert tuple(xz_actor.prop.color) != tuple(yz_actor.prop.color)
    assert tuple(lock_actor.prop.color) not in {
        tuple(xz_actor.prop.color),
        tuple(yz_actor.prop.color),
    }
    for name in names:
        actor = canvas._renderer._plotter.actors[name]
        mesh = pv.wrap(actor.mapper.dataset)
        assert mesh.n_points > 0
        assert mesh.n_lines > 0
        assert mesh.n_lines == mesh.n_cells, "a support must not add any faces"
