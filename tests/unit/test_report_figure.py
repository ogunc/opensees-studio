"""The cover drawing: an isometric (3D) or elevation (2D) SVG of the structure."""

from __future__ import annotations

import base64
import re
from pathlib import Path

from opensees_studio.core import Project
from opensees_studio.services.persistence import load_project
from opensees_studio.services.report_figure import model_svg, svg_data_uri

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"


def _numbers(svg: str, attr: str) -> list[float]:
    return [float(v) for v in re.findall(rf'{attr}="([-0-9.]+)"', svg)]


def test_a_3d_frame_is_drawn_inside_the_picture() -> None:
    project = load_project(EXAMPLES / "building_3storey_diaphragm.osmodel")
    svg = model_svg(project, width=400, height=300)
    assert svg is not None and svg.startswith("<svg") and svg.endswith("</svg>")
    assert svg.count("<line ") == len(project.elements)
    supports = sum(1 for n in project.nodes if any(n.restraint))
    assert svg.count('fill="#b0402a"') == supports
    xs = _numbers(svg, "x1") + _numbers(svg, "x2")
    ys = _numbers(svg, "y1") + _numbers(svg, "y2")
    assert min(xs) >= 0 and max(xs) <= 400 and min(ys) >= 0 and max(ys) <= 300


def test_a_2d_model_is_drawn_in_elevation_with_its_areas() -> None:
    project = load_project(EXAMPLES / "beam_quad_2d.osmodel")
    svg = model_svg(project)
    assert svg is not None
    assert svg.count('fill="#dde5ee"') == sum(1 for e in project.elements if len(e.nodes) == 4)


def test_nothing_to_draw_without_elements() -> None:
    assert model_svg(Project()) is None


def test_data_uri_round_trips() -> None:
    uri = svg_data_uri("<svg/>")
    assert base64.b64decode(uri.split(",", 1)[1]) == b"<svg/>"
