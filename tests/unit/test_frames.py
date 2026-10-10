"""The geometry of a parametric portal frame, before any Qt or solver sees it.

Every case here is a number a user would type into the wizard, checked against
a hand calculation rather than against the implementation's own output.
"""

from __future__ import annotations

import pytest

from opensees_studio.core import (
    ElasticBeamColumn,
    PortalFrameError,
    PortalFrameSpec,
    RoofType,
    SupportCondition,
    build_portal_frame,
    frame_grid,
)

FIXED = (True, True, True, True, True, True)


def _spec(**overrides: object) -> PortalFrameSpec:
    fields: dict[str, object] = {
        "bay_width": 6.0,
        "eave_height": 4.0,
        "column_section_id": 1,
        "rafter_section_id": 2,
    }
    fields.update(overrides)
    return PortalFrameSpec(**fields)  # type: ignore[arg-type]


def _build(spec: PortalFrameSpec, *, ndm: int = 3, ndf: int = 6, **ids: int):  # type: ignore[no-untyped-def]
    return build_portal_frame(
        spec,
        ndm=ndm,
        ndf=ndf,
        first_node_id=ids.get("node", 1),
        first_element_id=ids.get("element", 1),
    )


def _coords(frame) -> list[tuple[float, float, float]]:  # type: ignore[no-untyped-def]
    return [node.coords for node in frame.nodes]


# ──────────────────────────── the roof line ────────────────────────────
def test_a_gable_rises_to_half_the_span() -> None:
    spec = _spec(bay_width=6.0, eave_height=4.0, slope=0.10, roof=RoofType.GABLE)
    assert spec.span == 6.0
    assert spec.ridge_height == pytest.approx(4.30)  # 4 + 0.10 * 3
    assert spec.roof_height(0.0) == 4.0
    assert spec.roof_height(6.0) == 4.0
    assert spec.roof_height(3.0) == pytest.approx(4.30)


def test_a_mono_pitch_rises_across_the_whole_width() -> None:
    spec = _spec(bay_width=6.0, eave_height=4.0, slope=0.10, roof=RoofType.MONO_PITCH)
    assert spec.ridge_height == pytest.approx(4.60)  # 4 + 0.10 * 6
    assert spec.roof_height(0.0) == 4.0
    assert spec.roof_height(6.0) == pytest.approx(4.60)


def test_a_zero_slope_is_a_flat_roof() -> None:
    spec = _spec(slope=0.0, roof=RoofType.MONO_PITCH, n_bays=3, bay_width=5.0)
    assert spec.ridge_height == 4.0
    assert spec.column_heights() == [4.0, 4.0, 4.0, 4.0]


def test_interior_columns_reach_the_roof_line() -> None:
    """The point of putting the tops on the line: nobody types 4.6 by hand."""
    spec = _spec(n_bays=2, bay_width=6.0, slope=0.10, roof=RoofType.MONO_PITCH)
    assert spec.column_heights() == [4.0, pytest.approx(4.6), pytest.approx(5.2)]


# ──────────────────────────── the nodes ────────────────────────────
def test_one_bay_gable_has_two_columns_four_rafters_and_a_crown() -> None:
    frame = _build(_spec())

    assert frame.ridge_node_id == 5
    assert len(frame.nodes) == 5
    assert [el.nodes for el in frame.elements] == [(1, 2), (3, 4), (2, 5), (5, 4)]
    assert _coords(frame) == [
        (0.0, 0.0, 0.0),
        (0.0, 0.0, 4.0),
        (6.0, 0.0, 0.0),
        (6.0, 0.0, 4.0),
        (3.0, 0.0, 4.3),  # the ridge, at mid-span
    ]
    assert [el.section_id for el in frame.elements] == [1, 1, 2, 2]


def test_an_even_number_of_bays_puts_the_ridge_on_a_column() -> None:
    frame = _build(_spec(n_bays=2))

    assert frame.ridge_node_id is None  # the middle column IS the ridge
    assert len(frame.nodes) == 6
    # 2 bays of 6 m: the ridge is the middle column, at eave + slope * span/2.
    assert frame.nodes[3].coords == (6.0, 0.0, pytest.approx(4.6))
    assert [el.nodes for el in frame.elements] == [(1, 2), (3, 4), (5, 6), (2, 4), (4, 6)]


