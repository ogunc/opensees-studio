"""Support and spring symbols: shape says the kind of support, colour the axis held."""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("PySide6")

import pyvista as pv

from opensees_studio.core import Node, Project
from opensees_studio.views.canvas3d.model_canvas import ModelCanvas
from opensees_studio.views.canvas3d.support_glyphs import (
    OUTLINE,
    X_FILL,
    Y_FILL,
    Z_FILL,
    X,
    Y,
    Z,
    spring_glyph,
    support_glyph,
)

T, F = True, False


def _slots(glyph) -> set[int]:  # type: ignore[no-untyped-def]
    return set(glyph.colors.tolist())


def _valid(glyph) -> None:  # type: ignore[no-untyped-def]
    assert glyph.points.ndim == 2 and glyph.points.shape[1] == 3
    assert len(glyph.lines) == 3 * glyph.n_lines
    assert np.all(glyph.lines[0::3] == 2), "every line cell is a two-point line"
    n = len(glyph.points)
    assert glyph.lines[1::3].max(initial=0) < n and glyph.lines[2::3].max(initial=0) < n


# ── 2D: one textbook symbol in the X-Z plane ────────────────────────────────


@pytest.mark.parametrize(
    ("ux", "uz", "ry", "slots"),
    [
        (T, T, T, {X, Z, Y_FILL, Y}),  # fixed: Ry block, Ux sides, Uz floor
        (T, T, F, {X, X_FILL, Z}),  # pin: Ux triangle on a Uz floor
        (F, T, F, {Z, Z_FILL}),  # roller: all Uz
        (T, F, F, {X, X_FILL}),  # roller on a wall: all Ux
        (F, T, T, {Y, Y_FILL, Z, Z_FILL}),  # guide: Ry plate on Uz wheels
        (T, F, T, {Y, Y_FILL, X, X_FILL}),  # vertical guide: Ry plate on Ux wheels
        (F, F, T, {Y, Y_FILL}),  # rotation only: a clamp square
    ],
)
def test_2d_symbols_stay_in_the_xz_plane_with_the_axis_colours(
    ux: bool, uz: bool, ry: bool, slots: set[int]
) -> None:
    glyph = support_glyph((ux, F, uz), (F, ry, F), 1.0, planar=True)
    _valid(glyph)
    assert np.allclose(glyph.points[:, 1], 0.0), "a 2D symbol never leaves the X-Z plane"
    assert _slots(glyph) == slots


def test_2d_ignores_dofs_the_plane_does_not_have() -> None:
    plain = support_glyph((T, F, T), (F, F, F), 1.0, planar=True)
    extra = support_glyph((T, T, T), (T, F, T), 1.0, planar=True)
    assert np.allclose(plain.points, extra.points)


def test_a_2d_wall_roller_sits_on_the_minus_x_side() -> None:
    glyph = support_glyph((T, F, F), (F, F, F), 1.0, planar=True)
    assert glyph.points[:, 0].min() < -0.5
    assert glyph.points[:, 0].max() <= 1e-9


def test_free_joint_has_no_symbol() -> None:
    assert support_glyph((F, F, F), (F, F, F), 1.0, planar=True).is_empty()
    assert support_glyph((F, F, F), (F, F, F), 1.0).is_empty()


# ── 3D: one solid for the usual patterns ────────────────────────────────────


def test_3d_fixed_is_a_box_with_a_face_per_axis() -> None:
    glyph = support_glyph((T, T, T), (T, T, T), 1.0)
    _valid(glyph)
    assert {X_FILL, Y_FILL, Z_FILL, OUTLINE} <= _slots(glyph)
    assert glyph.points[:, 2].max() <= 1e-9, "everything hangs below the joint"


def test_3d_pin_is_a_pyramid_whose_faces_show_x_and_y() -> None:
    glyph = support_glyph((T, T, T), (F, F, F), 1.0)
    assert {X_FILL, Y_FILL, OUTLINE, Z} <= _slots(glyph)
    assert glyph.n_faces == 4, "four pyramid faces, the ground is an outline"


def test_3d_vertical_roller_is_all_z() -> None:
    glyph = support_glyph((F, F, T), (F, F, F), 1.0)
    assert _slots(glyph) <= {Z, Z_FILL, OUTLINE}


@pytest.mark.parametrize(
    ("translations", "held"),
    [((T, F, T), X_FILL), ((F, T, T), Y_FILL)],
)
def test_3d_guided_roller_shows_the_held_horizontal_axis(
    translations: tuple[bool, bool, bool], held: int
) -> None:
    glyph = support_glyph(translations, (F, F, F), 1.0)
    other = Y_FILL if held == X_FILL else X_FILL
    assert held in _slots(glyph)
    assert other not in _slots(glyph)


def test_3d_torsion_adds_a_horizontal_square_at_the_joint() -> None:
    plain = support_glyph((T, T, T), (F, F, F), 1.0)
    torsion = support_glyph((T, T, T), (F, F, T), 1.0)
    assert torsion.n_faces == plain.n_faces + 1
    assert np.isclose(torsion.points[:, 2].max(), 0.0)


