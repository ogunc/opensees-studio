"""Reading a cross-section from a DXF drawing: outlines, holes by nesting, units."""

from __future__ import annotations

import math
from pathlib import Path

import ezdxf
import pytest

from opensees_studio.core.sections.geometry import CircleRegion, section_properties
from opensees_studio.core.units import UnitSystem
from opensees_studio.services.dxf_import import DxfImportError
from opensees_studio.services.section_dxf import drawing_scale, read_section_drawing, scaled


def _drawing(tmp_path: Path, insunits: int = 4) -> Path:
    doc = ezdxf.new()
    doc.header["$INSUNITS"] = insunits
    msp = doc.modelspace()
    msp.add_lwpolyline([(-150, -250), (150, -250), (150, 250), (-150, 250)], close=True)
    msp.add_circle((0, 100), 50)  # a hole
    msp.add_circle((0, 100), 20)  # a solid inside the hole
    msp.add_lwpolyline([(-100, -200), (100, -200), (100, -100), (-100, -100)], close=True)
    msp.add_lwpolyline([(400, 0), (500, 0), (500, 100)])  # open: left out
    msp.add_line((0, 0), (1, 1))
    msp.add_text("label")
    path = tmp_path / "section.dxf"
    doc.saveas(path)
    return path


def test_outlines_holes_and_skips(tmp_path: Path) -> None:
    drawing = read_section_drawing(_drawing(tmp_path))
    holes = [r.hole for r in drawing.regions]
    assert holes == [False, True, False, True]
    assert drawing.open_outlines == 1
    assert drawing.skipped == {"LINE": 1, "TEXT": 1}
    assert drawing.unit_name == "millimetres"
    assert "2 outline(s) and 2 hole(s)" in drawing.summary()


def test_drawing_x_is_local_z(tmp_path: Path) -> None:
    drawing = read_section_drawing(_drawing(tmp_path))
    circle = drawing.regions[1]
    assert isinstance(circle, CircleRegion)
    assert (circle.y, circle.z) == (100.0, 0.0)


def test_scaled_to_the_project_units(tmp_path: Path) -> None:
    drawing = read_section_drawing(_drawing(tmp_path))
    factor = drawing_scale(drawing, UnitSystem.SI_M_N)
    assert factor == pytest.approx(1e-3)
    props = section_properties(scaled(drawing.regions, factor))
    expected = 0.3 * 0.5 - math.pi * 0.05**2 + math.pi * 0.02**2 - 0.2 * 0.1
    assert pytest.approx(expected) == props.A
    assert drawing_scale(drawing, UnitSystem.SI_MM_N) == pytest.approx(1.0)


def test_unitless_file_scales_by_one(tmp_path: Path) -> None:
    drawing = read_section_drawing(_drawing(tmp_path, insunits=0))
    assert drawing.unit_in_metres is None
    assert drawing_scale(drawing, UnitSystem.SI_M_N) == 1.0


def test_bulges_are_arcs(tmp_path: Path) -> None:
    doc = ezdxf.new()
    doc.modelspace().add_lwpolyline(
        [(0, 0, 0, 0, 1), (100, 0, 0, 0, 1)], format="xyseb", close=True
    )
    path = tmp_path / "round.dxf"
    doc.saveas(path)
    props = section_properties(read_section_drawing(path).regions)
    assert pytest.approx(math.pi * 50**2, rel=1e-3) == props.A


def test_missing_or_broken_files(tmp_path: Path) -> None:
    with pytest.raises(DxfImportError):
        read_section_drawing(tmp_path / "nope.dxf")
    broken = tmp_path / "broken.dxf"
    broken.write_text("not a dxf")
    with pytest.raises(DxfImportError):
        read_section_drawing(broken)