def test_three_bays_gable_crowns_the_middle_bay() -> None:
    frame = _build(_spec(n_bays=3, bay_width=5.0))

    assert frame.ridge_node_id == 9
    # The crown falls mid-bay at eave + slope * span/2 = 4 + 0.10 * 7.5.
    assert frame.nodes[-1].coords == (7.5, 0.0, pytest.approx(4.75))
    assert frame.spec.ridge_height == pytest.approx(4.75)
    # Columns 1-4, then a rafter per bay, with the middle bay split by the crown.
    assert [el.nodes for el in frame.elements] == [
        (1, 2),
        (3, 4),
        (5, 6),
        (7, 8),
        (2, 4),
        (4, 9),
        (9, 6),
        (6, 8),
    ]


def test_ids_continue_from_where_the_project_left_off() -> None:
    frame = _build(_spec(), node=100, element=250)

    assert [n.id for n in frame.nodes] == [100, 101, 102, 103, 104]
    assert [e.id for e in frame.elements] == [250, 251, 252, 253]


def test_the_origin_moves_the_whole_frame() -> None:
    frame = _build(_spec(plane="YZ", origin=(1.0, 2.0, 3.0)))

    # YZ: span along y, height along z, thickness along x.
    assert _coords(frame)[:3] == [(1.0, 2.0, 3.0), (1.0, 2.0, 7.0), (1.0, 8.0, 3.0)]


# ──────────────────────────── supports ────────────────────────────
def test_fixed_bases_and_out_of_plane_restraint_in_3d() -> None:
    frame = _build(_spec(plane="XZ"))

    assert frame.nodes[0].restraint == FIXED  # base: everything
    # Free nodes keep the out-of-plane Uy, Rx and Rz of the XZ plane fixed.
    assert frame.nodes[1].restraint == (False, True, False, True, False, True)


def test_pinned_bases_leave_the_in_plane_rotation_free() -> None:
    frame = _build(_spec(plane="XZ", support=SupportCondition.PINNED))

    assert frame.nodes[0].restraint == (True, True, True, True, False, True)


def test_turning_off_the_out_of_plane_restraint_leaves_a_3d_ready_frame() -> None:
    """What you want before copying the frame and tying the copies together."""
    frame = _build(_spec(plane="XZ", restrain_out_of_plane=False))

    assert frame.nodes[1].restraint == (False, False, False, False, False, False)


def test_the_out_of_plane_dof_depend_on_the_plane() -> None:
    assert _build(_spec(plane="XY")).nodes[1].restraint == (False, False, True, True, True, False)
    assert _build(_spec(plane="YZ")).nodes[1].restraint == (True, False, False, False, True, True)


def test_a_2d_project_uses_three_dof() -> None:
    frame = _build(_spec(plane="XY", n_bays=2), ndm=2, ndf=3)

    # (ndm, ndf) = (2, 3) stores Ux, Uy, Rz at positions 0, 1, 5.
    assert frame.nodes[0].restraint == (True, True, False, False, False, True)
    assert frame.nodes[1].restraint == (False, False, False, False, False, False)
    assert [n.coords for n in frame.nodes][:2] == [(0.0, 0.0, 0.0), (0.0, 4.0, 0.0)]


def test_a_2d_project_cannot_build_an_xz_frame() -> None:
    with pytest.raises(PortalFrameError, match="XY plane"):
        _build(_spec(plane="XZ"), ndm=2, ndf=3)


def test_a_truss_project_is_refused() -> None:
    with pytest.raises(PortalFrameError, match=r"Unsupported \(ndm, ndf\)"):
        _build(_spec(), ndm=2, ndf=2)