def test_unusual_3d_patterns_fall_back_to_both_elevation_planes() -> None:
    # Ux + Uz + Ry: a block in X-Z (Ry green, Ux red) and a roller in Y-Z.
    glyph = support_glyph((T, F, T), (F, T, F), 1.0)
    assert glyph.points[:, 0].min() < 0.0 and glyph.points[:, 1].min() < 0.0
    assert {X, Y_FILL, Z_FILL} <= _slots(glyph)
    # Uy only: a wall roller in Y-Z, nothing in X-Z.
    uy = support_glyph((F, T, F), (F, F, F), 1.0)
    assert np.allclose(uy.points[:, 0], 0.0)
    assert _slots(uy) == {Y, Y_FILL}


def test_size_scales_the_symbol() -> None:
    small = support_glyph((T, T, T), (F, F, F), 1.0)
    big = support_glyph((T, T, T), (F, F, F), 3.0)
    assert np.allclose(big.points, 3.0 * small.points)


# ── springs ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(("dof", "axis"), [(0, 0), (1, 1), (2, 2)])
def test_a_translational_spring_runs_along_its_axis_in_its_colour(dof: int, axis: int) -> None:
    sprung = [False] * 6
    sprung[dof] = True
    glyph = spring_glyph(sprung, 1.0)
    _valid(glyph)
    assert _slots(glyph) == {axis}
    assert glyph.points[:, axis].min() < -1.0, "the zigzag runs toward -axis"
    assert glyph.points[:, axis].max() <= 1e-9


@pytest.mark.parametrize(("dof", "axis"), [(3, 0), (4, 1), (5, 2)])
def test_a_rotational_spring_is_a_spiral_normal_to_its_axis(dof: int, axis: int) -> None:
    sprung = [False] * 6
    sprung[dof] = True
    glyph = spring_glyph(sprung, 1.0)
    assert _slots(glyph) == {axis}
    assert np.allclose(glyph.points[:, axis], 0.0)


def test_2d_springs_stay_in_the_xz_plane() -> None:
    glyph = spring_glyph((T, F, T, F, T, F), 1.0)
    assert np.allclose(glyph.points[:, 1], 0.0)
    assert _slots(glyph) == {X, Y, Z}


# ── renderer ────────────────────────────────────────────────────────────────


def _colors(canvas: ModelCanvas, name: str) -> set[int]:
    mesh = pv.wrap(canvas._renderer._plotter.actors[name].mapper.dataset)
    assert mesh.n_cells == mesh.GetNumberOfLines() + mesh.GetNumberOfPolys()
    return set(mesh.cell_data["_support_color"].tolist())


@pytest.mark.gui
def test_the_renderer_draws_one_actor_per_support_pattern(qtbot) -> None:  # type: ignore[no-untyped-def]
    canvas = ModelCanvas()
    qtbot.addWidget(canvas)
    canvas.show_project(
        Project(
            nodes=[
                Node(id=1, coords=(0.0, 0.0, 0.0), restraint=(F, F, T, F, F, F)),
                Node(id=2, coords=(4.0, 0.0, 0.0), restraint=(T, F, T, F, F, F)),
                Node(id=3, coords=(8.0, 0.0, 0.0), restraint=(T, T, T, T, T, T)),
                Node(id=4, coords=(12.0, 0.0, 0.0), restraint=(T, T, T, T, T, T)),
                # kUx on a free DOF is drawn; kUz on a restrained one is not.
                Node(
                    id=5,
                    coords=(16.0, 0.0, 0.0),
                    restraint=(F, F, T, F, F, F),
                    spring=(5.0, 0.0, 7.0, 0.0, 0.0, 0.0),
                ),
            ]
        )
    )
    actors = canvas._renderer._plotter.actors
    names = {str(name) for name in actors if str(name).startswith("supports_")}
    assert names == {"supports_uz", "supports_ux_uz", "supports_ux_uy_uz_rx_ry_rz"}
    fixed = pv.wrap(actors["supports_ux_uy_uz_rx_ry_rz"].mapper.dataset)
    one = support_glyph((T, T, T), (T, T, T), 1.0)
    assert fixed.n_cells == 2 * (one.n_lines + one.n_faces), "both fixed joints share the actor"
    assert {X_FILL, Y_FILL, Z_FILL} <= _colors(canvas, "supports_ux_uy_uz_rx_ry_rz")
    assert _colors(canvas, "support_springs") == {X}


@pytest.mark.gui
def test_a_2d_model_draws_only_the_xz_symbol(qtbot) -> None:  # type: ignore[no-untyped-def]
    canvas = ModelCanvas()
    qtbot.addWidget(canvas)
    canvas.show_project(
        Project(
            ndm=2,
            ndf=3,
            nodes=[Node(id=1, coords=(0.0, 0.0, 0.0), restraint=(T, F, T, F, F, F))],
        )
    )
    mesh = pv.wrap(canvas._renderer._plotter.actors["supports_ux_uz"].mapper.dataset)
    assert np.allclose(mesh.points[:, 1], 0.0), "no Y-Z symbol seen edge-on"
