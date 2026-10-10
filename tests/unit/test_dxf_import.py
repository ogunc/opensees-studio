"""Reading a bar layout out of a DXF drawing.

The files here are written with ``ezdxf`` in the test, so each case is exactly
the drawing it claims to be: a line, a chain, a closed polygon, a layer nobody
asked for, an inch drawing, a circle that must not become a member.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("ezdxf")

import ezdxf

from opensees_studio.core import UnitSystem
from opensees_studio.services.dxf_import import (
    DxfImportError,
    bars_from_drawing,
    merge_tolerance,
    read_drawing,
    unit_scale,
)


def _draw(callback, *, insunits: int = 6, name: str = "drawing.dxf", tmp_path: Path) -> Path:  # type: ignore[no-untyped-def]
    """Write a DXF with whatever the callback adds to its modelspace."""
    document = ezdxf.new("R2010")
    document.header["$INSUNITS"] = insunits
    callback(document.modelspace())
    path = tmp_path / name
    document.saveas(path)
    return path


def _line(msp, start, end, layer: str = "0") -> None:  # type: ignore[no-untyped-def]
    msp.add_line(start, end, dxfattribs={"layer": layer})


def _polyline(msp, points, *, closed: bool = False, layer: str = "0") -> None:  # type: ignore[no-untyped-def]
    entity = msp.add_lwpolyline(points, dxfattribs={"layer": layer})
    entity.closed = closed


# ──────────────────────────── entities ────────────────────────────
def test_a_line_is_one_member(tmp_path: Path) -> None:
    path = _draw(lambda msp: _line(msp, (0, 0), (6, 0)), tmp_path=tmp_path)

    drawing = read_drawing(path)
    bars = bars_from_drawing(drawing, section_id=1, plane="XY")

    assert drawing.layers == ["0"]
    assert [(node.coords) for node in bars.nodes] == [(0.0, 0.0, 0.0), (6.0, 0.0, 0.0)]
    assert [element.nodes for element in bars.elements] == [(1, 2)]
    assert bars.n_members == 1 and bars.n_nodes == 2
    assert bars.summary().startswith("1 member(s) and 2 node(s)")


def test_an_open_polyline_is_a_chain_of_members(tmp_path: Path) -> None:
    path = _draw(lambda msp: _polyline(msp, [(0, 0), (0, 4), (6, 4)]), tmp_path=tmp_path)

    bars = bars_from_drawing(read_drawing(path), section_id=1, plane="XY")

    assert bars.n_nodes == 3
    assert [element.nodes for element in bars.elements] == [(1, 2), (2, 3)]


def test_a_closed_polyline_closes_the_loop(tmp_path: Path) -> None:
    """A rectangle of bars is four members, not three."""
    path = _draw(
        lambda msp: _polyline(msp, [(0, 0), (4, 0), (4, 3), (0, 3)], closed=True),
        tmp_path=tmp_path,
    )

    bars = bars_from_drawing(read_drawing(path), section_id=1, plane="XY")

    assert bars.n_nodes == 4
    assert [element.nodes for element in bars.elements] == [(1, 2), (2, 3), (3, 4), (4, 1)]


def test_vertices_are_shared_instead_of_repeated(tmp_path: Path) -> None:
    """Drawings repeat coordinates; the model must not have two nodes there."""
    path = _draw(
        lambda msp: (
            _line(msp, (0, 0), (3, 0)),
            _line(msp, (3, 0), (3, 4)),  # the corner of the first line, written again
            _line(msp, (0.000001, 0), (0, 3)),  # a bar hung on that node, off by a micron
        ),
        tmp_path=tmp_path,
    )

    bars = bars_from_drawing(read_drawing(path), section_id=1, plane="XY")

    assert bars.n_nodes == 4  # (0,0), (3,0), (3,4), (0,3)
    assert bars.n_members == 3
    assert bars.merged_endpoints == 2  # the repeated corner and the micron
    assert "merged" in bars.summary()


def test_an_old_style_polyline_is_read_too(tmp_path: Path) -> None:
    path = _draw(lambda msp: msp.add_polyline2d([(0, 0), (2, 0), (2, 2)]), tmp_path=tmp_path)

    bars = bars_from_drawing(read_drawing(path), section_id=1, plane="XY")

    assert bars.n_members == 2 and bars.n_nodes == 3


def test_a_zero_length_segment_is_dropped_not_imported(tmp_path: Path) -> None:
    path = _draw(
        lambda msp: (
            _line(msp, (0, 0), (0, 0)),
            _line(msp, (0, 0), (5, 0)),
        ),
        tmp_path=tmp_path,
    )

    bars = bars_from_drawing(read_drawing(path), section_id=1, plane="XY")

    assert bars.n_members == 1
    assert bars.dropped_segments == 1
    assert "dropped" in bars.summary()


# ──────────────────────────── what is left out ────────────────────────────
def test_other_entities_are_counted_and_reported(tmp_path: Path) -> None:
    """A drawing that imports four members where the user drew two hundred
    has to say so."""
    path = _draw(
        lambda msp: (
            _line(msp, (0, 0), (1, 0)),
            msp.add_circle((0, 0), 1),
            msp.add_text("NOTAS", height=0.2),
            msp.add_circle((5, 5), 1),
        ),
        tmp_path=tmp_path,
    )

    drawing = read_drawing(path)

    assert drawing.skipped == {"CIRCLE": 2, "TEXT": 1}
    assert "2 CIRCLE" in drawing.skipped_summary()
    assert bars_from_drawing(drawing, section_id=1, plane="XY").n_members == 1


def test_only_the_layers_asked_for_are_read(tmp_path: Path) -> None:
    path = _draw(
        lambda msp: (
            _line(msp, (0, 0), (1, 0), layer="EJE"),
            _line(msp, (0, 1), (1, 1), layer="VIGAS"),
            _line(msp, (0, 2), (1, 2), layer="VIGAS"),
        ),
        tmp_path=tmp_path,
    )

    everything = read_drawing(path)
    only_beams = read_drawing(path, layers=["VIGAS"])

    assert everything.layers == ["EJE", "VIGAS"]
    assert only_beams.layers == ["VIGAS"]
    assert len(everything.segments) == 3 and len(only_beams.segments) == 2


def test_a_curved_polyline_segment_is_imported_as_a_chord_and_reported(tmp_path: Path) -> None:
    document = ezdxf.new("R2010")
    # The bulge of a vertex curves the segment that starts there.
    document.modelspace().add_lwpolyline([(0, 0, 0, 0, 0.5), (4, 0)])
    path = tmp_path / "arc.dxf"
    document.saveas(path)

    drawing = read_drawing(path)

    assert drawing.chorded == 1
    assert "straight chords" in drawing.skipped_summary()
    assert bars_from_drawing(drawing, section_id=1, plane="XY").n_members == 1


def test_a_drawing_with_no_bars_reads_as_empty(tmp_path: Path) -> None:
    path = _draw(lambda msp: msp.add_circle((0, 0), 1), tmp_path=tmp_path)

    drawing = read_drawing(path)

    assert drawing.is_empty
    assert bars_from_drawing(drawing, section_id=1, plane="XY").n_members == 0


# ──────────────────────────── units ────────────────────────────
def test_the_file_says_what_it_is_in(tmp_path: Path) -> None:
    path = _draw(lambda msp: _line(msp, (0, 0), (1000, 0)), insunits=4, tmp_path=tmp_path)

    drawing = read_drawing(path)

    assert drawing.unit_name == "millimetres"
    assert unit_scale(drawing, UnitSystem.SI_M_N) == pytest.approx(1e-3)
    assert unit_scale(drawing, UnitSystem.SI_MM_N) == pytest.approx(1.0)

    bars = bars_from_drawing(drawing, section_id=1, plane="XY", scale=1e-3)
    assert bars.nodes[1].coords == (1.0, 0.0, 0.0)  # 1000 mm is one metre


def test_an_inch_drawing_lands_in_metres(tmp_path: Path) -> None:
    path = _draw(lambda msp: _line(msp, (0, 0), (12, 0)), insunits=1, tmp_path=tmp_path)

    drawing = read_drawing(path)

    assert unit_scale(drawing, UnitSystem.SI_M_N) == pytest.approx(0.0254)
    bars = bars_from_drawing(drawing, section_id=1, plane="XY", scale=0.0254)
    assert bars.nodes[1].coords[0] == pytest.approx(0.3048)  # a foot of inches


def test_a_unitless_drawing_is_taken_as_it_is(tmp_path: Path) -> None:
    path = _draw(lambda msp: _line(msp, (0, 0), (5, 0)), insunits=0, tmp_path=tmp_path)

    drawing = read_drawing(path)

    assert drawing.unit_name == "unitless"
    assert drawing.unit_in_metres is None
    assert unit_scale(drawing, UnitSystem.SI_M_N) == 1.0  # nothing is converted behind the user


def test_an_unknown_unit_code_is_reported_not_guessed(tmp_path: Path) -> None:
    path = _draw(lambda msp: _line(msp, (0, 0), (5, 0)), insunits=99, tmp_path=tmp_path)

    drawing = read_drawing(path)

    assert drawing.unit_name == "code 99"
    assert unit_scale(drawing, UnitSystem.SI_M_N) == 1.0


# ──────────────────────────── where it lands ────────────────────────────
def test_the_drawing_can_be_read_as_an_elevation(tmp_path: Path) -> None:
    """Drawn flat, wanted as a portal frame elevation: x/y become x/z."""
    path = _draw(lambda msp: _polyline(msp, [(0, 0), (0, 4), (6, 4)]), tmp_path=tmp_path)

    bars = bars_from_drawing(read_drawing(path), section_id=1, plane="XZ")

    assert [node.coords for node in bars.nodes] == [
        (0.0, 0.0, 0.0),
        (0.0, 0.0, 4.0),
        (6.0, 0.0, 4.0),
    ]


def test_the_plane_can_be_lifted_and_shifted(tmp_path: Path) -> None:
    path = _draw(lambda msp: _line(msp, (0, 0), (6, 0)), tmp_path=tmp_path)

    bars = bars_from_drawing(
        read_drawing(path),
        section_id=1,
        plane="XZ",
        level=3.0,
        origin=(10.0, 2.0, 1.0),
    )

    # x and z from the drawing shifted by the origin, y at the origin's own y
    # plus the level.
    assert [node.coords for node in bars.nodes] == [(10.0, 5.0, 1.0), (16.0, 5.0, 1.0)]


def test_a_3d_drawing_keeps_its_own_coordinates(tmp_path: Path) -> None:
    path = _draw(
        lambda msp: _line(msp, (1, 2, 3), (4, 2, 3)),
        tmp_path=tmp_path,
    )

    bars = bars_from_drawing(read_drawing(path), section_id=1, plane="3D")

    assert [node.coords for node in bars.nodes] == [(1.0, 2.0, 3.0), (4.0, 2.0, 3.0)]


def test_an_unknown_plane_is_refused(tmp_path: Path) -> None:
    path = _draw(lambda msp: _line(msp, (0, 0), (1, 0)), tmp_path=tmp_path)

    with pytest.raises(DxfImportError, match="Unknown plane"):
        bars_from_drawing(read_drawing(path), section_id=1, plane="XY-plane")


def test_ids_continue_from_where_the_project_left_off(tmp_path: Path) -> None:
    path = _draw(lambda msp: _line(msp, (0, 0), (1, 0)), tmp_path=tmp_path)

    bars = bars_from_drawing(
        read_drawing(path), section_id=7, first_node_id=100, first_element_id=250
    )

    assert [node.id for node in bars.nodes] == [100, 101]
    assert [element.id for element in bars.elements] == [250]
    assert bars.elements[0].section_id == 7
    assert all(not any(node.restraint) for node in bars.nodes)  # no invented supports


def test_the_merge_tolerance_follows_the_drawing_size(tmp_path: Path) -> None:
    metres = _draw(lambda msp: _line(msp, (0, 0), (100, 0)), name="m.dxf", tmp_path=tmp_path)
    millimetres = _draw(
        lambda msp: _line(msp, (0, 0), (100_000, 0)),
        insunits=4,
        name="mm.dxf",
        tmp_path=tmp_path,
    )

    assert merge_tolerance(read_drawing(metres)) == pytest.approx(1e-4)
    assert merge_tolerance(read_drawing(millimetres)) == pytest.approx(0.1)
    assert merge_tolerance(read_drawing(metres), relative=1e-3) == pytest.approx(0.1)


# ──────────────────────────── failures ────────────────────────────
def test_a_missing_file_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(DxfImportError, match="No such file"):
        read_drawing(tmp_path / "nope.dxf")


def test_a_file_that_is_not_a_dxf_is_an_error(tmp_path: Path) -> None:
    path = tmp_path / "notes.dxf"
    path.write_text("this is not a drawing\n" * 20, encoding="utf-8")

    with pytest.raises(DxfImportError, match="not a readable DXF"):
        read_drawing(path)