# ──────────────────────────── rejections ────────────────────────────
@pytest.mark.parametrize(
    ("field", "message"),
    [
        ({"n_bays": 0}, "at least one bay"),
        ({"bay_width": 0.0}, "bay width must be positive"),
        ({"bay_width": -1.0}, "bay width must be positive"),
        ({"eave_height": 0.0}, "eave height must be positive"),
        ({"slope": -0.01}, "slope cannot be negative"),
        ({"slope": 1.0}, "not a roof"),
        ({"column_section_id": 0}, "need a section"),
        ({"rafter_section_id": 0}, "need a section"),
        ({"plane": "AB"}, "Unknown plane"),
    ],
)
def test_an_impossible_specification_is_rejected(field: dict[str, object], message: str) -> None:
    with pytest.raises(PortalFrameError, match=message):
        _spec(**field)


def test_the_frame_is_a_plain_beam_column_structure() -> None:
    frame = _build(_spec())

    assert all(isinstance(el, ElasticBeamColumn) for el in frame.elements)
    assert frame.n_columns == 2


def test_the_summary_names_the_geometry() -> None:
    text = _build(_spec(bay_width=6.0, eave_height=4.0, slope=0.10)).summary()

    assert "1 bay(s) x 6" in text
    assert "ridge 4.3" in text
    assert "2 slopes" in text
    assert "10 %" in text


# ──────────────────────────── the grid ────────────────────────────
def _ordinates(grid) -> dict[str, list[float]]:  # type: ignore[no-untyped-def]
    return {
        "x": [line.ordinate for line in grid.grid.x_grid_lines],
        "y": [line.ordinate for line in grid.grid.y_grid_lines],
        "z": [line.ordinate for line in grid.grid.z_grid_lines],
    }


def _labels(grid) -> dict[str, list[str]]:  # type: ignore[no-untyped-def]
    return {
        "x": [line.id for line in grid.grid.x_grid_lines],
        "y": [line.id for line in grid.grid.y_grid_lines],
        "z": [line.id for line in grid.grid.z_grid_lines],
    }


def test_the_grid_marks_the_columns_the_roof_levels_and_the_plane() -> None:
    """Started from a new 2D frame, the user keeps drawing on the wizard's lines."""
    grid = frame_grid(_spec(bay_width=6.0, eave_height=4.0, slope=0.10, plane="XY"))

    assert grid.name == "Portal Frame"
    assert grid.grid.visible
    assert _ordinates(grid) == {"x": [0.0, 3.0, 6.0], "y": [0.0, 4.0, 4.3], "z": [0.0]}


def test_the_grid_sits_at_the_origin_the_wizard_was_given() -> None:
    grid = frame_grid(_spec(origin=(10.0, 0.0, 2.0), plane="XY"))

    assert grid.coord.origin == (10.0, 0.0, 2.0)
    assert _ordinates(grid)["x"][0] == 0.0  # ordinates are relative to it


def test_the_grid_lines_carry_the_application_labels() -> None:
    grid = frame_grid(_spec(plane="XY"))

    assert _labels(grid)["x"] == ["X1", "X2", "X3"]
    assert _labels(grid)["y"] == ["Y1", "Y2", "Y3"]


def test_a_flat_multi_bay_grid_has_one_line_per_column() -> None:
    grid = frame_grid(
        _spec(n_bays=3, bay_width=5.0, eave_height=3.0, slope=0.0, roof=RoofType.MONO_PITCH)
    )

    # The default plane is XZ: the span is x, the heights are z, and y is the plane.
    assert _ordinates(grid) == {
        "x": [0.0, 5.0, 10.0, 15.0],  # one line per column
        "z": [0.0, 3.0],  # the ground and the single roof level, listed once
        "y": [0.0],
    }


def test_a_mono_pitch_lists_every_column_height() -> None:
    grid = frame_grid(
        _spec(n_bays=2, bay_width=6.0, eave_height=4.0, slope=0.10, roof=RoofType.MONO_PITCH)
    )

    assert _ordinates(grid)["z"] == [0.0, 4.0, 4.6, 5.2]  # every column top


def test_the_grid_follows_the_plane_the_frame_was_built_in() -> None:
    grid = frame_grid(_spec(n_bays=1, bay_width=6.0, eave_height=4.0, plane="YZ"))

    # YZ: span along y, height along z, and x is the plane's own level.
    assert _ordinates(grid)["y"] == [0.0, 3.0, 6.0]
    assert _ordinates(grid)["z"] == [0.0, 4.0, 4.3]
    assert _ordinates(grid)["x"] == [0.0]
