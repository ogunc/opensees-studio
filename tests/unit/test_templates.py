"""File → New Model: the beam and 3D frame templates."""

from __future__ import annotations

import pytest

from opensees_studio.core.templates import (
    TEMPLATE_NDF,
    TEMPLATES,
    TemplateError,
    build_beam,
    build_space_frame,
)


def test_every_template_has_a_model_type() -> None:
    assert set(TEMPLATES) == set(TEMPLATE_NDF)


def test_a_continuous_beam_sits_on_a_pin_and_rollers() -> None:
    beam = build_beam(3, 5.0, section_id=2)
    assert [n.coords for n in beam.nodes] == [
        (0.0, 0.0, 0.0),
        (5.0, 0.0, 0.0),
        (10.0, 0.0, 0.0),
        (15.0, 0.0, 0.0),
    ]
    assert beam.nodes[0].restraint == (True, False, True, False, False, False)
    assert all(n.restraint == (False, False, True, False, False, False) for n in beam.nodes[1:])
    assert [e.nodes for e in beam.elements] == [(1, 2), (2, 3), (3, 4)]
    assert {e.section_id for e in beam.elements} == {2}
    assert [line.ordinate for line in beam.grid.grid.x_grid_lines] == [0.0, 5.0, 10.0, 15.0]


def test_a_3d_frame_has_columns_and_beams_both_ways_on_every_floor() -> None:
    frame = build_space_frame(
        2, 1, 3, 6.0, 5.0, 3.0, column_section_id=1, beam_section_id=2, first_node_id=10
    )
    assert len(frame.nodes) == 3 * 2 * 4
    columns = [e for e in frame.elements if e.section_id == 1]
    beams = [e for e in frame.elements if e.section_id == 2]
    assert len(columns) == 6 * 3
    assert len(beams) == (2 * 2 + 3 * 1) * 3
    bases = [n for n in frame.nodes if n.coords[2] == 0.0]
    assert len(bases) == 6 and all(all(n.restraint) for n in bases)
    assert not any(any(n.restraint) for n in frame.nodes if n.coords[2] > 0.0)
    assert frame.nodes[0].id == 10
    assert [line.ordinate for line in frame.grid.grid.z_grid_lines] == [0.0, 3.0, 6.0, 9.0]


@pytest.mark.parametrize(
    "build",
    [
        lambda: build_beam(0, 5.0, section_id=1),
        lambda: build_beam(2, 0.0, section_id=1),
        lambda: build_space_frame(1, 0, 1, 5.0, 5.0, 3.0, column_section_id=1, beam_section_id=1),
        lambda: build_space_frame(1, 1, 1, 5.0, -5.0, 3.0, column_section_id=1, beam_section_id=1),
    ],
)
def test_impossible_numbers_are_refused(build) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(TemplateError):
        build()
